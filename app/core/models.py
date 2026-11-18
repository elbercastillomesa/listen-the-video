"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    """Where a resolution request came from."""

    TEXT = "text"
    YOUTUBE = "youtube"
    SPOTIFY = "spotify"


@dataclass(frozen=True)
class Track:
    """A music track resolved from user input."""

    title: str
    artist: str | None = None
    source: Source = Source.TEXT
    source_url: str | None = None
