"""Comment model supporting both anonymous guests and verified members."""

from __future__ import annotations

from collections.abc import Collection

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Chr, Length, Replace, StrIndex, Trim
from django.db.models.lookups import Exact, GreaterThanOrEqual, LessThanOrEqual

MAX_COMMENT_BODY_LENGTH = 1000
MAX_NOTE_SLUG_LENGTH = 120
GUEST_DISPLAY_NAME = "未登录用户"


def _trimmed_body_expression() -> Trim:
    """Fold ASCII CR/LF/TAB into spaces before SQLite TRIM as DB-level defense-in-depth.

    Note: SQLite's single-argument TRIM() only strips ASCII spaces (0x20), whereas
    Python's `str.strip()` in `Comment.clean_fields()` strips all Unicode whitespace
    (including full-width ideographic space `\u3000`). Both layers enforce non-blank text.
    """
    return Trim(
        Replace(
            Replace(
                Replace("body", Chr(13), Value(" ")),
                Chr(10),
                Value(" "),
            ),
            Chr(9),
            Value(" "),
        )
    )


class Comment(models.Model):
    """Public comment bound to a static note slug."""

    note_slug = models.SlugField(
        "札记标识",
        max_length=MAX_NOTE_SLUG_LENGTH,
        db_index=False,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="评论作者",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="comments",
    )
    body = models.TextField(
        "评论正文",
        max_length=MAX_COMMENT_BODY_LENGTH,
    )
    created_at = models.DateTimeField(
        "创建时间",
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "评论"
        verbose_name_plural = "评论"
        ordering = ("-id",)
        indexes = [
            models.Index(
                fields=["note_slug", "-id"],
                name="comments_note_slug_id_desc_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~Q(note_slug="")
                    & Exact(StrIndex("note_slug", Chr(0)), 0)
                    & Exact(StrIndex("body", Chr(0)), 0)
                    & GreaterThanOrEqual(Length(_trimmed_body_expression()), 1)
                    & LessThanOrEqual(Length("body"), MAX_COMMENT_BODY_LENGTH)
                ),
                name="comments_body_non_blank_and_max_length",
            ),
        ]

    def clean_fields(self, exclude: Collection[str] | None = None) -> None:
        excluded = set(exclude or ())
        errors: dict[str, list[ValidationError | str]] = {}
        try:
            super().clean_fields(exclude=excluded)
        except ValidationError as exc:
            errors = exc.update_error_dict(errors)

        if "note_slug" not in excluded:
            raw_slug = self.note_slug if isinstance(self.note_slug, str) else ""
            if "note_slug" not in errors and (
                not raw_slug or not raw_slug.strip() or "\x00" in raw_slug
            ):
                errors.setdefault("note_slug", []).append(
                    "札记标识不能为空或包含非法控制字符。"
                )

        # Python str.strip() rejects all Unicode whitespace (including \u3000),
        # complementing SQLite's ASCII whitespace CheckConstraint at the DB layer.
        if "body" not in excluded:
            raw_body = self.body if isinstance(self.body, str) else ""
            if "\x00" in raw_body:
                errors.setdefault("body", []).append(
                    "评论正文不能包含空字符。"
                )
            elif len(raw_body.strip()) < 1:
                errors.setdefault("body", []).append(
                    "评论正文不能为空或仅包含空白字符。"
                )
            elif (
                "body" not in errors
                and len(raw_body) > MAX_COMMENT_BODY_LENGTH
            ):
                errors.setdefault("body", []).append(
                    f"评论正文长度不能超过 {MAX_COMMENT_BODY_LENGTH} 个字符。"
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        ident = self.pk if self.pk is not None else "new"
        return f"Comment #{ident} ({self.note_slug})"
