"""Turns a free-form Telegram message into a validated, typed intent.

The LLM is only ever asked to produce JSON matching one of the schemas in
``expense_ai.models.schemas``; this module owns the prompt, calls the LLM,
and validates the result so nothing malformed reaches the database layer.
"""

from __future__ import annotations

import datetime as dt
import logging

from pydantic import ValidationError

from expense_ai.config import settings
from expense_ai.llm import llm_client
from expense_ai.models.schemas import CATEGORIES, INTENT_MODELS, AnyIntent, UnknownIntent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are the intent-understanding engine for a personal finance Telegram bot.
The user writes casual, natural language (often in English or Uzbek/Russian
mixed in) describing money they spent, money they received, or a question
about their finances. Your ONLY job is to classify the message and extract
structured data as a single JSON object. Never reply in prose.

Today's date is {today} ({weekday}). The user's default currency is {currency}.
Valid expense categories (choose the single best match, or "Other"):
{categories}

Return JSON with a "type" field set to exactly one of:
- "expense": user spent money. Fields: amount (number, positive, in the
  currency mentioned or default), currency (ISO-ish code or symbol, e.g.
  "UZS", "USD"), category (one of the valid categories), description
  (short, e.g. "Groceries", "Taxi ride").
- "income": user received money (salary, freelance, gift, etc). Fields:
  amount, currency, description.
- "set_balance": user is declaring/correcting their actual real-world
  balance rather than reporting a transaction -- e.g. listing card/account
  totals ("I have two cards, 9710 card: 411k, 3901 card: 629k"), or saying
  "my balance is actually X", "I actually have X left". Fields:
  total_amount (sum every account/card mentioned into one number),
  currency, breakdown (short plain-text list of the accounts/amounts
  mentioned, e.g. "Card 9710: 411,000; Card 3901: 629,000", else "").
  Use this whenever the user is stating a real balance/total rather than
  a single spend or income event, even if the phrasing is unusual.
- "query": a read-only question about balance/spending/income. Fields:
  query_kind (one of: balance, summary, total_by_period, total_by_category,
  biggest_expenses, total_income, other), period (today, yesterday,
  this_week, this_month, last_month, all_time, custom), category (if
  asking about a specific category, else null), limit (integer, for
  "biggest expenses" style queries, default 5).
- "edit": user wants to modify a previous entry. Fields: target
  (last_expense, last_income, or search), keyword (to find the entry if
  target is "search", else null), new_amount, new_category,
  new_description (only the fields being changed; null otherwise).
- "delete": user wants to remove entries. Fields: target (last_expense,
  last_income, or search), keyword, period, category.
- "search": user wants to find/list past entries. Fields: keyword,
  min_amount, max_amount, period, category.
- "export": user wants their data exported. Fields: format (csv, xlsx,
  json, pdf), period.
- "chart": user wants a visual chart/graph. Fields: chart_type
  (category_pie, monthly_spending, weekly_spending, balance_over_time),
  period (this_week, this_month, last_month, all_time).
- "unknown": message doesn't match any of the above. Fields: reason.

Rules:
- If no currency is mentioned, use "{currency}".
- Numbers may use commas/dots/words like "million"/"k" (e.g. "6.5 million"
  -> 6500000, "85k" -> 85000). Always resolve to a plain number.
- This bot has exactly one user (its owner), so there is no risk of
  spam or abuse -- be generous, not suspicious. If a message is unusual,
  informal, or doesn't perfectly match the phrasing in these examples,
  still map it to the closest matching intent above rather than giving
  up. Only use "unknown" when the message truly isn't about money/finance
  at all (e.g. small talk, or a question you have no data for).
- Respond with raw JSON only, no markdown fences, no commentary.
"""


def _build_system_prompt() -> str:
    now = dt.datetime.now()
    return _SYSTEM_PROMPT_TEMPLATE.format(
        today=now.strftime("%Y-%m-%d"),
        weekday=now.strftime("%A"),
        currency=settings.default_currency,
        categories=", ".join(CATEGORIES),
    )


async def parse_message(text: str) -> AnyIntent:
    """Classify a user message and return a validated intent object.

    Falls back to ``UnknownIntent`` (rather than raising) whenever the LLM
    call fails or returns something that doesn't validate, so a single bad
    message never crashes the bot.
    """
    try:
        raw = await llm_client.complete_json(
            system_prompt=_build_system_prompt(),
            user_prompt=text,
        )
    except Exception as exc:
        logger.error("Intent parsing failed for message %r: %s", text, exc)
        return UnknownIntent(reason=f"LLM error: {exc}")

    intent_type = raw.get("type", "unknown")
    model = INTENT_MODELS.get(intent_type, UnknownIntent)
    try:
        return model.model_validate(raw)  # type: ignore[return-value]
    except ValidationError as exc:
        logger.warning("LLM output failed validation for message %r: %s\nraw=%s", text, exc, raw)
        return UnknownIntent(reason=f"Could not validate {intent_type} intent")
