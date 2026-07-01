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
    # Which money bucket a "balance" question is about: the day-to-day
    # spendable "balance", the "savings" set aside, or "total" (both
    # combined / net worth). Only meaningful when query_kind == "balance".
    account: Literal["balance", "savings", "total"] = "balance"


class SetBalanceIntent(LLMIntentBase):
    """User is declaring/correcting their actual current balance or savings
    (e.g. listing card/account totals) rather than reporting a transaction.
    The bot reconciles the stored total for that account to this via a
    Transfer entry for the difference -- never as income/expense, since
    this is a correction, not something earned or spent."""

    type: Literal["set_balance"] = "set_balance"
    total_amount: float
    currency: str = "UZS"
    # Which bucket this correction applies to: "balance" (default -- day to
    # day spendable money, e.g. summed bank cards) or "savings" (money set
    # aside for a goal, not day-to-day spending).
    account: Literal["balance", "savings"] = "balance"
    breakdown: str = ""

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper().strip() if v else "UZS"


class TransferIntent(LLMIntentBase):
    """User wants to move money between their balance and savings, e.g.
    "transfer 200,000 from balance to savings" or "move 500k from savings
    to balance". Never a transaction against the outside world -- for that,
    use set_balance instead."""

    type: Literal["transfer"] = "transfer"
    from_account: Literal["balance", "savings"] = "balance"
    to_account: Literal["balance", "savings"] = "savings"
    amount: float = Field(gt=0)
    currency: str = "UZS"
    note: str = ""

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper().strip() if v else "UZS"


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
    | SetBalanceIntent
    | TransferIntent
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
    "set_balance": SetBalanceIntent,
    "transfer": TransferIntent,
    "edit": EditIntent,
    "delete": DeleteIntent,
    "search": SearchIntent,
    "chart": ChartIntent,
    "export": ExportIntent,
    "unknown": UnknownIntent,
}
