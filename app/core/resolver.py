"""Resolve user input into a canonical track (artist + title).

Supported inputs:
- a plain song name, e.g. "Daft Punk - Instant Crush"
- a YouTube link
- a Spotify link, used only as a metadata reference (no audio is downloaded
  from Spotify)
"""

from __future__ import annotations

import html
import logging
import re

import requests
import yt_dlp

from app.core.models import Source, Track

logger = logging.getLogger(__name__)

YOUTUBE_URL_RE = re.compile(
    r"^https?://(?:www\.|m\.)?"
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)",
    re.IGNORECASE,
)

SPOTIFY_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/(?:intl-[a-z-]+/)?(?:track|album|playlist)/",
    re.IGNORECASE,
)

# Noise commonly appended to YouTube titles, e.g. "(Official Video)" or "[HD]".
_NOISE_RE = re.compile(
    r"\s*[\(\[]"
    r"[^\)\]]*(?:official|lyric|audio|video|visualizer|remaster|hd|hq|4k|mv|m/v)[^\)\]]*"
    r"[\)\]]",
    re.IGNORECASE,
)

# "Artist - Title" separators (hyphen/en dash/em dash surrounded by spaces).
_ARTIST_TITLE_SEP_RE = re.compile(r"\s+[-–—]\s+")

_CRAWLER_UA = (
    "facebookexternalhit/1.1 "
    "(+https://developers.facebook.com/docs/sharing/webmasters/crawler)"
)

_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"', re.IGNORECASE)
_OG_DESCRIPTION_RE = re.compile(
    r'<meta property="og:description" content="([^"]*)"', re.IGNORECASE
)


def detect_source(text: str) -> Source:
    """Classify the input as a YouTube link, a Spotify link, or plain text."""
    if YOUTUBE_URL_RE.match(text):
        return Source.YOUTUBE
    if SPOTIFY_URL_RE.match(text):
        return Source.SPOTIFY
    return Source.TEXT


def resolve_input(text: str) -> Track:
    """Resolve a raw user message into a Track."""
    text = text.strip()
    source = detect_source(text)

    if source is Source.YOUTUBE:
        return resolve_youtube(text)
    if source is Source.SPOTIFY:
        return resolve_spotify(text)
    return resolve_text(text)


def resolve_text(text: str) -> Track:
    """Resolve a plain song name into a Track."""
    cleaned = _clean_title(text)
    parts = _ARTIST_TITLE_SEP_RE.split(cleaned, maxsplit=1)

    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return Track(title=parts[1].strip(), artist=parts[0].strip(), source=Source.TEXT)

    return Track(title=cleaned, source=Source.TEXT)


def resolve_youtube(url: str) -> Track:
    """Resolve a YouTube link into a Track using yt-dlp metadata."""
    info = _extract_youtube_info(url)

    raw_title = (info.get("track") or info.get("title") or "").strip()
    cleaned = _clean_title(raw_title)

    artist = info.get("artist")
    title = cleaned

    parts = _ARTIST_TITLE_SEP_RE.split(cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artist, title = parts[0].strip(), parts[1].strip()
    elif not artist:
        artist = info.get("uploader") or info.get("channel")

    if artist:
        artist = _clean_artist(artist)

    return Track(title=title, artist=artist, source=Source.YOUTUBE, source_url=url)


def resolve_spotify(url: str) -> Track:
    """Resolve a Spotify link into a Track from its Open Graph tags.

    Spotify only exposes the Open Graph tags to link-preview crawlers, so a
    crawler User-Agent is used. No audio is downloaded from Spotify.

    Raises:
        RuntimeError: if the metadata could not be read from the page.
    """
    response = requests.get(url, timeout=15, headers={"User-Agent": _CRAWLER_UA})
    response.raise_for_status()

    title = _og_value(_OG_TITLE_RE, response.text)
    description = _og_value(_OG_DESCRIPTION_RE, response.text)

    if not title:
        raise RuntimeError(f"Could not read Spotify metadata from {url}")

    # Spotify descriptions look like "Artist · Album · Song · 1987".
    artist = None
    if description:
        artist = description.split("·")[0].strip() or None

    return Track(
        title=title,
        artist=artist,
        source=Source.SPOTIFY,
        source_url=url,
    )


def _extract_youtube_info(url: str) -> dict:
    """Fetch metadata for a YouTube URL without downloading the media."""
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    return info or {}


def _og_value(pattern: re.Pattern[str], document: str) -> str | None:
    match = pattern.search(document)
    if not match:
        return None
    return html.unescape(match.group(1)).strip() or None


def _clean_title(title: str) -> str:
    """Remove common YouTube title noise and collapse whitespace."""
    cleaned = _NOISE_RE.sub(" ", title)
    return re.sub(r"\s+", " ", cleaned).strip(" -–—")


def _clean_artist(artist: str) -> str:
    """Normalize an artist name (e.g. drop YouTube's "- Topic" suffix)."""
    cleaned = re.sub(r"\s*-\s*Topic\s*$", "", artist, flags=re.IGNORECASE)
    return cleaned.strip() or artist.strip()
