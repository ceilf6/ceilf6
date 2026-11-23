"""End-to-end tests for email signup, verification, duplicate/race safety, logout, and reset."""

from __future__ import annotations

import secrets
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from allauth.account.models import EmailAddress
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings

from accounts.forms import AccountSignupForm
from accounts.models import User
from accounts.tests.helpers import (
    CONFIRM_URL_RE,
    RESET_URL_RE,
    _CSRF_KEY,
    _PW1_KEY,
    build_login_data,
    build_reset_key_data,
    build_signup_data,
    extract_csrf_token,
    gen_test_credential,
    read_filebased_messages,
    signup_and_verify_user,
)
from config.env import FILEBASED_EMAIL_BACKEND
from config.middleware import NO_STORE_CACHE_CONTROL


class EmailAccountFlowTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_end_to_end_filebased_signup_email_confirmation_and_login(self) -> None:
        pw_a = gen_test_credential()
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
                    data=build_signup_data(
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

                written_mails = read_filebased_messages(mail_dir)
                self.assertEqual(len(written_mails), 1)
                subject, body = written_mails[0]
                self.assertIn("请确认您的注册邮箱", subject)
                self.assertIn("您好：", body)
                self.assertNotIn("星河旅人", body)
                self.assertNotIn(user.username, body)

                url_match = CONFIRM_URL_RE.search(body)
                self.assertIsNotNone(url_match)
                confirm_path = urlparse(url_match.group(0)).path

                blocked_login = self.client.post(
                    "/accounts/login/",
                    data=build_login_data("staruser@example.com", pw_a),
                )
                self.assertEqual(blocked_login.status_code, 302)
                self.assertEqual(
                    blocked_login["Location"], "/accounts/confirm-email/"
                )
                self.assertNotIn("_auth_user_id", self.client.session)

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

                confirm_post = self.client.post(confirm_path)
                self.assertEqual(confirm_post.status_code, 302)
                self.assertEqual(confirm_post["Location"], "/accounts/login/")
                email_row.refresh_from_db()
                self.assertTrue(email_row.verified)

                self.client.get("/accounts/login/")
                pre_login_session_key = self.client.session.session_key
                self.assertTrue(pre_login_session_key)

                login_res = self.client.post(
                    "/accounts/login/",
                    data=build_login_data("STARUSER@Example.com", pw_a),
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

    def test_signup_rejects_unsafe_nicknames_and_similar_passwords(self) -> None:
        pw_a = gen_test_credential()
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
                    data=build_signup_data(
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
            data=build_signup_data(
                display_name=similar_nick,
                email_addr="similar-check@example.com",
                pw_main=f"{similar_nick}!",
            ),
        )
        self.assertEqual(similar_res.status_code, 200)
        self.assertIn(_PW1_KEY, similar_res.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_preexisting_and_concurrent_signup_never_500_or_enumerate(self) -> None:
        original_user, pw_orig = signup_and_verify_user(
            self.client,
            display_name="原始作者",
            raw_email="alice@example.com",
        )
        pw_other = gen_test_credential()

        throttled_dup = self.client.post(
            "/accounts/signup/",
            data=build_signup_data(
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
            data=build_signup_data(
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
            gen_test_credential(),
            display_name="管理员",
        )
        self.assertEqual(
            EmailAddress.objects.filter(user=cli_admin).count(), 0
        )
        cli_dup_res = self.client.post(
            "/accounts/signup/",
            data=build_signup_data(
                display_name="外部注册",
                email_addr="OPS-ROOT@WangJingHong.test",
                pw_main=pw_other,
            ),
        )
        self.assertEqual(cli_dup_res.status_code, 302)
        self.assertEqual(cli_dup_res["Location"], "/accounts/confirm-email/")
        self.assertEqual(User.objects.count(), 2)

        # Simulate true TOCTOU email race: colliding user row exists in DB when save() runs
        mail.outbox.clear()
        cache.clear()
        race_email = "race-user@wangjinghong.test"
        winner = User.objects.create_user(
            "u_race_winner",
            race_email,
            gen_test_credential(),
            display_name="并发赢家",
        )
        EmailAddress.objects.create(
            user=winner, email=race_email, verified=True, primary=True
        )

        with (
            patch.object(
                AccountSignupForm,
                "validate_unique_email",
                side_effect=lambda value: value.strip().lower(),
            ),
            self.assertLogs("accounts.forms", level="WARNING") as captured_logs,
        ):
            race_res = self.client.post(
                "/accounts/signup/",
                data=build_signup_data(
                    display_name="并发竞态",
                    email_addr=race_email,
                    pw_main=pw_other,
                ),
            )
        self.assertEqual(race_res.status_code, 302)
        self.assertEqual(race_res["Location"], "/accounts/confirm-email/")
        self.assertTrue(
            any("Concurrent signup IntegrityError" in entry for entry in captured_logs.output)
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("已关联现有账号", mail.outbox[0].body)

        # Unrelated IntegrityError (when target email row does NOT exist) must re-raise
        cache.clear()
        with patch.object(
            AccountSignupForm,
            "save",
            side_effect=IntegrityError("unrelated schema constraint failure"),
        ):
            with self.assertRaises(IntegrityError):
                self.client.post(
                    "/accounts/signup/",
                    data=build_signup_data(
                        display_name="非邮箱错误",
                        email_addr="non-existing-bug@wangjinghong.test",
                        pw_main=pw_other,
                    ),
                )

    def test_distinct_emails_can_register_identical_public_display_names(self) -> None:
        first_user, _ = signup_and_verify_user(
            self.client,
            display_name="清风明月",
            raw_email="one@example.com",
        )
        second_user, _ = signup_and_verify_user(
            self.client,
            display_name="清风明月",
            raw_email="two@example.com",
        )
        self.assertNotEqual(first_user.pk, second_user.pk)
        self.assertNotEqual(first_user.username, second_user.username)
        self.assertEqual(first_user.display_name, "清风明月")
        self.assertEqual(second_user.display_name, "清风明月")

    def test_tampered_and_already_used_confirmation_links_fail_gracefully(self) -> None:
        pw_a = gen_test_credential()
        self.client.post(
            "/accounts/signup/",
            data=build_signup_data(
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

    def test_logout_requires_csrf_post_and_invalidates_previous_session(self) -> None:
        user, pw_a = signup_and_verify_user(
            self.client,
            display_name="安全退出",
            raw_email="logout-test@example.com",
        )
        csrf_client = Client(enforce_csrf_checks=True)

        login_get = csrf_client.get("/accounts/login/")
        login_csrf = extract_csrf_token(login_get.content.decode("utf-8"))
        login_post = csrf_client.post(
            "/accounts/login/",
            data=build_login_data(
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

        csrf_fail = csrf_client.post("/accounts/logout/", data={})
        self.assertEqual(csrf_fail.status_code, 403)
        self.assertEqual(csrf_fail["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertTrue(
            Session.objects.filter(session_key=active_session_key).exists()
        )

        logout_csrf = extract_csrf_token(logout_html)
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
        user, pw_a = signup_and_verify_user(
            self.client,
            display_name="找回密码用户",
            raw_email="reset-flow@example.com",
        )
        pw_b = gen_test_credential()

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

        save_res = self.client.post(set_pw_path, data=build_reset_key_data(pw_b))
        self.assertEqual(save_res.status_code, 302)
        self.assertEqual(
            save_res["Location"], "/accounts/password/reset/key/done/"
        )

        replayed = self.client.get(reset_path)
        self.assertEqual(replayed.status_code, 200)
        self.assertIn("密码重置链接无效", replayed.content.decode("utf-8"))

        old_login = self.client.post(
            "/accounts/login/",
            data=build_login_data("reset-flow@example.com", pw_a),
        )
        self.assertEqual(old_login.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        new_login = self.client.post(
            "/accounts/login/",
            data=build_login_data("reset-flow@example.com", pw_b),
        )
        self.assertEqual(new_login.status_code, 302)
        self.assertEqual(new_login["Location"], "/")
        self.assertEqual(
            self.client.session.get("_auth_user_id"), str(user.pk)
        )
