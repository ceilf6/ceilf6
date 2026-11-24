"""Local sandbox harness with real WSGI server and fake systemctl stub."""

from __future__ import annotations

import hashlib
import http.cookies
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TESTS_DIR = Path(__file__).resolve().parent
DEPLOY_DIR = TESTS_DIR.parent
SITE_DIR = DEPLOY_DIR.parent
SERVER_SRC_DIR = SITE_DIR / "server"
SITE_VENV_DIR = SITE_DIR / ".venv"

_WSGI_DAEMON_CODE = r"""#!/usr/bin/env python3
from __future__ import annotations
import signal, socketserver, sys, threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

port = int(sys.argv[1])
app_root = Path(sys.argv[2])
cwd = str(Path.cwd().resolve())
if cwd not in sys.path:
    sys.path.insert(0, cwd)

from config.wsgi import application
from django.db import connections

class ThreadedWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    allow_reuse_address = True
    daemon_threads = True

class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        pass

httpd = make_server("127.0.0.1", port, application, server_class=ThreadedWSGIServer, handler_class=QuietHandler)

def _shutdown(signum, frame):
    threading.Thread(target=httpd.shutdown, daemon=True).start()

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)
try:
    httpd.serve_forever(poll_interval=0.05)
finally:
    httpd.server_close()
    connections.close_all()
"""

