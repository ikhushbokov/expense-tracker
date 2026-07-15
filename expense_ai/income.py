"""Month-by-month income log. Mirrors history.py's day-by-day ledger, but
scoped to income only and paged a month at a time via handlers/income.py's
callback (see keyboards.month_nav_keyboard).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from expense_ai.database import repository
from expense_ai.finance import format_amount, total_income_by_currency
from expense_ai.periods import month_range


def render_month_income_text(session: Session, year: int, month: int) -> str:
    start, end = month_range(year, month)
    label = start.strftime("%B %Y")
    incomes = sorted(repository.list_income(session, start=start, end=end), key=lambda i: i.datetime)

    lines = [f"\U0001F4B0 Income — {label}", ""]
    if not incomes:
        lines.append("No income recorded this month.")
    else:
        for i in incomes:
            lines.append(f"{i.datetime.strftime('%Y-%m-%d')} — {format_amount(i.amount, i.currency)} — {i.description or '-'}")
        lines.append("")
        totals = total_income_by_currency(session, start=start, end=end)
        lines.append("Total: " + ", ".join(format_amount(v, c) for c, v in totals.items()))

    return "\n".join(lines)
