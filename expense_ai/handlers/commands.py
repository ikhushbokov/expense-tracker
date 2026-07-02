"""Telegram slash-commands, including the quick-access command menu.

These bypass the LLM entirely -- they're direct DB queries via
finance.py/reports.py, so they're instant and don't depend on the LLM
provider being reachable.
"""

from __future__ import annotations

import datetime as dt

from telegram import BotCommand, Update
from telegram.ext import ContextTypes

from expense_ai.database import session_scope
from expense_ai.finance import (
    biggest_expenses,
    build_monthly_summary,
    format_amount,
    get_balances,
    get_net_worth,
    render_summary,
)
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.history import day_keyboard, render_day_text
from expense_ai.reports import category_pie_chart

WELCOME_MESSAGE = (
    "\U0001F44B Hi! I'm your personal finance assistant.\n\n"
    "Just talk to me naturally, for example:\n"
    "• \"Spent 85,000 on groceries\"\n"
    "• \"Salary came today: 6,500,000\"\n"
    "• \"How much did I spend this month?\"\n"
    "• \"Undo the last expense\"\n"
    "• \"Transfer 200,000 from balance to savings\"\n\n"
    "Or use the quick commands:\n"
    "/today, /week, /month — spending summaries\n"
    "/budget — current balance\n"
    "/savings — money set aside for goals\n"
    "/total — balance + savings combined\n"
    "/biggest — biggest expenses\n"
    "/chart — spending pie chart\n"
    "/history — day-by-day transaction log (◀/▶ to page through days)\n\n"
    "You can also send a photo of a receipt and I'll read it automatically.\n"
    "Type /help any time to see this again."
)

# Registered with Telegram via set_my_commands() in bot.py -- this is the
# single source of truth for the bot's command menu (the list shown when
# tapping "Menu" in the chat). Order here is the order Telegram displays.
BOT_COMMANDS: list[BotCommand] = [
    BotCommand("start", "Show welcome message"),
    BotCommand("today", "Today's spending summary"),
    BotCommand("week", "This week's spending summary"),
    BotCommand("month", "This month's spending summary"),
    BotCommand("budget", "Current balance"),
    BotCommand("savings", "Money set aside for goals"),
    BotCommand("total", "Balance + savings combined"),
    BotCommand("biggest", "Biggest expenses"),
    BotCommand("chart", "Spending pie chart (this month)"),
    BotCommand("history", "Day-by-day transaction log"),
    BotCommand("help", "Show usage help"),
]


@restrict_to_owner
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(WELCOME_MESSAGE)


@restrict_to_owner
async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(WELCOME_MESSAGE)


@restrict_to_owner
async def handle_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        summary = build_monthly_summary(session, period="today", label="Today")
    await update.effective_message.reply_text(render_summary(summary))


@restrict_to_owner
async def handle_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        summary = build_monthly_summary(session, period="this_week", label="This Week")
    await update.effective_message.reply_text(render_summary(summary))


@restrict_to_owner
async def handle_month_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        summary = build_monthly_summary(session, period="this_month", label="This Month")
    await update.effective_message.reply_text(render_summary(summary))


@restrict_to_owner
async def handle_budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        balances = get_balances(session, account="balance")
    if not balances:
        text = "You have no recorded income or expenses yet."
    else:
        text = "\U0001F4B0 Current balance:\n" + "\n".join(format_amount(v, c) for c, v in balances.items())
    await update.effective_message.reply_text(text)


@restrict_to_owner
async def handle_savings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        balances = get_balances(session, account="savings")
    if not balances:
        text = "You have no savings recorded yet."
    else:
        text = "\U0001F416 Savings:\n" + "\n".join(format_amount(v, c) for c, v in balances.items())
    await update.effective_message.reply_text(text)


@restrict_to_owner
async def handle_total_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        balances = get_net_worth(session)
    if not balances:
        text = "You have no recorded balance or savings yet."
    else:
        text = "\U0001F9EE Total (balance + savings):\n" + "\n".join(format_amount(v, c) for c, v in balances.items())
    await update.effective_message.reply_text(text)


@restrict_to_owner
async def handle_biggest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        top = biggest_expenses(session, limit=5)
    if not top:
        text = "No expenses recorded yet."
    else:
        lines = ["Biggest expenses (all time):"]
        for e in top:
            lines.append(f"{format_amount(e.amount, e.currency)} — {e.category} ({e.description or 'no description'})")
        text = "\n".join(lines)
    await update.effective_message.reply_text(text)


@restrict_to_owner
async def handle_chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        path = category_pie_chart(session, period="this_month")
    if path is None:
        await update.effective_message.reply_text("Not enough data yet to draw that chart.")
    else:
        with path.open("rb") as f:
            await update.effective_message.reply_photo(photo=f)


@restrict_to_owner
async def handle_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    day = dt.date.today()
    if context.args:
        try:
            day = dt.date.fromisoformat(context.args[0])
        except ValueError:
            await update.effective_message.reply_text("Use a date like /history 2026-06-15.")
            return
    with session_scope() as session:
        text = render_day_text(session, day)
    await update.effective_message.reply_text(text, reply_markup=day_keyboard(day))
