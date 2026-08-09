"""Turns parsed text into a bot reply, decoupled from *how* it gets sent.

``build_response`` is shared by the live message handler (handlers/text.py)
and the queued-message retry job (handlers/retry.py) so both paths behave
identically -- the only difference is whether the reply goes out via
``message.reply_*`` or ``bot.send_*`` to a possibly-much-later chat.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

from telegram import Bot, InlineKeyboardMarkup, Message

from expense_ai.database import repository, session_scope
from expense_ai.finance import format_amount, get_balances, reconcile_balance, savings_goal_progress, transfer_funds
from expense_ai.handlers.debts import handle_debt, handle_settle_debt
from expense_ai.handlers.edit_search import handle_delete, handle_edit, handle_export, handle_search
from expense_ai.handlers.queries import handle_query
from expense_ai.history import day_keyboard, render_day_text
from expense_ai.local_parser import try_parse_expense_locally
from expense_ai.models.schemas import (
    ChartIntent,
    DebtIntent,
    DeleteIntent,
    EditIntent,
    ExportIntent,
    HistoryIntent,
    QueryIntent,
    SavingsGoalIntent,
    SearchIntent,
    SetBalanceIntent,
    SettleDebtIntent,
    TransferIntent,
)
from expense_ai.parser import parse_message
from expense_ai.periods import resolve_period
from expense_ai.reports import CHART_GENERATORS

logger = logging.getLogger(__name__)

ACCOUNT_LABELS = {"balance": "Balance", "savings": "Savings"}

UNKNOWN_MESSAGE = (
    "I couldn't understand that as an expense, income entry, or question.\n"
    "Try something like:\n"
    "• \"Spent 85,000 on groceries\"\n"
    "• \"Salary came today: 6,500,000\"\n"
    "• \"How much did I spend this month?\""
)


@dataclass
class BotResponse:
    text: str | None = None
    photo_path: Path | None = None
    document_path: Path | None = None
    document_caption: str | None = None
    reply_markup: InlineKeyboardMarkup | None = None


async def build_response(text: str) -> BotResponse:
    """Classify ``text`` and perform whatever DB action it implies.

    Raises ``expense_ai.llm.LLMError`` if the LLM itself is unreachable --
    the caller decides what to do about that (see handlers/text.py and
    handlers/retry.py), since it means nothing was understood or stored.
    """
    with session_scope() as session:
        intent = try_parse_expense_locally(session, text)
    if intent is not None:
        logger.info("Handled locally (no LLM call): %r -> %s/%s %s", text, intent.amount, intent.currency, intent.category)
    else:
        intent = await parse_message(text)

    if intent.type == "expense":
        with session_scope() as session:
            expense = repository.add_expense(
                session,
                amount=intent.amount,
                currency=intent.currency,
                category=intent.category,
                description=intent.description,
                source="text",
            )
            session.flush()
            balance = get_balances(session).get(intent.currency, 0.0)
        return BotResponse(
            text=(
                "✅ Expense recorded\n\n"
                f"Amount: {format_amount(expense.amount, expense.currency)}\n"
                f"Category: {expense.category}\n"
                f"Description: {expense.description or '-'}\n\n"
                f"Current balance: {format_amount(balance, intent.currency)}"
            )
        )

    if intent.type == "income":
        with session_scope() as session:
            income = repository.add_income(
                session, amount=intent.amount, currency=intent.currency, description=intent.description
            )
            session.flush()
            balance = get_balances(session).get(intent.currency, 0.0)
        return BotResponse(
            text=(
                "\U0001F4B0 Income recorded\n\n"
                f"Amount: {format_amount(income.amount, income.currency)}\n"
                f"Description: {income.description or '-'}\n\n"
                f"Current balance: {format_amount(balance, intent.currency)}"
            )
        )

    if intent.type == "set_balance":
        assert isinstance(intent, SetBalanceIntent)
        label = ACCOUNT_LABELS[intent.account]
        with session_scope() as session:
            delta = reconcile_balance(
                session,
                total_amount=intent.total_amount,
                currency=intent.currency,
                account=intent.account,
                note=intent.breakdown,
            )
        if delta == 0:
            text_reply = f"{label} already matches what I have on record: {format_amount(intent.total_amount, intent.currency)}."
        else:
            verb = "Added" if delta > 0 else "Subtracted"
            text_reply = (
                f"\U0001F4CC {label} updated to {format_amount(intent.total_amount, intent.currency)}\n"
                f"({verb} an adjustment of {format_amount(abs(delta), intent.currency)}"
                f"{f' — {intent.breakdown}' if intent.breakdown else ''})\n"
                "(This is a correction, not counted as income or spending.)"
            )
        return BotResponse(text=text_reply)

    if intent.type == "transfer":
        assert isinstance(intent, TransferIntent)
        with session_scope() as session:
            transfer_funds(
                session,
                from_account=intent.from_account,
                to_account=intent.to_account,
                amount=intent.amount,
                currency=intent.currency,
                note=intent.note,
            )
            new_balances = {account: get_balances(session, account=account) for account in ("balance", "savings")}
        text_reply = (
            f"\U0001F501 Transferred {format_amount(intent.amount, intent.currency)} "
            f"from {ACCOUNT_LABELS[intent.from_account]} to {ACCOUNT_LABELS[intent.to_account]}\n\n"
            f"Balance: {format_amount(new_balances['balance'].get(intent.currency, 0.0), intent.currency)}\n"
            f"Savings: {format_amount(new_balances['savings'].get(intent.currency, 0.0), intent.currency)}"
        )
        return BotResponse(text=text_reply)

    if intent.type == "debt":
        assert isinstance(intent, DebtIntent)
        return BotResponse(text=handle_debt(intent))

    if intent.type == "settle_debt":
        assert isinstance(intent, SettleDebtIntent)
        return BotResponse(text=handle_settle_debt(intent))

    if intent.type == "savings_goal":
        assert isinstance(intent, SavingsGoalIntent)
        with session_scope() as session:
            goal = repository.upsert_savings_goal(
                session,
                name=intent.name,
                target_amount=intent.target_amount,
                currency=intent.currency,
                target_date=intent.target_date,
            )
            current, pct = savings_goal_progress(session, target_amount=goal.target_amount, currency=goal.currency)
        deadline = f" by {intent.target_date.strftime('%b %d, %Y')}" if intent.target_date else ""
        text_reply = (
            f"\U0001F3AF Goal set: {goal.name} — {format_amount(goal.target_amount, goal.currency)}{deadline}\n"
            f"Currently saved: {format_amount(current, goal.currency)} ({pct:.0f}%)"
        )
        return BotResponse(text=text_reply)

    if intent.type == "query":
        assert isinstance(intent, QueryIntent)
        return BotResponse(text=handle_query(intent))

    if intent.type == "edit":
        assert isinstance(intent, EditIntent)
        return BotResponse(text=handle_edit(intent))

    if intent.type == "delete":
        assert isinstance(intent, DeleteIntent)
        return BotResponse(text=handle_delete(intent))

    if intent.type == "search":
        assert isinstance(intent, SearchIntent)
        return BotResponse(text=handle_search(intent))

    if intent.type == "export":
        assert isinstance(intent, ExportIntent)
        caption, file_path = handle_export(intent)
        if file_path is None:
            return BotResponse(text=caption)
        return BotResponse(document_path=file_path, document_caption=caption)

    if intent.type == "history":
        assert isinstance(intent, HistoryIntent)
        if intent.custom_date is not None:
            day = intent.custom_date
        else:
            start, _ = resolve_period(intent.period)
            day = (start or dt.datetime.now()).date()
        with session_scope() as session:
            text = render_day_text(session, day)
        return BotResponse(text=text, reply_markup=day_keyboard(day))

    if intent.type == "chart":
        assert isinstance(intent, ChartIntent)
        with session_scope() as session:
            generator = CHART_GENERATORS[intent.chart_type]
            chart_path = generator(session, period=intent.period)
        if chart_path is None:
            return BotResponse(text="Not enough data yet to draw that chart.")
        return BotResponse(photo_path=chart_path)

    return BotResponse(text=UNKNOWN_MESSAGE)


async def send_response_via_message(message: Message, response: BotResponse, *, prefix: str = "") -> None:
    if response.photo_path is not None:
        with response.photo_path.open("rb") as f:
            await message.reply_photo(photo=f, caption=prefix or None)
    elif response.document_path is not None:
        with response.document_path.open("rb") as f:
            await message.reply_document(
                document=f, filename=response.document_path.name, caption=prefix + (response.document_caption or "")
            )
    else:
        await message.reply_text(prefix + (response.text or ""), reply_markup=response.reply_markup)


async def send_response_via_bot(bot: Bot, chat_id: int, response: BotResponse, *, prefix: str = "") -> None:
    if response.photo_path is not None:
        with response.photo_path.open("rb") as f:
            await bot.send_photo(chat_id=chat_id, photo=f, caption=prefix or None)
    elif response.document_path is not None:
        with response.document_path.open("rb") as f:
            await bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=response.document_path.name,
                caption=prefix + (response.document_caption or ""),
            )
    else:
        await bot.send_message(chat_id=chat_id, text=prefix + (response.text or ""), reply_markup=response.reply_markup)
