"""Tests for the month-by-month income log (expense_ai/income.py)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.income import render_month_income_text

TODAY = dt.date.today()


def test_render_month_income_text_lists_entries_and_total():
    with session_scope() as s:
        repository.add_income(
            s, amount=6_500_000, currency="UZS", description="Salary",
            when=dt.datetime.combine(TODAY.replace(day=1), dt.time(9, 0)),
        )
        repository.add_income(
            s, amount=350_000, currency="UZS", description="Freelance",
            when=dt.datetime.combine(TODAY.replace(day=1), dt.time(18, 0)),
        )

    with session_scope() as s:
        text = render_month_income_text(s, TODAY.year, TODAY.month)

    assert "Salary" in text
    assert "Freelance" in text
    assert "Total: 6,850,000 UZS" in text


def test_render_month_income_text_excludes_other_months():
    other_month = (TODAY.replace(day=1) - dt.timedelta(days=32)).replace(day=1)
    with session_scope() as s:
        repository.add_income(
            s, amount=100_000, currency="UZS", description="Old income",
            when=dt.datetime.combine(other_month, dt.time(9, 0)),
        )

    with session_scope() as s:
        text = render_month_income_text(s, TODAY.year, TODAY.month)

    assert "No income recorded this month." in text
    assert "Old income" not in text


def test_render_month_income_text_with_no_activity():
    with session_scope() as s:
        text = render_month_income_text(s, TODAY.year, TODAY.month)
    assert "No income recorded this month." in text
