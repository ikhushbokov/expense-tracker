"""Pagination for the /history day-by-day log (see expense_ai/history.py)."""

from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.database import session_scope
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.history import day_keyboard, render_day_text


@restrict_to_owner
async def handle_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    day = dt.date.fromisoformat(query.data.removeprefix("hist:"))
    with session_scope() as session:
        text = render_day_text(session, day)
    await query.edit_message_text(text, reply_markup=day_keyboard(day))
