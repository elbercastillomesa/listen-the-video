"""Tests for application configuration loading."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app import config


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure each test loads settings from scratch."""
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_loads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_USER_ID", "42")
    monkeypatch.setenv("DATA_DIR", "/tmp/downloads")
    monkeypatch.setenv("MP3_BITRATE", "192k")
    monkeypatch.setenv("MAX_UPLOAD_MB", "20")
    monkeypatch.setenv("OUTPUT_FILENAME_TEMPLATE", "{title}")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "4")
    monkeypatch.setenv("PROGRESS_UPDATE_INTERVAL_SECONDS", "2.5")

    settings = config.get_settings()

    assert settings.telegram_bot_token == "token"
    assert settings.allowed_user_id == 42
    assert settings.data_dir == Path("/tmp/downloads")
    assert settings.mp3_bitrate == "192k"
    assert settings.max_upload_mb == 20
    assert settings.output_filename_template == "{title}"
    assert settings.max_concurrent_jobs == 4
    assert settings.progress_update_interval_seconds == 2.5


def test_applies_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("ALLOWED_USER_ID", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("MP3_BITRATE", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    monkeypatch.delenv("OUTPUT_FILENAME_TEMPLATE", raising=False)
    monkeypatch.delenv("MAX_CONCURRENT_JOBS", raising=False)
    monkeypatch.delenv("PROGRESS_UPDATE_INTERVAL_SECONDS", raising=False)

    settings = config.get_settings()

    assert settings.allowed_user_id is None
    assert settings.data_dir == Path("data")
    assert settings.mp3_bitrate == "320k"
    assert settings.max_upload_mb == 50
    assert settings.output_filename_template == "{artist} - {title}"
    assert settings.max_concurrent_jobs == 2
    assert settings.progress_update_interval_seconds == 1.5


def test_raises_when_token_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        config.get_settings()


def test_raises_when_allowed_user_id_is_not_an_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_USER_ID", "not-a-number")

    with pytest.raises(RuntimeError, match="ALLOWED_USER_ID"):
        config.get_settings()


def test_raises_when_max_upload_mb_is_not_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAX_UPLOAD_MB", "0")

    with pytest.raises(RuntimeError, match="MAX_UPLOAD_MB"):
        config.get_settings()


def test_raises_when_max_concurrent_jobs_is_not_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "0")

    with pytest.raises(RuntimeError, match="MAX_CONCURRENT_JOBS"):
        config.get_settings()


def test_raises_when_progress_interval_is_not_a_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("PROGRESS_UPDATE_INTERVAL_SECONDS", "soon")

    with pytest.raises(RuntimeError, match="PROGRESS_UPDATE_INTERVAL_SECONDS"):
        config.get_settings()
