"""Tests for the asyncio job runner."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import TelegramError

from app.bot import jobs
from app.config import Settings
from app.core.converter import ConversionError
from app.core.metadata import TrackMetadata
from app.core.models import Candidate, Track
from app.core.pipeline import BuiltTrack
from app.core.progress import Progress, Stage

_TRACK = Track(title="Song", artist="Band")
_CANDIDATE = Candidate(title="Song", url="https://youtu.be/x")


def _make_message() -> MagicMock:
    """Build a fake Message with an editable status message and async replies."""
    status = MagicMock()
    status.edit_text = AsyncMock()
    status.delete = AsyncMock()

    message = MagicMock()
    message.reply_audio = AsyncMock()
    message.status = status
    return message


def _make_built(tmp_path: Path, *, size: int = 10) -> BuiltTrack:
    """Build a BuiltTrack backed by a real file inside a work directory."""
    work_dir = tmp_path / "work"
    work_dir.mkdir(exist_ok=True)
    path = work_dir / "song.mp3"
    path.write_bytes(b"x" * size)
    return BuiltTrack(path=path, metadata=TrackMetadata(title="Song", artist="Band"))


def _patch_build(
    monkeypatch: pytest.MonkeyPatch,
    built: BuiltTrack,
    progresses: tuple[Progress, ...] = (),
) -> None:
    """Replace build_mp3 with a fake that reports progress then returns `built`."""

    def fake_build(track, candidate, settings, on_progress=None):
        for progress in progresses:
            if on_progress is not None:
                on_progress(progress)
        return built

    monkeypatch.setattr(jobs, "build_mp3", fake_build)


def _patch_deliver(
    monkeypatch: pytest.MonkeyPatch, *, delay: float = 0.01
) -> dict[str, int]:
    """Replace the delivery step with one that records concurrency."""
    state = {"active": 0, "peak": 0, "calls": 0}

    async def fake_deliver(self, status, message, track, candidate):
        state["calls"] += 1
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(delay)
        state["active"] -= 1

    monkeypatch.setattr(jobs.JobRunner, "_deliver", fake_deliver)
    return state


def _texts(message: MagicMock) -> list[str]:
    return [call.args[0] for call in message.status.edit_text.await_args_list]


class TestRenderProgress:
    def test_includes_the_stage(self) -> None:
        assert jobs.render_progress(Progress(Stage.CONVERTING)) == "Converting to MP3..."

    def test_appends_the_detail(self) -> None:
        assert (
            jobs.render_progress(Progress(Stage.DOWNLOADING, "45.0%"))
            == "Downloading audio... 45.0%"
        )


class TestDeliver:
    def test_reports_progress_stages_in_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path)
        _patch_build(
            monkeypatch,
            built,
            (
                Progress(Stage.DOWNLOADING),
                Progress(Stage.CONVERTING),
                Progress(Stage.TAGGING),
            ),
        )
        message = _make_message()
        runner = jobs.JobRunner(make_settings())

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        assert _texts(message) == [
            "Downloading audio...",
            "Converting to MP3...",
            "Writing metadata...",
            "Uploading to Telegram...",
        ]

    def test_sends_the_mp3_then_deletes_the_status(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path, size=10)
        _patch_build(monkeypatch, built)
        message = _make_message()
        runner = jobs.JobRunner(make_settings())

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        kwargs = message.reply_audio.await_args.kwargs
        assert kwargs["filename"] == "song.mp3"
        assert kwargs["title"] == "Song"
        assert kwargs["performer"] == "Band"
        assert kwargs["audio"].getvalue() == b"x" * 10
        message.status.delete.assert_awaited_once()

    def test_removes_the_work_dir_after_sending(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path)
        work_dir = built.path.parent
        _patch_build(monkeypatch, built)
        message = _make_message()
        runner = jobs.JobRunner(make_settings())

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        assert not work_dir.exists()

    def test_reports_build_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
    ) -> None:
        def _fail(track, candidate, settings, on_progress=None):
            raise ConversionError("ffmpeg failed")

        monkeypatch.setattr(jobs, "build_mp3", _fail)
        message = _make_message()
        runner = jobs.JobRunner(make_settings())

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        message.status.edit_text.assert_awaited_once_with(jobs.BUILD_FAILED_TEXT)
        message.reply_audio.assert_not_awaited()

    def test_reports_file_over_the_upload_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path, size=1_100_000)
        _patch_build(monkeypatch, built)
        message = _make_message()
        runner = jobs.JobRunner(make_settings(max_upload_mb=1))

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        (text,) = message.status.edit_text.await_args.args
        assert "over the 1 MB" in text
        message.reply_audio.assert_not_awaited()

    def test_reports_send_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path)
        work_dir = built.path.parent
        _patch_build(monkeypatch, built)
        message = _make_message()
        message.reply_audio = AsyncMock(side_effect=TelegramError("too big"))
        runner = jobs.JobRunner(make_settings())

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        assert message.status.edit_text.await_args.args == (jobs.SEND_FAILED_TEXT,)
        assert not work_dir.exists()

    def test_throttles_repeated_detail_updates(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path)
        _patch_build(
            monkeypatch,
            built,
            (
                Progress(Stage.DOWNLOADING, "10%"),
                Progress(Stage.DOWNLOADING, "20%"),
            ),
        )
        message = _make_message()
        runner = jobs.JobRunner(make_settings(progress_update_interval_seconds=60.0))

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        assert _texts(message) == [
            "Downloading audio... 10%",
            "Uploading to Telegram...",
        ]

    def test_stage_changes_bypass_the_throttle(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        built = _make_built(tmp_path)
        _patch_build(
            monkeypatch,
            built,
            (
                Progress(Stage.DOWNLOADING, "10%"),
                Progress(Stage.CONVERTING),
            ),
        )
        message = _make_message()
        runner = jobs.JobRunner(make_settings(progress_update_interval_seconds=60.0))

        asyncio.run(runner.run(1, message.status, message, _TRACK, _CANDIDATE))

        assert _texts(message) == [
            "Downloading audio... 10%",
            "Converting to MP3...",
            "Uploading to Telegram...",
        ]


class TestConcurrency:
    def test_serializes_jobs_for_the_same_user(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
    ) -> None:
        state = _patch_deliver(monkeypatch)
        runner = jobs.JobRunner(make_settings(max_concurrent_jobs=2))
        message = _make_message()

        asyncio.run(_run_pair(runner, 1, 1, message))

        assert state["peak"] == 1
        assert state["calls"] == 2

    def test_limits_global_concurrency(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
    ) -> None:
        state = _patch_deliver(monkeypatch)
        runner = jobs.JobRunner(make_settings(max_concurrent_jobs=1))
        message = _make_message()

        asyncio.run(_run_pair(runner, 1, 2, message))

        assert state["peak"] == 1

    def test_runs_different_users_concurrently(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
    ) -> None:
        state = _patch_deliver(monkeypatch)
        runner = jobs.JobRunner(make_settings(max_concurrent_jobs=2))
        message = _make_message()

        asyncio.run(_run_pair(runner, 1, 2, message))

        assert state["peak"] == 2


class TestSpawn:
    def test_runs_the_job_in_the_background(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
    ) -> None:
        state = _patch_deliver(monkeypatch)
        runner = jobs.JobRunner(make_settings())
        message = _make_message()

        async def scenario() -> None:
            runner.spawn(1, message.status, message, _TRACK, _CANDIDATE)
            # spawn returns before the scheduled job gets to run.
            assert state["calls"] == 0
            await asyncio.sleep(0.05)

        asyncio.run(scenario())

        assert state["calls"] == 1

    def test_logs_unexpected_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        make_settings: Callable[..., Settings],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def _boom(self, status, message, track, candidate) -> None:
            raise ValueError("kaboom")

        monkeypatch.setattr(jobs.JobRunner, "_deliver", _boom)
        runner = jobs.JobRunner(make_settings())
        message = _make_message()

        async def scenario() -> None:
            runner.spawn(1, message.status, message, _TRACK, _CANDIDATE)
            await asyncio.sleep(0.05)

        with caplog.at_level(logging.ERROR, logger="app.bot.jobs"):
            asyncio.run(scenario())

        assert "Build job crashed" in caplog.text


async def _run_pair(runner: jobs.JobRunner, user_a: int, user_b: int, message) -> None:
    """Run two jobs at once, one per user id."""
    await asyncio.gather(
        runner.run(user_a, message.status, message, _TRACK, _CANDIDATE),
        runner.run(user_b, message.status, message, _TRACK, _CANDIDATE),
    )
