"""Tests for savings goal progress (database/models.py:SavingsGoal)."""

from __future__ import annotations

from expense_ai.database import repository, session_scope
from expense_ai.finance import render_savings_goal_lines, savings_goal_progress


def test_savings_goal_progress_percentage():
    with session_scope() as s:
        repository.add_transfer(s, from_account=None, to_account="savings", amount=2_000_000, currency="UZS")
    with session_scope() as s:
        current, pct = savings_goal_progress(s, target_amount=10_000_000, currency="UZS")
    assert current == 2_000_000
    assert pct == 20.0


def test_setting_a_new_goal_for_same_currency_replaces_old_one():
    with session_scope() as s:
        repository.upsert_savings_goal(s, name="Laptop", target_amount=10_000_000, currency="UZS")
        repository.upsert_savings_goal(s, name="Car", target_amount=50_000_000, currency="UZS")
    with session_scope() as s:
        goals = repository.list_savings_goals(s)
    assert len(goals) == 1
    assert goals[0].name == "Car"


def test_render_savings_goal_lines_includes_name_and_percentage():
    with session_scope() as s:
        repository.upsert_savings_goal(s, name="Laptop", target_amount=10_000_000, currency="UZS")
        repository.add_transfer(s, from_account=None, to_account="savings", amount=2_000_000, currency="UZS")
    with session_scope() as s:
        lines = render_savings_goal_lines(s)
    assert len(lines) == 1
    assert "Laptop" in lines[0]
    assert "20%" in lines[0]


def test_render_savings_goal_lines_empty_when_no_goals():
    with session_scope() as s:
        assert render_savings_goal_lines(s) == []
