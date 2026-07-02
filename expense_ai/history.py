"""Day-by-day transaction log (expenses, income, transfers).

Deliberately renders one day at a time rather than a growing flat list --
see ``render_day_text``/``day_keyboard`` -- so the log stays a fixed size
no matter how much history accumulates. Callers page through days via the
inline keyboard's callback data (``hist:<ISO date>``).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from expense_ai.database import repository
from expense_ai.finance import describe_transfer, format_amount, total_expenses_by_currency, total_income_by_currency

_ICONS = {"expense": "🔴", "income": "🟢", "transfer": "🔁"}


@dataclass
class LedgerEntry:
    kind: Literal["expense", "income", "transfer"]
    time: dt.datetime
    display: str  # fully rendered right-hand side, including the amount


def _day_range(day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, dt.time.min)
    return start, start + dt.timedelta(days=1)


def day_entries(session: Session, day: dt.date) -> list[LedgerEntry]:
    start, end = _day_range(day)
    entries: list[LedgerEntry] = []

    for e in repository.list_expenses(session, start=start, end=end):
        label = f"{e.category}{f' — {e.description}' if e.description else ''}"
        entries.append(LedgerEntry("expense", e.datetime, f"{label} — -{format_amount(e.amount, e.currency)}"))

    for i in repository.list_income(session, start=start, end=end):
        entries.append(
            LedgerEntry("income", i.datetime, f"{i.description or 'Income'} — +{format_amount(i.amount, i.currency)}")
        )

    for t in repository.list_transfers(session, start=start, end=end):
        entries.append(LedgerEntry("transfer", t.datetime, describe_transfer(t)))

    entries.sort(key=lambda entry: entry.time)
    return entries


def render_day_text(session: Session, day: dt.date) -> str:
    entries = day_entries(session, day)
    lines = [f"\U0001F4DC History — {day.strftime('%a, %b %d %Y')}", ""]

    if not entries:
        lines.append("No activity this day.")
    else:
        for entry in entries:
            lines.append(f"{entry.time.strftime('%H:%M')} {_ICONS[entry.kind]} {entry.display}")

    start, end = _day_range(day)
    spent = total_expenses_by_currency(session, start=start, end=end)
    received = total_income_by_currency(session, start=start, end=end)
    if spent or received:
        lines.append("")
    if spent:
        lines.append("Spent: " + ", ".join(format_amount(v, c) for c, v in spent.items()))
    if received:
        lines.append("Received: " + ", ".join(format_amount(v, c) for c, v in received.items()))

    return "\n".join(lines)


def day_keyboard(day: dt.date) -> InlineKeyboardMarkup:
    prev_day = day - dt.timedelta(days=1)
    buttons = [InlineKeyboardButton(f"◀ {prev_day.strftime('%b %d')}", callback_data=f"hist:{prev_day.isoformat()}")]
    if day < dt.date.today():
        next_day = day + dt.timedelta(days=1)
        buttons.append(InlineKeyboardButton(f"{next_day.strftime('%b %d')} ▶", callback_data=f"hist:{next_day.isoformat()}"))
    return InlineKeyboardMarkup([buttons])
