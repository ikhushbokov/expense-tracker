"""Routes incoming text messages to the right intent handler."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.finance import format_amount, get_balances, reconcile_balance
from expense_ai.handlers.common import restrict_to_owner
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

logger = logging.getLogger(__name__)


@restrict_to_owner
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")
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
            balances = get_balances(session)
            balance_text = balances.get(intent.currency, 0.0)
        reply = (
            "✅ Expense recorded\n\n"
            f"Amount: {format_amount(expense.amount, expense.currency)}\n"
            f"Category: {expense.category}\n"
            f"Description: {expense.description or '-'}\n\n"
            f"Current balance: {format_amount(balance_text, intent.currency)}"
        )
        await message.reply_text(reply)

    elif intent.type == "income":
        with session_scope() as session:
            income = repository.add_income(
                session,
                amount=intent.amount,
                currency=intent.currency,
                description=intent.description,
            )
            session.flush()
            balances = get_balances(session)
            balance_text = balances.get(intent.currency, 0.0)
        reply = (
            "\U0001F4B0 Income recorded\n\n"
            f"Amount: {format_amount(income.amount, income.currency)}\n"
            f"Description: {income.description or '-'}\n\n"
            f"Current balance: {format_amount(balance_text, intent.currency)}"
        )
        await message.reply_text(reply)

    elif intent.type == "set_balance":
        assert isinstance(intent, SetBalanceIntent)
        with session_scope() as session:
            delta = reconcile_balance(
                session, total_amount=intent.total_amount, currency=intent.currency, note=intent.breakdown
            )
        if delta == 0:
            reply = f"That already matches what I have on record: {format_amount(intent.total_amount, intent.currency)}."
        else:
            verb = "Added" if delta > 0 else "Subtracted"
            reply = (
                f"\U0001F4CC Balance updated to {format_amount(intent.total_amount, intent.currency)}\n"
                f"({verb} an adjustment of {format_amount(abs(delta), intent.currency)}"
                f"{f' — {intent.breakdown}' if intent.breakdown else ''})"
            )
        await message.reply_text(reply)

    elif intent.type == "query":
        assert isinstance(intent, QueryIntent)
        reply = handle_query(intent)
        await message.reply_text(reply)

    elif intent.type == "edit":
        assert isinstance(intent, EditIntent)
        reply = handle_edit(intent)
        await message.reply_text(reply)

    elif intent.type == "delete":
        assert isinstance(intent, DeleteIntent)
        reply = handle_delete(intent)
        await message.reply_text(reply)

    elif intent.type == "search":
        assert isinstance(intent, SearchIntent)
        reply = handle_search(intent)
        await message.reply_text(reply)

    elif intent.type == "export":
        assert isinstance(intent, ExportIntent)
        reply, file_path = handle_export(intent)
        if file_path is not None:
            await message.reply_document(document=file_path.open("rb"), filename=file_path.name, caption=reply)
        else:
            await message.reply_text(reply)

    elif intent.type == "chart":
        assert isinstance(intent, ChartIntent)
        with session_scope() as session:
            generator = CHART_GENERATORS[intent.chart_type]
            chart_path = generator(session, period=intent.period)
        if chart_path is None:
            await message.reply_text("Not enough data yet to draw that chart.")
        else:
            with chart_path.open("rb") as f:
                await message.reply_photo(photo=f)

    else:
        await message.reply_text(
            "I couldn't understand that as an expense, income entry, or question.\n"
            "Try something like:\n"
            "• \"Spent 85,000 on groceries\"\n"
            "• \"Salary came today: 6,500,000\"\n"
            "• \"How much did I spend this month?\""
        )
