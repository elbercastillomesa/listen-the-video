"""Tests for the metadata fetcher."""

from __future__ import annotations

import musicbrainzngs
import pytest

from app.core import metadata
from app.core.models import Track

_TRACK = Track(title="Instant Crush", artist="Daft Punk")

_STUDIO_RECORDING = {
    "title": "Instant Crush",
    "artist-credit-phrase": "Daft Punk",
    "tag-list": [{"name": "electronic", "count": 2}],
    "release-list": [
        {
            "id": "live-1",
            "title": "Live 2014",
            "date": "2014",
            "release-group": {
                "primary-type": "Album",
                "secondary-type-list": ["Live"],
            },
        },
        {
            "id": "rel-1",
            "title": "Random Access Memories",
            "date": "2013-05-17",
            "release-group": {"primary-type": "Album"},
        },
    ],
}


def _deezer_item(**overrides: object) -> dict:
    item = {
        "title": "Instant Crush",
        "artist": {"name": "Daft Punk"},
        "album": {
            "id": 42,
            "title": "Random Access Memories",
            "cover_xl": "https://cdn.deezer.com/cover.jpg",
        },
        "release_date": None,
    }
    item.update(overrides)
    return item


def _deezer_album(**overrides: object) -> dict:
    album = {
        "title": "Random Access Memories",
        "release_date": "2013-05-17",
        "genres": {"data": [{"name": "Electronic"}]},
    }
    album.update(overrides)
    return album


def _release_group(**overrides: object) -> dict:
    group = {
        "id": "rg-1",
        "title": "Random Access Memories",
        "artist-credit-phrase": "Daft Punk",
        "primary-type": "Album",
        "first-release-date": "2013-05-17",
        "tag-list": [{"name": "electronic", "count": 5}],
    }
    group.update(overrides)
    return group


