"""Session identity and CSRF bootstrap endpoint (/api/me/)."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt

from config.middleware import NO_STORE_CACHE_CONTROL

ALLOWED_ME_METHODS = ("GET", "HEAD")


def _json_no_store(payload: dict[str, Any], *, status: int) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = NO_STORE_CACHE_CONTROL
    return response


@csrf_exempt
def me_view(request: HttpRequest) -> JsonResponse:
    """Return current session user (never exposing email) and initialize CSRF token."""
    if request.method not in ALLOWED_ME_METHODS:
        response = _json_no_store(
            {
                "code": "method_not_allowed",
                "message": "Method not allowed.",
            },
            status=405,
        )
        response["Allow"] = ", ".join(ALLOWED_ME_METHODS)
        return response

    csrf_token = get_token(request)
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return _json_no_store(
            {
                "user": None,
                "csrfToken": csrf_token,
            },
            status=200,
        )

    is_comment_admin = bool(
        getattr(user, "is_comment_admin", False) or user.is_superuser
    )
    return _json_no_store(
        {
            "user": {
                "id": user.pk,
                "displayName": str(user),
                "isCommentAdmin": is_comment_admin,
            },
            "csrfToken": csrf_token,
        },
        status=200,
    )
