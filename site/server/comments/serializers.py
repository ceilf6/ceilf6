"""JSON serialization helpers for public comment payloads (zero email/username leak)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.utils import timezone

from comments.models import GUEST_DISPLAY_NAME, Comment
from comments.permissions import can_delete_comment


def format_utc_iso(dt: datetime) -> str:
    """Format datetime as UTC ISO-8601 timestamp ending with `Z`."""
    if timezone.is_naive(dt):
        utc_dt = dt.replace(tzinfo=UTC)
    else:
        utc_dt = dt.astimezone(UTC)
    return utc_dt.isoformat().replace("+00:00", "Z")


def serialize_comment_author(comment: Comment) -> dict[str, Any]:
    """Serialize comment author while never exposing email or internal opaque username."""
    if comment.author_id is None:
        return {
            "kind": "guest",
            "id": None,
            "displayName": GUEST_DISPLAY_NAME,
        }

    author = comment.author
    assert author is not None
    return {
        "kind": "member",
        "id": author.pk,
        "displayName": author.public_display_name,
    }


def serialize_comment(comment: Comment, *, viewer: Any) -> dict[str, Any]:
    """Serialize a single Comment row with viewer-specific `canDelete` flag."""
    return {
        "id": comment.pk,
        "body": comment.body,
        "createdAt": format_utc_iso(comment.created_at),
        "canDelete": can_delete_comment(viewer, comment),
        "author": serialize_comment_author(comment),
    }
