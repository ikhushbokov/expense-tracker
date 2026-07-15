"""Balance, summaries, and category breakdowns computed from stored data.

Amounts are grouped by currency rather than converted, since the bot has no
reliable exchange-rate source; a user who spends in both UZS and USD will
simply see both totals reported separately.

Money lives in one of two accounts: "balance" (day-to-day spendable money)
and "savings" (set aside for something specific, not day-to-day spending).
Moving money between them, or correcting either to match a real-world total,
goes through the Transfer ledger -- never through Expense/Income -- so
those corrections never show up as "income" or "spending" in period
reports. See database/models.py:Transfer for the reasoning.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from expense_ai.database import repository
from expense_ai.database.models import Transfer
from expense_ai.periods import resolve_period

ACCOUNTS = ("balance", "savings")

# "outside" (None) represents a correction against the real world (see
# database/models.py:Transfer) rather than a move between the two buckets.
ACCOUNT_LABELS = {"balance": "Balance", "savings": "Savings", None: "outside"}


def format_amount(amount: float, currency: str) -> str:
    """Render 85000.0 -> '85,000 UZS' (no decimals for whole numbers)."""
    if amount == int(amount):
        number = f"{int(amount):,}"
    else:
        number = f"{amount:,.2f}"
    return f"{number} {currency}"


def describe_transfer(transfer: Transfer) -> str:
    frm = ACCOUNT_LABELS.get(transfer.from_account, transfer.from_account)
    to = ACCOUNT_LABELS.get(transfer.to_account, transfer.to_account)
    return f"{format_amount(transfer.amount, transfer.currency)} ({frm} → {to}{f', ' + transfer.note if transfer.note else ''})"


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


def get_balances(session: Session, *, account: str = "balance") -> dict[str, float]:
    """Running total for one account: its income minus its expenses, plus
    net transfers into/out of it, grouped by currency."""
    balances: dict[str, float] = defaultdict(float)
    for income in repository.list_income(session, account=account):
        balances[income.currency] += income.amount
    for expense in repository.list_expenses(session, account=account):
        balances[expense.currency] -= expense.amount
    for transfer in repository.list_transfers(session, account=account):
        if transfer.to_account == account:
            balances[transfer.currency] += transfer.amount
        if transfer.from_account == account:
            balances[transfer.currency] -= transfer.amount
    return dict(balances)


def get_net_worth(session: Session) -> dict[str, float]:
    """Balance + savings combined, per currency. Internal transfers between
    the two accounts cancel out here, as they should -- moving money from
    balance to savings doesn't change how much you have in total."""
    totals: dict[str, float] = defaultdict(float)
    for account in ACCOUNTS:
        for currency, amount in get_balances(session, account=account).items():
            totals[currency] += amount
    return dict(totals)


def reconcile_balance(
    session: Session, *, total_amount: float, currency: str, account: str = "balance", note: str = ""
) -> float:
    """Record a Transfer so a given account's stored total matches a
    real-world total the user just reported (e.g. summed card balances).
    This is a correction, not a transaction, so it's never counted as
    income or spending in period reports.

    Returns the delta that was applied (0.0 if it already matched, in
    which case no entry is created).
    """
    current = get_balances(session, account=account).get(currency, 0.0)
    delta = total_amount - current
    if delta == 0:
        return 0.0

    if delta > 0:
        repository.add_transfer(
            session, from_account=None, to_account=account, amount=delta, currency=currency, note=note
        )
    else:
        repository.add_transfer(
            session, from_account=account, to_account=None, amount=-delta, currency=currency, note=note
        )
    return delta


def transfer_funds(
    session: Session,
    *,
    from_account: str,
    to_account: str,
    amount: float,
    currency: str,
    note: str = "",
) -> None:
    """Move money between the balance and savings accounts."""
    repository.add_transfer(
        session, from_account=from_account, to_account=to_account, amount=amount, currency=currency, note=note
    )


def total_expenses_by_currency(
    session: Session,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    category: str | None = None,
    account: str = "balance",
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for expense in repository.list_expenses(session, start=start, end=end, category=category, account=account):
        totals[expense.currency] += expense.amount
    return dict(totals)


def total_income_by_currency(
    session: Session,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    account: str = "balance",
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for income in repository.list_income(session, start=start, end=end, account=account):
        totals[income.currency] += income.amount
    return dict(totals)


def category_breakdown(
    session: Session, *, start: dt.datetime | None = None, end: dt.datetime | None = None, account: str = "balance"
) -> list[CategoryTotal]:
    """Per-category totals (grouped by currency) with % of that currency's total spend."""
    per_currency_category: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for expense in repository.list_expenses(session, start=start, end=end, account=account):
        per_currency_category[expense.currency][expense.category] += expense.amount

    results: list[CategoryTotal] = []
    for currency, by_category in per_currency_category.items():
        currency_total = sum(by_category.values())
        for category, amount in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True):
            pct = (amount / currency_total * 100) if currency_total else 0.0
            results.append(CategoryTotal(category=category, currency=currency, total=amount, percentage=pct))
    return results


def biggest_expenses(
    session: Session,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    limit: int = 5,
    account: str = "balance",
):
    expenses = repository.list_expenses(session, start=start, end=end, account=account)
    return sorted(expenses, key=lambda e: e.amount, reverse=True)[:limit]


def build_summary_for_range(
    session: Session, *, start: dt.datetime | None, end: dt.datetime | None, label: str
) -> MonthlySummary:
    return MonthlySummary(
        period_label=label,
        income_by_currency=total_income_by_currency(session, start=start, end=end),
        expense_by_currency=total_expenses_by_currency(session, start=start, end=end),
        category_totals=category_breakdown(session, start=start, end=end),
        balance_by_currency=get_balances(session, account="balance"),
    )


def build_monthly_summary(session: Session, *, period: str = "this_month", label: str | None = None) -> MonthlySummary:
    start, end = resolve_period(period)
    return build_summary_for_range(session, start=start, end=end, label=label or period.replace("_", " ").title())


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
