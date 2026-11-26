"""Template context processor splitting /accounts/ feedback into toasts and inline alerts."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest


def account_feedback(request: HttpRequest) -> dict[str, list[str]]:
    """Filter and split messages for /accounts/ routes without consuming messages elsewhere."""
    if not request.path.startswith("/accounts/"):
        return {}

    account_toasts: list[str] = []
    account_alerts: list[str] = []

    for msg in messages.get_messages(request):
        text = str(msg)
        if not text or "@" in text:
            continue
        if msg.level_tag in ("success", "info"):
            account_toasts.append(text)
        elif msg.level_tag in ("warning", "error"):
            account_alerts.append(text)

    if request.method == "GET":
        url_name = getattr(request.resolver_match, "url_name", None)
        if url_name == "account_settings" and request.GET.get("saved") == "1":
            account_toasts.append("已保存")
        elif (
            url_name == "account_login"
            and request.GET.get("confirmed") == "1"
        ):
            account_toasts.append("邮箱已确认，请登录。")

    return {
        "account_toasts": account_toasts,
        "account_alerts": account_alerts,
    }
