"""Tests for proactive scheduled messages (handlers/scheduled.py)."""

from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from expense_ai.config import settings
from expense_ai.database import repository, session_scope
from expense_ai.handlers.scheduled import (
    send_daily_summary,
    send_month_end_summary,
    send_monthly_reconciliation_prompt,
)

TODAY = dt.date.today()


@pytest.fixture(autouse=True)
def _owner_chat(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowed_user_id", 555)


def _mock_context():
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def test_send_daily_summary_reaches_owner_chat():
    with session_scope() as s:
        repository.add_expense(s, amount=15_000, currency="UZS", category="Food", description="Coffee")
    ctx = _mock_context()
    asyncio.run(send_daily_summary(ctx))
    ctx.bot.send_message.assert_awaited_once()
    _, kwargs = ctx.bot.send_message.call_args
    assert kwargs["chat_id"] == 555
    assert "Coffee" not in kwargs["text"]  # summary is totals, not line items
    assert "15,000 UZS" in kwargs["text"]


def test_send_daily_summary_includes_streak_when_no_spend_yesterday_onward():
    yesterday = TODAY - dt.timedelta(days=2)
    with session_scope() as s:
        repository.add_expense(
            s, amount=15_000, currency="UZS", category="Food",
            when=dt.datetime.combine(yesterday, dt.time(9, 0)),
        )
    ctx = _mock_context()
    asyncio.run(send_daily_summary(ctx))
    _, kwargs = ctx.bot.send_message.call_args
    assert "no-spend streak" in kwargs["text"]


def test_send_month_end_summary_includes_insights_when_available():
    last_month = (TODAY.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    with session_scope() as s:
        repository.add_expense(
            s, amount=100_000, currency="UZS", category="Food",
            when=dt.datetime.combine(last_month, dt.time(9, 0)),
        )
        repository.add_expense(
            s, amount=200_000, currency="UZS", category="Food",
            when=dt.datetime.combine(TODAY, dt.time(9, 0)),
        )
    ctx = _mock_context()
    asyncio.run(send_month_end_summary(ctx))
    _, kwargs = ctx.bot.send_message.call_args
    assert "Compared to last month" in kwargs["text"]


def test_send_monthly_reconciliation_prompt_reports_balances():
    with session_scope() as s:
        repository.add_income(s, amount=1_000_000, currency="UZS", description="Salary")
    ctx = _mock_context()
    asyncio.run(send_monthly_reconciliation_prompt(ctx))
    _, kwargs = ctx.bot.send_message.call_args
    assert "1,000,000 UZS" in kwargs["text"]
    assert "Still accurate?" in kwargs["text"]


def test_scheduled_messages_skipped_without_owner_chat_id(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowed_user_id", None)
    ctx = _mock_context()
    asyncio.run(send_daily_summary(ctx))
    ctx.bot.send_message.assert_not_awaited()
