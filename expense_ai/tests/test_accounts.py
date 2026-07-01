"""Tests for the balance/savings account model: reconciliation, transfers,
and that neither pollutes income/expense period reporting."""

from __future__ import annotations

from expense_ai.database import repository, session_scope
from expense_ai.finance import (
    get_balances,
    get_net_worth,
    reconcile_balance,
    total_expenses_by_currency,
    total_income_by_currency,
    transfer_funds,
)


def test_reconcile_balance_does_not_count_as_income():
    with session_scope() as s:
        repository.add_expense(s, amount=60_000, currency="UZS", category="Food")

    with session_scope() as s:
        delta = reconcile_balance(s, total_amount=1_040_000, currency="UZS", note="two cards")
        assert delta == 1_100_000

    with session_scope() as s:
        assert get_balances(s, account="balance") == {"UZS": 1_040_000.0}
        # The correction must not show up as income anywhere.
        assert total_income_by_currency(s) == {}
        assert total_expenses_by_currency(s) == {"UZS": 60_000.0}


def test_reconcile_balance_negative_delta():
    with session_scope() as s:
        repository.add_income(s, amount=500_000, currency="UZS")

    with session_scope() as s:
        delta = reconcile_balance(s, total_amount=100_000, currency="UZS")
        assert delta == -400_000

    with session_scope() as s:
        assert get_balances(s, account="balance") == {"UZS": 100_000.0}


def test_reconcile_balance_noop_when_already_matching():
    with session_scope() as s:
        repository.add_income(s, amount=100_000, currency="UZS")

    with session_scope() as s:
        delta = reconcile_balance(s, total_amount=100_000, currency="UZS")
        assert delta == 0.0


def test_savings_independent_of_balance():
    with session_scope() as s:
        reconcile_balance(s, total_amount=1_000_000, currency="UZS", account="balance")
        reconcile_balance(s, total_amount=300_000, currency="UZS", account="savings")

    with session_scope() as s:
        assert get_balances(s, account="balance") == {"UZS": 1_000_000.0}
        assert get_balances(s, account="savings") == {"UZS": 300_000.0}


def test_transfer_moves_money_without_changing_net_worth():
    with session_scope() as s:
        reconcile_balance(s, total_amount=1_000_000, currency="UZS", account="balance")

    with session_scope() as s:
        net_worth_before = get_net_worth(s)
        transfer_funds(s, from_account="balance", to_account="savings", amount=200_000, currency="UZS")

    with session_scope() as s:
        assert get_balances(s, account="balance") == {"UZS": 800_000.0}
        assert get_balances(s, account="savings") == {"UZS": 200_000.0}
        assert get_net_worth(s) == net_worth_before


def test_net_worth_combines_balance_and_savings():
    with session_scope() as s:
        reconcile_balance(s, total_amount=700_000, currency="UZS", account="balance")
        reconcile_balance(s, total_amount=300_000, currency="UZS", account="savings")

    with session_scope() as s:
        assert get_net_worth(s) == {"UZS": 1_000_000.0}
