"""Periodic job: retries messages queued while the LLM was unreachable.

Runs on a timer (see bot.py) rather than only at startup, since the LLM
can go down and come back at any point while the bot itself keeps running.
"""

from __future__ import annotations

import logging

from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.database.models import PendingMessage
from expense_ai.handlers.balance_sync import build_sync_mismatch_response
from expense_ai.handlers.dispatch import build_response, send_response_via_bot
from expense_ai.llm import LLMError

logger = logging.getLogger(__name__)

RETRIED_PREFIX = "\U0001F501 (processed after AI reconnected)\n\n"


async def retry_pending_messages(context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        pending = repository.list_pending_messages(session)

    if not pending:
        return

    for item in pending:
        if item.kind == "balance_sync":
            await _retry_balance_sync(context, item)
        else:
            await _retry_text(context, item)


async def _retry_text(context: ContextTypes.DEFAULT_TYPE, item: PendingMessage) -> None:
    try:
        response = await build_response(item.text)
    except LLMError:
        with session_scope() as session:
            repository.increment_pending_attempts(session, item.id)
        logger.info("LLM still unreachable, message %s stays queued (attempt %d)", item.id, item.attempts + 1)
        return
    except Exception:
        logger.exception("Unexpected error retrying queued message %s, leaving it queued", item.id)
        return

    # Drop it from the queue now, before sending: build_response already
    # wrote to the DB (e.g. inserted the expense), so retrying it again
    # next tick on a send failure would record it twice. A rare failed
    # notification is a better trade-off than a duplicated entry.
    with session_scope() as session:
        repository.delete_pending_message(session, item.id)

    try:
        await send_response_via_bot(context.bot, item.chat_id, response, prefix=RETRIED_PREFIX)
        logger.info("Delivered queued message %s after LLM reconnect", item.id)
    except Exception:
        logger.exception("Processed queued message %s but failed to deliver the reply", item.id)


async def _retry_balance_sync(context: ContextTypes.DEFAULT_TYPE, item: PendingMessage) -> None:
    """Same as _retry_text, but for a queued cards-screenshot sync: nothing
    gets written to the DB here (build_sync_mismatch_response only computes
    the mismatch and the confirm-buttons text), so unlike _retry_text it's
    safe -- and better -- to delete the pending item only *after* a
    successful send, so a delivery failure retries next tick instead of
    silently losing the prompt."""
    try:
        text, markup = await build_sync_mismatch_response(item.text)
    except LLMError:
        with session_scope() as session:
            repository.increment_pending_attempts(session, item.id)
        logger.info("LLM still unreachable, sync %s stays queued (attempt %d)", item.id, item.attempts + 1)
        return
    except Exception:
        logger.exception("Unexpected error retrying queued sync %s, leaving it queued", item.id)
        return

    try:
        await context.bot.send_message(chat_id=item.chat_id, text=RETRIED_PREFIX + text, reply_markup=markup)
        with session_scope() as session:
            repository.delete_pending_message(session, item.id)
        logger.info("Delivered queued sync-mismatch prompt %s after LLM reconnect", item.id)
    except Exception:
        logger.exception("Processed queued sync %s but failed to deliver the reply; will retry next tick", item.id)
