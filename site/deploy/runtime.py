"""Environment validation, privilege setup, content-addressed venvs, and health probing."""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

if not __package__:
    _SELF_DIR = str(Path(__file__).resolve().parent)
    if _SELF_DIR not in sys.path:
        sys.path.insert(0, _SELF_DIR)
    import fs_safe as _fs  # type: ignore[import-not-found]
else:
    from . import fs_safe as _fs

DEFAULT_APP_ROOT = Path("/opt/wangjinghong")
DEFAULT_ETC_ENV = Path("/etc/wangjinghong/server.env")
DEFAULT_VAR_DIR = Path("/var/lib/wangjinghong")
DEFAULT_LOCK_FILE = Path("/var/lock/wangjinghong-server-deploy.lock")
DEFAULT_STATIC_WEB_ROOT = Path("/var/www/wangjinghong")
DEFAULT_SERVICE_NAME = "wangjinghong-api"
DEFAULT_SERVICE_USER = "www-data"
DEFAULT_SYSTEMCTL_BIN = "systemctl"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/api/health/"
DEFAULT_KEEP_RELEASES = 5
DEFAULT_KEEP_BACKUPS = 10
DEFAULT_HEALTH_RETRIES = 15
DEFAULT_HEALTH_INTERVAL = 0.5
DEFAULT_HEALTH_TIMEOUT = 3.0

SAFE_RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
STAGE_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".env",
    ".venv",
    "var",
    "staticfiles",
    "*.sqlite3",
    "*.sqlite3-*",
    "*.db",
)


class DeployError(RuntimeError):
    """Raised when validation, deployment, health check, or rollback fails."""


@dataclasses.dataclass(frozen=True)
class DeployConfig:
    app_root: Path = DEFAULT_APP_ROOT
    etc_env: Path = DEFAULT_ETC_ENV
    var_dir: Path = DEFAULT_VAR_DIR
    lock_file: Path = DEFAULT_LOCK_FILE
    service_name: str = DEFAULT_SERVICE_NAME
    service_user: str = DEFAULT_SERVICE_USER
    systemctl_bin: str = DEFAULT_SYSTEMCTL_BIN
    health_url: str = DEFAULT_HEALTH_URL
    keep_releases: int = DEFAULT_KEEP_RELEASES
    keep_backups: int = DEFAULT_KEEP_BACKUPS
    health_retries: int = DEFAULT_HEALTH_RETRIES
    health_interval: float = DEFAULT_HEALTH_INTERVAL
    health_timeout: float = DEFAULT_HEALTH_TIMEOUT


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


@contextlib.contextmanager
def exclusive_lock(lock_file: Path) -> Iterator[None]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def validate_release_id(release_id: str, *, label: str = "release_id") -> str:
    cleaned = release_id.strip()
    if not cleaned or cleaned in {".", ".."} or not SAFE_RELEASE_ID_RE.fullmatch(cleaned):
        raise DeployError(f"Unsafe {label} {release_id!r}; must match ^[A-Za-z0-9._-]+$.")
    return cleaned


def _parse_systemd_safe_value(raw_val: str, *, env_path: Path, lineno: int) -> str:
    val = raw_val.strip()
    if "\\" in val:
        raise DeployError(
            f"Backslash escapes are not permitted in {env_path}:{lineno}; use plain values matching systemd."
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in val):
        raise DeployError(f"Control characters are not permitted in {env_path}:{lineno}.")
    if not val:
        return ""
    if val[0] in {"'", '"'} or val[-1] in {"'", '"'}:
        if len(val) < 2 or val[0] != val[-1] or val[0] not in {"'", '"'}:
            raise DeployError(f"Mismatched quotes in {env_path}:{lineno}.")
        quote_char = val[0]
        inner = val[1:-1]
        if quote_char in inner:
            raise DeployError(f"Nested {quote_char!r} quotes are not permitted in {env_path}:{lineno}.")
        return inner
    if any(ch.isspace() or ch in {"'", '"'} for ch in val):
        raise DeployError(
            f"Unquoted whitespace or quotes are not permitted in {env_path}:{lineno}; wrap value in quotes."
        )
    return val


