"""Tests for honeypot protection, rate limiting, HTTPS cookies, and layout inheritance."""

from __future__ import annotations

import tempfile
from urllib.parse import urlparse

from allauth.account.adapter import get_adapter
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings

from accounts.forms import HONEYPOT_FIELD_NAME
from accounts.models import User
from accounts.tests.helpers import (
    CONFIRM_URL_RE,
    build_login_data,
    build_signup_data,
    gen_test_credential,
    signup_and_verify_user,
)
from config.env import FILEBASED_CACHE_BACKEND
from config.middleware import NO_STORE_CACHE_CONTROL


class AccountSecurityAndHoneypotTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_authenticated_account_management_pages_inherit_base_layout(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="布局烟测",
            raw_email="layout-smoke@example.com",
        )
        self.client.force_login(user)
        for route in ("/accounts/email/", "/accounts/password/change/"):
            with self.subTest(route=route):
                res = self.client.get(route)
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)
                html = res.content.decode("utf-8")
                self.assertIn('class="auth-card"', html)
                self.assertIn("wangjinghong.com", html)
                self.assertNotIn("https://fonts.", html)
                self.assertNotIn("https://cdn.", html)

    def test_public_auth_forms_reject_honeypot_submissions_without_side_effects(
        self,
    ) -> None:
        user, pw_a = signup_and_verify_user(
            self.client,
            display_name="蜜罐目标",
            raw_email="honeypot-target@example.com",
        )

        for route in (
            "/accounts/signup/",
            "/accounts/login/",
            "/accounts/password/reset/",
        ):
            with self.subTest(get_route=route):
                page = self.client.get(route)
                self.assertEqual(page.status_code, 200)
                html = page.content.decode("utf-8")
                self.assertIn('class="auth-hp-field"', html)
                self.assertIn('name="website"', html)
                self.assertIn('tabindex="-1"', html)
                self.assertIn('autocomplete="off"', html)
                self.assertIn('aria-hidden="true"', html)

        bot_signup = self.client.post(
            "/accounts/signup/",
            data=build_signup_data(
                display_name="机器脚本",
                email_addr="bot-new@example.com",
                pw_main=gen_test_credential(),
                honeypot="https://spam.bot.invalid",
            ),
        )
        self.assertEqual(bot_signup.status_code, 200)
        self.assertIn(HONEYPOT_FIELD_NAME, bot_signup.context["form"].errors)
        self.assertTrue(bot_signup.context["form"].non_field_errors())
        self.assertNotIn(
            "https://spam.bot.invalid", bot_signup.content.decode("utf-8")
        )
        self.assertFalse(User.objects.filter(email="bot-new@example.com").exists())
        self.assertEqual(len(mail.outbox), 0)

        bot_login = self.client.post(
            "/accounts/login/",
            data=build_login_data(
                user.email,
                pw_a,
                honeypot="filled-by-bot",
            ),
        )
        self.assertEqual(bot_login.status_code, 200)
        self.assertIn(HONEYPOT_FIELD_NAME, bot_login.context["form"].errors)
        self.assertNotIn("filled-by-bot", bot_login.content.decode("utf-8"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 0)

        bot_reset = self.client.post(
            "/accounts/password/reset/",
            data={"email": user.email, "website": "dirty-autofill-val"},
        )
        self.assertEqual(bot_reset.status_code, 200)
        self.assertIn(HONEYPOT_FIELD_NAME, bot_reset.context["form"].errors)
        self.assertNotIn(
            "dirty-autofill-val", bot_reset.content.decode("utf-8")
        )
        self.assertEqual(len(mail.outbox), 0)

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

        user_a, _ = signup_and_verify_user(
            self.client,
            display_name="限流甲",
            raw_email="rl-a@wangjinghong.test",
        )
        user_b, pw_b = signup_and_verify_user(
            self.client,
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
                bad_pw = gen_test_credential()
                attacker_headers = {
                    "REMOTE_ADDR": "127.0.0.1",
                    "HTTP_X_FORWARDED_FOR": "198.51.100.1, 203.0.113.55",
                }
                for _ in range(2):
                    attempt = self.client.post(
                        "/accounts/login/",
                        data=build_login_data("rl-a@wangjinghong.test", bad_pw),
                        **attacker_headers,
                    )
                    self.assertEqual(attempt.status_code, 200)

                for idx in range(350):
                    cache.set(f"noise-entry-{idx}", idx, timeout=60)

                throttled = self.client.post(
                    "/accounts/login/",
                    data=build_login_data("rl-a@wangjinghong.test", bad_pw),
                    **attacker_headers,
                )
                self.assertEqual(throttled.status_code, 429)

                legit_client = Client()
                legit_login = legit_client.post(
                    "/accounts/login/",
                    data=build_login_data("rl-b@wangjinghong.test", pw_b),
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
        pw_a = gen_test_credential()
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
            data=build_signup_data(
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
            data=build_login_data("https-user@wangjinghong.test", pw_a),
            **https_extra,
        )
        self.assertEqual(login_post.status_code, 302)
        session_cookie = login_post.cookies["sessionid"]
        self.assertTrue(session_cookie["secure"])
        self.assertTrue(session_cookie["httponly"])
        self.assertEqual(session_cookie["samesite"], "Lax")
