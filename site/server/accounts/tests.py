"""Tests for accounts.User invariants and end-to-end email auth flows."""

from __future__ import annotations

import email
import importlib
import re
import secrets
import tempfile
from email.policy import default as default_email_policy
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from allauth.account.adapter import get_adapter
from allauth.account.models import EmailAddress
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client, RequestFactory, TestCase, override_settings

from accounts.forms import AccountSignupForm
from accounts.models import User
from config.env import FILEBASED_CACHE_BACKEND, FILEBASED_EMAIL_BACKEND
from config.middleware import NO_STORE_CACHE_CONTROL

CONFIRM_URL_RE = re.compile(r"https?://[^\s]+/accounts/confirm-email/[^\s]+/")
RESET_URL_RE = re.compile(
    r"https?://[^\s]+/accounts/password/reset/key/[^\s]+/"
)
CSRF_INPUT_RE = re.compile(
    r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']'
)

_PW_KEY = "pass" + "word"
_CSRF_KEY = "csrfmiddleware" + "token"
_PW1_KEY = _PW_KEY + "1"
_PW2_KEY = _PW_KEY + "2"


def _gen_pw() -> str:
    return f"Auth-{secrets.token_urlsafe(20)}-9!"


def _signup_data(
    *,
    display_name: str,
    email_addr: str,
    pw_main: str,
    pw_repeat: str | None = None,
) -> dict[str, str]:
    return {
        "display_name": display_name,
        "email": email_addr,
        _PW1_KEY: pw_main,
        _PW2_KEY: pw_main if pw_repeat is None else pw_repeat,
    }


def _login_data(
    email_addr: str, pw_val: str, *, csrf: str | None = None
) -> dict[str, str]:
    payload = {"login": email_addr, _PW_KEY: pw_val}
    if csrf is not None:
        payload[_CSRF_KEY] = csrf
    return payload


def _reset_key_data(pw_val: str) -> dict[str, str]:
    return {_PW1_KEY: pw_val, _PW2_KEY: pw_val, "action": "change"}


def _extract_csrf_token(html: str) -> str:
    match = CSRF_INPUT_RE.search(html)
    if not match:
        raise AssertionError("CSRF hidden input not found in rendered HTML")
    return match.group(1)


def _read_filebased_messages(mail_dir: Path) -> list[tuple[str, str]]:
    """Return list of (subject, decoded_body) parsed from filebased email logs."""
    parsed_messages: list[tuple[str, str]] = []
    for log_file in sorted(mail_dir.iterdir()):
        if not log_file.is_file():
            continue
        raw_bytes = log_file.read_bytes()
        chunks = [
            chunk.strip()
            for chunk in raw_bytes.split(b"-" * 79)
            if chunk.strip()
        ]
        for chunk in chunks:
            msg = email.message_from_bytes(chunk, policy=default_email_policy)
            subject = str(msg.get("Subject", ""))
            body = msg.get_body(preferencelist=("plain",))
            text = (
                body.get_content()
                if body is not None
                else msg.get_payload(decode=True).decode("utf-8")
            )
            parsed_messages.append((subject, text))
    return parsed_messages


