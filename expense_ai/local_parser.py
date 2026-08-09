"""Cheap, deterministic local parser for the dominant case: a short plain-
language expense message like "45k taxi" or "Spent 85,000 on groceries".

Model: the LLM should be the *fallback*, not the front door. Measured
against this bot's own history, roughly 80% of expense messages use a
vocabulary of a few dozen words with zero category ambiguity -- "taxi",
"groceries", "football" each map to exactly one category, unanimously,
every single time they've been logged. Handling those locally means no
network round-trip, no cost, and it keeps working through an LLM-provider
outage. More importantly, the field that actually matters for correctness
-- the amount -- is extracted by regex instead of asked of a model that
has, twice in one week on this exact bot, gotten arithmetic wrong.

This is intentionally narrow and paranoid about false positives: it
abstains (returns None, falling through to parse_message()/the LLM)
whenever anything looks even slightly like a different intent (income, a
balance correction, a transfer, a debt, an edit/delete, a question, ...),
whenever more than one amount-like token appears, or whenever the
category can't be resolved with real confidence from this user's own
history. A wrong ABSTAIN just costs one ordinary LLM call. A wrong ACCEPT
writes bad data -- so it only ever fires on the safe, common case.

One explicit convention on top of the inferred-from-history path: if the
LAST word left after the amount is removed exactly names one of the
fixed CATEGORIES (case-insensitively -- "food", "Food", "FOOD" all
count), it's taken as an explicit category override rather than fed into
the keyword vote, and everything before it becomes the description. This
skips _MIN_VOTES/tie-breaking entirely (there's no ambiguity to guess
about when the user just said the category), so it works even with zero
prior history -- "45k lunch food" resolves locally the very first time,
not just once "lunch" has been seen twice. Deliberately NOT extended to
inventing brand-new categories that aren't in CATEGORIES: the fixed list
is used elsewhere (dashboard, charts) and deciding "is this worth a new
category" isn't something this narrow a heuristic should judge -- that
stays a parse_message()/LLM (or you, telling Claude to add one) decision.

Gated behind settings.local_parser_enabled so it can be A/B'd against
real messages before being trusted -- see dispatch.py's build_response(),
the only call site.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from expense_ai.config import settings
from expense_ai.database import repository
from expense_ai.models.schemas import CATEGORIES, ExpenseIntent

_CATEGORY_BY_LOWER = {c.lower(): c for c in CATEGORIES}

# Substrings that strongly suggest a different intent than a plain expense --
# if any of these appear, abstain rather than guess. Mined from the exact
# phrasing parser.py's own prompt documents for each intent, since that's
# the closest thing to ground truth for how the LLM is told to tell them
# apart. Checked against the message padded with a leading/trailing space,
# so entries with surrounding spaces still match at the very start/end.
_NON_EXPENSE_SIGNALS: tuple[str, ...] = (
    # income
    "salary", "paid me", "got paid", "payment came", "freelance", "income",
    # set_balance -- a *state*, not an event; must never be read as an expense
    " i have", "i've got", "i actually have", "actual balance", "my balance",
    "balance is", "total is", "saved up", "on my card",
    # transfer
    " transfer", " move ", "into savings", "from balance", "from savings",
    # debt / settle_debt
    " lent ", "lend", "borrow", " owe", "loan", "paid back",
    "paid me back", "pay back", "repaid", "repay",
    # savings_goal
    "saving for", "save for", "savings goal", "my goal",
    # edit / delete / search
    "actually it was", "should be", "change the", "rename", "correct the",
    "delete", "remove", "undo", "find the", "search for", "list my",
    # export / chart / history
    "export", " csv", "xlsx", " pdf", "chart", "graph", "history",
    # query
    "how much", "what did", "what's my", "when did", "why did",
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


def _detect_currency(text: str) -> str | None:
    lowered = text.lower()
    for word, code in _CURRENCY_WORDS.items():
        if word in lowered:
            return code
    return None


def _split_explicit_category(remaining_text: str) -> tuple[str, str] | None:
    """If the last word of ``remaining_text`` exactly names one of the
    fixed CATEGORIES (case-insensitive), split it off as an explicit
    category override. Returns (category, description) with that word
    removed and the rest capitalized, or None if the last word doesn't
    name a category -- callers fall through to history-based inference."""
    words = remaining_text.split()
    if not words:
        return None
    last_word = re.sub(r"[^\w']", "", words[-1]).lower()
    category = _CATEGORY_BY_LOWER.get(last_word)
    if category is None:
        return None
    description = " ".join(words[:-1]).strip()
    if description:
        description = description[0].upper() + description[1:]
    else:
        description = category
    return category, description


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


def try_parse_expense_locally(session: Session, text: str) -> ExpenseIntent | None:
    """Attempt to classify ``text`` as a plain expense without the LLM.
    Returns None (abstain) for anything that isn't a confident,
    unambiguous match -- the caller falls through to parse_message() in
    that case. Never raises; this is a pure best-effort shortcut."""
    if not settings.local_parser_enabled:
        return None

    stripped = text.strip()
    if not stripped or stripped.endswith("?"):
        return None
    if len(stripped.split()) > _MAX_WORDS:
        return None

    padded = f" {stripped.lower()} "
    if any(signal in padded for signal in _NON_EXPENSE_SIGNALS):
        return None

    extracted = _extract_amount(stripped)
    if extracted is None:
        return None
    amount, remaining = extracted

    currency = _detect_currency(stripped) or settings.default_currency

    explicit = _split_explicit_category(remaining)
    if explicit is not None:
        category, description = explicit
    else:
        resolved = _resolve_category(session, remaining)
        if resolved is None:
            return None
        category, description = resolved

    return ExpenseIntent(amount=amount, currency=currency, category=category, description=description)
