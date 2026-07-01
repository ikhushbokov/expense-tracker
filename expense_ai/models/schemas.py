"""Pydantic schemas describing the structured JSON the LLM must return.

The bot never trusts free-form LLM text for anything actionable — every
response is validated against one of these models before it touches the
database.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CATEGORIES: list[str] = [
    "Food",
    "Transport",
    "Gym",
    "Supplements",
    "Health",
    "Entertainment",
    "Shopping",
    "Education",
    "Bills",
    "Rent",
    "Coffee",
    "Restaurants",
    "Electronics",
    "Subscriptions",
    "Travel",
    "Family",
    "Gifts",
    "Other",
]

IntentType = Literal[
    "expense",
    "income",
    "query",
    "edit",
    "delete",
    "search",
    "export",
    "unknown",
]


class LLMIntentBase(BaseModel):
    """Base for all intent models: treats explicit JSON ``null`` the same as
    an absent key, so fields with non-None defaults (e.g. ``period``) fall
    back correctly instead of failing validation when the LLM writes
    ``"period": null`` for a field it considers not applicable."""

    @model_validator(mode="before")
    @classmethod
    def _drop_none_values(cls, data: object) -> object:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class ExpenseIntent(LLMIntentBase):
    type: Literal["expense"] = "expense"
    amount: float = Field(gt=0)
    currency: str = "UZS"
    category: str = "Other"
    description: str = ""

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        return v if v in CATEGORIES else "Other"

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper().strip() if v else "UZS"


class IncomeIntent(LLMIntentBase):
    type: Literal["income"] = "income"
    amount: float = Field(gt=0)
    currency: str = "UZS"
    description: str = ""

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper().strip() if v else "UZS"


class QueryIntent(LLMIntentBase):
    """A read-only natural language question (balance, summary, totals...)."""

    type: Literal["query"] = "query"
    query_kind: Literal[
        "balance",
        "summary",
        "total_by_period",
        "total_by_category",
        "biggest_expenses",
        "total_income",
        "other",
    ] = "other"
    period: Literal["today", "yesterday", "this_week", "this_month", "last_month", "all_time", "custom"] = "all_time"
    category: str | None = None
    custom_start: dt.date | None = None
    custom_end: dt.date | None = None
    limit: int = 5


class EditIntent(LLMIntentBase):
    type: Literal["edit"] = "edit"
    target: Literal["last_expense", "last_income", "search"] = "last_expense"
    keyword: str | None = None
    new_amount: float | None = None
    new_category: str | None = None
    new_description: str | None = None

    @field_validator("new_category")
    @classmethod
    def _known_category(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v if v in CATEGORIES else "Other"


class DeleteIntent(LLMIntentBase):
    type: Literal["delete"] = "delete"
    target: Literal["last_expense", "last_income", "search"] = "last_expense"
    keyword: str | None = None
    period: Literal["today", "yesterday", "this_week", "this_month", "all_time"] = "all_time"
    category: str | None = None


class SearchIntent(LLMIntentBase):
    type: Literal["search"] = "search"
    keyword: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    period: Literal["today", "yesterday", "this_week", "this_month", "all_time"] = "all_time"
    category: str | None = None


class ExportIntent(LLMIntentBase):
    type: Literal["export"] = "export"
    format: Literal["csv", "xlsx", "json", "pdf"] = "csv"
    period: Literal["this_week", "this_month", "last_month", "all_time"] = "all_time"


class ChartIntent(LLMIntentBase):
    type: Literal["chart"] = "chart"
    chart_type: Literal[
        "category_pie", "monthly_spending", "weekly_spending", "balance_over_time"
    ] = "category_pie"
    period: Literal["this_week", "this_month", "last_month", "all_time"] = "this_month"


class UnknownIntent(LLMIntentBase):
    type: Literal["unknown"] = "unknown"
    reason: str = ""


AnyIntent = (
    ExpenseIntent
    | IncomeIntent
    | QueryIntent
    | EditIntent
    | DeleteIntent
    | SearchIntent
    | ExportIntent
    | ChartIntent
    | UnknownIntent
)

INTENT_MODELS: dict[str, type[BaseModel]] = {
    "expense": ExpenseIntent,
    "income": IncomeIntent,
    "query": QueryIntent,
    "edit": EditIntent,
    "delete": DeleteIntent,
    "search": SearchIntent,
    "chart": ChartIntent,
    "export": ExportIntent,
    "unknown": UnknownIntent,
}
