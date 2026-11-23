"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from app.config import Settings


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Return a factory that builds Settings with sensible test defaults."""

    def _make(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "telegram_bot_token": "test-token",
            "allowed_user_id": None,
            "data_dir": Path("data"),
            "mp3_bitrate": "320k",
            "max_upload_mb": 50,
            "output_filename_template": "{artist} - {title}",
            "max_concurrent_jobs": 2,
            # Zero keeps every progress edit in tests deterministic.
            "progress_update_interval_seconds": 0.0,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return _make
