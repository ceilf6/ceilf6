"""URL configuration for site/server."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import path

from config.views import health_check

urlpatterns = [
    path(settings.DJANGO_ADMIN_PATH, admin.site.urls),
    path("api/health/", health_check, name="api-health"),
]
