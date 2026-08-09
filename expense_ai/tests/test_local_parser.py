"""Tests for the local-first expense parser (expense_ai.local_parser).

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


def test_disabled_by_default_returns_none(monkeypatch):
    monkeypatch.setattr(local_parser.settings, "local_parser_enabled", False)
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "45000 taxi") is None


def test_plain_expense_resolves_amount_and_category():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "45000 taxi")
    assert intent is not None
    assert intent.type == "expense"
    assert intent.amount == 45000
    assert intent.category == "Transport"
    assert intent.description == "Taxi"


def test_k_suffix_magnitude():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "45k taxi")
    assert intent.amount == 45000


def test_m_suffix_magnitude():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "1.5m football sponsorship")
    assert intent.amount == 1_500_000


def test_comma_grouped_amount():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "Spent 85,000 on groceries")
    assert intent.amount == 85000
    assert intent.category == "Food"


def test_explicit_currency_detected():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "50 usd taxi")
    assert intent.currency == "USD"


def test_default_currency_used_when_unspecified():
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "45000 taxi")
    assert intent.currency == local_parser.settings.default_currency


@pytest.mark.parametrize(
    "text",
    [
        "Salary came today: 6500000",
        "I have 2000000 on my cards",
        "My balance is 3000000",
        "Transfer 200000 from balance to savings",
        "Lent 50000 to Aziz",
        "Borrowed 200000 from Vali",
        "Aziz paid me back 300000",
        "Saving 1000000 for a laptop",
        "Change the 45000 expense to groceries",
        "Delete the last expense",
        "How much did I spend this month?",
        "Export my data as csv",
        "Show me a chart of my spending",
    ],
)
def test_abstains_on_non_expense_signals(text):
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, text) is None


def test_abstains_with_no_amount():
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "Groceries") is None


def test_abstains_with_multiple_amounts():
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "45000 and 5000 for taxi") is None


def test_abstains_on_unseen_vocabulary():
    _seed_history()
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "82000 zzqxnotarealword") is None


def test_abstains_on_tied_category_vote():
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Food", description="snack")
        repository.add_expense(s, amount=1, currency="UZS", category="Shopping", description="snack")
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "12000 snack") is None


def test_abstains_when_only_token_seen_once():
    """A word seen exactly once historically isn't real evidence -- found
    empirically: "paid" appeared once under "Other" and once under
    "Subscriptions" in real data, and single-occurrence votes guessed
    wrong both times. See _MIN_VOTES in local_parser.py."""
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Other", description="paid off my debt")
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "40000 SSTP paid app") is None


def test_accepts_when_token_seen_at_least_twice():
    with session_scope() as s:
        repository.add_expense(s, amount=1, currency="UZS", category="Subscriptions", description="paid app")
        repository.add_expense(s, amount=1, currency="UZS", category="Subscriptions", description="paid renewal")
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "40000 SSTP paid app")
    assert intent is not None
    assert intent.category == "Subscriptions"


def test_abstains_on_long_message():
    _seed_history()
    text = "45000 " + " ".join(["taxi"] * 15)
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, text) is None


def test_abstains_with_no_history_at_all():
    with session_scope() as s:
        assert local_parser.try_parse_expense_locally(s, "45000 taxi") is None


def test_explicit_trailing_category_works_with_zero_history():
    """The whole point of an explicit category word: no need for
    _MIN_VOTES worth of prior history, unlike inferred categorization."""
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "45000 lunch food")
    assert intent is not None
    assert intent.category == "Food"
    assert intent.description == "Lunch"


def test_explicit_category_is_case_insensitive():
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "45000 lunch FOOD")
    assert intent.category == "Food"


def test_explicit_category_with_multi_word_description():
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "1000000 university contract education")
    assert intent is not None
    assert intent.category == "Education"
    assert intent.description == "University contract"


def test_explicit_category_with_no_description_words_falls_back_to_category_name():
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "45000 other")
    assert intent is not None
    assert intent.category == "Other"
    assert intent.description == "Other"


def test_trailing_word_that_is_not_a_category_falls_through_to_inference():
    """"drink" isn't one of CATEGORIES, so "cold drink" stays a single
    description phrase resolved via history, same as before this feature."""
    _seed_history()
    with session_scope() as s:
        intent = local_parser.try_parse_expense_locally(s, "20000 cold drink")
    assert intent is not None
    assert intent.category == "Food"
    assert intent.description == "Cold Drink"
