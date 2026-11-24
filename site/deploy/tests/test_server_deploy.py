"""Sandbox E2E tests for deploy, conditional DB rollback, venv switching, and history stack."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import stat
import time
import unittest
from pathlib import Path
from unittest import mock

from deploy import remote_server
from deploy.remote_server import main as remote_main
from deploy.tests.helpers import DeploySandbox


class SandboxDeployAndRollbackIntegrationTests(unittest.TestCase):
    def _cli_args(
        self,
        sbx: DeploySandbox,
        *,
        keep_releases: int = 5,
        keep_backups: int = 10,
        retries: int = 12,
    ) -> list[str]:
        return [
            "--app-root",
            str(sbx.app_root),
            "--etc-env",
            str(sbx.etc_env),
            "--var-dir",
            str(sbx.var_dir),
            "--lock-file",
            str(sbx.lock_file),
            "--systemctl-bin",
            str(sbx.systemctl_bin),
            "--health-url",
            sbx.health_url,
            "--keep-releases",
            str(keep_releases),
            "--keep-backups",
            str(keep_backups),
            "--health-retries",
            str(retries),
            "--health-interval",
            "0.1",
            "--health-timeout",
            "2.0",
        ]

    def test_v1_v2_upgrade_v3_migration_rollback_and_consecutive_history_rollback(self) -> None:
        sbx = DeploySandbox(env_mode=0o640)
        self.addCleanup(sbx.close)

        # 1. First deploy v1
        staged_v1 = sbx.clone_staged_server("v1")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v1), "--release-id", "v1", *self._cli_args(sbx)]),
            0,
        )
        self.assertEqual(stat.S_IMODE(sbx.var_dir.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE((sbx.var_dir / "backups").stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE((sbx.var_dir / "cache").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((sbx.var_dir / "mail").stat().st_mode), 0o700)
        self.assertTrue((sbx.app_root / "releases" / "v1" / ".activated").is_file())
        self.assertTrue(
            (sbx.app_root / "releases" / "v1" / "server" / "staticfiles" / "admin" / "css" / "base.css").is_file()
        )

        h_status, h_hdrs, h_body = sbx.http_request("/api/health/")
        self.assertEqual(h_status, 200)
        self.assertIn("no-store", h_hdrs.get("cache-control", ""))
        self.assertEqual(h_body, {"status": "ok"})

        created_v1 = sbx.post_guest_comment("cc-source-analysis", "持久化评论：v1 写入跨升级不丢失", client_ipv6="2001:db8::10")
        v1_comment_id = created_v1["id"]

        # 2. Upgrade deploy v2
        time.sleep(0.02)
        staged_v2 = sbx.clone_staged_server("v2")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v2), "--release-id", "v2", *self._cli_args(sbx)]),
            0,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2").resolve())

        v2_backups = sorted((sbx.var_dir / "backups").glob("db-*-v2.sqlite3"))
        self.assertEqual(len(v2_backups), 1)
        self.assertEqual(stat.S_IMODE(v2_backups[0].stat().st_mode), 0o600)
        with contextlib.closing(sqlite3.connect(str(v2_backups[0]))) as bconn:
            self.assertEqual(bconn.execute("PRAGMA integrity_check").fetchall(), [("ok",)])

        list_status, _, list_v2 = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual(list_status, 200)
        self.assertEqual([c["id"] for c in list_v2["items"]], [v1_comment_id])
        self.assertEqual(sbx.sentinel_file.read_text(encoding="utf-8"), sbx.sentinel_content)
        self.assertEqual(sbx.sentinel_file.stat().st_mtime_ns, sbx.sentinel_mtime_ns)

        # 3. Broken v3-broken with DB-polluting migration + HTTP 500 health check -> restores DB & v2
        staged_v3_bad = sbx.clone_staged_server("v3-broken")
        (staged_v3_bad / "comments" / "migrations" / "0002_broken_pollute.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RunSQL(\n"
            "            \"UPDATE comments_comment SET body = 'POLLUTED-BY-V3'; \"\n"
            "            \"CREATE TABLE broken_v3_marker (id INTEGER PRIMARY KEY);\"\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        views_py = staged_v3_bad / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            remote_main(
                ["deploy", "--staged-server", str(staged_v3_bad), "--release-id", "v3-broken", *self._cli_args(sbx, retries=3)]
            ),
            1,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2").resolve())
        self.assertFalse((sbx.app_root / "releases" / "v3-broken").exists())

        _, _, list_after_rb = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in list_after_rb["items"]], [v1_comment_id])
        self.assertEqual(list_after_rb["items"][0]["body"], "持久化评论：v1 写入跨升级不丢失")
        with contextlib.closing(sqlite3.connect(str(sbx.var_dir / "db.sqlite3"))) as db_conn:
            tables = {r[0] for r in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertNotIn("broken_v3_marker", tables)

        # 4. Deploy healthy v3, then consecutive no-arg rollbacks walk v3 -> v2 -> v1!
        staged_v3_ok = sbx.clone_staged_server("v3")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v3_ok), "--release-id", "v3", *self._cli_args(sbx)]),
            0,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v3").resolve())

        created_v3 = sbx.post_guest_comment("cc-source-analysis", "v3 新增评论", client_ipv6="2001:db8::20")
        v3_comment_id = created_v3["id"]

        # 1st no-arg rollback: v3 -> v2
        self.assertEqual(remote_main(["rollback", *self._cli_args(sbx)]), 0)
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2").resolve())

        # 2nd no-arg rollback: v2 -> v1 (does NOT bounce back to v3!)
        self.assertEqual(remote_main(["rollback", *self._cli_args(sbx)]), 0)
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())
        _, _, list_on_v1 = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in list_on_v1["items"]], [v3_comment_id, v1_comment_id])

        # 3rd no-arg rollback at bottom of stack fails cleanly
        self.assertEqual(remote_main(["rollback", *self._cli_args(sbx)]), 1)

        # Explicit rollback --to v2 --restore-db restores pre-v2 snapshot
        self.assertEqual(
            remote_main(["rollback", "--to", "v2", "--restore-db", v2_backups[0].name, *self._cli_args(sbx)]),
            0,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2").resolve())
        self.assertEqual(len(list((sbx.var_dir / "backups").glob("pre-rollback-*-v2.sqlite3"))), 1)
        _, _, list_restored = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in list_restored["items"]], [v1_comment_id])

    def test_no_migration_failure_keeps_window_comments_and_migrate_or_restart_errors_recover(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        staged_v1 = sbx.clone_staged_server("v1")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v1), "--release-id", "v1", *self._cli_args(sbx)]),
            0,
        )
        c1 = sbx.post_guest_comment("cc-source-analysis", "发布前已有评论", client_ipv6="2001:db8::31")

        # Case A: v2-code-bad has NO new migrations, /api/health/ returns 500.
        # Simulate a live comment arriving AFTER pre-deploy backup is taken!
        staged_code_bad = sbx.clone_staged_server("v2-code-bad")
        views_py = staged_code_bad / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )

        window_created: dict[str, int] = {}
        real_run_sqlite_op = remote_server._run_sqlite_op

        def backup_then_live_write(action: str, src: Path, dst: Path, **kwargs):
            real_run_sqlite_op(action, src, dst, **kwargs)
            if action == "backup" and "v2-code-bad" in dst.name:
                # Live user posts a comment to the still-running v1 server AFTER backup completed!
                posted = sbx.post_guest_comment(
                    "cc-source-analysis",
                    "备份后发布窗口内写入的新评论（严禁丢失）",
                    client_ipv6="2001:db8::32",
                )
                window_created["id"] = posted["id"]

        with mock.patch.object(remote_server, "_run_sqlite_op", side_effect=backup_then_live_write):
            rc = remote_main(
                ["deploy", "--staged-server", str(staged_code_bad), "--release-id", "v2-code-bad", *self._cli_args(sbx, retries=3)]
            )
        self.assertEqual(rc, 1)
        self.assertIn("id", window_created)
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())

        # Both c1 AND the comment written AFTER backup MUST still exist!
        _, _, comments_after = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in comments_after["items"]], [window_created["id"], c1["id"]])

        # Case B1: `migrate` itself fails mid-SQL -> restores backup & restarts v1 healthy
        staged_bad_mig = sbx.clone_staged_server("v2-bad-mig")
        (staged_bad_mig / "comments" / "migrations" / "0002_bad_sql.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RunSQL(\"DELETE FROM comments_comment; SELECT * FROM missing_tbl;\"),\n"
            "    ]\n",
            encoding="utf-8",
        )
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_bad_mig), "--release-id", "v2-bad-mig", *self._cli_args(sbx)]),
            1,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())
        _, _, comments_after_mig = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in comments_after_mig["items"]], [window_created["id"], c1["id"]])

        # Case B2: `systemctl restart` fails via fail_next_restart -> recovers back to v1 healthy
        staged_v2_ok = sbx.clone_staged_server("v2-restart-fail")
        (sbx.root / "fail_next_restart").write_text("1\n", encoding="utf-8")
        self.assertEqual(
            remote_main(
                ["deploy", "--staged-server", str(staged_v2_ok), "--release-id", "v2-restart-fail", *self._cli_args(sbx)]
            ),
            1,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())
        h_status, _, _ = sbx.http_request("/api/health/")
        self.assertEqual(h_status, 200)

    def test_corrupt_restore_db_venv_switch_rollback_backup_fail_and_pruning(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        # 1. First-deploy failure cleans up newly created db.sqlite3 and current symlink
        bad_initial = sbx.clone_staged_server("v0-broken")
        views_v0 = bad_initial / "config" / "views.py"
        views_v0.write_text(
            views_v0.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "unavailable"}, status=503)',
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(bad_initial), "--release-id", "v0-broken", *self._cli_args(sbx, retries=3)]),
            1,
        )
        self.assertFalse((sbx.app_root / "current").is_symlink())
        self.assertFalse((sbx.var_dir / "db.sqlite3").exists())
        self.assertFalse((sbx.app_root / "releases" / "v0-broken").exists())

        # Deploy rel-1 and rel-2
        for idx in (1, 2):
            time.sleep(0.02)
            staged = sbx.clone_staged_server(f"rel-{idx}")
            self.assertEqual(
                remote_main(["deploy", "--staged-server", str(staged), "--release-id", f"rel-{idx}", *self._cli_args(sbx)]),
                0,
            )
        rel1_venv_target = (sbx.app_root / "shared" / "venv").resolve()

        # 2. Backup failure during deploy cleans up staged dir so no-arg rollback never hits it
        staged_bk_fail = sbx.clone_staged_server("rel-bk-fail")
        with mock.patch.object(remote_server, "_run_sqlite_op", side_effect=remote_server.DeployError("disk full")):
            self.assertEqual(
                remote_main(["deploy", "--staged-server", str(staged_bk_fail), "--release-id", "rel-bk-fail", *self._cli_args(sbx)]),
                1,
            )
        self.assertFalse((sbx.app_root / "releases" / "rel-bk-fail").exists())

        # 3. Changed requirements.txt in failed deploy switches shared/venv back to prior venv!
        staged_dep_bad = sbx.clone_staged_server("rel-dep-bad")
        req_file = staged_dep_bad / "requirements.txt"
        req_file.write_text(req_file.read_text(encoding="utf-8") + "# pin-variant-for-venv-test\n", encoding="utf-8")
        alt_sha = hashlib.sha256(req_file.read_bytes()).hexdigest()[:16]
        alt_venv_dir = sbx.app_root / "shared" / "venvs" / alt_sha
        alt_venv_dir.mkdir(parents=True)
        for entry in sbx.venv_source.iterdir():
            if entry.name != ".requirements.sha256":
                os.symlink(str(entry), str(alt_venv_dir / entry.name))
        (alt_venv_dir / ".requirements.sha256").write_text(
            f"{hashlib.sha256(req_file.read_bytes()).hexdigest()}\n",
            encoding="utf-8",
        )
        views_dep = staged_dep_bad / "config" / "views.py"
        views_dep.write_text(
            views_dep.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_dep_bad), "--release-id", "rel-dep-bad", *self._cli_args(sbx, retries=3)]),
            1,
        )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "rel-2").resolve())
        self.assertEqual((sbx.app_root / "shared" / "venv").resolve(), rel1_venv_target)
        self.assertFalse(alt_venv_dir.exists())

        # 4. Corrupt --restore-db AND mid-restore failure both keep service running & healthy!
        corrupt_bk = sbx.var_dir / "backups" / "db-corrupt.sqlite3"
        corrupt_bk.write_bytes(b"not-a-valid-sqlite3-file")
        self.assertEqual(
            remote_main(["rollback", "--to", "rel-1", "--restore-db", corrupt_bk.name, *self._cli_args(sbx)]),
            1,
        )
        corrupt_bk.unlink()
        h_code, _, _ = sbx.http_request("/api/health/")
        self.assertEqual(h_code, 200)

        valid_bk = sorted((sbx.var_dir / "backups").glob("db-*-rel-2.sqlite3"))[0]
        orig_op = remote_server._run_sqlite_op

        def fail_on_first_restore(action: str, src: Path, dst: Path, **kwargs):
            if action == "restore" and src.resolve() == valid_bk.resolve():
                raise remote_server.DeployError("simulated mid-restore I/O error")
            return orig_op(action, src, dst, **kwargs)

        with mock.patch.object(remote_server, "_run_sqlite_op", side_effect=fail_on_first_restore):
            self.assertEqual(
                remote_main(["rollback", "--to", "rel-1", "--restore-db", valid_bk.name, *self._cli_args(sbx)]),
                1,
            )
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "rel-2").resolve())
        h_code_after, _, _ = sbx.http_request("/api/health/")
        self.assertEqual(h_code_after, 200)

        # 5. Disaster recovery: `rollback --restore-db` heals a corrupted or 0-byte live db.sqlite3!
        for corrupt_payload in (b"corrupted-live-sqlite-bytes", b""):
            (sbx.var_dir / "db.sqlite3").write_bytes(corrupt_payload)
            for sidecar in ("-wal", "-shm"):
                Path(f"{sbx.var_dir / 'db.sqlite3'}{sidecar}").unlink(missing_ok=True)
            self.assertEqual(
                remote_main(["rollback", "--to", "rel-2", "--restore-db", valid_bk.name, *self._cli_args(sbx)]),
                0,
            )
            self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())
            healed_code, _, _ = sbx.http_request("/api/health/")
            self.assertEqual(healed_code, 200)

        # 6. Retention pruning covers BOTH db-*.sqlite3 AND pre-rollback-*.sqlite3!
        for idx in (3, 4):
            time.sleep(0.02)
            staged = sbx.clone_staged_server(f"rel-{idx}")
            self.assertEqual(
                remote_main(
                    ["deploy", "--staged-server", str(staged), "--release-id", f"rel-{idx}", *self._cli_args(sbx, keep_releases=2, keep_backups=2)]
                ),
                0,
            )
        remaining_releases = sorted(d.name for d in (sbx.app_root / "releases").iterdir() if d.is_dir())
        self.assertEqual(remaining_releases, ["rel-3", "rel-4"])
        all_snaps = list((sbx.var_dir / "backups").glob("*.sqlite3"))
        self.assertEqual(len(all_snaps), 2)


if __name__ == "__main__":
    unittest.main()
