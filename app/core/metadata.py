"""Fetch track metadata from free sources.

Deezer provides the album and its cover: its plain-text search matches the
released track far more reliably than MusicBrainz's fuzzy recording search,
which happily ranks covers and live albums first. MusicBrainz provides the
*original* release year and a genre, read from the release group, because
Deezer's album ``release_date`` is often a reissue date. Each source also
covers for the other when it has no match.
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
COVER_ART_GROUP_URL = (
    "https://coverartarchive.org/release-group/{release_group_id}/front-500"
)
DEEZER_SEARCH_URL = "https://api.deezer.com/search"
DEEZER_ALBUM_URL = "https://api.deezer.com/album/{album_id}"

_REQUEST_TIMEOUT = 15

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
    """Fetch metadata for a track, cross-checking Deezer and MusicBrainz.

    Deezer wins for the artist name, album and cover art (its search returns the
    released display name), MusicBrainz for the original release year and genre.
    Missing fields fall back to the other source and finally to the values
    resolved from the user's input.
    """
    deezer = _from_deezer(track)
    brainz = _from_musicbrainz(track, album=deezer.album if deezer else None)

    dz = deezer or TrackMetadata()
    mb = brainz or TrackMetadata()

    return TrackMetadata(
        title=_first(mb.title, dz.title, track.title),
        artist=_first(dz.artist, mb.artist, track.artist),
        album=_first(dz.album, mb.album),
        date=_first(mb.date, dz.date),
        genre=_first(mb.genre, dz.genre),
        cover_url=_first(dz.cover_url, mb.cover_url),
    )


def _from_deezer(track: Track) -> TrackMetadata | None:
    """Look the track up on Deezer and enrich it with its album details."""
    if not track.title:
        return None

    query = f"{track.artist} {track.title}".strip() if track.artist else track.title
    payload = _deezer_get(DEEZER_SEARCH_URL, {"q": query, "limit": 10})
    items = (payload or {}).get("data") or []
    item = _match_deezer_item(items, track.artist)
    if item is None:
        return None

    album = item.get("album") or {}
    details = (
        _deezer_get(DEEZER_ALBUM_URL.format(album_id=album["id"]), {})
        if album.get("id")
        else None
    ) or {}

    return TrackMetadata(
        title=item.get("title"),
        artist=(item.get("artist") or {}).get("name"),
        album=details.get("title") or album.get("title"),
        date=_year(details.get("release_date")) or _year(item.get("release_date")),
        genre=_first_genre(details.get("genres")),
        cover_url=album.get("cover_xl") or album.get("cover_big"),
    )


def _from_musicbrainz(track: Track, album: str | None = None) -> TrackMetadata | None:
    """Resolve year and genre from MusicBrainz, preferring the release group."""
    if not track.title:
        return None

    if album:
        group = _find_release_group(album, track.artist)
        if group is not None:
            return TrackMetadata(
                artist=_credit(group),
                album=group.get("title") or album,
                date=_year(group.get("first-release-date")),
                genre=_top_tag(group.get("tag-list")),
                cover_url=(
                    COVER_ART_GROUP_URL.format(release_group_id=group["id"])
                    if group.get("id")
                    else None
                ),
            )

    return _from_recording(track)


def _from_recording(track: Track) -> TrackMetadata | None:
    """Fallback: derive metadata from the artist-matching recording."""
    arguments: dict[str, object] = {"recording": track.title, "limit": 10}
    if track.artist:
        arguments["artist"] = track.artist

    try:
        result = musicbrainzngs.search_recordings(**arguments)
    except musicbrainzngs.MusicBrainzError as exc:
        logger.warning("MusicBrainz lookup failed: %s", exc)
        return None

    recording = _match_recording(result.get("recording-list") or [], track.artist)
    if recording is None:
        return None

    album, date, release_id = _pick_release(recording)
    return TrackMetadata(
        title=recording.get("title"),
        artist=_credit(recording),
        album=album,
        date=date,
        genre=_top_tag(recording.get("tag-list")),
        cover_url=COVER_ART_URL.format(release_id=release_id) if release_id else None,
    )


def _find_release_group(album: str, artist: str | None) -> dict | None:
    """Find the original studio album release group for `album`."""
    arguments: dict[str, object] = {
        "releasegroup": album,
        "primarytype": "album",
        "limit": 10,
    }
    if artist:
        arguments["artist"] = artist

    try:
        result = musicbrainzngs.search_release_groups(**arguments)
    except musicbrainzngs.MusicBrainzError as exc:
        logger.warning("MusicBrainz release-group lookup failed: %s", exc)
        return None

    groups = [
        group
        for group in (result.get("release-group-list") or [])
        if _is_studio_album(group)
    ]
    if artist:
        credited = [group for group in groups if _same_artist(_credit(group), artist)]
        if credited:
            groups = credited
    if not groups:
        return None

    return min(groups, key=lambda group: group.get("first-release-date") or "9999")


def _deezer_get(url: str, params: dict) -> dict | None:
    try:
        response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Deezer request failed (%s): %s", url, exc)
        return None


def _match_deezer_item(items: list[dict], artist: str | None) -> dict | None:
    """Return the first Deezer result by the requested artist."""
    if not items:
        return None
    if not artist:
        return items[0]
    for item in items:
        if _same_artist((item.get("artist") or {}).get("name"), artist):
            return item
    return None


def _match_recording(recordings: list[dict], artist: str | None) -> dict | None:
    """Return the first MusicBrainz recording by the requested artist."""
    if not recordings:
        return None
    if not artist:
        return recordings[0]
    for recording in recordings:
        if _same_artist(_credit(recording), artist):
            return recording
    return None


def _pick_release(recording: dict) -> tuple[str | None, str | None, str | None]:
    """Return (album, year, release_id), preferring a studio album release."""
    fallback: tuple[str | None, str | None, str | None] = (None, None, None)
    for release in recording.get("release-list") or []:
        if not release.get("id"):
            continue
        group = release.get("release-group") or {}
        if _is_studio_album(group):
            return release.get("title"), _year(release.get("date")), release["id"]
        if fallback[2] is None:
            fallback = (
                release.get("title"),
                _year(release.get("date")),
                release["id"],
            )
    return fallback


def _is_studio_album(group: dict) -> bool:
    """True for a release group that is a regular album (not live, etc.)."""
    return group.get("primary-type") == "Album" and not group.get("secondary-type-list")


def _credit(entry: dict) -> str | None:
    """Return the first credited artist name of a recording/release group."""
    phrase = entry.get("artist-credit-phrase")
    if phrase:
        return phrase
    credits = entry.get("artist-credit") or []
    if credits and isinstance(credits[0], dict):
        return credits[0].get("name")
    return None


def _top_tag(tags: list[dict] | None) -> str | None:
    """Return the most frequently applied tag (first tag when uncounted)."""
    if not tags:
        return None
    counted = [(tag, _tag_count(tag)) for tag in tags]
    ranked = [pair for pair in counted if pair[1] > 0]
    if ranked:
        return max(ranked, key=lambda pair: pair[1])[0].get("name")
    return tags[0].get("name")


def _tag_count(tag: dict) -> int:
    """Tag counts arrive as strings from MusicBrainz, so coerce defensively."""
    try:
        return int(tag.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _first_genre(genres: dict | None) -> str | None:
    data = (genres or {}).get("data") or []
    return data[0].get("name") if data else None


def _first(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _same_artist(candidate: str | None, target: str | None) -> bool:
    """Compare two artist names, ignoring case, punctuation and extra words.

    The comparison is word-based, so a name that merely contains another
    (e.g. "Breve" inside "El Breve Espacio") is not treated as the same artist. A
    trailing credit extension ("Daft Punk" vs "Daft Punk feat. Pharrell") is
    still accepted.
    """
    left, right = _normalize(candidate), _normalize(target)
    if not left or not right:
        return False
    return (
        left == right
        or left.startswith(f"{right} ")
        or right.startswith(f"{left} ")
    )


def _normalize(text: str | None) -> str:
    """Lower-case a name and reduce it to its words, ignoring punctuation."""
    spaced = "".join(char if char.isalnum() else " " for char in (text or "").lower())
    return " ".join(spaced.split())


def _year(date: str | None) -> str | None:
    if not date:
        return None
    return date[:4] if len(date) >= 4 else date
