"""Chart generation (matplotlib) for spending/balance visualizations.

Charts are rendered to PNG files under ``EXPORT_DIR`` and sent back to the
user as Telegram photos (see handlers/text.py).
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless rendering, no display needed
import matplotlib.pyplot as plt
from sqlalchemy.orm import Session

from expense_ai.config import settings
from expense_ai.database import repository
from expense_ai.finance import category_breakdown
from expense_ai.periods import resolve_period


def _new_chart_path(name: str) -> Path:
    return settings.export_dir_full_path / f"{name}_{uuid.uuid4().hex[:8]}.png"


def category_pie_chart(session: Session, *, period: str = "this_month") -> Path | None:
    start, end = resolve_period(period)
    breakdown = category_breakdown(session, start=start, end=end)
    if not breakdown:
        return None

    # Use the currency with the largest total if multiple currencies are present.
    by_currency: dict[str, list] = {}
    for c in breakdown:
        by_currency.setdefault(c.currency, []).append(c)
    currency = max(by_currency, key=lambda c: sum(x.total for x in by_currency[c]))
    entries = by_currency[currency]

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(
        [e.total for e in entries],
        labels=[e.category for e in entries],
        autopct="%1.0f%%",
        startangle=90,
    )
    ax.set_title(f"Spending by Category ({period.replace('_', ' ').title()}, {currency})")
    path = _new_chart_path("category_pie")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def monthly_spending_chart(session: Session, *, months: int = 6) -> Path | None:
    now = dt.datetime.now()
    labels: list[str] = []
    totals: list[float] = []
    currency = settings.default_currency

    for i in range(months - 1, -1, -1):
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        start = dt.datetime(year, month, 1)
        end = dt.datetime(year + 1, 1, 1) if month == 12 else dt.datetime(year, month + 1, 1)
        expenses = repository.list_expenses(session, start=start, end=end)
        total = sum(e.amount for e in expenses if e.currency == currency)
        labels.append(start.strftime("%b %Y"))
        totals.append(total)

    if not any(totals):
        return None

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, totals, color="#4C72B0")
    ax.set_title(f"Monthly Spending ({currency})")
    ax.set_ylabel(currency)
    plt.xticks(rotation=45, ha="right")
    path = _new_chart_path("monthly_spending")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def weekly_spending_chart(session: Session, *, weeks: int = 8) -> Path | None:
    now = dt.datetime.now()
    today = now.date()
    this_monday = today - dt.timedelta(days=today.weekday())
    currency = settings.default_currency

    labels: list[str] = []
    totals: list[float] = []
    for i in range(weeks - 1, -1, -1):
        week_start = this_monday - dt.timedelta(weeks=i)
        start = dt.datetime.combine(week_start, dt.time.min)
        end = start + dt.timedelta(days=7)
        expenses = repository.list_expenses(session, start=start, end=end)
        total = sum(e.amount for e in expenses if e.currency == currency)
        labels.append(week_start.strftime("%b %d"))
        totals.append(total)

    if not any(totals):
        return None

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, totals, color="#55A868")
    ax.set_title(f"Weekly Spending ({currency})")
    ax.set_ylabel(currency)
    plt.xticks(rotation=45, ha="right")
    path = _new_chart_path("weekly_spending")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def balance_over_time_chart(session: Session) -> Path | None:
    currency = settings.default_currency
    expenses = [e for e in repository.list_expenses(session) if e.currency == currency]
    incomes = [i for i in repository.list_income(session) if i.currency == currency]

    events: list[tuple[dt.datetime, float]] = [(e.datetime, -e.amount) for e in expenses]
    events += [(i.datetime, i.amount) for i in incomes]
    if not events:
        return None
    events.sort(key=lambda ev: ev[0])

    dates: list[dt.datetime] = []
    running_balance: list[float] = []
    balance = 0.0
    for when, delta in events:
        balance += delta
        dates.append(when)
        running_balance.append(balance)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(dates, running_balance, marker="o", color="#C44E52")
    ax.set_title(f"Balance Over Time ({currency})")
    ax.set_ylabel(currency)
    plt.xticks(rotation=45, ha="right")
    path = _new_chart_path("balance_over_time")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


CHART_GENERATORS = {
    "category_pie": category_pie_chart,
    "monthly_spending": lambda session, period="this_month": monthly_spending_chart(session),
    "weekly_spending": lambda session, period="this_month": weekly_spending_chart(session),
    "balance_over_time": lambda session, period="this_month": balance_over_time_chart(session),
}
