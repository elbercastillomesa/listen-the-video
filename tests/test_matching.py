"""Tests for the artist/title identity resolver."""

from __future__ import annotations

import musicbrainzngs
import pytest
import requests

from app.core import matching
from app.core.models import Source


class TestNormalize:
    def test_strips_accents_case_and_punctuation(self) -> None:
        assert matching.normalize("Lázaro, Suplika-Dopamina!") == "lazaro suplika dopamina"

    def test_collapses_whitespace(self) -> None:
        assert matching.normalize("  El   Breve  ") == "el breve"

    def test_handles_missing_text(self) -> None:
        assert matching.normalize(None) == ""


class TestSimilarity:
    def test_exact_match_scores_one(self) -> None:
        assert matching.similarity("Instant Crush", "instant crush") == 1.0

    def test_ignores_accents(self) -> None:
        assert matching.similarity("Lázaro", "lazaro") == 1.0

    def test_containment_scores_high(self) -> None:
        assert matching.similarity("lazaro", "Lazaro Suplika Dopamina") == pytest.approx(
            0.85
        )

    def test_partial_token_overlap_scores_low(self) -> None:
        assert matching.similarity("Mario Ortiz", "Mario Bros") == pytest.approx(0.3)

    def test_unrelated_names_score_zero(self) -> None:
        assert matching.similarity("Daft Punk", "Arctic Monkeys") == 0.0

    def test_empty_values_score_zero(self) -> None:
        assert matching.similarity("", "anything") == 0.0


class TestCompare:
    def test_confirms_a_candidate_in_the_typed_order(self) -> None:
        straight, swapped = matching.compare(
            "Daft Punk", "Instant Crush", "Daft Punk", "Instant Crush"
        )

        assert straight == 2.0
        assert swapped == 0.0

    def test_flags_an_inverted_candidate(self) -> None:
        straight, swapped = matching.compare(
            "el breve espacio", "mario ortiz", "Mario Ortiz", "El Breve Espacio"
        )

        assert straight == 0.0
        assert swapped == 2.0

    def test_scores_a_wrong_candidate_below_the_threshold(self) -> None:
        straight, swapped = matching.compare(
            "El Breve Espacio", "Mario Ortiz", "Breve", "Vieux telegraph"
        )

        assert max(straight, swapped) < matching.IDENTITY_THRESHOLD


class TestIdentify:
    def test_finds_the_track_when_the_order_is_inverted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(
            monkeypatch,
            recordings=[
                {"title": "El Breve Espacio", "artist-credit-phrase": "Mario Ortiz"}
            ],
        )
        _patch_deezer(monkeypatch, search=[])

        track = matching.identify("el breve espacio", "mario ortiz")

        assert track is not None
        assert track.artist == "Mario Ortiz"
        assert track.title == "El Breve Espacio"
        assert track.source is Source.TEXT

    def test_keeps_the_order_when_the_candidate_confirms_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(
            monkeypatch,
            recordings=[
                {
                    "title": "Instant Crush (Lewis Lastella edit)",
                    "artist-credit-phrase": "Daft Punk",
                }
            ],
        )
        _patch_deezer(monkeypatch, search=[])

        assert matching.identify("Daft Punk", "Instant Crush") is None

    def test_probes_musicbrainz_in_both_orientations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_musicbrainz(monkeypatch, recordings=[])
        _patch_deezer(monkeypatch, search=[])

        matching.identify("puchito", "lazaro suplika dopamina")

        assert calls[0]["recording"] == "lazaro suplika dopamina"
        assert calls[0]["artist"] == "puchito"
        assert calls[1]["recording"] == "puchito"
        assert calls[1]["artist"] == "lazaro suplika dopamina"

    def test_queries_deezer_with_both_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, recordings=[])
        calls = _patch_deezer(monkeypatch, search=[])

        matching.identify("Daft Punk", "Instant Crush")

        assert calls[0]["url"] == matching.DEEZER_SEARCH_URL
        assert calls[0]["params"]["q"] == "Daft Punk Instant Crush"

    def test_uses_deezer_when_musicbrainz_has_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(monkeypatch, recordings=[])
        _patch_deezer(
            monkeypatch,
            search=[{"title": "Puchito", "artist": {"name": "Lázaro"}}],
        )

        track = matching.identify("puchito", "lazaro suplika dopamina")

        assert track is not None
        assert track.artist == "Lázaro"
        assert track.title == "Puchito"

    def test_returns_none_when_nothing_is_confident(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(
            monkeypatch,
            recordings=[{"title": "Something Else", "artist-credit-phrase": "Nobody"}],
        )
        _patch_deezer(
            monkeypatch, search=[{"title": "Unrelated", "artist": {"name": "Someone"}}]
        )

        assert matching.identify("Daft Punk", "Instant Crush") is None

    def test_skips_candidates_without_a_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(
            monkeypatch, recordings=[{"artist-credit-phrase": "Mario Ortiz"}]
        )
        _patch_deezer(monkeypatch, search=[])

        assert matching.identify("mario ortiz", "el breve espacio") is None

    def test_tolerates_a_musicbrainz_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_musicbrainz(
            monkeypatch, error=musicbrainzngs.MusicBrainzError("down")
        )
        _patch_deezer(
            monkeypatch,
            search=[{"title": "Puchito", "artist": {"name": "Lázaro"}}],
        )

        track = matching.identify("puchito", "lazaro suplika dopamina")

        assert track is not None
        assert track.title == "Puchito"

    def test_tolerates_a_deezer_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_musicbrainz(
            monkeypatch,
            recordings=[
                {"title": "El Breve Espacio", "artist-credit-phrase": "Mario Ortiz"}
            ],
        )
        _patch_deezer(monkeypatch, error=requests.RequestException("down"))

        track = matching.identify("el breve espacio", "mario ortiz")

        assert track is not None
        assert track.artist == "Mario Ortiz"


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _patch_musicbrainz(
    monkeypatch: pytest.MonkeyPatch,
    *,
    recordings: list[dict] | None = None,
    error: Exception | None = None,
) -> list[dict]:
    calls: list[dict] = []

    def fake_recordings(**kwargs: object) -> dict:
        calls.append(kwargs)
        if error is not None:
            raise error
        return {"recording-list": recordings or []}

    monkeypatch.setattr(matching.musicbrainzngs, "search_recordings", fake_recordings)
    return calls


def _patch_deezer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    search: list[dict] | None = None,
    error: Exception | None = None,
) -> list[dict]:
    calls: list[dict] = []

    def fake_get(url: str, params: dict, **_kwargs: object) -> _FakeResponse:
        calls.append({"url": url, "params": params})
        if error is not None:
            raise error
        return _FakeResponse({"data": search or []})

    monkeypatch.setattr(matching.requests, "get", fake_get)
    return calls
