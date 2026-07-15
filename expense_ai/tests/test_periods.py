"""Tests for named-period resolution."""

from __future__ import annotations

import datetime as dt

from expense_ai.periods import month_range, resolve_period, shift_month, week_range, week_start


def test_today():
    now = dt.datetime(2026, 7, 1, 15, 30)
    start, end = resolve_period("today", now=now)
    assert start == dt.datetime(2026, 7, 1, 0, 0)
    assert end == dt.datetime(2026, 7, 2, 0, 0)


def test_this_month():
    now = dt.datetime(2026, 7, 15, 10, 0)
    start, end = resolve_period("this_month", now=now)
    assert start == dt.datetime(2026, 7, 1, 0, 0)
    assert end == dt.datetime(2026, 8, 1, 0, 0)


def test_last_month_handles_year_boundary():
    now = dt.datetime(2026, 1, 15, 10, 0)
    start, end = resolve_period("last_month", now=now)
    assert start == dt.datetime(2025, 12, 1, 0, 0)
    assert end == dt.datetime(2026, 1, 1, 0, 0)


def test_all_time_returns_none_bounds():
    assert resolve_period("all_time") == (None, None)


def test_this_week_starts_monday():
    now = dt.datetime(2026, 7, 1, 10, 0)  # Wednesday
    start, end = resolve_period("this_week", now=now)
    assert start.weekday() == 0
    assert (end - start).days == 7


def test_week_start_returns_monday():
    assert week_start(dt.date(2026, 7, 1)) == dt.date(2026, 6, 29)  # Wednesday -> preceding Monday
    assert week_start(dt.date(2026, 6, 29)) == dt.date(2026, 6, 29)  # already Monday


def test_month_range_bounds():
    start, end = month_range(2026, 7)
    assert start == dt.datetime(2026, 7, 1, 0, 0)
    assert end == dt.datetime(2026, 8, 1, 0, 0)


def test_month_range_handles_leap_february():
    start, end = month_range(2028, 2)
    assert (end - start).days == 29


def test_week_range_bounds():
    monday = dt.date(2026, 6, 29)
    start, end = week_range(monday)
    assert start == dt.datetime(2026, 6, 29, 0, 0)
    assert end == dt.datetime(2026, 7, 6, 0, 0)


def test_shift_month_within_year():
    assert shift_month(2026, 7, 1) == (2026, 8)
    assert shift_month(2026, 7, -1) == (2026, 6)


def test_shift_month_crosses_year_boundary():
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2026, 1, -1) == (2025, 12)
