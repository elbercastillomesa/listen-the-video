"""YouTube search and audio download using yt-dlp.

Search uses flat extraction (metadata only) so the bot can present a list of
candidates without downloading anything. Download fetches the best available
audio stream; the MP3 conversion happens in a later phase.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yt_dlp

from app.core.models import Candidate, Track
from app.core.progress import Progress, ProgressCallback, Stage

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_LIMIT = 5

# Fail fast instead of blocking the worker thread if the network stalls.
_SOCKET_TIMEOUT = 30

# yt-dlp colourises `_percent_str`; strip the escapes before showing it.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

_SEARCH_OPTIONS: dict = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": True,
    "noplaylist": True,
    "socket_timeout": _SOCKET_TIMEOUT,
}


def build_query(track: Track) -> str:
    """Build a YouTube search query from a resolved track."""
    parts = [track.artist, track.title] if track.artist else [track.title]
    return " ".join(part.strip() for part in parts if part and part.strip())


def search(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[Candidate]:
    """Search YouTube and return up to `limit` candidates.

    The search does not download any media.
    """
    query = query.strip()
    if not query:
        return []

    # Pass a copy: yt-dlp mutates the options dict it is given.
    with yt_dlp.YoutubeDL(dict(_SEARCH_OPTIONS)) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    entries = (info or {}).get("entries") or []
    candidates: list[Candidate] = []
    for entry in entries:
        candidate = _candidate_from_entry(entry)
        if candidate is not None:
            candidates.append(candidate)

    logger.info("Search %r returned %d candidates.", query, len(candidates))
    return candidates


def download_audio(
    url: str, dest_dir: Path, on_progress: ProgressCallback | None = None
) -> Path:
    """Download the best available audio stream for a URL.

    Returns the path to the downloaded file (not yet converted to MP3). When
    `on_progress` is given, download percentages are reported as `DOWNLOADING`
    progress. The hook fires from yt-dlp's worker thread, so callbacks must be
    thread-safe (the job runner schedules them onto the event loop).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": _SOCKET_TIMEOUT,
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
    }
    if on_progress is not None:
        options["progress_hooks"] = [_download_hook(on_progress)]

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError(f"Could not download audio from {url}")
        path = Path(ydl.prepare_filename(info))

    logger.info("Downloaded audio to %s", path)
    return path


def _download_hook(on_progress: ProgressCallback):
    """Build a yt-dlp progress hook that reports DOWNLOADING percentages."""

    def hook(data: dict) -> None:
        if data.get("status") == "finished":
            on_progress(Progress(Stage.DOWNLOADING, "100%"))
            return
        percent = _clean_percent(data.get("_percent_str"))
        if percent:
            on_progress(Progress(Stage.DOWNLOADING, percent))

    return hook


def _clean_percent(raw: object) -> str:
    """Normalise yt-dlp's colourised percentage string."""
    if not isinstance(raw, str):
        return ""
    return _ANSI_ESCAPE.sub("", raw).strip()


def _candidate_from_entry(entry: dict) -> Candidate | None:
    """Convert a raw yt-dlp search entry into a Candidate."""
    title = (entry.get("title") or "").strip()
    if not title:
        return None

    url = entry.get("url") or entry.get("webpage_url")
    if not url and entry.get("id"):
        url = _watch_url(entry["id"])
    elif url and not url.startswith("http"):
        url = _watch_url(url)
    if not url:
        return None

    duration = entry.get("duration")

    return Candidate(
        title=title,
        url=url,
        artist=entry.get("uploader") or entry.get("channel"),
        duration=int(duration) if duration is not None else None,
    )


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"
