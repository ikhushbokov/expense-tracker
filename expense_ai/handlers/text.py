"""Routes incoming text messages: classify, act, reply -- or queue for later
if the LLM is unreachable."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.handlers.dispatch import build_response, send_response_via_message
from expense_ai.llm import LLMError

logger = logging.getLogger(__name__)

UNREACHABLE_MESSAGE = (
    "\U0001F916⚠️ I can't reach the AI right now (it's down or unreachable). "
    "I've saved your message and will process it automatically as soon as it's back, "
    "then report back here."
)


@restrict_to_owner
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    # Local import: balance_sync imports UNREACHABLE_MESSAGE from this
    # module, so a top-level import back here would be circular.
    from expense_ai.handlers.balance_sync import SYNC_PENDING_WINDOW_SECONDS, handle_missed_transaction_description

    with session_scope() as session:
        pending_missed = repository.pop_pending_missed_transaction(
            session, chat_id=message.chat_id, max_age_seconds=SYNC_PENDING_WINDOW_SECONDS
        )
    if pending_missed is not None:
        await handle_missed_transaction_description(
            message, pending_missed.kind, pending_missed.amount, pending_missed.currency, text
        )
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")

    try:
        response = await build_response(text)
    except LLMError as exc:
        logger.warning("LLM unreachable, queuing message %r: %s", text, exc)
        with session_scope() as session:
            repository.enqueue_pending_message(session, chat_id=message.chat_id, text=text)
        await message.reply_text(UNREACHABLE_MESSAGE)
        return

    await send_response_via_message(message, response)
