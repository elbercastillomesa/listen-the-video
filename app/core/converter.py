"""Convert downloaded audio to MP3 using ffmpeg.

The conversion output is intentionally left without metadata: ID3 tags are
written later from clean values, so inheriting the source container tags (which
often carry noisy YouTube metadata) would only be overwritten.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG_BINARY = "ffmpeg"


class ConversionError(RuntimeError):
    """Raised when ffmpeg is unavailable or fails to convert the audio."""


def convert_to_mp3(
    source: Path,
    bitrate: str = "320k",
    dest_dir: Path | None = None,
) -> Path:
    """Convert `source` to an MP3 file at `bitrate`.

    The output keeps the source stem and is written next to it unless `dest_dir`
    is given. Returns the path to the new MP3 file.

    Raises:
        ConversionError: if ffmpeg is missing or the conversion fails.
    """
    if shutil.which(FFMPEG_BINARY) is None:
        raise ConversionError("ffmpeg is not installed or not on PATH.")

    dest_dir = dest_dir or source.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{source.stem}.mp3"

    command = [
        FFMPEG_BINARY,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-map_metadata",
        "-1",
        str(target),
    ]

    logger.info("Converting %s to MP3 at %s.", source, bitrate)
    result = subprocess.run(command, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        raise ConversionError(
            f"ffmpeg failed with exit code {result.returncode}: {result.stderr.strip()}"
        )
    if not target.exists():
        raise ConversionError(f"ffmpeg did not produce the expected file: {target}")

    logger.info("Converted audio to %s", target)
    return target
