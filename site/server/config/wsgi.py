"""WSGI entrypoint for Gunicorn / production deployment (fails closed by default)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_PATH = Path(__file__).resolve().parent.parent
server_dir = str(SERVER_PATH)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from config.env import bootstrap_env  # noqa: E402

bootstrap_env(default_debug="false")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

_django_application = get_wsgi_application()
_MAINT_HEADERS = [
    ("Content-Type", "application/json"),
    ("Cache-Control", "private, no-store, no-cache, must-revalidate"),
    ("X-Content-Type-Options", "nosniff"),
]


def _resolve_maintenance_file(environ: dict[str, object]) -> Path | None:
    override = environ.get("WANGJINGHONG_MAINTENANCE_FILE") or os.environ.get(
        "WANGJINGHONG_MAINTENANCE_FILE"
    )
    if isinstance(override, str) and override.strip():
        return Path(override.strip())
    # Default release layout: <app_root>/releases/<release_id>/server/config/wsgi.py
    if SERVER_PATH.parent.parent.name == "releases":
        return SERVER_PATH.parent.parent.parent / "shared" / ".maintenance"
    return None


def application(environ, start_response):
    maint_file = _resolve_maintenance_file(environ)
    if maint_file is not None and maint_file.is_file():
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if not (
            environ.get("PATH_INFO") == "/api/health/"
            and method in {"GET", "HEAD"}
        ):
            start_response("503 Service Unavailable", list(_MAINT_HEADERS))
            return [b""] if method == "HEAD" else [b'{"status": "maintenance"}']
    return _django_application(environ, start_response)