class TestFetchMetadata:
    def test_combines_deezer_album_with_musicbrainz_year_and_genre(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, groups=[_release_group()])
        _patch_deezer(monkeypatch, search=[_deezer_item()], album=_deezer_album())

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.title == "Instant Crush"
        assert meta.artist == "Daft Punk"
        assert meta.album == "Random Access Memories"
        assert meta.date == "2013"
        assert meta.genre == "electronic"
        assert meta.cover_url == "https://cdn.deezer.com/cover.jpg"

    def test_queries_deezer_with_plain_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_deezer(
            monkeypatch, search=[_deezer_item()], album=_deezer_album()
        )
        _patch_musicbrainz(monkeypatch, groups=[_release_group()])

        metadata.fetch_metadata(_TRACK)

        assert calls[0]["url"] == metadata.DEEZER_SEARCH_URL
        assert calls[0]["params"]["q"] == "Daft Punk Instant Crush"

    def test_skips_deezer_results_by_another_artist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wrong = _deezer_item(
            artist={"name": "Auger"},
            album={"id": 7, "title": "Hard Pop Vol. 1", "cover_xl": "https://wrong"},
        )
        calls = _patch_deezer(
            monkeypatch, search=[wrong, _deezer_item()], album=_deezer_album()
        )
        _patch_musicbrainz(monkeypatch, groups=[_release_group()])

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.album == "Random Access Memories"
        assert meta.cover_url == "https://cdn.deezer.com/cover.jpg"
        assert calls[1]["url"] == metadata.DEEZER_ALBUM_URL.format(album_id=42)

    def test_uses_recording_when_deezer_has_no_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_deezer(monkeypatch, search=[])
        _patch_musicbrainz(
            monkeypatch, recordings={"recording-list": [_STUDIO_RECORDING]}
        )

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.album == "Random Access Memories"
        assert meta.date == "2013"
        assert meta.genre == "electronic"
        assert meta.cover_url == "https://coverartarchive.org/release/rel-1/front-500"

    def test_ignores_live_release_groups(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live = _release_group(
            id="rg-live",
            title="Instant Crush Live",
            **{"secondary-type-list": ["Live"]},
        )
        live["first-release-date"] = "2014"
        _patch_musicbrainz(monkeypatch, groups=[live, _release_group()])
        _patch_deezer(monkeypatch, search=[_deezer_item()], album=_deezer_album())

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.date == "2013"
        assert meta.album == "Random Access Memories"

    def test_ignores_release_groups_by_another_artist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        other = _release_group(
            id="rg-other",
            title="Random Access Memories",
            **{"artist-credit-phrase": "Another Band"},
        )
        other["first-release-date"] = "1999"
        _patch_musicbrainz(monkeypatch, groups=[other, _release_group()])
        _patch_deezer(monkeypatch, search=[_deezer_item()], album=_deezer_album())

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.date == "2013"

    def test_prefers_the_deezer_artist_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        track = Track(title="El Breve Espacio", artist="Mario Ortiz")
        group = _release_group(**{"artist-credit-phrase": "Mario"})
        _patch_musicbrainz(monkeypatch, groups=[group])
        _patch_deezer(
            monkeypatch,
            search=[_deezer_item(artist={"name": "Mario Ortiz"})],
            album=_deezer_album(),
        )

        meta = metadata.fetch_metadata(track)

        assert meta.artist == "Mario Ortiz"

    def test_ignores_deezer_results_whose_artist_only_contains_the_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        track = Track(title="Mario Ortiz", artist="El Breve Espacio")
        wrong = _deezer_item(
            artist={"name": "Breve"},
            album={
                "id": 7,
                "title": "Breve - Live at Plush",
                "cover_xl": "https://wrong",
            },
        )
        _patch_deezer(monkeypatch, search=[wrong], album=_deezer_album())
        _patch_musicbrainz(monkeypatch, recordings={"recording-list": []})

        meta = metadata.fetch_metadata(track)

        assert meta.album is None
        assert meta.cover_url is None

    def test_genre_uses_the_most_common_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        group = _release_group(
            **{"tag-list": [{"name": "rock", "count": 1}, {"name": "pop", "count": 9}]}
        )
        _patch_musicbrainz(monkeypatch, groups=[group])
        _patch_deezer(monkeypatch, search=[_deezer_item()], album=_deezer_album())

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.genre == "pop"

    def test_genre_handles_string_tag_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        group = _release_group(
            **{
                "tag-list": [
                    {"name": "rock", "count": "1"},
                    {"name": "pop", "count": "9"},
                ]
            }
        )
        _patch_musicbrainz(monkeypatch, groups=[group])
        _patch_deezer(monkeypatch, search=[_deezer_item()], album=_deezer_album())

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.genre == "pop"

    def test_handles_musicbrainz_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_musicbrainz(
            monkeypatch, error=musicbrainzngs.MusicBrainzError("down")
        )
        _patch_deezer(monkeypatch, search=[_deezer_item()], album=_deezer_album())

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.album == "Random Access Memories"
        assert meta.date == "2013"
        assert meta.genre == "Electronic"

    def test_handles_deezer_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_deezer(monkeypatch, error=metadata.requests.RequestException("down"))
        _patch_musicbrainz(
            monkeypatch, recordings={"recording-list": [_STUDIO_RECORDING]}
        )

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.album == "Random Access Memories"
        assert meta.date == "2013"
        assert meta.cover_url == "https://coverartarchive.org/release/rel-1/front-500"

    def test_returns_minimal_metadata_when_sources_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_deezer(monkeypatch, search=[])
        _patch_musicbrainz(monkeypatch, recordings={"recording-list": []})

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.title == "Instant Crush"
        assert meta.artist == "Daft Punk"
        assert meta.album is None
        assert meta.cover_url is None

    def test_defaults_artist_from_track(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_deezer(monkeypatch, search=[])
        _patch_musicbrainz(
            monkeypatch, recordings={"recording-list": [{"title": "Instant Crush"}]}
        )

        meta = metadata.fetch_metadata(_TRACK)

        assert meta.title == "Instant Crush"
        assert meta.artist == "Daft Punk"


class _FakeResponse:
    def __init__(self, json_data: dict) -> None:
        self._json = json_data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json


def _patch_deezer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    search: list[dict] | None = None,
    album: dict | None = None,
    error: Exception | None = None,
) -> list[dict]:
    calls: list[dict] = []

    def fake_get(url: str, params: dict, **_kwargs: object) -> _FakeResponse:
        calls.append({"url": url, "params": params})
        if error is not None:
            raise error
        if "/album/" in url:
            return _FakeResponse(album or {})
        return _FakeResponse({"data": search or []})

    monkeypatch.setattr(metadata.requests, "get", fake_get)
    return calls


def _patch_musicbrainz(
    monkeypatch: pytest.MonkeyPatch,
    *,
    groups: list[dict] | None = None,
    recordings: dict | None = None,
    error: Exception | None = None,
) -> None:
    def fake_groups(**_kwargs: object) -> dict:
        if error is not None:
            raise error
        return {"release-group-list": groups or []}

    def fake_recordings(**_kwargs: object) -> dict:
        if error is not None:
            raise error
        return recordings or {"recording-list": []}

    monkeypatch.setattr(metadata.musicbrainzngs, "search_release_groups", fake_groups)
    monkeypatch.setattr(metadata.musicbrainzngs, "search_recordings", fake_recordings)
