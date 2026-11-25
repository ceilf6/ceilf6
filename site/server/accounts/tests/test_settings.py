"""Tests for /accounts/settings/ public nickname management, PRG flow, and layout blocks."""

from __future__ import annotations

import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib import auth
from django.core.cache import cache
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext

from accounts.forms import (
    AccountSignupForm,
    HoneypotFormMixin,
    ProfileSettingsForm,
)
from accounts.models import MAX_DISPLAY_NAME_LENGTH, User
from accounts.tests.helpers import (
    _CSRF_KEY,
    build_login_data,
    extract_csrf_token,
    gen_test_credential,
    signup_and_verify_user,
)
from comments.models import Comment
from config.middleware import NO_STORE_CACHE_CONTROL

ANCHOR_TAG_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.DOTALL)
FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.DOTALL)
HIDDEN_NEXT_RE = re.compile(
    r'<input\b[^>]*type=["\']hidden["\'][^>]*name=["\']next["\'][^>]*value=["\']([^"\']*)["\'][^>]*>',
)


class AccountSettingsTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_profile_settings_form_excludes_honeypot_and_aligns_with_signup(
        self,
    ) -> None:
        self.assertFalse(issubclass(ProfileSettingsForm, HoneypotFormMixin))
        form = ProfileSettingsForm()
        self.assertEqual(list(form.fields.keys()), ["display_name"])
        field = form.fields["display_name"]
        signup_field = AccountSignupForm().fields["display_name"]
        self.assertEqual(field.max_length, MAX_DISPLAY_NAME_LENGTH)
        self.assertEqual(field.error_messages, signup_field.error_messages)
        self.assertEqual(
            field.widget.attrs.get("maxlength"),
            str(MAX_DISPLAY_NAME_LENGTH),
        )
        self.assertEqual(field.widget.attrs.get("autocomplete"), "nickname")
        self.assertTrue(
            ProfileSettingsForm(data={"display_name": "🇨🇳 旅人"}).is_valid()
        )

    def test_unauthenticated_access_redirects_to_login_and_preserves_next(
        self,
    ) -> None:
        user, pw_a = signup_and_verify_user(
            self.client,
            display_name="旅人初名",
            raw_email="settings-unauth@example.com",
        )

        unauth_get = self.client.get("/accounts/settings/?next=%2Fblog")
        self.assertEqual(unauth_get.status_code, 302)
        self.assertEqual(unauth_get["Cache-Control"], NO_STORE_CACHE_CONTROL)
        parsed_login_loc = urlparse(unauth_get["Location"])
        self.assertEqual(parsed_login_loc.path, "/accounts/login/")
        expected_settings_target = "/accounts/settings/?next=%2Fblog"
        self.assertEqual(
            parse_qs(parsed_login_loc.query).get("next"),
            [expected_settings_target],
        )

        unauth_post = self.client.post(
            "/accounts/settings/?next=%2Fblog",
            data={"display_name": "未登录篡改", "next": "/blog"},
        )
        self.assertEqual(unauth_post.status_code, 302)
        self.assertTrue(
            unauth_post["Location"].startswith("/accounts/login/?next=")
        )
        user.refresh_from_db()
        self.assertEqual(user.display_name, "旅人初名")

        login_res = self.client.post(
            unauth_get["Location"],
            data=build_login_data(
                user.email,
                pw_a,
                next_url=expected_settings_target,
            ),
        )
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res["Location"], expected_settings_target)

        settings_page = self.client.get(login_res["Location"])
        self.assertEqual(settings_page.status_code, 200)
        html = settings_page.content.decode("utf-8")
        self.assertIn('<a href="/blog">← 返回原页面</a>', html)
        self.assertNotIn(user.email, html)
        next_match = HIDDEN_NEXT_RE.search(html)
        self.assertIsNotNone(next_match)
        self.assertEqual(next_match.group(1), "/blog")

        logout_page = self.client.get("/accounts/logout/")
        self.assertEqual(logout_page.status_code, 200)
        self.assertNotIn("成功登录", logout_page.content.decode("utf-8"))

    def test_get_echoes_current_display_name_and_renders_single_back_link(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="山月随人归",
            raw_email="settings-get@example.com",
        )
        self.client.force_login(user)

        res = self.client.get(
            "/accounts/settings/",
            data={"next": "/blog?tab=latest"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)
        self.assertIn("Cookie", res["Vary"])
        html = res.content.decode("utf-8")

        self.assertIn('value="山月随人归"', html)
        self.assertIn('maxlength="64"', html)
        self.assertIn('autocomplete="nickname"', html)
        self.assertNotIn('name="website"', html)
        self.assertNotIn("已保存", html)

        anchors = ANCHOR_TAG_RE.findall(html)
        self.assertEqual(anchors, ["← 返回原页面"])
        self.assertIn('<a href="/blog?tab=latest">← 返回原页面</a>', html)

        # Legacy blank display_name falls back to public_display_name in input
        legacy_user = User.objects.create_user(
            "u_legacy_blank_nick",
            "legacy-blank-nick@example.com",
            gen_test_credential(),
            display_name="",
        )
        self.client.force_login(legacy_user)
        legacy_res = self.client.get("/accounts/settings/")
        self.assertEqual(legacy_res.status_code, 200)
        legacy_html = legacy_res.content.decode("utf-8")
        self.assertIn(f'value="用户 #{legacy_user.pk}"', legacy_html)
        self.assertEqual(ANCHOR_TAG_RE.findall(legacy_html), ["← 返回原页面"])
        self.assertIn('<a href="/">← 返回原页面</a>', legacy_html)

    def test_valid_post_redirects_prg_updates_me_and_historical_comments(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="旧时署名",
            raw_email="settings-save@example.com",
        )
        self.client.force_login(user)

        comment = Comment.objects.create(
            note_slug="cc-source-analysis",
            author=user,
            body="这是一条历史评论，改名后应同步显示新署名。",
        )
        before_comments = self.client.get(
            "/api/notes/cc-source-analysis/comments/"
        ).json()
        self.assertEqual(
            before_comments["items"][0]["author"],
            {
                "kind": "member",
                "id": user.pk,
                "displayName": "旧时署名",
            },
        )

        save_res = self.client.post(
            "/accounts/settings/",
            data={
                "display_name": "  新署名 👋🏽  ",
                "next": "/blog/cc-source-analysis",
            },
        )
        self.assertEqual(save_res.status_code, 302)
        self.assertEqual(save_res["Cache-Control"], NO_STORE_CACHE_CONTROL)
        parsed_loc = urlparse(save_res["Location"])
        self.assertEqual(parsed_loc.path, "/accounts/settings/")
        loc_qs = parse_qs(parsed_loc.query)
        self.assertEqual(loc_qs.get("next"), ["/blog/cc-source-analysis"])
        self.assertEqual(loc_qs.get("saved"), ["1"])

        followed = self.client.get(save_res["Location"])
        self.assertEqual(followed.status_code, 200)
        followed_html = followed.content.decode("utf-8")
        self.assertIn('role="status"', followed_html)
        self.assertIn("已保存", followed_html)
        self.assertIn('value="新署名 👋🏽"', followed_html)
        self.assertIn(
            '<a href="/blog/cc-source-analysis">← 返回原页面</a>',
            followed_html,
        )

        me_payload = self.client.get("/api/me/").json()
        self.assertEqual(me_payload["user"]["displayName"], "新署名 👋🏽")

        after_comments = self.client.get(
            "/api/notes/cc-source-analysis/comments/"
        ).json()
        self.assertEqual(after_comments["items"][0]["id"], comment.pk)
        self.assertEqual(
            after_comments["items"][0]["author"]["displayName"],
            "新署名 👋🏽",
        )

    def test_invalid_display_names_echo_errors_without_modifying_database(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="稳固原名",
            raw_email="settings-invalid@example.com",
        )
        self.client.force_login(user)

        invalid_candidates = (
            "",
            "   ",
            "\t\n ",
            "\u3000",
            "昵" * 65,
            "\ufdfa" * 10,
            "\u200b",
            "👨‍👩‍👧",
            "清风\n换行注入",
            "https://evil.example/phish",
            "http://evil.example",
            "访问 www.test.com 领奖",
            "ｈｔｔｐ：／／homoglyph.test",
        )
        for bad_name in invalid_candidates:
            with self.subTest(bad_name=repr(bad_name)):
                res = self.client.post(
                    "/accounts/settings/",
                    data={"display_name": bad_name, "next": "/blog"},
                )
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)
                self.assertIn("display_name", res.context["form"].errors)
                html = res.content.decode("utf-8")
                self.assertIn('role="alert"', html)
                self.assertNotIn("已保存", html)
                user.refresh_from_db()
                self.assertEqual(user.display_name, "稳固原名")

    def test_csrf_enforced_post_requires_valid_token(self) -> None:
        user, pw_a = signup_and_verify_user(
            self.client,
            display_name="令牌守护",
            raw_email="settings-csrf@example.com",
        )
        csrf_client = Client(enforce_csrf_checks=True)

        login_get = csrf_client.get("/accounts/login/")
        login_csrf = extract_csrf_token(login_get.content.decode("utf-8"))
        login_post = csrf_client.post(
            "/accounts/login/",
            data=build_login_data(user.email, pw_a, csrf=login_csrf),
        )
        self.assertEqual(login_post.status_code, 302)

        settings_get = csrf_client.get("/accounts/settings/?next=%2Fblog")
        self.assertEqual(settings_get.status_code, 200)
        settings_csrf = extract_csrf_token(settings_get.content.decode("utf-8"))

        missing_csrf = csrf_client.post(
            "/accounts/settings/",
            data={"display_name": "无令牌修改", "next": "/blog"},
        )
        self.assertEqual(missing_csrf.status_code, 403)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "令牌守护")

        bad_csrf = csrf_client.post(
            "/accounts/settings/",
            data={
                "display_name": "伪造令牌修改",
                "next": "/blog",
                _CSRF_KEY: "bad-token-value",
            },
        )
        self.assertEqual(bad_csrf.status_code, 403)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "令牌守护")

        valid_post = csrf_client.post(
            "/accounts/settings/",
            data={
                "display_name": "合法令牌修改",
                "next": "/blog",
                _CSRF_KEY: settings_csrf,
            },
        )
        self.assertEqual(valid_post.status_code, 302)
        self.assertEqual(
            valid_post["Location"],
            "/accounts/settings/?next=%2Fblog&saved=1",
        )
        user.refresh_from_db()
        self.assertEqual(user.display_name, "合法令牌修改")

    def test_unsupported_http_methods_return_405(self) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="方法测试",
            raw_email="settings-method@example.com",
        )

        # Unauthenticated disallowed methods still return 405
        for method in ("put", "patch", "delete", "head", "options"):
            with self.subTest(auth=False, method=method):
                res = getattr(self.client, method)("/accounts/settings/")
                self.assertEqual(res.status_code, 405)
                self.assertEqual(res["Allow"], "GET, POST")
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)

        # Authenticated disallowed methods return 405
        self.client.force_login(user)
        for method in ("put", "patch", "delete", "head", "options"):
            with self.subTest(auth=True, method=method):
                res = getattr(self.client, method)("/accounts/settings/")
                self.assertEqual(res.status_code, 405)
                self.assertEqual(res["Allow"], "GET, POST")
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)

    def test_unsafe_next_urls_fallback_to_root_on_get_and_post(self) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="跳转卫士",
            raw_email="settings-next@example.com",
        )
        self.client.force_login(user)

        unsafe_next_values = (
            "//evil.example",
            "///evil.example/path",
            "blog/x",
            "/\\evil",
            "\\evil",
            "/blog\n",
            "/blog\r\nLocation: https://evil.example",
            "/blog\x00",
            "https://evil.example/phish",
            "javascript:alert(1)",
            "   ",
        )
        for idx, bad_next in enumerate(unsafe_next_values):
            with self.subTest(bad_next=repr(bad_next)):
                get_res = self.client.get(
                    "/accounts/settings/",
                    data={"next": bad_next},
                )
                self.assertEqual(get_res.status_code, 200)
                get_html = get_res.content.decode("utf-8")
                self.assertIn('<a href="/">← 返回原页面</a>', get_html)
                hidden_match = HIDDEN_NEXT_RE.search(get_html)
                self.assertIsNotNone(hidden_match)
                self.assertEqual(hidden_match.group(1), "/")

                post_res = self.client.post(
                    "/accounts/settings/?next=%2Fblog",
                    data={
                        "display_name": f"安全昵称{idx}",
                        "next": bad_next,
                    },
                )
                self.assertEqual(post_res.status_code, 302)
                parsed = urlparse(post_res["Location"])
                self.assertEqual(parsed.path, "/accounts/settings/")
                self.assertEqual(parse_qs(parsed.query).get("next"), ["/"])
                self.assertEqual(parse_qs(parsed.query).get("saved"), ["1"])

                has_control_char = any(
                    ch in bad_next for ch in ("\x00", "\n", "\r")
                )
                raw_qs = "" if has_control_char else f"next={bad_next}"
                post_query_only = self.client.post(
                    "/accounts/settings/",
                    QUERY_STRING=raw_qs,
                    data={"display_name": f"安全昵称{idx}"},
                )
                self.assertEqual(post_query_only.status_code, 302)
                parsed_q = urlparse(post_query_only["Location"])
                self.assertEqual(parse_qs(parsed_q.query).get("next"), ["/"])

    def test_submitting_unchanged_display_name_skips_database_update(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="不变如初",
            raw_email="settings-noop@example.com",
        )
        self.client.force_login(user)

        with CaptureQueriesContext(connection) as queries_ctx:
            res = self.client.post(
                "/accounts/settings/",
                data={"display_name": "  不变如初  ", "next": "/blog"},
            )

        self.assertEqual(res.status_code, 302)
        self.assertEqual(
            res["Location"],
            "/accounts/settings/?next=%2Fblog&saved=1",
        )
        write_queries = [
            q["sql"]
            for q in queries_ctx.captured_queries
            if q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
        ]
        self.assertEqual(write_queries, [])

    def test_save_updates_only_display_name_column_preserving_concurrent_fields(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="并发初态",
            raw_email="settings-partial-save@example.com",
        )
        self.assertFalse(user.is_comment_admin)
        self.assertFalse(user.is_staff)
        self.client.force_login(user)

        real_get_user = auth.get_user

        def get_user_with_concurrent_grant(request):  # type: ignore[no-untyped-def]
            loaded_user = real_get_user(request)
            # Simulate concurrent DB grant after user row was fetched into memory
            User.objects.filter(pk=user.pk).update(
                is_comment_admin=True,
                is_staff=True,
            )
            return loaded_user

        with (
            patch("django.contrib.auth.get_user", side_effect=get_user_with_concurrent_grant),
            CaptureQueriesContext(connection) as queries_ctx,
        ):
            res = self.client.post(
                "/accounts/settings/",
                data={"display_name": "并发新昵称", "next": "/"},
            )

        self.assertEqual(res.status_code, 302)
        user_updates = [
            q["sql"]
            for q in queries_ctx.captured_queries
            if q["sql"].lstrip().upper().startswith('UPDATE "ACCOUNTS_USER"')
        ]
        # Filter out our simulated queryset .update() which sets both is_comment_admin and is_staff
        view_updates = [
            sql for sql in user_updates if '"display_name"' in sql
        ]
        self.assertEqual(len(view_updates), 1)
        self.assertNotIn('"is_comment_admin"', view_updates[0])
        self.assertNotIn('"is_staff"', view_updates[0])
        self.assertNotIn('"email"', view_updates[0])
        self.assertNotIn('"password"', view_updates[0])

        user.refresh_from_db()
        self.assertEqual(user.display_name, "并发新昵称")
        self.assertTrue(user.is_comment_admin)
        self.assertTrue(user.is_staff)

    def test_user_a_saving_does_not_affect_user_b(self) -> None:
        user_a, _ = signup_and_verify_user(
            self.client,
            display_name="甲之原名",
            raw_email="user-a-settings@example.com",
        )
        user_b, _ = signup_and_verify_user(
            self.client,
            display_name="乙之原名",
            raw_email="user-b-settings@example.com",
        )
        client_a = Client()
        client_b = Client()
        client_a.force_login(user_a)
        client_b.force_login(user_b)

        res_a = client_a.post(
            "/accounts/settings/",
            data={"display_name": "甲之新名", "next": "/"},
        )
        self.assertEqual(res_a.status_code, 302)

        user_a.refresh_from_db()
        user_b.refresh_from_db()
        self.assertEqual(user_a.display_name, "甲之新名")
        self.assertEqual(user_b.display_name, "乙之原名")
        self.assertEqual(
            client_a.get("/api/me/").json()["user"]["displayName"],
            "甲之新名",
        )
        self.assertEqual(
            client_b.get("/api/me/").json()["user"]["displayName"],
            "乙之原名",
        )

    def test_settings_page_never_exposes_private_email_or_opaque_username(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="隐私隔离者",
            raw_email="secret-inbox-42@example.com",
        )
        self.client.force_login(user)

        responses = [
            self.client.get("/accounts/settings/"),
            self.client.get("/accounts/settings/?saved=1"),
            self.client.post(
                "/accounts/settings/",
                data={"display_name": "   ", "next": "/"},
            ),
        ]
        for idx, res in enumerate(responses):
            with self.subTest(case=idx):
                self.assertEqual(res.status_code, 200)
                html = res.content.decode("utf-8")
                html_without_style = re.sub(
                    r"<style\b[^>]*>.*?</style>",
                    "",
                    html,
                    flags=re.DOTALL,
                )
                self.assertNotIn(user.email, html)
                self.assertNotIn("secret-inbox-42", html)
                self.assertNotIn("example.com", html)
                self.assertNotIn(user.username, html)
                self.assertNotIn("@", html_without_style)

    def test_other_account_pages_retain_default_home_back_link(self) -> None:
        for route in (
            "/accounts/login/",
            "/accounts/signup/",
            "/accounts/password/reset/",
        ):
            with self.subTest(route=route):
                res = self.client.get(route)
                self.assertEqual(res.status_code, 200)
                html = res.content.decode("utf-8")
                self.assertIn('<a href="/">← 返回首页</a>', html)
                self.assertNotIn("← 返回原页面", html)

    def test_titles_use_unified_prefix_and_omit_legacy_domain_suffix(
        self,
    ) -> None:
        login_html = self.client.get("/accounts/login/").content.decode("utf-8")
        signup_html = self.client.get("/accounts/signup/").content.decode("utf-8")
        self.assertIn("<title>王景宏 · 邮箱登录</title>", login_html)
        self.assertIn("<title>王景宏 · 注册账号</title>", signup_html)

        user, _ = signup_and_verify_user(
            self.client,
            display_name="标题核验",
            raw_email="title-check@example.com",
        )
        self.client.force_login(user)
        settings_html = self.client.get("/accounts/settings/").content.decode(
            "utf-8"
        )
        self.assertIn("<title>王景宏 · 账号设置</title>", settings_html)

        # Check live authenticated routes including allauth built-ins inheriting base.html
        for route in (
            "/accounts/settings/",
            "/accounts/logout/",
            "/accounts/email/",
            "/accounts/password/change/",
            "/accounts/password/reset/",
            "/accounts/password/reset/done/",
            "/accounts/password/reset/key/done/",
            "/accounts/confirm-email/",
        ):
            with self.subTest(live_route=route):
                res = self.client.get(route)
                self.assertEqual(res.status_code, 200)
                html = res.content.decode("utf-8")
                self.assertIn("<title>王景宏 · ", html)
                self.assertNotIn("· wangjinghong.com", html)
                self.assertIn("<span>wangjinghong.com</span>", html)

        # Render remaining standalone templates extending account/base.html
        rf = RequestFactory()
        req = rf.get("/")
        req.user = user
        for template_name, ctx in (
            ("account/base.html", {}),
            ("account/account_inactive.html", {}),
            ("account/email_confirm.html", {"confirmation": None}),
            (
                "account/password_reset_from_key.html",
                {"token_fail": True},
            ),
            ("403.html", {}),
        ):
            with self.subTest(template=template_name):
                rendered = render_to_string(template_name, ctx, request=req)
                self.assertIn("<title>王景宏 · ", rendered)
                self.assertNotIn("· wangjinghong.com", rendered)

    def test_invalid_post_with_saved_query_param_hides_saved_and_keeps_clean_action(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="初始昵称",
            raw_email="settings-saved-edge@example.com",
        )
        self.client.force_login(user)

        for payload in (
            {"display_name": "   ", "next": "/blog"},
            {"display_name": "昵" * 65},
        ):
            with self.subTest(payload=payload):
                res = self.client.post(
                    "/accounts/settings/?next=%2Fblog&saved=1",
                    data=payload,
                )
                self.assertEqual(res.status_code, 200)
                html = res.content.decode("utf-8")
                self.assertIn('role="alert"', html)
                self.assertNotIn("已保存", html)
                self.assertNotIn('role="status"', html)

                form_match = FORM_TAG_RE.search(html)
                self.assertIsNotNone(form_match)
                self.assertIn('action="/accounts/settings/"', form_match.group(0))
                self.assertNotIn("?", form_match.group(0))

                next_match = HIDDEN_NEXT_RE.search(html)
                self.assertIsNotNone(next_match)
                self.assertEqual(next_match.group(1), "/blog")
                self.assertIn('<a href="/blog">← 返回原页面</a>', html)

        user.refresh_from_db()
        self.assertEqual(user.display_name, "初始昵称")
