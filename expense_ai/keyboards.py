"""Shared ◀/▶ inline-keyboard builders for paging month- or week-scoped views
(e.g. /month, /week, /income). ``callback_prefix`` becomes the callback_data
prefix -- e.g. "income" -> "income:2026-06" -- parsed back by the matching
callback handler in handlers/. Mirrors expense_ai/history.py's day_keyboard,
generalized to month/week granularity and reused across features instead of
duplicated per feature.
"""

from __future__ import annotations

import calendar
import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from expense_ai.periods import shift_month, week_start


def month_nav_keyboard(callback_prefix: str, year: int, month: int) -> InlineKeyboardMarkup:
    """Never pages past the current month."""
    prev_year, prev_month = shift_month(year, month, -1)
    buttons = [
        InlineKeyboardButton(
            f"◀ {calendar.month_abbr[prev_month]} {prev_year}",
            callback_data=f"{callback_prefix}:{prev_year:04d}-{prev_month:02d}",
        )
    ]
    today = dt.date.today()
    if (year, month) < (today.year, today.month):
        next_year, next_month = shift_month(year, month, 1)
        buttons.append(
            InlineKeyboardButton(
                f"{calendar.month_abbr[next_month]} {next_year} ▶",
                callback_data=f"{callback_prefix}:{next_year:04d}-{next_month:02d}",
            )
        )
    return InlineKeyboardMarkup([buttons])


def week_nav_keyboard(callback_prefix: str, monday: dt.date) -> InlineKeyboardMarkup:
    """Never pages past the current week. ``monday`` is that week's Monday."""
    prev_monday = monday - dt.timedelta(days=7)
    buttons = [
        InlineKeyboardButton(
            f"◀ Week of {prev_monday.strftime('%b %d')}",
            callback_data=f"{callback_prefix}:{prev_monday.isoformat()}",
        )
    ]
    if monday < week_start(dt.date.today()):
        next_monday = monday + dt.timedelta(days=7)
        buttons.append(
            InlineKeyboardButton(
                f"Week of {next_monday.strftime('%b %d')} ▶",
                callback_data=f"{callback_prefix}:{next_monday.isoformat()}",
            )
        )
    return InlineKeyboardMarkup([buttons])
