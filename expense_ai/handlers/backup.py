"""Periodic off-host backup: sends a consistent copy of the SQLite DB to the
owner's own Telegram chat as a document -- a cheap, no-new-infra offsite
backup, since the bot already has a private 1:1 channel with its only user.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import tempfile
from pathlib import Path

from telegram.ext import ContextTypes

from expense_ai.config import settings

logger = logging.getLogger(__name__)


async def send_db_backup(context: ContextTypes.DEFAULT_TYPE) -> None:
    if settings.telegram_allowed_user_id is None:
        logger.warning("Skipping DB backup: TELEGRAM_ALLOWED_USER_ID is not set")
        return

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    with tempfile.TemporaryDirectory() as tmp_dir:
        backup_path = Path(tmp_dir) / f"expenses_backup_{timestamp}.db"

        # SQLite's own online backup API, not a plain file copy, so a
        # concurrent write from the running bot can't produce a torn/corrupt
        # copy of the file.
        source = sqlite3.connect(settings.database_full_path)
        try:
            dest = sqlite3.connect(backup_path)
            try:
                source.backup(dest)
            finally:
                dest.close()
        finally:
            source.close()

        with backup_path.open("rb") as f:
            await context.bot.send_document(
                chat_id=settings.telegram_allowed_user_id,
                document=f,
                filename=backup_path.name,
                caption=f"\U0001F4BE Automatic backup — {timestamp}",
            )
    logger.info("Sent automatic DB backup")
