"""Tests for the caption check that routes a photo to balance-sync vs receipt OCR."""

from __future__ import annotations

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
