"""Cheap, deterministic local parsers tried before the LLM for a handful of
common, unambiguous message shapes: a plain expense ("45k taxi"), income
("Salary came today: 6,500,000"), "undo/delete the last X", export, and
chart requests.

Model: the LLM should be the *fallback*, not the front door. Measured
against this bot's own history, roughly 80% of expense messages use a
vocabulary of a few dozen words with zero category ambiguity -- "taxi",
"groceries", "football" each map to exactly one category, unanimously,
every single time they've been logged. Handling those locally means no
network round-trip, no cost, and it keeps working through an LLM-provider
outage. More importantly, the field that actually matters for correctness
-- the amount -- is extracted by regex instead of asked of a model that
has, twice in one week on this exact bot, gotten arithmetic wrong.

Every parser here is intentionally narrow and paranoid about false
positives: it abstains (returns None, falling through to
parse_message()/the LLM) whenever anything looks even slightly ambiguous
or like a different intent. A wrong ABSTAIN just costs one ordinary LLM
call. A wrong ACCEPT writes bad data (or deletes/exports the wrong thing)
-- so each one only ever fires on its own safe, unambiguous case.
Deliberately NOT covered, and why:
  - transfer: near-zero real usage in this bot's history (one real
    transfer ever) -- not worth the design and test effort for something
    practically unused.
  - edit, search, free-text query, set_balance-by-text: all need
    semantic judgment (which past entry does "the coffee expense" mean?
    what does "how much did I spend" actually want?) -- this is where an
    LLM's reasoning is doing real work, not just being expensive glue.
  - history: already has a zero-LLM path (the /history command), so the
    free-text version isn't worth building too.
Lending/borrowing money isn't its own category here at all anymore --
per an explicit product decision, it's just a plain expense (lending) or
income (getting repaid/borrowing), same as any other. There's no
person-name extraction to get right, because there's no separate ledger
that needs a name to look someone's balance up in.

One explicit convention on top of the expense parser's inferred-from-
history path: if the LAST word left after the amount is removed exactly
names a *known* category (case-insensitively -- "food", "Food", "FOOD"
all count) -- the fixed CATEGORIES list, or anything added via /category
-- it's taken as an explicit category override rather than fed into the
keyword vote, and everything before it becomes the description. This
skips _MIN_VOTES/tie-breaking entirely (there's no ambiguity to guess
about when the user just said the category), so it works even with zero
prior history -- "45k lunch food" resolves locally the very first time,
not just once "lunch" has been seen twice. New categories themselves are
never invented here, or by the LLM -- see finance.known_categories'
docstring -- only /category creates one, explicitly, on request.

When an expense's category genuinely can't be resolved (new vocabulary,
no explicit category word), _try_expense doesn't abstain either: it logs
as "Other" with category_confirmed=False, so dispatch.py attaches a
one-tap recategorize prompt instead of asking the LLM to guess. This is
what makes lending money ("Gave Aziz 300,000") work locally on the very
first use, with no LLM call at all.

Gated behind settings.local_parser_enabled so it can be A/B'd against
real messages before being trusted -- see dispatch.py's build_response(),
the only call site.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from expense_ai.database import repository
from expense_ai.config import settings
from expense_ai.finance import known_categories
from expense_ai.models.schemas import (
    AnyIntent,
    ChartIntent,
    DeleteIntent,
    ExpenseIntent,
    ExportIntent,
    IncomeIntent,
)

# Substrings that strongly suggest a different intent than a plain expense --
# if any of these appear, abstain rather than guess. Mined from the exact
# phrasing parser.py's own prompt documents for each intent, since that's
# the closest thing to ground truth for how the LLM is told to tell them
# apart. Checked against the message padded with a leading/trailing space,
# so entries with surrounding spaces still match at the very start/end.
# Income-ish phrasing ("salary", "got paid", "borrowed", "paid me back",
# ...) isn't here anymore -- it's a positive trigger for _try_income below
# instead, now that there's no settle_debt intent left for it to be
# ambiguous with. "owe"/"loan" stay here since they read more like a
# state ("I owe Vali") than an event -- not confidently one direction or
# the other. Similarly "delete"/"remove"/"undo" and "export"/"chart"/etc.
# stay here too: _try_undo_last/_try_export/_try_chart handle the
# confident, simple case earlier, and this list is what stops anything
# more complex from falling through and being misread as a brand new
# expense instead of reaching the LLM.
_NON_EXPENSE_SIGNALS: tuple[str, ...] = (
    # set_balance -- a *state*, not an event; must never be read as an expense
    " i have", "i've got", "i actually have", "actual balance", "my balance",
    "balance is", "total is", "saved up", "on my card",
    # transfer
    " transfer", " move ", "into savings", "from balance", "from savings",
    # ambiguous-direction debt phrasing -- not confidently expense or income
    " owe", "loan",
    # savings_goal doesn't exist as an intent anymore, but "savings goal" /
    # "my goal" is a statement of intent, not a transaction -- still not an
    # expense. "saving <amount> for <thing>" is handled separately by
    # _mentions_saving_for below, since the amount sitting between "saving"
    # and "for" means a plain substring check here would miss it.
    "savings goal", "my goal",
    # edit / delete / search
    "actually it was", "should be", "change the", "rename", "correct the",
    "delete", "remove", "undo", "find the", "search for", "list my",
    # export / chart / history
    "export", " csv", "xlsx", " pdf", "chart", "graph", "history",
    # query
    "how much", "what did", "what's my", "when did", "why did",
)

_INCOME_TRIGGERS: tuple[str, ...] = (
    "salary", "got paid", "payment came", "freelance", "income", "bonus",
    # repayment/borrowing: money landing in your hands, whichever way
    "paid me back", "paid me", "borrowed",
)

_EXPORT_FORMAT_WORDS: tuple[tuple[str, str], ...] = (
    ("csv", "csv"), ("xlsx", "xlsx"), ("excel", "xlsx"), ("json", "json"), ("pdf", "pdf"),
)

_CHART_TYPE_WORDS: tuple[tuple[str, str], ...] = (
    ("pie", "category_pie"), ("category", "category_pie"),
    ("weekly", "weekly_spending"), ("monthly", "monthly_spending"),
    ("net worth", "balance_over_time"), ("trend", "balance_over_time"), ("balance", "balance_over_time"),
)

_MAGNITUDE = {"k": 1_000, "m": 1_000_000, "thousand": 1_000, "million": 1_000_000}

_CURRENCY_WORDS = {
    "usd": "USD", "$": "USD", "dollars": "USD", "dollar": "USD",
    "uzs": "UZS", "sum": "UZS", "so'm": "UZS", "som": "UZS",
    "eur": "EUR", "€": "EUR", "euros": "EUR",
    "rub": "RUB", "₽": "RUB",
}

# One amount token: plain/grouped digits with an optional decimal part,
# optionally followed by a k/m/thousand/million magnitude word.
_AMOUNT_RE = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k|m|thousand|million)?(?![\w])",
    re.IGNORECASE,
)

_MAX_WORDS = 10

# A word seen exactly once historically isn't real evidence -- e.g. "paid"
# showed up once each under "Other" ("paid off my debt") and "Subscriptions"
# ("SSTP paid app") in this bot's own data, and single-occurrence votes on
# either side guessed the other one's category with total confidence. This
# was found empirically (leave-one-out validation against real history),
# not chosen a priori.
_MIN_VOTES = 2


def _extract_amount(text: str) -> tuple[float, str] | None:
    """(amount, remaining_text_with_amount_removed), or None if zero or
    more than one amount-like token is found -- too ambiguous to guess."""
    matches = list(_AMOUNT_RE.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = match.group(2)
    if suffix:
        number *= _MAGNITUDE[suffix.lower()]
    if number <= 0:
        return None
    remaining = text[: match.start()] + text[match.end() :]
    return number, remaining


def _mentions_saving_for(padded: str) -> bool:
    """"Saving 1,000,000 for a laptop" -- a statement of intent, not a
    transaction. A plain substring check for "saving for" would miss this
    since the amount sits between the two words; check word-presence
    instead of contiguous text."""
    return ("saving" in padded or "save" in padded or "saved" in padded) and " for " in padded


def _detect_currency(text: str) -> str | None:
    lowered = text.lower()
    for word, code in _CURRENCY_WORDS.items():
        if word in lowered:
            return code
    return None


def _clean_description(text: str) -> str:
    """Collapse the double space/stray punctuation left over when an
    amount gets removed from the *middle* of a sentence (e.g. "Gave Aziz
    300000, he'll pay me back" -> "Gave Aziz , he'll..." before this),
    then trim the ends and capitalize the first letter."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[\s:,.\-]+|[\s:,.\-]+$", "", text)
    text = re.sub(r"\s+,", ",", text)
    return text[0].upper() + text[1:] if text else ""


