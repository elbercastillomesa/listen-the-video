"""Tests for the YouTube search and download module."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import youtube
from app.core.models import Track


class TestBuildQuery:
    def test_combines_artist_and_title(self) -> None:
        track = Track(title="Instant Crush", artist="Daft Punk")

        assert youtube.build_query(track) == "Daft Punk Instant Crush"

    def test_uses_title_when_artist_is_missing(self) -> None:
        assert youtube.build_query(Track(title="Instant Crush")) == "Instant Crush"

    def test_ignores_blank_parts(self) -> None:
        assert youtube.build_query(Track(title="  Song  ", artist="   ")) == "Song"


class TestSearch:
    def test_returns_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = {
            "entries": [
                {
                    "id": "abc",
                    "title": "Instant Crush",
                    "uploader": "Daft Punk",
                    "duration": 336.0,
                },
                {"id": "def", "title": "Instant Crush (Live)", "channel": "Daft Punk"},
            ]
        }
        _patch_youtube(monkeypatch, result)

        candidates = youtube.search("Daft Punk Instant Crush")

        assert len(candidates) == 2
        assert candidates[0].title == "Instant Crush"
        assert candidates[0].artist == "Daft Punk"
        assert candidates[0].duration == 336
        assert candidates[0].url == "https://www.youtube.com/watch?v=abc"
        assert candidates[1].artist == "Daft Punk"

    def test_builds_search_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[_FakeYoutubeDL] = []
        _patch_youtube(monkeypatch, {"entries": []}, captured)

        youtube.search("Daft Punk Instant Crush", limit=3)

        assert captured[0].extract_url == "ytsearch3:Daft Punk Instant Crush"

    def test_returns_empty_list_when_there_are_no_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_youtube(monkeypatch, {"entries": []})

        assert youtube.search("nothing") == []

    def test_returns_empty_list_for_blank_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_youtube(monkeypatch, {"entries": [{"id": "abc", "title": "X"}]})

        assert youtube.search("   ") == []

    def test_skips_entries_without_title_or_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = {"entries": [{"id": "abc"}, {"title": "No URL here"}]}
        _patch_youtube(monkeypatch, result)

        assert youtube.search("query") == []

    def test_keeps_full_url_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = {
            "entries": [
                {"title": "Song", "url": "https://www.youtube.com/watch?v=abc"}
            ]
        }
        _patch_youtube(monkeypatch, result)

        candidates = youtube.search("query")

        assert candidates[0].url == "https://www.youtube.com/watch?v=abc"

    def test_expands_bare_video_id_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = {"entries": [{"title": "Song", "url": "abc"}]}
        _patch_youtube(monkeypatch, result)

        candidates = youtube.search("query")

        assert candidates[0].url == "https://www.youtube.com/watch?v=abc"


class TestDownloadAudio:
    def test_returns_downloaded_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        expected = tmp_path / "abc.webm"
        _patch_youtube(monkeypatch, {"id": "abc", "_filename": str(expected)})

        path = youtube.download_audio("https://youtu.be/abc", tmp_path)

        assert path == expected

    def test_requests_best_audio_format(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured: list[_FakeYoutubeDL] = []
        _patch_youtube(
            monkeypatch,
            {"id": "abc", "_filename": str(tmp_path / "abc.webm")},
            captured,
        )

        youtube.download_audio("https://youtu.be/abc", tmp_path)

        assert captured[0].options["format"] == "bestaudio/best"
        assert captured[0].download is True

    def test_creates_destination_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        destination = tmp_path / "nested"
        _patch_youtube(
            monkeypatch, {"id": "abc", "_filename": str(destination / "abc.webm")}
        )

        youtube.download_audio("https://youtu.be/abc", destination)

        assert destination.is_dir()

    def test_raises_when_download_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_youtube(monkeypatch, None)

        with pytest.raises(RuntimeError):
            youtube.download_audio("https://youtu.be/abc", tmp_path)


class _FakeYoutubeDL:
    def __init__(self, options: dict, result: dict | None) -> None:
        self.options = options
        self.extract_url: str | None = None
        self.download = False
        self._result = result

    def __enter__(self) -> "_FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> dict | None:
        self.extract_url = url
        self.download = download
        return self._result

    def prepare_filename(self, info: dict) -> str:
        return info["_filename"]


def _patch_youtube(
    monkeypatch: pytest.MonkeyPatch,
    result: dict | None,
    captured: list[_FakeYoutubeDL] | None = None,
) -> None:
    def factory(options: dict) -> _FakeYoutubeDL:
        ydl = _FakeYoutubeDL(options, result)
        if captured is not None:
            captured.append(ydl)
        return ydl

    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", factory)
