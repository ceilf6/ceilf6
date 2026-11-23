"""Unit tests for accounts.User invariants, migrations, and UserAdmin config."""

from __future__ import annotations

import importlib

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase

from accounts.adapter import user_display
from accounts.admin import AccountUserAdmin
from accounts.models import User
from accounts.tests.helpers import gen_test_credential


class UserModelTests(TestCase):
    def test_auth_user_model_points_to_accounts_user_with_default_flags(
        self,
    ) -> None:
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIs(get_user_model(), User)
        user = User.objects.create_user(
            "u_role_default",
            "default-role@example.com",
            gen_test_credential(),
            display_name="普通读者",
        )
        self.assertFalse(user.is_comment_admin)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_user_admin_exposes_display_name_and_locks_privileged_fields_for_staff(
        self,
    ) -> None:
        model_admin = admin.site._registry[User]
        self.assertIsInstance(model_admin, AccountUserAdmin)
        self.assertIn("display_name", model_admin.list_display)
        self.assertIn("is_comment_admin", model_admin.list_display)

        rf = RequestFactory()
        staff_user = User.objects.create_user(
            "u_staff_ro",
            "staff-ro@example.com",
            gen_test_credential(),
            display_name="只读管理",
            is_staff=True,
            is_comment_admin=True,
        )
        req = rf.get("/admin/accounts/user/")
        req.user = staff_user
        ro_fields = model_admin.get_readonly_fields(req, staff_user)
        self.assertIn("is_comment_admin", ro_fields)
        self.assertIn("is_staff", ro_fields)
        self.assertIn("is_superuser", ro_fields)

    def test_create_user_separates_display_name_from_email_and_hashes_password(
        self,
    ) -> None:
        pw_a = gen_test_credential()
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
            gen_test_credential(),
            display_name="   ",
        )
        self.assertEqual(str(user), "reader01")
        self.assertNotIn("hidden-address@example.com", str(user))

    def test_str_never_exposes_username_containing_at_sign(self) -> None:
        saved_user = User.objects.create_user(
            "login-alias@example.com",
            "login-alias@example.com",
            gen_test_credential(),
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
        self.assertEqual(unsaved_user.public_display_name, "用户")
        self.assertEqual(user_display(unsaved_user), "用户")
        self.assertEqual(
            saved_user.public_display_name, f"用户 #{saved_user.pk}"
        )
        self.assertEqual(user_display(saved_user), f"用户 #{saved_user.pk}")
        nfkc_unsaved = User(username="u_nfkc", display_name="  ＡＢＣ  ")
        self.assertEqual(nfkc_unsaved.public_display_name, "ABC")
        self.assertEqual(user_display(nfkc_unsaved), "ABC")

    def test_display_name_validation_enforces_post_nfkc_length_and_blocks_urls(
        self,
    ) -> None:
        valid_user = User(
            username="valid64",
            email="v64@example.com",
            display_name="昵" * 64,
        )
        valid_user.set_password(gen_test_credential())
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
                candidate.set_password(gen_test_credential())
                with self.assertRaises(ValidationError) as ctx:
                    candidate.full_clean()
                self.assertIn("display_name", ctx.exception.message_dict)

    def test_display_name_allows_duplicates_while_non_empty_email_is_unique_ci(
        self,
    ) -> None:
        first = User.objects.create_user(
            "u_first",
            "unique-reader@example.com",
            gen_test_credential(),
            display_name="同名旅人",
        )
        second = User.objects.create_user(
            "u_second",
            "second-reader@example.com",
            gen_test_credential(),
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

        blank_a = User.objects.create_user("tech_a", "", gen_test_credential())
        blank_b = User.objects.create_user("tech_b", "", gen_test_credential())
        self.assertEqual(blank_a.email, "")
        self.assertEqual(blank_b.email, "")

    def test_migration_0002_normalizes_legacy_rows_and_raises_on_collision(
        self,
    ) -> None:
        migration_mod = importlib.import_module(
            "accounts.migrations.0002_user_accounts_user_unique_non_empty_email_ci"
        )
        first = User.objects.create_user(
            "legacy_one", "first@example.com", gen_test_credential(), display_name="甲"
        )
        second = User.objects.create_user(
            "legacy_two", "second@example.com", gen_test_credential(), display_name="乙"
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

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.email, "collide@example.com")
        self.assertEqual(second.email, "  collide@example.com ")
