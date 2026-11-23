"""Tests for the delivered filename template."""

from __future__ import annotations

from app.core import naming
from app.core.metadata import TrackMetadata
from app.core.models import Track

_TEMPLATE = "{artist} - {title}"
_FALLBACK = "dQw4w9WgXcQ"


def _render(
    template: str = _TEMPLATE,
    metadata: TrackMetadata | None = None,
    track: Track | None = None,
    fallback: str = _FALLBACK,
) -> str:
    return naming.render_filename(
        template,
        metadata if metadata is not None else TrackMetadata(),
        track if track is not None else Track(title=""),
        fallback,
    )


def test_renders_artist_and_title_from_metadata() -> None:
    metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")

    assert _render(metadata=metadata) == "Daft Punk - Instant Crush"


def test_falls_back_to_track_when_metadata_is_missing() -> None:
    track = Track(title="Instant Crush", artist="Daft Punk")

    assert _render(metadata=TrackMetadata(), track=track) == "Daft Punk - Instant Crush"


def test_metadata_takes_precedence_over_track() -> None:
    metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")
    track = Track(title="505", artist="Arctic Monkeys")

    assert _render(metadata=metadata, track=track) == "Daft Punk - Instant Crush"


def test_supports_album_and_year_tokens() -> None:
    metadata = TrackMetadata(
        title="Instant Crush",
        artist="Daft Punk",
        album="Random Access Memories",
        date="2013-05-17",
    )
    template = "{artist} - {album} ({year})"

    assert _render(template, metadata) == "Daft Punk - Random Access Memories (2013)"


def test_year_accepts_a_year_only_date() -> None:
    metadata = TrackMetadata(title="T", artist="A", date="1997")

    assert _render("{year}", metadata) == "1997"


def test_empty_token_does_not_leave_a_dangling_separator() -> None:
    metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")
    template = "{artist} - {album} - {title}"

    assert _render(template, metadata) == "Daft Punk - Instant Crush"


def test_unknown_token_expands_to_empty() -> None:
    metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")

    assert _render("{artist} {bogus} {title}", metadata) == "Daft Punk Instant Crush"


def test_removes_characters_that_are_unsafe_in_filenames() -> None:
    metadata = TrackMetadata(title="Back in Black?", artist="AC/DC")

    assert _render(metadata=metadata) == "ACDC - Back in Black"


def test_empty_template_uses_the_fallback() -> None:
    metadata = TrackMetadata(title="Instant Crush", artist="Daft Punk")

    assert _render("", metadata) == _FALLBACK


def test_template_that_renders_to_nothing_uses_the_fallback() -> None:
    assert _render("{artist} - {title}") == _FALLBACK


def test_caps_the_length() -> None:
    metadata = TrackMetadata(title="A" * 300, artist="B")

    assert len(_render("{title}", metadata)) == naming._MAX_LENGTH
