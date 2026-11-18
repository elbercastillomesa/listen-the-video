"""Tests for the Telegram handlers."""

from __future__ import annotations

import asyncio
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

from telegram import Update
from yt_dlp.utils import DownloadError

from app.bot import handlers
from app.config import Settings
from app.core.models import Candidate, Source, Track


def _make_update(
    *, user_id: int | None = 1, text: str | None = "hello"
) -> MagicMock:
    """Build a fake Update with async reply helpers."""
    update = MagicMock()
    if user_id is None:
        update.effective_user = None
    else:
        update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_chat_action = AsyncMock()
    return update


def _make_context() -> MagicMock:
    """Build a fake context backed by a real user_data dict."""
    context = MagicMock()
    context.user_data = {}
    return context


def _make_callback_update(data: str | None = "pick:0") -> MagicMock:
    """Build a fake Update for a callback query."""
    update = MagicMock()
    update.effective_user.id = 1
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


class TestFormatCandidatesPrompt:
    def test_lists_candidates_with_numbers(self) -> None:
        track = Track(title="Instant Crush")
        candidates = [
            Candidate(title="First", url="u1"),
            Candidate(title="Second", url="u2"),
        ]

        text = handlers._format_candidates_prompt(track, candidates)

        assert "Found 2 matches for Instant Crush:" in text
        assert "1. First" in text
        assert "2. Second" in text

    def test_uses_singular_for_one_candidate(self) -> None:
        track = Track(title="Instant Crush")
        candidates = [Candidate(title="Only", url="u1")]

        text = handlers._format_candidates_prompt(track, candidates)

        assert "Found 1 match for" in text


