"""Custom user model separating public display_name from private login email."""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Site user with public nickname isolated from private login email."""

    display_name = models.CharField(
        "公开昵称",
        max_length=64,
        blank=True,
        default="",
        help_text="对外展示的公开昵称，与私有登录邮箱分离。",
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self) -> str:
        cleaned_display_name = (self.display_name or "").strip()
        if cleaned_display_name:
            return cleaned_display_name
        username = (self.get_username() or "").strip()
        if username and "@" not in username:
            return username
        if self.pk is not None:
            return f"user-{self.pk}"
        return "user"
