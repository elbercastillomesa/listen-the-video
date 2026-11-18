"""Tests for the MP3 converter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core import converter
from app.core.converter import ConversionError


class TestConvertToMp3:
    def test_returns_mp3_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        destination = tmp_path / "out"
        _patch_ffmpeg(monkeypatch)

        result = converter.convert_to_mp3(source, "320k", destination)

        assert result == destination / "abc.mp3"
        assert result.exists()

    def test_defaults_destination_to_source_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        _patch_ffmpeg(monkeypatch)

        result = converter.convert_to_mp3(source)

        assert result == tmp_path / "abc.mp3"

    def test_builds_ffmpeg_command(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        captured: list[list[str]] = []
        _patch_ffmpeg(monkeypatch, captured)

        converter.convert_to_mp3(source, "192k")

        command = captured[0]
        assert command[0] == converter.FFMPEG_BINARY
        assert "libmp3lame" in command
        assert "192k" in command
        assert str(source) in command
        assert command[-1] == str(tmp_path / "abc.mp3")

    def test_strips_source_metadata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        captured: list[list[str]] = []
        _patch_ffmpeg(monkeypatch, captured)

        converter.convert_to_mp3(source)

        command = captured[0]
        assert "-map_metadata" in command
        assert command[command.index("-map_metadata") + 1] == "-1"

    def test_raises_when_ffmpeg_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        monkeypatch.setattr(converter.shutil, "which", lambda _: None)

        with pytest.raises(ConversionError, match="ffmpeg"):
            converter.convert_to_mp3(source)

    def test_raises_when_ffmpeg_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        _patch_ffmpeg(monkeypatch, returncode=1, stderr="boom")

        with pytest.raises(ConversionError, match="boom"):
            converter.convert_to_mp3(source)

    def test_raises_when_output_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _touch(tmp_path / "abc.webm")
        _patch_ffmpeg(monkeypatch, create_output=False)

        with pytest.raises(ConversionError, match="expected file"):
            converter.convert_to_mp3(source)


def _touch(path: Path) -> Path:
    path.write_bytes(b"audio")
    return path


def _patch_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    captured: list[list[str]] | None = None,
    *,
    returncode: int = 0,
    stderr: str = "",
    create_output: bool = True,
) -> None:
    """Patch ffmpeg availability and subprocess.run."""
    monkeypatch.setattr(converter.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        if captured is not None:
            captured.append(command)
        if create_output and returncode == 0:
            Path(command[-1]).write_bytes(b"mp3")
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(converter.subprocess, "run", fake_run)