def _split_explicit_category(session: Session, remaining_text: str) -> tuple[str, str] | None:
    """If the last word of ``remaining_text`` exactly names a known
    category (case-insensitive) -- fixed CATEGORIES, or anything added
    via /category -- split it off as an explicit category override.
    Returns (category, description) with that word removed and the rest
    capitalized, or None if the last word doesn't name a category --
    callers fall through to history-based inference."""
    words = remaining_text.split()
    if not words:
        return None
    last_word = re.sub(r"[^\w']", "", words[-1]).lower()
    category_by_lower = {c.lower(): c for c in known_categories(session)}
    category = category_by_lower.get(last_word)
    if category is None:
        return None
    description = _clean_description(" ".join(words[:-1]))
    return category, (description or category)


def _build_category_keyword_map(session: Session) -> dict[str, Counter]:
    """token -> {category: times this user's own history used it for that
    category}. Rebuilt fresh each call: at personal-bot volume (a couple
    messages a day, a few hundred expenses total) this is sub-millisecond,
    so there's no real caching/invalidation problem to solve here."""
    keywords: dict[str, Counter] = defaultdict(Counter)
    for expense in repository.list_expenses(session):
        for token in re.findall(r"[a-z']+", (expense.description or "").lower()):
            if len(token) > 2:
                keywords[token][expense.category] += 1
    return keywords


