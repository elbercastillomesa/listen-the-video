"""Stage-based progress reporting shared by the core pipeline and the bot.

The core modules stay Telegram-free: they only emit `Progress` values through a
plain callback. Whoever subscribes (the bot job runner) decides how to surface
them, e.g. by editing a Telegram status message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class Stage(str, Enum):
    """The stages a track build goes through."""

    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    TAGGING = "tagging"
    SENDING = "sending"


@dataclass(frozen=True)
class Progress:
    """A progress report emitted while building a track.

    `detail` carries stage-specific context, e.g. the download percentage.
    """

    stage: Stage
    detail: str = ""


ProgressCallback = Callable[[Progress], None]


def noop_progress(progress: Progress) -> None:
    """Default callback for callers that do not care about progress."""
    return None
