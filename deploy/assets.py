"""Public asset contract shared by site builds, publishing, and smoke checks.

The four README cards and the favicon are updated by scheduled jobs, so they are
loaded at runtime from /assets/ instead of being bundled by Vite. This module is
the single place that decides what "complete and reachable" means.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

REQUIRED = {
    "github-stats-card.svg": "image/svg+xml",
    "blog-card.svg": "image/svg+xml",
    "vlog-card.svg": "image/svg+xml",
    "huggingface-card.svg": "image/svg+xml",
    "Profile.jpg": "image/jpeg",
}


class AssetError(Exception):
    """The asset contract was not met."""


def _svg_problem(path: Path) -> str | None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        return f"invalid SVG ({error})"
    if not root.tag.endswith("svg"):
        return f"root element is <{root.tag}>, not <svg>"
    return None


def validate(source: Path | str, *, require_all: bool = True) -> None:
    """Raise AssetError listing every missing, empty, or malformed SVG.

    With require_all=False only the files present are checked; callers use this
    for partial uploads and validate the merged public directory afterwards.
    """
    source = Path(source)
    if require_all:
        targets = {name: True for name in REQUIRED}
    else:
        targets = {
            path.name: path.name in REQUIRED
            for path in source.iterdir()
            if path.is_file()
        }
    problems = []
    for name, required in targets.items():
        path = source / name
        if not path.is_file():
            problems.append(f"{name}: missing from {source}")
            continue
        if path.stat().st_size == 0:
            problems.append(f"{name}: empty" + ("" if required else " (unexpected file)"))
            continue
        if name.endswith(".svg"):
            problem = _svg_problem(path)
            if problem:
                problems.append(f"{name}: {problem}")
    if problems:
        raise AssetError("\n".join(problems))


def bundle(source: Path | str, dest: Path | str) -> None:
    """Validate source assets, then copy the whole tree into a public directory."""
    source, dest = Path(source), Path(dest)
    validate(source)
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o755)
    for entry in sorted(source.iterdir()):
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
            os.chmod(target, 0o755)
        else:
            shutil.copyfile(entry, target)
            os.chmod(target, 0o644)


def smoke(
    base_url: str,
    *,
    required: dict[str, str] | None = None,
    resolve: str | None = None,
    timeout: int = 20,
) -> list[tuple[str, str, str]]:
    """Check each required asset over HTTP; raise AssetError with every failure.

    `resolve` maps a hostname to an address for origin checks (curl --resolve).
    """
    required = REQUIRED if required is None else required
    base = base_url.rstrip("/")
    results = []
    problems = []
    with tempfile.TemporaryDirectory(prefix="asset-smoke-") as scratch:
        for name, expected in required.items():
            url = f"{base}/assets/{quote(name)}"
            body = Path(scratch) / "body"
            command = [
                "curl",
                "--noproxy",
                "*",
                "-sS",
                "-L",
                "--max-time",
                str(timeout),
                "-o",
                str(body),
                "-w",
                "%{http_code}\n%{content_type}",
            ]
            if resolve:
                command += ["--resolve", resolve]
            command.append(url)
            probe = subprocess.run(command, capture_output=True, text=True)
            if probe.returncode != 0:
                problems.append(f"{name}: request failed ({probe.stderr.strip()})")
                continue
            status, _, content_type = probe.stdout.strip().partition("\n")
            content_type = content_type.split(";", 1)[0].strip().lower()
            results.append((name, status, content_type))
            if status != "200":
                problems.append(f"{name}: HTTP {status} at {url}")
                continue
            if content_type != expected:
                problems.append(f"{name}: content-type {content_type}, expected {expected}")
                continue
            if body.stat().st_size == 0:
                problems.append(f"{name}: empty response body")
                continue
            if name.endswith(".svg"):
                problem = _svg_problem(body)
                if problem:
                    problems.append(f"{name}: {problem}")
    if problems:
        raise AssetError("\n".join(problems))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser("validate", help="check the source asset tree")
    validate_parser.add_argument("source", type=Path)

    bundle_parser = commands.add_parser("bundle", help="validate and copy assets into a build")
    bundle_parser.add_argument("source", type=Path)
    bundle_parser.add_argument("dest", type=Path)

    smoke_parser = commands.add_parser("smoke", help="check published assets over HTTP")
    smoke_parser.add_argument("--base", required=True)
    smoke_parser.add_argument("--resolve", help="HOST:PORT:ADDRESS for origin checks")
    smoke_parser.add_argument("--timeout", type=int, default=20)

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            validate(args.source)
            print(f"assets ok: {args.source}")
        elif args.command == "bundle":
            bundle(args.source, args.dest)
            print(f"bundled {len(list(args.source.iterdir()))} files into {args.dest}")
        else:
            for name, status, content_type in smoke(
                args.base, resolve=args.resolve, timeout=args.timeout
            ):
                print(f"{status} {content_type} {name}")
    except AssetError as error:
        print(f"asset check failed:\n{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
