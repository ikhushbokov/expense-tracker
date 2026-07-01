"""Answers read-only natural-language questions about balance/spending/income."""

from __future__ import annotations

from expense_ai.database import repository, session_scope
from expense_ai.finance import (
    biggest_expenses,
    build_monthly_summary,
    category_breakdown,
    format_amount,
    get_balances,
    get_net_worth,
    render_summary,
    total_expenses_by_currency,
    total_income_by_currency,
)
from expense_ai.models.schemas import QueryIntent
from expense_ai.periods import resolve_period


def handle_query(intent: QueryIntent) -> str:
    with session_scope() as session:
        if intent.query_kind == "balance":
            if intent.account == "total":
                balances = get_net_worth(session)
                label, empty_msg = "Total (balance + savings)", "You have no recorded balance or savings yet."
            elif intent.account == "savings":
                balances = get_balances(session, account="savings")
                label, empty_msg = "Savings", "You have no savings recorded yet."
            else:
                balances = get_balances(session, account="balance")
                label, empty_msg = "Current balance", "You have no recorded income or expenses yet."
            if not balances:
                return empty_msg
            return f"{label}:\n" + "\n".join(format_amount(v, c) for c, v in balances.items())

        if intent.query_kind == "summary":
            summary = build_monthly_summary(session, period=intent.period)
            return render_summary(summary)

        if intent.query_kind == "total_by_period":
            start, end = resolve_period(intent.period, custom_start=intent.custom_start, custom_end=intent.custom_end)
            totals = total_expenses_by_currency(session, start=start, end=end, category=intent.category)
            if not totals:
                label = intent.category or "expenses"
                return f"No {label} recorded for {intent.period.replace('_', ' ')}."
            header = f"Total {intent.category + ' ' if intent.category else ''}spending ({intent.period.replace('_', ' ')}):"
            return header + "\n" + "\n".join(format_amount(v, c) for c, v in totals.items())

        if intent.query_kind == "total_by_category":
            start, end = resolve_period(intent.period, custom_start=intent.custom_start, custom_end=intent.custom_end)
            breakdown = [c for c in category_breakdown(session, start=start, end=end) if c.category == intent.category]
            if not breakdown:
                return f"No expenses recorded for category '{intent.category}'."
            return "\n".join(f"{c.category}: {format_amount(c.total, c.currency)} ({c.percentage:.0f}%)" for c in breakdown)

        if intent.query_kind == "biggest_expenses":
            start, end = resolve_period(intent.period, custom_start=intent.custom_start, custom_end=intent.custom_end)
            top = biggest_expenses(session, start=start, end=end, limit=intent.limit)
            if not top:
                return "No expenses recorded for that period."
            lines = ["Biggest expenses:"]
            for e in top:
                lines.append(f"{format_amount(e.amount, e.currency)} — {e.category} ({e.description or 'no description'})")
            return "\n".join(lines)

        if intent.query_kind == "total_income":
            start, end = resolve_period(intent.period, custom_start=intent.custom_start, custom_end=intent.custom_end)
            totals = total_income_by_currency(session, start=start, end=end)
            if not totals:
                return "No income recorded for that period."
            return "Total income:\n" + "\n".join(format_amount(v, c) for c, v in totals.items())

        # "other" / fallback: give a general balance + this-month snapshot
        summary = build_monthly_summary(session, period="this_month")
        return render_summary(summary)
