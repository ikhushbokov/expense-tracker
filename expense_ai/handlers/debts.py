"""Handlers for lending/borrowing money and settling loans (see
database/models.py:Debt). Deletion (target="last_debt") is handled inside
edit_search.py::handle_delete, alongside the other entry types.
"""

from __future__ import annotations

from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.database.models import Debt
from expense_ai.finance import describe_debt, format_amount, open_debt_totals
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.models.schemas import DebtIntent, SettleDebtIntent


def _find_open_debt(session: Session, *, keyword: str | None, currency: str | None) -> Debt | None:
    if keyword is not None or currency is not None:
        matches = repository.list_debts(session, status="open", keyword=keyword, currency=currency)
        if matches:
            return matches[0]
        # Nothing matched that name/currency -- this bot has exactly one user,
        # so fall back to the most recent open debt rather than refusing (same
        # pattern as edit_search.py's _find_target_expense/_find_target_transfer).
    return repository.last_debt(session, status="open")


def handle_debt(intent: DebtIntent) -> str:
    with session_scope() as session:
        debt = repository.add_debt(
            session,
            person=intent.person,
            amount=intent.amount,
            currency=intent.currency,
            direction=intent.direction,
            note=intent.note,
        )
        summary = describe_debt(debt)
    verb = "You lent" if intent.direction == "lent" else "You borrowed"
    return f"\U0001F91D {verb} — {summary}"


def handle_settle_debt(intent: SettleDebtIntent) -> str:
    with session_scope() as session:
        debt = _find_open_debt(session, keyword=intent.person, currency=intent.currency)
        if debt is None:
            return "You don't have any open loans to settle."
        before = describe_debt(debt)
        currency = debt.currency
        updated = repository.settle_debt(session, debt.id, settled_amount=intent.amount)
        assert updated is not None
        repaid = updated.settled_amount if updated.settled_amount is not None else updated.amount
    return f"✅ Settled: {before}\n(Repaid: {format_amount(repaid, currency)})"


def render_open_debts_text(session: Session) -> str:
    open_debts = repository.list_debts(session, status="open")
    owed_to_me = [d for d in open_debts if d.direction == "lent"]
    i_owe = [d for d in open_debts if d.direction == "borrowed"]

    lines = ["\U0001F91D Open loans", "", "Owed to you:"]
    lines += [f"  • {describe_debt(d)}" for d in owed_to_me] if owed_to_me else ["  (none)"]
    lines += ["", "You owe:"]
    lines += [f"  • {describe_debt(d)}" for d in i_owe] if i_owe else ["  (none)"]

    totals = open_debt_totals(session)
    if totals["owed_to_me"] or totals["i_owe"]:
        lines.append("")
        if totals["owed_to_me"]:
            lines.append("Total owed to you: " + ", ".join(format_amount(v, c) for c, v in totals["owed_to_me"].items()))
        if totals["i_owe"]:
            lines.append("Total you owe: " + ", ".join(format_amount(v, c) for c, v in totals["i_owe"].items()))

    return "\n".join(lines)


def open_debts_keyboard(session: Session) -> InlineKeyboardMarkup | None:
    open_debts = repository.list_debts(session, status="open")
    if not open_debts:
        return None
    buttons = [
        [
            InlineKeyboardButton(
                f"✅ Settle: {d.person} ({format_amount(d.amount, d.currency)})",
                callback_data=f"debt_settle:{d.id}",
            )
        ]
        for d in open_debts
    ]
    return InlineKeyboardMarkup(buttons)


@restrict_to_owner
async def handle_debt_settle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    debt_id = int(query.data.removeprefix("debt_settle:"))
    with session_scope() as session:
        debt = repository.get_debt(session, debt_id)
        if debt is None or debt.status != "open":
            text = "That loan is already settled or no longer exists.\n\n" + render_open_debts_text(session)
            await query.edit_message_text(text, reply_markup=open_debts_keyboard(session))
            return
        summary = describe_debt(debt)
        repository.settle_debt(session, debt_id)
        text = render_open_debts_text(session)
        markup = open_debts_keyboard(session)
    await query.edit_message_text(f"✅ Settled: {summary}\n\n{text}", reply_markup=markup)
