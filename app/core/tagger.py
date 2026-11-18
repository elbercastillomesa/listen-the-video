"""Write ID3 tags and cover art to an MP3 using mutagen."""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TCON, TDRC, TIT2, TPE1
from mutagen.id3 import Frame

from app.core.metadata import TrackMetadata

logger = logging.getLogger(__name__)

_COVER_TYPE = 3  # ID3 attached picture type: front cover.
_DEFAULT_COVER_MIME = "image/jpeg"


def tag_mp3(path: Path, metadata: TrackMetadata) -> None:
    """Write ID3 tags (and cover art, when available) into the MP3 at `path`."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    _set_text(tags, TIT2, metadata.title)
    _set_text(tags, TPE1, metadata.artist)
    _set_text(tags, TALB, metadata.album)
    _set_text(tags, TDRC, metadata.date)
    _set_text(tags, TCON, metadata.genre)

    if metadata.cover_url:
        cover = _download_cover(metadata.cover_url)
        if cover is not None:
            mime, data = cover
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=_COVER_TYPE, desc="Cover", data=data))

    tags.save(path, v2_version=3)
    logger.info("Tagged %s", path)


def _set_text(tags: ID3, frame_type: type[Frame], value: str | None) -> None:
    if value:
        tags.setall(frame_type.__name__, [frame_type(encoding=3, text=value)])


def _download_cover(url: str) -> tuple[str, bytes] | None:
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Could not download cover art from %s: %s", url, exc)
        return None

    if not response.content:
        return None

    mime = response.headers.get("Content-Type", _DEFAULT_COVER_MIME)
    return mime.split(";")[0].strip() or _DEFAULT_COVER_MIME, response.content
