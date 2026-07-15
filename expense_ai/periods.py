"""Resolves named periods ("this_month", "yesterday", ...) into datetime ranges."""

from __future__ import annotations

import calendar
import datetime as dt

PeriodName = str  # today, yesterday, this_week, this_month, last_month, all_time, custom


def resolve_period(
    period: PeriodName,
    *,
    custom_start: dt.date | None = None,
    custom_end: dt.date | None = None,
    now: dt.datetime | None = None,
) -> tuple[dt.datetime | None, dt.datetime | None]:
    """Return a (start, end) datetime range for a named period.

    ``end`` is exclusive. Both bounds are ``None`` for "all_time".
    """
    now = now or dt.datetime.now()
    today = now.date()

    if period == "today":
        start = dt.datetime.combine(today, dt.time.min)
        end = start + dt.timedelta(days=1)
    elif period == "yesterday":
        yesterday = today - dt.timedelta(days=1)
        start = dt.datetime.combine(yesterday, dt.time.min)
        end = start + dt.timedelta(days=1)
    elif period == "this_week":
        start_date = today - dt.timedelta(days=today.weekday())  # Monday
        start = dt.datetime.combine(start_date, dt.time.min)
        end = start + dt.timedelta(days=7)
    elif period == "this_month":
        start = dt.datetime(today.year, today.month, 1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        end = start + dt.timedelta(days=last_day)
    elif period == "last_month":
        first_of_this_month = dt.date(today.year, today.month, 1)
        last_month_end = first_of_this_month
        last_month_start_date = (first_of_this_month - dt.timedelta(days=1)).replace(day=1)
        start = dt.datetime.combine(last_month_start_date, dt.time.min)
        end = dt.datetime.combine(last_month_end, dt.time.min)
    elif period == "custom":
        if custom_start is None:
            return None, None
        start = dt.datetime.combine(custom_start, dt.time.min)
        end_date = custom_end or custom_start
        end = dt.datetime.combine(end_date, dt.time.min) + dt.timedelta(days=1)
    else:  # "all_time" or unrecognized
        return None, None

    return start, end


def week_start(day: dt.date) -> dt.date:
    """Monday of the week containing ``day``."""
    return day - dt.timedelta(days=day.weekday())


def month_range(year: int, month: int) -> tuple[dt.datetime, dt.datetime]:
    """(start, end) bounds for one specific calendar month. ``end`` is exclusive."""
    start = dt.datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    return start, start + dt.timedelta(days=last_day)


def week_range(monday: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """(start, end) bounds for the 7-day week starting on ``monday``. ``end`` is exclusive."""
    start = dt.datetime.combine(monday, dt.time.min)
    return start, start + dt.timedelta(days=7)


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Add ``delta`` months to (year, month), normalizing year/month overflow."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1
