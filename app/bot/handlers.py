"""Telegram command and message handlers."""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

from requests import RequestException
from telegram import Message, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from yt_dlp.utils import DownloadError

from app.bot.keyboards import build_candidates_keyboard, parse_pick_callback
from app.config import Settings, get_settings
from app.core.converter import ConversionError
from app.core.models import Candidate, Track
from app.core.pipeline import build_mp3, cleanup
from app.core.resolver import resolve_input
from app.core.youtube import build_query, search

logger = logging.getLogger(__name__)

# Errors expected while resolving user input. Anything else bubbles up to the
# global error handler instead of being silently swallowed.
_RESOLVE_ERRORS = (RequestException, DownloadError, RuntimeError)
_SEARCH_ERRORS = (DownloadError, RuntimeError)
_DELIVERY_ERRORS = (
    DownloadError,
    ConversionError,
    RequestException,
    RuntimeError,
    OSError,
    TelegramError,
)

_CANDIDATES_KEY = "candidates"
_TRACK_KEY = "track"

WELCOME_TEXT = (
    "Hi! I'm listen-the-video.\n\n"
    "Send me a song name or a YouTube/Spotify link. I'll search YouTube, show "
    "you the matches, and send back the MP3 with its metadata attached.\n\n"
    "Use /help to see the available commands."
)

HELP_TEXT = (
    "How to use me:\n"
    "- Send a song name, for example: Daft Punk - Instant Crush\n"
    "- Or send a YouTube link\n"
    "- Or send a Spotify link (used as a metadata reference)\n\n"
    "Pick a result with the buttons under my reply and I'll download, convert "
    "and tag the MP3 for you.\n\n"
    "Commands:\n"
    "/start - show the welcome message\n"
    "/help - show this help\n"
    "/id - show your Telegram user id\n\n"
    "Note: the public Telegram Bot API caps uploads at 50 MB."
)

PRIVATE_BOT_TEXT = "Sorry, this bot is private."
RESOLVE_FAILED_TEXT = (
    "I could not resolve that input. Try a song name or a YouTube/Spotify link."
)
SEARCH_FAILED_TEXT = "The YouTube search failed. Please try again."
NO_RESULTS_TEXT = "I could not find anything on YouTube for that."
EXPIRED_SELECTION_TEXT = (
    "That selection is no longer available. Send the song again for a fresh list."
)
PREPARING_TEXT = "Downloading, converting and tagging the MP3..."
BUILD_FAILED_TEXT = "I could not prepare that track. Please try another match."
SEND_FAILED_TEXT = "I could not send the MP3. Please try again."
TOO_LARGE_TEXT = "That MP3 is {size:.1f} MB, over the {limit} MB Telegram limit."


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


def _format_candidates_prompt(track: Track, candidates: list[Candidate]) -> str:
    """Format the message shown above the candidate buttons."""
    count = len(candidates)
    found = f"Found {count} matches" if count > 1 else "Found 1 match"

    lines = [f"{found} for {track.title}:", ""]
    for index, candidate in enumerate(candidates, start=1):
        lines.append(f"{index}. {candidate.title}")
    lines.append("")
    lines.append("Pick one below.")
    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve the input, search YouTube and offer the matches as buttons."""
    if not _is_authorized(update, get_settings()):
        await update.message.reply_text(PRIVATE_BOT_TEXT)
        return

    text = (update.message.text or "").strip()
    logger.info("Received message from user %s: %s", update.effective_user.id, text)

    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        # The resolver performs blocking network calls; keep them off the loop.
        track = await asyncio.to_thread(resolve_input, text)
    except _RESOLVE_ERRORS:
        logger.exception("Failed to resolve input: %s", text)
        await update.message.reply_text(RESOLVE_FAILED_TEXT)
        return

    query = build_query(track)
    try:
        candidates = await asyncio.to_thread(search, query)
    except _SEARCH_ERRORS:
        logger.exception("YouTube search failed for query: %s", query)
        await update.message.reply_text(SEARCH_FAILED_TEXT)
        return

    if not candidates:
        await update.message.reply_text(NO_RESULTS_TEXT)
        return

    context.user_data[_TRACK_KEY] = track
    context.user_data[_CANDIDATES_KEY] = candidates
    await update.message.reply_text(
        _format_candidates_prompt(track, candidates),
        reply_markup=build_candidates_keyboard(candidates),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the inline button the user presses to pick a search result."""
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    settings = get_settings()
    if not _is_authorized(update, settings):
        await query.message.reply_text(PRIVATE_BOT_TEXT)
        return

    state = context.user_data or {}
    track = state.get(_TRACK_KEY)
    candidates = state.get(_CANDIDATES_KEY) or []
    index = parse_pick_callback(query.data or "")

    if track is None or index is None or not 0 <= index < len(candidates):
        await query.message.reply_text(EXPIRED_SELECTION_TEXT)
        return

    candidate = candidates[index]
    logger.info("User %s selected %s", update.effective_user.id, candidate.url)

    # Editing the text also drops the inline keyboard.
    await query.edit_message_text(f"Selected: {candidate.title}")
    await _deliver_track(query.message, track, candidate, settings)


async def _deliver_track(
    message: Message, track: Track, candidate: Candidate, settings: Settings
) -> None:
    """Build the MP3 and send it back to the user."""
    status = await message.reply_text(PREPARING_TEXT)

    try:
        built = await asyncio.to_thread(build_mp3, track, candidate, settings)
    except _DELIVERY_ERRORS:
        logger.exception("Failed to build the MP3 for %s", candidate.url)
        await status.edit_text(BUILD_FAILED_TEXT)
        return

    try:
        size_mb = built.path.stat().st_size / (1024 * 1024)
        if size_mb > settings.max_upload_mb:
            await status.edit_text(
                TOO_LARGE_TEXT.format(size=size_mb, limit=settings.max_upload_mb)
            )
            return

        # Reading and uploading can take a while for a full-length track.
        data = await asyncio.to_thread(built.path.read_bytes)
        await message.reply_audio(
            audio=BytesIO(data),
            filename=built.path.name,
            title=built.metadata.title or track.title,
            performer=built.metadata.artist or track.artist,
        )
        await status.delete()
    except _DELIVERY_ERRORS:
        logger.exception("Failed to send the MP3 for %s", candidate.url)
        await status.edit_text(SEND_FAILED_TEXT)
    finally:
        cleanup(built)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and notify the user when possible."""
    logger.error("Unhandled exception while processing an update", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Something went wrong while processing your request. Please try again."
        )
