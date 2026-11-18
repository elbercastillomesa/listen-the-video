"""Tests for the Telegram handlers."""

from __future__ import annotations

import asyncio
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

from telegram import Update

from app.bot import handlers
from app.config import Settings
from app.core.models import Source, Track


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


class TestFormatTrack:
    def test_includes_title_artist_and_source(self) -> None:
        track = Track(title="Instant Crush", artist="Daft Punk", source=Source.YOUTUBE)

        text = handlers._format_track(track)

        assert "Title: Instant Crush" in text
        assert "Artist: Daft Punk" in text
        assert "Source: youtube" in text

    def test_omits_artist_when_missing(self) -> None:
        track = Track(title="Unknown Song")

        text = handlers._format_track(track)

        assert "Title: Unknown Song" in text
        assert "Artist:" not in text


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
    def test_resolves_and_replies(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())
        track = Track(title="Instant Crush", artist="Daft Punk", source=Source.YOUTUBE)
        monkeypatch.setattr(handlers, "resolve_input", lambda text: track)
        update = _make_update(text="Daft Punk - Instant Crush")

        asyncio.run(handlers.handle_message(update, MagicMock()))

        (message,) = update.message.reply_text.await_args.args
        assert "Instant Crush" in message

    def test_reports_resolution_failure(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(handlers, "get_settings", lambda: make_settings())

        def _fail(text: str) -> Track:
            raise RuntimeError("resolution failed")

        monkeypatch.setattr(handlers, "resolve_input", _fail)
        update = _make_update(text="???")

        asyncio.run(handlers.handle_message(update, MagicMock()))

        (message,) = update.message.reply_text.await_args.args
        assert "could not resolve" in message

    def test_blocks_unauthorized_user(
        self, monkeypatch, make_settings: Callable[..., Settings]
    ) -> None:
        monkeypatch.setattr(
            handlers, "get_settings", lambda: make_settings(allowed_user_id=7)
        )
        update = _make_update(user_id=8)

        asyncio.run(handlers.handle_message(update, MagicMock()))

        update.message.reply_text.assert_awaited_once_with(handlers.PRIVATE_BOT_TEXT)


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
