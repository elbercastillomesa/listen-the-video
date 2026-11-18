"""Entry point for the Telegram bot."""

from __future__ import annotations

import logging

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot import handlers
from app.config import get_settings

logger = logging.getLogger(__name__)


def build_application() -> Application:
    """Build and configure the Telegram application with its handlers."""
    settings = get_settings()

    application = ApplicationBuilder().token(settings.telegram_bot_token).build()

    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("id", handlers.id_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message)
    )
    application.add_handler(
        CallbackQueryHandler(handlers.handle_callback, pattern=r"^pick:")
    )
    application.add_error_handler(handlers.error_handler)

    return application


def main() -> None:
    """Start the bot and begin polling for updates."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs request URLs at INFO, which would expose the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    application = build_application()

    logger.info("Starting bot polling.")
    application.run_polling()


if __name__ == "__main__":
    main()
