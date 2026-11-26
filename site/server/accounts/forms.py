"""Public authentication forms with anti-bot honeypot and safe nickname handling."""

from __future__ import annotations

import logging
from typing import Any

from allauth.account.forms import LoginForm, ResetPasswordForm, SignupForm
from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms.utils import ErrorDict
from django.http import HttpRequest

from accounts.avatar import AVATAR_CHOICES
from accounts.models import (
    MAX_DISPLAY_NAME_LENGTH,
    User,
    normalize_display_name,
    validate_safe_display_name,
)

logger = logging.getLogger(__name__)

HONEYPOT_FIELD_NAME = "website"
HONEYPOT_ERROR_MESSAGE = "请求未通过安全校验，请重试。"


class HoneypotTextInput(forms.TextInput):
    """Off-screen text input that never echoes dirty values on form re-render."""

    def format_value(self, value: Any) -> None:
        del value
        return None


class HoneypotFormMixin(forms.Form):
    """Reject automated submissions that populate the off-screen honeypot field."""

    website = forms.CharField(
        label="个人主页（请留空）",
        required=False,
        strip=False,
        widget=HoneypotTextInput(
            attrs={
                "tabindex": "-1",
                "autocomplete": "off",
                "aria-hidden": "true",
            }
        ),
    )

    def _is_honeypot_triggered(self) -> bool:
        if not self.is_bound:
            return False
        raw_value = self.data.get(self.add_prefix(HONEYPOT_FIELD_NAME))
        return bool(raw_value)

    def full_clean(self) -> None:
        if self._is_honeypot_triggered():
            self._errors = ErrorDict()
            self.cleaned_data = {}
            self.add_error(HONEYPOT_FIELD_NAME, HONEYPOT_ERROR_MESSAGE)
            self.add_error(None, HONEYPOT_ERROR_MESSAGE)
            return
        super().full_clean()


class AccountLoginForm(HoneypotFormMixin, LoginForm):
    """Unified email+password login form protected by an off-screen honeypot."""


class AccountResetPasswordForm(HoneypotFormMixin, ResetPasswordForm):
    """Password reset request form protected by an off-screen honeypot."""

    field_order = ["email", HONEYPOT_FIELD_NAME]


def _build_display_name_field() -> forms.CharField:
    """Create the shared public nickname field used across signup and settings."""
    return forms.CharField(
        label="公开昵称",
        max_length=MAX_DISPLAY_NAME_LENGTH,
        required=True,
        strip=True,
        validators=[validate_safe_display_name],
        error_messages={
            "required": "请输入公开昵称（不能仅包含空白字符）。",
            "max_length": f"公开昵称长度不能超过 {MAX_DISPLAY_NAME_LENGTH} 个字符。",
        },
        widget=forms.TextInput(
            attrs={
                "placeholder": "对外展示的公开昵称（1–64 字符）",
                "autocomplete": "nickname",
                "maxlength": str(MAX_DISPLAY_NAME_LENGTH),
            }
        ),
    )


def _clean_display_name_value(form: forms.BaseForm) -> str:
    cleaned = normalize_display_name(form.cleaned_data.get("display_name"))
    if not cleaned:
        raise forms.ValidationError(
            form.fields["display_name"].error_messages["required"]
        )
    validate_safe_display_name(cleaned)
    return cleaned


class AccountSignupForm(HoneypotFormMixin, SignupForm):
    """Signup form requiring a safe public nickname isolated from private email."""

    display_name = _build_display_name_field()

    field_order = [
        "display_name",
        "email",
        "password1",
        "password2",
        HONEYPOT_FIELD_NAME,
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "email" in self.fields:
            self.fields["email"].label = "登录邮箱（仅用于登录与验证，不对外公开）"
            self.fields["email"].widget.attrs.update(
                {
                    "placeholder": "you@example.com",
                    "autocomplete": "email",
                }
            )
        if "password1" in self.fields:
            self.fields["password1"].label = "登录密码"
            self.fields["password1"].widget.attrs["placeholder"] = "请设置至少 8 位高强度密码"
        if "password2" in self.fields:
            self.fields["password2"].label = "确认密码"
            self.fields["password2"].widget.attrs["placeholder"] = "请再次输入登录密码"

    def clean_display_name(self) -> str:
        return _clean_display_name_value(self)

    def validate_unique_email(self, value: str) -> str:
        email = super().validate_unique_email(value)
        if (
            not self.account_already_exists
            and User.objects.filter(email__iexact=email).exists()
        ):
            self.account_already_exists = True
        return email

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        display_name = cleaned_data.get("display_name") or ""
        email = cleaned_data.get("email") or ""
        candidate_value = cleaned_data.get("password1")
        if candidate_value and display_name and "password1" not in self.errors:
            try:
                password_validation.validate_password(
                    candidate_value,
                    User(email=email, display_name=display_name),
                )
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned_data

    def try_save(self, request: HttpRequest) -> tuple[Any, Any]:
        if self.account_already_exists:
            return super().try_save(request)
        try:
            with transaction.atomic():
                return super().try_save(request)
        except IntegrityError:
            candidate_email = (self.cleaned_data.get("email") or "").strip()
            if not candidate_email or not User.objects.filter(
                email__iexact=candidate_email
            ).exists():
                raise
            logger.warning(
                "Concurrent signup IntegrityError resolved via enumeration-safe fallback for existing account."
            )
            self.account_already_exists = True
            return super().try_save(request)


class ProfileSettingsForm(forms.Form):
    """Authenticated account settings form for updating public nickname and avatar color."""

    display_name = _build_display_name_field()
    avatar_color = forms.ChoiceField(
        label="头像底色",
        choices=AVATAR_CHOICES,
        required=False,
        initial="",
        error_messages={
            "invalid_choice": "请选择预设的头像底色。",
        },
    )

    def __init__(
        self,
        *args: Any,
        current_public_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if isinstance(current_public_name, str) and current_public_name.strip():
            self.fields["display_name"].widget.attrs["placeholder"] = (
                f"当前显示为：{current_public_name.strip()}"
            )

    def clean_display_name(self) -> str:
        return _clean_display_name_value(self)
