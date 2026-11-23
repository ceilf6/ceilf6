"""Test runner anchored to site/server regardless of working directory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.conf import settings
from django.test.runner import DiscoverRunner


class ServerDiscoverRunner(DiscoverRunner):
    """Ensure `manage.py test` finds all server tests from any cwd."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.top_level is None:
            self.top_level = str(settings.BASE_DIR)

    def build_suite(
        self, test_labels: Sequence[str] | None = None, **kwargs: Any
    ) -> Any:
        effective_labels = (
            list(test_labels) if test_labels else [str(settings.BASE_DIR)]
        )
        return super().build_suite(effective_labels, **kwargs)
