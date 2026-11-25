"""Session identity (/api/me/) and authenticated account settings views."""

from __future__ import annotations

from typing import cast
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.adapter import is_safe_internal_redirect_url
from accounts.forms import ProfileSettingsForm
from accounts.models import User
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


def _resolve_safe_next_url(request: HttpRequest) -> str:
    """Resolve and validate the internal return target from POST or GET `next`."""
    if request.method == "POST":
        raw_next = (
            request.POST.get("next")
            if "next" in request.POST
            else request.GET.get("next")
        )
    else:
        raw_next = request.GET.get("next")

    if is_safe_internal_redirect_url(raw_next):
        assert isinstance(raw_next, str)
        return raw_next
    return "/"


@require_http_methods(["GET", "POST"])
@login_required
def settings_view(request: HttpRequest) -> HttpResponse:
    """Render and save authenticated public profile settings via PRG."""
    user = cast(User, request.user)
    safe_next = _resolve_safe_next_url(request)

    if request.method == "POST":
        form = ProfileSettingsForm(request.POST)
        if form.is_valid():
            cleaned_display_name = form.cleaned_data["display_name"]
            if cleaned_display_name != user.display_name:
                user.display_name = cleaned_display_name
                user.save(update_fields=["display_name"])

            query = urlencode({"next": safe_next, "saved": "1"})
            return HttpResponseRedirect(
                f"{reverse('account_settings')}?{query}"
            )
        saved = False
    else:
        form = ProfileSettingsForm(
            initial={"display_name": user.public_display_name}
        )
        saved = request.GET.get("saved") == "1"

    return render(
        request,
        "account/settings.html",
        {
            "form": form,
            "next_url": safe_next,
            "saved": saved,
        },
    )
