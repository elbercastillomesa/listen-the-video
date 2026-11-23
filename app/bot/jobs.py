"""Asyncio job runner for track builds.

The runner bounds how many builds run at once, serializes a single user's own
jobs, and reports staged progress by editing the status message. The core
pipeline stays Telegram-free: progress crosses the worker-thread boundary through
a plain callback that this module hops back onto the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO
from typing import Final, cast

from requests import RequestException
from telegram import Message
from telegram.error import TelegramError
from yt_dlp.utils import DownloadError

from app.config import Settings
from app.core.converter import ConversionError
from app.core.models import Candidate, Track
from app.core.pipeline import BuiltTrack, build_mp3, cleanup
from app.core.progress import Progress, Stage

logger = logging.getLogger(__name__)

# Key under `context.bot_data` where the application-wide runner is stored.
BOT_DATA_KEY = "job_runner"

BUILD_FAILED_TEXT = "I could not prepare that track. Please try another match."
SEND_FAILED_TEXT = "I could not send the MP3. Please try again."
TOO_LARGE_TEXT = "That MP3 is {size:.1f} MB, over the {limit} MB Telegram limit."

# Errors expected while building or sending. Anything else bubbles up to the
# task's done callback, where it is logged rather than silently dropped.
_DELIVERY_ERRORS = (
    DownloadError,
    ConversionError,
    RequestException,
    RuntimeError,
    OSError,
    TelegramError,
)

_STAGE_TEXT = {
    Stage.SEARCHING: "Searching YouTube",
    Stage.DOWNLOADING: "Downloading audio",
    Stage.CONVERTING: "Converting to MP3",
    Stage.TAGGING: "Writing metadata",
    Stage.SENDING: "Uploading to Telegram",
}

# Sentinel pushed onto the progress queue once the worker thread is done.
_DONE: Final = object()


def render_progress(progress: Progress) -> str:
    """Render a progress report as the status message text."""
    base = _STAGE_TEXT.get(progress.stage, progress.stage.value)
    if progress.detail:
        return f"{base}... {progress.detail}"
    return f"{base}..."


class JobRunner:
    """Schedule and run track builds with bounded, per-user concurrency."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_jobs))
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(
        self,
        user_id: int,
        status: Message,
        message: Message,
        track: Track,
        candidate: Candidate,
    ) -> None:
        """Queue a build in the background and return immediately."""
        task = asyncio.get_running_loop().create_task(
            self.run(user_id, status, message, track, candidate)
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_done)

    async def run(
        self,
        user_id: int,
        status: Message,
        message: Message,
        track: Track,
        candidate: Candidate,
    ) -> None:
        """Wait for a slot, then build and deliver the track."""
        async with self._semaphore:
            async with self._user_lock(user_id):
                await self._deliver(status, message, track, candidate)

    def _user_lock(self, user_id: int) -> asyncio.Lock:
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        return lock

    def _on_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Build job crashed", exc_info=error)

    async def _deliver(
        self, status: Message, message: Message, track: Track, candidate: Candidate
    ) -> None:
        try:
            built = await self._build(track, candidate, status)
        except _DELIVERY_ERRORS:
            logger.exception("Failed to build the MP3 for %s", candidate.url)
            await status.edit_text(BUILD_FAILED_TEXT)
            return

        try:
            size_mb = built.path.stat().st_size / (1024 * 1024)
            if size_mb > self._settings.max_upload_mb:
                await status.edit_text(
                    TOO_LARGE_TEXT.format(
                        size=size_mb, limit=self._settings.max_upload_mb
                    )
                )
                return

            await status.edit_text(render_progress(Progress(Stage.SENDING)))
            # Reading and uploading can take a while for a full-length track.
            data = await asyncio.to_thread(built.path.read_bytes)
            await message.reply_audio(
                audio=BytesIO(data),
                filename=built.path.name,
                title=built.metadata.title or track.title,
                performer=built.metadata.artist or track.artist,
            )
            await status.delete()
        except _DELIVERY_ERRORS:
            logger.exception("Failed to send the MP3 for %s", candidate.url)
            await status.edit_text(SEND_FAILED_TEXT)
        finally:
            cleanup(built)

    async def _build(
        self, track: Track, candidate: Candidate, status: Message
    ) -> BuiltTrack:
        """Run `build_mp3` in a thread, applying progress updates as they arrive."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()

        def report(progress: Progress) -> None:
            # Called from the worker thread: hand the report to the loop.
            loop.call_soon_threadsafe(queue.put_nowait, progress)

        def work() -> BuiltTrack:
            try:
                return build_mp3(
                    track, candidate, self._settings, on_progress=report
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        worker = asyncio.create_task(asyncio.to_thread(work))
        await self._drain(queue, status)
        return await worker

    async def _drain(self, queue: asyncio.Queue[object], status: Message) -> None:
        """Edit the status message as progress reports come off the queue."""
        interval = self._settings.progress_update_interval_seconds
        last_stage: Stage | None = None
        last_edit_at = 0.0
        while True:
            item = await queue.get()
            if item is _DONE:
                return
            progress = cast(Progress, item)
            now = time.monotonic()
            # Always surface a stage change; throttle same-stage detail updates.
            if progress.stage == last_stage and now - last_edit_at < interval:
                continue
            last_stage = progress.stage
            last_edit_at = now
            await status.edit_text(render_progress(progress))
