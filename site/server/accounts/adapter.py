"""Custom django-allauth adapter isolating opaque usernames from private emails."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from allauth.account.adapter import DefaultAccountAdapter
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.http import HttpRequest

from accounts.models import normalize_display_name

if TYPE_CHECKING:
    from django.forms import BaseForm


def generate_opaque_username() -> str:
    """Generate a collision-free non-PII internal username (e.g. u_9f8a7b6c5d4e3f2a)."""
    user_model = get_user_model()
    while True:
        candidate = f"u_{uuid.uuid4().hex[:16]}"
        if not user_model.objects.filter(username=candidate).exists():
            return candidate


def user_display(user: AbstractBaseUser) -> str:
    """Return safe public label for templates without exposing private email."""
    return str(user)


class AccountAdapter(DefaultAccountAdapter):
    """Adapter enforcing lowercase emails, opaque usernames, and public nicknames."""

    error_messages = {
        **DefaultAccountAdapter.error_messages,
        "account_inactive": "当前账号尚未激活或已被停用。",
        "email_password_mismatch": "邮箱或密码不正确。",
        "email_taken": "该邮箱已注册账号。",
        "invalid_login": "邮箱或密码不正确。",
        "invalid_or_expired_key": "验证链接无效或已过期。",
        "invalid_password_reset": "密码重置链接无效或已过期。",
        "rate_limited": "操作过于频繁，请稍后再试。",
        "too_many_login_attempts": "登录尝试次数过多，请稍后再试。",
        "unverified_primary_email": "请先完成邮箱验证后再登录。",
    }

    def clean_email(self, email: str) -> str:
        normalized = (email or "").strip().lower()
        return super().clean_email(normalized)

    def populate_username(
        self, request: HttpRequest, user: AbstractBaseUser
    ) -> None:
        current = (getattr(user, "username", "") or "").strip()
        if current and "@" not in current:
            return
        setattr(user, "username", generate_opaque_username())

    def save_user(
        self,
        request: HttpRequest,
        user: AbstractBaseUser,
        form: BaseForm,
        commit: bool = True,
    ) -> AbstractBaseUser:
        saved_user = super().save_user(request, user, form, commit=False)
        display_name = normalize_display_name(
            form.cleaned_data.get("display_name")
        )
        setattr(saved_user, "display_name", display_name)
        if commit:
            saved_user.save()
        return saved_user
