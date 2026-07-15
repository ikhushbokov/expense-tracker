"""Tests for month-over-month spending insights (finance.month_over_month_insights)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.finance import month_over_month_insights

THIS_MONTH = dt.date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - dt.timedelta(days=1)).replace(day=1)


def test_total_spending_percentage_change():
    with session_scope() as s:
        repository.add_expense(
            s, amount=100_000, currency="UZS", category="Food",
            when=dt.datetime.combine(LAST_MONTH, dt.time(12, 0)),
        )
        repository.add_expense(
            s, amount=150_000, currency="UZS", category="Food",
            when=dt.datetime.combine(THIS_MONTH, dt.time(12, 0)),
        )
    with session_scope() as s:
        lines = month_over_month_insights(s, year=THIS_MONTH.year, month=THIS_MONTH.month)
    assert any("+50%" in line for line in lines)


def test_no_insights_without_prior_month_data():
    with session_scope() as s:
        repository.add_expense(
            s, amount=100_000, currency="UZS", category="Food",
            when=dt.datetime.combine(THIS_MONTH, dt.time(12, 0)),
        )
    with session_scope() as s:
        lines = month_over_month_insights(s, year=THIS_MONTH.year, month=THIS_MONTH.month)
    assert lines == []


def test_biggest_category_movers_included():
    with session_scope() as s:
        repository.add_expense(
            s, amount=100_000, currency="UZS", category="Food",
            when=dt.datetime.combine(LAST_MONTH, dt.time(12, 0)),
        )
        repository.add_expense(
            s, amount=300_000, currency="UZS", category="Food",
            when=dt.datetime.combine(THIS_MONTH, dt.time(12, 0)),
        )
    with session_scope() as s:
        lines = month_over_month_insights(s, year=THIS_MONTH.year, month=THIS_MONTH.month)
    assert any("Food" in line and "+200%" in line for line in lines)
