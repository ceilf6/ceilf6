"""App configuration and startup system check for note comments."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.core.checks import CheckMessage, Error, register
from django.core.exceptions import ImproperlyConfigured


def check_note_slugs_manifest(
    app_configs: Sequence[AppConfig] | None,
    **kwargs: Any,
) -> list[CheckMessage]:
    """Verify `note_slugs.json` is loadable and non-empty during `manage.py check`."""
    del app_configs, kwargs
    from comments.slugs import load_manifest_note_slugs

    try:
        slugs = load_manifest_note_slugs()
    except ImproperlyConfigured as exc:
        return [
            Error(
                str(exc),
                hint="Run `node site/scripts/update-note-slugs.mjs` to regenerate `note_slugs.json`.",
                id="comments.E001",
            )
        ]
    if not slugs:
        return [
            Error(
                "Note slug manifest `comments/note_slugs.json` is empty.",
                hint="Ensure `site/content/notes/*.md` has notes and run `node site/scripts/update-note-slugs.mjs`.",
                id="comments.E002",
            )
        ]
    return []


class CommentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "comments"
    verbose_name = "札记评论"

    def ready(self) -> None:
        register(check_note_slugs_manifest)
