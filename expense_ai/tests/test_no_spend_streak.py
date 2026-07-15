"""Tests for the no-spend streak (finance.no_spend_streak_days)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.finance import no_spend_streak_days

TODAY = dt.date.today()


def test_zero_when_no_expenses_exist():
    with session_scope() as s:
        assert no_spend_streak_days(s, today=TODAY) == 0


def test_zero_when_spent_today():
    with session_scope() as s:
        repository.add_expense(
            s, amount=10_000, currency="UZS", category="Food",
            when=dt.datetime.combine(TODAY, dt.time(9, 0)),
        )
    with session_scope() as s:
        assert no_spend_streak_days(s, today=TODAY) == 0


def test_counts_days_since_last_expense():
    last_spend_day = TODAY - dt.timedelta(days=3)
    with session_scope() as s:
        repository.add_expense(
            s, amount=10_000, currency="UZS", category="Food",
            when=dt.datetime.combine(last_spend_day, dt.time(9, 0)),
        )
    with session_scope() as s:
        assert no_spend_streak_days(s, today=TODAY) == 3
