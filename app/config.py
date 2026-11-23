"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_optional_int(name: str) -> int | None:
    """Read an optional integer environment variable."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be an integer, got {raw!r}. "
            "Leave it empty to allow any user."
        ) from exc


def _get_optional_float(name: str) -> float | None:
    """Read an optional numeric environment variable."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}.") from exc


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the bot."""

    telegram_bot_token: str
    allowed_user_id: int | None
    data_dir: Path
    mp3_bitrate: str
    max_upload_mb: int
    output_filename_template: str
    max_concurrent_jobs: int
    progress_update_interval_seconds: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache the application settings.

    Raises:
        RuntimeError: if the required bot token is missing.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    max_upload_mb = _get_optional_int("MAX_UPLOAD_MB")
    if max_upload_mb is not None and max_upload_mb <= 0:
        raise RuntimeError(
            f"MAX_UPLOAD_MB must be a positive integer, got {max_upload_mb}."
        )

    max_concurrent_jobs = _get_optional_int("MAX_CONCURRENT_JOBS")
    if max_concurrent_jobs is not None and max_concurrent_jobs <= 0:
        raise RuntimeError(
            f"MAX_CONCURRENT_JOBS must be a positive integer, got {max_concurrent_jobs}."
        )

    progress_interval = _get_optional_float("PROGRESS_UPDATE_INTERVAL_SECONDS")
    if progress_interval is not None and progress_interval < 0:
        raise RuntimeError(
            "PROGRESS_UPDATE_INTERVAL_SECONDS must be zero or greater, got "
            f"{progress_interval}."
        )

    return Settings(
        telegram_bot_token=token,
        allowed_user_id=_get_optional_int("ALLOWED_USER_ID"),
        data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
        mp3_bitrate=os.getenv("MP3_BITRATE", "320k").strip() or "320k",
        max_upload_mb=max_upload_mb or 50,
        # Empty value keeps the downloaded file's original name.
        output_filename_template=os.getenv(
            "OUTPUT_FILENAME_TEMPLATE", "{title} - {artist}"
        ).strip(),
        max_concurrent_jobs=max_concurrent_jobs or 2,
        progress_update_interval_seconds=(
            progress_interval if progress_interval is not None else 1.5
        ),
    )
