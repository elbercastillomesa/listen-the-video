"""Tests for the download/convert/tag pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest
from yt_dlp.utils import DownloadError

from app.config import Settings
from app.core import pipeline
from app.core.metadata import TrackMetadata
from app.core.models import Candidate, Track
from app.core.progress import Progress, Stage

_TRACK = Track(title="Instant Crush", artist="Daft Punk")
_CANDIDATE = Candidate(title="Instant Crush", url="https://youtu.be/x")


class TestBuildMp3:
    def test_runs_every_step_in_order(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")
        _patch_steps(monkeypatch, calls, metadata)

        built = pipeline.build_mp3(_TRACK, _CANDIDATE, _settings(make_settings, tmp_path))

        assert calls == ["download", "convert", "metadata", "tag"]
        assert built.metadata is metadata

    def test_converts_into_a_work_dir_under_data_dir(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        _patch_steps(monkeypatch, calls, TrackMetadata())
        settings = _settings(make_settings, tmp_path)

        built = pipeline.build_mp3(_TRACK, _CANDIDATE, settings)

        assert built.path.parent.parent == settings.data_dir
        assert built.path.parent.name.startswith(pipeline._WORK_DIR_PREFIX)

    def test_downloads_the_candidate_url(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        urls: list[str] = []

        def fake_download(
            url: str, dest_dir: Path, on_progress: object = None
        ) -> Path:
            urls.append(url)
            return dest_dir / "audio.webm"

        monkeypatch.setattr(pipeline, "download_audio", fake_download)
        monkeypatch.setattr(pipeline, "convert_to_mp3", _fake_convert)
        monkeypatch.setattr(pipeline, "fetch_metadata", lambda track: TrackMetadata())
        monkeypatch.setattr(pipeline, "tag_mp3", lambda path, meta: None)

        pipeline.build_mp3(_TRACK, _CANDIDATE, _settings(make_settings, tmp_path))

        assert urls == [_CANDIDATE.url]

    def test_uses_the_configured_bitrate(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        bitrates: list[str] = []

        def fake_convert(source: Path, bitrate: str, dest_dir: Path | None = None) -> Path:
            bitrates.append(bitrate)
            assert dest_dir is not None
            target = dest_dir / "audio.mp3"
            target.touch()
            return target

        monkeypatch.setattr(pipeline, "download_audio", _fake_download)
        monkeypatch.setattr(pipeline, "convert_to_mp3", fake_convert)
        monkeypatch.setattr(pipeline, "fetch_metadata", lambda track: TrackMetadata())
        monkeypatch.setattr(pipeline, "tag_mp3", lambda path, meta: None)
        settings = _settings(make_settings, tmp_path, mp3_bitrate="128k")

        pipeline.build_mp3(_TRACK, _CANDIDATE, settings)

        assert bitrates == ["128k"]

    def test_removes_the_work_dir_when_a_step_fails(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        def _fail(url: str, dest_dir: Path, on_progress: object = None) -> Path:
            raise DownloadError("download failed")

        monkeypatch.setattr(pipeline, "download_audio", _fail)
        settings = _settings(make_settings, tmp_path)

        with pytest.raises(DownloadError):
            pipeline.build_mp3(_TRACK, _CANDIDATE, settings)

        assert list(settings.data_dir.iterdir()) == []

    def test_enriches_track_from_candidate_when_artist_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        seen: list[Track] = []
        candidate = Candidate(
            title="Arctic Monkeys - 505 (Official Audio)",
            url="https://youtu.be/x",
        )

        def fake_fetch(track: Track) -> TrackMetadata:
            seen.append(track)
            return TrackMetadata()

        monkeypatch.setattr(pipeline, "download_audio", _fake_download)
        monkeypatch.setattr(pipeline, "convert_to_mp3", _fake_convert)
        monkeypatch.setattr(pipeline, "fetch_metadata", fake_fetch)
        monkeypatch.setattr(pipeline, "tag_mp3", lambda path, meta: None)

        pipeline.build_mp3(
            Track(title="505 artic monkeys"),
            candidate,
            _settings(make_settings, tmp_path),
        )

        assert seen[0].artist == "Arctic Monkeys"
        assert seen[0].title == "505"

    def test_keeps_resolved_artist_when_present(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        seen: list[Track] = []

        def fake_fetch(track: Track) -> TrackMetadata:
            seen.append(track)
            return TrackMetadata()

        monkeypatch.setattr(pipeline, "download_audio", _fake_download)
        monkeypatch.setattr(pipeline, "convert_to_mp3", _fake_convert)
        monkeypatch.setattr(pipeline, "fetch_metadata", fake_fetch)
        monkeypatch.setattr(pipeline, "tag_mp3", lambda path, meta: None)

        pipeline.build_mp3(_TRACK, _CANDIDATE, _settings(make_settings, tmp_path))

        assert seen[0].artist == "Daft Punk"
        assert seen[0].title == "Instant Crush"

    def test_names_the_file_from_the_metadata_template(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")
        _patch_steps(monkeypatch, calls, metadata)

        built = pipeline.build_mp3(_TRACK, _CANDIDATE, _settings(make_settings, tmp_path))

        assert built.path.name == "Daft Punk - Instant Crush.mp3"
        assert built.path.exists()

    def test_uses_the_configured_filename_template(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")
        _patch_steps(monkeypatch, calls, metadata)
        settings = _settings(
            make_settings, tmp_path, output_filename_template="{title} - {artist}"
        )

        built = pipeline.build_mp3(_TRACK, _CANDIDATE, settings)

        assert built.path.name == "Instant Crush - Daft Punk.mp3"

    def test_empty_template_keeps_the_downloaded_name(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        _patch_steps(monkeypatch, calls, TrackMetadata())
        settings = _settings(make_settings, tmp_path, output_filename_template="")

        built = pipeline.build_mp3(_TRACK, _CANDIDATE, settings)

        assert built.path.name == "audio.mp3"

    def test_reports_stages_in_order(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        _patch_steps(monkeypatch, calls, TrackMetadata())
        reports: list[Progress] = []

        pipeline.build_mp3(
            _TRACK,
            _CANDIDATE,
            _settings(make_settings, tmp_path),
            on_progress=reports.append,
        )

        assert [report.stage for report in reports] == [
            Stage.DOWNLOADING,
            Stage.CONVERTING,
            Stage.TAGGING,
        ]

    def test_forwards_the_callback_to_the_downloader(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        seen: list[object] = []

        def fake_download(
            url: str, dest_dir: Path, on_progress: object = None
        ) -> Path:
            seen.append(on_progress)
            return dest_dir / "audio.webm"

        monkeypatch.setattr(pipeline, "download_audio", fake_download)
        monkeypatch.setattr(pipeline, "convert_to_mp3", _fake_convert)
        monkeypatch.setattr(pipeline, "fetch_metadata", lambda track: TrackMetadata())
        monkeypatch.setattr(pipeline, "tag_mp3", lambda path, meta: None)

        def report(progress: Progress) -> None:
            return None

        pipeline.build_mp3(
            _TRACK, _CANDIDATE, _settings(make_settings, tmp_path), on_progress=report
        )

        assert seen == [report]


class TestCleanup:
    def test_removes_the_work_dir(
        self, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings],
        tmp_path: Path,
    ) -> None:
        calls: list[str] = []
        _patch_steps(monkeypatch, calls, TrackMetadata())
        built = pipeline.build_mp3(_TRACK, _CANDIDATE, _settings(make_settings, tmp_path))
        work_dir = built.path.parent

        pipeline.cleanup(built)

        assert not work_dir.exists()


def _settings(
    make_settings: Callable[..., Settings], tmp_path: Path, **overrides: object
) -> Settings:
    values: dict[str, object] = {"data_dir": tmp_path / "data"}
    values.update(overrides)
    return make_settings(**values)


def _fake_download(
    url: str, dest_dir: Path, on_progress: object = None
) -> Path:
    return dest_dir / "audio.webm"


def _fake_convert(source: Path, bitrate: str, dest_dir: Path | None = None) -> Path:
    assert dest_dir is not None
    target = dest_dir / "audio.mp3"
    target.touch()
    return target


def _patch_steps(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], metadata: TrackMetadata
) -> None:
    def fake_download(
        url: str, dest_dir: Path, on_progress: object = None
    ) -> Path:
        calls.append("download")
        return dest_dir / "audio.webm"

    def fake_convert(source: Path, bitrate: str, dest_dir: Path | None = None) -> Path:
        calls.append("convert")
        assert dest_dir is not None
        target = dest_dir / "audio.mp3"
        target.touch()
        return target

    def fake_fetch(track: Track) -> TrackMetadata:
        calls.append("metadata")
        return metadata

    def fake_tag(path: Path, meta: TrackMetadata) -> None:
        calls.append("tag")

    monkeypatch.setattr(pipeline, "download_audio", fake_download)
    monkeypatch.setattr(pipeline, "convert_to_mp3", fake_convert)
    monkeypatch.setattr(pipeline, "fetch_metadata", fake_fetch)
    monkeypatch.setattr(pipeline, "tag_mp3", fake_tag)
