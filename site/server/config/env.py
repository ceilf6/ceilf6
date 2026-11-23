"""Environment bootstrap and fail-closed runtime settings resolution."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

SERVER_DIR = Path(__file__).resolve().parent.parent

LOCAL_DEV_SECRET_KEY = "django-insecure-local-dev-placeholder"
EXAMPLE_SECRET_KEY_PLACEHOLDER = "django-insecure-example-placeholder"
INSECURE_SECRET_KEYS = frozenset(
    {
        LOCAL_DEV_SECRET_KEY,
        EXAMPLE_SECRET_KEY_PLACEHOLDER,
        "change-me",
        "changeme",
        "secret",
    }
)
MIN_PRODUCTION_SECRET_KEY_LENGTH = 50
MIN_PRODUCTION_SECRET_KEY_UNIQUE_CHARS = 5
FILEBASED_EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
SMTP_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
LOCMEM_CACHE_BACKEND = "django.core.cache.backends.locmem.LocMemCache"
FILEBASED_CACHE_BACKEND = "django.core.cache.backends.filebased.FileBasedCache"
RESERVED_ADMIN_PREFIXES = ("api/", "accounts/", "django-static/", "static/")


@dataclass(frozen=True)
class RuntimeSettings:
    debug: bool
    secret_key: str
    allowed_hosts: list[str]
    sqlite_name: str | Path
    cache_backend: str
    cache_location: str
    trusted_proxy_count: int
    email_backend: str
    email_file_path: Path
    email_host: str
    email_port: int
    email_host_user: str
    email_host_password: str
    email_use_ssl: bool
    email_use_tls: bool
    email_timeout: int
    default_from_email: str
    admin_path: str


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


def parse_env_bool(
    environ: Mapping[str, str], name: str, *, default: bool
) -> bool:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(
        f"Invalid boolean value for {name}: {raw!r}. Expected true/false."
    )


def parse_env_int(
    environ: Mapping[str, str],
    name: str,
    *,
    default: int,
    min_value: int = 1,
    max_value: int | None = None,
) -> int:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"Invalid integer value for {name}: {raw!r}."
        ) from exc
    if parsed < min_value or (max_value is not None and parsed > max_value):
        upper = f" <= {max_value}" if max_value is not None else ""
        raise ImproperlyConfigured(
            f"Out-of-range integer value for {name}: {parsed} (expected >= {min_value}{upper})."
        )
    return parsed


def _resolve_path(base_dir: Path, raw_path: str, default_rel: Path) -> Path:
    candidate = Path(raw_path) if raw_path else (base_dir / default_rel)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _ensure_private_dir(target_dir: Path) -> None:
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        target_dir.chmod(0o700)
    except OSError:
        pass


def _normalize_admin_path(raw_admin_path: str) -> str:
    cleaned = raw_admin_path.strip().lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise ImproperlyConfigured(
            "DJANGO_ADMIN_PATH must be a non-empty relative URL prefix."
        )
    if not cleaned.endswith("/"):
        cleaned = f"{cleaned}/"
    if any(cleaned.startswith(prefix) for prefix in RESERVED_ADMIN_PREFIXES):
        raise ImproperlyConfigured(
            "DJANGO_ADMIN_PATH must not collide with api/, accounts/, static/, or django-static/."
        )
    return cleaned


def resolve_runtime_settings(
    environ: Mapping[str, str], *, base_dir: Path = SERVER_DIR
) -> RuntimeSettings:
    # Default to False (fail-closed) when DJANGO_DEBUG is unset; manage.py calls
    # bootstrap_env(default_debug="true") after loading .env for local dev.
    debug = parse_env_bool(environ, "DJANGO_DEBUG", default=False)

    raw_secret = environ.get("DJANGO_SECRET_KEY", "").strip()
    if debug:
        secret_key = raw_secret or LOCAL_DEV_SECRET_KEY
    else:
        if (
            not raw_secret
            or raw_secret in INSECURE_SECRET_KEYS
            or raw_secret.startswith("django-insecure-")
            or len(raw_secret) < MIN_PRODUCTION_SECRET_KEY_LENGTH
            or len(set(raw_secret)) < MIN_PRODUCTION_SECRET_KEY_UNIQUE_CHARS
        ):
            raise ImproperlyConfigured(
                "DJANGO_SECRET_KEY must be set to a strong non-default secret "
                f"(>= {MIN_PRODUCTION_SECRET_KEY_LENGTH} chars with at least "
                f"{MIN_PRODUCTION_SECRET_KEY_UNIQUE_CHARS} distinct chars, "
                "not starting with 'django-insecure-') when DJANGO_DEBUG is false."
            )
        secret_key = raw_secret

    raw_hosts = environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
    allowed_hosts = [h.strip() for h in raw_hosts.split(",") if h.strip()]
    if not allowed_hosts:
        if debug:
            allowed_hosts = ["127.0.0.1", "localhost"]
        else:
            raise ImproperlyConfigured(
                "DJANGO_ALLOWED_HOSTS must be set when DJANGO_DEBUG is false."
            )
    if not debug and "*" in allowed_hosts:
        raise ImproperlyConfigured(
            "Wildcard '*' is not permitted in DJANGO_ALLOWED_HOSTS when DJANGO_DEBUG is false."
        )

    raw_sqlite = environ.get("SQLITE_PATH", "").strip()
    if raw_sqlite == ":memory:":
        sqlite_name: str | Path = ":memory:"
    else:
        sqlite_path = _resolve_path(
            base_dir, raw_sqlite, Path("var") / "db.sqlite3"
        )
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        sqlite_name = sqlite_path

    raw_cache_path = environ.get("DJANGO_CACHE_PATH", "").strip()
    if raw_cache_path == ":memory:":
        cache_backend = LOCMEM_CACHE_BACKEND
        cache_location = "site-server-memory-cache"
    else:
        cache_backend = FILEBASED_CACHE_BACKEND
        cache_dir = _resolve_path(
            base_dir, raw_cache_path, Path("var") / "cache"
        )
        _ensure_private_dir(cache_dir)
        cache_location = str(cache_dir)

    if not debug and not environ.get("DJANGO_TRUSTED_PROXY_COUNT", "").strip():
        raise ImproperlyConfigured(
            "DJANGO_TRUSTED_PROXY_COUNT must be explicitly set when DJANGO_DEBUG is false."
        )
    trusted_proxy_count = parse_env_int(
        environ,
        "DJANGO_TRUSTED_PROXY_COUNT",
        default=0,
        min_value=0,
        max_value=10,
    )

    raw_email_backend = environ.get("DJANGO_EMAIL_BACKEND", "").strip()
    if debug:
        email_backend = raw_email_backend or FILEBASED_EMAIL_BACKEND
    else:
        if not raw_email_backend:
            raise ImproperlyConfigured(
                "DJANGO_EMAIL_BACKEND must be explicitly set when DJANGO_DEBUG is false."
            )
        email_backend = raw_email_backend

    raw_email_dir = environ.get("EMAIL_FILE_PATH", "").strip()
    email_file_path = _resolve_path(
        base_dir, raw_email_dir, Path("var") / "mail"
    )
    if email_backend == FILEBASED_EMAIL_BACKEND:
        _ensure_private_dir(email_file_path)

    email_use_ssl = parse_env_bool(
        environ, "DJANGO_EMAIL_USE_SSL", default=False
    )
    email_use_tls = parse_env_bool(
        environ, "DJANGO_EMAIL_USE_TLS", default=False
    )
    if email_use_ssl and email_use_tls:
        raise ImproperlyConfigured(
            "DJANGO_EMAIL_USE_SSL and DJANGO_EMAIL_USE_TLS cannot both be true."
        )

    default_smtp_port = 465 if email_use_ssl else 587
    email_port = parse_env_int(
        environ,
        "DJANGO_EMAIL_PORT",
        default=default_smtp_port,
        min_value=1,
        max_value=65535,
    )
    email_timeout = parse_env_int(
        environ,
        "DJANGO_EMAIL_TIMEOUT",
        default=10,
        min_value=1,
    )
    raw_email_host = environ.get("DJANGO_EMAIL_HOST", "").strip()
    if not debug and email_backend == SMTP_EMAIL_BACKEND:
        if not raw_email_host:
            raise ImproperlyConfigured(
                "DJANGO_EMAIL_HOST must be set when using SMTP in production."
            )
        if email_port == 25:
            raise ImproperlyConfigured(
                "Port 25 is blocked on cloud instances; use 465 (SSL) or 587 (STARTTLS) for production SMTP."
            )
        if not (email_use_ssl or email_use_tls):
            raise ImproperlyConfigured(
                "Production SMTP requires DJANGO_EMAIL_USE_SSL=true or DJANGO_EMAIL_USE_TLS=true."
            )
        if email_port == 465 and not email_use_ssl:
            raise ImproperlyConfigured(
                "SMTP port 465 requires DJANGO_EMAIL_USE_SSL=true."
            )
        if email_port == 587 and not email_use_tls:
            raise ImproperlyConfigured(
                "SMTP port 587 requires DJANGO_EMAIL_USE_TLS=true."
            )
    email_host = raw_email_host or "localhost"
    email_host_user = environ.get("DJANGO_EMAIL_HOST_USER", "").strip()
    email_host_password = environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
    default_from_email = (
        environ.get("DJANGO_DEFAULT_FROM_EMAIL", "").strip()
        or "noreply@localhost"
    )

    raw_admin_path = environ.get("DJANGO_ADMIN_PATH", "admin/")
    admin_path = _normalize_admin_path(raw_admin_path)

    return RuntimeSettings(
        debug=debug,
        secret_key=secret_key,
        allowed_hosts=allowed_hosts,
        sqlite_name=sqlite_name,
        cache_backend=cache_backend,
        cache_location=cache_location,
        trusted_proxy_count=trusted_proxy_count,
        email_backend=email_backend,
        email_file_path=email_file_path,
        email_host=email_host,
        email_port=email_port,
        email_host_user=email_host_user,
        email_host_password=email_host_password,
        email_use_ssl=email_use_ssl,
        email_use_tls=email_use_tls,
        email_timeout=email_timeout,
        default_from_email=default_from_email,
        admin_path=admin_path,
    )
