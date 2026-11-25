"""Tests for 8-color avatar palette, user_avatar_color migration, settings UI, and /api/me/."""

from __future__ import annotations

import io
import re
from unittest.mock import patch

from django.contrib import admin, auth
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from accounts.admin import AccountUserAdmin
from accounts.avatar import (
    AVATAR_CHOICES,
    AVATAR_PALETTE,
    extract_avatar_initial,
    resolve_avatar_color,
)
from accounts.forms import ProfileSettingsForm
from accounts.models import User
from accounts.tests.helpers import gen_test_credential, signup_and_verify_user
from config.middleware import NO_STORE_CACHE_CONTROL

EXPECTED_PALETTE: tuple[tuple[str, str, str], ...] = (
    ("indigo", "靛蓝", "#4F46E5"),
    ("violet", "紫罗兰", "#7C3AED"),
    ("sky", "天蓝", "#0369A1"),
    ("teal", "青绿", "#0F766E"),
    ("emerald", "翠绿", "#047857"),
    ("amber", "琥珀", "#B45309"),
    ("rose", "玫红", "#BE123C"),
    ("slate", "石板灰", "#475569"),
)

PREVIEW_INITIAL_RE = re.compile(
    r'id=["\']settings-avatar-initial["\'][^>]*>(.*?)</span>',
    re.DOTALL,
)
PREVIEW_BOX_STYLE_RE = re.compile(
    r'id=["\']settings-avatar-preview["\'][^>]*style=["\']([^"\']*)["\']',
    re.DOTALL,
)
STYLE_ATTR_RE = re.compile(r'style=["\']([^"\']*)["\']')


def _srgb_channel_to_linear(channel_byte: int) -> float:
    c = channel_byte / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    cleaned = hex_color.lstrip("#")
    r = _srgb_channel_to_linear(int(cleaned[0:2], 16))
    g = _srgb_channel_to_linear(int(cleaned[2:4], 16))
    b = _srgb_channel_to_linear(int(cleaned[4:6], 16))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _wcag_contrast_with_white(hex_color: str) -> float:
    lum = _relative_luminance(hex_color)
    return (1.0 + 0.05) / (lum + 0.05)


class AvatarPaletteAndInitialUnitTests(TestCase):
    def test_palette_order_choices_and_wcag_aa_white_contrast(self) -> None:
        self.assertEqual(
            tuple((entry[0], entry[1], entry[2]) for entry in AVATAR_PALETTE),
            EXPECTED_PALETTE,
        )
        self.assertEqual(
            tuple(AVATAR_CHOICES),
            (("", "自动"), *((k, label) for k, label, _ in EXPECTED_PALETTE)),
        )
        for key, label, hex_color in AVATAR_PALETTE:
            with self.subTest(key=key, label=label, hex_color=hex_color):
                self.assertRegex(hex_color, r"^#[0-9A-F]{6}$")
                ratio = _wcag_contrast_with_white(hex_color)
                self.assertGreaterEqual(
                    ratio,
                    4.5,
                    f"{key} ({hex_color}) contrast against #FFFFFF is {ratio:.2f} (< 4.5)",
                )

    def test_extract_avatar_initial_matches_frontend_grapheme_contract(
        self,
    ) -> None:
        cases: tuple[tuple[str, str], ...] = (
            ("王", "王"),
            ("王景宏", "王"),
            ("abc", "A"),
            ("🇨🇳", "🇨🇳"),
            ("🇨🇳 旅人", "🇨🇳"),
            ("👋🏽", "👋🏽"),
            ("👋🏽 朋友", "👋🏽"),
            ("👨‍👩‍👧", "👨‍👩‍👧"),
            ("👨🏽‍❤️‍💋‍👨🏻abc", "👨🏽‍❤️‍💋‍👨🏻"),
            ("1\ufe0f\u20e3abc", "1\ufe0f\u20e3"),
            ("e\u0301", "E\u0301"),
            ("किरण", "कि"),
            ("ß", "SS"),
            ("用户 #12", "用"),
            ("", "?"),
            ("   \t\n ", "?"),
        )
        for raw, expected in cases:
            with self.subTest(raw=repr(raw)):
                self.assertEqual(extract_avatar_initial(raw), expected)


class AvatarMigrationAndSettingsIntegrationTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_migrations_clean_default_blank_and_admin_untouched(self) -> None:
        call_command(
            "makemigrations",
            "--check",
            "--dry-run",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

        user = User.objects.create_user(
            "u_default_avatar",
            "default-avatar@example.com",
            gen_test_credential(),
            display_name="默认底色读者",
        )
        self.assertEqual(user.avatar_color, "")
        user.refresh_from_db()
        self.assertEqual(user.avatar_color, "")

        model_admin = admin.site._registry[User]
        self.assertIsInstance(model_admin, AccountUserAdmin)
        self.assertNotIn("avatar_color", model_admin.list_display)
        flattened_fields = [
            field_name
            for _, opts in model_admin.fieldsets
            for field_name in opts.get("fields", ())
        ]
        self.assertNotIn("avatar_color", flattened_fields)

    def test_sqlite_db_default_preserved_and_raw_insert_without_avatar_color_succeeds(
        self,
    ) -> None:
        with connection.cursor() as cursor:
            cols = cursor.execute("PRAGMA table_info(accounts_user)").fetchall()
            avatar_cols = [row for row in cols if row[1] == "avatar_color"]
            self.assertEqual(len(avatar_cols), 1)
            _, _, col_type, notnull, dflt_value, _ = avatar_cols[0]
            self.assertIn("CHAR", (col_type or "").upper())
            self.assertEqual(int(notnull), 1)
            self.assertEqual(dflt_value, "''")

            cursor.execute(
                "INSERT INTO accounts_user "
                "(password, is_superuser, username, first_name, last_name, email, "
                "is_staff, is_active, date_joined, display_name, is_comment_admin) "
                "VALUES ('!', 0, 'raw_no_avatar_col', '', '', 'raw-avatar@example.com', "
                "0, 1, '2026-01-01T00:00:00Z', '原生插入', 0)"
            )

        inserted = User.objects.get(username="raw_no_avatar_col")
        self.assertEqual(inserted.avatar_color, "")

    def test_auto_mode_assigns_deterministic_color_by_user_id_mod_8(
        self,
    ) -> None:
        self.assertEqual(resolve_avatar_color(None, ""), "#4F46E5")
        self.assertEqual(resolve_avatar_color(0, ""), "#4F46E5")
        self.assertEqual(
            resolve_avatar_color(3, "nonexistent"),
            EXPECTED_PALETTE[3][2],
        )

        created_users: list[User] = []
        for idx in range(10):
            u = User.objects.create_user(
                f"u_auto_{idx}",
                f"auto-{idx}@example.com",
                gen_test_credential(),
                display_name=f"自动色用户{idx}",
            )
            created_users.append(u)

        for u in created_users:
            expected_hex = EXPECTED_PALETTE[u.pk % 8][2]
            self.assertEqual(resolve_avatar_color(u.pk, ""), expected_hex)
            self.client.force_login(u)
            me_json = self.client.get("/api/me/").json()
            self.assertEqual(me_json["user"]["avatarColor"], expected_hex)

    def test_unauthenticated_me_response_structure_completely_unchanged(
        self,
    ) -> None:
        anon_res = self.client.get("/api/me/")
        self.assertEqual(anon_res.status_code, 200)
        self.assertEqual(anon_res["Cache-Control"], NO_STORE_CACHE_CONTROL)
        payload = anon_res.json()
        self.assertEqual(
            set(payload.keys()),
            {"user", "csrfToken", "guestCommentsAllowed"},
        )
        self.assertIsNone(payload["user"])
        self.assertNotIn("avatarColor", anon_res.content.decode("utf-8"))

    def test_selecting_preset_colors_persists_updates_me_and_uses_minimal_update_fields(
        self,
    ) -> None:
        user_a, _ = signup_and_verify_user(
            self.client,
            display_name="调色师甲",
            raw_email="palette-a@example.com",
        )
        user_b, _ = signup_and_verify_user(
            self.client,
            display_name="调色师乙",
            raw_email="palette-b@example.com",
        )
        client_a = Client()
        client_b = Client()
        client_a.force_login(user_a)
        client_b.force_login(user_b)

        initial_get = client_a.get("/accounts/settings/")
        self.assertEqual(initial_get.status_code, 200)
        initial_html = initial_get.content.decode("utf-8")
        self.assertIn("<fieldset", initial_html)
        self.assertIn("<legend", initial_html)
        self.assertIn("自动", initial_html)
        for _, label, _ in EXPECTED_PALETTE:
            self.assertIn(label, initial_html)

        for key, label, expected_hex in EXPECTED_PALETTE:
            with self.subTest(key=key, label=label):
                post_res = client_a.post(
                    "/accounts/settings/",
                    data={
                        "display_name": "调色师甲",
                        "avatar_color": key,
                        "next": "/blog",
                    },
                )
                self.assertEqual(post_res.status_code, 302)
                self.assertEqual(
                    post_res["Location"],
                    "/accounts/settings/?next=%2Fblog&saved=1",
                )
                user_a.refresh_from_db()
                self.assertEqual(user_a.avatar_color, key)
                self.assertEqual(
                    client_a.get("/api/me/").json()["user"]["avatarColor"],
                    expected_hex,
                )

                page_html = client_a.get("/accounts/settings/").content.decode(
                    "utf-8"
                )
                style_match = PREVIEW_BOX_STYLE_RE.search(page_html)
                self.assertIsNotNone(style_match)
                self.assertIn(expected_hex, style_match.group(1))
                self.assertRegex(
                    page_html,
                    rf'<input\b[^>]*name=["\']avatar_color["\'][^>]*value=["\']{key}["\'][^>]*checked',
                )

        # User B remains untouched on automatic color
        user_b.refresh_from_db()
        self.assertEqual(user_b.avatar_color, "")
        self.assertEqual(
            client_b.get("/api/me/").json()["user"]["avatarColor"],
            EXPECTED_PALETTE[user_b.pk % 8][2],
        )

        # Switch User A back to "" ("自动")
        reset_auto = client_a.post(
            "/accounts/settings/",
            data={
                "display_name": "调色师甲",
                "avatar_color": "",
                "next": "/",
            },
        )
        self.assertEqual(reset_auto.status_code, 302)
        user_a.refresh_from_db()
        self.assertEqual(user_a.avatar_color, "")
        self.assertEqual(
            client_a.get("/api/me/").json()["user"]["avatarColor"],
            EXPECTED_PALETTE[user_a.pk % 8][2],
        )

        # Verify column-level update_fields when ONLY avatar_color changes (concurrent grant preserved)
        real_get_user = auth.get_user

        def get_user_with_concurrent_grant(request):  # type: ignore[no-untyped-def]
            loaded_user = real_get_user(request)
            User.objects.filter(pk=user_a.pk).update(
                is_comment_admin=True,
                is_staff=True,
            )
            return loaded_user

        with (
            patch(
                "django.contrib.auth.get_user",
                side_effect=get_user_with_concurrent_grant,
            ),
            CaptureQueriesContext(connection) as color_only_ctx,
        ):
            color_only_res = client_a.post(
                "/accounts/settings/",
                data={
                    "display_name": "调色师甲",
                    "avatar_color": "rose",
                    "next": "/",
                },
            )
        self.assertEqual(color_only_res.status_code, 302)
        color_updates = [
            q["sql"]
            for q in color_only_ctx.captured_queries
            if q["sql"].lstrip().upper().startswith('UPDATE "ACCOUNTS_USER"')
            and '"avatar_color"' in q["sql"]
        ]
        self.assertEqual(len(color_updates), 1)
        self.assertNotIn('"display_name"', color_updates[0])
        self.assertNotIn('"is_comment_admin"', color_updates[0])
        self.assertNotIn('"is_staff"', color_updates[0])
        user_a.refresh_from_db()
        self.assertEqual(user_a.avatar_color, "rose")
        self.assertTrue(user_a.is_comment_admin)
        self.assertTrue(user_a.is_staff)

        # Verify zero UPDATE when neither display_name nor avatar_color changed
        with CaptureQueriesContext(connection) as noop_ctx:
            noop_res = client_a.post(
                "/accounts/settings/",
                data={
                    "display_name": "  调色师甲  ",
                    "avatar_color": "rose",
                    "next": "/",
                },
            )
        self.assertEqual(noop_res.status_code, 302)
        noop_writes = [
            q["sql"]
            for q in noop_ctx.captured_queries
            if q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
        ]
        self.assertEqual(noop_writes, [])

        # Verify nickname-only change does NOT write avatar_color column
        with CaptureQueriesContext(connection) as nick_only_ctx:
            nick_only_res = client_a.post(
                "/accounts/settings/",
                data={
                    "display_name": "调色师甲改名",
                    "avatar_color": "rose",
                    "next": "/",
                },
            )
        self.assertEqual(nick_only_res.status_code, 302)
        nick_updates = [
            q["sql"]
            for q in nick_only_ctx.captured_queries
            if q["sql"].lstrip().upper().startswith('UPDATE "ACCOUNTS_USER"')
        ]
        self.assertEqual(len(nick_updates), 1)
        self.assertIn('"display_name"', nick_updates[0])
        self.assertNotIn('"avatar_color"', nick_updates[0])

    def test_forged_avatar_color_keys_rejected_without_db_mutation_or_style_injection(
        self,
    ) -> None:
        valid_auto_form = ProfileSettingsForm(
            data={"display_name": "合法昵称", "avatar_color": ""}
        )
        self.assertTrue(valid_auto_form.is_valid())
        self.assertEqual(valid_auto_form.cleaned_data["avatar_color"], "")

        user, _ = signup_and_verify_user(
            self.client,
            display_name="防篡改读者",
            raw_email="palette-forged@example.com",
        )
        user.avatar_color = "teal"
        user.save(update_fields=["avatar_color"])
        self.client.force_login(user)

        forged_values = (
            "#000000",
            "#4F46E5",
            "javascript:alert(1)",
            "../",
            "unknown",
            "INDIGO",
            "   ",
            "#000000;background-image:url(//evil.example)",
        )
        palette_hexes = {hex_val for _, _, hex_val in EXPECTED_PALETTE}
        for bad_color in forged_values:
            with self.subTest(bad_color=repr(bad_color)):
                form = ProfileSettingsForm(
                    data={"display_name": "防篡改读者", "avatar_color": bad_color}
                )
                self.assertFalse(form.is_valid())
                self.assertIn("avatar_color", form.errors)

                res = self.client.post(
                    "/accounts/settings/",
                    data={
                        "display_name": "防篡改读者",
                        "avatar_color": bad_color,
                        "next": "/blog",
                    },
                )
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res["Cache-Control"], NO_STORE_CACHE_CONTROL)
                self.assertIn("avatar_color", res.context["form"].errors)
                html = res.content.decode("utf-8")
                self.assertIn('role="alert"', html)
                self.assertNotIn("已保存", html)

                preview_style = PREVIEW_BOX_STYLE_RE.search(html)
                self.assertIsNotNone(preview_style)
                self.assertEqual(
                    preview_style.group(1),
                    "background-color: #0F766E;",
                )
                if bad_color not in palette_hexes:
                    for style_val in STYLE_ATTR_RE.findall(html):
                        self.assertNotIn(bad_color, style_val)

                user.refresh_from_db()
                self.assertEqual(user.avatar_color, "teal")
                self.assertEqual(user.display_name, "防篡改读者")

    def test_settings_html_no_js_avatar_initial_renders_flag_and_skin_tone_emojis(
        self,
    ) -> None:
        user, _ = signup_and_verify_user(
            self.client,
            display_name="初始名",
            raw_email="emoji-preview@example.com",
        )
        self.client.force_login(user)

        for nickname, expected_initial in (
            ("🇨🇳 旅人", "🇨🇳"),
            ("👋🏽 朋友", "👋🏽"),
        ):
            with self.subTest(nickname=nickname):
                save_res = self.client.post(
                    "/accounts/settings/",
                    data={
                        "display_name": nickname,
                        "avatar_color": "violet",
                        "next": "/",
                    },
                )
                self.assertEqual(save_res.status_code, 302)

                get_res = self.client.get("/accounts/settings/")
                self.assertEqual(get_res.status_code, 200)
                html = get_res.content.decode("utf-8")
                match = PREVIEW_INITIAL_RE.search(html)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1).strip(), expected_initial)

        # Invalid POST error re-render preserves current user's saved public nickname initial
        invalid_post = self.client.post(
            "/accounts/settings/",
            data={
                "display_name": "   ",
                "avatar_color": "indigo",
                "next": "/",
            },
        )
        self.assertEqual(invalid_post.status_code, 200)
        err_html = invalid_post.content.decode("utf-8")
        err_initial_match = PREVIEW_INITIAL_RE.search(err_html)
        self.assertIsNotNone(err_initial_match)
        self.assertEqual(err_initial_match.group(1).strip(), "👋🏽")
