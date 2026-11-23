"""Note slug manifest loading and synchronization helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_slug

from comments.models import MAX_NOTE_SLUG_LENGTH

NOTE_SLUGS_MANIFEST_PATH = Path(__file__).resolve().with_name("note_slugs.json")
DEFAULT_CONTENT_NOTES_DIR = (
    Path(__file__).resolve().parents[2] / "content" / "notes"
)


def slug_from_note_path(path: str | Path) -> str:
    """Derive note slug identically to `slugFromPath` in `site/src/data/notes.ts`."""
    filename = str(path).replace("\\", "/").split("/")[-1]
    return filename[:-3] if filename.endswith(".md") else filename


def discover_content_note_slugs(
    notes_dir: Path = DEFAULT_CONTENT_NOTES_DIR,
) -> list[str]:
    """Scan `content/notes/*.md` and return sorted note slugs."""
    if not notes_dir.is_dir():
        raise FileNotFoundError(f"Notes content directory not found: {notes_dir}")
    slugs = [
        slug_from_note_path(entry.name)
        for entry in notes_dir.iterdir()
        if entry.is_file()
        and not entry.name.startswith(".")
        and entry.name.endswith(".md")
    ]
    return sorted(slugs)


def _validate_manifest_slug_entry(item: object, manifest_path: Path) -> str:
    if (
        not isinstance(item, str)
        or not item.strip()
        or item != item.strip()
        or len(item) > MAX_NOTE_SLUG_LENGTH
    ):
        raise ImproperlyConfigured(
            f"Invalid or overlong note slug entry in {manifest_path}: {item!r}"
        )
    try:
        validate_slug(item)
    except ValidationError as exc:
        raise ImproperlyConfigured(
            f"Note slug entry failed SlugField validation in {manifest_path}: {item!r}"
        ) from exc
    return item


@lru_cache(maxsize=4)
def load_manifest_note_slugs(
    manifest_path: Path = NOTE_SLUGS_MANIFEST_PATH,
) -> frozenset[str]:
    """Read committed `note_slugs.json` without touching `site/content/notes/`."""
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ImproperlyConfigured(
            f"Failed to load note slug manifest from {manifest_path}: {exc}"
        ) from exc

    if not isinstance(parsed, list):
        raise ImproperlyConfigured(
            f"Note slug manifest must be a JSON array of slug strings: {manifest_path}"
        )
    validated = [
        _validate_manifest_slug_entry(entry, manifest_path) for entry in parsed
    ]
    return frozenset(validated)


def get_valid_note_slugs() -> frozenset[str]:
    """Return active valid note slugs (honoring `@override_settings(VALID_NOTE_SLUGS=...)`)."""
    override = getattr(settings, "VALID_NOTE_SLUGS", None)
    if override is not None:
        return frozenset(str(slug) for slug in override)
    return load_manifest_note_slugs()
