"""Balance, summaries, and category breakdowns computed from stored data.

Amounts are grouped by currency rather than converted, since the bot has no
reliable exchange-rate source; a user who spends in both UZS and USD will
simply see both totals reported separately.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from expense_ai.database import repository
from expense_ai.periods import resolve_period


def format_amount(amount: float, currency: str) -> str:
    """Render 85000.0 -> '85,000 UZS' (no decimals for whole numbers)."""
    if amount == int(amount):
        number = f"{int(amount):,}"
    else:
        number = f"{amount:,.2f}"
    return f"{number} {currency}"


@dataclass
class CategoryTotal:
    category: str
    currency: str
    total: float
    percentage: float


@dataclass
class MonthlySummary:
    period_label: str
    income_by_currency: dict[str, float]
    expense_by_currency: dict[str, float]
    category_totals: list[CategoryTotal]
    balance_by_currency: dict[str, float]


def get_balances(session: Session) -> dict[str, float]:
    """Total income minus total expenses, grouped by currency."""
    balances: dict[str, float] = defaultdict(float)
    for income in repository.list_income(session):
        balances[income.currency] += income.amount
    for expense in repository.list_expenses(session):
        balances[expense.currency] -= expense.amount
    return dict(balances)


def reconcile_balance(
    session: Session, *, total_amount: float, currency: str, note: str = ""
) -> float:
    """Insert an adjustment entry so the stored balance matches a real-world
    total the user just reported (e.g. summed card balances).

    Returns the delta that was applied (0.0 if the stored balance already
    matched, in which case no entry is created).
    """
    current = get_balances(session).get(currency, 0.0)
    delta = total_amount - current
    if delta == 0:
        return 0.0

    description = f"Balance adjustment{f': {note}' if note else ''}"
    if delta > 0:
        repository.add_income(session, amount=delta, currency=currency, description=description)
    else:
        repository.add_expense(
            session, amount=-delta, currency=currency, category="Other", description=description
        )
    return delta


def total_expenses_by_currency(
    session: Session, *, start: dt.datetime | None = None, end: dt.datetime | None = None, category: str | None = None
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for expense in repository.list_expenses(session, start=start, end=end, category=category):
        totals[expense.currency] += expense.amount
    return dict(totals)


def total_income_by_currency(
    session: Session, *, start: dt.datetime | None = None, end: dt.datetime | None = None
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for income in repository.list_income(session, start=start, end=end):
        totals[income.currency] += income.amount
    return dict(totals)


def category_breakdown(
    session: Session, *, start: dt.datetime | None = None, end: dt.datetime | None = None
) -> list[CategoryTotal]:
    """Per-category totals (grouped by currency) with % of that currency's total spend."""
    per_currency_category: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for expense in repository.list_expenses(session, start=start, end=end):
        per_currency_category[expense.currency][expense.category] += expense.amount

    results: list[CategoryTotal] = []
    for currency, by_category in per_currency_category.items():
        currency_total = sum(by_category.values())
        for category, amount in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True):
            pct = (amount / currency_total * 100) if currency_total else 0.0
            results.append(CategoryTotal(category=category, currency=currency, total=amount, percentage=pct))
    return results


def biggest_expenses(
    session: Session, *, start: dt.datetime | None = None, end: dt.datetime | None = None, limit: int = 5
):
    expenses = repository.list_expenses(session, start=start, end=end)
    return sorted(expenses, key=lambda e: e.amount, reverse=True)[:limit]


def build_monthly_summary(session: Session, *, period: str = "this_month", label: str | None = None) -> MonthlySummary:
    start, end = resolve_period(period)
    return MonthlySummary(
        period_label=label or period.replace("_", " ").title(),
        income_by_currency=total_income_by_currency(session, start=start, end=end),
        expense_by_currency=total_expenses_by_currency(session, start=start, end=end),
        category_totals=category_breakdown(session, start=start, end=end),
        balance_by_currency=get_balances(session),
    )


def render_summary(summary: MonthlySummary) -> str:
    lines = [f"\U0001F4CA Summary: {summary.period_label}", ""]

    lines.append("Income")
    if summary.income_by_currency:
        for currency, amount in summary.income_by_currency.items():
            lines.append(format_amount(amount, currency))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("Expenses")
    if summary.category_totals:
        name_width = max(len(c.category) for c in summary.category_totals) + 1
        for c in summary.category_totals:
            dots = "." * max(1, 20 - len(c.category))
            lines.append(
                f"{c.category} {dots} {format_amount(c.total, c.currency)} ({c.percentage:.0f}%)"
            )
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("Total Expenses")
    if summary.expense_by_currency:
        for currency, amount in summary.expense_by_currency.items():
            lines.append(format_amount(amount, currency))
    else:
        lines.append(format_amount(0, "—"))
    lines.append("")

    lines.append("Remaining Balance")
    if summary.balance_by_currency:
        for currency, amount in summary.balance_by_currency.items():
            lines.append(format_amount(amount, currency))
    else:
        lines.append(format_amount(0, "—"))

    return "\n".join(lines)
