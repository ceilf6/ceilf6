"""Tests for toast feedback, suppressed stale/email messages, reset redirect, and blank nickname."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from allauth.account.adapter import get_adapter
from allauth.account.models import EmailAddress, get_emailconfirmation_model
from django.conf import settings
from django.contrib import messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.cache import cache
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve

from accounts.forms import AccountSignupForm, ProfileSettingsForm
from accounts.models import User
from accounts.tests.helpers import (
    CONFIRM_URL_RE,
    RESET_URL_RE,
    _PW1_KEY,
    _PW2_KEY,
    build_login_data,
    build_reset_key_data,
    build_signup_data,
    gen_test_credential,
    signup_and_verify_user,
)
from config.middleware import NO_STORE_CACHE_CONTROL

STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.DOTALL)
DISPLAY_NAME_INPUT_RE = re.compile(
    r'<input\b[^>]*name=["\']display_name["\'][^>]*>',
    re.DOTALL,
)
PREVIEW_INITIAL_RE = re.compile(
    r'id=["\']settings-avatar-initial["\'][^>]*>(.*?)</span>',
    re.DOTALL,
)


def _strip_style_blocks(html: str) -> str:
    return STYLE_BLOCK_RE.sub("", html)


def _extract_css_block(css: str, header_regex: str) -> str | None:
    """Extract a balanced {...} CSS block without coupling to indentation."""
    match = re.search(header_regex + r"\s*\{", css)
    if not match:
        return None
    depth = 1
    idx = match.end()
    start = idx
    while idx < len(css) and depth > 0:
        if css[idx] == "{":
            depth += 1
        elif css[idx] == "}":
            depth -= 1
        idx += 1
    return css[start : idx - 1] if depth == 0 else None


VOID_HTML_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


class _FeedbackDOMParser(HTMLParser):
    """Parse rendered account page HTML to verify toast and alert placement."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.toast_containers: list[dict[str, object]] = []
        self.toasts: list[dict[str, object]] = []
        self.close_buttons: list[dict[str, object]] = []
        self.alert_boxes: list[dict[str, object]] = []
        self._active_toast_idx: int | None = None
        self._active_alert_idx: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        ancestor_tags = [t for t, _ in self.stack]
        ancestor_classes = {cls for _, a in self.stack for cls in (a.get("class") or "").split()}

        if "auth-toasts" in classes:
            self.toast_containers.append(
                {"tag": tag, "attrs": attr_map, "ancestor_tags": ancestor_tags, "ancestor_classes": ancestor_classes}
            )
        if "auth-toast" in classes:
            self._active_toast_idx = len(self.toasts)
            self.toasts.append(
                {
                    "tag": tag,
                    "attrs": attr_map,
                    "ancestor_classes": ancestor_classes,
                    "text_parts": [],
                    "has_close_button": False,
                    "has_check_icon": False,
                }
            )
        if "auth-toast-icon" in classes and self._active_toast_idx is not None:
            self.toasts[self._active_toast_idx]["has_check_icon"] = attr_map.get("aria-hidden") == "true"
        if "auth-toast-close" in classes:
            self.close_buttons.append({"tag": tag, "attrs": attr_map, "inside_toast": self._active_toast_idx is not None})
            if self._active_toast_idx is not None:
                self.toasts[self._active_toast_idx]["has_close_button"] = True
        if "auth-error-box" in classes:
            self._active_alert_idx = len(self.alert_boxes)
            self.alert_boxes.append(
                {"tag": tag, "attrs": attr_map, "ancestor_tags": ancestor_tags, "ancestor_classes": ancestor_classes, "text_parts": []}
            )
        if tag.lower() not in VOID_HTML_TAGS:
            self.stack.append((tag, attr_map))

    def handle_data(self, data: str) -> None:
        in_close = any("auth-toast-close" in (a.get("class") or "").split() for _, a in self.stack)
        in_icon = any("auth-toast-icon" in (a.get("class") or "").split() for _, a in self.stack)
        if self._active_toast_idx is not None and not in_close and not in_icon:
            parts = self.toasts[self._active_toast_idx]["text_parts"]
            assert isinstance(parts, list)
            parts.append(data)
        if self._active_alert_idx is not None:
            alert_parts = self.alert_boxes[self._active_alert_idx]["text_parts"]
            assert isinstance(alert_parts, list)
            alert_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        popped_tag, popped_attrs = self.stack.pop()
        popped_classes = set((popped_attrs.get("class") or "").split())
        if popped_tag == tag and "auth-toast" in popped_classes:
            self._active_toast_idx = None
        if popped_tag == tag and "auth-error-box" in popped_classes:
            self._active_alert_idx = None


