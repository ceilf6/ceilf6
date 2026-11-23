"""Environment bootstrap with precedence: process env > .env > entrypoint default."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent


def load_dotenv_file(
    dotenv_path: Path, target_env: MutableMapping[str, str]
) -> None:
    """Load simple KEY=VALUE pairs from .env without overriding existing env vars."""
    if not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = raw_value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        target_env.setdefault(key, value)


def bootstrap_env(
    *,
    default_debug: str,
    environ: MutableMapping[str, str] | None = None,
    base_dir: Path = SERVER_DIR,
) -> None:
    """Load .env before applying the entrypoint's fallback DJANGO_DEBUG value."""
    target = os.environ if environ is None else environ
    dotenv_override = target.get("DJANGO_DOTENV_PATH", "").strip()
    dotenv_path = (
        Path(dotenv_override) if dotenv_override else (base_dir / ".env")
    )
    load_dotenv_file(dotenv_path, target)
    target.setdefault("DJANGO_DEBUG", default_debug)