class TestIsAuthorized:
    def test_open_when_no_allowed_user(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(allowed_user_id=None)

        assert handlers._is_authorized(MagicMock(), settings) is True

    def test_allows_matching_user(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(allowed_user_id=7)
        update = MagicMock()
        update.effective_user.id = 7

        assert handlers._is_authorized(update, settings) is True

    def test_blocks_other_user(self, make_settings: Callable[..., Settings]) -> None:
        settings = make_settings(allowed_user_id=7)
        update = MagicMock()
        update.effective_user.id = 8

        assert handlers._is_authorized(update, settings) is False

    def test_blocks_when_user_is_missing(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        settings = make_settings(allowed_user_id=7)
        update = MagicMock()
        update.effective_user = None

        assert handlers._is_authorized(update, settings) is False


class TestCommands:
    def test_start_sends_welcome(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())
        update = _make_update()

        asyncio.run(handlers.start_command(update, MagicMock()))

        update.message.reply_text.assert_awaited_once_with(handlers.WELCOME_TEXT)

    def test_start_blocks_unauthorized_user(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(
            handlers, "get_settings", lambda: make_settings(allowed_user_id=7)
        )
        update = _make_update(user_id=8)

        asyncio.run(handlers.start_command(update, MagicMock()))

        update.message.reply_text.assert_awaited_once_with(handlers.PRIVATE_BOT_TEXT)

    def test_help_sends_help_text(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())
        update = _make_update()

        asyncio.run(handlers.help_command(update, MagicMock()))

        update.message.reply_text.assert_awaited_once_with(handlers.HELP_TEXT)

    def test_id_sends_user_id(self) -> None:
        update = _make_update(user_id=42)

        asyncio.run(handlers.id_command(update, MagicMock()))

        (message,) = update.message.reply_text.await_args.args
        assert "42" in message

    def test_id_ignores_missing_user(self) -> None:
        update = _make_update(user_id=None)

        asyncio.run(handlers.id_command(update, MagicMock()))

        update.message.reply_text.assert_not_awaited()


class TestHandleMessage:
    def test_offers_candidates_as_buttons(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())
        track = Track(title="Instant Crush", artist="Daft Punk", source=Source.YOUTUBE)
        candidates = [
            Candidate(title="First", url="u1"),
            Candidate(title="Second", url="u2"),
        ]
        monkeypatch.setattr(handlers, "resolve_input", lambda text: track)
        monkeypatch.setattr(handlers, "search", lambda query: candidates)
        context = _make_context()
        update = _make_update(text="Daft Punk - Instant Crush")

        asyncio.run(handlers.handle_message(update, context))

        assert context.user_data["candidates"] == candidates
        (message,) = update.message.reply_text.await_args.args
        assert "1. First" in message
        keyboard = update.message.reply_text.await_args.kwargs["reply_markup"]
        assert len(keyboard.inline_keyboard) == 2

    def test_searches_with_artist_and_title(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())
        track = Track(title="Instant Crush", artist="Daft Punk")
        queries: list[str] = []

        def fake_search(query: str) -> list[Candidate]:
            queries.append(query)
            return [Candidate(title="First", url="u1")]

        monkeypatch.setattr(handlers, "resolve_input", lambda text: track)
        monkeypatch.setattr(handlers, "search", fake_search)
        update = _make_update()

        asyncio.run(handlers.handle_message(update, _make_context()))

        assert queries == ["Daft Punk Instant Crush"]

    def test_reports_no_results(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())
        track = Track(title="Instant Crush")
        monkeypatch.setattr(handlers, "resolve_input", lambda text: track)
        monkeypatch.setattr(handlers, "search", lambda query: [])
        context = _make_context()
        update = _make_update()

        asyncio.run(handlers.handle_message(update, context))

        update.message.reply_text.assert_awaited_once_with(handlers.NO_RESULTS_TEXT)
        assert context.user_data == {}

    def test_reports_search_failure(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())

        def _fail(query: str) -> list[Candidate]:
            raise DownloadError("search failed")

        monkeypatch.setattr(handlers, "resolve_input", lambda text: Track(title="Song"))
        monkeypatch.setattr(handlers, "search", _fail)
        update = _make_update()

        asyncio.run(handlers.handle_message(update, _make_context()))

        update.message.reply_text.assert_awaited_once_with(handlers.SEARCH_FAILED_TEXT)

    def test_reports_resolution_failure(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())

        def _fail(text: str) -> Track:
            raise RuntimeError("resolution failed")

        monkeypatch.setattr(handlers, "resolve_input", _fail)
        update = _make_update(text="???")

        asyncio.run(handlers.handle_message(update, _make_context()))

        (message,) = update.message.reply_text.await_args.args
        assert "could not resolve" in message

    def test_blocks_unauthorized_user(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(
            handlers, "get_settings", lambda: make_settings(allowed_user_id=7)
        )
        update = _make_update(user_id=8)

        asyncio.run(handlers.handle_message(update, _make_context()))

        update.message.reply_text.assert_awaited_once_with(handlers.PRIVATE_BOT_TEXT)


class TestHandleCallback:
    def test_stores_selection_and_confirms(self) -> None:
        candidates = [
            Candidate(title="First", url="u1"),
            Candidate(title="Second", url="u2"),
        ]
        context = _make_context()
        context.user_data["candidates"] = candidates
        update = _make_callback_update("pick:1")

        asyncio.run(handlers.handle_callback(update, context))

        assert context.user_data["selected"] == candidates[1]
        (message,) = update.callback_query.edit_message_text.await_args.args
        assert "Second" in message

    def test_answers_the_callback_query(self) -> None:
        context = _make_context()
        context.user_data["candidates"] = [Candidate(title="First", url="u1")]
        update = _make_callback_update("pick:0")

        asyncio.run(handlers.handle_callback(update, context))

        update.callback_query.answer.assert_awaited_once()

    def test_rejects_out_of_range_index(self) -> None:
        context = _make_context()
        context.user_data["candidates"] = [Candidate(title="First", url="u1")]
        update = _make_callback_update("pick:9")

        asyncio.run(handlers.handle_callback(update, context))

        update.callback_query.message.reply_text.assert_awaited_once_with(
            handlers.EXPIRED_SELECTION_TEXT
        )
        update.callback_query.edit_message_text.assert_not_awaited()

    def test_rejects_malformed_callback(self) -> None:
        context = _make_context()
        context.user_data["candidates"] = [Candidate(title="First", url="u1")]
        update = _make_callback_update("nonsense")

        asyncio.run(handlers.handle_callback(update, context))

        update.callback_query.message.reply_text.assert_awaited_once_with(
            handlers.EXPIRED_SELECTION_TEXT
        )

    def test_rejects_when_no_candidates_stored(self) -> None:
        update = _make_callback_update("pick:0")

        asyncio.run(handlers.handle_callback(update, _make_context()))

        update.callback_query.message.reply_text.assert_awaited_once_with(
            handlers.EXPIRED_SELECTION_TEXT
        )

    def test_ignores_missing_callback_query(self) -> None:
        update = MagicMock()
        update.callback_query = None

        asyncio.run(handlers.handle_callback(update, _make_context()))


class TestErrorHandler:
    def test_notifies_user(self) -> None:
        update = MagicMock(spec=Update)
        update.effective_message.reply_text = AsyncMock()
        context = MagicMock()
        context.error = ValueError("boom")

        asyncio.run(handlers.error_handler(update, context))

        update.effective_message.reply_text.assert_awaited_once()

    def test_ignores_non_update(self) -> None:
        context = MagicMock()
        context.error = ValueError("boom")

        asyncio.run(handlers.error_handler(None, context))
