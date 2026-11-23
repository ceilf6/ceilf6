"""Tests for server configuration, SQLite WAL/IMMEDIATE, health probe, and WSGI."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
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
from config.env import bootstrap_env, load_dotenv_file
from config.settings import (
    BASE_DIR,
    EXAMPLE_SECRET_KEY_PLACEHOLDER,
    FILEBASED_EMAIL_BACKEND,
    LOCAL_DEV_SECRET_KEY,
    resolve_runtime_settings,
)

MANAGE_PY = BASE_DIR / "manage.py"
EXPECTED_NO_STORE = "private, no-store, no-cache, must-revalidate"
SMTP_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def _make_prod_secret() -> str:
    return f"prod-{secrets.token_urlsafe(48)}"


def _isolated_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    cleaned = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DJANGO_DEBUG",
            "DJANGO_SECRET_KEY",
            "DJANGO_ALLOWED_HOSTS",
            "SQLITE_PATH",
            "DJANGO_EMAIL_BACKEND",
            "EMAIL_FILE_PATH",
            "DJANGO_ADMIN_PATH",
            "DJANGO_DOTENV_PATH",
        }
    }
    cleaned["DJANGO_DOTENV_PATH"] = str(tmp_path / ".env.isolated")
    cleaned["SQLITE_PATH"] = str(tmp_path / "isolated.sqlite3")
    cleaned["EMAIL_FILE_PATH"] = str(tmp_path / "mail")
    cleaned.update(overrides)
    return cleaned


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

            first_run = subprocess.run(
                [sys.executable, str(MANAGE_PY), "migrate", "--noinput"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                first_run.returncode,
                0,
                msg=f"First migrate failed:\n{first_run.stdout}\n{first_run.stderr}",
            )
            self.assertTrue(db_path.is_file())

            second_run = subprocess.run(
                [sys.executable, str(MANAGE_PY), "migrate", "--noinput"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
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


class HealthEndpointTests(TestCase):
    def test_get_health_returns_200_ok_and_no_store(self) -> None:
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], EXPECTED_NO_STORE)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        self.assertEqual(response.json(), {"status": "ok"})

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
    def test_static_url_uses_django_static_prefix_avoiding_vite_collision(
        self,
    ) -> None:
        self.assertEqual(settings.STATIC_URL, "/django-static/")

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
            self.assertEqual(cfg.email_backend, FILEBASED_EMAIL_BACKEND)
            mail_dir = base / "var" / "mail"
            self.assertTrue(mail_dir.is_dir())
            self.assertEqual(stat.S_IMODE(mail_dir.stat().st_mode), 0o700)
            self.assertEqual(cfg.admin_path, "admin/")

    def test_smtp_email_backend_does_not_create_local_mail_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-smtp-") as tmp_dir:
            base = Path(tmp_dir)
            cfg = resolve_runtime_settings(
                {
                    "DJANGO_DEBUG": "false",
                    "DJANGO_SECRET_KEY": _make_prod_secret(),
                    "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com,127.0.0.1",
                    "DJANGO_EMAIL_BACKEND": SMTP_EMAIL_BACKEND,
                },
                base_dir=base,
            )
            self.assertEqual(cfg.email_backend, SMTP_EMAIL_BACKEND)
            self.assertFalse((base / "var" / "mail").exists())

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
                        "DJANGO_SECRET_KEY": candidate,
                        "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com",
                    }
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(env, base_dir=base)

    def test_production_mode_accepts_strong_key_and_rejects_empty_or_wildcard_hosts(
        self,
    ) -> None:
        strong_key = _make_prod_secret()
        with tempfile.TemporaryDirectory(prefix="ceilf6-prod-ok-") as tmp_dir:
            base = Path(tmp_dir)
            cfg = resolve_runtime_settings(
                {
                    "DJANGO_DEBUG": "false",
                    "DJANGO_SECRET_KEY": strong_key,
                    "DJANGO_ALLOWED_HOSTS": "www.wangjinghong.com, 127.0.0.1, localhost",
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
            self.assertEqual(cfg.admin_path, "ops-panel/")

            for bad_hosts in ("", "*", "www.wangjinghong.com,*"):
                with self.subTest(allowed_hosts=bad_hosts):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                "DJANGO_DEBUG": "false",
                                "DJANGO_SECRET_KEY": strong_key,
                                "DJANGO_ALLOWED_HOSTS": bad_hosts,
                            },
                            base_dir=base,
                        )

    def test_manage_py_rejects_explicit_debug_false_without_secret_key(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-prod-proc-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            env = _isolated_env(tmp_path, DJANGO_DEBUG="false")
            proc = subprocess.run(
                [sys.executable, str(MANAGE_PY), "check"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("DJANGO_SECRET_KEY", proc.stderr)

    def test_dotenv_debug_false_overrides_manage_py_default_and_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-env-prec-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            dotenv_file = tmp_path / ".env"
            dotenv_file.write_text("DJANGO_DEBUG=false\n", encoding="utf-8")

            env = _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(dotenv_file))
            proc = subprocess.run(
                [sys.executable, str(MANAGE_PY), "check"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("DJANGO_SECRET_KEY", proc.stderr)

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

            # Process env beats .env
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

            # .env beats entrypoint default
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
            for bad_admin in ("", "/", "api/admin/", "../admin/"):
                with self.subTest(admin_path=bad_admin):
                    with self.assertRaises(ImproperlyConfigured):
                        resolve_runtime_settings(
                            {
                                "DJANGO_DEBUG": "true",
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

            wsgi_import = subprocess.run(
                [sys.executable, "-c", "import config.wsgi"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(wsgi_import.returncode, 0)
            self.assertIn("DJANGO_SECRET_KEY", wsgi_import.stderr)

            gunicorn_proc = subprocess.run(
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
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(gunicorn_proc.returncode, 0)

            manage_proc = subprocess.run(
                [sys.executable, str(MANAGE_PY), "check"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
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

            import_proc = subprocess.run(
                [sys.executable, "-c", "import config.wsgi"],
                cwd=str(BASE_DIR),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(import_proc.returncode, 0)
            self.assertIn("DJANGO_SECRET_KEY", import_proc.stderr)

            gunicorn_proc = subprocess.run(
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
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(gunicorn_proc.returncode, 0)

    def test_dotenv_debug_true_allows_wsgi_gunicorn_in_local_dev(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-wsgi-env-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            dotenv_file = tmp_path / ".env"
            dotenv_file.write_text("DJANGO_DEBUG=true\n", encoding="utf-8")
            env = _isolated_env(tmp_path, DJANGO_DOTENV_PATH=str(dotenv_file))

            proc = subprocess.run(
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
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                msg=f"dotenv DJANGO_DEBUG=true gunicorn failed:\n{proc.stdout}\n{proc.stderr}",
            )

    def test_wsgi_and_gunicorn_succeed_with_explicit_dev_or_prod_env(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ceilf6-wsgi-ok-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            dev_env = _isolated_env(tmp_path, DJANGO_DEBUG="true")
            dev_proc = subprocess.run(
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
                env=dev_env,
                capture_output=True,
                text=True,
                check=False,
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
                DJANGO_SECRET_KEY=_make_prod_secret(),
                DJANGO_ALLOWED_HOSTS="www.wangjinghong.com,127.0.0.1,localhost",
                DJANGO_EMAIL_BACKEND=SMTP_EMAIL_BACKEND,
                EMAIL_FILE_PATH=str(prod_mail_dir),
            )
            prod_proc = subprocess.run(
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
                env=prod_env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                prod_proc.returncode,
                0,
                msg=f"prod gunicorn failed:\n{prod_proc.stdout}\n{prod_proc.stderr}",
            )
            self.assertFalse(prod_mail_dir.exists())
