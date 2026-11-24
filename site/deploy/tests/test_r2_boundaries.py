"""Round-2 boundary tests: stop failure, .maintenance gate, strict env, DELETE backup, legacy venv."""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from deploy import remote_server
from deploy.remote_server import main as remote_main
from deploy.runtime import DeployError, load_and_validate_env_file
from deploy.tests.helpers import DeploySandbox


class Round2BoundaryRegressionTests(unittest.TestCase):
    def _cli_args(self, sbx: DeploySandbox, *, keep_backups: int = 10, retries: int = 10) -> list[str]:
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
            "--keep-backups",
            str(keep_backups),
            "--health-retries",
            str(retries),
            "--health-interval",
            "0.1",
            "--health-timeout",
            "2.0",
        ]

    def test_strict_systemd_env_subset_rejects_ambiguous_syntax(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="strict-env-r2-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        env_file = tmp / "server.env"

        for bad_body, err_pattern in (
            ("FOO=bar\\\nBAZ=1\n", "Line continuation"),
            ("FOO=a\\nb\n", "Backslash"),
            ('FOO="a\\"b"\n', "Backslash"),
            ("FOO=C:\\temp\\db.sqlite3\n", "Backslash"),
            ('FOO="nested"quote"\n', "Nested"),
            ("FOO='nested'quote'\n", "Nested"),
            ('FOO="unclosed\n', "Mismatched quotes"),
            ("FOO=unclosed'\n", "Mismatched quotes"),
            ("FOO=unquoted space\n", "Unquoted whitespace"),
            ('FOO=mid"quote\n', "Unquoted whitespace or quotes"),
            ("FOO='ctrl\x07bell'\n", "Control characters"),
        ):
            with self.subTest(body=bad_body):
                env_file.write_text(bad_body, encoding="utf-8")
                os.chmod(env_file, 0o600)
                with self.assertRaisesRegex(DeployError, err_pattern):
                    load_and_validate_env_file(env_file)

        env_file.write_text(
            'EMPTY=\nQUOTED_SPACE="alpha beta"\nSINGLE=\'gamma delta\'\n',
            encoding="utf-8",
        )
        os.chmod(env_file, 0o600)
        self.assertEqual(
            load_and_validate_env_file(env_file),
            {"EMPTY": "", "QUOTED_SPACE": "alpha beta", "SINGLE": "gamma delta"},
        )

    def test_systemctl_stop_failure_never_mutates_or_restores_over_live_db(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        for rel in ("v1", "v2"):
            time.sleep(0.02)
            staged = sbx.clone_staged_server(rel)
            self.assertEqual(
                remote_main(["deploy", "--staged-server", str(staged), "--release-id", rel, *self._cli_args(sbx)]),
                0,
            )
        seed_comment = sbx.post_guest_comment("cc-source-analysis", "stop失败保护评论", client_ipv6="2001:db8::81")

        # 1. Migration deploy when `systemctl stop` fails: must NOT run migrate!
        staged_mig = sbx.clone_staged_server("v3-mig")
        (staged_mig / "comments" / "migrations" / "0002_mut.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [migrations.RunSQL(\"UPDATE comments_comment SET body='WIPED';\")]\n",
            encoding="utf-8",
        )
        (sbx.root / "fail_stop").write_text("1\n", encoding="utf-8")
        try:
            self.assertEqual(
                remote_main(["deploy", "--staged-server", str(staged_mig), "--release-id", "v3-mig", *self._cli_args(sbx)]),
                1,
            )
        finally:
            (sbx.root / "fail_stop").unlink(missing_ok=True)
        # Clear maintenance left by unrecovered stop failure & verify DB untouched
        (sbx.app_root / "shared" / ".maintenance").unlink(missing_ok=True)
        _, _, after_deploy_stop_fail = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual(after_deploy_stop_fail["items"][0]["id"], seed_comment["id"])
        self.assertEqual(after_deploy_stop_fail["items"][0]["body"], "stop失败保护评论")

        # 1b. Even when `current` symlink is missing/dangling while service is still running,
        #     migration deploy MUST still enforce `systemctl stop` and abort if stop fails!
        current_link = sbx.app_root / "current"
        saved_target = current_link.resolve()
        current_link.unlink()
        os.symlink(str(sbx.app_root / "releases" / "dangling-nonexistent"), str(current_link))
        (sbx.root / "fail_stop").write_text("1\n", encoding="utf-8")
        try:
            self.assertEqual(
                remote_main(["deploy", "--staged-server", str(staged_mig), "--release-id", "v3-dangling", *self._cli_args(sbx)]),
                1,
            )
        finally:
            (sbx.root / "fail_stop").unlink(missing_ok=True)
            current_link.unlink(missing_ok=True)
            os.symlink(str(saved_target), str(current_link))
            (sbx.app_root / "shared" / ".maintenance").unlink(missing_ok=True)
        _, _, after_dangling_stop_fail = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual(after_dangling_stop_fail["items"][0]["body"], "stop失败保护评论")

        # 2. Manual `rollback --restore-db` when `systemctl stop` fails: must NOT overwrite DB!
        v2_bk = sorted((sbx.var_dir / "backups").glob("db-*-v2.sqlite3"))[0]
        (sbx.root / "fail_stop").write_text("1\n", encoding="utf-8")
        try:
            self.assertEqual(
                remote_main(["rollback", "--to", "v1", "--restore-db", v2_bk.name, *self._cli_args(sbx)]),
                1,
            )
        finally:
            (sbx.root / "fail_stop").unlink(missing_ok=True)
        (sbx.app_root / "shared" / ".maintenance").unlink(missing_ok=True)
        _, _, after_rb_stop_fail = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual(after_rb_stop_fail["items"][0]["body"], "stop失败保护评论")

        # 3. Auto-recovery `_restore_release_state` when `stop` fails after `db_mutated=True`:
        #    must skip restoring backup over a still-running service and keep `.maintenance`!
        views_py = staged_mig / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )
        orig_wait = remote_server.wait_for_healthy

        def arm_fail_stop_on_probe(cfg, runtime_env):
            (sbx.root / "fail_stop").write_text("1\n", encoding="utf-8")
            return orig_wait(cfg, runtime_env)

        try:
            with mock.patch.object(remote_server, "wait_for_healthy", side_effect=arm_fail_stop_on_probe):
                self.assertEqual(
                    remote_main(
                        ["deploy", "--staged-server", str(staged_mig), "--release-id", "v3-mig", *self._cli_args(sbx, retries=2)]
                    ),
                    1,
                )
            # Because recovery stop failed, DB was NOT overwritten back to pre-migration snapshot
            # and `.maintenance` stays in place to block external traffic!
            self.assertTrue((sbx.app_root / "shared" / ".maintenance").is_file())
            with contextlib.closing(sqlite3.connect(str(sbx.var_dir / "db.sqlite3"))) as conn:
                bodies = [r[0] for r in conn.execute("SELECT body FROM comments_comment").fetchall()]
            self.assertEqual(bodies, ["WIPED"])
        finally:
            (sbx.root / "fail_stop").unlink(missing_ok=True)

    def test_maintenance_gate_blocks_traffic_during_migration_probe_and_clears_after_recovery(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        staged_v1 = sbx.clone_staged_server("v1")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v1), "--release-id", "v1", *self._cli_args(sbx)]),
            0,
        )
        self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())

        staged_v2_mig_bad = sbx.clone_staged_server("v2-mig-bad")
        (staged_v2_mig_bad / "comments" / "migrations" / "0002_noop.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [migrations.RunSQL('SELECT 1;')]\n",
            encoding="utf-8",
        )
        views_py = staged_v2_mig_bad / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )

        observed_during_probe: list[tuple[bool, int, int]] = []
        orig_wait = remote_server.wait_for_healthy

        def check_gate_during_probe(cfg, runtime_env):
            if not observed_during_probe:
                maint_exists = (sbx.app_root / "shared" / ".maintenance").is_file()
                ext_code, ext_hdrs, _ = sbx.http_request("/api/notes/cc-source-analysis/comments/")
                post_code, post_hdrs, _ = sbx.http_request(
                    "/api/notes/cc-source-analysis/comments/",
                    method="POST",
                    json_body={"body": "维护窗口内慢请求严禁入库", "expectedAuthorKind": "guest"},
                )
                self.assertIn("no-store", ext_hdrs.get("cache-control", ""))
                self.assertIn("no-store", post_hdrs.get("cache-control", ""))
                observed_during_probe.append((maint_exists, ext_code, post_code))
            return orig_wait(cfg, runtime_env)

        with mock.patch.object(remote_server, "wait_for_healthy", side_effect=check_gate_during_probe):
            rc = remote_main(
                ["deploy", "--staged-server", str(staged_v2_mig_bad), "--release-id", "v2-mig-bad", *self._cli_args(sbx, retries=2)]
            )
        self.assertEqual(rc, 1)
        self.assertEqual(observed_during_probe, [(True, 503, 503)])

        # After auto-rollback to v1 passes health check, .maintenance is automatically cleared!
        self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())
        code_after, _, list_after = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual(code_after, 200)
        self.assertEqual(list_after["items"], [])

        # Missing backup snapshot during failed migration recovery MUST fail closed and keep .maintenance!
        def unlink_snapshot_then_probe(cfg, runtime_env):
            for snap in (sbx.var_dir / "backups").glob("db-*-v2-snap-missing.sqlite3"):
                snap.unlink()
            return orig_wait(cfg, runtime_env)

        with mock.patch.object(remote_server, "wait_for_healthy", side_effect=unlink_snapshot_then_probe):
            rc_missing = remote_main(
                [
                    "deploy",
                    "--staged-server",
                    str(staged_v2_mig_bad),
                    "--release-id",
                    "v2-snap-missing",
                    *self._cli_args(sbx, retries=2),
                ]
            )
        self.assertEqual(rc_missing, 1)
        self.assertTrue((sbx.app_root / "shared" / ".maintenance").is_file())
        (sbx.app_root / "shared" / ".maintenance").unlink(missing_ok=True)

        # Replacing backups/ with an external directory symlink AFTER prepare_var_dirs MUST be rejected by
        # descriptor-anchored O_NOFOLLOW pruning without deleting external sentinel files!
        ext_bk_dir = sbx.root / "external-protected-backups"
        ext_bk_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(1, 5):
            (ext_bk_dir / f"db-2026010{idx}T000000_000000Z-ext.sqlite3").write_bytes(b"keep-sentinel")
        shutil.rmtree(sbx.var_dir / "backups")
        os.symlink(str(ext_bk_dir), str(sbx.var_dir / "backups"))
        with self.assertRaisesRegex(DeployError, "backups"):
            remote_server._hist.prune_old_backups(sbx.var_dir, keep=1, protected=set())
        self.assertEqual(len(list(ext_bk_dir.glob("*.sqlite3"))), 4)

    def test_delete_journal_backups_zero_sidecars_runuser_verify_fail_pruning_and_legacy_venv_dir(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        # Convert shared/venv into a REAL directory (simulating legacy pre-symlink layout)
        venv_link = sbx.app_root / "shared" / "venv"
        venv_link.unlink()
        shutil.rmtree(sbx.app_root / "shared" / "venvs")
        venv_link.mkdir(parents=True)
        for item in sbx.venv_source.iterdir():
            if item.name != ".requirements.sha256":
                os.symlink(str(item), str(venv_link / item.name))
        req_sha_full = hashlib.sha256((sbx.clone_staged_server("tmp-req") / "requirements.txt").read_bytes()).hexdigest()
        (venv_link / ".requirements.sha256").write_text(f"{req_sha_full}\n", encoding="utf-8")
        self.assertTrue(venv_link.is_dir() and not venv_link.is_symlink())

        staged_v1 = sbx.clone_staged_server("v1")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v1), "--release-id", "v1", *self._cli_args(sbx)]),
            0,
        )
        # Legacy real directory must smoothly migrate to shared/venvs/<id> + symlink shared/venv!
        self.assertTrue(venv_link.is_symlink())
        self.assertEqual(venv_link.resolve().parent, (sbx.app_root / "shared" / "venvs").resolve())

        staged_v2 = sbx.clone_staged_server("v2")
        time.sleep(0.02)
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(staged_v2), "--release-id", "v2", *self._cli_args(sbx, keep_backups=2)]),
            0,
        )

        # Verify backup uses journal_mode=delete and backups/ has ZERO hidden or -wal/-shm sidecars
        backups_dir = sbx.var_dir / "backups"
        v2_bk = sorted(backups_dir.glob("db-*-v2.sqlite3"))[0]
        with contextlib.closing(sqlite3.connect(str(v2_bk))) as conn:
            jmode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(jmode.lower(), "delete")

        # Verify _resolve_validated_backup invokes sqlite_ops.py verify via run_checked(..., as_user=run_user)
        recorded_cmds: list[tuple[list[str], str | None]] = []
        orig_run_checked = remote_server.run_checked

        def spy_run_checked(cmd, **kwargs):
            recorded_cmds.append(([str(x) for x in cmd], kwargs.get("as_user")))
            return orig_run_checked(cmd, **kwargs)

        with mock.patch.object(remote_server, "run_checked", side_effect=spy_run_checked):
            remote_server._resolve_validated_backup(
                sbx.var_dir,
                v2_bk.name,
                helper_py=sbx.app_root / "shared" / "sqlite_ops.py",
                python_bin=str(venv_link / "bin" / "python"),
                run_user=None,
            )
        self.assertTrue(any("verify" in cmd and str(v2_bk.resolve()) in cmd for cmd, _ in recorded_cmds))

        # Repeated failed deployments MUST prune backups according to --keep-backups=2!
        bad_rel = sbx.clone_staged_server("bad-loop")
        views_py = bad_rel / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )
        for idx in range(1, 5):
            time.sleep(0.02)
            self.assertEqual(
                remote_main(
                    [
                        "deploy",
                        "--staged-server",
                        str(bad_rel),
                        "--release-id",
                        f"fail-{idx}",
                        *self._cli_args(sbx, keep_backups=2, retries=2),
                    ]
                ),
                1,
            )

        entries = os.listdir(backups_dir)
        self.assertLessEqual(len(entries), 2)
        for fname in entries:
            self.assertFalse(fname.startswith("."), f"Hidden temp file left in backups/: {fname}")
            self.assertTrue(fname.endswith(".sqlite3"), f"Sidecar file left in backups/: {fname}")

    def test_prep_preserves_legacy_real_venv_immutable_release_ids_and_prep_gc(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        for rel in ("v1", "v2"):
            time.sleep(0.02)
            staged = sbx.clone_staged_server(rel)
            self.assertEqual(
                remote_main(["deploy", "--staged-server", str(staged), "--release-id", rel, *self._cli_args(sbx)]),
                0,
            )

        # 1. Reusing historical activated release_id 'v1' while 'v2' is active must be rejected without touching v1!
        v1_marker = sbx.app_root / "releases" / "v1" / ".activated"
        v1_marker_mtime = v1_marker.stat().st_mtime_ns
        dup_staged = sbx.clone_staged_server("dup-v1")
        self.assertEqual(
            remote_main(["deploy", "--staged-server", str(dup_staged), "--release-id", "v1", *self._cli_args(sbx)]),
            1,
        )
        self.assertTrue(v1_marker.is_file())
        self.assertEqual(v1_marker.stat().st_mtime_ns, v1_marker_mtime)

        # 2. Repeated preparation failures with distinct requirements must garbage-collect orphaned shared/venvs/*
        venvs_root = sbx.app_root / "shared" / "venvs"
        baseline_venvs = set(os.listdir(venvs_root))
        for idx in range(1, 4):
            prep_bad = sbx.clone_staged_server(f"prep-bad-{idx}")
            req_path = prep_bad / "requirements.txt"
            req_Text = req_path.read_text(encoding="utf-8") + f"# distinct-req-{idx}\n"
            req_path.write_text(req_Text, encoding="utf-8")
            new_sha_full = hashlib.sha256(req_Text.encode("utf-8")).hexdigest()
            fake_new_venv = venvs_root / new_sha_full[:16]
            fake_new_venv.mkdir(parents=True, exist_ok=True)
            for item in sbx.venv_source.iterdir():
                if item.name != ".requirements.sha256":
                    os.symlink(str(item), str(fake_new_venv / item.name))
            (fake_new_venv / ".requirements.sha256").write_text(f"{new_sha_full}\n", encoding="utf-8")
            # Make `manage.py check --deploy` fail in preparation via invalid note_slugs.json
            (prep_bad / "comments" / "note_slugs.json").write_text("[]\n", encoding="utf-8")
            self.assertEqual(
                remote_main(
                    ["deploy", "--staged-server", str(prep_bad), "--release-id", f"prep-fail-{idx}", *self._cli_args(sbx)]
                ),
                1,
            )
        self.assertEqual(set(os.listdir(venvs_root)), baseline_venvs)

        # 3. Legacy real directory `shared/venv` WITHOUT `.requirements.sha256` must remain untouched on prep failure
        #    AND be restored if activation/health fails!
        venv_link = sbx.app_root / "shared" / "venv"
        venv_link.unlink()
        venv_link.mkdir(parents=True)
        for item in sbx.venv_source.iterdir():
            if item.name != ".requirements.sha256":
                os.symlink(str(item), str(venv_link / item.name))
        legacy_marker = venv_link / "legacy-marker.txt"
        legacy_marker.write_text("keep-me\n", encoding="utf-8")

        prep_fail_legacy = sbx.clone_staged_server("prep-fail-legacy")
        (prep_fail_legacy / "comments" / "note_slugs.json").write_text("[]\n", encoding="utf-8")
        with mock.patch.object(remote_server, "ensure_release_venv", return_value=venvs_root / next(iter(baseline_venvs))):
            self.assertEqual(
                remote_main(
                    ["deploy", "--staged-server", str(prep_fail_legacy), "--release-id", "v3-prep-fail", *self._cli_args(sbx)]
                ),
                1,
            )
        self.assertTrue(venv_link.is_dir() and not venv_link.is_symlink())
        self.assertTrue(legacy_marker.is_file())

        health_fail_legacy = sbx.clone_staged_server("health-fail-legacy")
        views_py = health_fail_legacy / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )
        with mock.patch.object(remote_server, "ensure_release_venv", return_value=venvs_root / next(iter(baseline_venvs))):
            self.assertEqual(
                remote_main(
                    [
                        "deploy",
                        "--staged-server",
                        str(health_fail_legacy),
                        "--release-id",
                        "v3-health-fail",
                        *self._cli_args(sbx, retries=2),
                    ]
                ),
                1,
            )
        self.assertTrue(venv_link.is_dir() and not venv_link.is_symlink())
        self.assertTrue(legacy_marker.is_file())
        code_ok, _, _ = sbx.http_request("/api/health/")
        self.assertEqual(code_ok, 200)


if __name__ == "__main__":
    unittest.main()
