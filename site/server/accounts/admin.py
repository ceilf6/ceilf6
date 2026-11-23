"""Admin registration for the custom User model."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class AccountUserAdmin(UserAdmin):
    list_display = (
        "username",
        "display_name",
        "email",
        "is_staff",
        "is_active",
    )
    search_fields = ("username", "display_name", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("公开资料", {"fields": ("display_name",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("公开资料", {"fields": ("display_name",)}),
    )
