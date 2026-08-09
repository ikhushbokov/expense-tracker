"""Tests for LLM-output validation via Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from expense_ai.models.schemas import ExpenseIntent, INTENT_MODELS, UnknownIntent


def test_expense_requires_positive_amount():
    with pytest.raises(ValidationError):
        ExpenseIntent(amount=-5, currency="UZS", category="Food")


def test_expense_category_passes_through_uncoerced():
    """Categories are dynamic now (fixed CATEGORIES + anything added via
    /category), which a stateless Pydantic validator can't know about --
    coercing an unknown category to "Other" is finance.coerce_category's
    job, run downstream once a DB session is available (dispatch.py,
    photo.py), not this schema's."""
    intent = ExpenseIntent(amount=1000, currency="uzs", category="NotARealCategory")
    assert intent.category == "NotARealCategory"
    assert intent.currency == "UZS"


def test_unrecognized_type_falls_back_to_unknown_model():
    model = INTENT_MODELS.get("not_a_type", UnknownIntent)
    assert model is UnknownIntent


def test_expense_missing_amount_raises():
    with pytest.raises(ValidationError):
        INTENT_MODELS["expense"].model_validate({"type": "expense", "currency": "UZS", "category": "Food"})