def _resolve_category(session: Session, remaining_text: str) -> tuple[str, str] | None:
    """(category, description) from this user's own history-derived
    keyword voting, or None to abstain: no token in the remaining text is
    in the learned vocabulary (genuinely new wording), the vote is tied
    between two categories, or the total evidence is too thin (a word
    seen exactly once isn't a real signal -- see _MIN_VOTES)."""
    tokens = [t for t in re.findall(r"[a-z']+", remaining_text.lower()) if len(t) > 2]
    if not tokens:
        return None

    keywords = _build_category_keyword_map(session)
    votes: Counter = Counter()
    matched_tokens: list[str] = []
    for token in tokens:
        if token in keywords:
            matched_tokens.append(token)
            votes.update(keywords[token])

    if not votes or sum(votes.values()) < _MIN_VOTES:
        return None

    top = votes.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None  # tied vote -- don't guess, let the LLM disambiguate

    category = top[0][0]
    description = " ".join(w.capitalize() for w in matched_tokens)
    return category, description


def _try_expense(session: Session, stripped: str) -> ExpenseIntent | None:
    extracted = _extract_amount(stripped)
    if extracted is None:
        return None
    amount, remaining = extracted

    currency = _detect_currency(stripped) or settings.default_currency

    explicit = _split_explicit_category(session, remaining)
    if explicit is not None:
        category, description = explicit
        return ExpenseIntent(amount=amount, currency=currency, category=category, description=description)

    resolved = _resolve_category(session, remaining)
    if resolved is not None:
        category, description = resolved
        return ExpenseIntent(amount=amount, currency=currency, category=category, description=description)

    # Confirmed to be a plain expense (single amount, none of the other-
    # intent signals below matched) but the category genuinely can't be
    # resolved -- log it now as "Other" rather than asking the LLM to
    # guess; dispatch.py attaches a one-tap recategorize prompt since
    # category_confirmed=False.
    description = _clean_description(remaining) or "Expense"
    return ExpenseIntent(
        amount=amount, currency=currency, category="Other", description=description, category_confirmed=False
    )


