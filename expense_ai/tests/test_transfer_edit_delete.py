"""Tests for editing/deleting the last balance/savings adjustment or transfer."""

from __future__ import annotations

from expense_ai.database import repository, session_scope
from expense_ai.finance import get_balances, reconcile_balance, transfer_funds
from expense_ai.handlers.edit_search import handle_delete, handle_edit
from expense_ai.models.schemas import DeleteIntent, EditIntent


def test_delete_last_transfer_removes_a_mistaken_savings_correction():
    with session_scope() as s:
        reconcile_balance(s, total_amount=200, currency="USD", account="savings")

    with session_scope() as s:
        assert get_balances(s, account="savings") == {"USD": 200.0}

    reply = handle_delete(DeleteIntent(target="last_transfer"))
    assert "Deleted" in reply

    with session_scope() as s:
        assert get_balances(s, account="savings") == {}
        assert repository.list_transfers(s) == []


def test_edit_last_transfer_changes_amount():
    with session_scope() as s:
        reconcile_balance(s, total_amount=200, currency="USD", account="savings")

    reply = handle_edit(EditIntent(target="last_transfer", new_amount=500))
    assert "updated" in reply.lower()

    with session_scope() as s:
        assert get_balances(s, account="savings") == {"USD": 500.0}


def test_delete_last_transfer_after_real_transfer():
    with session_scope() as s:
        reconcile_balance(s, total_amount=1_000_000, currency="UZS", account="balance")

    with session_scope() as s:
        transfer_funds(s, from_account="balance", to_account="savings", amount=200_000, currency="UZS")

    reply = handle_delete(DeleteIntent(target="last_transfer"))
    assert "Deleted" in reply

    with session_scope() as s:
        # The real transfer is undone; only the original balance correction remains.
        assert get_balances(s, account="balance") == {"UZS": 1_000_000.0}
        assert get_balances(s, account="savings") == {}


def test_delete_last_transfer_when_none_exist():
    reply = handle_delete(DeleteIntent(target="last_transfer"))
    assert "don't have any" in reply.lower()


def test_edit_last_transfer_when_none_exist():
    reply = handle_edit(EditIntent(target="last_transfer", new_amount=100))
    assert "don't have any" in reply.lower()
