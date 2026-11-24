"""Unit tests for publish-server.sh (real OpenSSH quoting), runtime.py, and sqlite_ops.py."""

from __future__ import annotations

import contextlib
import hashlib
import os
import pwd
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from deploy import sqlite_ops
from deploy.runtime import (
    DeployError,
    build_runtime_env,
    ensure_release_venv,
    is_healthy_payload,
    load_and_validate_env_file,
    normalize_tree_permissions,
    prepare_var_dirs,
    validate_release_id,
)
from deploy.tests.helpers import DEPLOY_DIR, SITE_DIR, DeploySandbox

PUBLISH_SH = DEPLOY_DIR / "publish-server.sh"
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class PublishServerScriptTests(unittest.TestCase):
    def test_bash_syntax_and_zero_hardcoded_ips_or_keys_in_deploy_dir(self) -> None:
        syntax = subprocess.run(["bash", "-n", str(PUBLISH_SH)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        for path in sorted(DEPLOY_DIR.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            content = path.read_text(encoding="utf-8")
            for match in IPV4_RE.findall(content):
                self.assertEqual(
                    match,
                    "127.0.0.1",
                    f"Non-loopback IPv4 literal {match!r} found in {path.relative_to(SITE_DIR)}",
                )
            for header in (
                "BEGIN " + "OPENSSH PRIVATE KEY",
                "BEGIN " + "RSA PRIVATE KEY",
                "BEGIN " + "PRIVATE KEY",
            ):
                self.assertNotIn(header, content)

    def test_cli_usage_host_user_and_restore_db_rejected_when_invalid(self) -> None:
        base_env = {k: v for k, v in os.environ.items() if k not in {"DEPLOY_HOST", "DEPLOY_USER"}}

        for bad_args, extra_env in (
            ([], {}),
            (["status"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["deploy", "--extra"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["deploy"], {}),
            (["deploy"], {"DEPLOY_HOST": ""}),
            (["deploy"], {"DEPLOY_HOST": "-oProxyCommand=evil"}),
            (["deploy"], {"DEPLOY_HOST": "bad host"}),
            (["deploy"], {"DEPLOY_HOST": "ecs.example.invalid", "DEPLOY_USER": "root;id"}),
            (["deploy"], {"DEPLOY_HOST": "ecs.example.invalid", "DEPLOY_USER": "-bad"}),
            (["deploy"], {"DEPLOY_HOST": "ecs.example.invalid", "DEPLOY_USER": "9bad"}),
            (["deploy"], {"DEPLOY_HOST": "ecs.example.invalid", "RELEASE_ID": "../escape"}),
            (["rollback", "--unknown"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["rollback", "--to"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["rollback", "--to", "bad/id"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["rollback", "--restore-db"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["rollback", "--restore-db", "../outside.sqlite3"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["rollback", "--restore-db", "sub/db.sqlite3"], {"DEPLOY_HOST": "ecs.example.invalid"}),
            (["rollback", "--restore-db", "db.sqlite3;id"], {"DEPLOY_HOST": "ecs.example.invalid"}),
        ):
            with self.subTest(args=bad_args, env=extra_env):
                res = subprocess.run(
                    ["bash", str(PUBLISH_SH), *bad_args],
                    env={**base_env, **extra_env},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, 2, f"Expected exit 2, got {res.returncode}: {res.stderr}")

        missing_key = subprocess.run(
            ["bash", str(PUBLISH_SH), "deploy"],
            env={
                **base_env,
                "DEPLOY_HOST": "ecs.example.invalid",
                "DEPLOY_KEY": "/nonexistent/key.pem",
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(missing_key.returncode, 1)
        self.assertIn("DEPLOY_KEY", missing_key.stderr)

    def test_publish_server_sh_with_real_openssh_concat_behavior(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        dummy_key = sbx.root / "dummy_id_ed25519"
        dummy_key.write_text("placeholder-not-a-real-key\n", encoding="utf-8")
        dummy_key.chmod(0o600)

        # Exact OpenSSH remote shell semantics: concatenates all post-host args with single spaces.
        ssh_stub = sbx.bin_dir / "fake-ssh"
        ssh_stub.write_text(
            "#!/usr/bin/env bash\n"
            "while [ $# -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -i|-o) shift 2 ;;\n"
            "    *@*) shift; break ;;\n"
            "    *) break ;;\n"
            "  esac\n"
            "done\n"
            "exec bash -c \"$*\"\n",
            encoding="utf-8",
        )
        ssh_stub.chmod(0o755)

        scp_stub = sbx.bin_dir / "fake-scp"
        scp_stub.write_text(
            "#!/usr/bin/env bash\n"
            "args=()\n"
            "while [ $# -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -i|-o) shift 2 ;;\n"
            "    *) args+=(\"$1\"); shift ;;\n"
            "  esac\n"
            "done\n"
            "last_idx=$(( ${#args[@]} - 1 ))\n"
            "dest=${args[$last_idx]#*:}\n"
            "unset 'args[$last_idx]'\n"
            "cp \"${args[@]}\" \"$dest\"\n",
            encoding="utf-8",
        )
        scp_stub.chmod(0o755)

        os.symlink(str(sbx.systemctl_bin), str(sbx.bin_dir / "systemctl"))
        env = {
            **os.environ,
            "PATH": f"{sbx.bin_dir}:{os.environ.get('PATH', '')}",
            "DEPLOY_HOST": "ecs.example.invalid",
            "DEPLOY_USER": "ops_user",
            "DEPLOY_KEY": str(dummy_key),
            "SSH_BIN": str(ssh_stub),
            "SCP_BIN": str(scp_stub),
            "REMOTE_APP_ROOT": str(sbx.app_root),
            "REMOTE_ETC_ENV": str(sbx.etc_env),
            "REMOTE_VAR_DIR": str(sbx.var_dir),
            "REMOTE_LOCK_FILE": str(sbx.lock_file),
            "HEALTH_URL": sbx.health_url,
        }

        for rel_id in ("sh-rel-1", "sh-rel-2"):
            time.sleep(0.02)
            res = subprocess.run(
                ["bash", str(PUBLISH_SH), "deploy"],
                env={**env, "RELEASE_ID": rel_id},
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

        # No-arg rollback passes empty ROLLBACK_TO="" and RESTORE_DB="" through `bash -c "$*"`!
        rb_no_args = subprocess.run(
            ["bash", str(PUBLISH_SH), "rollback"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rb_no_args.returncode, 0, f"{rb_no_args.stdout}\n{rb_no_args.stderr}")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "sh-rel-1").resolve())

        backups = sorted((sbx.var_dir / "backups").glob("db-*-sh-rel-2.sqlite3"))
        self.assertEqual(len(backups), 1)
        rb_with_db = subprocess.run(
            ["bash", str(PUBLISH_SH), "rollback", "--to", "sh-rel-2", "--restore-db", backups[0].name],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rb_with_db.returncode, 0, f"{rb_with_db.stdout}\n{rb_with_db.stderr}")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "sh-rel-2").resolve())


class RuntimeAndSqliteOpsUnitTests(unittest.TestCase):
    def test_sqlite_ops_verify_backup_restore_and_cli(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="sqlite-ops-unit-"))
        self.addCleanup(shutil.rmtree, tmp, True)

        src_db = tmp / "live.sqlite3"
        with contextlib.closing(sqlite3.connect(str(src_db))) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
            conn.execute("INSERT INTO items (label) VALUES ('alpha')")
            conn.commit()

        snap = tmp / "snap.sqlite3"
        self.assertEqual(sqlite_ops.main(["backup", str(src_db), str(snap)]), 0)
        self.assertEqual(stat.S_IMODE(snap.stat().st_mode), 0o600)
        self.assertEqual(sqlite_ops.main(["verify", str(snap)]), 0)

        with contextlib.closing(sqlite3.connect(str(src_db))) as conn:
            conn.execute("UPDATE items SET label='mutated'")
            conn.commit()

        self.assertEqual(sqlite_ops.main(["restore", str(snap), str(src_db)]), 0)
        with contextlib.closing(sqlite3.connect(str(src_db))) as conn:
            rows = conn.execute("SELECT label FROM items").fetchall()
        self.assertEqual(rows, [("alpha",)])

        corrupt = tmp / "corrupt.sqlite3"
        corrupt.write_bytes(b"corrupted-sqlite-header")
        self.assertEqual(sqlite_ops.main(["verify", str(corrupt)]), 1)
        self.assertEqual(sqlite_ops.main(["restore", str(corrupt), str(src_db)]), 1)

        empty = tmp / "empty.sqlite3"
        empty.write_bytes(b"")
        with self.assertRaises(sqlite_ops.SqliteOpError):
            sqlite_ops.verify_sqlite_integrity(empty)

        link = tmp / "link.sqlite3"
        os.symlink(snap, link)
        with self.assertRaises(sqlite_ops.SqliteOpError):
            sqlite_ops.verify_sqlite_integrity(link)

        # Simulate SQLITE_FULL / I/O error during restore: existing dst_db MUST remain intact!
        with contextlib.closing(sqlite3.connect(str(src_db))) as conn:
            conn.execute("UPDATE items SET label='committed-before-failed-restore'")
            conn.commit()
        real_connect = sqlite3.connect

        def fail_on_tmp_restore(path, *args, **kwargs):
            if ".restore." in str(path):
                raise sqlite3.OperationalError("database or disk is full")
            return real_connect(path, *args, **kwargs)

        with mock.patch("sqlite3.connect", side_effect=fail_on_tmp_restore):
            with self.assertRaisesRegex(sqlite_ops.SqliteOpError, "disk is full"):
                sqlite_ops.restore_sqlite_file(snap, src_db)
        with contextlib.closing(sqlite3.connect(str(src_db))) as conn:
            self.assertEqual(
                conn.execute("SELECT label FROM items").fetchall(),
                [("committed-before-failed-restore",)],
            )

    def test_env_file_systemd_syntax_and_permission_enforcement(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="env-perm-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)

        with self.assertRaisesRegex(DeployError, "does not exist"):
            load_and_validate_env_file(tmp / "missing.env")

        env_file = tmp / "server.env"
        env_file.write_text("# comment\nFOO='alpha'\nBAR=\"beta\"\nPLAIN=gamma\n", encoding="utf-8")
        os.chmod(env_file, 0o600)

        link_env = tmp / "link.env"
        os.symlink(env_file, link_env)
        with self.assertRaisesRegex(DeployError, "regular file"):
            load_and_validate_env_file(link_env)

        for insecure_mode in (0o644, 0o666, 0o660, 0o604):
            os.chmod(env_file, insecure_mode)
            with self.assertRaisesRegex(DeployError, "too open"):
                load_and_validate_env_file(env_file)

        for secure_mode in (0o600, 0o640):
            os.chmod(env_file, secure_mode)
            self.assertEqual(
                load_and_validate_env_file(env_file),
                {"FOO": "alpha", "BAR": "beta", "PLAIN": "gamma"},
            )

        for bad_line, pattern in (
            ("export FOO=alpha\n", "export"),
            ("NO_EQUALS_SIGN\n", "without '='"),
            ("BAD-KEY=1\n", "Invalid variable name"),
        ):
            env_file.write_text(bad_line, encoding="utf-8")
            os.chmod(env_file, 0o600)
            with self.assertRaisesRegex(DeployError, pattern):
                load_and_validate_env_file(env_file)

    def test_path_guards_root_service_user_fail_closed_and_venv_umask(self) -> None:
        for bad_id in ("", " ", ".", "..", "../evil", "a/b", "bad space", "semi;colon"):
            with self.assertRaises(DeployError):
                validate_release_id(bad_id)

        tmp = Path(tempfile.mkdtemp(prefix="root-guard-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        app_root = tmp / "opt" / "wangjinghong"
        var_dir = tmp / "var" / "lib" / "wangjinghong"

        for bad_sqlite in (
            "var/db.sqlite3",
            ":memory:",
            str(app_root / "releases" / "v1" / "db.sqlite3"),
            "/var/www/wangjinghong/db.sqlite3",
            "/etc/wangjinghong/db.sqlite3",
            f"{var_dir}/../escape.sqlite3",
            f"{var_dir}/backups/db-live.sqlite3",
            f"{var_dir}/cache/db.sqlite3",
            str(var_dir),
        ):
            with self.assertRaises(DeployError):
                build_runtime_env({"SQLITE_PATH": bad_sqlite}, var_dir=var_dir, app_root=app_root)

        from deploy.runtime import stage_release

        host_secret_dir = tmp / "host-secrets"
        host_secret_dir.mkdir(parents=True)
        host_secret_file = host_secret_dir / "token.txt"
        host_secret_file.write_text("TOP-SECRET-DO-NOT-COPY\n", encoding="utf-8")
        os.chmod(host_secret_file, 0o600)

        staged = tmp / "staged"
        (staged / "config").mkdir(parents=True)
        for req in ("manage.py", "requirements.txt", "config/wsgi.py"):
            (staged / req).write_text("# stub\n", encoding="utf-8")

        # 1. File symlink inside staged_server rejected at stage_release entrypoint without copying secret!
        os.symlink(host_secret_file, staged / "sneaky.py")
        with self.assertRaisesRegex(DeployError, "Symlink"):
            stage_release(staged, app_root, "rel-sym-file", None)
        self.assertFalse((app_root / "releases" / "rel-sym-file").exists())
        (staged / "sneaky.py").unlink()

        # 2. Directory symlink inside staged_server rejected at stage_release entrypoint without copying secret!
        os.symlink(host_secret_dir, staged / "sneaky_dir")
        with self.assertRaisesRegex(DeployError, "Symlink"):
            stage_release(staged, app_root, "rel-sym-dir", None)
        self.assertFalse((app_root / "releases" / "rel-sym-dir").exists())
        (staged / "sneaky_dir").unlink()

        # 3. Symlinked staged_server root itself rejected!
        staged_link = tmp / "staged-link"
        os.symlink(staged, staged_link)
        with self.assertRaisesRegex(DeployError, "symlink"):
            stage_release(staged_link, app_root, "rel-sym-root", None)

        self.assertTrue(is_healthy_payload({"status": "ok"}))
        self.assertTrue(is_healthy_payload({"ok": True}))
        for bad_payload in ({"status": "unavailable"}, {"ok": False}, {"ok": 1}, {}, []):
            self.assertFalse(is_healthy_payload(bad_payload))

        # Root mode MUST fail closed when service_user is blank or missing from pwd!
        with mock.patch("os.geteuid", return_value=0):
            with self.assertRaisesRegex(DeployError, "non-empty"):
                prepare_var_dirs(
                    var_dir,
                    sqlite_path=var_dir / "db.sqlite3",
                    cache_path=var_dir / "cache",
                    email_file_path=var_dir / "mail",
                    service_user="   ",
                )
            with mock.patch("pwd.getpwnam", side_effect=KeyError("missing")):
                with self.assertRaisesRegex(DeployError, "does not exist"):
                    prepare_var_dirs(
                        var_dir,
                        sqlite_path=var_dir / "db.sqlite3",
                        cache_path=var_dir / "cache",
                        email_file_path=var_dir / "mail",
                        service_user="nonexistent-svc-user",
                    )

        fake_pw = pwd.struct_passwd(("www-data", "x", 33, 33, "", "/var/www", "/usr/sbin/nologin"))
        (var_dir).mkdir(parents=True, exist_ok=True)
        (var_dir / "db.sqlite3").write_text("", encoding="utf-8")
        (var_dir / "db.sqlite3-wal").write_text("", encoding="utf-8")
        with (
            mock.patch("os.geteuid", return_value=0),
            mock.patch("pwd.getpwnam", return_value=fake_pw),
            mock.patch("os.fchown") as fchown_mock,
            mock.patch("os.chown", side_effect=AssertionError("os.chown must not be called; use os.fchown")),
        ):
            user, ids = prepare_var_dirs(
                var_dir,
                sqlite_path=var_dir / "db.sqlite3",
                cache_path=var_dir / "custom_cache",
                email_file_path=var_dir / "custom_mail",
                service_user="www-data",
            )
        self.assertEqual(user, "www-data")
        self.assertEqual(ids, (33, 33))
        self.assertGreaterEqual(fchown_mock.call_count, 8)

        # Service-account controllable symlinks inside var_dir MUST be rejected via O_NOFOLLOW
        # without mutating external target permissions or ownership!
        ext_dir = tmp / "protected-root-dir"
        ext_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(ext_dir, 0o755)
        ext_file = tmp / "protected-root-file"
        ext_file.write_text("do-not-touch\n", encoding="utf-8")
        os.chmod(ext_file, 0o600)

        for entry_rel, target in (
            ("cache", ext_dir),
            ("mail", ext_dir),
            ("backups", ext_dir),
            ("nested_db_dir", ext_dir),
            ("db.sqlite3", ext_file),
            ("db.sqlite3-wal", ext_file),
        ):
            victim = var_dir / entry_rel
            if victim.is_dir() and not victim.is_symlink():
                shutil.rmtree(victim)
            else:
                victim.unlink(missing_ok=True)
            os.symlink(target, victim)
            db_arg = (var_dir / "nested_db_dir" / "db.sqlite3") if entry_rel == "nested_db_dir" else (var_dir / "db.sqlite3")
            try:
                with (
                    mock.patch("os.geteuid", return_value=0),
                    mock.patch("pwd.getpwnam", return_value=fake_pw),
                    mock.patch("os.fchown"),
                ):
                    with self.assertRaises(DeployError):
                        prepare_var_dirs(
                            var_dir,
                            sqlite_path=db_arg,
                            cache_path=var_dir / "cache",
                            email_file_path=var_dir / "mail",
                            service_user="www-data",
                        )
                self.assertEqual(stat.S_IMODE(ext_dir.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE(ext_file.stat().st_mode), 0o600)
            finally:
                victim.unlink(missing_ok=True)
                if entry_rel in ("db.sqlite3", "db.sqlite3-wal"):
                    victim.write_text("", encoding="utf-8")

        sym_var = tmp / "symlink-var-root"
        os.symlink(ext_dir, sym_var)
        with self.assertRaises(DeployError):
            prepare_var_dirs(
                sym_var,
                sqlite_path=sym_var / "db.sqlite3",
                cache_path=sym_var / "cache",
                email_file_path=sym_var / "mail",
                service_user="www-data",
            )

        # Verify Ubuntu python3-venv auto-repair AND umask 022 restoration even under caller umask 077
        reqs = tmp / "requirements.txt"
        reqs.write_text("Django==5.2.19\n", encoding="utf-8")
        full_sha = hashlib.sha256(reqs.read_bytes()).hexdigest()
        venv_slot = app_root / "shared" / "venvs" / full_sha[:16]
        venv_py = venv_slot / "bin" / "python"
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            cmd_list = [str(c) for c in cmd]
            calls.append(cmd_list)
            if "-m" in cmd_list and "venv" in cmd_list:
                venv_attempts = [c for c in calls if "-m" in c and "venv" in c]
                if len(venv_attempts) == 1:
                    return subprocess.CompletedProcess(cmd_list, 1, "", "No module named ensurepip")
                venv_py.parent.mkdir(parents=True, exist_ok=True)
                venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd_list, 0, "", "")
            return subprocess.CompletedProcess(cmd_list, 0, "", "")

        prior_umask = os.umask(0o077)
        try:
            with mock.patch("os.geteuid", return_value=0), mock.patch("subprocess.run", side_effect=fake_run):
                created_slot = ensure_release_venv(app_root, reqs)
            restored_umask = os.umask(prior_umask)
            self.assertEqual(restored_umask, 0o077)
        finally:
            os.umask(prior_umask)

        self.assertEqual(created_slot, venv_slot)
        self.assertEqual(stat.S_IMODE((app_root / "shared" / "venvs").stat().st_mode), 0o755)
        self.assertTrue(any(c[:4] == ["apt-get", "install", "-y", "python3-venv"] for c in calls))
        self.assertEqual((venv_slot / ".requirements.sha256").read_text().strip(), full_sha)


if __name__ == "__main__":
    unittest.main()
