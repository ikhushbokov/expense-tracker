"""Application entrypoint: builds the Telegram bot and starts polling."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from expense_ai.config import settings
from expense_ai.database import init_db
from expense_ai.handlers.commands import handle_help, handle_start
from expense_ai.handlers.photo import handle_photo
from expense_ai.handlers.text import handle_text
from expense_ai.logging_setup import setup_logging

logger = logging.getLogger(__name__)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Something went wrong on my end. Your data is safe — please try again."
        )


def build_application() -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()

    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/start"), handle_start))
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/help"), handle_help))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(handle_error)

    return application


def main() -> None:
    setup_logging()
    logger.info("Initializing database at %s", settings.database_full_path)
    init_db()

    application = build_application()
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
