"""Custom Django AdminSite consolidating login into /accounts/login/ with 403 for non-staff."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.apps import AdminConfig
from django.http import HttpRequest, HttpResponse, HttpResponseBase, HttpResponseRedirect
from django.shortcuts import resolve_url
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache


class UnifiedLoginAdminSite(admin.AdminSite):
    """AdminSite delegating authentication exclusively to allauth /accounts/login/."""

    @method_decorator(never_cache)
    def login(
        self,
        request: HttpRequest,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        del extra_context
        from allauth.account.decorators import secure_admin_login
        from allauth.account.utils import get_next_redirect_url

        def _authenticated_staff_entry(req: HttpRequest) -> HttpResponse:
            admin_login_path = reverse("admin:login", current_app=self.name)
            candidate_next = get_next_redirect_url(req)
            if (
                candidate_next
                and urlsplit(candidate_next).path != admin_login_path
            ):
                target = candidate_next
            else:
                target = reverse("admin:index", current_app=self.name)
            return HttpResponseRedirect(target)

        return secure_admin_login(_authenticated_staff_entry)(request)

    def admin_view(
        self,
        view: Callable[..., HttpResponseBase],
        cacheable: bool = False,
    ) -> Callable[..., HttpResponseBase]:
        wrapped_view = super().admin_view(view, cacheable=cacheable)

        @wraps(view)
        def inner(
            request: HttpRequest, *args: Any, **kwargs: Any
        ) -> HttpResponseBase:
            if not self.has_permission(request):
                if (
                    not request.user.is_authenticated
                    and request.path
                    == reverse("admin:logout", current_app=self.name)
                ):
                    index_url = reverse("admin:index", current_app=self.name)
                    query = urlencode({"next": index_url})
                    return HttpResponseRedirect(
                        f"{resolve_url(settings.LOGIN_URL)}?{query}"
                    )
                return self.login(request)
            return wrapped_view(request, *args, **kwargs)

        if not cacheable:
            inner = never_cache(inner)
        return inner


class UnifiedAdminConfig(AdminConfig):
    """Register UnifiedLoginAdminSite as the default admin.site."""

    default_site = "config.admin_site.UnifiedLoginAdminSite"