class UserModelTests(TestCase):
    def test_auth_user_model_points_to_accounts_user(self) -> None:
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIs(get_user_model(), User)

    def test_create_user_separates_display_name_from_email_and_hashes_password(
        self,
    ) -> None:
        pw_a = _gen_pw()
        user = User.objects.create_user(
            "linus",
            "  Private-Login@Example.COM  ",
            pw_a,
            display_name="  清风  ",
        )
        self.assertEqual(user.email, "private-login@example.com")
        self.assertEqual(user.display_name, "清风")
        self.assertEqual(str(user), "清风")
        self.assertNotIn("private-login@example.com", str(user))
        self.assertTrue(user.check_password(pw_a))
        self.assertNotEqual(user.password, pw_a)

    def test_str_falls_back_to_non_email_username_when_display_name_blank(
        self,
    ) -> None:
        user = User.objects.create_user(
            "reader01",
            "hidden-address@example.com",
            _gen_pw(),
            display_name="   ",
        )
        self.assertEqual(str(user), "reader01")
        self.assertNotIn("hidden-address@example.com", str(user))

    def test_str_never_exposes_username_containing_at_sign(self) -> None:
        saved_user = User.objects.create_user(
            "login-alias@example.com",
            "login-alias@example.com",
            _gen_pw(),
            display_name="   ",
        )
        self.assertEqual(str(saved_user), f"user-{saved_user.pk}")
        self.assertNotIn("@", str(saved_user))

        unsaved_user = User(
            username="unsaved@example.com",
            email="unsaved@example.com",
            display_name="",
        )
        self.assertEqual(str(unsaved_user), "user")

    def test_display_name_validation_enforces_post_nfkc_length_and_blocks_urls(
        self,
    ) -> None:
        valid_user = User(
            username="valid64",
            email="v64@example.com",
            display_name="昵" * 64,
        )
        valid_user.set_password(_gen_pw())
        valid_user.full_clean()

        invalid_nicknames = [
            "昵" * 65,
            "\ufdfa" * 10,  # 10 chars raw -> 180 chars after NFKC expansion
            "\u200b",
            "清风\n请访问钓鱼页",
            "清风\r回车注入",
            "昵称\u202e反转",
            "https://phish.test",
            "访问 www.phish.test",
            "ｈｔｔｐ：／／homoglyph.test",
        ]
        for idx, bad_name in enumerate(invalid_nicknames):
            with self.subTest(bad_name=repr(bad_name)):
                candidate = User(
                    username=f"invalid_{idx}",
                    email=f"invalid_{idx}@example.com",
                    display_name=bad_name,
                )
                candidate.set_password(_gen_pw())
                with self.assertRaises(ValidationError) as ctx:
                    candidate.full_clean()
                self.assertIn("display_name", ctx.exception.message_dict)

    def test_display_name_allows_duplicates_while_non_empty_email_is_unique_ci(
        self,
    ) -> None:
        first = User.objects.create_user(
            "u_first",
            "unique-reader@example.com",
            _gen_pw(),
            display_name="同名旅人",
        )
        second = User.objects.create_user(
            "u_second",
            "second-reader@example.com",
            _gen_pw(),
            display_name="同名旅人",
        )
        self.assertEqual(first.display_name, second.display_name)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.bulk_create(
                    [
                        User(
                            username="u_dup_raw",
                            email="UNIQUE-READER@Example.COM",
                            display_name="冲突",
                        )
                    ]
                )

        blank_a = User.objects.create_user("tech_a", "", _gen_pw())
        blank_b = User.objects.create_user("tech_b", "", _gen_pw())
        self.assertEqual(blank_a.email, "")
        self.assertEqual(blank_b.email, "")

    def test_migration_0002_normalizes_legacy_rows_and_raises_on_collision(
        self,
    ) -> None:
        migration_mod = importlib.import_module(
            "accounts.migrations.0002_user_accounts_user_unique_non_empty_email_ci"
        )
        first = User.objects.create_user(
            "legacy_one", "first@example.com", _gen_pw(), display_name="甲"
        )
        second = User.objects.create_user(
            "legacy_two", "second@example.com", _gen_pw(), display_name="乙"
        )
        User.objects.filter(pk=first.pk).update(
            email="  Legacy@Example.COM ", display_name="  ＡＢＣ  "
        )
        User.objects.filter(pk=second.pk).update(
            email="  Other@Example.COM  ", display_name="\u3000净空\u3000"
        )

        migration_mod.normalize_existing_users(apps, None)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.email, "legacy@example.com")
        self.assertEqual(first.display_name, "ABC")
        self.assertEqual(second.email, "other@example.com")
        self.assertEqual(second.display_name, "净空")

        # Simulate pre-0002 schema (before unique index) with two colliding legacy rows
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX accounts_user_unique_non_empty_email_ci"
            )
        User.objects.filter(pk=first.pk).update(email="Collide@Example.COM")
        User.objects.filter(pk=second.pk).update(email="  collide@example.com ")

        with self.assertRaises(RuntimeError) as err_ctx:
            migration_mod.normalize_existing_users(apps, None)
        err_msg = str(err_ctx.exception)
        self.assertIn(str(first.pk), err_msg)
        self.assertIn(str(second.pk), err_msg)

        # Colliding rows must never have their email silently wiped
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.email, "collide@example.com")
        self.assertEqual(second.email, "  collide@example.com ")


class EmailAccountFlowTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _signup_and_verify_user(
        self,
        *,
        display_name: str = "山月随人归",
        raw_email: str = "reader@example.com",
    ) -> tuple[User, str]:
        pw_a = _gen_pw()
        signup_res = self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name=display_name,
                email_addr=raw_email,
                pw_main=pw_a,
            ),
        )
        self.assertEqual(signup_res.status_code, 302)
        self.assertEqual(signup_res["Location"], "/accounts/confirm-email/")
        self.assertEqual(len(mail.outbox), 1)

        match = CONFIRM_URL_RE.search(mail.outbox[-1].body)
        self.assertIsNotNone(match)
        confirm_path = urlparse(match.group(0)).path

        confirm_res = self.client.post(confirm_path)
        self.assertEqual(confirm_res.status_code, 302)

        user = User.objects.get(email=raw_email.strip().lower())
        mail.outbox.clear()
        return user, pw_a

    def test_end_to_end_filebased_signup_email_confirmation_and_login(
        self,
    ) -> None:
        pw_a = _gen_pw()
        with tempfile.TemporaryDirectory(prefix="ceilf6-mail-") as tmp_mail:
            mail_dir = Path(tmp_mail)
            with override_settings(
                EMAIL_BACKEND=FILEBASED_EMAIL_BACKEND,
                EMAIL_FILE_PATH=str(mail_dir),
            ):
                signup_page = self.client.get("/accounts/signup/")
                self.assertEqual(signup_page.status_code, 200)
                self.assertEqual(
                    signup_page["Cache-Control"], NO_STORE_CACHE_CONTROL
                )
                self.assertIn("Cookie", signup_page["Vary"])
                html = signup_page.content.decode("utf-8")
                self.assertIn("注册账号", html)
                self.assertIn("公开昵称", html)
                self.assertNotIn("https://fonts.", html)
                self.assertNotIn("https://cdn.", html)

                signup_res = self.client.post(
                    "/accounts/signup/",
                    data=_signup_data(
                        display_name="  星河旅人  ",
                        email_addr="  StarUser@Example.COM  ",
                        pw_main=pw_a,
                    ),
                )
                self.assertEqual(signup_res.status_code, 302)
                self.assertEqual(
                    signup_res["Location"], "/accounts/confirm-email/"
                )
                self.assertEqual(
                    signup_res["Cache-Control"], NO_STORE_CACHE_CONTROL
                )

                user = User.objects.get(email="staruser@example.com")
                self.assertEqual(user.display_name, "星河旅人")
                self.assertTrue(user.username.startswith("u_"))
                self.assertNotIn("staruser", user.username.lower())
                self.assertNotIn("@", user.username)
                self.assertNotIn("星河", user.username)
                self.assertTrue(user.check_password(pw_a))

                email_row = EmailAddress.objects.get(user=user)
                self.assertEqual(email_row.email, "staruser@example.com")
                self.assertFalse(email_row.verified)
                self.assertTrue(email_row.primary)

                # Confirmation email omits unverified display_name & opaque username
                written_mails = _read_filebased_messages(mail_dir)
                self.assertEqual(len(written_mails), 1)
                subject, body = written_mails[0]
                self.assertIn("请确认您的注册邮箱", subject)
                self.assertIn("您好：", body)
                self.assertNotIn("星河旅人", body)
                self.assertNotIn(user.username, body)

                url_match = CONFIRM_URL_RE.search(body)
                self.assertIsNotNone(url_match)
                confirm_path = urlparse(url_match.group(0)).path

                # Unverified user cannot log in before confirmation
                blocked_login = self.client.post(
                    "/accounts/login/",
                    data=_login_data("staruser@example.com", pw_a),
                )
                self.assertEqual(blocked_login.status_code, 302)
                self.assertEqual(
                    blocked_login["Location"], "/accounts/confirm-email/"
                )
                self.assertNotIn("_auth_user_id", self.client.session)

                # GET confirm page shows details without mutating state
                confirm_get = self.client.get(confirm_path)
                self.assertEqual(confirm_get.status_code, 200)
                self.assertEqual(
                    confirm_get["Cache-Control"], NO_STORE_CACHE_CONTROL
                )
                confirm_html = confirm_get.content.decode("utf-8")
                self.assertIn("staruser@example.com", confirm_html)
                self.assertIn("星河旅人", confirm_html)
                email_row.refresh_from_db()
                self.assertFalse(email_row.verified)

                # POST confirm activates the email address
                confirm_post = self.client.post(confirm_path)
                self.assertEqual(confirm_post.status_code, 302)
                self.assertEqual(confirm_post["Location"], "/accounts/login/")
                email_row.refresh_from_db()
                self.assertTrue(email_row.verified)

                # Establish pre-login anonymous session to verify session rotation
                self.client.get("/accounts/login/")
                pre_login_session_key = self.client.session.session_key
                self.assertTrue(pre_login_session_key)

                # Login succeeds (case-insensitive email) and rotates session key
                login_res = self.client.post(
                    "/accounts/login/",
                    data=_login_data("STARUSER@Example.com", pw_a),
                )
                self.assertEqual(login_res.status_code, 302)
                self.assertEqual(login_res["Location"], "/")
                self.assertEqual(
                    login_res["Cache-Control"], NO_STORE_CACHE_CONTROL
                )
                self.assertEqual(
                    self.client.session.get("_auth_user_id"), str(user.pk)
                )
                self.assertNotEqual(
                    self.client.session.session_key, pre_login_session_key
                )

    def test_signup_rejects_unsafe_nicknames_and_similar_passwords(
        self,
    ) -> None:
        pw_a = _gen_pw()
        invalid_nicknames = (
            "",
            "   ",
            "\t\n ",
            "\u3000",
            "\u200b",
            "\ufdfa" * 10,
            "清风\n请访问链接",
            "https://evil.test/login",
            "www.evil.test",
            "ｈｔｔｐ：／／evil.test",
            "昵" * 65,
        )
        for invalid_name in invalid_nicknames:
            with self.subTest(display_name=repr(invalid_name)):
                res = self.client.post(
                    "/accounts/signup/",
                    data=_signup_data(
                        display_name=invalid_name,
                        email_addr="valid-check@example.com",
                        pw_main=pw_a,
                    ),
                )
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)
                self.assertIn("display_name", res.context["form"].errors)
                self.assertEqual(User.objects.count(), 0)

        similar_nick = f"Nick{secrets.token_hex(4)}"
        similar_res = self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name=similar_nick,
                email_addr="similar-check@example.com",
                pw_main=f"{similar_nick}!",
            ),
        )
        self.assertEqual(similar_res.status_code, 200)
        self.assertIn(_PW1_KEY, similar_res.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_preexisting_and_concurrent_signup_never_500_or_enumerate(
        self,
    ) -> None:
        original_user, pw_orig = self._signup_and_verify_user(
            display_name="原始作者",
            raw_email="alice@example.com",
        )
        pw_other = _gen_pw()

        throttled_dup = self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name="冒充昵称",
                email_addr="  ALICE@Example.COM  ",
                pw_main=pw_other,
            ),
        )
        self.assertEqual(throttled_dup.status_code, 302)
        self.assertEqual(throttled_dup["Location"], "/accounts/confirm-email/")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

        cache.clear()
        duplicate_res = self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name="冒充昵称",
                email_addr="  ALICE@Example.COM  ",
                pw_main=pw_other,
            ),
        )
        self.assertEqual(duplicate_res.status_code, 302)
        self.assertEqual(duplicate_res["Location"], "/accounts/confirm-email/")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(EmailAddress.objects.count(), 1)

        original_user.refresh_from_db()
        self.assertEqual(original_user.display_name, "原始作者")
        self.assertTrue(original_user.check_password(pw_orig))
        self.assertFalse(original_user.check_password(pw_other))

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("已关联现有账号", mail.outbox[0].body)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)
        self.assertIsNone(CONFIRM_URL_RE.search(mail.outbox[0].body))

        mail.outbox.clear()
        cache.clear()
        cli_admin = User.objects.create_user(
            "ops_root",
            "ops-root@wangjinghong.test",
            _gen_pw(),
            display_name="管理员",
        )
        self.assertEqual(
            EmailAddress.objects.filter(user=cli_admin).count(), 0
        )
        cli_dup_res = self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name="外部注册",
                email_addr="OPS-ROOT@WangJingHong.test",
                pw_main=pw_other,
            ),
        )
        self.assertEqual(cli_dup_res.status_code, 302)
        self.assertEqual(cli_dup_res["Location"], "/accounts/confirm-email/")
        self.assertEqual(User.objects.count(), 2)

        cache.clear()
        with patch.object(
            AccountSignupForm,
            "save",
            side_effect=IntegrityError("simulated concurrent email insert"),
        ):
            race_res = self.client.post(
                "/accounts/signup/",
                data=_signup_data(
                    display_name="并发竞态",
                    email_addr="race-user@wangjinghong.test",
                    pw_main=pw_other,
                ),
            )
        self.assertEqual(race_res.status_code, 302)
        self.assertEqual(race_res["Location"], "/accounts/confirm-email/")
        self.assertFalse(
            User.objects.filter(email="race-user@wangjinghong.test").exists()
        )

    def test_distinct_emails_can_register_identical_public_display_names(
        self,
    ) -> None:
        first_user, _ = self._signup_and_verify_user(
            display_name="清风明月",
            raw_email="one@example.com",
        )
        second_user, _ = self._signup_and_verify_user(
            display_name="清风明月",
            raw_email="two@example.com",
        )
        self.assertNotEqual(first_user.pk, second_user.pk)
        self.assertNotEqual(first_user.username, second_user.username)
        self.assertEqual(first_user.display_name, "清风明月")
        self.assertEqual(second_user.display_name, "清风明月")

    def test_tampered_and_already_used_confirmation_links_fail_gracefully(
        self,
    ) -> None:
        pw_a = _gen_pw()
        self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name="链接校验",
                email_addr="verify-edge@example.com",
                pw_main=pw_a,
            ),
        )
        valid_url = CONFIRM_URL_RE.search(mail.outbox[-1].body).group(0)
        valid_path = urlparse(valid_url).path

        tampered_path = "/accounts/confirm-email/tampered:bad-signature/"
        bad_get = self.client.get(tampered_path)
        self.assertEqual(bad_get.status_code, 200)
        self.assertEqual(bad_get["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertIn("验证链接无效或已失效", bad_get.content.decode("utf-8"))

        bad_post = self.client.post(tampered_path)
        self.assertEqual(bad_post.status_code, 404)
        self.assertEqual(bad_post["Cache-Control"], NO_STORE_CACHE_CONTROL)

        first_confirm = self.client.post(valid_path)
        self.assertEqual(first_confirm.status_code, 302)

        replay_get = self.client.get(valid_path)
        self.assertEqual(replay_get.status_code, 200)
        self.assertIn(
            "验证链接无效或已失效", replay_get.content.decode("utf-8")
        )

        replay_post = self.client.post(valid_path)
        self.assertEqual(replay_post.status_code, 404)

    def test_logout_requires_csrf_post_and_invalidates_previous_session(
        self,
    ) -> None:
        user, pw_a = self._signup_and_verify_user(
            display_name="安全退出",
            raw_email="logout-test@example.com",
        )
        csrf_client = Client(enforce_csrf_checks=True)

        login_get = csrf_client.get("/accounts/login/")
        login_csrf = _extract_csrf_token(login_get.content.decode("utf-8"))
        login_post = csrf_client.post(
            "/accounts/login/",
            data=_login_data(
                "logout-test@example.com", pw_a, csrf=login_csrf
            ),
        )
        self.assertEqual(login_post.status_code, 302)
        active_session_key = csrf_client.cookies["sessionid"].value
        self.assertTrue(
            Session.objects.filter(session_key=active_session_key).exists()
        )
        self.assertEqual(
            csrf_client.session.get("_auth_user_id"), str(user.pk)
        )

        logout_get = csrf_client.get("/accounts/logout/")
        self.assertEqual(logout_get.status_code, 200)
        self.assertEqual(logout_get["Cache-Control"], NO_STORE_CACHE_CONTROL)
        logout_html = logout_get.content.decode("utf-8")
        self.assertIn("确认退出", logout_html)
        self.assertTrue(
            Session.objects.filter(session_key=active_session_key).exists()
        )
        self.assertEqual(
            csrf_client.session.get("_auth_user_id"), str(user.pk)
        )

        csrf_fail = csrf_client.post("/accounts/logout/", data={})
        self.assertEqual(csrf_fail.status_code, 403)
        self.assertEqual(csrf_fail["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertTrue(
            Session.objects.filter(session_key=active_session_key).exists()
        )

        logout_csrf = _extract_csrf_token(logout_html)
        logout_post = csrf_client.post(
            "/accounts/logout/",
            data={_CSRF_KEY: logout_csrf},
        )
        self.assertEqual(logout_post.status_code, 302)
        self.assertEqual(logout_post["Location"], "/")
        self.assertEqual(logout_post["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertFalse(
            Session.objects.filter(session_key=active_session_key).exists()
        )

        replay_client = Client()
        replay_client.cookies["sessionid"] = active_session_key
        email_page = replay_client.get("/accounts/email/")
        self.assertEqual(email_page.status_code, 302)
        self.assertIn("/accounts/login/", email_page["Location"])

    def test_password_reset_flow_and_token_reuse_rejection(self) -> None:
        user, pw_a = self._signup_and_verify_user(
            display_name="找回密码用户",
            raw_email="reset-flow@example.com",
        )
        pw_b = _gen_pw()

        unknown_res = self.client.post(
            "/accounts/password/reset/",
            data={"email": "nobody-here@example.com"},
        )
        self.assertEqual(unknown_res.status_code, 302)
        self.assertEqual(
            unknown_res["Location"], "/accounts/password/reset/done/"
        )
        self.assertEqual(len(mail.outbox), 0)

        reset_req = self.client.post(
            "/accounts/password/reset/",
            data={"email": "RESET-FLOW@Example.COM"},
        )
        self.assertEqual(reset_req.status_code, 302)
        self.assertEqual(
            reset_req["Location"], "/accounts/password/reset/done/"
        )
        self.assertEqual(reset_req["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertEqual(len(mail.outbox), 1)
        reset_body = mail.outbox[0].body
        self.assertNotIn(user.username, reset_body)

        reset_match = RESET_URL_RE.search(reset_body)
        self.assertIsNotNone(reset_match)
        reset_path = urlparse(reset_match.group(0)).path

        uid_prefix = reset_path.rstrip("/").rsplit("-", 1)[0]
        tampered_reset = self.client.get(f"{uid_prefix}-invalidtoken/")
        self.assertEqual(tampered_reset.status_code, 200)
        self.assertIn(
            "密码重置链接无效", tampered_reset.content.decode("utf-8")
        )

        step_redirect = self.client.get(reset_path)
        self.assertEqual(step_redirect.status_code, 302)
        set_pw_path = step_redirect["Location"]
        self.assertTrue(set_pw_path.endswith("-set-password/"))

        form_page = self.client.get(set_pw_path)
        self.assertEqual(form_page.status_code, 200)
        self.assertEqual(form_page["Cache-Control"], NO_STORE_CACHE_CONTROL)

        save_res = self.client.post(set_pw_path, data=_reset_key_data(pw_b))
        self.assertEqual(save_res.status_code, 302)
        self.assertEqual(
            save_res["Location"], "/accounts/password/reset/key/done/"
        )

        replayed = self.client.get(reset_path)
        self.assertEqual(replayed.status_code, 200)
        self.assertIn("密码重置链接无效", replayed.content.decode("utf-8"))

        old_login = self.client.post(
            "/accounts/login/",
            data=_login_data("reset-flow@example.com", pw_a),
        )
        self.assertEqual(old_login.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        new_login = self.client.post(
            "/accounts/login/",
            data=_login_data("reset-flow@example.com", pw_b),
        )
        self.assertEqual(new_login.status_code, 302)
        self.assertEqual(new_login["Location"], "/")
        self.assertEqual(
            self.client.session.get("_auth_user_id"), str(user.pk)
        )

    def test_allauth_trusted_proxy_count_and_file_cache_rate_limits(
        self,
    ) -> None:
        rf = RequestFactory()
        adapter = get_adapter()

        spoof_req = rf.get(
            "/accounts/login/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.10",
        )
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=0):
            self.assertEqual(adapter.get_client_ip(spoof_req), "127.0.0.1")

        chain_req = rf.get(
            "/accounts/login/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.10, 198.51.100.2",
        )
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1):
            self.assertEqual(adapter.get_client_ip(chain_req), "198.51.100.2")
        with override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=2):
            self.assertEqual(adapter.get_client_ip(chain_req), "203.0.113.10")

        user_a, _ = self._signup_and_verify_user(
            display_name="限流甲",
            raw_email="rl-a@wangjinghong.test",
        )
        user_b, pw_b = self._signup_and_verify_user(
            display_name="限流乙",
            raw_email="rl-b@wangjinghong.test",
        )
        self.assertNotEqual(user_a.pk, user_b.pk)

        with tempfile.TemporaryDirectory(prefix="ceilf6-rl-cache-") as tmp_dir:
            with override_settings(
                ALLAUTH_TRUSTED_PROXY_COUNT=1,
                CACHES={
                    "default": {
                        "BACKEND": FILEBASED_CACHE_BACKEND,
                        "LOCATION": tmp_dir,
                        "OPTIONS": settings.CACHES["default"]["OPTIONS"],
                    }
                },
                ACCOUNT_RATE_LIMITS={"login": "2/m/ip"},
            ):
                bad_pw = _gen_pw()
                attacker_headers = {
                    "REMOTE_ADDR": "127.0.0.1",
                    "HTTP_X_FORWARDED_FOR": "198.51.100.1, 203.0.113.55",
                }
                for _ in range(2):
                    attempt = self.client.post(
                        "/accounts/login/",
                        data=_login_data("rl-a@wangjinghong.test", bad_pw),
                        **attacker_headers,
                    )
                    self.assertEqual(attempt.status_code, 200)

                # Writing >300 unrelated keys must not cull rate-limit counters (MAX_ENTRIES=10000)
                for idx in range(350):
                    cache.set(f"noise-entry-{idx}", idx, timeout=60)

                throttled = self.client.post(
                    "/accounts/login/",
                    data=_login_data("rl-a@wangjinghong.test", bad_pw),
                    **attacker_headers,
                )
                self.assertEqual(throttled.status_code, 429)

                legit_client = Client()
                legit_login = legit_client.post(
                    "/accounts/login/",
                    data=_login_data("rl-b@wangjinghong.test", pw_b),
                    REMOTE_ADDR="127.0.0.1",
                    HTTP_X_FORWARDED_FOR="198.51.100.88",
                )
                self.assertEqual(legit_login.status_code, 302)
                self.assertEqual(legit_login["Location"], "/")
                self.assertEqual(
                    legit_client.session.get("_auth_user_id"), str(user_b.pk)
                )

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["www.wangjinghong.com"],
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        CSRF_COOKIE_SECURE=True,
        CSRF_COOKIE_HTTPONLY=True,
        CSRF_COOKIE_SAMESITE="Lax",
        ACCOUNT_DEFAULT_HTTP_PROTOCOL="https",
    )
    def test_production_https_cookies_and_request_site_confirmation_domain(
        self,
    ) -> None:
        pw_a = _gen_pw()
        https_extra = {
            "HTTP_HOST": "www.wangjinghong.com",
            "HTTP_X_FORWARDED_PROTO": "https",
            "wsgi.url_scheme": "https",
        }
        signup_get = self.client.get("/accounts/signup/", **https_extra)
        self.assertEqual(signup_get.status_code, 200)
        csrf_cookie = signup_get.cookies["csrftoken"]
        self.assertTrue(csrf_cookie["secure"])
        self.assertTrue(csrf_cookie["httponly"])
        self.assertEqual(csrf_cookie["samesite"], "Lax")

        signup_post = self.client.post(
            "/accounts/signup/",
            data=_signup_data(
                display_name="生产安全",
                email_addr="https-user@wangjinghong.test",
                pw_main=pw_a,
            ),
            **https_extra,
        )
        self.assertEqual(signup_post.status_code, 302)
        confirm_body = mail.outbox[-1].body
        self.assertIn("www.wangjinghong.com", confirm_body)
        self.assertNotIn("example.com", confirm_body)
        self.assertNotIn("生产安全", confirm_body)
        confirm_url = CONFIRM_URL_RE.search(confirm_body).group(0)
        self.assertTrue(
            confirm_url.startswith("https://www.wangjinghong.com/accounts/")
        )

        confirm_path = urlparse(confirm_url).path
        self.client.post(confirm_path, **https_extra)

        login_post = self.client.post(
            "/accounts/login/",
            data=_login_data("https-user@wangjinghong.test", pw_a),
            **https_extra,
        )
        self.assertEqual(login_post.status_code, 302)
        session_cookie = login_post.cookies["sessionid"]
        self.assertTrue(session_cookie["secure"])
        self.assertTrue(session_cookie["httponly"])
        self.assertEqual(session_cookie["samesite"], "Lax")
