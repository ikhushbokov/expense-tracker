"""Tests for the day-by-day history log (expense_ai/history.py)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.history import day_entries, day_keyboard, render_day_text

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)


def test_day_entries_includes_expense_income_and_transfer_sorted_by_time():
    with session_scope() as s:
        repository.add_expense(
            s, amount=13_000, currency="UZS", category="Food", description="Drink",
            when=dt.datetime.combine(TODAY, dt.time(12, 51)),
        )
        repository.add_income(
            s, amount=500_000, currency="UZS", description="Freelance",
            when=dt.datetime.combine(TODAY, dt.time(9, 0)),
        )
    with session_scope() as s:
        repository.add_transfer(
            s, from_account="balance", to_account="savings", amount=100_000, currency="UZS",
            when=dt.datetime.combine(TODAY, dt.time(18, 0)),
        )

    with session_scope() as s:
        entries = day_entries(s, TODAY)

    assert [e.kind for e in entries] == ["income", "expense", "transfer"]
    assert "Drink" in entries[1].display
    assert "-13,000 UZS" in entries[1].display


def test_day_entries_excludes_other_days():
    with session_scope() as s:
        repository.add_expense(
            s, amount=20_000, currency="UZS", category="Food", description="Old lunch",
            when=dt.datetime.combine(YESTERDAY, dt.time(12, 0)),
        )

    with session_scope() as s:
        assert day_entries(s, TODAY) == []
        assert len(day_entries(s, YESTERDAY)) == 1


def test_render_day_text_includes_totals():
    with session_scope() as s:
        repository.add_expense(s, amount=13_000, currency="UZS", category="Food", description="Drink")
        repository.add_income(s, amount=500_000, currency="UZS", description="Freelance")

    with session_scope() as s:
        text = render_day_text(s, TODAY)

    assert "Spent: 13,000 UZS" in text
    assert "Received: 500,000 UZS" in text


def test_render_day_text_with_no_activity():
    with session_scope() as s:
        text = render_day_text(s, TODAY)
    assert "No activity" in text


def test_day_keyboard_hides_next_button_for_today_but_shows_for_past_day():
    today_markup = day_keyboard(TODAY)
    assert len(today_markup.inline_keyboard[0]) == 1  # only "prev"

    past_markup = day_keyboard(YESTERDAY)
    assert len(past_markup.inline_keyboard[0]) == 2  # prev and next
    callback_data = [button.callback_data for button in past_markup.inline_keyboard[0]]
    assert callback_data == [f"hist:{YESTERDAY - dt.timedelta(days=1)}", f"hist:{TODAY}"]