def load_and_validate_env_file(env_path: Path) -> dict[str, str]:
    try:
        st = env_path.lstat()
    except FileNotFoundError as exc:
        raise DeployError(f"Required environment file does not exist: {env_path}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise DeployError(f"Environment path must be a regular file (not symlink/dir): {env_path}")
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o027:
        raise DeployError(
            f"Permissions {oct(mode)} on {env_path} are too open; expected 0o600 or 0o640."
        )
    parsed: dict[str, str] = {}
    for lineno, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        trimmed_cr = raw_line.rstrip("\r")
        if trimmed_cr.endswith("\\"):
            raise DeployError(f"Line continuation '\\' is not permitted at {env_path}:{lineno}.")
        line = trimmed_cr.strip()
        if not line or line.startswith("#"):
            continue
        if line == "export" or line.startswith("export "):
            raise DeployError(
                f"Invalid 'export' prefix at {env_path}:{lineno}; systemd EnvironmentFile requires KEY=VALUE."
            )
        if "=" not in line:
            raise DeployError(f"Invalid line without '=' at {env_path}:{lineno}.")
        key, raw_val = line.split("=", 1)
        key = key.strip()
        if not SAFE_ENV_KEY_RE.fullmatch(key):
            raise DeployError(f"Invalid variable name {key!r} at {env_path}:{lineno}.")
        parsed[key] = _parse_systemd_safe_value(raw_val, env_path=env_path, lineno=lineno)
    return parsed


def _confinement_to_deploy_error(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _fs.FsConfinementError as exc:
        raise DeployError(str(exc)) from exc


def build_runtime_env(
    parsed_env: Mapping[str, str], *, var_dir: Path, app_root: Path
) -> tuple[dict[str, str], Path, Path, Path]:
    _confinement_to_deploy_error(_fs.validate_disjoint_roots, app_root, var_dir, DEFAULT_STATIC_WEB_ROOT)
    anchored_var = _confinement_to_deploy_error(_fs.anchor_var_root, var_dir)
    passthru_keys = ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "USER", "LOGNAME")
    env = {k: os.environ[k] for k in passthru_keys if k in os.environ}
    env.update(
        {
            "DJANGO_DEBUG": "false",
            "SQLITE_PATH": str(anchored_var / "db.sqlite3"),
            "DJANGO_CACHE_PATH": str(anchored_var / "cache"),
            "EMAIL_FILE_PATH": str(anchored_var / "mail"),
        }
    )
    env.update(parsed_env)
    env["DJANGO_DOTENV_PATH"] = "/dev/null"
    env["PYTHONUNBUFFERED"] = "1"
    sqlite_path, _ = _confinement_to_deploy_error(
        _fs.extract_var_rel_parts, "SQLITE_PATH", env["SQLITE_PATH"], var_dir=var_dir, anchored_var=anchored_var
    )
    cache_path, _ = _confinement_to_deploy_error(
        _fs.extract_var_rel_parts, "DJANGO_CACHE_PATH", env["DJANGO_CACHE_PATH"], var_dir=var_dir, anchored_var=anchored_var
    )
    mail_path, _ = _confinement_to_deploy_error(
        _fs.extract_var_rel_parts, "EMAIL_FILE_PATH", env["EMAIL_FILE_PATH"], var_dir=var_dir, anchored_var=anchored_var
    )
    env["SQLITE_PATH"] = str(sqlite_path)
    env["DJANGO_CACHE_PATH"] = str(cache_path)
    env["EMAIL_FILE_PATH"] = str(mail_path)
    return env, sqlite_path, cache_path, mail_path


def prepare_var_dirs(
    var_dir: Path,
    *,
    sqlite_path: Path,
    cache_path: Path,
    email_file_path: Path,
    service_user: str,
) -> tuple[str | None, tuple[int, int] | None]:
    return _confinement_to_deploy_error(
        _fs.prepare_var_dirs_nofollow,
        var_dir,
        sqlite_path=sqlite_path,
        cache_path=cache_path,
        email_file_path=email_file_path,
        service_user=service_user,
    )


def run_checked(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    as_user: str | None = None,
) -> subprocess.CompletedProcess[str]:
    full_cmd = ["runuser", "-u", as_user, "--", *cmd] if as_user else list(cmd)
    proc = subprocess.run(
        full_cmd,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise DeployError(f"Command failed ({' '.join(full_cmd)}): {detail}")
    return proc


def atomic_switch_symlink(link_path: Path, target_dir: Path) -> Path | None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    stashed: Path | None = None
    if link_path.exists() and not link_path.is_symlink() and link_path.is_dir():
        stashed = link_path.parent / f".{link_path.name}.legacy"
        if stashed.exists():
            shutil.rmtree(stashed, ignore_errors=True)
        os.replace(str(link_path), str(stashed))
    tmp_link = link_path.parent / f".{link_path.name}.tmp.{os.getpid()}"
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    os.symlink(str(target_dir.resolve()), str(tmp_link))
    os.replace(str(tmp_link), str(link_path))
    return stashed


def restore_stashed_legacy_dir(link_path: Path) -> bool:
    stashed = link_path.parent / f".{link_path.name}.legacy"
    if not stashed.is_dir() or stashed.is_symlink():
        return False
    if link_path.is_symlink():
        link_path.unlink()
    elif link_path.exists():
        return False
    os.replace(str(stashed), str(link_path))
    return True


def requirements_venv_id(requirements_file: Path) -> str:
    return hashlib.sha256(requirements_file.read_bytes()).hexdigest()[:16]


def ensure_release_venv(app_root: Path, requirements_file: Path) -> Path:
    req_bytes = requirements_file.read_bytes()
    full_sha = hashlib.sha256(req_bytes).hexdigest()
    venv_id = full_sha[:16]
    shared_dir = app_root / "shared"
    venvs_root = shared_dir / "venvs"
    venv_dir = venvs_root / venv_id
    venv_python = venv_dir / "bin" / "python"

    old_umask = os.umask(0o022)
    try:
        for directory in (app_root, shared_dir, venvs_root):
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o755)

        legacy_link = shared_dir / "venv"
        if not venv_python.exists() and (legacy_link / ".requirements.sha256").is_file():
            if (legacy_link / ".requirements.sha256").read_text(encoding="utf-8").strip() == full_sha:
                if legacy_link.is_symlink():
                    os.symlink(str(legacy_link.resolve()), str(venv_dir))
                elif legacy_link.is_dir() and (legacy_link / "bin" / "python").exists():
                    shutil.copytree(legacy_link, venv_dir, symlinks=True)

        ver_check = "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
        probe = (
            subprocess.run([str(venv_python), "-c", ver_check], capture_output=True, text=True)
            if venv_python.exists()
            else None
        )
        if probe is None or probe.returncode != 0:
            if venv_dir.is_symlink():
                venv_dir.unlink()
            elif venv_dir.exists():
                shutil.rmtree(venv_dir)
            create = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], capture_output=True, text=True)
            if create.returncode != 0:
                if os.geteuid() != 0:
                    detail = (create.stderr or create.stdout or f"exit {create.returncode}").strip()
                    raise DeployError(f"Failed to create venv at {venv_dir}: {detail}")
                apt_env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
                run_checked(["apt-get", "update"], env=apt_env)
                run_checked(["apt-get", "install", "-y", "python3-venv"], env=apt_env)
                if venv_dir.exists() and not venv_dir.is_symlink():
                    shutil.rmtree(venv_dir)
                run_checked([sys.executable, "-m", "venv", str(venv_dir)])

        stamp_file = venv_dir / ".requirements.sha256"
        current_sha = stamp_file.read_text(encoding="utf-8").strip() if stamp_file.is_file() else ""
        if current_sha != full_sha:
            try:
                run_checked(
                    [
                        str(venv_python),
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "--retries",
                        "3",
                        "--timeout",
                        "30",
                        "-r",
                        str(requirements_file),
                    ]
                )
                stamp_file.write_text(f"{full_sha}\n", encoding="utf-8")
            except BaseException:
                if venv_dir.exists() and not venv_dir.is_symlink():
                    shutil.rmtree(venv_dir, ignore_errors=True)
                raise
    finally:
        os.umask(old_umask)
    return venv_dir


