"""Proactive scheduled messages the bot sends without being asked: an
evening spending recap, a month-end summary with month-over-month
insights, and a monthly balance/savings reconciliation nudge. Registered
as job_queue jobs in bot.py (run_daily/run_monthly), not triggered by user
messages, so each function sends directly via ``context.bot`` to the
owner's chat rather than replying to an update.
"""

from __future__ import annotations

import datetime as dt
import logging

from telegram.ext import ContextTypes

from expense_ai.config import settings
from expense_ai.database import session_scope
from expense_ai.finance import (
    build_monthly_summary,
    format_amount,
    get_balances,
    month_over_month_insights,
    no_spend_streak_days,
    render_summary,
)

logger = logging.getLogger(__name__)


async def _send_to_owner(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if settings.telegram_allowed_user_id is None:
        logger.warning("Skipping scheduled message: TELEGRAM_ALLOWED_USER_ID is not set")
        return
    await context.bot.send_message(chat_id=settings.telegram_allowed_user_id, text=text)


async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        summary = build_monthly_summary(session, period="today", label="Today")
        streak = no_spend_streak_days(session)
    text = render_summary(summary)
    if streak > 0:
        text += f"\n\n\U0001F525 {streak}-day no-spend streak!"
    await _send_to_owner(context, text)


async def send_month_end_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    today = dt.date.today()
    with session_scope() as session:
        summary = build_monthly_summary(session, period="this_month", label=today.strftime("%B %Y"))
        insights = month_over_month_insights(session, year=today.year, month=today.month)
    text = "\U0001F4C5 Your month wrapped up:\n\n" + render_summary(summary)
    if insights:
        text += "\n\nCompared to last month\n" + "\n".join(insights)
    await _send_to_owner(context, text)


async def send_monthly_reconciliation_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        balance = get_balances(session, account="balance")
        savings = get_balances(session, account="savings")

    lines = ["\U0001F4CC Monthly check-in — here's what I have on record:"]
    if balance:
        lines.append("Balance: " + ", ".join(format_amount(v, c) for c, v in balance.items()))
    if savings:
        lines.append("Savings: " + ", ".join(format_amount(v, c) for c, v in savings.items()))
    if not balance and not savings:
        lines.append("(nothing recorded yet)")
    lines.append("\nStill accurate? If not, just tell me your real numbers and I'll adjust.")
    await _send_to_owner(context, "\n".join(lines))
