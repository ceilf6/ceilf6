"""Shared HTTP response helpers for dynamic JSON endpoints."""

from __future__ import annotations

from typing import Any

from django.http import JsonResponse
from django.utils.cache import patch_vary_headers

from config.middleware import NO_STORE_CACHE_CONTROL


def json_no_store(payload: dict[str, Any], *, status: int = 200) -> JsonResponse:
    """Return a JsonResponse with private no-store headers and `Vary: Cookie`."""
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = NO_STORE_CACHE_CONTROL
    patch_vary_headers(response, ("Cookie",))
    return response
