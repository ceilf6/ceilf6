"""Template context processor splitting /accounts/ feedback into toasts and inline alerts."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest
from django.utils.functional import SimpleLazyObject


def _resolve_account_feedback(
    request: HttpRequest,
) -> tuple[list[str], list[str]]:
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

    return account_toasts, account_alerts


def account_feedback(request: HttpRequest) -> dict[str, object]:
    """Lazily filter and split messages for /accounts/ HTML pages without premature consumption."""
    if not request.path.startswith("/accounts/"):
        return {}

    resolved: tuple[list[str], list[str]] | None = None

    def _ensure_resolved() -> tuple[list[str], list[str]]:
        nonlocal resolved
        if resolved is None:
            resolved = _resolve_account_feedback(request)
        return resolved

    return {
        "account_toasts": SimpleLazyObject(lambda: _ensure_resolved()[0]),
        "account_alerts": SimpleLazyObject(lambda: _ensure_resolved()[1]),
    }
