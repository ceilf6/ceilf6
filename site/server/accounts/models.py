"""Custom User model decoupling public nickname from private login email."""

from __future__ import annotations

import unicodedata
from typing import Any

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

MAX_DISPLAY_NAME_LENGTH = 64
FORBIDDEN_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
FORBIDDEN_LINK_SUBSTRINGS = ("://", "http:", "https:", "www.")


def normalize_display_name(raw: str | None) -> str:
    """Normalize public nickname with NFKC and trim surrounding whitespace."""
    return unicodedata.normalize("NFKC", raw or "").strip()


def validate_safe_display_name(value: str) -> None:
    """Reject overlong NFKC expansions, control/zero-width chars, and URLs."""
    normalized = normalize_display_name(value)
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise ValidationError(
            f"公开昵称长度不能超过 {MAX_DISPLAY_NAME_LENGTH} 个字符。"
        )
    for ch in normalized:
        if (
            ch in {"\r", "\n"}
            or unicodedata.category(ch) in FORBIDDEN_UNICODE_CATEGORIES
        ):
            raise ValidationError(
                "公开昵称不能包含换行符、控制字符或不可见格式字符。"
            )
    lowered = normalized.lower()
    if any(token in lowered for token in FORBIDDEN_LINK_SUBSTRINGS):
        raise ValidationError("公开昵称不能包含链接或网址。")


class User(AbstractUser):
    """Site user with public nickname isolated from private login email."""

    display_name = models.CharField(
        "公开昵称",
        max_length=MAX_DISPLAY_NAME_LENGTH,
        blank=True,
        default="",
        validators=[validate_safe_display_name],
        help_text="对外展示的公开昵称，与私有登录邮箱分离。",
    )
    is_comment_admin = models.BooleanField(
        "站主评论管理权限",
        default=False,
        help_text="标记该账号具备站主评论治理权限（由 grant_comment_admin 命令显式授予或撤销）。",
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "用户"
        verbose_name_plural = "用户"
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="accounts_user_unique_non_empty_email_ci",
            ),
        ]

    def _normalize_identity_fields(self) -> None:
        self.email = (self.email or "").strip().lower()
        self.display_name = normalize_display_name(self.display_name)

    def clean(self) -> None:
        self._normalize_identity_fields()
        super().clean()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self._normalize_identity_fields()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        cleaned_display_name = normalize_display_name(self.display_name)
        if cleaned_display_name:
            return cleaned_display_name
        username = (self.get_username() or "").strip()
        if username and "@" not in username:
            return username
        if self.pk is not None:
            return f"user-{self.pk}"
        return "user"
