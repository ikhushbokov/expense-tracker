"""Tests for the static HTML dashboard export (expense_ai/dashboard.py)."""

from __future__ import annotations

from expense_ai.dashboard import generate_dashboard_html
from expense_ai.database import repository, session_scope


def test_generate_dashboard_html_writes_a_file_with_expected_sections():
    with session_scope() as s:
        repository.add_income(s, amount=1_000_000, currency="UZS", description="Salary")
        repository.add_expense(s, amount=85_000, currency="UZS", category="Food", description="Groceries")

    with session_scope() as s:
        path = generate_dashboard_html(s)

    assert path.exists()
    assert path.suffix == ".html"
    html = path.read_text(encoding="utf-8")
    assert "Expense Dashboard" in html
    assert "Food" in html
    assert "85,000 UZS" in html
    assert "<html>" in html and "</html>" in html


def test_generate_dashboard_html_handles_empty_database():
    with session_scope() as s:
        path = generate_dashboard_html(s)
    html = path.read_text(encoding="utf-8")
    assert "No expenses recorded this month." in html
    assert "No savings goals set." in html
