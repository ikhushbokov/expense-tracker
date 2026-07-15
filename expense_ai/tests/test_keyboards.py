"""Tests for the shared month/week pagination keyboards (expense_ai/keyboards.py)."""

from __future__ import annotations

import datetime as dt

from expense_ai.keyboards import month_nav_keyboard, week_nav_keyboard
from expense_ai.periods import week_start

TODAY = dt.date.today()


def test_month_nav_keyboard_hides_next_for_current_month():
    markup = month_nav_keyboard("income", TODAY.year, TODAY.month)
    assert len(markup.inline_keyboard[0]) == 1  # only "prev"
    assert markup.inline_keyboard[0][0].callback_data.startswith("income:")


def test_month_nav_keyboard_shows_next_for_past_month():
    year, month = (TODAY.year - 1, 12) if TODAY.month == 1 else (TODAY.year, TODAY.month - 1)
    markup = month_nav_keyboard("summary_month", year, month)
    assert len(markup.inline_keyboard[0]) == 2
    callback_data = [b.callback_data for b in markup.inline_keyboard[0]]
    assert callback_data[1] == f"summary_month:{TODAY.year:04d}-{TODAY.month:02d}"


def test_week_nav_keyboard_hides_next_for_current_week():
    monday = week_start(TODAY)
    markup = week_nav_keyboard("summary_week", monday)
    assert len(markup.inline_keyboard[0]) == 1


def test_week_nav_keyboard_shows_next_for_past_week():
    monday = week_start(TODAY) - dt.timedelta(days=7)
    markup = week_nav_keyboard("summary_week", monday)
    assert len(markup.inline_keyboard[0]) == 2
    callback_data = [b.callback_data for b in markup.inline_keyboard[0]]
    assert callback_data == [
        f"summary_week:{(monday - dt.timedelta(days=7)).isoformat()}",
        f"summary_week:{week_start(TODAY).isoformat()}",
    ]
