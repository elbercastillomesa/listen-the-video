"""Render the filename used when delivering a track.

The name is built from a user-configurable template (``OUTPUT_FILENAME_TEMPLATE``)
so downloaded files are not named after the YouTube video id. Only the stem is
returned; the caller appends the ``.mp3`` extension.
"""

from __future__ import annotations

import re

from app.core.metadata import TrackMetadata
from app.core.models import Track

DEFAULT_TEMPLATE = "{title} - {artist}"

# Characters that are unsafe in filenames across platforms, plus control chars.
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")
# Runs of separators left behind by empty tokens, e.g. "A - - B" or "A - ".
_SEPARATOR_RUN_RE = re.compile(r"(?:\s*[-–—]\s*){2,}")
_YEAR_RE = re.compile(r"(\d{4})")
# Characters trimmed from the start/end of the final name.
_EDGE_CHARS = " -–—_.\t"

_MAX_LENGTH = 120


def render_filename(
    template: str,
    metadata: TrackMetadata,
    track: Track,
    fallback: str,
) -> str:
    """Return a sanitized filename stem built from ``template``.

    Supported tokens are ``{artist}``, ``{title}``, ``{album}`` and ``{year}``.
    Unknown tokens and missing values expand to an empty string, and the leftover
    separators are cleaned up. When the template is empty or renders to nothing,
    ``fallback`` (usually the downloaded file's stem) is used instead.
    """
    if not template.strip():
        return _sanitize(fallback)

    stem = _sanitize(_substitute(template, metadata, track))
    return stem or _sanitize(fallback)


def _substitute(template: str, metadata: TrackMetadata, track: Track) -> str:
    values = {
        "artist": metadata.artist or track.artist or "",
        "title": metadata.title or track.title or "",
        "album": metadata.album or "",
        "year": _year(metadata.date),
    }
    try:
        return template.format_map(_MissingDefault(values))
    except (KeyError, ValueError):
        return ""


class _MissingDefault(dict):
    """A mapping whose unknown keys expand to an empty string."""

    def __missing__(self, key: str) -> str:
        return ""


def _year(date: str | None) -> str:
    match = _YEAR_RE.search(date or "")
    return match.group(1) if match else ""


def _sanitize(text: str) -> str:
    text = _UNSAFE_CHARS_RE.sub("", text)
    text = _SEPARATOR_RUN_RE.sub(" - ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip(_EDGE_CHARS)
    return text[:_MAX_LENGTH].strip(_EDGE_CHARS)
