"""Account signup form collecting public display_name alongside email + password."""

from __future__ import annotations

from typing import Any

from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest

from accounts.models import (
    MAX_DISPLAY_NAME_LENGTH,
    User,
    normalize_display_name,
    validate_safe_display_name,
)


class AccountSignupForm(SignupForm):
    """Signup form requiring a safe public nickname isolated from private email."""

    display_name = forms.CharField(
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

    field_order = ["display_name", "email", "password1", "password2"]

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
        cleaned = normalize_display_name(self.cleaned_data.get("display_name"))
        if not cleaned:
            raise forms.ValidationError(
                self.fields["display_name"].error_messages["required"]
            )
        validate_safe_display_name(cleaned)
        return cleaned

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
        try:
            with transaction.atomic():
                return super().try_save(request)
        except IntegrityError:
            self.account_already_exists = True
            return super().try_save(request)
