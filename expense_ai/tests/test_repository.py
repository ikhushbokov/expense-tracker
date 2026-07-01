"""Tests for the CRUD repository layer."""

from __future__ import annotations

from expense_ai.database import repository, session_scope


def test_add_and_get_expense():
    with session_scope() as s:
        expense = repository.add_expense(s, amount=1000, currency="UZS", category="Food", description="Test")
        expense_id = expense.id
    with session_scope() as s:
        fetched = repository.get_expense(s, expense_id)
        assert fetched is not None
        assert fetched.amount == 1000
        assert fetched.category == "Food"


def test_update_expense_only_changes_given_fields():
    with session_scope() as s:
        expense = repository.add_expense(s, amount=1000, currency="UZS", category="Food", description="Original")
        expense_id = expense.id
    with session_scope() as s:
        repository.update_expense(s, expense_id, amount=2000, category=None, description=None)
    with session_scope() as s:
        updated = repository.get_expense(s, expense_id)
        assert updated.amount == 2000
        assert updated.category == "Food"
        assert updated.description == "Original"


def test_delete_expense():
    with session_scope() as s:
        expense = repository.add_expense(s, amount=1000, currency="UZS", category="Food")
        expense_id = expense.id
    with session_scope() as s:
        assert repository.delete_expense(s, expense_id) is True
    with session_scope() as s:
        assert repository.get_expense(s, expense_id) is None


def test_delete_nonexistent_expense_returns_false():
    with session_scope() as s:
        assert repository.delete_expense(s, 99999) is False


def test_last_expense_returns_most_recent():
    with session_scope() as s:
        repository.add_expense(s, amount=1000, currency="UZS", category="Food")
        second = repository.add_expense(s, amount=2000, currency="UZS", category="Transport")
    with session_scope() as s:
        last = repository.last_expense(s)
        assert last.id == second.id


def test_list_expenses_filters_by_keyword():
    with session_scope() as s:
        repository.add_expense(s, amount=1000, currency="UZS", category="Food", description="Protein shake")
        repository.add_expense(s, amount=2000, currency="UZS", category="Food", description="Bread")
    with session_scope() as s:
        matches = repository.list_expenses(s, keyword="protein")
        assert len(matches) == 1
        assert matches[0].description == "Protein shake"


def test_list_expenses_filters_by_amount_range():
    with session_scope() as s:
        repository.add_expense(s, amount=100, currency="UZS", category="Food")
        repository.add_expense(s, amount=500_000, currency="UZS", category="Shopping")
    with session_scope() as s:
        matches = repository.list_expenses(s, min_amount=1000)
        assert len(matches) == 1
        assert matches[0].amount == 500_000