def _parse_dom(html: str) -> _FeedbackDOMParser:
    parser = _FeedbackDOMParser()
    parser.feed(html)
    return parser


def _attach_session_and_messages(request: HttpRequest) -> FallbackStorage:
    session = SessionStore()
    session.create()
    request.session = session
    storage = FallbackStorage(request)
    setattr(request, "_messages", storage)
    return storage


def _seed_client_messages(
    client: Client, entries: list[tuple[int, str]]
) -> None:
    """Persist Django messages into the test client's cookie and session stores."""
    session = client.session
    req = RequestFactory().get("/")
    req.session = session
    storage = FallbackStorage(req)
    setattr(req, "_messages", storage)
    for level, text in entries:
        messages.add_message(req, level, text)
    dummy = HttpResponseDummy()
    storage.update(dummy)  # type: ignore[arg-type]
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key or ""
    for key, morsel in dummy.cookies.items():
        client.cookies[key] = morsel.value


class HttpResponseDummy:
    """Minimal cookie-capable response stub for FallbackStorage.update()."""

    def __init__(self) -> None:
        from http.cookies import SimpleCookie

        self.cookies: SimpleCookie = SimpleCookie()

    def set_cookie(self, key: str, value: str = "", **_kwargs: object) -> None:
        self.cookies[key] = value

    def delete_cookie(self, key: str, **_kwargs: object) -> None:
        self.cookies.pop(key, None)


class AccountFeedbackMessagesTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    # --- Group 1: Items 1-5 (Suppressed stale messages & zero email leakage) ---

    def test_01_login_then_get_settings_never_shows_logged_in_message(
        self,
    ) -> None:
        user, pw = signup_and_verify_user(
            self.client,
            display_name="静默登录读者",
            raw_email="quiet-login@example.com",
        )
        login_res = self.client.post(
            "/accounts/login/",
            data=build_login_data(user.email, pw),
        )
        self.assertEqual(login_res.status_code, 302)

        settings_res = self.client.get("/accounts/settings/")
        self.assertEqual(settings_res.status_code, 200)
        html = settings_res.content.decode("utf-8")
        self.assertNotIn("成功登录", html)
        self.assertNotIn("role=\"status\"", html)

    def test_02_login_logout_relogin_leaves_zero_queued_messages(self) -> None:
        user, pw = signup_and_verify_user(
            self.client,
            display_name="进出无痕",
            raw_email="cycle-auth@example.com",
        )
        self.assertEqual(
            self.client.post(
                "/accounts/login/",
                data=build_login_data(user.email, pw),
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post("/accounts/logout/").status_code,
            302,
        )
        relogin_res = self.client.post(
            "/accounts/login/",
            data=build_login_data(user.email, pw),
        )
        self.assertEqual(relogin_res.status_code, 302)
        self.assertEqual(
            len(list(messages.get_messages(relogin_res.wsgi_request))),
            0,
        )

        settings_res = self.client.get("/accounts/settings/")
        self.assertEqual(settings_res.status_code, 200)
        html = settings_res.content.decode("utf-8")
        self.assertNotIn("成功登录", html)
        self.assertNotIn("已登出", html)
        self.assertEqual(
            len(list(messages.get_messages(settings_res.wsgi_request))),
            0,
        )

    def test_03_signup_and_verify_never_leaks_email_on_settings_including_authenticated_confirm(
        self,
    ) -> None:
        user, pw = signup_and_verify_user(
            self.client,
            display_name="零邮箱验证者",
            raw_email="zero-leak-signup@example.com",
        )
        login_res = self.client.post(
            "/accounts/login/",
            data=build_login_data(user.email, pw),
        )
        self.assertEqual(login_res.status_code, 302)

        settings_res = self.client.get("/accounts/settings/")
        self.assertEqual(settings_res.status_code, 200)
        html = settings_res.content.decode("utf-8")
        self.assertNotIn(user.email, html)
        self.assertNotIn("zero-leak-signup", html)
        self.assertNotIn("@", _strip_style_blocks(html))

        # Also test confirming an email while already authenticated in the same browser
        email_row = EmailAddress.objects.get(user=user)
        email_row.verified = False
        email_row.save(update_fields=["verified"])
        confirmation = get_emailconfirmation_model()(email_row)

        auth_confirm_res = self.client.post(
            f"/accounts/confirm-email/{confirmation.key}/"
        )
        self.assertEqual(auth_confirm_res.status_code, 302)
        self.assertEqual(auth_confirm_res["Location"], "/")

        after_confirm_settings = self.client.get("/accounts/settings/")
        after_html = after_confirm_settings.content.decode("utf-8")
        self.assertNotIn(user.email, after_html)
        self.assertNotIn("已确认Email", after_html)
        self.assertNotIn("@", _strip_style_blocks(after_html))

    def test_04_legacy_queued_message_containing_at_sign_is_dropped_without_empty_toast_box(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="过渡期读者",
            raw_email="legacy-queue@example.com",
        )
        # Anonymous account page with stale email info message
        _seed_client_messages(
            self.client,
            [(messages.INFO, "确认邮件已发往 legacy-queue@example.com。")],
        )
        login_page = self.client.get("/accounts/login/")
        self.assertEqual(login_page.status_code, 200)
        login_html = login_page.content.decode("utf-8")
        self.assertNotIn("legacy-queue@example.com", login_html)
        self.assertNotIn("确认邮件已发往", login_html)
        self.assertNotIn("@", _strip_style_blocks(login_html))
        self.assertNotIn('class="auth-toasts"', login_html)
        self.assertNotIn('role="status"', login_html)

        # Authenticated settings page with stale email message
        self.client.force_login(user)
        _seed_client_messages(
            self.client,
            [(messages.SUCCESS, "您已确认Email地址 legacy-queue@example.com。")],
        )
        settings_page = self.client.get("/accounts/settings/")
        self.assertEqual(settings_page.status_code, 200)
        settings_html = settings_page.content.decode("utf-8")
        self.assertNotIn("legacy-queue@example.com", settings_html)
        self.assertNotIn("您已确认Email", settings_html)
        self.assertNotIn("@", _strip_style_blocks(settings_html))
        self.assertNotIn('class="auth-toasts"', settings_html)

    def test_05_adapter_preserves_non_suppressed_templates_like_password_changed(
        self,
    ) -> None:
        from accounts.adapter import SUPPRESSED_MESSAGE_TEMPLATES

        self.assertEqual(
            SUPPRESSED_MESSAGE_TEMPLATES,
            frozenset(
                {
                    "account/messages/logged_in.txt",
                    "account/messages/logged_out.txt",
                    "account/messages/email_confirmation_sent.txt",
                    "account/messages/email_confirmed.txt",
                }
            ),
        )
        req = RequestFactory().get("/accounts/login/")
        _attach_session_and_messages(req)
        adapter = get_adapter(req)

        for suppressed in SUPPRESSED_MESSAGE_TEMPLATES:
            adapter.add_message(
                req,
                messages.SUCCESS,
                suppressed,
                {"email": "hidden@example.com", "name": "旅人"},
            )
        self.assertEqual([str(m) for m in messages.get_messages(req)], [])

        adapter.add_message(
            req,
            messages.SUCCESS,
            "account/messages/password_changed.txt",
        )
        adapter.add_message(
            req,
            messages.ERROR,
            message=adapter.error_messages["rate_limited"],
        )
        self.assertEqual(
            [str(m) for m in messages.get_messages(req)],
            ["密码已更新。", "操作过于频繁，请稍后再试。"],
        )

    # --- Group 2: Items 6-10a (Toast DOM structure, routing, CSS guardrails, context processor) ---

    def test_06_valid_settings_save_renders_toast_outside_auth_card_and_removes_auth_messages(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="原名",
            raw_email="toast-save@example.com",
        )
        self.client.force_login(user)

        post_res = self.client.post(
            "/accounts/settings/",
            data={"display_name": "新名", "next": "/blog"},
        )
        self.assertEqual(post_res.status_code, 302)

        page_res = self.client.get(post_res["Location"])
        self.assertEqual(page_res.status_code, 200)
        html = page_res.content.decode("utf-8")

        self.assertNotIn("auth-messages", html)
        main_close_idx = html.index("</main>")
        toasts_idx = html.index('class="auth-toasts"')
        self.assertGreater(toasts_idx, main_close_idx)

        dom = _parse_dom(html)
        self.assertEqual(len(dom.toast_containers), 1)
        container = dom.toast_containers[0]
        self.assertEqual(container["ancestor_tags"], ["html", "body"])
        self.assertNotIn("auth-card", container["ancestor_classes"])  # type: ignore[arg-type]
        self.assertNotIn("auth-shell", container["ancestor_classes"])  # type: ignore[arg-type]

        self.assertEqual(len(dom.toasts), 1)
        toast_text = "".join(dom.toasts[0]["text_parts"]).strip()  # type: ignore[arg-type]
        self.assertEqual(toast_text, "已保存")
        self.assertTrue(dom.toasts[0]["has_check_icon"])
        self.assertTrue(dom.toasts[0]["has_close_button"])

    def test_07_invalid_settings_post_on_saved_query_url_renders_zero_toast_or_close_button(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="原名",
            raw_email="toast-invalid-post@example.com",
        )
        self.client.force_login(user)

        res = self.client.post(
            "/accounts/settings/?next=%2Fblog&saved=1",
            data={"display_name": "   ", "next": "/blog"},
        )
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertIn('role="alert"', html)
        self.assertNotIn('role="status"', html)
        self.assertNotIn('class="auth-toasts"', html)
        self.assertNotIn('aria-label="关闭提示"', html)
        self.assertNotIn("×", _strip_style_blocks(html))

    def test_08_success_and_error_messages_split_into_toasts_and_inline_card_alerts(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="分流测试者",
            raw_email="split-levels@example.com",
        )
        self.client.force_login(user)

        _seed_client_messages(
            self.client,
            [
                (messages.SUCCESS, "操作已完成。"),
                (messages.INFO, "这是一条提示。"),
                (messages.WARNING, "请注意操作风险。"),
                (messages.ERROR, "操作过于频繁，请稍后再试。"),
            ],
        )
        res = self.client.get("/accounts/settings/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        dom = _parse_dom(html)

        toast_texts = [
            "".join(t["text_parts"]).strip()  # type: ignore[arg-type]
            for t in dom.toasts
        ]
        self.assertEqual(toast_texts, ["操作已完成。", "这是一条提示。"])

        self.assertEqual(len(dom.alert_boxes), 1)
        alert_box = dom.alert_boxes[0]
        self.assertEqual(alert_box["attrs"].get("role"), "alert")  # type: ignore[union-attr]
        self.assertIn("main", alert_box["ancestor_tags"])  # type: ignore[arg-type]
        self.assertIn("auth-card", alert_box["ancestor_classes"])  # type: ignore[arg-type]
        alert_text = "".join(alert_box["text_parts"])  # type: ignore[arg-type]
        self.assertIn("请注意操作风险。", alert_text)
        self.assertIn("操作过于频繁，请稍后再试。", alert_text)
        self.assertNotIn("操作已完成。", alert_text)

    def test_09_toast_a11y_attributes_present_only_when_toasts_non_empty(
        self,
    ) -> None:
        # Empty state on login and error-only login
        clean_login = self.client.get("/accounts/login/").content.decode("utf-8")
        self.assertNotIn('role="status"', clean_login)
        self.assertNotIn('aria-live="polite"', clean_login)
        self.assertNotIn('aria-label="关闭提示"', clean_login)
        self.assertNotIn('class="auth-toasts"', clean_login)

        _seed_client_messages(
            self.client,
            [(messages.ERROR, "登录尝试次数过多，请稍后再试。")],
        )
        err_only_login = self.client.get("/accounts/login/").content.decode(
            "utf-8"
        )
        self.assertIn('role="alert"', err_only_login)
        self.assertNotIn('role="status"', err_only_login)
        self.assertNotIn('aria-live="polite"', err_only_login)
        self.assertNotIn('aria-label="关闭提示"', err_only_login)
        self.assertNotIn('class="auth-toasts"', err_only_login)

        # Non-empty toast state
        confirmed_login = self.client.get(
            "/accounts/login/?confirmed=1"
        ).content.decode("utf-8")
        dom = _parse_dom(confirmed_login)
        self.assertEqual(len(dom.toast_containers), 1)
        attrs = dom.toast_containers[0]["attrs"]
        assert isinstance(attrs, dict)
        self.assertEqual(attrs.get("role"), "status")
        self.assertEqual(attrs.get("aria-live"), "polite")
        self.assertEqual(len(dom.close_buttons), 1)
        btn_attrs = dom.close_buttons[0]["attrs"]
        assert isinstance(btn_attrs, dict)
        self.assertEqual(btn_attrs.get("type"), "button")
        self.assertEqual(btn_attrs.get("aria-label"), "关闭提示")
        self.assertTrue(dom.close_buttons[0]["inside_toast"])

    def test_10_base_html_css_guardrails_for_centering_keyframes_and_reduced_motion(
        self,
    ) -> None:
        base_path = (
            Path(settings.BASE_DIR) / "templates" / "account" / "base.html"
        )
        raw = base_path.read_text(encoding="utf-8")
        style_match = STYLE_BLOCK_RE.search(raw)
        self.assertIsNotNone(style_match)
        css = style_match.group(0)

        # 1) .auth-toasts outer container never uses translateX(-50%) or animation
        toasts_rule_match = re.search(
            r"\.auth-toasts\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(toasts_rule_match)
        toasts_decl = toasts_rule_match.group(1)
        self.assertNotIn("translateX(-50%)", toasts_decl)
        self.assertNotIn("animation", toasts_decl)
        self.assertIn("inset-inline: 0", toasts_decl)
        self.assertIn("width: fit-content", toasts_decl)
        self.assertIn("margin-inline: auto", toasts_decl)
        self.assertIn("pointer-events: none", toasts_decl)

        # 2) Keyframe animation attaches to inner .auth-toast
        keyframe_names = re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", css)
        self.assertGreaterEqual(len(keyframe_names), 2)
        inner_toast_match = re.search(
            r"\.auth-toast\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(inner_toast_match)
        inner_toast_decl = inner_toast_match.group(1)
        self.assertIn("animation:", inner_toast_decl)
        self.assertTrue(
            any(name in inner_toast_decl for name in keyframe_names),
            f"Expected one of {keyframe_names} in .auth-toast rule",
        )

        # 3) prefers-reduced-motion never uses animation: none and uses step-end keyframes
        reduced_block = _extract_css_block(
            css,
            r"@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)",
        )
        self.assertIsNotNone(reduced_block)
        assert reduced_block is not None
        self.assertNotIn("animation: none", reduced_block)
        self.assertNotIn("animation:none", reduced_block)
        self.assertIn(".auth-toast", reduced_block)
        self.assertIn("step-end", reduced_block)
        self.assertIn("forwards", reduced_block)

    def test_10a_account_feedback_context_processor_unit_and_non_consumption(
        self,
    ) -> None:
        from accounts.context_processors import account_feedback

        rf = RequestFactory()

        # Non-/accounts/ routes return {} and do NOT mark message storage as used
        for non_account_path in ("/api/me/", "/", "/admin/login/"):
            with self.subTest(path=non_account_path):
                req = rf.get(non_account_path)
                storage = _attach_session_and_messages(req)
                messages.success(req, "密码已更新。")
                self.assertEqual(account_feedback(req), {})
                self.assertFalse(storage.used)

        # End-to-end check: hitting /api/me/ preserves queued messages for next /accounts/ page
        _seed_client_messages(
            self.client,
            [(messages.SUCCESS, "密码已更新。")],
        )
        api_res = self.client.get("/api/me/")
        self.assertEqual(api_res.status_code, 200)
        login_res = self.client.get("/accounts/login/")
        self.assertIn("密码已更新。", login_res.content.decode("utf-8"))

        # Error-only queue -> account_toasts empty, account_alerts has 1 item
        err_req = rf.get("/accounts/login/")
        err_req.resolver_match = resolve("/accounts/login/")
        _attach_session_and_messages(err_req)
        messages.error(err_req, "操作过于频繁，请稍后再试。")
        self.assertEqual(
            account_feedback(err_req),
            {
                "account_toasts": [],
                "account_alerts": ["操作过于频繁，请稍后再试。"],
            },
        )

        # Info/error containing '@' -> both lists empty
        at_req = rf.get("/accounts/login/")
        at_req.resolver_match = resolve("/accounts/login/")
        _attach_session_and_messages(at_req)
        messages.info(at_req, "确认邮件已发往 secret@example.com。")
        messages.error(at_req, "无法确认 secret@example.com。")
        self.assertEqual(
            account_feedback(at_req),
            {"account_toasts": [], "account_alerts": []},
        )

        # POST to /accounts/settings/?saved=1 or /accounts/login/?confirmed=1 -> never appends query toast
        post_settings_req = rf.post("/accounts/settings/?saved=1")
        post_settings_req.resolver_match = resolve("/accounts/settings/")
        _attach_session_and_messages(post_settings_req)
        self.assertEqual(
            account_feedback(post_settings_req),
            {"account_toasts": [], "account_alerts": []},
        )

        post_login_req = rf.post("/accounts/login/?confirmed=1")
        post_login_req.resolver_match = resolve("/accounts/login/")
        _attach_session_and_messages(post_login_req)
        self.assertEqual(
            account_feedback(post_login_req),
            {"account_toasts": [], "account_alerts": []},
        )

        # Null resolver_match (e.g. bare RequestFactory or 404 under /accounts/) never raises AttributeError
        bare_req = rf.get("/accounts/unknown-404/?saved=1&confirmed=1")
        self.assertIsNone(bare_req.resolver_match)
        self.assertEqual(
            account_feedback(bare_req),
            {"account_toasts": [], "account_alerts": []},
        )

        # Lazy evaluation: rendering non-HTML message/email templates on /accounts/ never consumes queued messages
        lazy_req = rf.post("/accounts/password/reset/")
        lazy_storage = _attach_session_and_messages(lazy_req)
        messages.success(lazy_req, "操作已完成。")
        rendered_txt = render_to_string(
            "account/messages/password_changed.txt",
            {},
            request=lazy_req,
        )
        self.assertEqual(rendered_txt.strip(), "密码已更新。")
        self.assertFalse(lazy_storage.used)
        self.assertEqual(
            [str(m) for m in messages.get_messages(lazy_req)],
            ["操作已完成。"],
        )

    # --- Group 3: Items 11-14 (Password reset redirect & toast, email confirm toast) ---

    def test_11_password_reset_flow_lands_on_login_with_single_toast_and_password_change_matches(
        self,
    ) -> None:
        user, old_pw = signup_and_verify_user(
            self.client,
            display_name="重置密码读者",
            raw_email="reset-toast@example.com",
        )
        new_pw = gen_test_credential()

        reset_req = self.client.post(
            "/accounts/password/reset/",
            data={"email": user.email},
        )
        self.assertEqual(reset_req.status_code, 302)
        reset_match = RESET_URL_RE.search(mail.outbox[-1].body)
        self.assertIsNotNone(reset_match)
        reset_path = urlparse(reset_match.group(0)).path

        step_redirect = self.client.get(reset_path)
        self.assertEqual(step_redirect.status_code, 302)
        set_pw_path = step_redirect["Location"]

        final_res = self.client.post(
            set_pw_path,
            data=build_reset_key_data(new_pw),
            follow=True,
        )
        self.assertEqual(final_res.status_code, 200)
        self.assertEqual(
            final_res.redirect_chain,
            [
                ("/accounts/password/reset/key/done/", 302),
                ("/accounts/login/", 302),
            ],
        )
        html = final_res.content.decode("utf-8")
        self.assertNotIn("密码修改成功", html)
        dom = _parse_dom(html)
        toast_texts = [
            "".join(t["text_parts"]).strip()  # type: ignore[arg-type]
            for t in dom.toasts
        ]
        self.assertEqual(toast_texts, ["密码已更新。"])

        # Subsequent login with new password succeeds
        login_res = self.client.post(
            "/accounts/login/",
            data=build_login_data(user.email, new_pw),
        )
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res["Location"], "/")

        # Authenticated password change (even with ACCOUNT_EMAIL_NOTIFICATIONS=True) renders the toast
        third_pw = gen_test_credential()
        with override_settings(ACCOUNT_EMAIL_NOTIFICATIONS=True):
            change_res = self.client.post(
                "/accounts/password/change/",
                data={
                    "oldpassword": new_pw,
                    _PW1_KEY: third_pw,
                    _PW2_KEY: third_pw,
                },
                follow=True,
            )
        self.assertEqual(change_res.status_code, 200)
        change_dom = _parse_dom(change_res.content.decode("utf-8"))
        change_toasts = [
            "".join(t["text_parts"]).strip()  # type: ignore[arg-type]
            for t in change_dom.toasts
        ]
        self.assertEqual(change_toasts, ["密码已更新。"])
        self.assertNotEqual(old_pw, third_pw)

        # Pre-existing queued message survives POST /accounts/password/reset/ mail rendering
        self.client.logout()
        _seed_client_messages(self.client, [(messages.SUCCESS, "操作已完成。")])
        self.assertEqual(
            self.client.post(
                "/accounts/password/reset/",
                data={"email": user.email},
            ).status_code,
            302,
        )
        reset_done_html = self.client.get(
            "/accounts/password/reset/done/"
        ).content.decode("utf-8")
        self.assertIn("操作已完成。", reset_done_html)

    def test_12_password_reset_done_endpoint_redirects_get_validates_next_and_405s_post(
        self,
    ) -> None:
        direct_get = self.client.get("/accounts/password/reset/key/done/")
        self.assertEqual(direct_get.status_code, 302)
        self.assertEqual(direct_get["Location"], "/accounts/login/")
        self.assertEqual(direct_get["Cache-Control"], NO_STORE_CACHE_CONTROL)

        safe_next_get = self.client.get(
            "/accounts/password/reset/key/done/",
            data={"next": "/blog"},
        )
        self.assertEqual(safe_next_get.status_code, 302)
        self.assertEqual(
            safe_next_get["Location"],
            "/accounts/login/?next=%2Fblog",
        )

        for unsafe_next in (
            "https://evil.example/phish",
            "//evil.example/phish",
            "javascript:alert(1)",
            "blog/relative",
        ):
            with self.subTest(unsafe_next=unsafe_next):
                bad_res = self.client.get(
                    "/accounts/password/reset/key/done/",
                    data={"next": unsafe_next},
                )
                self.assertEqual(bad_res.status_code, 302)
                self.assertEqual(bad_res["Location"], "/accounts/login/")

        post_res = self.client.post("/accounts/password/reset/key/done/")
        self.assertEqual(post_res.status_code, 405)
        self.assertEqual(post_res["Allow"], "GET")
        self.assertEqual(post_res["Cache-Control"], NO_STORE_CACHE_CONTROL)

    def test_13_password_reset_from_key_done_template_removed_and_unreferenced(
        self,
    ) -> None:
        site_root = Path(settings.BASE_DIR).parent
        removed_tpl = (
            Path(settings.BASE_DIR)
            / "templates"
            / "account"
            / "password_reset_from_key_done.html"
        )
        self.assertFalse(removed_tpl.exists())

        target_needle = "password_reset_from_key_done.html"
        this_file = Path(__file__).resolve()
        skip_dirs = {".venv", "node_modules", "dist", "__pycache__", "var", "staticfiles"}
        text_suffixes = {".py", ".html", ".txt", ".md", ".ts", ".tsx", ".js", ".mjs", ".css", ".sh", ".json"}

        offending: list[str] = []
        for path in site_root.rglob("*"):
            if any(part in skip_dirs for part in path.parts):
                continue
            if not path.is_file() or path.suffix not in text_suffixes or path.resolve() == this_file:
                continue
            if target_needle in path.read_text(encoding="utf-8"):
                offending.append(str(path.relative_to(site_root)))

        self.assertEqual(offending, [])

    def test_14_anonymous_email_confirmation_redirects_to_login_with_stateless_toast(
        self,
    ) -> None:
        pw = gen_test_credential()
        signup_res = self.client.post(
            "/accounts/signup/",
            data=build_signup_data(
                display_name="匿名确认读者",
                email_addr="anon-confirm@example.com",
                pw_main=pw,
            ),
        )
        self.assertEqual(signup_res.status_code, 302)
        confirm_url = CONFIRM_URL_RE.search(mail.outbox[-1].body).group(0)
        confirm_path = urlparse(confirm_url).path

        preview_res = self.client.get(confirm_path)
        self.assertEqual(preview_res.status_code, 200)

        confirm_res = self.client.post(confirm_path, follow=True)
        self.assertEqual(confirm_res.status_code, 200)
        self.assertEqual(
            confirm_res.redirect_chain,
            [("/accounts/login/?confirmed=1", 302)],
        )
        html = confirm_res.content.decode("utf-8")
        self.assertNotIn("anon-confirm@example.com", html)
        self.assertNotIn("@", _strip_style_blocks(html))
        dom = _parse_dom(html)
        toast_texts = [
            "".join(t["text_parts"]).strip()  # type: ignore[arg-type]
            for t in dom.toasts
        ]
        self.assertEqual(toast_texts, ["邮箱已确认，请登录。"])

        # Plain GET /accounts/login/ without confirmed=1 has no toast
        plain_login = self.client.get("/accounts/login/").content.decode("utf-8")
        self.assertNotIn("邮箱已确认，请登录。", plain_login)
        self.assertNotIn('class="auth-toasts"', plain_login)

        # Failed confirmation (email already verified by another user) never shows confirmed=1 toast
        rival_user = User.objects.create_user(
            "u_rival_14", "rival-temp@example.com", gen_test_credential()
        )
        stale_email = EmailAddress.objects.create(
            user=rival_user, email="anon-confirm@example.com", verified=False
        )
        stale_key = get_emailconfirmation_model()(stale_email).key
        conflict_res = self.client.post(
            f"/accounts/confirm-email/{stale_key}/", follow=True
        )
        self.assertEqual(
            conflict_res.redirect_chain, [("/accounts/login/", 302)]
        )
        conflict_html = conflict_res.content.decode("utf-8")
        self.assertNotIn("邮箱已确认，请登录。", conflict_html)
        self.assertNotIn("anon-confirm@example.com", conflict_html)
        self.assertNotIn("@", _strip_style_blocks(conflict_html))
        conflict_dom = _parse_dom(conflict_html)
        self.assertEqual(conflict_dom.toasts, [])
        self.assertEqual(len(conflict_dom.alert_boxes), 1)
        self.assertIn(
            "该邮箱地址已被其他账号验证",
            "".join(conflict_dom.alert_boxes[0]["text_parts"]),  # type: ignore[arg-type]
        )

    # --- Group 4: Items 15-17 (Settings blank nickname initial & placeholder) ---

    def test_15_blank_display_name_get_settings_leaves_input_empty_with_current_placeholder(
        self,
    ) -> None:
        # Optional current_public_name parameter preserves signup default when omitted
        default_form = ProfileSettingsForm()
        signup_placeholder = AccountSignupForm().fields["display_name"].widget.attrs[
            "placeholder"
        ]
        self.assertEqual(
            default_form.fields["display_name"].widget.attrs["placeholder"],
            signup_placeholder,
        )
        custom_form = ProfileSettingsForm(current_public_name="用户 #99")
        self.assertEqual(
            custom_form.fields["display_name"].widget.attrs["placeholder"],
            "当前显示为：用户 #99",
        )
        after_custom_default = ProfileSettingsForm()
        self.assertEqual(
            after_custom_default.fields["display_name"].widget.attrs["placeholder"],
            signup_placeholder,
        )

        legacy_user = User.objects.create_user(
            "u_blank_nick_15",
            "blank-15@example.com",
            gen_test_credential(),
            display_name="",
        )
        self.client.force_login(legacy_user)

        res = self.client.get("/accounts/settings/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")

        input_match = DISPLAY_NAME_INPUT_RE.search(html)
        self.assertIsNotNone(input_match)
        input_tag = input_match.group(0)
        self.assertNotIn(f'value="用户 #{legacy_user.pk}"', input_tag)
        val_match = re.search(r'\bvalue=["\']([^"\']*)["\']', input_tag)
        self.assertEqual(val_match.group(1) if val_match else "", "")
        self.assertIn(
            f'placeholder="当前显示为：用户 #{legacy_user.pk}"',
            input_tag,
        )

        initial_match = PREVIEW_INITIAL_RE.search(html)
        self.assertIsNotNone(initial_match)
        self.assertEqual(initial_match.group(1).strip(), "用")

    def test_16_blank_display_name_submitting_empty_keeps_db_blank_and_current_placeholder(
        self,
    ) -> None:
        legacy_user = User.objects.create_user(
            "u_blank_nick_16",
            "blank-16@example.com",
            gen_test_credential(),
            display_name="",
        )
        self.client.force_login(legacy_user)

        res = self.client.post(
            "/accounts/settings/",
            data={"display_name": "", "avatar_color": "", "next": "/"},
        )
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertIn("请输入公开昵称（不能仅包含空白字符）。", html)

        input_match = DISPLAY_NAME_INPUT_RE.search(html)
        self.assertIsNotNone(input_match)
        self.assertIn(
            f'placeholder="当前显示为：用户 #{legacy_user.pk}"',
            input_match.group(0),
        )

        legacy_user.refresh_from_db()
        self.assertEqual(legacy_user.display_name, "")

    def test_17_populated_display_name_get_settings_echoes_existing_nickname(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="明月松间照",
            raw_email="populated-17@example.com",
        )
        self.client.force_login(user)

        res = self.client.get("/accounts/settings/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        input_match = DISPLAY_NAME_INPUT_RE.search(html)
        self.assertIsNotNone(input_match)
        self.assertIn('value="明月松间照"', input_match.group(0))
        self.assertIn(
            'placeholder="当前显示为：明月松间照"',
            input_match.group(0),
        )
