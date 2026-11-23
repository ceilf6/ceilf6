"""HTTP middleware enforcing private no-store cache headers on dynamic routes."""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase
from django.utils.cache import patch_vary_headers

NO_STORE_CACHE_CONTROL = "private, no-store, no-cache, must-revalidate"


def is_dynamic_route(path_info: str) -> bool:
    """Return True for auth, API, and admin paths that must never be CDN-cached."""
    admin_prefix = f"/{settings.DJANGO_ADMIN_PATH.strip('/')}"
    for prefix in ("/accounts", "/api", admin_prefix):
        if path_info == prefix or path_info.startswith(f"{prefix}/"):
            return True
    return False


class DynamicRouteNoStoreMiddleware:
    """Ensure /accounts/*, /api/*, and admin responses bypass shared/CDN caches."""

    def __init__(
        self, get_response: Callable[[HttpRequest], HttpResponseBase]
    ) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        response = self.get_response(request)
        if is_dynamic_route(request.path_info):
            response["Cache-Control"] = NO_STORE_CACHE_CONTROL
            patch_vary_headers(response, ("Cookie",))
        return response
