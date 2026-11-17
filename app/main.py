"""Entry point for the Telegram bot."""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot.

    The actual Telegram polling logic is added in phase 2. For now this only
    validates the configuration and prepares the working directory.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Configuration loaded. Data directory: %s", settings.data_dir)
    logger.info("Bot startup logic will be implemented in phase 2.")


if __name__ == "__main__":
    main()
