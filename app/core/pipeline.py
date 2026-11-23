"""Run the download, conversion and tagging steps end to end.

Everything happens in a throwaway directory under DATA_DIR so that a failure
never leaves half-built files behind. Call `cleanup` once the MP3 has been sent.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.core.converter import convert_to_mp3
from app.core.metadata import TrackMetadata, fetch_metadata
from app.core.models import Candidate, Track
from app.core.naming import render_filename
from app.core.progress import Progress, ProgressCallback, Stage, noop_progress
from app.core.resolver import split_artist_title
from app.core.tagger import tag_mp3
from app.core.youtube import download_audio

logger = logging.getLogger(__name__)

_WORK_DIR_PREFIX = "track-"


@dataclass(frozen=True)
class BuiltTrack:
    """A finished MP3 together with the metadata written onto it."""

    path: Path
    metadata: TrackMetadata


def build_mp3(
    track: Track,
    candidate: Candidate,
    settings: Settings,
    on_progress: ProgressCallback = noop_progress,
) -> BuiltTrack:
    """Download, convert and tag the chosen candidate.

    `on_progress` is called before each stage; download percentages are reported
    through the same callback by `download_audio`.

    Raises:
        The underlying error from whichever step fails (yt-dlp, ffmpeg or
        mutagen), after removing the working directory.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=_WORK_DIR_PREFIX, dir=settings.data_dir))

    try:
        on_progress(Progress(Stage.DOWNLOADING))
        source = download_audio(candidate.url, work_dir, on_progress=on_progress)
        on_progress(Progress(Stage.CONVERTING))
        mp3 = convert_to_mp3(source, settings.mp3_bitrate, dest_dir=work_dir)
        enriched = _enrich_track(track, candidate)
        metadata = fetch_metadata(enriched)
        on_progress(Progress(Stage.TAGGING))
        tag_mp3(mp3, metadata)
        mp3 = _rename(mp3, metadata, enriched, settings.output_filename_template)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    logger.info("Built %s", mp3)
    return BuiltTrack(path=mp3, metadata=metadata)


def _enrich_track(track: Track, candidate: Candidate) -> Track:
    """Fill in a missing artist from the candidate's YouTube title.

    Users often type just the song name ("505") which the resolver cannot split
    into artist/title. YouTube video titles almost always carry the canonical
    "Artist - Title" form, so the chosen candidate is used to recover the
    artist when the resolved track is missing one.
    """
    if track.artist:
        return track

    artist, title = split_artist_title(candidate.title)
    if artist:
        return Track(
            title=title or track.title,
            artist=artist,
            source=track.source,
            source_url=track.source_url,
        )
    return track


def _rename(mp3: Path, metadata: TrackMetadata, track: Track, template: str) -> Path:
    """Rename the tagged MP3 using the configured filename template."""
    stem = render_filename(template, metadata, track, fallback=mp3.stem)
    target = mp3.with_name(f"{stem}.mp3")
    if target != mp3:
        mp3.replace(target)
    return target


def cleanup(built: BuiltTrack) -> None:
    """Remove the working directory that holds the built MP3."""
    shutil.rmtree(built.path.parent, ignore_errors=True)
