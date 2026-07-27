"""Telegram slash-commands, including the quick-access command menu.

These bypass the LLM entirely -- they're direct DB queries via
finance.py/reports.py, so they're instant and don't depend on the LLM
provider being reachable.
"""

from __future__ import annotations

import datetime as dt

from telegram import BotCommand, Update
from telegram.ext import ContextTypes

from expense_ai.dashboard import generate_dashboard_html
from expense_ai.database import session_scope
from expense_ai.finance import (
    biggest_expenses,
    build_monthly_summary,
    build_summary_for_range,
    format_amount,
    get_balances,
    get_net_worth,
    month_over_month_insights,
    no_spend_streak_days,
    render_savings_goal_lines,
    render_summary,
)
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.handlers.debts import open_debts_keyboard, render_open_debts_text
from expense_ai.history import day_keyboard, render_day_text
from expense_ai.income import render_month_income_text
from expense_ai.keyboards import month_nav_keyboard, week_nav_keyboard
from expense_ai.periods import month_range, week_range, week_start
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
    "/today — today's spending summary\n"
    "/week, /month — spending summaries (◀/▶ to page weeks/months)\n"
    "/income — this month's income (◀/▶ to page months)\n"
    "/budget — current balance\n"
    "/savings — money set aside for goals\n"
    "/total — balance + savings combined\n"
    "/debts — open loans (lent/borrowed), tap to settle\n"
    "/biggest — biggest expenses\n"
    "/chart — spending pie chart\n"
    "/dashboard — offline HTML dashboard (balances, trends, loans, goals)\n"
    "/history — day-by-day transaction log (◀/▶ to page through days)\n"
    "/sync — sync tracked balance from a cards/accounts screenshot\n\n"
    "You can also send a photo of a receipt and I'll read it automatically, "
    "or a screenshot of your cards/accounts captioned \"sync\" to reconcile your balance.\n"
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
    BotCommand("income", "This month's income"),
    BotCommand("budget", "Current balance"),
    BotCommand("savings", "Money set aside for goals"),
    BotCommand("total", "Balance + savings combined"),
    BotCommand("debts", "Open loans (lent/borrowed)"),
    BotCommand("biggest", "Biggest expenses"),
    BotCommand("chart", "Spending pie chart (this month)"),
    BotCommand("dashboard", "Offline HTML dashboard"),
    BotCommand("history", "Day-by-day transaction log"),
    BotCommand("sync", "Sync tracked balance from a cards screenshot"),
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
        streak = no_spend_streak_days(session)
    text = render_summary(summary)
    if streak > 0:
        text += f"\n\n\U0001F525 {streak}-day no-spend streak!"
    await update.effective_message.reply_text(text)


@restrict_to_owner
async def handle_week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    monday = week_start(dt.date.today())
    start, end = week_range(monday)
    with session_scope() as session:
        summary = build_summary_for_range(session, start=start, end=end, label=f"Week of {monday.strftime('%b %d, %Y')}")
    await update.effective_message.reply_text(
        render_summary(summary), reply_markup=week_nav_keyboard("summary_week", monday)
    )


@restrict_to_owner
async def handle_month_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = dt.date.today()
    start, end = month_range(today.year, today.month)
    with session_scope() as session:
        summary = build_summary_for_range(session, start=start, end=end, label=today.strftime("%B %Y"))
        insights = month_over_month_insights(session, year=today.year, month=today.month)
    text = render_summary(summary)
    if insights:
        text += "\n\nCompared to last month\n" + "\n".join(insights)
    await update.effective_message.reply_text(
        text, reply_markup=month_nav_keyboard("summary_month", today.year, today.month)
    )


@restrict_to_owner
async def handle_income_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = dt.date.today()
    with session_scope() as session:
        text = render_month_income_text(session, today.year, today.month)
    await update.effective_message.reply_text(
        text, reply_markup=month_nav_keyboard("income", today.year, today.month)
    )


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
        goal_lines = render_savings_goal_lines(session)
    if not balances:
        text = "You have no savings recorded yet."
    else:
        text = "\U0001F416 Savings:\n" + "\n".join(format_amount(v, c) for c, v in balances.items())
    if goal_lines:
        text += "\n\n" + "\n".join(goal_lines)
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
async def handle_dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        path = generate_dashboard_html(session)
    with path.open("rb") as f:
        await update.effective_message.reply_document(
            document=f, filename=path.name, caption="\U0001F4CA Your expense dashboard — open in any browser."
        )


@restrict_to_owner
async def handle_debts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with session_scope() as session:
        text = render_open_debts_text(session)
        markup = open_debts_keyboard(session)
    await update.effective_message.reply_text(text, reply_markup=markup)


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
