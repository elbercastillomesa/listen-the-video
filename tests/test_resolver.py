"""Tests for the input resolver."""

from __future__ import annotations

import pytest

from app.core import resolver
from app.core.models import Source


class TestDetectSource:
    @pytest.mark.parametrize(
        "text",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        ],
    )
    def test_detects_youtube(self, text: str) -> None:
        assert resolver.detect_source(text) is Source.YOUTUBE

    @pytest.mark.parametrize(
        "text",
        [
            "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
            "https://open.spotify.com/intl-es/track/4cOdK2wGLETKBW3PvgPWqT",
            "https://open.spotify.com/album/4cOdK2wGLETKBW3PvgPWqT",
        ],
    )
    def test_detects_spotify(self, text: str) -> None:
        assert resolver.detect_source(text) is Source.SPOTIFY

    @pytest.mark.parametrize(
        "text",
        [
            "Daft Punk - Instant Crush",
            "https://example.com/song",
            "Just a song name",
        ],
    )
    def test_detects_plain_text(self, text: str) -> None:
        assert resolver.detect_source(text) is Source.TEXT


class TestResolveText:
    def test_splits_artist_and_title(self) -> None:
        track = resolver.resolve_text("Daft Punk - Instant Crush")

        assert track.title == "Instant Crush"
        assert track.artist == "Daft Punk"
        assert track.source is Source.TEXT

    def test_supports_en_dash_separator(self) -> None:
        track = resolver.resolve_text("Daft Punk – Instant Crush")

        assert track.artist == "Daft Punk"
        assert track.title == "Instant Crush"

    def test_title_only(self) -> None:
        track = resolver.resolve_text("Instant Crush")

        assert track.title == "Instant Crush"
        assert track.artist is None

    def test_strips_youtube_noise(self) -> None:
        track = resolver.resolve_text("Imagine Dragons - Believer (Official Music Video)")

        assert track.artist == "Imagine Dragons"
        assert track.title == "Believer"

    def test_keeps_hyphenated_words(self) -> None:
        track = resolver.resolve_text("Jay-Z")

        assert track.title == "Jay-Z"
        assert track.artist is None

    def test_keeps_bracketed_text_without_noise_keywords(self) -> None:
        track = resolver.resolve_text("Some Band - Some Song (Audiotree Live)")

        assert track.artist == "Some Band"
        assert track.title == "Some Song (Audiotree Live)"


class TestSplitArtistTitle:
    def test_returns_artist_and_title(self) -> None:
        artist, title = resolver.split_artist_title("Daft Punk - Instant Crush")

        assert artist == "Daft Punk"
        assert title == "Instant Crush"

    def test_returns_none_when_no_separator(self) -> None:
        artist, title = resolver.split_artist_title("Instant Crush")

        assert artist is None
        assert title == "Instant Crush"

    def test_strips_youtube_noise_before_splitting(self) -> None:
        artist, title = resolver.split_artist_title(
            "Arctic Monkeys - 505 (Official Audio)"
        )

        assert artist == "Arctic Monkeys"
        assert title == "505"


class TestResolveYoutube:
    def test_splits_artist_and_title_from_video_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        info = {
            "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
            "uploader": "Rick Astley",
        }
        _patch_youtube(monkeypatch, info)

        track = resolver.resolve_youtube("https://youtu.be/dQw4w9WgXcQ")

        assert track.title == "Never Gonna Give You Up"
        assert track.artist == "Rick Astley"
        assert track.source is Source.YOUTUBE
        assert track.source_url == "https://youtu.be/dQw4w9WgXcQ"

    def test_uses_uploader_and_strips_topic_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        info = {"title": "Instant Crush", "uploader": "Daft Punk - Topic"}
        _patch_youtube(monkeypatch, info)

        track = resolver.resolve_youtube("https://youtu.be/abc")

        assert track.title == "Instant Crush"
        assert track.artist == "Daft Punk"

    def test_prefers_explicit_artist_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        info = {"title": "Instant Crush", "artist": "Daft Punk", "uploader": "whatever"}
        _patch_youtube(monkeypatch, info)

        track = resolver.resolve_youtube("https://youtu.be/abc")

        assert track.artist == "Daft Punk"

    def test_handles_empty_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_youtube(monkeypatch, {})

        track = resolver.resolve_youtube("https://youtu.be/abc")

        assert track.title == ""
        assert track.artist is None
        assert track.source_url == "https://youtu.be/abc"


class TestResolveSpotify:
    def test_reads_open_graph_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        html = (
            '<meta property="og:title" content="Never Gonna Give You Up"/>'
            '<meta property="og:description" '
            'content="Rick Astley · Whenever You Need Somebody · Song · 1987"/>'
        )
        _patch_requests(monkeypatch, html)

        track = resolver.resolve_spotify("https://open.spotify.com/track/abc")

        assert track.title == "Never Gonna Give You Up"
        assert track.artist == "Rick Astley"
        assert track.source is Source.SPOTIFY

    def test_unescapes_html_entities(self, monkeypatch: pytest.MonkeyPatch) -> None:
        html = '<meta property="og:title" content="Rock &amp; Roll"/>'
        _patch_requests(monkeypatch, html)

        track = resolver.resolve_spotify("https://open.spotify.com/track/abc")

        assert track.title == "Rock & Roll"
        assert track.artist is None

    def test_raises_when_metadata_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_requests(monkeypatch, "<html><title>Spotify</title></html>")

        with pytest.raises(RuntimeError):
            resolver.resolve_spotify("https://open.spotify.com/track/abc")

    def test_ignores_attribute_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        html = '<meta content="Never Gonna Give You Up" property="og:title"/>'
        _patch_requests(monkeypatch, html)

        track = resolver.resolve_spotify("https://open.spotify.com/track/abc")

        assert track.title == "Never Gonna Give You Up"

    def test_ignores_description_without_separator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = (
            '<meta property="og:title" content="Some Song"/>'
            '<meta property="og:description" content="A chill playlist"/>'
        )
        _patch_requests(monkeypatch, html)

        track = resolver.resolve_spotify("https://open.spotify.com/track/abc")

        assert track.title == "Some Song"
        assert track.artist is None


class TestResolveInput:
    def test_dispatches_text(self) -> None:
        track = resolver.resolve_input("Daft Punk - Instant Crush")

        assert track.source is Source.TEXT

    def test_dispatches_youtube(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_youtube(monkeypatch, {"title": "Some Song", "uploader": "Someone"})

        track = resolver.resolve_input("https://youtu.be/abc")

        assert track.source is Source.YOUTUBE

    def test_dispatches_spotify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_requests(monkeypatch, '<meta property="og:title" content="Some Song"/>')

        track = resolver.resolve_input("https://open.spotify.com/track/abc")

        assert track.source is Source.SPOTIFY


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeYoutubeDL:
    def __init__(self, info: dict) -> None:
        self._info = info

    def __enter__(self) -> "_FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> dict:
        return self._info


def _patch_requests(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    monkeypatch.setattr(resolver.requests, "get", lambda *a, **k: _FakeResponse(html))


def _patch_youtube(monkeypatch: pytest.MonkeyPatch, info: dict) -> None:
    monkeypatch.setattr(
        resolver.yt_dlp, "YoutubeDL", lambda options: _FakeYoutubeDL(info)
    )
