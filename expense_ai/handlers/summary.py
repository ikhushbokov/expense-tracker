"""Pagination for the /month and /week spending-summary cards."""

from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.database import session_scope
from expense_ai.finance import build_summary_for_range, month_over_month_insights, render_summary
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.keyboards import month_nav_keyboard, week_nav_keyboard
from expense_ai.periods import month_range, week_range


@restrict_to_owner
async def handle_month_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    year_str, month_str = query.data.removeprefix("summary_month:").split("-")
    year, month = int(year_str), int(month_str)
    start, end = month_range(year, month)
    label = start.strftime("%B %Y")
    with session_scope() as session:
        summary = build_summary_for_range(session, start=start, end=end, label=label)
        insights = month_over_month_insights(session, year=year, month=month)
    text = render_summary(summary)
    if insights:
        text += "\n\nCompared to last month\n" + "\n".join(insights)
    await query.edit_message_text(text, reply_markup=month_nav_keyboard("summary_month", year, month))


@restrict_to_owner
async def handle_week_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    monday = dt.date.fromisoformat(query.data.removeprefix("summary_week:"))
    start, end = week_range(monday)
    label = f"Week of {monday.strftime('%b %d, %Y')}"
    with session_scope() as session:
        summary = build_summary_for_range(session, start=start, end=end, label=label)
    await query.edit_message_text(render_summary(summary), reply_markup=week_nav_keyboard("summary_week", monday))