def activate_venv_for_release(app_root: Path, release_dir: Path) -> Path:
    venv_dir = ensure_release_venv(app_root, release_dir / "server" / "requirements.txt")
    atomic_switch_symlink(app_root / "shared" / "venv", venv_dir)
    return venv_dir / "bin" / "python"


def normalize_tree_permissions(root: Path) -> None:
    os.chmod(root, 0o755)
    for dirpath, dirnames, filenames in os.walk(root):
        parent = Path(dirpath)
        for dname in dirnames:
            target_dir = parent / dname
            if target_dir.is_symlink():
                raise DeployError(f"Symlink directory not permitted in staged server: {target_dir}")
            os.chmod(target_dir, 0o755)
        for fname in filenames:
            target_file = parent / fname
            if target_file.is_symlink():
                raise DeployError(f"Symlink file not permitted in staged server: {target_file}")
            mode = 0o755 if (parent == root and fname == "manage.py") else 0o644
            os.chmod(target_file, mode)


def _reject_symlinks_in_source(staged_server: Path) -> None:
    if staged_server.is_symlink():
        raise DeployError(f"Staged server root must not be a symlink: {staged_server}")
    ignore_fn = shutil.ignore_patterns(*STAGE_IGNORE_PATTERNS)
    for dirpath, dirnames, filenames in os.walk(staged_server, followlinks=False):
        parent = Path(dirpath)
        ignored = set(ignore_fn(str(parent), [*dirnames, *filenames]))
        kept_dirs: list[str] = []
        for dname in dirnames:
            if dname in ignored:
                continue
            candidate_dir = parent / dname
            if candidate_dir.is_symlink():
                raise DeployError(f"Symlink directory not permitted in staged server: {candidate_dir}")
            kept_dirs.append(dname)
        dirnames[:] = kept_dirs
        for fname in filenames:
            if fname in ignored:
                continue
            candidate_file = parent / fname
            if candidate_file.is_symlink():
                raise DeployError(f"Symlink file not permitted in staged server: {candidate_file}")


