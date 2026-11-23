"""Session identity and CSRF bootstrap endpoint (/api/me/)."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt

from config.http import json_no_store

ALLOWED_ME_METHODS = ("GET", "HEAD")


@csrf_exempt
def me_view(request: HttpRequest) -> JsonResponse:
    """Return current session user (never exposing email) and initialize CSRF token."""
    if request.method not in ALLOWED_ME_METHODS:
        response = json_no_store(
            {
                "code": "method_not_allowed",
                "message": "Method not allowed.",
            },
            status=405,
        )
        response["Allow"] = ", ".join(ALLOWED_ME_METHODS)
        return response

    csrf_token = get_token(request)
    guest_comments_allowed = bool(settings.ALLOW_GUEST_COMMENTS)
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return json_no_store(
            {
                "user": None,
                "csrfToken": csrf_token,
                "guestCommentsAllowed": guest_comments_allowed,
            },
            status=200,
        )

    is_comment_admin = bool(
        getattr(user, "is_comment_admin", False) or user.is_superuser
    )
    return json_no_store(
        {
            "user": {
                "id": user.pk,
                "displayName": user.public_display_name,
                "isCommentAdmin": is_comment_admin,
            },
            "csrfToken": csrf_token,
            "guestCommentsAllowed": guest_comments_allowed,
        },
        status=200,
    )
