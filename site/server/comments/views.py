"""Cursor-paginated read endpoint for note comments."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from comments.models import Comment
from comments.serializers import serialize_comment
from comments.slugs import get_valid_note_slugs
from config.http import json_no_store

ALLOWED_COMMENTS_METHODS = ("GET", "HEAD")
PAGE_SIZE = 20
MAX_SQLITE_INT64 = (1 << 63) - 1
MAX_SQLITE_INT64_DIGITS = 19


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


@csrf_exempt
def note_comments_view(request: HttpRequest, slug: str) -> JsonResponse:
    """List comments for a valid note slug in descending ID cursor pages."""
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
