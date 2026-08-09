"""Tests for the caption check that routes a photo to balance-sync vs receipt OCR,
and for build_sync_mismatch_response's Python-side summation (given a
cards-screenshot data URL -- the LLM only ever lists individual balances)."""

from __future__ import annotations

import asyncio

from expense_ai.database import session_scope
from expense_ai.finance import reconcile_balance
from expense_ai.handlers import balance_sync
from expense_ai.handlers.balance_sync import is_sync_photo


def test_matches_plain_sync_caption():
    assert is_sync_photo("sync")


def test_matches_slash_command_style_caption():
    assert is_sync_photo("/sync")


def test_matches_case_insensitively_with_trailing_words():
    assert is_sync_photo("Sync my cards please")


def test_no_caption_is_not_a_sync():
    assert not is_sync_photo(None)
    assert not is_sync_photo("")


def test_receipt_style_caption_is_not_a_sync():
    assert not is_sync_photo("lunch with team")


class _FakeLLMClient:
    """Stands in for expense_ai.llm.llm_client: returns a fixed
    {"amounts": [...], "currency": ...} instead of calling out. Accepts
    (and ignores) image_data_url/response_schema so it matches
    complete_json's real signature."""

    def __init__(self, amounts, currency="UZS"):
        self._amounts = amounts
        self._currency = currency

    async def complete_json(self, system_prompt, user_prompt, temperature=0.1, image_data_url=None, response_schema=None):
        return {"amounts": self._amounts, "currency": self._currency}


_DUMMY_IMAGE_DATA_URL = "data:image/jpeg;base64,dGVzdA=="


def test_sums_extracted_amounts_in_python_not_via_llm(monkeypatch):
    """The exact real-incident regression check: the LLM lists each card
    balance (never asked to add them), and Python computes the total --
    this is the fix for a wrong LLM-computed total that hit production
    twice. 968.32 + 15,181.58 + 1,484,109.58 + 1,054,826.06 = 2,555,085.54."""
    amounts = [968.32, 15181.58, 1484109.58, 1054826.06]
    monkeypatch.setattr(balance_sync, "llm_client", _FakeLLMClient(amounts))

    with session_scope() as s:
        reconcile_balance(s, total_amount=1669486.20, currency="UZS", account="balance")

    text, markup = asyncio.run(balance_sync.build_sync_mismatch_response(_DUMMY_IMAGE_DATA_URL))
    assert "2,555,085.54" in text
    assert markup is not None


def test_no_amounts_found_abstains_gracefully(monkeypatch):
    monkeypatch.setattr(balance_sync, "llm_client", _FakeLLMClient([]))

    text, markup = asyncio.run(balance_sync.build_sync_mismatch_response(_DUMMY_IMAGE_DATA_URL))
    assert "couldn't confidently total" in text
    assert markup is None
