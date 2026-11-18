"""Inline keyboards used to present search results."""

from __future__ import annotations

from collections.abc import Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.models import Candidate

CALLBACK_PICK_PREFIX = "pick:"

# Telegram truncates very long button labels, so shorten them ourselves.
_MAX_LABEL_LENGTH = 60


def build_candidates_keyboard(candidates: Sequence[Candidate]) -> InlineKeyboardMarkup:
    """Build one button per candidate, indexed by its position in the list."""
    rows = [
        [
            InlineKeyboardButton(
                _label(candidate), callback_data=f"{CALLBACK_PICK_PREFIX}{index}"
            )
        ]
        for index, candidate in enumerate(candidates)
    ]
    return InlineKeyboardMarkup(rows)


def parse_pick_callback(data: str) -> int | None:
    """Return the candidate index carried by a callback, or None if malformed."""
    if not data.startswith(CALLBACK_PICK_PREFIX):
        return None

    try:
        return int(data[len(CALLBACK_PICK_PREFIX) :])
    except ValueError:
        return None


def _label(candidate: Candidate) -> str:
    label = candidate.title
    if candidate.duration:
        label = f"{label} ({_format_duration(candidate.duration)})"
    return _truncate(label, _MAX_LABEL_LENGTH)


def _format_duration(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
