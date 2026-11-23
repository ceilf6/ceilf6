"""Core operational endpoints for site/server."""

from __future__ import annotations

import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from config.middleware import NO_STORE_CACHE_CONTROL

logger = logging.getLogger(__name__)

ALLOWED_HEALTH_METHODS = ("GET", "HEAD")


def _json_no_store(payload: dict[str, str], *, status: int) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = NO_STORE_CACHE_CONTROL
    return response


@csrf_exempt
def health_check(request: HttpRequest) -> HttpResponse:
    """Database liveness/readiness probe for local dev, Nginx, and smoke checks."""
    if request.method not in ALLOWED_HEALTH_METHODS:
        response = _json_no_store(
            {
                "code": "method_not_allowed",
                "message": "Method not allowed.",
            },
            status=405,
        )
        response["Allow"] = ", ".join(ALLOWED_HEALTH_METHODS)
        return response

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        if row != (1,):
            raise DatabaseError("Unexpected SELECT 1 result from database")
    except DatabaseError:
        logger.exception("Database connectivity probe failed")
        try:
            connection.close()
        except DatabaseError:
            logger.warning("Closing broken database connection failed")
        return _json_no_store({"status": "unavailable"}, status=503)

    return _json_no_store({"status": "ok"}, status=200)
