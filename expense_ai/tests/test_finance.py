"""Tests for balance/summary/category-breakdown calculations."""

from __future__ import annotations

from expense_ai.database import repository, session_scope
from expense_ai.finance import (
    biggest_expenses,
    category_breakdown,
    get_balances,
    total_expenses_by_currency,
    total_income_by_currency,
)


def _seed():
    with session_scope() as s:
        repository.add_income(s, amount=6_500_000, currency="UZS", description="Salary")
        repository.add_expense(s, amount=85_000, currency="UZS", category="Food", description="Groceries")
        repository.add_expense(s, amount=420_000, currency="UZS", category="Supplements", description="Protein")
        repository.add_expense(s, amount=35_000, currency="UZS", category="Transport", description="Taxi")


def test_balance_is_income_minus_expenses():
    _seed()
    with session_scope() as s:
        balances = get_balances(s)
    assert balances["UZS"] == 6_500_000 - 85_000 - 420_000 - 35_000


def test_total_expenses_by_currency():
    _seed()
    with session_scope() as s:
        totals = total_expenses_by_currency(s)
    assert totals["UZS"] == 85_000 + 420_000 + 35_000


def test_total_income_by_currency():
    _seed()
    with session_scope() as s:
        totals = total_income_by_currency(s)
    assert totals["UZS"] == 6_500_000


def test_category_breakdown_percentages_sum_to_100():
    _seed()
    with session_scope() as s:
        breakdown = category_breakdown(s)
    total_pct = sum(c.percentage for c in breakdown)
    assert abs(total_pct - 100.0) < 0.01
    assert breakdown[0].category == "Supplements"  # largest first


def test_biggest_expenses_sorted_desc():
    _seed()
    with session_scope() as s:
        top = biggest_expenses(s, limit=2)
    assert [e.amount for e in top] == [420_000, 85_000]


def test_empty_database_has_no_balance():
    with session_scope() as s:
        assert get_balances(s) == {}
