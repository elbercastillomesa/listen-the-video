"""Work out which way round a typed artist/title request goes.

The resolver assumes the user typed "Artist - Title" and hands the first part to
the artist. Sometimes the order is inverted, and the swapped pair then makes the
metadata lookups match the wrong track: Deezer's result is rejected because it is
filed under the real artist, and MusicBrainz's loose artist comparison can accept
an unrelated band.

This module asks the same free sources the metadata step uses which way round the
two typed tokens go. Each source is scored against both orientations, so the
result does not depend on the order the user typed. Only a clearly inverted pair
is rewritten; otherwise the caller keeps the artist/title it already resolved.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterator

import musicbrainzngs
import requests

from app.core.metadata import DEEZER_SEARCH_URL
from app.core.models import Source, Track

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15
_MUSICBRAINZ_LIMIT = 5
_DEEZER_LIMIT = 10

# A confident match must look like both typed tokens: an exact match on both
# scores 2.0 and a containment match on both scores 1.7. Anything lower is left
# to the caller's original split.
IDENTITY_THRESHOLD = 1.5

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Lower-case, strip accents and punctuation, and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    spaced = _NON_ALNUM_RE.sub(" ", without_accents.lower())
    return _WHITESPACE_RE.sub(" ", spaced).strip()


def similarity(query: str | None, value: str | None) -> float:
    """Score how closely `value` matches `query`, between 0.0 and 1.0."""
    left, right = normalize(query), normalize(value)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.85
    left_tokens, right_tokens = set(left.split()), set(right.split())
    shared = len(left_tokens & right_tokens)
    if shared:
        return 0.6 * shared / max(len(left_tokens), len(right_tokens))
    return 0.0


def compare(
    first: str, second: str, artist: str | None, title: str | None
) -> tuple[float, float]:
    """Score a candidate (artist, title) against the two typed tokens.

    Returns ``(straight, swapped)``: `straight` assumes the user typed
    "Artist - Title" (so `first` is the artist) and `swapped` assumes the
    inverted "Title - Artist". A high `swapped` with a low `straight` is what an
    inverted request looks like.
    """
    straight = similarity(first, artist) + similarity(second, title)
    swapped = similarity(first, title) + similarity(second, artist)
    return straight, swapped


def identify(first: str, second: str) -> Track | None:
    """Return the canonical track when the two tokens look inverted, else None.

    Both tokens are probed against MusicBrainz (in both orientations) and Deezer
    (whose free-text search is order-insensitive). An inversion is only reported
    when the strongest evidence for the "Title - Artist" reading clears
    `IDENTITY_THRESHOLD` *and* is stronger than the best evidence for the
    "Artist - Title" reading; that keeps a correctly typed pair unchanged, so
    the caller keeps the artist and title it already resolved.
    """
    best: Track | None = None
    best_swapped = 0.0
    best_straight = 0.0

    for artist, title in _candidates(first, second):
        if not title:
            continue
        straight, swapped = compare(first, second, artist, title)
        best_straight = max(best_straight, straight)
        if swapped > best_swapped:
            best_swapped = swapped
            best = Track(title=title, artist=artist, source=Source.TEXT)

    if (
        best is None
        or best_swapped < IDENTITY_THRESHOLD
        or best_swapped <= best_straight
    ):
        return None

    logger.info("Reversed %r / %r to %s - %s", first, second, best.artist, best.title)
    return best


def _candidates(first: str, second: str) -> Iterator[tuple[str | None, str | None]]:
    """Yield (artist, title) pairs from every source, in both orientations."""
    yield from _musicbrainz_candidates(first, second)
    yield from _deezer_candidates(first, second)


def _musicbrainz_candidates(
    first: str, second: str
) -> Iterator[tuple[str | None, str | None]]:
    """Query MusicBrainz with each token as the recording and the other as artist."""
    for recording, artist in ((second, first), (first, second)):
        try:
            result = musicbrainzngs.search_recordings(
                recording=recording, artist=artist, limit=_MUSICBRAINZ_LIMIT
            )
        except musicbrainzngs.MusicBrainzError as exc:
            logger.warning("MusicBrainz identity lookup failed: %s", exc)
            continue
        for entry in result.get("recording-list") or []:
            yield _credit(entry), entry.get("title")


def _deezer_candidates(
    first: str, second: str
) -> Iterator[tuple[str | None, str | None]]:
    """Query Deezer's order-insensitive free-text search."""
    query = f"{first} {second}".strip()
    try:
        response = requests.get(
            DEEZER_SEARCH_URL,
            params={"q": query, "limit": _DEEZER_LIMIT},
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Deezer identity lookup failed: %s", exc)
        return

    for item in (payload or {}).get("data") or []:
        yield (item.get("artist") or {}).get("name"), item.get("title")


def _credit(entry: dict) -> str | None:
    """Return the first credited artist name of a MusicBrainz recording."""
    phrase = entry.get("artist-credit-phrase")
    if phrase:
        return phrase
    credits = entry.get("artist-credit") or []
    if credits and isinstance(credits[0], dict):
        return credits[0].get("name")
    return None
