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

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.finance import coerce_category, format_amount, get_balances, known_categories, reconcile_balance, transfer_funds
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.handlers.edit_search import handle_delete, handle_edit, handle_export, handle_search
from expense_ai.handlers.queries import handle_query
from expense_ai.history import day_keyboard, render_day_text
from expense_ai.local_parser import try_parse_locally
from expense_ai.models.schemas import (
    ChartIntent,
    DeleteIntent,
    EditIntent,
    ExportIntent,
    HistoryIntent,
    QueryIntent,
    SearchIntent,
    SetBalanceIntent,
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


def _category_keyboard(expense_id: int, categories: list[str]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for category in categories:
        row.append(InlineKeyboardButton(category, callback_data=f"recat:{expense_id}:{category}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


@restrict_to_owner
async def handle_recategorize_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the one-tap category fix attached to an expense logged
    with category_confirmed=False (see build_response's "expense" branch)
    -- the no-LLM alternative to asking the LLM to guess a category for
    vocabulary local_parser.py hasn't seen before."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    _, expense_id_str, category = query.data.split(":", 2)
    with session_scope() as session:
        expense = repository.update_expense(session, int(expense_id_str), category=category)
        if expense is None:
            await query.edit_message_text("That expense no longer exists.")
            return
        balance = get_balances(session).get(expense.currency, 0.0)

    await query.edit_message_text(
        "✅ Expense recorded\n\n"
        f"Amount: {format_amount(expense.amount, expense.currency)}\n"
        f"Category: {expense.category}\n"
        f"Description: {expense.description or '-'}\n\n"
        f"Current balance: {format_amount(balance, expense.currency)}"
    )


async def build_response(text: str) -> BotResponse:
    """Classify ``text`` and perform whatever DB action it implies.

    Raises ``expense_ai.llm.LLMError`` if the LLM itself is unreachable --
    the caller decides what to do about that (see handlers/text.py and
    handlers/retry.py), since it means nothing was understood or stored.
    """
    with session_scope() as session:
        intent = try_parse_locally(session, text)
    if intent is not None:
        logger.info("Handled locally (no LLM call): %r -> %r", text, intent)
    else:
        intent = await parse_message(text)

    if intent.type == "expense":
        with session_scope() as session:
            category = coerce_category(session, intent.category)
            expense = repository.add_expense(
                session,
                amount=intent.amount,
                currency=intent.currency,
                category=category,
                description=intent.description,
                source="text",
            )
            session.flush()
            balance = get_balances(session).get(intent.currency, 0.0)
            categories = known_categories(session) if not intent.category_confirmed else []
        text_reply = (
            "✅ Expense recorded\n\n"
            f"Amount: {format_amount(expense.amount, expense.currency)}\n"
            f"Category: {expense.category}\n"
            f"Description: {expense.description or '-'}\n\n"
            f"Current balance: {format_amount(balance, intent.currency)}"
        )
        markup = None
        if not intent.category_confirmed:
            # local_parser.py couldn't confidently resolve a category (new
            # vocabulary) -- logged as "Other" already rather than asking
            # the LLM to guess; one tap fixes it if that's wrong.
            text_reply += "\n\nNot sure about the category — tap to fix it:"
            markup = _category_keyboard(expense.id, categories)
        return BotResponse(text=text_reply, reply_markup=markup)

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
