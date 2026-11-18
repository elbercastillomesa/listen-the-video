"""Fetch track metadata from free sources.

MusicBrainz is the primary source (recording, artist, release and genre) and
also yields the release id used to build a Cover Art Archive URL. Deezer is
used as a fallback to fill any gaps, especially the cover art.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import musicbrainzngs
import requests

from app.core.models import Track

logger = logging.getLogger(__name__)

_APP_NAME = "listen-the-video"
_APP_VERSION = "0.1"
_CONTACT = "https://github.com/elbercastillomesa/listen-the-video"

COVER_ART_URL = "https://coverartarchive.org/release/{release_id}/front-500"
DEEZER_SEARCH_URL = "https://api.deezer.com/search"

musicbrainzngs.set_useragent(_APP_NAME, _APP_VERSION, _CONTACT)


@dataclass(frozen=True)
class TrackMetadata:
    """Metadata to embed in the final MP3."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    date: str | None = None
    genre: str | None = None
    cover_url: str | None = None


def fetch_metadata(track: Track) -> TrackMetadata:
    """Fetch metadata for a track, filling gaps with a Deezer fallback."""
    metadata = _from_musicbrainz(track) or TrackMetadata()

    if not (metadata.cover_url and metadata.album and metadata.date):
        fallback = _from_deezer(track)
        if fallback is not None:
            metadata = _merge(metadata, fallback)

    return TrackMetadata(
        title=metadata.title or track.title or None,
        artist=metadata.artist or track.artist,
        album=metadata.album,
        date=metadata.date,
        genre=metadata.genre,
        cover_url=metadata.cover_url,
    )


def _from_musicbrainz(track: Track) -> TrackMetadata | None:
    if not track.title:
        return None

    arguments: dict[str, object] = {"recording": track.title, "limit": 5}
    if track.artist:
        arguments["artist"] = track.artist

    try:
        result = musicbrainzngs.search_recordings(**arguments)
    except musicbrainzngs.MusicBrainzError as exc:
        logger.warning("MusicBrainz lookup failed: %s", exc)
        return None

    recordings = result.get("recording-list") or []
    if not recordings:
        return None

    recording = recordings[0]
    album, date, release_id = _first_release(recording)

    return TrackMetadata(
        title=recording.get("title"),
        artist=_first_artist(recording),
        album=album,
        date=date,
        genre=_first_tag(recording),
        cover_url=COVER_ART_URL.format(release_id=release_id) if release_id else None,
    )


def _from_deezer(track: Track) -> TrackMetadata | None:
    if not track.title:
        return None

    if track.artist:
        query = f'artist:"{track.artist}" track:"{track.title}"'
    else:
        query = f'track:"{track.title}"'

    try:
        response = requests.get(
            DEEZER_SEARCH_URL, params={"q": query, "limit": 1}, timeout=15
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Deezer lookup failed: %s", exc)
        return None

    results = payload.get("data") or []
    if not results:
        return None

    item = results[0]
    album = item.get("album") or {}

    return TrackMetadata(
        title=item.get("title"),
        artist=(item.get("artist") or {}).get("name"),
        album=album.get("title"),
        date=_year(item.get("release_date")),
        cover_url=album.get("cover_xl") or album.get("cover_big"),
    )


def _merge(base: TrackMetadata, fallback: TrackMetadata) -> TrackMetadata:
    """Fill empty fields of `base` with values from `fallback`."""
    return TrackMetadata(
        title=base.title or fallback.title,
        artist=base.artist or fallback.artist,
        album=base.album or fallback.album,
        date=base.date or fallback.date,
        genre=base.genre or fallback.genre,
        cover_url=base.cover_url or fallback.cover_url,
    )


def _first_artist(recording: dict) -> str | None:
    credits = recording.get("artist-credit") or []
    if not credits:
        return None
    credit = credits[0]
    if isinstance(credit, dict):
        return credit.get("name") or (credit.get("artist") or {}).get("name")
    return None


def _first_release(recording: dict) -> tuple[str | None, str | None, str | None]:
    """Return (album, year, release_id) for the first release that has an id."""
    for release in recording.get("release-list") or []:
        release_id = release.get("id")
        if release_id:
            return release.get("title"), _year(release.get("date")), release_id
    return None, None, None


def _first_tag(recording: dict) -> str | None:
    tags = recording.get("tag-list") or []
    return tags[0].get("name") if tags else None


def _year(date: str | None) -> str | None:
    if not date:
        return None
    return date[:4] if len(date) >= 4 else date
