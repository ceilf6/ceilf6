"""URL configuration for site/server."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from accounts.views import (
    me_view,
    password_reset_done_redirect_view,
    settings_view,
)
from comments.views import delete_comment_view, note_comments_view
from config.views import health_check

urlpatterns = [
    path(settings.DJANGO_ADMIN_PATH, admin.site.urls),
    path("accounts/settings/", settings_view, name="account_settings"),
    path(
        "accounts/password/reset/key/done/",
        password_reset_done_redirect_view,
        name="account_reset_password_from_key_done_redirect",
    ),
    path("accounts/", include("allauth.account.urls")),
    path("api/health/", health_check, name="api-health"),
    path("api/me/", me_view, name="api-me"),
    path(
        "api/notes/<str:slug>/comments/",
        note_comments_view,
        name="api-note-comments",
    ),
    path(
        "api/comments/<str:comment_id>/delete/",
        delete_comment_view,
        name="api-comment-delete",
    ),
]
