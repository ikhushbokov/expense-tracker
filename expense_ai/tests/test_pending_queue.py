"""Tests for the pending-message queue (used when the LLM is unreachable)."""

from __future__ import annotations

from expense_ai.database import repository, session_scope


def test_enqueue_and_list_pending_messages():
    with session_scope() as s:
        repository.enqueue_pending_message(s, chat_id=111, text="Spent 5000 on coffee")
        repository.enqueue_pending_message(s, chat_id=111, text="Salary 100000")
    with session_scope() as s:
        pending = repository.list_pending_messages(s)
        assert len(pending) == 2
        assert pending[0].text == "Spent 5000 on coffee"


def test_delete_pending_message():
    with session_scope() as s:
        item = repository.enqueue_pending_message(s, chat_id=111, text="test")
        item_id = item.id
    with session_scope() as s:
        assert repository.delete_pending_message(s, item_id) is True
    with session_scope() as s:
        assert repository.list_pending_messages(s) == []


def test_increment_pending_attempts():
    with session_scope() as s:
        item = repository.enqueue_pending_message(s, chat_id=111, text="test")
        item_id = item.id
    with session_scope() as s:
        repository.increment_pending_attempts(s, item_id)
        repository.increment_pending_attempts(s, item_id)
    with session_scope() as s:
        pending = repository.list_pending_messages(s)
        assert pending[0].attempts == 2


def test_ordered_by_creation_time():
    with session_scope() as s:
        repository.enqueue_pending_message(s, chat_id=1, text="first")
        repository.enqueue_pending_message(s, chat_id=1, text="second")
    with session_scope() as s:
        pending = repository.list_pending_messages(s)
        assert [p.text for p in pending] == ["first", "second"]


def test_kind_defaults_to_text():
    with session_scope() as s:
        repository.enqueue_pending_message(s, chat_id=1, text="Spent 5000 on coffee")
    with session_scope() as s:
        assert repository.list_pending_messages(s)[0].kind == "text"


def test_kind_can_be_set_to_balance_sync():
    with session_scope() as s:
        repository.enqueue_pending_message(s, chat_id=1, text="OCR'd screenshot text", kind="balance_sync")
    with session_scope() as s:
        assert repository.list_pending_messages(s)[0].kind == "balance_sync"
