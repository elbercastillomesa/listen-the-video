"""Tests for the inline keyboards."""

from __future__ import annotations

from app.bot import keyboards
from app.core.models import Candidate


class TestBuildCandidatesKeyboard:
    def test_creates_one_button_per_candidate(self) -> None:
        candidates = [
            Candidate(title="First", url="u1"),
            Candidate(title="Second", url="u2"),
        ]

        keyboard = keyboards.build_candidates_keyboard(candidates)

        assert len(keyboard.inline_keyboard) == 2
        assert keyboard.inline_keyboard[0][0].callback_data == "pick:0"
        assert keyboard.inline_keyboard[1][0].callback_data == "pick:1"

    def test_label_includes_duration(self) -> None:
        candidates = [Candidate(title="Song", url="u1", duration=215)]

        keyboard = keyboards.build_candidates_keyboard(candidates)

        assert keyboard.inline_keyboard[0][0].text == "Song (3:35)"

    def test_formats_long_durations_with_hours(self) -> None:
        candidates = [Candidate(title="Mix", url="u1", duration=3725)]

        keyboard = keyboards.build_candidates_keyboard(candidates)

        assert keyboard.inline_keyboard[0][0].text == "Mix (1:02:05)"

    def test_omits_duration_when_missing(self) -> None:
        candidates = [Candidate(title="Song", url="u1")]

        keyboard = keyboards.build_candidates_keyboard(candidates)

        assert keyboard.inline_keyboard[0][0].text == "Song"

    def test_truncates_long_titles(self) -> None:
        candidates = [Candidate(title="x" * 200, url="u1")]

        keyboard = keyboards.build_candidates_keyboard(candidates)

        label = keyboard.inline_keyboard[0][0].text
        assert len(label) == keyboards._MAX_LABEL_LENGTH
        assert label.endswith("…")

    def test_handles_no_candidates(self) -> None:
        keyboard = keyboards.build_candidates_keyboard([])

        assert list(keyboard.inline_keyboard) == []


class TestParsePickCallback:
    def test_parses_index(self) -> None:
        assert keyboards.parse_pick_callback("pick:2") == 2

    def test_rejects_other_prefix(self) -> None:
        assert keyboards.parse_pick_callback("other:2") is None

    def test_rejects_non_numeric_index(self) -> None:
        assert keyboards.parse_pick_callback("pick:abc") is None

    def test_rejects_empty_data(self) -> None:
        assert keyboards.parse_pick_callback("") is None
