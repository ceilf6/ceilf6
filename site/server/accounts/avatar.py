"""Single source of truth for the 8-color dark avatar palette and initial extraction."""

from __future__ import annotations

import unicodedata
from typing import NamedTuple


class AvatarColorSpec(NamedTuple):
    """Preset dark avatar background color entry (WCAG AA >= 4.5:1 with #FFFFFF)."""

    key: str
    label: str
    hex_color: str


class AvatarSwatchOption(NamedTuple):
    """Renderable swatch option for the server-rendered account settings page."""

    key: str
    label: str
    hex_color: str
    is_auto: bool = False


AVATAR_PALETTE: tuple[AvatarColorSpec, ...] = (
    AvatarColorSpec("indigo", "靛蓝", "#4F46E5"),
    AvatarColorSpec("violet", "紫罗兰", "#7C3AED"),
    AvatarColorSpec("sky", "天蓝", "#0369A1"),
    AvatarColorSpec("teal", "青绿", "#0F766E"),
    AvatarColorSpec("emerald", "翠绿", "#047857"),
    AvatarColorSpec("amber", "琥珀", "#B45309"),
    AvatarColorSpec("rose", "玫红", "#BE123C"),
    AvatarColorSpec("slate", "石板灰", "#475569"),
)

AVATAR_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "自动"),
    *((spec.key, spec.label) for spec in AVATAR_PALETTE),
)

AVATAR_PALETTE_BY_KEY: dict[str, str] = {
    spec.key: spec.hex_color for spec in AVATAR_PALETTE
}


def resolve_avatar_color(
    user_id: int | None, avatar_color: str | None
) -> str:
    """Resolve `#RRGGBB` avatar background from explicit key or deterministic `user_id % 8`."""
    if avatar_color and avatar_color in AVATAR_PALETTE_BY_KEY:
        return AVATAR_PALETTE_BY_KEY[avatar_color]
    index = (user_id or 0) % len(AVATAR_PALETTE)
    return AVATAR_PALETTE[index].hex_color


def build_avatar_swatch_options(
    user_id: int | None,
) -> tuple[AvatarSwatchOption, ...]:
    """Return ('自动' + 8 preset colors) swatch metadata for settings template rendering."""
    auto_hex = resolve_avatar_color(user_id, "")
    return (
        AvatarSwatchOption("", "自动", auto_hex, True),
        *(
            AvatarSwatchOption(spec.key, spec.label, spec.hex_color, False)
            for spec in AVATAR_PALETTE
        ),
    )


def _is_regional_indicator(ch: str) -> bool:
    cp = ord(ch)
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_grapheme_extender(ch: str) -> bool:
    cp = ord(ch)
    if cp in (0xFE0E, 0xFE0F):
        return True
    if 0x1F3FB <= cp <= 0x1F3FF:
        return True
    return unicodedata.category(ch) in ("Mn", "Me", "Mc")


def extract_avatar_initial(name: str) -> str:
    """Extract the first grapheme cluster from `name` and convert to uppercase."""
    trimmed = (name or "").strip()
    if not trimmed:
        return "?"

    n = len(trimmed)
    cluster_chars = [trimmed[0]]
    i = 1

    if (
        _is_regional_indicator(trimmed[0])
        and i < n
        and _is_regional_indicator(trimmed[i])
    ):
        cluster_chars.append(trimmed[i])
        i += 1

    while i < n:
        ch = trimmed[i]
        if ch == "\u200d":
            cluster_chars.append(ch)
            i += 1
            if i < n:
                cluster_chars.append(trimmed[i])
                i += 1
            continue
        if _is_grapheme_extender(ch):
            cluster_chars.append(ch)
            i += 1
            continue
        break

    return "".join(cluster_chars).upper()
