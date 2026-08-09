"""Tests for the local-first parsers (expense_ai.local_parser).

Per CLAUDE.md's settings-singleton gotcha, local_parser_enabled isn't one
of the fields conftest.py's isolated_db fixture patches on the shared
original settings instance -- so rather than fight import-order ambiguity
about *which* settings object local_parser.py ended up bound to, these
tests monkeypatch the attribute directly on local_parser's own bound
`settings` reference (`local_parser.settings`), which is always the right
object regardless of when the module was first imported.
"""

from __future__ import annotations

import pytest

from expense_ai import local_parser
from expense_ai.database import repository, session_scope


@pytest.fixture(autouse=True)
def _enable_local_parser(monkeypatch):
    monkeypatch.setattr(local_parser.settings, "local_parser_enabled", True)


def _seed_history():
    # Each keyword appears at least twice -- a single occurrence isn't
    # treated as real evidence (_MIN_VOTES), matching the empirically
    # observed failure mode where a once-seen word guessed wrong.
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Transport", description="Taxi ride")
        repository.add_expense(s, amount=1, currency="UZS", category="Transport", description="Taxi")
        repository.add_expense(s, amount=1, currency="UZS", category="Food", description="Groceries")
        repository.add_expense(s, amount=1, currency="UZS", category="Food", description="Groceries run")
        repository.add_expense(s, amount=1, currency="UZS", category="Food", description="Dinner")
        repository.add_expense(s, amount=1, currency="UZS", category="Food", description="Cold drink")
        repository.add_expense(s, amount=1, currency="UZS", category="Entertainment", description="Football")
        repository.add_expense(s, amount=1, currency="UZS", category="Entertainment", description="Football match")


# --- expense ----------------------------------------------------------


def test_disabled_by_default_returns_none(monkeypatch):
    monkeypatch.setattr(local_parser.settings, "local_parser_enabled", False)
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "45000 taxi") is None


def test_plain_expense_resolves_amount_and_category():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45000 taxi")
    assert intent is not None
    assert intent.type == "expense"
    assert intent.amount == 45000
    assert intent.category == "Transport"
    assert intent.description == "Taxi"


def test_k_suffix_magnitude():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45k taxi")
    assert intent.amount == 45000


def test_m_suffix_magnitude():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "1.5m football sponsorship")
    assert intent.amount == 1_500_000


def test_comma_grouped_amount():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Spent 85,000 on groceries")
    assert intent.amount == 85000
    assert intent.category == "Food"


def test_explicit_currency_detected():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "50 usd taxi")
    assert intent.currency == "USD"


def test_default_currency_used_when_unspecified():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45000 taxi")
    assert intent.currency == local_parser.settings.default_currency


@pytest.mark.parametrize(
    "text",
    [
        "I have 2000000 on my cards",
        "My balance is 3000000",
        "Transfer 200000 from balance to savings",
        "I owe Vali 50000",
        "Loan payment due 100000",
        "Saving 1000000 for a laptop",
        "Change the 45000 expense to groceries",
        "How much did I spend this month?",
        "Delete the 200 usd from savings",
        "Export something confusing about a category",
    ],
)
def test_abstains_on_non_expense_signals(text):
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, text) is None


def test_abstains_with_no_amount():
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "Groceries") is None


def test_abstains_with_multiple_amounts():
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "45000 and 5000 for taxi") is None


def test_unresolvable_category_logs_as_other_unconfirmed():
    """No LLM fallback for an unresolvable category anymore -- log it now
    as "Other" and let dispatch.py attach a one-tap recategorize prompt
    instead of abstaining."""
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "82000 zzqxnotarealword")
    assert intent is not None
    assert intent.type == "expense"
    assert intent.category == "Other"
    assert intent.category_confirmed is False


def test_tied_category_vote_logs_as_other_unconfirmed():
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Food", description="snack")
        repository.add_expense(s, amount=1, currency="UZS", category="Shopping", description="snack")
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "12000 snack")
    assert intent is not None
    assert intent.category == "Other"
    assert intent.category_confirmed is False


def test_token_seen_once_logs_as_other_unconfirmed():
    """A word seen exactly once historically isn't real evidence -- found
    empirically: "paid" appeared once under "Other" and once under
    "Subscriptions" in real data, and single-occurrence votes guessed
    wrong both times. See _MIN_VOTES in local_parser.py."""
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Other", description="paid off my debt")
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "40000 SSTP paid app")
    assert intent is not None
    assert intent.category == "Other"
    assert intent.category_confirmed is False


def test_accepts_when_token_seen_at_least_twice():
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Subscriptions", description="paid app")
        repository.add_expense(s, amount=1, currency="UZS", category="Subscriptions", description="paid renewal")
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "40000 SSTP paid app")
    assert intent is not None
    assert intent.category == "Subscriptions"


