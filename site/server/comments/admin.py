"""Admin registration for strictly read/delete-only Comment moderation."""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest

from comments.models import GUEST_DISPLAY_NAME, Comment
from comments.permissions import can_delete_comment

BODY_PREVIEW_MAX_LENGTH = 60


def _is_active_comment_moderator(user: object) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (
            getattr(user, "is_comment_admin", False)
            or getattr(user, "is_superuser", False)
        )
    )


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "note_slug",
        "author_display",
        "body_preview",
        "created_at",
    )
    list_filter = ("note_slug", "created_at")
    list_select_related = ("author",)
    search_fields = ("note_slug", "body", "author__display_name", "author__email")
    readonly_fields = ("note_slug", "author", "body", "created_at")

    @admin.display(description="评论作者", ordering="author__display_name")
    def author_display(self, obj: Comment) -> str:
        if obj.author_id and obj.author:
            return obj.author.public_display_name
        return GUEST_DISPLAY_NAME

    @admin.display(description="正文摘要")
    def body_preview(self, obj: Comment) -> str:
        single_line = " ".join((obj.body or "").split())
        if len(single_line) <= BODY_PREVIEW_MAX_LENGTH:
            return single_line
        return f"{single_line[:BODY_PREVIEW_MAX_LENGTH]}…"

    def has_module_permission(self, request: HttpRequest) -> bool:
        if _is_active_comment_moderator(request.user):
            return True
        return super().has_module_permission(request)

    def has_view_permission(
        self, request: HttpRequest, obj: Comment | None = None
    ) -> bool:
        if _is_active_comment_moderator(request.user):
            return True
        return super().has_view_permission(request, obj)

    def has_delete_permission(
        self, request: HttpRequest, obj: Comment | None = None
    ) -> bool:
        if obj is not None:
            return can_delete_comment(request.user, obj)
        return _is_active_comment_moderator(request.user)

    def has_add_permission(self, request: HttpRequest) -> bool:
        del request
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: Comment | None = None
    ) -> bool:
        del request, obj
        return False
