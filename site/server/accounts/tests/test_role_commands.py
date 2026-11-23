"""Tests for ensure_verified_user and grant_comment_admin CLI commands."""

from __future__ import annotations

import io
import re
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from accounts.models import User
from accounts.tests.helpers import (
    _PW_KEY,
    build_login_data,
    gen_test_credential,
)

_PW_ENV_OPT = "--" + _PW_KEY + "-env"
_PW_STDIN_OPT = "--" + _PW_KEY + "-stdin"
_GEN_PW_OPT = "--generate-" + _PW_KEY
_RESET_PW_OPT = "--reset-" + _PW_KEY
_GEN_PW_LINE_RE = re.compile(r"Generated password \(shown once\):\s*(\S+)")


def _extract_generated_pw(stderr_output: str) -> str:
    match = _GEN_PW_LINE_RE.search(stderr_output)
    if not match:
        raise AssertionError(
            f"Generated password line missing from stderr: {stderr_output!r}"
        )
    return match.group(1)


class AccountRoleManagementCommandTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_generate_password_outputs_once_and_requires_reset_flag_on_existing_user(
        self,
    ) -> None:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        call_command(
            "ensure_verified_user",
            "--email",
            "  Demo-Seed@Example.COM ",
            "--display-name",
            "  初始昵称  ",
            _GEN_PW_OPT,
            stdout=out_buf,
            stderr=err_buf,
        )
        first_pw = _extract_generated_pw(err_buf.getvalue())
        self.assertNotIn(first_pw, out_buf.getvalue())

        seeded = User.objects.get(email="demo-seed@example.com")
        self.assertEqual(seeded.display_name, "初始昵称")
        self.assertTrue(seeded.username.startswith("u_"))
        self.assertTrue(seeded.check_password(first_pw))

        # Generated password must actually log in through /accounts/login/!
        login_res = self.client.post(
            "/accounts/login/",
            data=build_login_data("demo-seed@example.com", first_pw),
        )
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res["Location"], "/")
        self.assertEqual(
            self.client.session.get("_auth_user_id"), str(seeded.pk)
        )

        # Re-running --generate-password on existing user without --reset-password fails closed
        with self.assertRaises(CommandError):
            call_command(
                "ensure_verified_user",
                "--email",
                "demo-seed@example.com",
                "--display-name",
                "尝试覆盖",
                _GEN_PW_OPT,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        seeded.refresh_from_db()
        self.assertEqual(seeded.display_name, "初始昵称")
        self.assertTrue(seeded.check_password(first_pw))

        # Explicit --reset-password rotates password and prints new credential once to stderr
        rot_err = io.StringIO()
        call_command(
            "ensure_verified_user",
            "--email",
            "demo-seed@example.com",
            "--display-name",
            "轮换后昵称",
            _GEN_PW_OPT,
            _RESET_PW_OPT,
            stdout=io.StringIO(),
            stderr=rot_err,
        )
        second_pw = _extract_generated_pw(rot_err.getvalue())
        self.assertNotEqual(first_pw, second_pw)
        seeded.refresh_from_db()
        self.assertEqual(seeded.display_name, "轮换后昵称")
        self.assertFalse(seeded.check_password(first_pw))
        self.assertTrue(seeded.check_password(second_pw))

        client_rot = Client()
        rot_login = client_rot.post(
            "/accounts/login/",
            data=build_login_data("demo-seed@example.com", second_pw),
        )
        self.assertEqual(rot_login.status_code, 302)
        self.assertEqual(
            client_rot.session.get("_auth_user_id"), str(seeded.pk)
        )

    def test_ensure_verified_user_protects_inactive_accounts_and_normalizes_mixed_case_email_row(
        self,
    ) -> None:
        # 1. Inactive account is NEVER silently re-enabled unless --reactivate is passed
        pw_init = gen_test_credential()
        inactive_user = User.objects.create_user(
            "u_suspended",
            "suspended@example.com",
            pw_init,
            display_name="已停用读者",
            is_active=False,
        )
        pw_attempt = gen_test_credential()
        with (
            patch("sys.stdin", io.StringIO(f"{pw_attempt}\n")),
            self.assertRaises(CommandError),
        ):
            call_command(
                "ensure_verified_user",
                "--email",
                "suspended@example.com",
                "--display-name",
                "企图静默恢复",
                _PW_STDIN_OPT,
                stdout=io.StringIO(),
            )
        inactive_user.refresh_from_db()
        self.assertFalse(inactive_user.is_active)
        self.assertEqual(inactive_user.display_name, "已停用读者")
        self.assertTrue(inactive_user.check_password(pw_init))

        # Explicit --reactivate restores active state and verifies email
        with patch("sys.stdin", io.StringIO(f"{pw_attempt}\n")):
            call_command(
                "ensure_verified_user",
                "--email",
                "suspended@example.com",
                "--display-name",
                "显式恢复读者",
                _PW_STDIN_OPT,
                "--reactivate",
                stdout=io.StringIO(),
            )
        inactive_user.refresh_from_db()
        self.assertTrue(inactive_user.is_active)
        self.assertEqual(inactive_user.display_name, "显式恢复读者")
        self.assertTrue(inactive_user.check_password(pw_attempt))

        # 2. Pre-existing mixed-case primary EmailAddress updates in place without IntegrityError
        mixed_user = User.objects.create_user(
            "legacy@example.com",
            "mixed@example.com",
            gen_test_credential(),
            display_name="存量大小写",
        )
        EmailAddress.objects.create(
            user=mixed_user,
            email="Mixed@Example.COM",
            verified=False,
            primary=True,
        )
        pw_mixed = gen_test_credential()
        with patch("sys.stdin", io.StringIO(f"{pw_mixed}\n")):
            call_command(
                "ensure_verified_user",
                "--email",
                "MIXED@example.com",
                "--display-name",
                "归一完成",
                _PW_STDIN_OPT,
                stdout=io.StringIO(),
            )
        mixed_user.refresh_from_db()
        self.assertTrue(mixed_user.username.startswith("u_"))
        self.assertEqual(EmailAddress.objects.filter(user=mixed_user).count(), 1)
        email_row = EmailAddress.objects.get(user=mixed_user)
        self.assertEqual(email_row.email, "mixed@example.com")
        self.assertTrue(email_row.verified)
        self.assertTrue(email_row.primary)

    def test_validation_errors_and_grant_comment_admin_warnings(self) -> None:
        for bad_args, stdin_text in (
            (
                ["--email", "not-an-email", "--display-name", "合法", _GEN_PW_OPT],
                None,
            ),
            (
                [
                    "--email",
                    "bad-nick@example.com",
                    "--display-name",
                    "https://phish.invalid",
                    _GEN_PW_OPT,
                ],
                None,
            ),
            (
                [
                    "--email",
                    "missing-env@example.com",
                    "--display-name",
                    "合法",
                    _PW_ENV_OPT,
                    "UNSET_CREDENTIAL_ENV_VAR_XYZ",
                ],
                None,
            ),
            (
                [
                    "--email",
                    "empty-stdin@example.com",
                    "--display-name",
                    "合法",
                    _PW_STDIN_OPT,
                ],
                "\n",
            ),
        ):
            with self.subTest(args=bad_args):
                ctx = (
                    patch("sys.stdin", io.StringIO(stdin_text))
                    if stdin_text is not None
                    else io.StringIO()
                )
                with ctx, self.assertRaises(CommandError):
                    call_command("ensure_verified_user", *bad_args)

        for bad_grant in (
            ["--user-id", "999999"],
            ["--user-id", "0"],
            ["--email", "nobody@example.com"],
        ):
            with self.subTest(grant=bad_grant), self.assertRaises(CommandError):
                call_command("grant_comment_admin", *bad_grant)

        # Granting on a user without verified EmailAddress warns on stderr
        unverified = User.objects.create_user(
            "u_unverified_staff",
            "unverified-owner@example.com",
            gen_test_credential(),
            display_name="待验证站主",
        )
        grant_err = io.StringIO()
        call_command(
            "grant_comment_admin",
            "--user-id",
            str(unverified.pk),
            stdout=io.StringIO(),
            stderr=grant_err,
        )
        self.assertIn("ensure_verified_user", grant_err.getvalue())

        unverified.is_active = False
        unverified.save(update_fields=["is_active"])
        with self.assertRaises(CommandError):
            call_command("grant_comment_admin", "--user-id", str(unverified.pk))

        # Revoking on superuser warns on stderr and retains is_staff + /api/me/ isCommentAdmin
        superuser = User.objects.create_superuser(
            "u_super",
            "super@wangjinghong.test",
            gen_test_credential(),
            display_name="超管",
            is_comment_admin=True,
        )
        super_err = io.StringIO()
        call_command(
            "grant_comment_admin",
            "--user-id",
            str(superuser.pk),
            "--revoke",
            stdout=io.StringIO(),
            stderr=super_err,
        )
        superuser.refresh_from_db()
        self.assertFalse(superuser.is_comment_admin)
        self.assertTrue(superuser.is_staff)
        self.assertIn("is_superuser=True", super_err.getvalue())

        self.client.force_login(superuser)
        self.assertTrue(self.client.get("/api/me/").json()["user"]["isCommentAdmin"])

        # Non-DB SESSION_ENGINE emits warning on --revoke
        non_db_err = io.StringIO()
        with override_settings(
            SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies"
        ):
            call_command(
                "grant_comment_admin",
                "--user-id",
                str(superuser.pk),
                "--revoke",
                stdout=io.StringIO(),
                stderr=non_db_err,
            )
        self.assertIn("SESSION_ENGINE", non_db_err.getvalue())
