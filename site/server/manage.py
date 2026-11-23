#!/usr/bin/env python3
"""Django's command-line utility for local administrative and dev tasks."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    """Run administrative tasks (defaults to zero-config local dev mode)."""
    server_dir = str(Path(__file__).resolve().parent)
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)

    os.environ.setdefault("DJANGO_DEBUG", "true")
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        os.environ.setdefault("SQLITE_PATH", ":memory:")
        os.environ.setdefault(
            "DJANGO_EMAIL_BACKEND",
            "django.core.mail.backends.locmem.EmailBackend",
        )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
