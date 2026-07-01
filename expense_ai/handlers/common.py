"""Shared helpers for Telegram handlers: auth guard and message formatting."""

from __future__ import annotations

import functools
import logging
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.config import settings

logger = logging.getLogger(__name__)

HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def restrict_to_owner(handler: HandlerFunc) -> HandlerFunc:
    """Reject updates from anyone but ``TELEGRAM_ALLOWED_USER_ID`` (if set)."""

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if settings.telegram_allowed_user_id is not None:
            user = update.effective_user
            if user is None or user.id != settings.telegram_allowed_user_id:
                logger.warning("Rejected message from unauthorized user %s", user.id if user else "unknown")
                if update.effective_message is not None:
                    await update.effective_message.reply_text("This bot is private.")
                return
        await handler(update, context)

    return wrapper
