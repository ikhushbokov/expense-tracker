"""Tests for lending/borrowing (database/models.py:Debt, handlers/debts.py)."""

from __future__ import annotations

from expense_ai.database import repository, session_scope
from expense_ai.finance import get_balances, open_debt_totals
from expense_ai.handlers.debts import handle_debt, handle_settle_debt, render_open_debts_text
from expense_ai.handlers.edit_search import handle_delete
from expense_ai.models.schemas import DebtIntent, DeleteIntent, SettleDebtIntent


def test_lending_reduces_balance():
    handle_debt(DebtIntent(person="Aziz", amount=300_000, currency="UZS", direction="lent"))
    with session_scope() as s:
        assert get_balances(s)["UZS"] == -300_000


def test_borrowing_increases_balance():
    handle_debt(DebtIntent(person="Vali", amount=200_000, currency="UZS", direction="borrowed"))
    with session_scope() as s:
        assert get_balances(s)["UZS"] == 200_000


def test_settling_a_lent_debt_restores_balance():
    handle_debt(DebtIntent(person="Aziz", amount=300_000, currency="UZS", direction="lent"))
    handle_settle_debt(SettleDebtIntent(person="Aziz"))
    with session_scope() as s:
        assert get_balances(s).get("UZS", 0.0) == 0.0


def test_settling_with_different_repay_amount():
    handle_debt(DebtIntent(person="Aziz", amount=300_000, currency="UZS", direction="lent"))
    handle_settle_debt(SettleDebtIntent(person="Aziz", amount=280_000))
    with session_scope() as s:
        # lent 300k out (-300k), got back 280k (+280k) -> net -20k
        assert get_balances(s)["UZS"] == -20_000


def test_open_debt_totals_grouped_by_direction():
    handle_debt(DebtIntent(person="Aziz", amount=300_000, currency="UZS", direction="lent"))
    handle_debt(DebtIntent(person="Vali", amount=200_000, currency="UZS", direction="borrowed"))
    with session_scope() as s:
        totals = open_debt_totals(s)
    assert totals["owed_to_me"]["UZS"] == 300_000
    assert totals["i_owe"]["UZS"] == 200_000


def test_settled_debt_excluded_from_open_totals():
    handle_debt(DebtIntent(person="Aziz", amount=300_000, currency="UZS", direction="lent"))
    handle_settle_debt(SettleDebtIntent(person="Aziz"))
    with session_scope() as s:
        totals = open_debt_totals(s)
    assert totals["owed_to_me"] == {}


def test_delete_last_debt_reverses_balance_effect():
    handle_debt(DebtIntent(person="Vali", amount=200_000, currency="UZS", direction="borrowed"))
    handle_delete(DeleteIntent(target="last_debt", keyword="Vali"))
    with session_scope() as s:
        assert get_balances(s) == {}
        assert repository.list_debts(s) == []


def test_render_open_debts_text_lists_both_directions():
    handle_debt(DebtIntent(person="Aziz", amount=300_000, currency="UZS", direction="lent"))
    handle_debt(DebtIntent(person="Vali", amount=200_000, currency="UZS", direction="borrowed"))
    with session_scope() as s:
        text = render_open_debts_text(s)
    assert "Aziz" in text
    assert "Vali" in text
    assert "Total owed to you: 300,000 UZS" in text
    assert "Total you owe: 200,000 UZS" in text


def test_render_open_debts_text_with_no_activity():
    with session_scope() as s:
        text = render_open_debts_text(s)
    assert "(none)" in text
