"""Periodic job: retries messages queued while the LLM was unreachable.

Runs on a timer (see bot.py) rather than only at startup, since the LLM
can go down and come back at any point while the bot itself keeps running.
"""

from __future__ import annotations

import logging

from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
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
        try:
            response = await build_response(item.text)
        except LLMError:
            with session_scope() as session:
                repository.increment_pending_attempts(session, item.id)
            logger.info("LLM still unreachable, message %s stays queued (attempt %d)", item.id, item.attempts + 1)
            continue
        except Exception:
            logger.exception("Unexpected error retrying queued message %s, leaving it queued", item.id)
            continue

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
