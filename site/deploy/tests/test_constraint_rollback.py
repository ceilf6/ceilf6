"""Regression tests for CHECK, UNIQUE, and FOREIGN KEY write-constraint checks on code-only rollback."""

from __future__ import annotations

import contextlib
import re
import sqlite3
import subprocess
import unittest
from pathlib import Path

from deploy import remote_server
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


class WriteConstraintRollbackTests(unittest.TestCase):
    def test_tightened_check_added_unique_and_added_fk_rejected_on_code_only_rollback(self) -> None:
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

        staged_v1 = sbx.clone_staged_server("v1")
        remote_server.deploy_release(cfg, staged_server=staged_v1, release_id="v1")

        # 1. Tighten Comment body max length CHECK constraint from 1000 -> 500:
        #    code-only rollback to v1 MUST fail before switching `current`!
        staged_v2_check = sbx.clone_staged_server("v2-check-500")
        models_py = staged_v2_check / "comments" / "models.py"
        models_py.write_text(
            models_py.read_text(encoding="utf-8").replace(
                "MAX_COMMENT_BODY_LENGTH = 1000",
                "MAX_COMMENT_BODY_LENGTH = 500",
            ),
            encoding="utf-8",
        )
        (staged_v2_check / "comments" / "migrations" / "0002_tighten_check.py").write_text(
            "from django.db import migrations, models\n"
            "from django.db.models import Q, Value\n"
            "from django.db.models.functions import Chr, Length, Replace, StrIndex, Trim\n"
            "from django.db.models.lookups import Exact, GreaterThanOrEqual, LessThanOrEqual\n"
            "from comments.models import _trimmed_body_expression\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RemoveConstraint(\n"
            "            model_name='comment',\n"
            "            name='comments_body_non_blank_and_max_length',\n"
            "        ),\n"
            "        migrations.AlterField(\n"
            "            model_name='comment',\n"
            "            name='body',\n"
            "            field=models.TextField(max_length=500, verbose_name='评论正文'),\n"
            "        ),\n"
            "        migrations.AddConstraint(\n"
            "            model_name='comment',\n"
            "            constraint=models.CheckConstraint(\n"
            "                condition=(\n"
            "                    ~Q(note_slug='')\n"
            "                    & Exact(StrIndex('note_slug', Chr(0)), 0)\n"
            "                    & Exact(StrIndex('body', Chr(0)), 0)\n"
            "                    & GreaterThanOrEqual(Length(_trimmed_body_expression()), 1)\n"
            "                    & LessThanOrEqual(Length('body'), 500)\n"
            "                ),\n"
            "                name='comments_body_non_blank_and_max_length',\n"
            "            ),\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2_check, release_id="v2-check-500")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-check-500").resolve())

        with self.assertRaisesRegex(DeployError, "checks constraints differ"):
            remote_server.rollback_release(cfg, to_release="v1")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-check-500").resolve())

        pre_check_bk = sorted((sbx.var_dir / "backups").glob("db-*-v2-check-500.sqlite3"))[0]
        remote_server.rollback_release(cfg, to_release="v1", restore_db=pre_check_bk.name)

        # 2. Add a UNIQUE index on `comments_comment(note_slug, body)`:
        #    code-only rollback to v1 MUST fail before switching `current`!
        staged_v2_uniq = sbx.clone_staged_server("v2-uniq")
        (staged_v2_uniq / "comments" / "migrations" / "0002_add_uniq.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.RunSQL(\n"
            "            'CREATE UNIQUE INDEX comments_slug_body_uniq ON comments_comment (note_slug, body);'\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2_uniq, release_id="v2-uniq")
        with self.assertRaisesRegex(DeployError, "uniques constraints differ"):
            remote_server.rollback_release(cfg, to_release="v1")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-uniq").resolve())

        pre_uniq_bk = sorted((sbx.var_dir / "backups").glob("db-*-v2-uniq.sqlite3"))[0]
        remote_server.rollback_release(cfg, to_release="v1", restore_db=pre_uniq_bk.name)

        # 2b. Partial expression unique index (`accounts_user_unique_non_empty_email_ci`):
        #     change expression `Lower('email')` -> `Substr(Lower('email'), 1, 1)` while keeping
        #     the EXACT same `WHERE NOT ("email" = '')` condition -> code-only rollback MUST reject!
        staged_v2_expr_uniq = sbx.clone_staged_server("v2-expr-uniq")
        acc_models = staged_v2_expr_uniq / "accounts" / "models.py"
        acc_models.write_text(
            acc_models.read_text(encoding="utf-8").replace(
                'Lower("email")',
                'models.functions.Substr(Lower("email"), 1, 1)',
            ),
            encoding="utf-8",
        )
        acc_mig_dir = staged_v2_expr_uniq / "accounts" / "migrations"
        max_num, latest_mig_name = _latest_migration(acc_mig_dir)
        (acc_mig_dir / f"{max_num + 1:04d}_tighten_email_expr_uniq.py").write_text(
            "from django.db import migrations, models\n"
            "import django.db.models.functions.text\n"
            "class Migration(migrations.Migration):\n"
            f"    dependencies = [('accounts', {latest_mig_name!r})]\n"
            "    operations = [\n"
            "        migrations.RemoveConstraint(\n"
            "            model_name='user',\n"
            "            name='accounts_user_unique_non_empty_email_ci',\n"
            "        ),\n"
            "        migrations.AddConstraint(\n"
            "            model_name='user',\n"
            "            constraint=models.UniqueConstraint(\n"
            "                django.db.models.functions.text.Substr(\n"
            "                    django.db.models.functions.text.Lower('email'), 1, 1\n"
            "                ),\n"
            "                condition=models.Q(('email', ''), _negated=True),\n"
            "                name='accounts_user_unique_non_empty_email_ci',\n"
            "            ),\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2_expr_uniq, release_id="v2-expr-uniq")
        with self.assertRaisesRegex(DeployError, "uniques constraints differ"):
            remote_server.rollback_release(cfg, to_release="v1")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-expr-uniq").resolve())

        pre_expr_bk = sorted((sbx.var_dir / "backups").glob("db-*-v2-expr-uniq.sqlite3"))[0]
        remote_server.rollback_release(cfg, to_release="v1", restore_db=pre_expr_bk.name)

        # 3. Add a FOREIGN KEY constraint (both on `Comment` itself and restrictive inbound FK from extra table):
        #    code-only rollback to v1 MUST fail before switching `current`!
        staged_v2_fk = sbx.clone_staged_server("v2-fk")
        (staged_v2_fk / "comments" / "migrations" / "0002_add_fk.py").write_text(
            "from django.conf import settings\n"
            "from django.db import migrations, models\n"
            "import django.db.models.deletion\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.AddField(\n"
            "            model_name='comment',\n"
            "            name='reviewed_by',\n"
            "            field=models.ForeignKey(\n"
            "                blank=True,\n"
            "                null=True,\n"
            "                on_delete=django.db.models.deletion.PROTECT,\n"
            "                related_name='reviewed_comments',\n"
            "                to=settings.AUTH_USER_MODEL,\n"
            "            ),\n"
            "        ),\n"
            "    ]\n",
            encoding="utf-8",
        )
        fk_models = staged_v2_fk / "comments" / "models.py"
        fk_models.write_text(
            fk_models.read_text(encoding="utf-8").replace(
                "    body = models.TextField(",
                "    reviewed_by = models.ForeignKey(\n"
                "        settings.AUTH_USER_MODEL,\n"
                "        on_delete=models.PROTECT,\n"
                "        null=True,\n"
                "        blank=True,\n"
                "        related_name='reviewed_comments',\n"
                "    )\n"
                "    body = models.TextField(",
            ),
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2_fk, release_id="v2-fk")
        with self.assertRaisesRegex(DeployError, "fks constraints differ"):
            remote_server.rollback_release(cfg, to_release="v1")
        self.assertEqual((sbx.app_root / "current").resolve(), (sbx.app_root / "releases" / "v2-fk").resolve())

    def test_verify_schema_isolates_historical_runpython_from_live_db_and_handles_dropped_historical_fields(
        self,
    ) -> None:
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

        # Build v1 -> v2 where:
        # - 0002 adds `temp_hist_col` and runs a `RunPython` using default ORM WITHOUT `.using(...)`
        #   that reads `temp_hist_col` AND mutates all existing `Comment.body` rows;
        # - 0003 subsequently removes `temp_hist_col`!
        staged_v1 = sbx.clone_staged_server("v1-hist")
        remote_server.deploy_release(cfg, staged_server=staged_v1, release_id="v1-hist")

        staged_v2 = sbx.clone_staged_server("v2-hist-dropped")
        (staged_v2 / "comments" / "migrations" / "0002_hist_runpython.py").write_text(
            "from django.db import migrations, models\n"
            "def mutate_on_default_db(apps, schema_editor):\n"
            "    print('RunPython progress output on stdout must not break JSON schema dump')\n"
            "    Comment = apps.get_model('comments', 'Comment')\n"
            "    # Deliberately omit `.using(schema_editor.connection.alias)` like real-world migrations!\n"
            "    list(Comment.objects.values_list('temp_hist_col', flat=True))\n"
            "    Comment.objects.all().update(body='CLOBBERED-BY-HISTORICAL-RUNPYTHON')\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0001_initial')]\n"
            "    operations = [\n"
            "        migrations.AddField(\n"
            "            model_name='comment',\n"
            "            name='temp_hist_col',\n"
            "            field=models.CharField(default='tmp', max_length=16),\n"
            "        ),\n"
            "        migrations.RunPython(mutate_on_default_db, migrations.RunPython.noop),\n"
            "    ]\n",
            encoding="utf-8",
        )
        (staged_v2 / "comments" / "migrations" / "0003_drop_temp_hist_col.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('comments', '0002_hist_runpython')]\n"
            "    operations = [\n"
            "        migrations.RemoveField(model_name='comment', name='temp_hist_col'),\n"
            "    ]\n",
            encoding="utf-8",
        )
        remote_server.deploy_release(cfg, staged_server=staged_v2, release_id="v2-hist-dropped")

        # Seed a live comment AND an un-normalized email row (which accounts/0002 would normalize if replayed!)
        live_comment = sbx.post_guest_comment("cc-source-analysis", "线上真实评论：严禁被预检篡改", client_ipv6="2001:db8::99")
        with contextlib.closing(sqlite3.connect(str(sbx.var_dir / "db.sqlite3"))) as conn:
            conn.execute(
                "INSERT INTO accounts_user "
                "(password, is_superuser, username, first_name, last_name, email, is_staff, is_active, date_joined, display_name, is_comment_admin) "
                "VALUES ('!', 0, 'raw_case_u', '', '', '  MixedCase@Example.COM  ', 0, 1, '2026-01-01T00:00:00Z', 'Raw', 0)"
            )
            conn.commit()

        # 1. No-migration deploy v3 (copies v2's migrations): runs `verify-schema` BEFORE backup/maintenance.
        #    Must SUCCEED (even though `temp_hist_col` no longer exists on live DB) AND must NOT touch live rows!
        staged_v3 = sbx.clone_staged_server("v3-no-mig")
        for mig_name in ("0002_hist_runpython.py", "0003_drop_temp_hist_col.py"):
            (staged_v3 / "comments" / "migrations" / mig_name).write_text(
                (staged_v2 / "comments" / "migrations" / mig_name).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        remote_server.deploy_release(cfg, staged_server=staged_v3, release_id="v3-no-mig")

        # 2. Failed code-only rollback to v1-hist AND successful code-only rollback to v2-hist-dropped:
        #    neither may mutate live comment body or raw email row!
        remote_server.rollback_release(cfg, to_release="v2-hist-dropped")
        _, _, comments_payload = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual(comments_payload["items"][0]["id"], live_comment["id"])
        self.assertEqual(comments_payload["items"][0]["body"], "线上真实评论：严禁被预检篡改")
        with contextlib.closing(sqlite3.connect(str(sbx.var_dir / "db.sqlite3"))) as conn:
            raw_email = conn.execute("SELECT email FROM accounts_user WHERE username='raw_case_u'").fetchone()[0]
        self.assertEqual(raw_email, "  MixedCase@Example.COM  ")

    def test_avatar_color_db_default_allows_code_only_rollback_and_old_release_user_writes(
        self,
    ) -> None:
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

        # Build previous release `v1` without `avatar_color` field or `>= 0004` migrations
        staged_v1 = sbx.clone_staged_server("v1-pre-avatar")
        v1_mig_dir = staged_v1 / "accounts" / "migrations"
        removed_migs = [
            mf
            for mf in sorted(v1_mig_dir.glob("[0-9][0-9][0-9][0-9]_*.py"))
            if int(mf.name[:4]) >= 4
        ]
        self.assertTrue(
            any(mf.name == "0004_user_avatar_color.py" for mf in removed_migs),
            "Expected 0004_user_avatar_color.py to exist in current server tree",
        )
        for mf in removed_migs:
            mf.unlink()

        v1_models = staged_v1 / "accounts" / "models.py"
        v1_models_src = v1_models.read_text(encoding="utf-8")
        v1_models_stripped, removed_count = re.subn(
            r"\n    avatar_color = models\.CharField\(\n(?:        .*\n)+?    \)\n",
            "\n",
            v1_models_src,
            count=1,
        )
        self.assertEqual(removed_count, 1)
        v1_models.write_text(v1_models_stripped, encoding="utf-8")

        remote_server.deploy_release(cfg, staged_server=staged_v1, release_id="v1")
        venv_py = sbx.app_root / "shared" / "venv" / "bin" / "python"
        v1_server_dir = sbx.app_root / "releases" / "v1" / "server"
        runtime_env, _, _, _ = remote_server.build_runtime_env(
            remote_server.load_and_validate_env_file(sbx.etc_env),
            var_dir=sbx.var_dir,
            app_root=sbx.app_root,
        )
        pre_user_proc = subprocess.run(
            [
                str(venv_py),
                str(v1_server_dir / "manage.py"),
                "ensure_verified_user",
                "--email",
                "pre-migration@example.com",
                "--display-name",
                "迁移前老读者",
                "--generate-password",
            ],
            cwd=str(v1_server_dir),
            env=runtime_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(pre_user_proc.returncode, 0, pre_user_proc.stderr)
        live_comment = sbx.post_guest_comment(
            "cc-source-analysis",
            "迁移前评论：纯代码回退后仍须完整保留",
            client_ipv6="2001:db8::77",
        )

        # Deploy current release `v2` containing `avatar_color` (with db_default="") + `0004_user_avatar_color`
        staged_v2 = sbx.clone_staged_server("v2-with-avatar")
        remote_server.deploy_release(cfg, staged_server=staged_v2, release_id="v2")
        self.assertEqual(
            (sbx.app_root / "current").resolve(),
            (sbx.app_root / "releases" / "v2").resolve(),
        )
        with contextlib.closing(sqlite3.connect(str(sbx.var_dir / "db.sqlite3"))) as conn:
            pre_row = conn.execute(
                "SELECT display_name, avatar_color FROM accounts_user WHERE email = ?",
                ("pre-migration@example.com",),
            ).fetchone()
        self.assertEqual(pre_row, ("迁移前老读者", ""))

        # Code-only rollback to `v1` WITHOUT `restore_db` must pass sqlite_ops schema gate!
        remote_server.rollback_release(cfg, to_release="v1")
        self.assertFalse((sbx.app_root / "shared" / ".maintenance").exists())
        self.assertEqual(
            (sbx.app_root / "current").resolve(),
            (sbx.app_root / "releases" / "v1").resolve(),
        )

        # Under rolled-back `v1` code (whose User model lacks `avatar_color`), creating a new user must succeed!
        create_proc = subprocess.run(
            [
                str(venv_py),
                str(v1_server_dir / "manage.py"),
                "ensure_verified_user",
                "--email",
                "v1-after-rollback@example.com",
                "--display-name",
                "回退后新注册读者",
                "--generate-password",
            ],
            cwd=str(v1_server_dir),
            env=runtime_env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            create_proc.returncode,
            0,
            f"Creating user on rolled-back v1 failed:\n{create_proc.stdout}\n{create_proc.stderr}",
        )

        with contextlib.closing(sqlite3.connect(str(sbx.var_dir / "db.sqlite3"))) as conn:
            row = conn.execute(
                "SELECT display_name, avatar_color FROM accounts_user WHERE email = ?",
                ("v1-after-rollback@example.com",),
            ).fetchone()
        self.assertEqual(row, ("回退后新注册读者", ""))

        _, _, comments_after = sbx.http_request("/api/notes/cc-source-analysis/comments/")
        self.assertEqual([c["id"] for c in comments_after["items"]], [live_comment["id"]])


if __name__ == "__main__":
    unittest.main()
