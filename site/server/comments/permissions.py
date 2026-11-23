"""Centralized permission helpers for comment moderation and author deletion."""

from __future__ import annotations

from typing import Any

from comments.models import Comment


def can_delete_comment(user: Any, comment: Comment) -> bool:
    """Return True iff `user` may delete `comment`."""
    if user is None:
        return False
    if not getattr(user, "is_authenticated", False) or not getattr(
        user, "is_active", False
    ):
        return False
    if bool(
        getattr(user, "is_comment_admin", False)
        or getattr(user, "is_superuser", False)
    ):
        return True
    user_pk = getattr(user, "pk", None)
    return (
        user_pk is not None
        and comment.author_id is not None
        and comment.author_id == user_pk
    )
