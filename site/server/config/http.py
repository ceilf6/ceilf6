"""Shared HTTP response helpers for dynamic JSON and empty endpoints."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.cache import patch_vary_headers
from django.views.csrf import csrf_failure as django_csrf_failure

from config.middleware import NO_STORE_CACHE_CONTROL


def json_no_store(payload: dict[str, Any], *, status: int = 200) -> JsonResponse:
    """Return a JsonResponse with private no-store headers and `Vary: Cookie`."""
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = NO_STORE_CACHE_CONTROL
    patch_vary_headers(response, ("Cookie",))
    return response


def empty_no_store(*, status: int = 204) -> HttpResponse:
    """Return an empty HttpResponse with private no-store headers and `Vary: Cookie`."""
    response = HttpResponse(status=status)
    response["Cache-Control"] = NO_STORE_CACHE_CONTROL
    patch_vary_headers(response, ("Cookie",))
    return response


def csrf_failure_view(
    request: HttpRequest, reason: str = ""
) -> HttpResponse:
    """Return JSON 403 for `/api/*` CSRF failures and HTML for page routes."""
    if request.path_info == "/api" or request.path_info.startswith("/api/"):
        return json_no_store(
            {
                "code": "csrf_failed",
                "message": "CSRF 安全校验未通过，请刷新页面后重试。",
            },
            status=403,
        )
    return django_csrf_failure(request, reason=reason)
