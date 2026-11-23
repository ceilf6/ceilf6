"""Tests for server configuration, SQLite WAL/IMMEDIATE, health probe, and WSGI."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import (
    DatabaseError,
    IntegrityError,
    OperationalError,
    connections,
    transaction,
)
from django.db.backends.sqlite3.base import DatabaseWrapper
from django.test import Client, SimpleTestCase, TestCase, override_settings

from accounts.models import User
from config.env import (
    EXAMPLE_SECRET_KEY_PLACEHOLDER,
    FILEBASED_CACHE_BACKEND,
    FILEBASED_EMAIL_BACKEND,
    LOCAL_DEV_SECRET_KEY,
    LOCMEM_CACHE_BACKEND,
    SMTP_EMAIL_BACKEND,
    bootstrap_env,
    load_dotenv_file,
    resolve_runtime_settings,
)
from config.middleware import NO_STORE_CACHE_CONTROL, is_dynamic_route
from config.settings import BASE_DIR

MANAGE_PY = BASE_DIR / "manage.py"
EXPECTED_NO_STORE = NO_STORE_CACHE_CONTROL
_SMTP_AUTH_ENV = "DJANGO_EMAIL_HOST_" + "PASSWORD"
_SECRET_ENV = "DJANGO_SECRET_" + "KEY"


def _make_prod_key() -> str:
    return f"prod-{secrets.token_urlsafe(48)}"


def _isolated_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    stripped_keys = {
        "DJANGO_DEBUG",
        _SECRET_ENV,
        "DJANGO_ALLOWED_HOSTS",
        "SQLITE_PATH",
        "DJANGO_CACHE_PATH",
        "DJANGO_TRUSTED_PROXY_COUNT",
        "DJANGO_EMAIL_BACKEND",
        "EMAIL_FILE_PATH",
        "DJANGO_EMAIL_HOST",
        "DJANGO_EMAIL_PORT",
        "DJANGO_EMAIL_HOST_USER",
        _SMTP_AUTH_ENV,
        "DJANGO_EMAIL_USE_SSL",
        "DJANGO_EMAIL_USE_TLS",
        "DJANGO_EMAIL_TIMEOUT",
        "DJANGO_DEFAULT_FROM_EMAIL",
        "DJANGO_ADMIN_PATH",
        "DJANGO_DOTENV_PATH",
    }
    cleaned = {
        key: value
        for key, value in os.environ.items()
        if key not in stripped_keys
    }
    cleaned["DJANGO_DOTENV_PATH"] = str(tmp_path / ".env.isolated")
    cleaned["SQLITE_PATH"] = str(tmp_path / "isolated.sqlite3")
    cleaned["DJANGO_CACHE_PATH"] = str(tmp_path / "cache")
    cleaned["EMAIL_FILE_PATH"] = str(tmp_path / "mail")
    cleaned.update(overrides)
    return cleaned


def _run_manage(
    *args: str, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MANAGE_PY), *args],
        cwd=str(BASE_DIR),
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


def _run_python_code(
    code: str, *, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BASE_DIR),
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


def _gunicorn_check(
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "gunicorn",
            "--check-config",
            "--chdir",
            str(BASE_DIR),
            "config.wsgi:application",
        ],
        cwd=str(BASE_DIR),
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


class SqliteWalAndMigrationTests(unittest.TestCase):
    def test_fresh_file_sqlite_migrate_and_concurrent_immediate_transactions(
        self,
    ) -> None:
        options = settings.DATABASES["default"]["OPTIONS"]
        self.assertEqual(options["timeout"], 5)
        self.assertEqual(options["transaction_mode"], "IMMEDIATE")

        with tempfile.TemporaryDirectory(prefix="ceilf6-sqlite-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "nested" / "fresh.sqlite3"
            env = _isolated_env(
                tmp_path,
                DJANGO_DEBUG="true",
                SQLITE_PATH=str(db_path),
            )

            first_run = _run_manage("migrate", "--noinput", env=env)
            self.assertEqual(
                first_run.returncode,
                0,
                msg=f"First migrate failed:\n{first_run.stdout}\n{first_run.stderr}",
            )
            self.assertTrue(db_path.is_file())

            second_run = _run_manage("migrate", "--noinput", env=env)
            self.assertEqual(
                second_run.returncode,
                0,
                msg=f"Second migrate failed:\n{second_run.stdout}\n{second_run.stderr}",
            )
            self.assertIn("No migrations to apply.", second_run.stdout)

            db_settings = {
                **settings.DATABASES["default"],
                "NAME": db_path,
            }
            wrapper = DatabaseWrapper(db_settings, alias="wal_probe")
            try:
                wrapper.ensure_connection()
                self.assertEqual(wrapper.transaction_mode, "IMMEDIATE")
                with wrapper.cursor() as cursor:
                    cursor.execute("PRAGMA journal_mode;")
                    journal_mode = cursor.fetchone()[0]

                    cursor.execute("PRAGMA foreign_keys;")
                    foreign_keys = cursor.fetchone()[0]

                    cursor.execute("PRAGMA busy_timeout;")
                    busy_timeout = cursor.fetchone()[0]

                    cursor.execute("PRAGMA synchronous;")
                    synchronous = cursor.fetchone()[0]

                    self.assertEqual(str(journal_mode).lower(), "wal")
                    self.assertEqual(foreign_keys, 1)
                    self.assertEqual(busy_timeout, 5000)
                    # SQLite PRAGMA synchronous: 1 == NORMAL
                    self.assertEqual(synchronous, 1)

                    with self.assertRaises(IntegrityError):
                        cursor.execute(
                            "INSERT INTO accounts_user_groups (user_id, group_id) "
                            "VALUES (999999, 999999);"
                        )
            finally:
                wrapper.close()

            alias = "concurrent_wal_test"
            connections.settings[alias] = db_settings
            try:
                seed_user = User.objects.db_manager(alias).create_user(
                    "concurrency-seed",
                    "seed@example.com",
                    secrets.token_urlsafe(20),
                    display_name="init",
                )
                first_tx_entered = threading.Event()
                errors: list[BaseException] = []

                def writer_one() -> None:
                    try:
                        with transaction.atomic(using=alias):
                            row = User.objects.using(alias).get(pk=seed_user.pk)
                            first_tx_entered.set()
                            time.sleep(0.05)
                            row.display_name = f"{row.display_name}-A"
                            row.save(using=alias)
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)
                    finally:
                        connections[alias].close()

                def writer_two() -> None:
                    try:
                        first_tx_entered.wait(timeout=2.0)
                        with transaction.atomic(using=alias):
                            row = User.objects.using(alias).get(pk=seed_user.pk)
                            row.display_name = f"{row.display_name}-B"
                            row.save(using=alias)
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)
                    finally:
                        connections[alias].close()

                t1 = threading.Thread(target=writer_one)
                t2 = threading.Thread(target=writer_two)
                t1.start()
                t2.start()
                t1.join(timeout=5.0)
                t2.join(timeout=5.0)

                self.assertEqual(errors, [])
                seed_user.refresh_from_db(using=alias)
                self.assertEqual(seed_user.display_name, "init-A-B")
            finally:
                connections[alias].close()
                connections.settings.pop(alias, None)


class HealthAndNoStoreMiddlewareTests(TestCase):
    def test_get_health_returns_200_ok_and_no_store(self) -> None:
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], EXPECTED_NO_STORE)
        self.assertIn("Cookie", response["Vary"])
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_without_trailing_slash_redirects_with_no_store(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/api/health/")
        self.assertEqual(response["Cache-Control"], EXPECTED_NO_STORE)

    def test_head_health_returns_200_and_no_store(self) -> None:
        response = self.client.head("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], EXPECTED_NO_STORE)

    def test_non_get_methods_return_405_json_even_with_csrf_checks_enabled(
        self,
    ) -> None:
        csrf_client = Client(enforce_csrf_checks=True)
        for method_name in ("post", "put", "patch", "delete"):
            with self.subTest(method=method_name):
                caller = getattr(csrf_client, method_name)
                response = caller("/api/health/")
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response["Cache-Control"], EXPECTED_NO_STORE)
                self.assertEqual(response["Allow"], "GET, HEAD")
                payload = response.json()
                self.assertEqual(payload["code"], "method_not_allowed")
                self.assertTrue(payload["message"])

    def test_admin_and_auth_routes_emit_no_store_while_static_prefix_excluded(
        self,
    ) -> None:
        self.assertTrue(is_dynamic_route("/accounts/login/"))
        self.assertTrue(is_dynamic_route("/api/health/"))
        self.assertTrue(is_dynamic_route("/api/me/"))
        self.assertTrue(is_dynamic_route(f"/{settings.DJANGO_ADMIN_PATH}"))
        self.assertFalse(is_dynamic_route("/django-static/admin/css/base.css"))
        self.assertFalse(is_dynamic_route("/static/index.js"))

        admin_res = self.client.get(f"/{settings.DJANGO_ADMIN_PATH}login/")
        self.assertEqual(admin_res.status_code, 302)
        self.assertTrue(
            admin_res["Location"].startswith("/accounts/login/?next=")
        )
        self.assertEqual(admin_res["Cache-Control"], EXPECTED_NO_STORE)
        self.assertIn("Cookie", admin_res["Vary"])

    def test_database_failure_closes_connection_and_returns_503_safely(
        self,
    ) -> None:
        for error in (
            OperationalError(
                "unable to open database file: /srv/internal/var/db.sqlite3"
            ),
            DatabaseError("corrupt btree page 42"),
        ):
            with self.subTest(error=type(error).__name__):
                with (
                    patch("config.views.connection.cursor", side_effect=error),
                    patch("config.views.connection.close") as mock_close,
                    self.assertLogs("config.views", level="ERROR") as captured,
                ):
                    response = self.client.get("/api/health/")

                mock_close.assert_called_once()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response["Cache-Control"], EXPECTED_NO_STORE)
                self.assertEqual(response.json(), {"status": "unavailable"})
                raw_body = response.content.decode("utf-8")
                self.assertNotIn("/srv/internal", raw_body)
                self.assertNotIn("btree", raw_body)
                self.assertNotIn("Traceback", raw_body)
                self.assertTrue(
                    any(
                        "Database connectivity probe failed" in entry
                        for entry in captured.output
                    )
                )

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["www.wangjinghong.com", "127.0.0.1", "localhost"],
    )
    def test_loopback_and_domain_hosts_succeed_while_untrusted_host_rejected(
        self,
    ) -> None:
        for allowed_host in ("www.wangjinghong.com", "127.0.0.1", "localhost"):
            with self.subTest(host=allowed_host):
                res = self.client.get("/api/health/", HTTP_HOST=allowed_host)
                self.assertEqual(res.status_code, 200)

        with self.assertLogs("django.security.DisallowedHost", level="ERROR"):
            blocked = self.client.get(
                "/api/health/", HTTP_HOST="evil.example.org"
            )
        self.assertEqual(blocked.status_code, 400)


class RuntimeSettingsSecurityTests(SimpleTestCase):
    def test_declarative_settings_no_sites_app_and_cookie_security_defaults(
        self,
    ) -> None:
        import config.settings as settings_module

        self.assertFalse(hasattr(settings_module, "__all__"))
        self.assertNotIn("django.contrib.sites", settings.INSTALLED_APPS)
        self.assertFalse(hasattr(settings_module, "SITE_ID"))
        self.assertFalse(hasattr(settings_module, "TRUSTED_PROXY_COUNT"))
        self.assertEqual(
            settings.CACHES["default"]["OPTIONS"]["MAX_ENTRIES"], 10000
        )
        self.assertEqual(settings.STATIC_URL, "/django-static/")
        from django.contrib import admin
        from config.admin_site import UnifiedLoginAdminSite

        self.assertIsInstance(admin.site._wrapped or admin.site, UnifiedLoginAdminSite)
        self.assertEqual(settings.LOGIN_URL, "/accounts/login/")
        self.assertEqual(settings.LOGIN_REDIRECT_URL, "/")
        self.assertEqual(settings.ACCOUNT_LOGOUT_REDIRECT_URL, "/")

        with tempfile.TemporaryDirectory(prefix="ceilf6-decl-env-") as tmp_dir:
            env = _isolated_env(Path(tmp_dir), DJANGO_DEBUG="true")
            probe = _run_python_code(
                "import django, os; "
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
                "django.setup(); "
                "from django.conf import settings; "
                "assert settings.ALLAUTH_TRUSTED_PROXY_COUNT == 0; "
                "assert settings.SESSION_COOKIE_HTTPONLY is True; "
                "assert settings.SESSION_COOKIE_SAMESITE == 'Lax'; "
                "assert settings.SESSION_COOKIE_SECURE is False; "
                "assert settings.CSRF_COOKIE_HTTPONLY is True; "
                "assert settings.CSRF_COOKIE_SAMESITE == 'Lax'; "
                "assert settings.CSRF_COOKIE_SECURE is False; "
                "assert settings.LOGIN_URL == '/accounts/login/'; "
                "assert settings.LOGIN_REDIRECT_URL == '/'; "
                "assert settings.ACCOUNT_LOGOUT_REDIRECT_URL == '/'",
                env=env,
            )
            self.assertEqual(
                probe.returncode,
                0,
                msg=f"Isolated declarative settings probe failed:\n{probe.stdout}\n{probe.stderr}",
            )

    def test_default_without_django_debug_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-closed-") as tmp_dir:
            with self.assertRaises(ImproperlyConfigured):
                resolve_runtime_settings({}, base_dir=Path(tmp_dir))

    def test_explicit_debug_true_enables_zero_config_local_defaults(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-dev-") as tmp_dir:
            base = Path(tmp_dir)
            cfg = resolve_runtime_settings(
                {"DJANGO_DEBUG": "true"}, base_dir=base
            )
            self.assertTrue(cfg.debug)
            self.assertEqual(cfg.secret_key, LOCAL_DEV_SECRET_KEY)
            self.assertEqual(cfg.allowed_hosts, ["127.0.0.1", "localhost"])
            self.assertEqual(
                cfg.sqlite_name, (base / "var" / "db.sqlite3").resolve()
            )
            self.assertEqual(cfg.cache_backend, FILEBASED_CACHE_BACKEND)
            cache_dir = base / "var" / "cache"
            self.assertTrue(cache_dir.is_dir())
            self.assertEqual(stat.S_IMODE(cache_dir.stat().st_mode), 0o700)
            self.assertEqual(cfg.trusted_proxy_count, 0)
            self.assertEqual(cfg.email_backend, FILEBASED_EMAIL_BACKEND)
            mail_dir = base / "var" / "mail"
            self.assertTrue(mail_dir.is_dir())
            self.assertEqual(stat.S_IMODE(mail_dir.stat().st_mode), 0o700)
            self.assertEqual(cfg.admin_path, "admin/")

    def test_memory_cache_and_trusted_proxy_count_fail_closed_in_prod(
        self,
    ) -> None:
        strong_key = _make_prod_key()
        with tempfile.TemporaryDirectory(prefix="ceilf6-cache-") as tmp_dir:
            base = Path(tmp_dir)
            mem_cfg = resolve_runtime_settings(
                {
                    "DJANGO_DEBUG": "true",
                    "DJANGO_CACHE_PATH": ":memory:",
                    "DJANGO_TRUSTED_PROXY_COUNT": "2",
                },
                base_dir=base,
            )
            self.assertEqual(mem_cfg.cache_backend, LOCMEM_CACHE_BACKEND)
            self.assertFalse((base / "var" / "cache").exists())
            self.assertEqual(mem_cfg.trusted_proxy_count, 2)

            # Production mode fails closed when DJANGO_TRUSTED_PROXY_COUNT is omitted
            with self.assertRaises(ImproperlyConfigured):
                resolve_runtime_settings(
                    {
                        "DJANGO_DEBUG": "false",
                        _SECRET_ENV: strong_key,
                        "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com",
                        "DJANGO_CACHE_PATH": ":memory:",
                        "DJANGO_EMAIL_BACKEND": FILEBASED_EMAIL_BACKEND,
                    },
                    base_dir=base,
                )

            for bad_hops in ("-1", "11", "proxy"):
                with self.subTest(hops=bad_hops):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                "DJANGO_DEBUG": "true",
                                "DJANGO_CACHE_PATH": ":memory:",
                                "DJANGO_TRUSTED_PROXY_COUNT": bad_hops,
                            },
                            base_dir=base,
                        )

    def test_production_mode_requires_explicit_email_backend_and_encrypted_smtp(
        self,
    ) -> None:
        strong_key = _make_prod_key()
        v_auth = secrets.token_urlsafe(18)
        with tempfile.TemporaryDirectory(prefix="ceilf6-email-cfg-") as tmp_dir:
            base = Path(tmp_dir)
            base_prod_env = {
                "DJANGO_DEBUG": "false",
                _SECRET_ENV: strong_key,
                "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com,127.0.0.1",
                "DJANGO_TRUSTED_PROXY_COUNT": "1",
                "DJANGO_CACHE_PATH": ":memory:",
            }

            # Missing or non-production DJANGO_EMAIL_BACKEND in production fails closed
            with self.assertRaises(ImproperlyConfigured):
                resolve_runtime_settings(base_prod_env, base_dir=base)

            for disallowed_backend in (
                "django.core.mail.backends.console.EmailBackend",
                "django.core.mail.backends.locmem.EmailBackend",
                "django.core.mail.backends.dummy.EmailBackend",
                "custom.untrusted.EmailBackend",
            ):
                with self.subTest(email_backend=disallowed_backend):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                **base_prod_env,
                                "DJANGO_EMAIL_BACKEND": disallowed_backend,
                            },
                            base_dir=base,
                        )

            # Explicit filebased in production creates 0700 directory
            file_mail_dir = base / "prod-mail"
            file_cfg = resolve_runtime_settings(
                {
                    **base_prod_env,
                    "DJANGO_EMAIL_BACKEND": FILEBASED_EMAIL_BACKEND,
                    "EMAIL_FILE_PATH": str(file_mail_dir),
                },
                base_dir=base,
            )
            self.assertEqual(file_cfg.email_backend, FILEBASED_EMAIL_BACKEND)
            self.assertTrue(file_mail_dir.is_dir())
            self.assertEqual(
                stat.S_IMODE(file_mail_dir.stat().st_mode), 0o700
            )

            invalid_smtp_overrides = [
                {"DJANGO_EMAIL_USE_SSL": "true"},
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_PORT": "25",
                    "DJANGO_EMAIL_USE_TLS": "true",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_PORT": "2525",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_SSL": "true",
                    "DJANGO_EMAIL_USE_TLS": "true",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_PORT": "465",
                    "DJANGO_EMAIL_USE_TLS": "true",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_PORT": "587",
                    "DJANGO_EMAIL_USE_SSL": "true",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_SSL": "true",
                    "DJANGO_EMAIL_PORT": "0",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_SSL": "true",
                    "DJANGO_EMAIL_PORT": "70000",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_SSL": "true",
                    "DJANGO_EMAIL_PORT": "smtp",
                },
                {
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_SSL": "true",
                    "DJANGO_EMAIL_TIMEOUT": "0",
                },
            ]
            for bad_smtp in invalid_smtp_overrides:
                with self.subTest(smtp=bad_smtp):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                **base_prod_env,
                                "DJANGO_EMAIL_BACKEND": SMTP_EMAIL_BACKEND,
                                **bad_smtp,
                            },
                            base_dir=base,
                        )

            unused_mail_dir = base / "unused-smtp-mail"
            ssl_cfg = resolve_runtime_settings(
                {
                    **base_prod_env,
                    "DJANGO_EMAIL_BACKEND": SMTP_EMAIL_BACKEND,
                    "EMAIL_FILE_PATH": str(unused_mail_dir),
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_SSL": "true",
                    "DJANGO_EMAIL_HOST_USER": "mailer@example.com",
                    _SMTP_AUTH_ENV: v_auth,
                    "DJANGO_EMAIL_TIMEOUT": "15",
                    "DJANGO_DEFAULT_FROM_EMAIL": "noreply@wangjinghong.com",
                },
                base_dir=base,
            )
            self.assertEqual(ssl_cfg.email_backend, SMTP_EMAIL_BACKEND)
            self.assertEqual(ssl_cfg.email_host, "smtp.example.com")
            self.assertEqual(ssl_cfg.email_port, 465)
            self.assertTrue(ssl_cfg.email_use_ssl)
            self.assertFalse(ssl_cfg.email_use_tls)
            self.assertEqual(ssl_cfg.email_host_user, "mailer@example.com")
            self.assertEqual(ssl_cfg.email_host_password, v_auth)
            self.assertEqual(ssl_cfg.email_timeout, 15)
            self.assertEqual(
                ssl_cfg.default_from_email, "noreply@wangjinghong.com"
            )
            self.assertFalse(unused_mail_dir.exists())

            tls_cfg = resolve_runtime_settings(
                {
                    **base_prod_env,
                    "DJANGO_EMAIL_BACKEND": SMTP_EMAIL_BACKEND,
                    "DJANGO_EMAIL_HOST": "smtp.example.com",
                    "DJANGO_EMAIL_USE_TLS": "true",
                },
                base_dir=base,
            )
            self.assertEqual(tls_cfg.email_port, 587)
            self.assertTrue(tls_cfg.email_use_tls)
            self.assertFalse(tls_cfg.email_use_ssl)

    def test_production_mode_rejects_weak_placeholder_or_low_diversity_keys(
        self,
    ) -> None:
        insecure_candidates = [
            "",
            LOCAL_DEV_SECRET_KEY,
            EXAMPLE_SECRET_KEY_PLACEHOLDER,
            "django-insecure-" + ("x" * 60),
            "change-me",
            "x" * 49,
            "a" * 60,
        ]
        with tempfile.TemporaryDirectory(prefix="ceilf6-prod-cfg-") as tmp_dir:
            base = Path(tmp_dir)
            for candidate in insecure_candidates:
                with self.subTest(length=len(candidate)):
                    env = {
                        "DJANGO_DEBUG": "false",
                        _SECRET_ENV: candidate,
                        "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com",
                        "DJANGO_TRUSTED_PROXY_COUNT": "1",
                        "DJANGO_CACHE_PATH": ":memory:",
                        "DJANGO_EMAIL_BACKEND": FILEBASED_EMAIL_BACKEND,
                    }
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(env, base_dir=base)

    def test_production_mode_accepts_strong_key_and_rejects_empty_or_wildcard_hosts(
        self,
    ) -> None:
        strong_key = _make_prod_key()
        with tempfile.TemporaryDirectory(prefix="ceilf6-prod-ok-") as tmp_dir:
            base = Path(tmp_dir)
            cfg = resolve_runtime_settings(
                {
                    "DJANGO_DEBUG": "false",
                    _SECRET_ENV: strong_key,
                    "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com, 127.0.0.1, localhost",
                    "DJANGO_TRUSTED_PROXY_COUNT": "1",
                    "DJANGO_CACHE_PATH": ":memory:",
                    "DJANGO_EMAIL_BACKEND": FILEBASED_EMAIL_BACKEND,
                    "DJANGO_ADMIN_PATH": "/ops-panel",
                },
                base_dir=base,
            )
            self.assertFalse(cfg.debug)
            self.assertEqual(cfg.secret_key, strong_key)
            self.assertEqual(
                cfg.allowed_hosts,
                ["www.wangjinghong.com", "127.0.0.1", "localhost"],
            )
            self.assertEqual(cfg.trusted_proxy_count, 1)
            self.assertEqual(cfg.admin_path, "ops-panel/")

            for bad_hosts in ("", "*", "www.wangjinghong.com,*"):
                with self.subTest(allowed_hosts=bad_hosts):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                "DJANGO_DEBUG": "false",
                                _SECRET_ENV: strong_key,
                                "DJANGO_ALLOWED_HOSTS": bad_hosts,
                                "DJANGO_TRUSTED_PROXY_COUNT": "1",
                                "DJANGO_CACHE_PATH": ":memory:",
                                "DJANGO_EMAIL_BACKEND": FILEBASED_EMAIL_BACKEND,
                            },
                            base_dir=base,
                        )

    def test_manage_py_rejects_explicit_debug_false_without_secret_key(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-prod-proc-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = _isolated_env(tmp_path, DJANGO_DEBUG="false")
            proc = _run_manage("check", env=env)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(_SECRET_ENV, proc.stderr)

    def test_dotenv_debug_false_overrides_manage_py_default_and_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-env-prec-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            dotenv_file = tmp_path / ".env"
            dotenv_file.write_text("DJANGO_DEBUG=false\n", encoding="utf-8")

            env = _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(dotenv_file))
            proc = _run_manage("check", env=env)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(_SECRET_ENV, proc.stderr)

    def test_production_settings_enforce_https_cookies_and_deploy_check(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-prod-sec-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = _isolated_env(
                tmp_path,
                DJANGO_DEBUG="false",
                **{_SECRET_ENV: _make_prod_key()},
                DJANGO_ALLOWED_HOSTS="www.wangjinghong.com,127.0.0.1",
                DJANGO_TRUSTED_PROXY_COUNT="1",
                DJANGO_EMAIL_BACKEND=SMTP_EMAIL_BACKEND,
                DJANGO_EMAIL_HOST="smtp.example.com",
                DJANGO_EMAIL_USE_SSL="true",
            )
            probe = _run_python_code(
                "import django, os; "
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
                "django.setup(); "
                "from django.conf import settings; "
                "assert settings.SESSION_COOKIE_SECURE is True; "
                "assert settings.SESSION_COOKIE_HTTPONLY is True; "
                "assert settings.SESSION_COOKIE_SAMESITE == 'Lax'; "
                "assert settings.CSRF_COOKIE_SECURE is True; "
                "assert settings.CSRF_COOKIE_HTTPONLY is True; "
                "assert settings.CSRF_COOKIE_SAMESITE == 'Lax'; "
                "assert settings.ALLAUTH_TRUSTED_PROXY_COUNT == 1; "
                "assert settings.ACCOUNT_DEFAULT_HTTP_PROTOCOL == 'https'",
                env=env,
            )
            self.assertEqual(
                probe.returncode,
                0,
                msg=f"Production security probe failed:\n{probe.stdout}\n{probe.stderr}",
            )
            deploy_check = _run_manage("check", "--deploy", env=env)
            self.assertEqual(
                deploy_check.returncode,
                0,
                msg=f"check --deploy failed:\n{deploy_check.stdout}\n{deploy_check.stderr}",
            )
            warning_ids = set(
                re.findall(r"\(([A-Za-z0-9_.]+\.W\d+)\)", deploy_check.stderr)
            )
            self.assertTrue(
                warning_ids.issubset({"security.W004", "security.W008"}),
                msg=f"Unexpected deploy warnings: {warning_ids}\n{deploy_check.stderr}",
            )

    def test_bootstrap_env_precedence_process_beats_dotenv_beats_default(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-boot-env-") as tmp_dir:
            base = Path(tmp_dir)
            dotenv_path = base / ".env"
            dotenv_path.write_text(
                "# comment\n"
                "DJANGO_DEBUG=false\n"
                "DJANGO_ALLOWED_HOSTS='dotenv.example.com'\n"
                "export DJANGO_ADMIN_PATH=dotenv-admin/\n",
                encoding="utf-8",
            )

            target_proc = {
                "DJANGO_DEBUG": "true",
                "DJANGO_ALLOWED_HOSTS": "process.example.com",
            }
            load_dotenv_file(dotenv_path, target_proc)
            bootstrap_env(
                default_debug="true", environ=target_proc, base_dir=base
            )
            self.assertEqual(target_proc["DJANGO_DEBUG"], "true")
            self.assertEqual(
                target_proc["DJANGO_ALLOWED_HOSTS"], "process.example.com"
            )
            self.assertEqual(target_proc["DJANGO_ADMIN_PATH"], "dotenv-admin/")

            target_dotenv: dict[str, str] = {}
            bootstrap_env(
                default_debug="true", environ=target_dotenv, base_dir=base
            )
            self.assertEqual(target_dotenv["DJANGO_DEBUG"], "false")

    def test_invalid_boolean_and_colliding_admin_path_raise_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-invalid-") as tmp_dir:
            base = Path(tmp_dir)
            with self.assertRaises(ImproperlyConfigured):
                resolve_runtime_settings(
                    {"DJANGO_DEBUG": "flase"}, base_dir=base
                )
            for bad_admin in (
                "",
                "/",
                "api/admin/",
                "accounts/admin/",
                "static/admin/",
                "django-static/admin/",
                "../admin/",
                "admin//nested/",
                "admin?next=/evil",
                "admin#frag",
                "admin%2fpanel",
                "admin&x=1",
                "admin panel/",
                "admin\npanel/",
            ):
                with self.subTest(admin_path=bad_admin):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                "DJANGO_DEBUG": "true",
                                "DJANGO_CACHE_PATH": ":memory:",
                                "DJANGO_ADMIN_PATH": bad_admin,
                            },
                            base_dir=base,
                        )


class WsgiEntrypointTests(SimpleTestCase):
    def test_verbatim_dotenv_example_fails_closed_for_wsgi_while_manage_py_works(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-env-example-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            copied_dotenv = tmp_path / ".env"
            shutil.copyfile(BASE_DIR / ".env.example", copied_dotenv)
            env = _isolated_env(
                tmp_path, DJANGO_DOTENV_PATH=str(copied_dotenv)
            )

            wsgi_import = _run_python_code("import config.wsgi", env=env)
            self.assertNotEqual(wsgi_import.returncode, 0)
            self.assertIn(_SECRET_ENV, wsgi_import.stderr)

            manage_proc = _run_manage("check", env=env)
            self.assertEqual(
                manage_proc.returncode,
                0,
                msg=f"manage.py check with .env.example failed:\n{manage_proc.stdout}\n{manage_proc.stderr}",
            )

    def test_wsgi_import_fails_closed_when_unconfigured_or_dotenv_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-wsgi-fail-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            empty_dotenv = tmp_path / ".env"
            empty_dotenv.write_text("# empty dotenv\n", encoding="utf-8")
            env = _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(empty_dotenv))

            import_proc = _run_python_code("import config.wsgi", env=env)
            self.assertNotEqual(import_proc.returncode, 0)
            self.assertIn(_SECRET_ENV, import_proc.stderr)

    @unittest.skipIf(
        sys.platform == "win32", "gunicorn does not support Windows"
    )
    def test_gunicorn_fails_closed_on_example_or_empty_dotenv_and_succeeds_when_configured(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-gunicorn-") as tmp_dir:
            tmp_path = Path(tmp_dir)

            copied_dotenv = tmp_path / ".env.copy"
            shutil.copyfile(BASE_DIR / ".env.example", copied_dotenv)
            example_proc = _gunicorn_check(
                _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(copied_dotenv))
            )
            self.assertNotEqual(example_proc.returncode, 0)

            empty_dotenv = tmp_path / ".env.empty"
            empty_dotenv.write_text("# empty\n", encoding="utf-8")
            empty_proc = _gunicorn_check(
                _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(empty_dotenv))
            )
            self.assertNotEqual(empty_proc.returncode, 0)

            dev_dotenv = tmp_path / ".env.dev"
            dev_dotenv.write_text("DJANGO_DEBUG=true\n", encoding="utf-8")
            dev_proc = _gunicorn_check(
                _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(dev_dotenv))
            )
            self.assertEqual(
                dev_proc.returncode,
                0,
                msg=f"dev gunicorn failed:\n{dev_proc.stdout}\n{dev_proc.stderr}",
            )

            prod_mail_dir = tmp_path / "unused-smtp-mail"
            prod_env = _isolated_env(
                tmp_path,
                DJANGO_DEBUG="false",
                **{_SECRET_ENV: _make_prod_key()},
                DJANGO_ALLOWED_HOSTS="www.wangjinghong.com,127.0.0.1,localhost",
                DJANGO_TRUSTED_PROXY_COUNT="1",
                DJANGO_EMAIL_BACKEND=SMTP_EMAIL_BACKEND,
                DJANGO_EMAIL_HOST="smtp.example.com",
                DJANGO_EMAIL_USE_SSL="true",
                EMAIL_FILE_PATH=str(prod_mail_dir),
            )
            prod_proc = _gunicorn_check(prod_env)
            self.assertEqual(
                prod_proc.returncode,
                0,
                msg=f"prod gunicorn failed:\n{prod_proc.stdout}\n{prod_proc.stderr}",
            )
            self.assertFalse(prod_mail_dir.exists())