def test_abstains_on_long_message():
    _seed_history()
    text = "45000 " + " ".join(["taxi"] * 15)
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, text) is None


def test_no_history_at_all_logs_as_other_unconfirmed():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45000 taxi")
    assert intent is not None
    assert intent.category == "Other"
    assert intent.category_confirmed is False


def test_explicit_trailing_category_works_with_zero_history():
    """The whole point of an explicit category word: no need for
    _MIN_VOTES worth of prior history, unlike inferred categorization."""
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45000 lunch food")
    assert intent is not None
    assert intent.category == "Food"
    assert intent.description == "Lunch"


def test_explicit_category_is_case_insensitive():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45000 lunch FOOD")
    assert intent.category == "Food"


def test_explicit_category_with_multi_word_description():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "1000000 university contract education")
    assert intent is not None
    assert intent.category == "Education"
    assert intent.description == "University contract"


def test_explicit_category_with_no_description_words_falls_back_to_category_name():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "45000 other")
    assert intent is not None
    assert intent.category == "Other"
    assert intent.description == "Other"


def test_trailing_word_that_is_not_a_category_falls_through_to_inference():
    """"drink" isn't one of CATEGORIES, so "cold drink" stays a single
    description phrase resolved via history, same as before this feature."""
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "20000 cold drink")
    assert intent is not None
    assert intent.category == "Food"
    assert intent.description == "Cold Drink"


# --- income -------------------------------------------------------------


def test_income_salary_trigger():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Salary came today: 6500000")
    assert intent is not None
    assert intent.type == "income"
    assert intent.amount == 6500000
    assert intent.description == "Salary came today"


def test_income_bonus_trigger():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Got a bonus of 500000")
    assert intent is not None
    assert intent.type == "income"
    assert intent.amount == 500000


def test_income_defaults_description_when_nothing_left():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Income 200000")
    assert intent is not None
    assert intent.type == "income"
    assert intent.description == "Income"


def test_income_abstains_without_amount():
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "Got paid today") is None


def test_paid_me_back_triggers_income():
    """Repayment is just income now (no separate settle_debt ledger) --
    "paid me back" unambiguously means money landing in your hands."""
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Aziz paid me back 300000")
    assert intent is not None
    assert intent.type == "income"
    assert intent.amount == 300000


def test_borrowed_triggers_income():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Borrowed 200000 from Vali")
    assert intent is not None
    assert intent.type == "income"
    assert intent.amount == 200000


# --- undo/delete last X --------------------------------------------------


def test_undo_last_expense_default_target():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Delete the last expense")
    assert intent is not None
    assert intent.type == "delete"
    assert intent.target == "last_expense"


def test_undo_last_income_target():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "undo the last income")
    assert intent.target == "last_income"


def test_undo_last_transfer_target():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "remove the last balance adjustment")
    assert intent.target == "last_transfer"


def test_undo_abstains_on_loan_mention():
    """No dedicated ledger for lending anymore, so there's no reliable way
    to tell "the last loan" apart from any other expense -- abstain
    rather than guess "last_expense" and maybe delete the wrong thing."""
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "delete the last loan") is None


def test_undo_abstains_without_last_or_previous():
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "delete that") is None


def test_undo_abstains_when_amount_mentioned():
    """A specific amount could mean disambiguating among several matching
    entries -- that needs the LLM, not a blind "the last one". (Must
    include "last" too, or this abstains via the blocklist for an
    unrelated reason and wouldn't actually exercise the digit guard.)"""
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "delete the last 200 usd transfer") is None


# --- export ---------------------------------------------------------------


def test_export_csv_default_period():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Export my data as csv")
    assert intent is not None
    assert intent.type == "export"
    assert intent.format == "csv"
    assert intent.period == "all_time"


def test_export_pdf_this_month():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "export this month as pdf")
    assert intent.format == "pdf"
    assert intent.period == "this_month"


def test_export_excel_word_maps_to_xlsx():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "export as excel")
    assert intent.format == "xlsx"


def test_export_abstains_without_explicit_format():
    with session_scope() as s:
        assert local_parser.try_parse_locally(s, "export my expenses") is None


# --- chart ------------------------------------------------------------


def test_chart_default_type_and_period():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "Show me a chart of my spending")
    assert intent is not None
    assert intent.type == "chart"
    assert intent.chart_type == "category_pie"
    assert intent.period == "this_month"


def test_chart_weekly_type():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "weekly spending chart")
    assert intent.chart_type == "weekly_spending"


def test_chart_balance_over_time_type():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "chart my balance trend")
    assert intent.chart_type == "balance_over_time"


def test_chart_last_month_period():
    with session_scope() as s:
        intent = local_parser.try_parse_locally(s, "pie chart for last month")
    assert intent.period == "last_month"
