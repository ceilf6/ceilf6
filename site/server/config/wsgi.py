"""WSGI entrypoint for Gunicorn / production deployment (fails closed by default)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

server_dir = str(Path(__file__).resolve().parent.parent)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

os.environ.setdefault("DJANGO_DEBUG", "false")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
