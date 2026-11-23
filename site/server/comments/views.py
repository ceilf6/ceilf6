"""Cursor-paginated read, create, and delete endpoints for note comments."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.exceptions import RequestDataTooBig, ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse, RawPostDataException
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from comments.models import MAX_COMMENT_BODY_LENGTH, Comment
from comments.permissions import can_delete_comment
from comments.ratelimit import consume_comment_rate_limit
from comments.serializers import serialize_comment
from comments.slugs import get_valid_note_slugs
from config.http import empty_no_store, json_no_store

ALLOWED_COMMENTS_METHODS = ("GET", "HEAD", "POST")
PAGE_SIZE = 20
MAX_SQLITE_INT64 = (1 << 63) - 1
MAX_SQLITE_INT64_DIGITS = 19
MAX_COMMENT_REQUEST_BYTES = 16_384
ALLOWED_CREATE_KEYS = frozenset({"body", "expectedAuthorKind", "website"})
REQUIRED_CREATE_KEYS = frozenset({"body", "expectedAuthorKind"})
VALID_AUTHOR_KINDS = frozenset({"guest", "member"})
FORBIDDEN_BODY_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
ALLOWED_EMOJI_JOINERS = frozenset({"\u200d", "\ufe0e", "\ufe0f"})


def _parse_before_cursor(request: HttpRequest) -> tuple[int | None, bool]:
    """Return `(before_id, is_valid)` parsed from `?before=<id>`."""
    if "before" not in request.GET:
        return None, True

    raw_values = request.GET.getlist("before")
    if len(raw_values) != 1:
        return None, False

    raw = raw_values[0]
    if not raw or not raw.isascii() or not raw.isdigit():
        return None, False

    # Strip leading zeros and cap at 19 digits before int() so 4301+ digit inputs
    # never trigger Python's int_max_str_digits ValueError (500).
    normalized = raw.lstrip("0")
    if not normalized or len(normalized) > MAX_SQLITE_INT64_DIGITS:
        return None, False

    value = int(normalized)
    if value > MAX_SQLITE_INT64:
        return None, False
    return value, True


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"Unsupported JSON constant: {constant}")


def _parse_create_payload(
    request: HttpRequest,
) -> tuple[dict[str, Any] | None, str | None]:
    raw_length = str(request.META.get("CONTENT_LENGTH", "") or "").strip()
    if raw_length:
        try:
            parsed_len = int(raw_length)
        except ValueError:
            return None, "请求体长度头无效。"
        if parsed_len < 0 or parsed_len > MAX_COMMENT_REQUEST_BYTES:
            return None, "请求体过大，请精简内容后重试。"

    if (request.content_type or "").lower() != "application/json":
        return None, "请求格式必须为 application/json。"

    try:
        raw_body = request.body
    except (RequestDataTooBig, RawPostDataException):
        return None, "请求体过大或无法读取，请精简内容后重试。"

    if len(raw_body) > MAX_COMMENT_REQUEST_BYTES:
        return None, "请求体过大，请精简内容后重试。"

    try:
        decoded = raw_body.decode("utf-8")
        payload = json.loads(decoded, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None, "请求体 JSON 格式无效。"

    if not isinstance(payload, dict):
        return None, "请求体必须为 JSON 对象。"

    unknown_keys = set(payload.keys()) - ALLOWED_CREATE_KEYS
    if unknown_keys:
        return None, "请求包含未允许的字段。"

    if not REQUIRED_CREATE_KEYS.issubset(payload.keys()):
        return None, "请求缺少必填字段。"

    return payload, None


def _clean_comment_body(raw_body: Any) -> tuple[str, str | None]:
    if not isinstance(raw_body, str):
        return "", "评论内容格式无效。"

    normalized = raw_body.replace("\r\n", "\n").replace("\r", "\n")
    for ch in normalized:
        if ch in ("\n", "\t") or ch in ALLOWED_EMOJI_JOINERS:
            continue
        if ch == "\x00" or unicodedata.category(ch) in FORBIDDEN_BODY_CATEGORIES:
            return "", "评论内容包含不支持的控制字符或不可见字符。"

    cleaned = normalized.strip()
    visible = "".join(
        ch
        for ch in cleaned
        if not ch.isspace() and ch not in ALLOWED_EMOJI_JOINERS
    )
    if len(cleaned) < 1 or not visible:
        return "", "评论内容不能为空。"
    if len(cleaned) > MAX_COMMENT_BODY_LENGTH:
        return "", f"评论内容不能超过 {MAX_COMMENT_BODY_LENGTH} 个字符。"
    return cleaned, None


def _rate_limited_response(retry_after: int) -> JsonResponse:
    response = json_no_store(
        {
            "code": "rate_limited",
            "message": "评论提交过于频繁，请稍后再试。",
        },
        status=429,
    )
    response["Retry-After"] = str(retry_after)
    return response


def _list_note_comments_view(request: HttpRequest, slug: str) -> JsonResponse:
    if slug not in get_valid_note_slugs():
        return json_no_store(
            {
                "code": "note_not_found",
                "message": "未找到对应的札记。",
            },
            status=404,
        )

    before_id, cursor_ok = _parse_before_cursor(request)
    if not cursor_ok:
        return json_no_store(
            {
                "code": "invalid_cursor",
                "message": "分页游标参数无效。",
            },
            status=400,
        )

    queryset = (
        Comment.objects.filter(note_slug=slug)
        .select_related("author")
        .only(
            "id",
            "note_slug",
            "author_id",
            "body",
            "created_at",
            "author__id",
            "author__display_name",
        )
        .order_by("-pk")
    )
    if before_id is not None:
        queryset = queryset.filter(pk__lt=before_id)

    fetched = list(queryset[: PAGE_SIZE + 1])
    has_more = len(fetched) > PAGE_SIZE
    page_rows = fetched[:PAGE_SIZE]
    next_before = page_rows[-1].pk if has_more and page_rows else None

    viewer = request.user
    items = [serialize_comment(row, viewer=viewer) for row in page_rows]
    return json_no_store(
        {
            "items": items,
            "nextBefore": next_before,
        },
        status=200,
    )


@csrf_protect
def _create_note_comment_view(request: HttpRequest, slug: str) -> JsonResponse:
    if slug not in get_valid_note_slugs():
        return json_no_store(
            {
                "code": "note_not_found",
                "message": "未找到对应的札记。",
            },
            status=404,
        )

    payload, payload_error = _parse_create_payload(request)
    if payload is None:
        return json_no_store(
            {
                "code": "invalid_payload",
                "message": payload_error or "请求参数无效。",
            },
            status=400,
        )

    expected_kind = payload["expectedAuthorKind"]
    if not isinstance(expected_kind, str) or expected_kind not in VALID_AUTHOR_KINDS:
        return json_no_store(
            {
                "code": "invalid_payload",
                "message": "身份类型参数无效。",
            },
            status=400,
        )

    user = request.user
    if user.is_authenticated and user.is_active:
        has_verified_email = bool(
            user.is_superuser
            or EmailAddress.objects.filter(user=user, verified=True).exists()
        )
        if not has_verified_email:
            return json_no_store(
                {
                    "code": "email_not_verified",
                    "message": "请先完成邮箱验证后再发表评论。",
                },
                status=403,
            )
        actual_kind = "member"
    else:
        actual_kind = "guest"

    if expected_kind != actual_kind:
        return json_no_store(
            {
                "code": "author_state_changed",
                "actualAuthorKind": actual_kind,
                "message": "当前登录状态已变化，请确认后再提交评论。",
            },
            status=409,
        )

    if actual_kind == "guest" and not settings.ALLOW_GUEST_COMMENTS:
        return json_no_store(
            {
                "code": "guest_comments_disabled",
                "message": "当前已暂停未登录访客发表评论，请登录后发言。",
            },
            status=403,
        )

    rate_limit_user_id = user.pk if actual_kind == "member" else None
    if "website" in payload:
        raw_website = payload["website"]
        if not isinstance(raw_website, str):
            return json_no_store(
                {
                    "code": "invalid_payload",
                    "message": "校验字段格式无效。",
                },
                status=400,
            )
        if len(raw_website) > 0:
            allowed, retry_after = consume_comment_rate_limit(
                request, user_id=rate_limit_user_id
            )
            if not allowed:
                return _rate_limited_response(retry_after)
            return json_no_store(
                {
                    "code": "honeypot_triggered",
                    "message": "请求未通过安全校验。",
                },
                status=400,
            )

    cleaned_body, body_error = _clean_comment_body(payload["body"])
    if body_error is not None:
        return json_no_store(
            {
                "code": "invalid_body",
                "message": body_error,
            },
            status=400,
        )

    allowed, retry_after = consume_comment_rate_limit(
        request, user_id=rate_limit_user_id
    )
    if not allowed:
        return _rate_limited_response(retry_after)

    author = user if actual_kind == "member" else None
    comment = Comment(
        note_slug=slug,
        author=author,
        body=cleaned_body,
    )
    try:
        comment.full_clean()
        comment.save()
    except ValidationError:
        return json_no_store(
            {
                "code": "invalid_body",
                "message": "评论内容未通过校验。",
            },
            status=400,
        )

    return json_no_store(
        serialize_comment(comment, viewer=user),
        status=201,
    )


@csrf_exempt
def note_comments_view(request: HttpRequest, slug: str) -> JsonResponse:
    """Dispatch GET/HEAD comment list or CSRF-enforced POST comment creation."""
    if request.method not in ALLOWED_COMMENTS_METHODS:
        response = json_no_store(
            {
                "code": "method_not_allowed",
                "message": "Method not allowed.",
            },
            status=405,
        )
        response["Allow"] = ", ".join(ALLOWED_COMMENTS_METHODS)
        return response

    if request.method == "POST":
        return _create_note_comment_view(request, slug)
    return _list_note_comments_view(request, slug)


def _parse_positive_comment_id(raw_id: str) -> int | None:
    """Parse canonical positive SQLite int64 comment ID (rejecting leading zeros)."""
    if (
        not raw_id
        or not raw_id.isascii()
        or not raw_id.isdigit()
        or raw_id.startswith("0")
        or len(raw_id) > MAX_SQLITE_INT64_DIGITS
    ):
        return None

    value = int(raw_id)
    if value < 1 or value > MAX_SQLITE_INT64:
        return None
    return value


def _validate_delete_payload(request: HttpRequest) -> str | None:
    raw_length = str(request.META.get("CONTENT_LENGTH", "") or "").strip()
    if raw_length:
        try:
            parsed_len = int(raw_length)
        except ValueError:
            return "请求体长度头无效。"
        if parsed_len < 0 or parsed_len > MAX_COMMENT_REQUEST_BYTES:
            return "请求体过大，请精简内容后重试。"

    try:
        raw_body = request.body
    except (RequestDataTooBig, RawPostDataException):
        return "请求体过大或无法读取，请精简内容后重试。"

    if len(raw_body) > MAX_COMMENT_REQUEST_BYTES:
        return "请求体过大，请精简内容后重试。"

    if len(raw_body) == 0:
        return None

    if (request.content_type or "").lower() != "application/json":
        return "请求格式必须为 application/json。"

    try:
        decoded = raw_body.decode("utf-8")
        payload = json.loads(decoded, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return "请求体 JSON 格式无效。"

    if not isinstance(payload, dict):
        return "请求体必须为 JSON 对象。"

    if payload:
        return "请求包含未允许的字段。"

    return None


def _comment_not_found_response() -> JsonResponse:
    return json_no_store(
        {"code": "comment_not_found", "message": "未找到对应的评论。"},
        status=404,
    )


@csrf_protect
def _delete_comment_post_view(
    request: HttpRequest, comment_id: str
) -> HttpResponse:
    payload_error = _validate_delete_payload(request)
    if payload_error is not None:
        return json_no_store(
            {"code": "invalid_payload", "message": payload_error},
            status=400,
        )

    user = request.user
    if not user.is_authenticated or not user.is_active:
        return json_no_store(
            {
                "code": "authentication_required",
                "message": "请先登录后再删除评论。",
            },
            status=401,
        )

    has_verified_email = bool(
        user.is_superuser
        or EmailAddress.objects.filter(user=user, verified=True).exists()
    )
    if not has_verified_email:
        return json_no_store(
            {
                "code": "email_not_verified",
                "message": "请先完成邮箱验证后再操作评论。",
            },
            status=403,
        )

    parsed_id = _parse_positive_comment_id(comment_id)
    if parsed_id is None:
        return _comment_not_found_response()

    comment = (
        Comment.objects.only("id", "author_id").filter(pk=parsed_id).first()
    )
    if comment is None:
        return _comment_not_found_response()

    if not can_delete_comment(user, comment):
        return json_no_store(
            {"code": "permission_denied", "message": "无权删除该条评论。"},
            status=403,
        )

    deleted_count, _ = Comment.objects.filter(pk=comment.pk).delete()
    if deleted_count == 0:
        return _comment_not_found_response()

    return empty_no_store(status=204)


@csrf_exempt
def delete_comment_view(
    request: HttpRequest, comment_id: str
) -> HttpResponse:
    """Dispatch CSRF-enforced POST comment deletion; reject non-POST with 405 JSON."""
    if request.method != "POST":
        response = json_no_store(
            {"code": "method_not_allowed", "message": "Method not allowed."},
            status=405,
        )
        response["Allow"] = "POST"
        return response

    return _delete_comment_post_view(request, comment_id)
