"""Tests for the metadata fetcher."""

from __future__ import annotations

import musicbrainzngs
import pytest

from app.core import metadata
from app.core.models import Track

_MB_RECORDING = {
    "recording-list": [
        {
            "title": "Instant Crush",
            "artist-credit": [{"name": "Daft Punk"}],
            "tag-list": [{"name": "electronic"}],
            "release-list": [
                {
                    "id": "rel-1",
                    "title": "Random Access Memories",
                    "date": "2013-05-17",
                }
            ],
        }
    ]
}

_DEEZER_PAYLOAD = {
    "data": [
        {
            "title": "Instant Crush",
            "artist": {"name": "Daft Punk"},
            "album": {
                "title": "Random Access Memories",
                "cover_xl": "https://cdn.deezer.com/cover.jpg",
            },
            "release_date": "2013-05-17",
        }
    ]
}


class TestFetchMetadata:
    def test_prefers_musicbrainz_and_skips_deezer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, _MB_RECORDING)
        calls = _patch_deezer(monkeypatch, _DEEZER_PAYLOAD)

        meta = metadata.fetch_metadata(Track(title="Instant Crush", artist="Daft Punk"))

        assert meta.title == "Instant Crush"
        assert meta.artist == "Daft Punk"
        assert meta.album == "Random Access Memories"
        assert meta.date == "2013"
        assert meta.genre == "electronic"
        assert meta.cover_url == "https://coverartarchive.org/release/rel-1/front-500"
        assert calls == []

    def test_falls_back_to_deezer_when_musicbrainz_has_no_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, {"recording-list": []})
        _patch_deezer(monkeypatch, _DEEZER_PAYLOAD)

        meta = metadata.fetch_metadata(Track(title="Instant Crush", artist="Daft Punk"))

        assert meta.album == "Random Access Memories"
        assert meta.date == "2013"
        assert meta.cover_url == "https://cdn.deezer.com/cover.jpg"

    def test_fills_missing_cover_from_deezer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recording = {"recording-list": [{"title": "Instant Crush"}]}
        _patch_musicbrainz(monkeypatch, recording)
        _patch_deezer(monkeypatch, _DEEZER_PAYLOAD)

        meta = metadata.fetch_metadata(Track(title="Instant Crush", artist="Daft Punk"))

        assert meta.cover_url == "https://cdn.deezer.com/cover.jpg"
        assert meta.album == "Random Access Memories"

    def test_handles_musicbrainz_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_musicbrainz(monkeypatch, error=musicbrainzngs.MusicBrainzError("down"))
        _patch_deezer(monkeypatch, _DEEZER_PAYLOAD)

        meta = metadata.fetch_metadata(Track(title="Instant Crush", artist="Daft Punk"))

        assert meta.album == "Random Access Memories"

    def test_returns_minimal_metadata_when_sources_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, {"recording-list": []})
        _patch_deezer(monkeypatch, {"data": []})

        meta = metadata.fetch_metadata(Track(title="Instant Crush", artist="Daft Punk"))

        assert meta.title == "Instant Crush"
        assert meta.artist == "Daft Punk"
        assert meta.album is None
        assert meta.cover_url is None

    def test_defaults_artist_from_track(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, {"recording-list": [{"title": "Instant Crush"}]})
        _patch_deezer(monkeypatch, {"data": []})

        meta = metadata.fetch_metadata(Track(title="Instant Crush", artist="Daft Punk"))

        assert meta.title == "Instant Crush"
        assert meta.artist == "Daft Punk"


class _FakeResponse:
    def __init__(self, json_data: dict) -> None:
        self._json = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json


def _patch_musicbrainz(
    monkeypatch: pytest.MonkeyPatch,
    result: dict | None = None,
    *,
    error: Exception | None = None,
) -> None:
    def fake_search(**kwargs: object) -> dict:
        if error is not None:
            raise error
        return result or {}

    monkeypatch.setattr(metadata.musicbrainzngs, "search_recordings", fake_search)


def _patch_deezer(
    monkeypatch: pytest.MonkeyPatch, payload: dict
) -> list[dict]:
    calls: list[dict] = []

    def fake_get(url: str, params: dict, timeout: int) -> _FakeResponse:
        calls.append({"url": url, "params": params})
        return _FakeResponse(payload)

    monkeypatch.setattr(metadata.requests, "get", fake_get)
    return calls
