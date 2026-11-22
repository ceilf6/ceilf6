"""Locked, staged publication of website releases and runtime assets.

Full-site releases and scheduled asset uploads share one lock. Both make every
public file readable by the web server before the switch, and both probe the
origin while still holding the lock. A failed full-site release restores the
previous tree; a failed asset upload restores the files it replaced.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import assets

DEFAULT_LOCK = Path("/var/lock/wangjinghong-deploy.lock")
DIR_MODE = 0o755
FILE_MODE = 0o644


@contextmanager
def _locked(lock_path: Path | str):
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _public_modes(root: Path | str) -> None:
    root = Path(root)
    for path in sorted(root.rglob("*")):
        os.chmod(path, DIR_MODE if path.is_dir() else FILE_MODE)
    os.chmod(root, DIR_MODE)


def _assert_readable(root: Path | str, reader_user: str | None, names) -> None:
    if not reader_user:
        return
    root = Path(root)
    problems = []
    for name in names:
        probe = subprocess.run(
            ["runuser", "-u", reader_user, "--", "test", "-r", str(root / name)],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            detail = probe.stderr.strip() or "permission denied"
            problems.append(f"{name}: not readable by {reader_user} ({detail})")
    if problems:
        raise assets.AssetError("\n".join(problems))


def _copy_missing(source: str, target: str) -> str:
    if not Path(target).exists():
        shutil.copy2(source, target)
    return target


def _preserve(source: Path, target: Path) -> None:
    """Keep runtime files that the site build does not produce (old chunks, harness)."""
    if not source.exists():
        return
    if not target.exists():
        shutil.copytree(source, target, copy_function=_copy_missing)
    else:
        shutil.copytree(source, target, dirs_exist_ok=True, copy_function=_copy_missing)


def publish_site(
    staging: Path | str,
    live: Path | str,
    *,
    lock_path: Path | str = DEFAULT_LOCK,
    reader_user: str | None = None,
    origin_check=None,
) -> None:
    staging, live = Path(staging), Path(live)
    previous = live.with_name(live.name + ".old")
    if not (staging / "index.html").is_file():
        raise assets.AssetError(f"index.html missing from {staging}")
    assets.validate(staging / "assets")
    _public_modes(staging)
    with _locked(lock_path):
        _assert_readable(staging, reader_user, ["index.html"])
        _assert_readable(staging / "assets", reader_user, assets.REQUIRED)
        _preserve(live / "static", staging / "static")
        _preserve(live / "harness", staging / "harness")
        if previous.exists():
            shutil.rmtree(previous)
        if live.exists():
            live.rename(previous)
        try:
            staging.rename(live)
            if origin_check:
                origin_check()
        except BaseException:
            if live.exists():
                shutil.rmtree(live)
            if previous.exists():
                previous.rename(live)
            raise


def publish_assets(
    staging: Path | str,
    live: Path | str,
    *,
    lock_path: Path | str = DEFAULT_LOCK,
    reader_user: str | None = None,
    origin_check=None,
) -> None:
    staging, live = Path(staging), Path(live)
    assets.validate(staging, require_all=False)
    _public_modes(staging)
    with _locked(lock_path):
        _assert_readable(staging, reader_user, assets.REQUIRED)
        published = live / "assets"
        published.mkdir(parents=True, exist_ok=True)
        os.chmod(published, DIR_MODE)
        backup = Path(tempfile.mkdtemp(prefix=".assets-backup-", dir=live))
        replaced: dict[str, Path] = {}
        added: list[Path] = []
        temporary: list[Path] = []
        try:
            for source in sorted(staging.iterdir()):
                if not source.is_file():
                    continue
                target = published / source.name
                if target.exists():
                    saved = backup / source.name
                    shutil.copy2(target, saved)
                    replaced[source.name] = saved
                else:
                    added.append(target)
                pending = published / f".{source.name}.publish"
                temporary.append(pending)
                shutil.copyfile(source, pending)
                os.chmod(pending, FILE_MODE)
                os.replace(pending, target)
            assets.validate(published)
            _assert_readable(published, reader_user, assets.REQUIRED)
            if origin_check:
                origin_check()
        except BaseException:
            for leftover in temporary:
                if leftover.exists():
                    leftover.unlink()
            for target in added:
                if target.exists():
                    target.unlink()
            for name, saved in replaced.items():
                pending = published / f".{name}.restore"
                shutil.copyfile(saved, pending)
                os.chmod(pending, FILE_MODE)
                os.replace(pending, published / name)
            raise
        finally:
            shutil.rmtree(backup, ignore_errors=True)


def _origin_check(url: str, resolve: str | None):
    def check() -> None:
        assets.smoke(url, resolve=resolve)
        command = [
            "curl",
            "--noproxy",
            "*",
            "-sS",
            "-L",
            "--max-time",
            "20",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "-H",
            "Accept: text/html",
        ]
        if resolve:
            command += ["--resolve", resolve]
        command.append(url.rstrip("/") + "/")
        probe = subprocess.run(command, capture_output=True, text=True)
        status = probe.stdout.strip()
        if probe.returncode != 0 or status != "200":
            detail = status or probe.stderr.strip() or f"curl exit {probe.returncode}"
            raise assets.AssetError(f"homepage {url}: HTTP {detail}")

    return check


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("site", "switch a full site release"), ("assets", "replace runtime assets")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--staging", required=True, type=Path)
        command.add_argument("--live", required=True, type=Path)
        command.add_argument("--lock", default=DEFAULT_LOCK, type=Path)
        command.add_argument("--reader", help="web-server user that must be able to read files")
        command.add_argument("--origin", help="origin URL to probe before declaring success")
        command.add_argument("--resolve", help="HOST:PORT:ADDRESS used for the origin probe")

    args = parser.parse_args(argv)
    publish = publish_site if args.command == "site" else publish_assets
    if args.origin and args.command == "site":
        check = _origin_check(args.origin, args.resolve)
    elif args.origin:
        check = lambda: assets.smoke(args.origin, resolve=args.resolve)
    else:
        check = None
    try:
        publish(
            args.staging,
            args.live,
            lock_path=args.lock,
            reader_user=args.reader,
            origin_check=check,
        )
    except assets.AssetError as error:
        print(f"publication failed:\n{error}", file=sys.stderr)
        return 1
    print(f"published {args.command} to {args.live}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
