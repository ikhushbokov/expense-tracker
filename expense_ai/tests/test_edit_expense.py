"""Tests for editing an expense by category/period, not just the last one --
see handlers/edit_search.py::_find_target_expense and the bug it fixes
(searching by category word when the description doesn't contain it)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.handlers.edit_search import handle_edit
from expense_ai.models.schemas import EditIntent


def test_edit_finds_expense_by_category_when_description_differs():
    with session_scope() as s:
        repository.add_expense(s, amount=13_000, currency="UZS", category="Food", description="Drink")

    reply = handle_edit(EditIntent(target="search", keyword="food", new_description="Cold drink"))
    assert "updated" in reply.lower()

    with session_scope() as s:
        expense = repository.last_expense(s)
        assert expense.description == "Cold drink"
        assert expense.category == "Food"  # untouched, since new_category wasn't set


def test_edit_search_narrows_by_period_and_category():
    with session_scope() as s:
        repository.add_expense(
            s, amount=50_000, currency="UZS", category="Food", description="Old one",
            when=dt.datetime(2020, 1, 1),
        )
        repository.add_expense(s, amount=13_000, currency="UZS", category="Food", description="Drink")

    reply = handle_edit(EditIntent(target="search", category="Food", period="today", new_amount=15_000))
    assert "updated" in reply.lower()

    with session_scope() as s:
        expenses = repository.list_expenses(s)
        amounts = sorted(e.amount for e in expenses)
        # Only today's Food expense (13,000) should have been updated to 15,000;
        # the old one from 2020 is untouched.
        assert amounts == [15_000.0, 50_000.0]


def test_edit_falls_back_to_last_expense_when_search_matches_nothing():
    with session_scope() as s:
        repository.add_expense(s, amount=20_000, currency="UZS", category="Food", description="Lunch")

    reply = handle_edit(EditIntent(target="search", keyword="nonexistent-keyword", new_description="Renamed"))
    assert "updated" in reply.lower()

    with session_scope() as s:
        expense = repository.last_expense(s)
        assert expense.description == "Renamed"


def test_edit_with_no_matching_expenses_at_all():
    reply = handle_edit(EditIntent(target="search", keyword="food", new_description="Cold drink"))
    assert "couldn't find" in reply.lower()


def test_edit_reports_no_change_instead_of_a_false_positive():
    with session_scope() as s:
        repository.add_expense(s, amount=13_000, currency="UZS", category="Food", description="Cold drink")

    # Same description as already stored -- nothing actually changes.
    reply = handle_edit(EditIntent(target="last_expense", new_description="Cold drink"))
    assert "already" in reply.lower()
    assert "updated" not in reply.lower()


def test_edit_with_no_fields_asks_what_to_change():
    with session_scope() as s:
        repository.add_expense(s, amount=13_000, currency="UZS", category="Food", description="Cold drink")

    reply = handle_edit(EditIntent(target="last_expense"))
    assert "tell me what to change" in reply.lower()
