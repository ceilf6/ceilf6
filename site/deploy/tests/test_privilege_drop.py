"""Regression tests for privilege-dropped collectstatic and staticfiles root reclamation."""

from __future__ import annotations

import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deploy import fs_safe, remote_server
from deploy.runtime import DeployConfig, DeployError
from deploy.tests.helpers import DeploySandbox


def _latest_migration(migrations_dir: Path) -> tuple[int, str]:
    candidates = [
        (int(prefix), path.stem)
        for path in migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.py")
        if (prefix := path.stem.split("_", 1)[0]).isdigit()
    ]
    if not candidates:
        raise AssertionError(f"No numbered migrations found in {migrations_dir}")
    return max(candidates)


class PrivilegeDroppedCollectstaticTests(unittest.TestCase):
    def test_reclaim_tree_to_root_rejects_symlinks_and_hardlinks_without_touching_targets(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="reclaim-static-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)

        server_dir = tmp / "server"
        server_dir.mkdir(parents=True)
        fchown_calls: list[tuple[int, int]] = []

        def record_fchown(fd: int, uid: int, gid: int) -> None:
            fchown_calls.append((uid, gid))

        with mock.patch("os.fchown", side_effect=record_fchown):
            static_dir = fs_safe.prepare_temp_writable_dir_nofollow(
                server_dir, "staticfiles", owner_ids=(33, 33)
            )
        self.assertEqual(fchown_calls, [(33, 33)])

        (static_dir / "admin" / "css").mkdir(parents=True)
        css_file = static_dir / "admin" / "css" / "base.css"
        css_file.write_text("body { color: #fff; }\n", encoding="utf-8")
        os.chmod(css_file, 0o600)

        fchown_calls.clear()
        with mock.patch("os.fchown", side_effect=record_fchown):
            fs_safe.reclaim_tree_to_root_nofollow(static_dir, reclaim_owner=True)

        self.assertTrue(all(call == (0, 0) for call in fchown_calls))
        self.assertGreaterEqual(len(fchown_calls), 4)
        self.assertEqual(stat.S_IMODE(static_dir.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(css_file.stat().st_mode), 0o644)

        # 1. Symlink planted inside staticfiles/ MUST be rejected without altering target mode!
        secret_target = tmp / "outside-secret.txt"
        secret_target.write_text("secret\n", encoding="utf-8")
        os.chmod(secret_target, 0o600)
        sym_asset = static_dir / "admin" / "leak-sym.txt"
        os.symlink(secret_target, sym_asset)
        with mock.patch("os.fchown"):
            with self.assertRaisesRegex(fs_safe.FsConfinementError, "Symlink"):
                fs_safe.reclaim_tree_to_root_nofollow(static_dir, reclaim_owner=True)
        self.assertEqual(stat.S_IMODE(secret_target.stat().st_mode), 0o600)
        sym_asset.unlink()

        # 2. Hardlink planted inside staticfiles/ (e.g. linking live db.sqlite3) MUST be rejected
        #    before fchown/fchmod can make the underlying inode world-readable!
        db_inode = tmp / "db.sqlite3"
        db_inode.write_text("sqlite-private-data\n", encoding="utf-8")
        os.chmod(db_inode, 0o600)
        hardlink_asset = static_dir / "admin" / "leak-hardlink.css"
        os.link(db_inode, hardlink_asset)
        with mock.patch("os.fchown"):
            with self.assertRaisesRegex(fs_safe.FsConfinementError, "Hardlinked"):
                fs_safe.reclaim_tree_to_root_nofollow(static_dir, reclaim_owner=True)
        self.assertEqual(stat.S_IMODE(db_inode.stat().st_mode), 0o600)
        hardlink_asset.unlink()

        # 3. Repeated directory traversals (`reclaim_tree_to_root_nofollow` + `prune_backups_nofollow`)
        #    MUST close duplicated `scandir` descriptors with zero FD leak!
        var_fd_test = tmp / "var-fd-leak-check"
        (var_fd_test / "backups").mkdir(parents=True)
        (var_fd_test / "backups" / "db-20260101T000000_000000Z-v1.sqlite3").write_bytes(b"x")
        before_fd = os.open(os.devnull, os.O_RDONLY)
        os.close(before_fd)
        with mock.patch("os.fchown"):
            for _ in range(25):
                fs_safe.reclaim_tree_to_root_nofollow(static_dir, reclaim_owner=True)
                fs_safe.prune_backups_nofollow(var_fd_test, keep=5, protected_names=set())
        after_fd = os.open(os.devnull, os.O_RDONLY)
        os.close(after_fd)
        self.assertEqual(after_fd, before_fd)

    def test_root_deploy_runs_collectstatic_as_service_user_and_protects_swapped_cache_mail_symlinks(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        staged_v1 = sbx.clone_staged_server("v1-root-sim")
        fake_pw = pwd.struct_passwd(("www-data", "x", 33, 33, "", "/var/www", "/usr/sbin/nologin"))

        ext_cache_sentinel = sbx.root / "outside-root-cache-target"
        ext_mail_sentinel = sbx.root / "outside-root-mail-target"
        ext_cache_sentinel.mkdir(parents=True)
        ext_mail_sentinel.mkdir(parents=True)
        os.chmod(ext_cache_sentinel, 0o755)
        os.chmod(ext_mail_sentinel, 0o755)

        observed_manage_users: list[tuple[str, bool]] = []
        real_subprocess_run = subprocess.run
        real_prepare_var = remote_server.prepare_var_dirs

        def swap_symlinks_after_prepare(*args, **kwargs):
            res = real_prepare_var(*args, **kwargs)
            # Simulate compromised www-data replacing cache/ and mail/ with symlinks to external
            # root-owned directories immediately AFTER prepare_var_dirs closes its descriptors!
            for sub_name, ext_target in (("cache", ext_cache_sentinel), ("mail", ext_mail_sentinel)):
                victim = sbx.var_dir / sub_name
                if victim.is_symlink():
                    victim.unlink()
                elif victim.is_dir():
                    shutil.rmtree(victim)
                os.symlink(str(ext_target), str(victim))
            return res

        def intercept_runuser_subprocess(cmd, *args, **kwargs):
            cmd_list = [str(x) for x in cmd]
            has_runuser = cmd_list[:3] == ["runuser", "-u", "www-data"] and cmd_list[3] == "--"
            actual_cmd = cmd_list[4:] if has_runuser else cmd_list
            if "manage.py" in actual_cmd:
                idx = actual_cmd.index("manage.py")
                subcmd = actual_cmd[idx + 1] if idx + 1 < len(actual_cmd) else ""
                observed_manage_users.append((subcmd, has_runuser))
                # Under simulated unprivileged www-data, chmod on external root-owned target is denied;
                # point symlink back to an isolated sandbox user dir only for the unprivileged child!
                if has_runuser:
                    for sub_name in ("cache", "mail"):
                        victim = sbx.var_dir / sub_name
                        if victim.is_symlink():
                            victim.unlink()
                            victim.mkdir(mode=0o700)
            return real_subprocess_run(actual_cmd, *args, **kwargs)

        cfg = DeployConfig(
            app_root=sbx.app_root,
            etc_env=sbx.etc_env,
            var_dir=sbx.var_dir,
            lock_file=sbx.lock_file,
            systemctl_bin=str(sbx.systemctl_bin),
            health_url=sbx.health_url,
            keep_releases=10,
            health_retries=10,
            health_interval=0.1,
            health_timeout=2.0,
        )

        with (
            mock.patch("os.geteuid", return_value=0),
            mock.patch("pwd.getpwnam", return_value=fake_pw),
            mock.patch("os.fchown"),
            mock.patch.object(remote_server, "prepare_var_dirs", side_effect=swap_symlinks_after_prepare),
            mock.patch("subprocess.run", side_effect=intercept_runuser_subprocess),
        ):
            active_dir = remote_server.deploy_release(cfg, staged_server=staged_v1, release_id="v1-root")

        self.assertTrue((active_dir / "server" / "staticfiles" / "admin" / "css" / "base.css").is_file())
        # EVERY manage.py invocation (including collectstatic, check, migrate) MUST use runuser -u www-data!
        self.assertIn(("collectstatic", True), observed_manage_users)
        self.assertTrue(
            all(is_dropped for _, is_dropped in observed_manage_users),
            f"Found root manage.py invocation without runuser: {observed_manage_users}",
        )
        # External sentinel directory permissions MUST remain untouched at 0755!
        self.assertEqual(stat.S_IMODE(ext_cache_sentinel.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(ext_mail_sentinel.stat().st_mode), 0o755)

    def test_disjoint_roots_rejected_before_mkdir_or_mutation(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="disjoint-roots-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        app_root = tmp / "opt" / "wangjinghong"
        var_dir = tmp / "var" / "lib" / "wangjinghong"

        for bad_app, bad_var in (
            (app_root, app_root / "shared" / "venvs" / "data"),
            (app_root, app_root),
            (var_dir / "nested-app", var_dir),
            (Path("/var/www/wangjinghong"), var_dir),
            (Path("/var/www/wangjinghong/backend"), var_dir),
            (app_root, Path("/var/www/wangjinghong/data")),
        ):
            with self.subTest(app=str(bad_app), var=str(bad_var)):
                with self.assertRaisesRegex(DeployError, "disjoint"):
                    remote_server.build_runtime_env({}, var_dir=bad_var, app_root=bad_app)
        # Verify zero directories were created under tmp by failed disjoint checks!
        self.assertEqual(list(tmp.iterdir()), [])

    def test_restore_db_schema_mismatch_and_activation_metadata_commit_boundaries(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        cfg = DeployConfig(
            app_root=sbx.app_root,
            etc_env=sbx.etc_env,
            var_dir=sbx.var_dir,
            lock_file=sbx.lock_file,
            systemctl_bin=str(sbx.systemctl_bin),
            health_url=sbx.health_url,
            keep_releases=10,
            health_retries=10,
            health_interval=0.1,
            health_timeout=2.0,
        )

        # 1. Deploy v1, then deploy v2 WITH a new table migration `0002_extra_tbl.py`
        staged_v1 = sbx.clone_staged_server("v1")
        remote_server.deploy_release(cfg, staged_server=staged_v1, release_id="v1")

        staged_v2 = sbx.clone_staged_server("v2-schema")
        (staged_v2 / "comments" / "migrations" / "0002_extra_tbl.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RunSQL(\n"
            "            'CREATE TABLE v2_only_tbl (id INT PRIMARY KEY); '\n"
            "            'ALTER TABLE comments_comment ADD COLUMN mood TEXT NULL; '\n"
            "            'CREATE INDEX comments_mood_idx ON comments_comment (mood);'\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2, release_id="v2-schema")
        pre_v2_bk = sorted((sbx.var_dir / "backups").glob("db-*-v2-schema.sqlite3"))[0]

        # Restoring pre-v2 snapshot (which lacks 0002_extra_tbl) onto `--to v2-schema` MUST fail
        # `verify-schema` and self-heal back to v2-schema's migrated DB!
        with self.assertRaisesRegex(DeployError, "verify-schema"):
            remote_server.rollback_release(cfg, to_release="v2-schema", restore_db=pre_v2_bk.name)
        self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-schema").resolve())

        # 1a-additive. Backward-compatible additive migration (extra table / nullable column / index):
        #     code-only `rollback` WITHOUT `--restore-db` MUST succeed while preserving live comments!
        kept_comment = sbx.post_guest_comment("cc-source-analysis", "向后兼容新增表后保留的评论", client_ipv6="2001:db8::91")
        remote_server.rollback_release(cfg, to_release="v1")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())
        _, _, after_compat_rb = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in after_compat_rb["items"]], [kept_comment["id"]])

        # Restoring pre-v2 snapshot onto `--to v1` (matching schema!) succeeds cleanly!
        remote_server.rollback_release(cfg, to_release="v1", restore_db=pre_v2_bk.name)
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())

        # 1b. Unsynced destructive SQL migration (`RENAME COLUMN body TO legacy_body` without model sync):
        #     `deploy_release` MUST reject it immediately after `migrate`, restore pre-migration DB,
        #     keep `v1` active, and clear `.maintenance`!
        staged_v2_unsynced = sbx.clone_staged_server("v2-unsynced")
        (staged_v2_unsynced / "comments" / "migrations" / "0002_rename_col.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RunSQL('ALTER TABLE comments_comment RENAME COLUMN body TO legacy_body;'),\n"
            "    ]\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeployError, "verify-schema"):
            remote_server.deploy_release(cfg, staged_server=staged_v2_unsynced, release_id="v2-unsynced")
        self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())

        # 1c. Auto-created M2M join table (`accounts_user_user_permissions`) destructive migration:
        #     `deploy_release` rejects unsynced M2M rename and restores `v1`, AND if M2M table is
        #     mutated out-of-band, code-only `rollback` ALSO rejects it via `include_auto_created=True`!
        staged_v2_m2m = sbx.clone_staged_server("v2-m2m-break")
        m2m_mig_dir = staged_v2_m2m / "accounts" / "migrations"
        max_num, latest_mig_name = _latest_migration(m2m_mig_dir)
        (m2m_mig_dir / f"{max_num + 1:04d}_break_m2m.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            f"    dependencies = [('accounts', {latest_mig_name!r})]\n"
            "    operations = [\n"
            "        migrations.RunSQL(\n"
            "            'ALTER TABLE accounts_user_user_permissions RENAME COLUMN permission_id TO perm_legacy;'\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DeployError, "verify-schema"):
            remote_server.deploy_release(cfg, staged_server=staged_v2_m2m, release_id="v2-m2m-break")
        self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())

        # 1e. Model-synced tightening of nullable `Comment.author` (`null=True` -> `null=False`):
        #     - `deploy_release` of `v2-tighten` SUCCEEDS;
        #     - Default code-only `rollback --to v1` is REJECTED (`NOT NULL in DB but nullable in v1`);
        #     - Re-deploying old checkout (`staged_v1`) via `deploy_release` is ALSO REJECTED before switch;
        #     - `rollback --to v1 --restore-db <pre_tighten_bk>` SUCCEEDS cleanly!
        staged_v2_tight = sbx.clone_staged_server("v2-tighten")
        models_py = staged_v2_tight / "comments" / "models.py"
        models_py.write_text(
            models_py.read_text(encoding="utf-8").replace("null=True,\n        blank=True,", "null=False,"),
            encoding="utf-8",
        )
        (staged_v2_tight / "comments" / "migrations" / "0002_tighten_author.py").write_text(
            "from django.conf import settings\n"
            "from django.db import migrations, models\n"
            "import django.db.models.deletion\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RunSQL('DELETE FROM comments_comment WHERE author_id IS NULL;'),\n"
            "        migrations.AlterField(\n"
            "            model_name='comment',\n"
            "            name='author',\n"
            "            field=models.ForeignKey(\n"
            "                on_delete=django.db.models.deletion.PROTECT,\n"
            "                related_name='comments',\n"
            "                to=settings.AUTH_USER_MODEL,\n"
            "                verbose_name='评论作者',\n"
            "            ),\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2_tight, release_id="v2-tighten")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-tighten").resolve())

        with self.assertRaisesRegex(DeployError, "verify-schema"):
            remote_server.rollback_release(cfg, to_release="v1")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-tighten").resolve())

        old_checkout = sbx.clone_staged_server("v3-old-checkout")
        with self.assertRaisesRegex(DeployError, "verify-schema"):
            remote_server.deploy_release(cfg, staged_server=old_checkout, release_id="v3-old-checkout")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-tighten").resolve())

        pre_tighten_bk = sorted((sbx.var_dir / "backups").glob("db-*-v2-tighten.sqlite3"))[0]
        remote_server.rollback_release(cfg, to_release="v1", restore_db=pre_tighten_bk.name)
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())

        # 1d. Missing live `db.sqlite3` during code-only rollback MUST fail before switching `current`
        #     and MUST NOT implicitly create an empty `db.sqlite3`!
        staged_v2_plain = sbx.clone_staged_server("v2-plain")
        remote_server.deploy_release(cfg, staged_server=staged_v2_plain, release_id="v2-plain")
        saved_db = sbx.root / "stashed-live.sqlite3"
        os.replace(sbx.var_dir / "db.sqlite3", saved_db)
        for suffix in ("-wal", "-shm"):
            Path(f"{sbx.var_dir / 'db.sqlite3'}{suffix}").unlink(missing_ok=True)
        try:
            with self.assertRaisesRegex(DeployError, "--restore-db"):
                remote_server.rollback_release(cfg, to_release="v1")
            self.assertFalse((sbx.var_dir / "db.sqlite3").exists())
            self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-plain").resolve())
        finally:
            os.replace(saved_db, sbx.var_dir / "db.sqlite3")
        remote_server.rollback_release(cfg, to_release="v1")

        # 2. Activation metadata failure during deploy_release rolls back `current` and history cleanly!
        staged_v3 = sbx.clone_staged_server("v3-meta-fail")
        with mock.patch.object(remote_server._hist, "record_activated_release", side_effect=OSError("ENOSPC on history")):
            with self.assertRaisesRegex(DeployError, "ENOSPC"):
                remote_server.deploy_release(cfg, staged_server=staged_v3, release_id="v3-meta-fail")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v1").resolve())
        self.assertFalse((sbx.app_root / "releases" / "v3-meta-fail").exists())
        expected_base_hist = ["v2-schema", "v2-tighten", "v2-plain", "v1"]
        self.assertEqual(remote_server._hist.read_release_history(sbx.app_root), expected_base_hist)

        # 3. Activation history write failure during rollback_release rolls back `current` cleanly!
        staged_v4 = sbx.clone_staged_server("v4-ok")
        remote_server.deploy_release(cfg, staged_server=staged_v4, release_id="v4-ok")
        orig_write_hist = remote_server._hist.write_release_history
        fail_calls = 0

        def fail_first_write(app_root: Path, history):
            nonlocal fail_calls
            fail_calls += 1
            if fail_calls == 1:
                raise OSError("ENOSPC writing .release-history")
            return orig_write_hist(app_root, history)

        with mock.patch.object(remote_server._hist, "write_release_history", side_effect=fail_first_write):
            with self.assertRaisesRegex(DeployError, "ENOSPC"):
                remote_server.rollback_release(cfg)
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v4-ok").resolve())
        self.assertEqual(remote_server._hist.read_release_history(sbx.app_root), [*expected_base_hist, "v4-ok"])

    def test_nested_sqlite_path_initial_deploy_failure_rejects_swapped_parent_symlink(self) -> None:
        sbx = DeploySandbox()
        self.addCleanup(sbx.close)

        nested_sqlite = sbx.var_dir / "nested_db_parent" / "db.sqlite3"
        sbx.etc_env.write_text(
            sbx.etc_env.read_text(encoding="utf-8").replace(
                f"SQLITE_PATH={sbx.var_dir / 'db.sqlite3'}",
                f"SQLITE_PATH={nested_sqlite}",
            ),
            encoding="utf-8",
        )
        os.chmod(sbx.etc_env, 0o600)

        ext_dir = sbx.root / "outside-db-dir"
        ext_dir.mkdir(parents=True)
        sentinel_db = ext_dir / "db.sqlite3"
        sentinel_db.write_bytes(b"PROTECTED-OUTSIDE-DB")

        bad_v0 = sbx.clone_staged_server("v0-nested-fail")
        views_py = bad_v0 / "config" / "views.py"
        views_py.write_text(
            views_py.read_text(encoding="utf-8").replace(
                'return _json_no_store({"status": "ok"}, status=200)',
                'return _json_no_store({"status": "broken"}, status=500)',
            ),
            encoding="utf-8",
        )

        orig_wait = remote_server.wait_for_healthy

        def swap_parent_to_symlink_before_probe_fails(cfg, runtime_env):
            subprocess.run([str(sbx.systemctl_bin), "stop", "wangjinghong-api"], check=True)
            shutil.rmtree(nested_sqlite.parent)
            os.symlink(str(ext_dir), str(nested_sqlite.parent))
            return orig_wait(cfg, runtime_env)

        cfg = DeployConfig(
            app_root=sbx.app_root,
            etc_env=sbx.etc_env,
            var_dir=sbx.var_dir,
            lock_file=sbx.lock_file,
            systemctl_bin=str(sbx.systemctl_bin),
            health_url=sbx.health_url,
            health_retries=1,
            health_interval=0.05,
            health_timeout=1.0,
        )
        with mock.patch.object(remote_server, "wait_for_healthy", side_effect=swap_parent_to_symlink_before_probe_fails):
            with self.assertRaisesRegex(DeployError, "new DB cleanup failed"):
                remote_server.deploy_release(cfg, staged_server=bad_v0, release_id="v0-nested-fail")

        # External sentinel DB MUST remain untouched and .maintenance MUST stay active!
        self.assertEqual(sentinel_db.read_bytes(), b"PROTECTED-OUTSIDE-DB")
        self.assertTrue((sbx.app_root / "shared" / ".maintenance").is_file())


if __name__ == "__main__":
    unittest.main()
