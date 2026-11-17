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
    return int(raw)


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the bot."""

    telegram_bot_token: str
    allowed_user_id: int | None
    data_dir: Path
    mp3_bitrate: str
    max_upload_mb: int


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

    return Settings(
        telegram_bot_token=token,
        allowed_user_id=_get_optional_int("ALLOWED_USER_ID"),
        data_dir=Path(os.getenv("DATA_DIR", "data")).expanduser(),
        mp3_bitrate=os.getenv("MP3_BITRATE", "320k").strip() or "320k",
        max_upload_mb=_get_optional_int("MAX_UPLOAD_MB") or 50,
    )