def stage_release(staged_server: Path, app_root: Path, release_id: str, active_target: Path | None) -> Path:
    if not staged_server.is_dir() or staged_server.is_symlink():
        raise DeployError(f"Staged server directory not found or is a symlink: {staged_server}")
    _reject_symlinks_in_source(staged_server)
    for required in ("manage.py", "requirements.txt", "config/wsgi.py"):
        req_path = staged_server / required
        if req_path.is_symlink() or not req_path.is_file():
            raise DeployError(f"Staged server is missing required regular file: {required}")
    for directory in (app_root, app_root / "releases"):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o755)
    release_dir = app_root / "releases" / release_id
    if active_target is not None and release_dir.resolve() == active_target.resolve():
        raise DeployError(f"Release {release_id!r} is currently active; choose a new release_id.")
    if release_dir.exists() or release_dir.is_symlink():
        if (release_dir / ".activated").exists() or release_dir.is_symlink():
            raise DeployError(
                f"Release {release_id!r} already exists in activated history and is immutable; choose a new release_id."
            )
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True)
    os.chmod(release_dir, 0o755)
    server_dst = release_dir / "server"
    try:
        shutil.copytree(
            staged_server,
            server_dst,
            symlinks=True,
            ignore=shutil.ignore_patterns(*STAGE_IGNORE_PATTERNS),
        )
        normalize_tree_permissions(server_dst)
    except BaseException:
        shutil.rmtree(release_dir, ignore_errors=True)
        raise
    return release_dir


def is_healthy_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if "status" in payload and payload["status"] != "ok":
        return False
    if "ok" in payload and payload["ok"] is not True:
        return False
    return payload.get("status") == "ok" or payload.get("ok") is True


def _extract_probe_host(runtime_env: Mapping[str, str]) -> str:
    for item in runtime_env.get("DJANGO_ALLOWED_HOSTS", "").split(","):
        cleaned = item.strip().lstrip(".")
        if cleaned and cleaned != "*":
            return cleaned
    return "127.0.0.1"


def wait_for_healthy(cfg: DeployConfig, runtime_env: Mapping[str, str]) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
    headers = {"Host": _extract_probe_host(runtime_env), "X-Forwarded-Proto": "https", "Accept": "application/json"}
    last_error = "no probe attempts executed"
    for attempt in range(1, max(1, cfg.health_retries) + 1):
        req = urllib.request.Request(cfg.health_url, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=cfg.health_timeout) as resp:
                status = resp.status
                cache_ctl = (resp.headers.get("Cache-Control") or "").lower()
                raw_body = resp.read().decode("utf-8", errors="replace")
            if status != 200:
                last_error = f"HTTP {status}"
            elif "no-store" not in cache_ctl:
                last_error = f"missing no-store in Cache-Control ({cache_ctl!r})"
            elif is_healthy_payload(json.loads(raw_body)):
                return
            else:
                last_error = f"unhealthy JSON payload {raw_body!r}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            exc.close()
        except (OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < cfg.health_retries:
            time.sleep(cfg.health_interval)
    raise DeployError(f"Health probe failed at {cfg.health_url} after {cfg.health_retries} attempts ({last_error}).")
