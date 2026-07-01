"""Telegram slash-commands: /start and /help."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.handlers.common import restrict_to_owner

WELCOME_MESSAGE = (
    "\U0001F44B Hi! I'm your personal finance assistant.\n\n"
    "Just talk to me naturally, for example:\n"
    "• \"Spent 85,000 on groceries\"\n"
    "• \"Salary came today: 6,500,000\"\n"
    "• \"How much did I spend this month?\"\n"
    "• \"Show my biggest expenses\"\n"
    "• \"Undo the last expense\"\n\n"
    "You can also send a photo of a receipt and I'll read it automatically.\n"
    "Type /help any time to see this again."
)


@restrict_to_owner
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(WELCOME_MESSAGE)


@restrict_to_owner
async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(WELCOME_MESSAGE)
