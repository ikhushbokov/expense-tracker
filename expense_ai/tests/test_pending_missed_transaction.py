"""Tests for the pending missed-expense/income marker (used by the sync
"log missed expense/income" button while it waits for a description)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.database.models import PendingMissedTransaction


def test_pop_returns_none_when_none_set():
    with session_scope() as s:
        assert repository.pop_pending_missed_transaction(s, chat_id=1, max_age_seconds=600) is None


def test_pop_returns_data_when_fresh():
    with session_scope() as s:
        repository.mark_pending_missed_transaction(s, chat_id=1, kind="expense", amount=46000.0, currency="UZS")
    with session_scope() as s:
        pending = repository.pop_pending_missed_transaction(s, chat_id=1, max_age_seconds=600)
        assert pending is not None
        assert pending.kind == "expense"
        assert pending.amount == 46000.0
        assert pending.currency == "UZS"


def test_pop_consumes_the_marker():
    with session_scope() as s:
        repository.mark_pending_missed_transaction(s, chat_id=1, kind="income", amount=1000.0, currency="USD")
    with session_scope() as s:
        repository.pop_pending_missed_transaction(s, chat_id=1, max_age_seconds=600)
    with session_scope() as s:
        assert repository.pop_pending_missed_transaction(s, chat_id=1, max_age_seconds=600) is None


def test_pop_is_none_once_stale():
    with session_scope() as s:
        repository.mark_pending_missed_transaction(s, chat_id=1, kind="expense", amount=5000.0, currency="UZS")
        stale = s.query(PendingMissedTransaction).filter_by(chat_id=1).one()
        stale.created_at = dt.datetime.now() - dt.timedelta(seconds=700)
    with session_scope() as s:
        assert repository.pop_pending_missed_transaction(s, chat_id=1, max_age_seconds=600) is None


def test_mark_replaces_earlier_marker_for_same_chat():
    with session_scope() as s:
        repository.mark_pending_missed_transaction(s, chat_id=1, kind="expense", amount=1.0, currency="UZS")
        repository.mark_pending_missed_transaction(s, chat_id=1, kind="income", amount=2.0, currency="UZS")
    with session_scope() as s:
        assert s.query(PendingMissedTransaction).filter_by(chat_id=1).count() == 1
        pending = repository.pop_pending_missed_transaction(s, chat_id=1, max_age_seconds=600)
        assert pending.kind == "income"
        assert pending.amount == 2.0
