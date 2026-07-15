"""Pagination for the /income month-by-month log (see expense_ai/income.py)."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.database import session_scope
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.income import render_month_income_text
from expense_ai.keyboards import month_nav_keyboard


@restrict_to_owner
async def handle_income_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    year_str, month_str = query.data.removeprefix("income:").split("-")
    year, month = int(year_str), int(month_str)
    with session_scope() as session:
        text = render_month_income_text(session, year, month)
    await query.edit_message_text(text, reply_markup=month_nav_keyboard("income", year, month))
