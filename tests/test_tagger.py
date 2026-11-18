"""Tests for the ID3 tagger."""

from __future__ import annotations

from pathlib import Path

import pytest
from mutagen.id3 import APIC, ID3

from app.core import tagger
from app.core.metadata import TrackMetadata


class TestTagMp3:
    def test_writes_basic_tags(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path)
        extra = TrackMetadata(
            title="Song", artist="Band", album="Album", date="1987", genre="Pop"
        )

        tagger.tag_mp3(path, extra)

        tags = ID3(path)
        assert str(tags["TIT2"]) == "Song"
        assert str(tags["TPE1"]) == "Band"
        assert str(tags["TALB"]) == "Album"
        assert str(tags["TDRC"]) == "1987"
        assert str(tags["TCON"]) == "Pop"

    def test_skips_missing_fields(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path)

        tagger.tag_mp3(path, TrackMetadata(title="Song"))

        tags = ID3(path)
        assert str(tags["TIT2"]) == "Song"
        assert "TPE1" not in tags

    def test_embeds_cover_art(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _make_mp3(tmp_path)
        _patch_cover(monkeypatch, b"PNGDATA", "image/png")

        tagger.tag_mp3(path, TrackMetadata(title="Song", cover_url="https://cover/1"))

        images = ID3(path).getall("APIC")
        assert len(images) == 1
        assert images[0].mime == "image/png"
        assert images[0].data == b"PNGDATA"
        assert images[0].type == 3

    def test_ignores_cover_download_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _make_mp3(tmp_path)
        _patch_cover_error(monkeypatch)

        tagger.tag_mp3(path, TrackMetadata(title="Song", cover_url="https://cover/1"))

        tags = ID3(path)
        assert str(tags["TIT2"]) == "Song"
        assert tags.getall("APIC") == []

    def test_replaces_existing_cover(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _make_mp3(tmp_path)
        tags = ID3()
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="old", data=b"OLD"))
        tags.save(path, v2_version=3)
        _patch_cover(monkeypatch, b"NEW", "image/jpeg")

        tagger.tag_mp3(path, TrackMetadata(title="Song", cover_url="https://cover/1"))

        images = ID3(path).getall("APIC")
        assert len(images) == 1
        assert images[0].data == b"NEW"


def _make_mp3(tmp_path: Path) -> Path:
    path = tmp_path / "song.mp3"
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 512)
    return path


class _FakeResponse:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self) -> None:
        return None


def _patch_cover(
    monkeypatch: pytest.MonkeyPatch, content: bytes, content_type: str = "image/jpeg"
) -> None:
    monkeypatch.setattr(
        tagger.requests, "get", lambda *a, **k: _FakeResponse(content, content_type)
    )


def _patch_cover_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise tagger.requests.RequestException("nope")

    monkeypatch.setattr(tagger.requests, "get", _raise)
