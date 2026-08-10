"""Handles incoming photos.

Balance-sync screenshots are routed to handlers/balance_sync.py -- either
because the photo is captioned "sync" (is_sync_photo()), or because /sync
armed a "the next photo is the screenshot" marker for this chat
(pop_pending_sync(), consumed here either way so a later, unrelated photo
doesn't get mistaken for one).

Receipt OCR used to live here too (OCR -> LLM classification -> stored
expense) but was removed: unused in practice, since expenses are always
typed directly instead. Any photo that isn't a sync screenshot just gets
pointed back to typing the expense.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.handlers.balance_sync import SYNC_PENDING_WINDOW_SECONDS, handle_sync_photo, is_sync_photo
from expense_ai.handlers.common import restrict_to_owner

NOT_A_RECEIPT_MESSAGE = (
    "I only read photos for /sync (a screenshot of your card balances). "
    "For an expense, just tell me the amount and category directly, e.g. "
    "\"Spent 45,000 on groceries\"."
)


@restrict_to_owner
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return

    with session_scope() as session:
        pending_sync = repository.pop_pending_sync(
            session, chat_id=message.chat_id, max_age_seconds=SYNC_PENDING_WINDOW_SECONDS
        )
    if is_sync_photo(message.caption) or pending_sync:
        await handle_sync_photo(update, context)
        return

    await message.reply_text(NOT_A_RECEIPT_MESSAGE)
