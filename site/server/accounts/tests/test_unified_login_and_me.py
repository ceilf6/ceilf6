"""Tests for unified login, admin consolidation, role commands, and /api/me/."""

from __future__ import annotations

import io
import os
from types import ModuleType
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import include, path

from accounts.adapter import is_safe_internal_redirect_url
from accounts.models import User
from accounts.tests.helpers import (
    _PW_KEY,
    build_login_data,
    gen_test_credential,
    signup_and_verify_user,
)
from accounts.views import me_view
from config.middleware import NO_STORE_CACHE_CONTROL
from config.views import health_check

_PW_ENV_OPT = "--" + _PW_KEY + "-env"
_PW_STDIN_OPT = "--" + _PW_KEY + "-stdin"
_GEN_PW_OPT = "--generate-" + _PW_KEY


class UnifiedLoginAndRedirectSecurityTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_is_safe_internal_redirect_url_blocks_open_redirect_vectors(
        self,
    ) -> None:
        valid_paths = (
            "/",
            "/notes/cc-source-analysis",
            "/notes/cc-source-analysis?tab=comments#c-42",
            f"/{settings.DJANGO_ADMIN_PATH}accounts/user/",
        )
        for valid in valid_paths:
            with self.subTest(valid=valid):
                self.assertTrue(is_safe_internal_redirect_url(valid))

        malicious_targets = (
            "",
            "   ",
            " /notes/leading-space",
            "https://evil.example/phish",
            "http://127.0.0.1/notes/cross-host",
            "http://localhost/admin/",
            "//evil.example/phish",
            "///evil.example/phish",
            "/\\evil.example",
            "\\evil.example",
            "javascript:alert(1)",
            "JavaScript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "notes/relative-without-slash",
            "/notes\r\nLocation: https://evil.example",
        )
        for bad in malicious_targets:
            with self.subTest(bad=repr(bad)):
                self.assertFalse(is_safe_internal_redirect_url(bad))

    def test_login_signup_and_logout_honor_safe_next_and_reject_external_next(
        self,
    ) -> None:
        user, pw_a = signup_and_verify_user(
            self.client,
            display_name="回跳测试者",
            raw_email="redirect-user@example.com",
        )

        # Valid internal next on /accounts/login/ returns user to original article
        valid_login = self.client.post(
            "/accounts/login/?next=/notes/cc-source-analysis",
            data=build_login_data(
                user.email,
                pw_a,
                next_url="/notes/cc-source-analysis",
            ),
        )
        self.assertEqual(valid_login.status_code, 302)
        self.assertEqual(valid_login["Location"], "/notes/cc-source-analysis")

        # Valid internal next on /accounts/logout/ returns user to safe path
        valid_logout = self.client.post(
            "/accounts/logout/",
            data={"next": "/notes/cc-source-analysis"},
        )
        self.assertEqual(valid_logout.status_code, 302)
        self.assertEqual(valid_logout["Location"], "/notes/cc-source-analysis")

        evil_vectors = (
            "https://evil.example/steal",
            "//evil.example/steal",
            "/\\evil.example/steal",
            "\\evil.example",
            "javascript:alert(1)",
            "http://localhost/steal",
        )
        for bad_next in evil_vectors:
            with self.subTest(bad_next=bad_next):
                cache.clear()
                # Unauthenticated /accounts/login/ GET must not propagate unsafe next to signup_url
                login_page = self.client.get(
                    "/accounts/login/", data={"next": bad_next}
                )
                self.assertEqual(login_page.status_code, 200)
                self.assertNotIn("evil.example", login_page.context["signup_url"])

                # POST /accounts/login/ with unsafe next falls back to /
                res_login = self.client.post(
                    "/accounts/login/",
                    data=build_login_data(user.email, pw_a, next_url=bad_next),
                )
                self.assertEqual(res_login.status_code, 302)
                self.assertEqual(res_login["Location"], "/")

                # Authenticated GET /accounts/signup/?next=<evil> falls back to /
                res_signup_auth = self.client.get(
                    "/accounts/signup/", data={"next": bad_next}
                )
                self.assertEqual(res_signup_auth.status_code, 302)
                self.assertEqual(res_signup_auth["Location"], "/")

                # POST /accounts/logout/ with unsafe next falls back to /
                res_logout = self.client.post(
                    "/accounts/logout/", data={"next": bad_next}
                )
                self.assertEqual(res_logout.status_code, 302)
                self.assertEqual(res_logout["Location"], "/")


class AdminConsolidationAndRoleCommandTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_admin_three_states_unauthenticated_ordinary_403_and_owner_200(
        self,
    ) -> None:
        admin_root = f"/{settings.DJANGO_ADMIN_PATH}"
        admin_login = f"/{settings.DJANGO_ADMIN_PATH}login/"
        admin_users = f"/{settings.DJANGO_ADMIN_PATH}accounts/user/"

        # State A: Unauthenticated visitor on /{DJANGO_ADMIN_PATH} & /{DJANGO_ADMIN_PATH}login/
        for target in (admin_root, admin_login, admin_users):
            with self.subTest(unauth_get=target):
                res = self.client.get(target)
                self.assertEqual(res.status_code, 302)
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)
                parsed = urlparse(res["Location"])
                self.assertEqual(parsed.path, "/accounts/login/")
                self.assertEqual(parse_qs(parsed.query).get("next"), [target])

        unauth_post = self.client.post(
            admin_login,
            data={"username": "any", _PW_KEY: gen_test_credential()},
        )
        self.assertEqual(unauth_post.status_code, 302)
        self.assertTrue(
            unauth_post["Location"].startswith("/accounts/login/?next=")
        )

        # State B: Authenticated ordinary user (is_staff=False) -> immediate 403, zero redirect loop
        ordinary_pw = gen_test_credential()
        env_var = "TEST_ORDINARY_ACCOUNT_CRED"
        with patch.dict(os.environ, {env_var: ordinary_pw}):
            call_command(
                "ensure_verified_user",
                "--email",
                "reader-normal@example.com",
                "--display-name",
                "普通读者",
                _PW_ENV_OPT,
                env_var,
                stdout=io.StringIO(),
            )
        ordinary_client = Client()
        login_res = ordinary_client.post(
            "/accounts/login/",
            data=build_login_data("reader-normal@example.com", ordinary_pw),
        )
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res["Location"], "/")

        for target in (admin_root, admin_login, admin_users):
            with self.subTest(ordinary_target=target):
                direct_403 = ordinary_client.get(target)
                self.assertEqual(direct_403.status_code, 403)
                self.assertEqual(
                    direct_403["Cache-Control"], NO_STORE_CACHE_CONTROL
                )
                body_403 = direct_403.content.decode("utf-8")
                self.assertIn("403 · 无访问权限", body_403)
                self.assertIn("当前会话没有访问此页面或执行该操作的权限。", body_403)
                self.assertIn('class="auth-card"', body_403)
                self.assertNotIn("切换账号", body_403)
                self.assertNotIn("reader-normal@example.com", body_403)

                followed_403 = ordinary_client.get(target, follow=True)
                self.assertEqual(followed_403.redirect_chain, [])
                self.assertEqual(followed_403.status_code, 403)

        # State C: Site owner authorized via grant_comment_admin enters admin on same session
        owner_pw = gen_test_credential()
        with patch("sys.stdin", io.StringIO(f"{owner_pw}\n")):
            call_command(
                "ensure_verified_user",
                "--email",
                "owner@wangjinghong.test",
                "--display-name",
                "站主王惊鸿",
                _PW_STDIN_OPT,
                stdout=io.StringIO(),
            )
        owner = User.objects.get(email="owner@wangjinghong.test")
        # Idempotent execution: run grant_comment_admin twice (by email & by user-id)
        call_command(
            "grant_comment_admin",
            "--email",
            "OWNER@WangJingHong.test",
            stdout=io.StringIO(),
        )
        call_command(
            "grant_comment_admin",
            "--user-id",
            str(owner.pk),
            stdout=io.StringIO(),
        )
        owner.refresh_from_db()
        self.assertTrue(owner.is_comment_admin)
        self.assertTrue(owner.is_staff)
        self.assertFalse(owner.is_superuser)

        owner_client = Client()
        # Enter via /{DJANGO_ADMIN_PATH} -> redirects to /accounts/login/?next=/{DJANGO_ADMIN_PATH}
        entry = owner_client.get(admin_root)
        self.assertEqual(entry.status_code, 302)
        owner_login = owner_client.post(
            entry["Location"],
            data=build_login_data(
                "owner@wangjinghong.test", owner_pw, next_url=admin_root
            ),
        )
        self.assertEqual(owner_login.status_code, 302)
        self.assertEqual(owner_login["Location"], admin_root)

        index_ok = owner_client.get(admin_root)
        self.assertEqual(index_ok.status_code, 200)
        self.assertEqual(index_ok["Cache-Control"], NO_STORE_CACHE_CONTROL)

        users_ok = owner_client.get(admin_users)
        self.assertEqual(users_ok.status_code, 200)
        self.assertIn("站主王惊鸿", users_ok.content.decode("utf-8"))

        # Staff with view_user only gets 403 (with non-misleading copy) on user add & change POST
        add_403 = owner_client.get(f"{admin_users}add/")
        self.assertEqual(add_403.status_code, 403)
        add_403_html = add_403.content.decode("utf-8")
        self.assertIn("当前会话没有访问此页面或执行该操作的权限。", add_403_html)
        self.assertNotIn("切换账号", add_403_html)
        change_post_403 = owner_client.post(
            f"{admin_users}{owner.pk}/change/", data={"display_name": "篡改"}
        )
        self.assertEqual(change_post_403.status_code, 403)

        # Visiting /{DJANGO_ADMIN_PATH}login/ (even with ?next=admin:login) redirects to admin index
        for login_target in (admin_login, f"{admin_login}?next={admin_login}"):
            login_while_staff = owner_client.get(login_target)
            self.assertEqual(login_while_staff.status_code, 302)
            self.assertEqual(login_while_staff["Location"], admin_root)

        # Revoking access clears role, removes staff, and immediately invalidates owner's DB session
        call_command(
            "grant_comment_admin",
            "--user-id",
            str(owner.pk),
            "--revoke",
            stdout=io.StringIO(),
        )
        call_command(
            "grant_comment_admin",
            "--user-id",
            str(owner.pk),
            "--revoke",
            stdout=io.StringIO(),
        )
        owner.refresh_from_db()
        self.assertFalse(owner.is_comment_admin)
        self.assertFalse(owner.is_staff)

        after_revoke = owner_client.get(admin_root)
        self.assertEqual(after_revoke.status_code, 302)
        self.assertTrue(
            after_revoke["Location"].startswith("/accounts/login/?next=")
        )
        self.assertIsNone(owner_client.get("/api/me/").json()["user"])

    def test_custom_django_admin_path_works_without_exposing_default_admin(
        self,
    ) -> None:
        custom_urlconf = ModuleType("test_custom_admin_urls")
        custom_urlconf.urlpatterns = [  # type: ignore[attr-defined]
            path("ops-console/", admin.site.urls),
            path("accounts/", include("allauth.account.urls")),
            path("api/health/", health_check, name="api-health"),
            path("api/me/", me_view, name="api-me"),
        ]
        with override_settings(
            DJANGO_ADMIN_PATH="ops-console/",
            ROOT_URLCONF=custom_urlconf,
        ):
            default_admin = self.client.get("/admin/login/")
            self.assertEqual(default_admin.status_code, 404)

            custom_unauth = self.client.get("/ops-console/login/")
            self.assertEqual(custom_unauth.status_code, 302)
            self.assertEqual(
                custom_unauth["Cache-Control"], NO_STORE_CACHE_CONTROL
            )
            self.assertTrue(
                custom_unauth["Location"].startswith(
                    "/accounts/login/?next=%2Fops-console%2Flogin%2F"
                )
            )

class CurrentSessionMeApiTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_anonymous_and_independent_sessions_return_privacy_safe_identity_and_csrf(
        self,
    ) -> None:
        pw_a = gen_test_credential()
        pw_b = gen_test_credential()
        with patch("sys.stdin", io.StringIO(f"{pw_a}\n")):
            call_command(
                "ensure_verified_user",
                "--email",
                "alice-private@example.com",
                "--display-name",
                "读者甲",
                _PW_STDIN_OPT,
                stdout=io.StringIO(),
            )
        with patch("sys.stdin", io.StringIO(f"{pw_b}\n")):
            call_command(
                "ensure_verified_user",
                "--email",
                "owner-private@example.com",
                "--display-name",
                "站主乙",
                _PW_STDIN_OPT,
                stdout=io.StringIO(),
            )
        call_command(
            "grant_comment_admin",
            "--email",
            "owner-private@example.com",
            stdout=io.StringIO(),
        )
        user_a = User.objects.get(email="alice-private@example.com")
        user_b = User.objects.get(email="owner-private@example.com")

        anon_client = Client(enforce_csrf_checks=True)
        client_a = Client(enforce_csrf_checks=True)
        client_b = Client(enforce_csrf_checks=True)

        # Anonymous GET /api/me/ initializes HttpOnly csrftoken cookie and returns user=None
        anon_res = anon_client.get("/api/me/")
        self.assertEqual(anon_res.status_code, 200)
        self.assertEqual(anon_res["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertIn("Cookie", anon_res["Vary"])
        self.assertTrue(anon_res.cookies["csrftoken"]["httponly"])
        self.assertEqual(anon_res.cookies["csrftoken"]["samesite"], "Lax")
        anon_json = anon_res.json()
        self.assertIsNone(anon_json["user"])
        self.assertTrue(len(anon_json["csrfToken"]) >= 32)

        head_res = anon_client.head("/api/me/")
        self.assertEqual(head_res.status_code, 200)
        self.assertEqual(head_res["Cache-Control"], NO_STORE_CACHE_CONTROL)

        # Non-GET/HEAD methods return 405 JSON even under enforce_csrf_checks=True without token
        for method_name in ("post", "put", "patch", "delete"):
            with self.subTest(method=method_name):
                res_405 = getattr(anon_client, method_name)("/api/me/")
                self.assertEqual(res_405.status_code, 405)
                self.assertEqual(res_405["Allow"], "GET, HEAD")
                self.assertEqual(
                    res_405["Cache-Control"], NO_STORE_CACHE_CONTROL
                )
                self.assertEqual(
                    res_405.json(),
                    {
                        "code": "method_not_allowed",
                        "message": "Method not allowed.",
                    },
                )

        # Log in client_a and client_b using csrfToken bootstrapped from GET /api/me/!
        csrf_a_boot = client_a.get("/api/me/").json()["csrfToken"]
        login_a = client_a.post(
            "/accounts/login/",
            data=build_login_data("alice-private@example.com", pw_a),
            HTTP_X_CSRFTOKEN=csrf_a_boot,
        )
        self.assertEqual(login_a.status_code, 302)

        csrf_b_boot = client_b.get("/api/me/").json()["csrfToken"]
        login_b = client_b.post(
            "/accounts/login/",
            data=build_login_data("owner-private@example.com", pw_b),
            HTTP_X_CSRFTOKEN=csrf_b_boot,
        )
        self.assertEqual(login_b.status_code, 302)

        me_a = client_a.get("/api/me/")
        me_b = client_b.get("/api/me/")
        self.assertEqual(me_a.status_code, 200)
        self.assertEqual(me_b.status_code, 200)
        self.assertEqual(me_a["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertEqual(me_b["Cache-Control"], NO_STORE_CACHE_CONTROL)

        json_a = me_a.json()
        json_b = me_b.json()
        self.assertEqual((anon_json["guestCommentsAllowed"], json_a["guestCommentsAllowed"], json_b["guestCommentsAllowed"]), (True, True, True))
        self.assertEqual(
            json_a["user"],
            {
                "id": user_a.pk,
                "displayName": "读者甲",
                "isCommentAdmin": False,
            },
        )
        self.assertEqual(
            json_b["user"],
            {
                "id": user_b.pk,
                "displayName": "站主乙",
                "isCommentAdmin": True,
            },
        )
        for raw_text, user_obj in (
            (me_a.content.decode("utf-8"), user_a),
            (me_b.content.decode("utf-8"), user_b),
        ):
            self.assertNotIn("email", raw_text)
            self.assertNotIn("@", raw_text)
            self.assertNotIn(user_obj.username, raw_text)

        # Verify csrfToken from GET /api/me/ passes CsrfViewMiddleware via X-CSRFToken on POST /accounts/logout/
        logout_without_csrf = client_a.post("/accounts/logout/")
        self.assertEqual(logout_without_csrf.status_code, 403)

        logout_with_header = client_a.post(
            "/accounts/logout/",
            HTTP_X_CSRFTOKEN=json_a["csrfToken"],
        )
        self.assertEqual(logout_with_header.status_code, 302)
        self.assertIsNone(client_a.get("/api/me/").json()["user"])
        # Independent session B remains logged in!
        self.assertEqual(client_b.get("/api/me/").json()["user"]["id"], user_b.pk)

    def test_me_endpoint_handles_blank_display_name_and_inactive_users_safely(
        self,
    ) -> None:
        for uname, email_addr in (
            ("legacy@example.com", "legacy@example.com"),
            ("u_9f8e7d6c5b4a3210", "opaque-blank@example.com"),
        ):
            user_obj = User.objects.create_user(
                uname, email_addr, gen_test_credential(), display_name="  "
            )
            self.client.force_login(user_obj)
            res = self.client.get("/api/me/")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(
                res.json()["user"]["displayName"], f"用户 #{user_obj.pk}"
            )
            raw = res.content.decode("utf-8")
            self.assertNotIn("@", raw)
            self.assertNotIn(uname, raw)

        user_obj.is_active = False
        user_obj.save(update_fields=["is_active"])
        self.assertIsNone(self.client.get("/api/me/").json()["user"])
