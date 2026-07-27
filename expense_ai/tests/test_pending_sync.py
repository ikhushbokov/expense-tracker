"""Tests for the pending-sync marker (used by /sync to arm the next photo)."""

from __future__ import annotations

import datetime as dt

from expense_ai.database import repository, session_scope
from expense_ai.database.models import PendingSync


def test_pop_pending_sync_returns_false_when_none_set():
    with session_scope() as s:
        assert repository.pop_pending_sync(s, chat_id=1, max_age_seconds=600) is False


def test_pop_pending_sync_returns_true_when_fresh():
    with session_scope() as s:
        repository.mark_pending_sync(s, chat_id=1)
    with session_scope() as s:
        assert repository.pop_pending_sync(s, chat_id=1, max_age_seconds=600) is True


def test_pop_pending_sync_consumes_the_marker():
    with session_scope() as s:
        repository.mark_pending_sync(s, chat_id=1)
    with session_scope() as s:
        repository.pop_pending_sync(s, chat_id=1, max_age_seconds=600)
    with session_scope() as s:
        # A second photo right after shouldn't also count as a sync.
        assert repository.pop_pending_sync(s, chat_id=1, max_age_seconds=600) is False


def test_pop_pending_sync_is_false_once_stale():
    with session_scope() as s:
        repository.mark_pending_sync(s, chat_id=1)
        stale = s.query(PendingSync).filter_by(chat_id=1).one()
        stale.created_at = dt.datetime.now() - dt.timedelta(seconds=700)
    with session_scope() as s:
        assert repository.pop_pending_sync(s, chat_id=1, max_age_seconds=600) is False


def test_mark_pending_sync_replaces_earlier_marker_for_same_chat():
    with session_scope() as s:
        repository.mark_pending_sync(s, chat_id=1)
        repository.mark_pending_sync(s, chat_id=1)
    with session_scope() as s:
        assert s.query(PendingSync).filter_by(chat_id=1).count() == 1


def test_pending_sync_is_scoped_per_chat():
    with session_scope() as s:
        repository.mark_pending_sync(s, chat_id=1)
    with session_scope() as s:
        assert repository.pop_pending_sync(s, chat_id=2, max_age_seconds=600) is False
    with session_scope() as s:
        # chat 1's marker is untouched by the chat-2 lookup above.
        assert repository.pop_pending_sync(s, chat_id=1, max_age_seconds=600) is True
