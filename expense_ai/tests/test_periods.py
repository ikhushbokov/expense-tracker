"""Tests for named-period resolution."""

from __future__ import annotations

import datetime as dt

from expense_ai.periods import resolve_period


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
