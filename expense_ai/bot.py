"""Application entrypoint: builds the Telegram bot and starts polling."""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from expense_ai.config import settings
from expense_ai.database import init_db
from expense_ai.handlers.backup import send_db_backup
from expense_ai.handlers.commands import (
    BOT_COMMANDS,
    handle_biggest_command,
    handle_budget_command,
    handle_chart_command,
    handle_dashboard_command,
    handle_debts_command,
    handle_help,
    handle_history_command,
    handle_income_command,
    handle_month_command,
    handle_savings_command,
    handle_start,
    handle_today_command,
    handle_total_command,
    handle_week_command,
)
from expense_ai.handlers.debts import handle_debt_settle_callback
from expense_ai.handlers.history import handle_history_callback
from expense_ai.handlers.income import handle_income_callback
from expense_ai.handlers.photo import handle_photo
from expense_ai.handlers.retry import retry_pending_messages
from expense_ai.handlers.scheduled import send_daily_summary, send_month_end_summary, send_monthly_reconciliation_prompt
from expense_ai.handlers.summary import handle_month_summary_callback, handle_week_summary_callback
from expense_ai.handlers.text import handle_text
from expense_ai.logging_setup import setup_logging

logger = logging.getLogger(__name__)


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update %s", update, exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Something went wrong on my end. Your data is safe — please try again."
        )


async def _post_init(application: Application) -> None:
    """Register the quick-command menu with Telegram (replaces any prior list)."""
    await application.bot.set_my_commands(BOT_COMMANDS)
    logger.info("Registered %d bot commands", len(BOT_COMMANDS))


def build_application() -> Application:
    application = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).build()

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("today", handle_today_command))
    application.add_handler(CommandHandler("week", handle_week_command))
    application.add_handler(CommandHandler("month", handle_month_command))
    application.add_handler(CommandHandler("budget", handle_budget_command))
    application.add_handler(CommandHandler("savings", handle_savings_command))
    application.add_handler(CommandHandler("total", handle_total_command))
    application.add_handler(CommandHandler("debts", handle_debts_command))
    application.add_handler(CommandHandler("biggest", handle_biggest_command))
    application.add_handler(CommandHandler("chart", handle_chart_command))
    application.add_handler(CommandHandler("dashboard", handle_dashboard_command))
    application.add_handler(CommandHandler("history", handle_history_command))
    application.add_handler(CommandHandler("income", handle_income_command))
    application.add_handler(CallbackQueryHandler(handle_history_callback, pattern=r"^hist:"))
    application.add_handler(CallbackQueryHandler(handle_income_callback, pattern=r"^income:"))
    application.add_handler(CallbackQueryHandler(handle_month_summary_callback, pattern=r"^summary_month:"))
    application.add_handler(CallbackQueryHandler(handle_week_summary_callback, pattern=r"^summary_week:"))
    application.add_handler(CallbackQueryHandler(handle_debt_settle_callback, pattern=r"^debt_settle:"))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(handle_error)

    application.job_queue.run_repeating(
        retry_pending_messages,
        interval=settings.retry_queue_interval_seconds,
        first=10,
        name="retry_pending_messages",
    )

    tzinfo = ZoneInfo(settings.timezone)
    application.job_queue.run_daily(
        send_daily_summary,
        time=dt.time(hour=settings.daily_summary_hour, tzinfo=tzinfo),
        name="daily_summary",
    )
    application.job_queue.run_monthly(
        send_month_end_summary,
        when=dt.time(hour=settings.daily_summary_hour, tzinfo=tzinfo),
        day=-1,
        name="month_end_summary",
    )
    application.job_queue.run_monthly(
        send_monthly_reconciliation_prompt,
        when=dt.time(hour=settings.reconciliation_hour, tzinfo=tzinfo),
        day=1,
        name="monthly_reconciliation",
    )
    application.job_queue.run_repeating(
        send_db_backup,
        interval=settings.backup_interval_hours * 3600,
        first=300,
        name="db_backup",
    )

    return application


def _apply_timezone() -> None:
    """Make every ``dt.datetime.now()`` call across the app (storage,
    /today-/week boundaries, history log dates, chart labels...) reflect
    ``settings.timezone`` instead of the process's default system clock --
    which, in Docker, is UTC regardless of the host machine's timezone."""
    os.environ["TZ"] = settings.timezone
    if hasattr(time, "tzset"):  # not available on Windows
        time.tzset()
    logger.info("Using timezone %s", settings.timezone)


def main() -> None:
    setup_logging()
    _apply_timezone()
    logger.info("Initializing database at %s", settings.database_full_path)
    init_db()

    application = build_application()
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
