"""Admin registration for the custom User model."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.http import HttpRequest

from accounts.models import User


@admin.register(User)
class AccountUserAdmin(UserAdmin):
    list_display = (
        "username",
        "display_name",
        "email",
        "is_comment_admin",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_comment_admin", *UserAdmin.list_filter)
    search_fields = ("username", "display_name", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("公开资料与站主角色", {"fields": ("display_name", "is_comment_admin")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("公开资料", {"fields": ("display_name",)}),
    )

    def get_readonly_fields(
        self, request: HttpRequest, obj: User | None = None
    ) -> tuple[str, ...]:
        base = tuple(super().get_readonly_fields(request, obj))
        if request.user.is_superuser:
            return base
        restricted = (
            "is_comment_admin",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )
        return tuple(dict.fromkeys((*base, *restricted)))
