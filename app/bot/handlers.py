"""Telegram command and message handlers."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.config import Settings, get_settings
from app.core.models import Track
from app.core.resolver import resolve_input

logger = logging.getLogger(__name__)

WELCOME_TEXT = (
    "Hi! I'm listen-the-video.\n\n"
    "Send me a song name or a YouTube/Spotify link and I'll fetch the MP3 "
    "and attach its metadata.\n\n"
    "The download pipeline is not wired up yet, so for now I can only "
    "acknowledge your input. Use /help to see the available commands."
)

HELP_TEXT = (
    "How to use me:\n"
    "- Send a song name, for example: Daft Punk - Instant Crush\n"
    "- Or send a YouTube link\n"
    "- Or send a Spotify link (used as a metadata reference)\n\n"
    "Commands:\n"
    "/start - show the welcome message\n"
    "/help - show this help\n"
    "/id - show your Telegram user id\n\n"
    "Note: the download/conversion pipeline is implemented in upcoming phases."
)

PRIVATE_BOT_TEXT = "Sorry, this bot is private."


def _is_authorized(update: Update, settings: Settings) -> bool:
    """Return True if the sender is allowed to use the bot.

    When ALLOWED_USER_ID is not set, the bot is open to anyone.
    """
    if settings.allowed_user_id is None:
        return True

    user = update.effective_user
    return user is not None and user.id == settings.allowed_user_id


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not _is_authorized(update, get_settings()):
        await update.message.reply_text(PRIVATE_BOT_TEXT)
        return

    await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    if not _is_authorized(update, get_settings()):
        await update.message.reply_text(PRIVATE_BOT_TEXT)
        return

    await update.message.reply_text(HELP_TEXT)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /id command, useful to configure ALLOWED_USER_ID."""
    user = update.effective_user
    if user is None:
        return

    await update.message.reply_text(f"Your Telegram user id is: {user.id}")


def _format_track(track: Track) -> str:
    lines = [f"Title: {track.title}"]
    if track.artist:
        lines.append(f"Artist: {track.artist}")
    lines.append(f"Source: {track.source.value}")
    lines.append("")
    lines.append("The download pipeline is not wired up yet (coming in the next phases).")
    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a plain text message.

    Resolves the input (song name, YouTube link or Spotify link) into a
    canonical track. The download, conversion and tagging steps are
    implemented in later phases.
    """
    if not _is_authorized(update, get_settings()):
        await update.message.reply_text(PRIVATE_BOT_TEXT)
        return

    text = (update.message.text or "").strip()
    logger.info("Received message from user %s: %s", update.effective_user.id, text)

    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        # The resolver performs blocking network calls; keep them off the loop.
        track = await asyncio.to_thread(resolve_input, text)
    except Exception:
        logger.exception("Failed to resolve input: %s", text)
        await update.message.reply_text(
            "I could not resolve that input. "
            "Try a song name or a YouTube/Spotify link."
        )
        return

    await update.message.reply_text(_format_track(track))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and notify the user when possible."""
    logger.error("Unhandled exception while processing an update", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Something went wrong while processing your request. Please try again."
        )
