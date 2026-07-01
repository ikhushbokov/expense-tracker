"""Turns parsed text into a bot reply, decoupled from *how* it gets sent.

``build_response`` is shared by the live message handler (handlers/text.py)
and the queued-message retry job (handlers/retry.py) so both paths behave
identically -- the only difference is whether the reply goes out via
``message.reply_*`` or ``bot.send_*`` to a possibly-much-later chat.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from telegram import Bot, Message

from expense_ai.database import repository, session_scope
from expense_ai.finance import format_amount, get_balances, reconcile_balance
from expense_ai.handlers.edit_search import handle_delete, handle_edit, handle_export, handle_search
from expense_ai.handlers.queries import handle_query
from expense_ai.models.schemas import (
    ChartIntent,
    DeleteIntent,
    EditIntent,
    ExportIntent,
    QueryIntent,
    SearchIntent,
    SetBalanceIntent,
)
from expense_ai.parser import parse_message
from expense_ai.reports import CHART_GENERATORS

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


async def build_response(text: str) -> BotResponse:
    """Classify ``text`` and perform whatever DB action it implies.

    Raises ``expense_ai.llm.LLMError`` if the LLM itself is unreachable --
    the caller decides what to do about that (see handlers/text.py and
    handlers/retry.py), since it means nothing was understood or stored.
    """
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
        with session_scope() as session:
            delta = reconcile_balance(
                session, total_amount=intent.total_amount, currency=intent.currency, note=intent.breakdown
            )
        if delta == 0:
            text_reply = f"That already matches what I have on record: {format_amount(intent.total_amount, intent.currency)}."
        else:
            verb = "Added" if delta > 0 else "Subtracted"
            text_reply = (
                f"\U0001F4CC Balance updated to {format_amount(intent.total_amount, intent.currency)}\n"
                f"({verb} an adjustment of {format_amount(abs(delta), intent.currency)}"
                f"{f' — {intent.breakdown}' if intent.breakdown else ''})"
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
        await message.reply_text(prefix + (response.text or ""))


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
        await bot.send_message(chat_id=chat_id, text=prefix + (response.text or ""))
