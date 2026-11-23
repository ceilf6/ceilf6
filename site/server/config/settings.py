"""Django settings for site/server."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

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
SQLITE_INIT_COMMAND = (
    "PRAGMA journal_mode=WAL; "
    "PRAGMA synchronous=NORMAL; "
    "PRAGMA busy_timeout=5000; "
    "PRAGMA foreign_keys=ON;"
)


@dataclass(frozen=True)
class RuntimeSettings:
    debug: bool
    secret_key: str
    allowed_hosts: list[str]
    sqlite_name: str | Path
    email_backend: str
    email_file_path: Path
    admin_path: str
    allow_guest_comments: bool


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


def _resolve_path(base_dir: Path, raw_path: str, default_rel: Path) -> Path:
    candidate = Path(raw_path) if raw_path else (base_dir / default_rel)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _normalize_admin_path(raw_admin_path: str) -> str:
    cleaned = raw_admin_path.strip().lstrip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise ImproperlyConfigured(
            "DJANGO_ADMIN_PATH must be a non-empty relative URL prefix."
        )
    if not cleaned.endswith("/"):
        cleaned = f"{cleaned}/"
    if cleaned.startswith("api/"):
        raise ImproperlyConfigured(
            "DJANGO_ADMIN_PATH must not be nested under api/."
        )
    return cleaned


def resolve_runtime_settings(
    environ: Mapping[str, str], *, base_dir: Path = BASE_DIR
) -> RuntimeSettings:
    # Default to False (fail-closed) when DJANGO_DEBUG is unset; manage.py sets
    # DJANGO_DEBUG=true explicitly for zero-config local CLI/runserver usage.
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

    email_backend = (
        environ.get("DJANGO_EMAIL_BACKEND", "").strip()
        or FILEBASED_EMAIL_BACKEND
    )
    raw_email_dir = environ.get("EMAIL_FILE_PATH", "").strip()
    email_file_path = _resolve_path(
        base_dir, raw_email_dir, Path("var") / "mail"
    )
    if email_backend == FILEBASED_EMAIL_BACKEND:
        email_file_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            email_file_path.chmod(0o700)
        except OSError:
            pass

    raw_admin_path = environ.get("DJANGO_ADMIN_PATH", "admin/")
    admin_path = _normalize_admin_path(raw_admin_path)

    allow_guest_comments = parse_env_bool(
        environ, "ALLOW_GUEST_COMMENTS", default=False
    )

    return RuntimeSettings(
        debug=debug,
        secret_key=secret_key,
        allowed_hosts=allowed_hosts,
        sqlite_name=sqlite_name,
        email_backend=email_backend,
        email_file_path=email_file_path,
        admin_path=admin_path,
        allow_guest_comments=allow_guest_comments,
    )


_DOTENV_OVERRIDE = os.environ.get("DJANGO_DOTENV_PATH", "").strip()
load_dotenv_file(
    Path(_DOTENV_OVERRIDE) if _DOTENV_OVERRIDE else (BASE_DIR / ".env"),
    os.environ,
)
_RUNTIME = resolve_runtime_settings(os.environ, base_dir=BASE_DIR)

SECRET_KEY = _RUNTIME.secret_key
DEBUG = _RUNTIME.debug
ALLOWED_HOSTS = _RUNTIME.allowed_hosts

DJANGO_ADMIN_PATH = _RUNTIME.admin_path
ALLOW_GUEST_COMMENTS = _RUNTIME.allow_guest_comments

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _RUNTIME.sqlite_name,
        "OPTIONS": {
            "timeout": 5,
            "transaction_mode": "IMMEDIATE",
            "init_command": SQLITE_INIT_COMMAND,
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# Use /django-static/ so Django Admin static assets never collide with Vite's /static/ bundle dir.
STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

EMAIL_BACKEND = _RUNTIME.email_backend
EMAIL_FILE_PATH = str(_RUNTIME.email_file_path)

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    # Requires front-end Nginx reverse proxy to overwrite X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

TEST_RUNNER = "config.test_runner.ServerDiscoverRunner"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