_FAKE_SYSTEMCTL_TEMPLATE = r"""#!/usr/bin/env python3
from __future__ import annotations
import os, signal, socket, subprocess, sys, time
from pathlib import Path

SANDBOX = Path({sandbox!r})
APP_ROOT = Path({app_root!r})
ETC_ENV = Path({etc_env!r})
VAR_DIR = Path({var_dir!r})
PORT = {port!r}
PID_FILE = SANDBOX / "service.pid"
LOG_FILE = SANDBOX / "systemctl.log"
DAEMON_PY = SANDBOX / "bin" / "wsgi_daemon.py"

action = sys.argv[1] if len(sys.argv) > 1 else ""
svc = sys.argv[2] if len(sys.argv) > 2 else ""
with LOG_FILE.open("a", encoding="utf-8") as fh:
    fh.write(f"{{action}} {{svc}}\n")

def _stop() -> None:
    if not PID_FILE.is_file():
        return
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(60):
            time.sleep(0.05)
            os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    PID_FILE.unlink(missing_ok=True)

def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {{}}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in {{"'", '"'}}:
            v = v[1:-1]
        if k:
            out[k] = v
    return out

if action == "stop":
    if (SANDBOX / "fail_stop").exists():
        sys.stderr.write("simulated systemctl stop failure\n")
        raise SystemExit(1)
    _stop()
    raise SystemExit(0)

if action in {{"start", "restart"}}:
    _stop()
    fail_once = SANDBOX / "fail_next_restart"
    if fail_once.exists():
        fail_once.unlink()
        sys.stderr.write("simulated systemctl restart failure\n")
        raise SystemExit(1)
    server_cwd = APP_ROOT / "current" / "server"
    venv_py = APP_ROOT / "shared" / "venv" / "bin" / "python"
    if not server_cwd.is_dir() or not venv_py.exists():
        sys.stderr.write("missing current/server or shared/venv\n")
        raise SystemExit(1)
    env = os.environ.copy()
    env.update({{
        "DJANGO_DOTENV_PATH": "/dev/null",
        "DJANGO_DEBUG": "false",
        "WANGJINGHONG_MAINTENANCE_FILE": str(APP_ROOT / "shared" / ".maintenance"),
        "SQLITE_PATH": str(VAR_DIR / "db.sqlite3"),
        "DJANGO_CACHE_PATH": str(VAR_DIR / "cache"),
        "EMAIL_FILE_PATH": str(VAR_DIR / "mail"),
    }})
    env.update(_parse_env(ETC_ENV))
    env["DJANGO_DOTENV_PATH"] = "/dev/null"
    err_log = (SANDBOX / "wsgi.stderr.log").open("ab")
    proc = subprocess.Popen(
        [str(venv_py), str(DAEMON_PY), str(PORT), str(APP_ROOT)],
        cwd=str(server_cwd.resolve()),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=err_log,
        start_new_session=True,
    )
    PID_FILE.write_text(f"{{proc.pid}}\n", encoding="utf-8")
    for _ in range(100):
        if proc.poll() is not None:
            sys.stderr.write("wsgi daemon exited immediately on startup\n")
            raise SystemExit(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.05)
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                raise SystemExit(0)
        time.sleep(0.05)
    raise SystemExit(0)

raise SystemExit(2)
"""


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DeploySandbox:
    """Isolated filesystem + real local WSGI daemon simulating ECS production layout."""

    def __init__(self, *, env_mode: int = 0o600) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="site-server-deploy-sbx-"))
        self.app_root = self.root / "opt" / "wangjinghong"
        self.etc_env = self.root / "etc" / "wangjinghong" / "server.env"
        self.var_dir = self.root / "var" / "lib" / "wangjinghong"
        self.lock_file = self.root / "var" / "lock" / "wangjinghong-server-deploy.lock"
        self.fake_var_www = self.root / "fake_var_www"
        self.staging_root = self.root / "staging"
        self.bin_dir = self.root / "bin"

        venvs_dir = self.app_root / "shared" / "venvs"
        for d in (venvs_dir, self.etc_env.parent, self.fake_var_www, self.staging_root, self.bin_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.venv_source = SITE_VENV_DIR.resolve() if SITE_VENV_DIR.exists() else Path(sys.executable).resolve().parents[1]
        base_req_sha = hashlib.sha256((SERVER_SRC_DIR / "requirements.txt").read_bytes()).hexdigest()[:16]
        default_venv_slot = venvs_dir / base_req_sha
        os.symlink(str(self.venv_source), str(default_venv_slot))
        os.symlink(str(default_venv_slot), str(self.app_root / "shared" / "venv"))

        self.sentinel_file = self.fake_var_www / "index.html"
        self.sentinel_content = "<!doctype html><title>wangjinghong-static-sentinel</title>\n"
        self.sentinel_file.write_text(self.sentinel_content, encoding="utf-8")
        self.sentinel_mtime_ns = self.sentinel_file.stat().st_mtime_ns

        self.port = pick_free_port()
        self.health_url = f"http://127.0.0.1:{self.port}/api/health/"
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.secret_key = secrets.token_urlsafe(48)
        self.write_env_file(mode=env_mode)

        daemon_py = self.bin_dir / "wsgi_daemon.py"
        daemon_py.write_text(_WSGI_DAEMON_CODE, encoding="utf-8")
        daemon_py.chmod(0o755)

        self.systemctl_bin = self.bin_dir / "fake-systemctl"
        self.systemctl_bin.write_text(
            _FAKE_SYSTEMCTL_TEMPLATE.format(
                sandbox=str(self.root),
                app_root=str(self.app_root),
                etc_env=str(self.etc_env),
                var_dir=str(self.var_dir),
                port=self.port,
            ),
            encoding="utf-8",
        )
        self.systemctl_bin.chmod(0o755)

    def write_env_file(self, *, mode: int = 0o600) -> None:
        body = (
            "# Sandbox production server.env (systemd EnvironmentFile syntax)\n"
            f"DJANGO_SECRET_KEY={self.secret_key}\n"
            "DJANGO_DEBUG=false\n"
            'DJANGO_ALLOWED_HOSTS="www.wangjinghong.com,127.0.0.1,localhost"\n'
            "DJANGO_TRUSTED_PROXY_COUNT=1\n"
            "DJANGO_ADMIN_PATH=ops-console/\n"
            f"SQLITE_PATH={self.var_dir / 'db.sqlite3'}\n"
            f"DJANGO_CACHE_PATH={self.var_dir / 'cache'}\n"
            "DJANGO_EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend\n"
            f"EMAIL_FILE_PATH={self.var_dir / 'mail'}\n"
            "ALLOW_GUEST_COMMENTS=true\n"
        )
        self.etc_env.write_text(body, encoding="utf-8")
        os.chmod(self.etc_env, mode)

    def clone_staged_server(self, label: str) -> Path:
        dst = self.staging_root / label
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(
            SERVER_SRC_DIR,
            dst,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "var", "staticfiles", ".env", ".venv", "*.sqlite3*"),
        )
        return dst

    def http_request(
        self,
        path: str,
        *,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {
            "Host": "www.wangjinghong.com",
            "X-Forwarded-Proto": "https",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with opener.open(req, timeout=3.0) as resp:
                raw = resp.read().decode("utf-8")
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                hdrs["set-cookie-all"] = "\n".join(resp.headers.get_all("Set-Cookie") or [])
                return resp.status, hdrs, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                hdrs = {k.lower(): v for k, v in exc.headers.items()}
            finally:
                exc.close()
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = raw
            return exc.code, hdrs, parsed

    def post_guest_comment(self, slug: str, body: str, *, client_ipv6: str = "2001:db8::1") -> dict[str, Any]:
        status, hdrs, me_data = self.http_request("/api/me/")
        assert status == 200, f"GET /api/me/ returned {status}: {me_data}"
        jar = http.cookies.SimpleCookie()
        for line in hdrs.get("set-cookie-all", "").splitlines():
            if line.strip():
                jar.load(line)
        csrf_cookie = jar["csrftoken"].value
        create_status, _, payload = self.http_request(
            f"/api/notes/{slug}/comments/",
            method="POST",
            json_body={"body": body, "expectedAuthorKind": "guest"},
            extra_headers={
                "Origin": "https://www.wangjinghong.com",
                "X-CSRFToken": me_data["csrfToken"],
                "Cookie": f"csrftoken={csrf_cookie}",
                "X-Forwarded-For": client_ipv6,
            },
        )
        assert create_status == 201, f"POST comment failed ({create_status}): {payload}"
        return payload

    def close(self) -> None:
        (self.root / "fail_stop").unlink(missing_ok=True)
        subprocess.run([str(self.systemctl_bin), "stop", "wangjinghong-api"], capture_output=True)
        pid_file = self.root / "service.pid"
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8").strip()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
        shutil.rmtree(self.root, ignore_errors=True)
