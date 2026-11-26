"""Declarative Django settings for site/server."""

from __future__ import annotations

import os

from config.env import SERVER_DIR, bootstrap_env, resolve_runtime_settings

BASE_DIR = SERVER_DIR

SQLITE_INIT_COMMAND = (
    "PRAGMA journal_mode=WAL; "
    "PRAGMA synchronous=NORMAL; "
    "PRAGMA busy_timeout=5000; "
    "PRAGMA foreign_keys=ON;"
)

bootstrap_env(default_debug="false", environ=os.environ, base_dir=BASE_DIR)
_RUNTIME = resolve_runtime_settings(os.environ, base_dir=BASE_DIR)

SECRET_KEY = _RUNTIME.secret_key
DEBUG = _RUNTIME.debug
ALLOWED_HOSTS = _RUNTIME.allowed_hosts

DJANGO_ADMIN_PATH = _RUNTIME.admin_path
ALLAUTH_TRUSTED_PROXY_COUNT = _RUNTIME.trusted_proxy_count
ALLOW_GUEST_COMMENTS = _RUNTIME.allow_guest_comments
COMMENT_RATE_LIMITS = {
    "guest_ip": (
        (5, 60),
        (20, 3600),
    ),
    "member_user": (
        (10, 60),
    ),
    "member_ip": (
        (20, 60),
    ),
}

INSTALLED_APPS = [
    "config.admin_site.UnifiedAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "comments.apps.CommentsConfig",
    "allauth",
    "allauth.account",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.DynamicRouteNoStoreMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.account_feedback",
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

CACHES = {
    "default": {
        "BACKEND": _RUNTIME.cache_backend,
        "LOCATION": _RUNTIME.cache_location,
        "OPTIONS": {
            "MAX_ENTRIES": 10000,
        },
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {
            "user_attributes": ("username", "email", "display_name"),
        },
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

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = (
    "/accounts/login/?confirmed=1"
)

ACCOUNT_ADAPTER = "accounts.adapter.AccountAdapter"
ACCOUNT_FORMS = {
    "login": "accounts.forms.AccountLoginForm",
    "reset_password": "accounts.forms.AccountResetPasswordForm",
    "signup": "accounts.forms.AccountSignupForm",
}
ACCOUNT_USER_DISPLAY = "accounts.adapter.user_display"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_MAX_EMAIL_ADDRESSES = 1
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS = False
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[wangjinghong.com] "
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

# Use /django-static/ so Django Admin static assets never collide with Vite's /static/ bundle dir.
STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

EMAIL_BACKEND = _RUNTIME.email_backend
EMAIL_FILE_PATH = str(_RUNTIME.email_file_path)
EMAIL_HOST = _RUNTIME.email_host
EMAIL_PORT = _RUNTIME.email_port
EMAIL_HOST_USER = _RUNTIME.email_host_user
EMAIL_HOST_PASSWORD = _RUNTIME.email_host_password
EMAIL_USE_SSL = _RUNTIME.email_use_ssl
EMAIL_USE_TLS = _RUNTIME.email_use_tls
EMAIL_TIMEOUT = _RUNTIME.email_timeout
DEFAULT_FROM_EMAIL = _RUNTIME.default_from_email

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_FAILURE_VIEW = "config.http.csrf_failure_view"

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    # Requires front-end Nginx reverse proxy to overwrite X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

TEST_RUNNER = "config.test_runner.ServerDiscoverRunner"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
