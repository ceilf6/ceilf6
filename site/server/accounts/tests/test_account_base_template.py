"""Static template and CSS guardrails for templates/account/base.html."""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.DOTALL)


def _extract_css_block(css: str, header_regex: str) -> str | None:
    """Extract a balanced {...} CSS block without coupling to indentation."""
    match = re.search(header_regex + r"\s*\{", css)
    if not match:
        return None
    depth = 1
    idx = match.end()
    start = idx
    while idx < len(css) and depth > 0:
        if css[idx] == "{":
            depth += 1
        elif css[idx] == "}":
            depth -= 1
        idx += 1
    return css[start : idx - 1] if depth == 0 else None


class AccountBaseTemplateGuardrailTests(SimpleTestCase):
    """Guardrail checks on account/base.html CSS and markup invariants."""

    def _read_base_template(self) -> str:
        base_path = Path(settings.BASE_DIR) / "templates" / "account" / "base.html"
        return base_path.read_text(encoding="utf-8")

    def test_10_base_html_css_guardrails_for_centering_keyframes_and_reduced_motion(
        self,
    ) -> None:
        raw = self._read_base_template()
        style_match = STYLE_BLOCK_RE.search(raw)
        self.assertIsNotNone(style_match)
        assert style_match is not None
        css = style_match.group(0)

        # 1) .auth-toasts outer container never uses translateX(-50%) or animation
        toasts_rule_match = re.search(
            r"\.auth-toasts\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(toasts_rule_match)
        assert toasts_rule_match is not None
        toasts_decl = toasts_rule_match.group(1)
        self.assertNotIn("translateX(-50%)", toasts_decl)
        self.assertNotIn("animation", toasts_decl)
        self.assertIn("inset-inline: 0", toasts_decl)
        self.assertIn("width: fit-content", toasts_decl)
        self.assertIn("margin-inline: auto", toasts_decl)
        self.assertIn("pointer-events: none", toasts_decl)

        # 2) Keyframe animation attaches to inner .auth-toast, and neither auth-toast-* keyframe touches pointer-events
        keyframe_names = re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", css)
        self.assertGreaterEqual(len(keyframe_names), 2)
        toast_keyframes = [name for name in keyframe_names if name.startswith("auth-toast-")]
        self.assertEqual(len(toast_keyframes), 2)
        for kf_name in toast_keyframes:
            kf_block = _extract_css_block(css, rf"@keyframes\s+{re.escape(kf_name)}")
            self.assertIsNotNone(kf_block)
            assert kf_block is not None
            self.assertNotIn("pointer-events", kf_block)

        inner_toast_match = re.search(
            r"\.auth-toast\s*\{([^}]*)\}",
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(inner_toast_match)
        assert inner_toast_match is not None
        inner_toast_decl = inner_toast_match.group(1)
        self.assertIn("animation:", inner_toast_decl)
        self.assertTrue(
            any(name in inner_toast_decl for name in keyframe_names),
            f"Expected one of {keyframe_names} in .auth-toast rule",
        )

        # 3) Hover pause rule exists on .auth-toast:hover without stale :focus-within
        self.assertNotIn(":focus-within", css)
        hover_decl = _extract_css_block(css, r"\.auth-toast:hover")
        self.assertIsNotNone(hover_decl)
        assert hover_decl is not None
        self.assertIn("animation-play-state: paused", hover_decl)

        # 4) prefers-reduced-motion never uses animation: none and uses step-end keyframes
        reduced_block = _extract_css_block(
            css,
            r"@media\s*\(\s*prefers-reduced-motion:\s*reduce\s*\)",
        )
        self.assertIsNotNone(reduced_block)
        assert reduced_block is not None
        self.assertNotIn("animation: none", reduced_block)
        self.assertNotIn("animation:none", reduced_block)
        self.assertIn(".auth-toast", reduced_block)
        self.assertIn("step-end", reduced_block)
        self.assertIn("forwards", reduced_block)

    def test_18_base_template_has_no_toast_icon_close_or_script(self) -> None:
        raw = self._read_base_template()
        for forbidden in ("auth-toast-icon", "auth-toast-close", "✓", "关闭提示"):
            self.assertNotIn(forbidden, raw)

        toasts_block_match = re.search(
            r"\{%\s*block\s+toasts\s*%\}(.*?)\{%\s*endblock(?:\s+toasts)?\s*%\}",
            raw,
            re.DOTALL,
        )
        self.assertIsNotNone(toasts_block_match)
        assert toasts_block_match is not None
        self.assertNotIn("<script", toasts_block_match.group(1).lower())

    def test_19_auth_page_top_padding_clears_toast(self) -> None:
        raw = self._read_base_template()
        style_match = STYLE_BLOCK_RE.search(raw)
        self.assertIsNotNone(style_match)
        assert style_match is not None
        css = re.sub(r"/\*[\s\S]*?\*/", "", style_match.group(0))

        pre_media_css = css.split("@media", 1)[0]
        base_body_decl = _extract_css_block(pre_media_css, r"(?:^|\s)body")
        self.assertIsNotNone(base_body_decl)
        assert base_body_decl is not None
        self.assertRegex(base_body_decl, r"padding:\s*4\.25rem\b")

        media_480_block = _extract_css_block(
            css,
            r"@media\s*\(\s*max-width:\s*480px\s*\)",
        )
        self.assertIsNotNone(media_480_block)
        assert media_480_block is not None
        narrow_body_decl = _extract_css_block(media_480_block, r"(?:^|\s)body")
        self.assertIsNotNone(narrow_body_decl)
        assert narrow_body_decl is not None
        self.assertRegex(narrow_body_decl, r"padding:\s*4\.25rem\b")