def _try_income(stripped: str, padded: str) -> IncomeIntent | None:
    if not any(trigger in padded for trigger in _INCOME_TRIGGERS):
        return None
    extracted = _extract_amount(stripped)
    if extracted is None:
        return None
    amount, remaining = extracted
    currency = _detect_currency(stripped) or settings.default_currency
    description = _clean_description(remaining) or "Income"
    return IncomeIntent(amount=amount, currency=currency, description=description)


def _try_undo_last(padded: str) -> DeleteIntent | None:
    """Only the simple, unambiguous "undo/delete the last X" case -- any
    mention of a specific amount/currency means there could be more than
    one matching entry to disambiguate, which needs the LLM (or you,
    being more specific)."""
    if not any(word in padded for word in ("delete", "undo", "remove")):
        return None
    if "last" not in padded and "previous" not in padded:
        return None
    if any(ch.isdigit() for ch in padded):
        return None
    if "loan" in padded or "debt" in padded:
        # Lending/borrowing is just an Expense/Income row now, not its own
        # ledger -- there's no reliable way to tell "the last one" apart
        # from any other expense without a keyword search, so let the LLM
        # (which can build a "search"-targeted delete) handle this instead
        # of guessing "last_expense" and maybe deleting the wrong thing.
        return None

    if "income" in padded:
        target = "last_income"
    elif any(word in padded for word in ("transfer", "adjustment", "correction", "balance", "savings")):
        target = "last_transfer"
    else:
        target = "last_expense"
    return DeleteIntent(target=target)


def _try_export(padded: str) -> ExportIntent | None:
    if "export" not in padded and "download" not in padded:
        return None
    fmt = next((code for word, code in _EXPORT_FORMAT_WORDS if word in padded), None)
    if fmt is None:
        return None  # ambiguous format -- let the LLM ask/decide

    period = "all_time"
    if "this week" in padded:
        period = "this_week"
    elif "this month" in padded:
        period = "this_month"
    elif "last month" in padded:
        period = "last_month"
    return ExportIntent(format=fmt, period=period)


def _try_chart(padded: str) -> ChartIntent | None:
    if "chart" not in padded and "graph" not in padded:
        return None
    chart_type = next((code for word, code in _CHART_TYPE_WORDS if word in padded), "category_pie")

    period = "this_month"
    if "this week" in padded:
        period = "this_week"
    elif "last month" in padded:
        period = "last_month"
    elif "all time" in padded or "all-time" in padded:
        period = "all_time"
    return ChartIntent(chart_type=chart_type, period=period)


def try_parse_locally(session: Session, text: str) -> AnyIntent | None:
    """Attempt to classify ``text`` locally, without the LLM, across the
    handful of intent shapes covered here (expense, income, "undo/delete
    the last X", export, chart). Returns None (abstain) for anything not
    a confident, unambiguous match -- the caller falls through to
    parse_message() in that case. Never raises; this is a pure
    best-effort shortcut tried before the LLM."""
    if not settings.local_parser_enabled:
        return None

    stripped = text.strip()
    if not stripped or stripped.endswith("?"):
        return None
    if len(stripped.split()) > _MAX_WORDS:
        return None

    padded = f" {stripped.lower()} "

    delete_intent = _try_undo_last(padded)
    if delete_intent is not None:
        return delete_intent

    export_intent = _try_export(padded)
    if export_intent is not None:
        return export_intent

    chart_intent = _try_chart(padded)
    if chart_intent is not None:
        return chart_intent

    income_intent = _try_income(stripped, padded)
    if income_intent is not None:
        return income_intent

    if any(signal in padded for signal in _NON_EXPENSE_SIGNALS):
        return None
    if _mentions_saving_for(padded):
        return None

    return _try_expense(session, stripped)
