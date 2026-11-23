"""Unit tests for the custom accounts.User model and privacy invariants."""

from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User


def _make_credential() -> str:
    return secrets.token_urlsafe(24)


class UserModelTests(TestCase):
    def test_auth_user_model_points_to_accounts_user(self) -> None:
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIs(get_user_model(), User)

    def test_create_user_separates_display_name_from_email_and_hashes_password(
        self,
    ) -> None:
        raw_cred = _make_credential()
        user = User.objects.create_user(
            "linus",
            "private-login@example.com",
            raw_cred,
            display_name="  清风  ",
        )
        self.assertEqual(user.email, "private-login@example.com")
        self.assertEqual(str(user), "清风")
        self.assertNotIn("private-login@example.com", str(user))
        self.assertTrue(user.check_password(raw_cred))
        self.assertNotEqual(user.password, raw_cred)

    def test_str_falls_back_to_non_email_username_when_display_name_blank(
        self,
    ) -> None:
        user = User.objects.create_user(
            "reader01",
            "hidden-address@example.com",
            _make_credential(),
            display_name="   ",
        )
        self.assertEqual(str(user), "reader01")
        self.assertNotIn("hidden-address@example.com", str(user))

    def test_str_never_exposes_username_containing_at_sign(self) -> None:
        saved_user = User.objects.create_user(
            "login-alias@example.com",
            "login-alias@example.com",
            _make_credential(),
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

    def test_display_name_max_length_is_64(self) -> None:
        valid_user = User(
            username="valid64",
            email="v64@example.com",
            display_name="昵" * 64,
        )
        valid_user.set_password(_make_credential())
        valid_user.full_clean()

        too_long_user = User(
            username="invalid65",
            email="v65@example.com",
            display_name="昵" * 65,
        )
        too_long_user.set_password(_make_credential())
        with self.assertRaises(ValidationError) as ctx:
            too_long_user.full_clean()
        self.assertIn("display_name", ctx.exception.message_dict)
