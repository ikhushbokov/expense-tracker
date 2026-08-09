"""Reconciles the tracked balance against a cards/accounts screenshot.

Triggered by a photo captioned "sync" (see is_sync_photo(), and
handlers/photo.py:handle_photo which routes to handle_sync_photo() instead
of the receipt flow when it matches). The screenshot is sent directly to
the LLM as vision input (base64 data URL, see _extract_card_amounts) --
NOT run through Tesseract like receipts are. Tesseract measurably
mis-read this exact bot's own incident screenshot (a digit: "29,768.32"
-> "29,768.52"; a bank name: "Aloqabank" -> "Alogabar", which is where the
infamous "Alogabar" phantom expense came from), while the vision model
got every value right on the same image. The LLM is asked to LIST each
individual account/card balance shown -- explicitly NOT to sum them (see
_extract_card_amounts's prompt); Python does the addition. This is
deliberately its own narrow extraction call rather than going through
parser.py's general set_balance intent (which asks the LLM for one
pre-summed total_amount): summing several numbers is exactly the kind of
arithmetic an LLM has gotten wrong on this bot twice in production, and
listing is a strictly easier, more mechanical task than adding.

A mismatch isn't applied blindly: it's usually either (a) something
genuinely unaccounted for (a bank fee, cashback, a correction with no
real transaction behind it) or (b) a transaction the user forgot to log
(cashed out and spent it, forgot to log income). Those need different
treatment -- (a) as a Transfer correction that never shows up as income
or spending, (b) as a real dated Expense/Income so it shows up in
category totals and monthly summaries. So handle_sync_photo asks via two
buttons instead of guessing; the callback data carries the amount/currency
directly, so nothing is written to the DB until the user actually taps
one. Tapping "log missed expense/income" still doesn't write immediately
either -- it arms a PendingMissedTransaction marker and asks what it was
for; handlers/text.py:handle_text checks for that marker before its
normal flow and, if present, treats the reply as the description (see
handle_missed_transaction_description below) rather than re-parsing it
as a brand new message.

If the LLM is unreachable when the screenshot is first processed, the
image gets queued as a data URL (kind="balance_sync", see repository.py)
same as any other message -- but handlers/retry.py must NOT replay it
through the generic build_response() path, since that would run
set_balance through dispatch.py's unconditional reconcile_balance() and
apply whatever the LLM says with no chance to confirm (this happened once
in production with a wrong LLM-computed total). build_sync_mismatch_response()
below is the shared "image -> extract -> compute mismatch -> (text,
markup)" step both handle_sync_photo and retry.py call, so the confirm
buttons show up either way -- only *how* the result gets sent differs
(message.reply_text vs. bot.send_message on a delay).
"""

from __future__ import annotations

import base64
import logging

from pydantic import BaseModel
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from expense_ai.config import settings
from expense_ai.database import repository, session_scope
from expense_ai.finance import format_amount, get_balances, reconcile_balance
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.handlers.text import UNREACHABLE_MESSAGE
from expense_ai.llm import LLMError, llm_client
from expense_ai.parser import parse_message

logger = logging.getLogger(__name__)

_AMOUNT_EXTRACTION_SYSTEM_PROMPT = """\
You extract account balances from a screenshot of a banking app's list of
cards/accounts. List EVERY individual account/card balance shown, each as
its own number -- do NOT add them together, a later step handles the sum.
Amounts are in Uzbek so'm/UZS unless another currency is clearly stated.
Respond with JSON only: {"amounts": [<number>, <number>, ...], "currency": "<ISO code>"}.
If you can't find any balances, return {"amounts": [], "currency": "UZS"}.
"""


class _CardAmounts(BaseModel):
    amounts: list[float] = []
    currency: str = "UZS"


def _to_data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"


async def _extract_card_amounts(image_data_url: str) -> _CardAmounts:
    """List each balance shown in the screenshot -- deliberately does not
    ask the LLM to sum them; build_sync_mismatch_response does the
    addition in Python."""
    raw = await llm_client.complete_json(
        system_prompt=_AMOUNT_EXTRACTION_SYSTEM_PROMPT,
        user_prompt="Extract the account balances from this screenshot.",
        image_data_url=image_data_url,
    )
    return _CardAmounts.model_validate(raw)

# How long a pending marker (the next photo after /sync, or the next text
# reply describing a missed expense/income) stays valid before being
# treated as stale -- see handlers/photo.py and handlers/text.py, which
# consume the marker either way once that message arrives.
SYNC_PENDING_WINDOW_SECONDS = 600


def is_sync_photo(caption: str | None) -> bool:
    """True if a photo's caption asks for a balance sync rather than a receipt scan."""
    return (caption or "").strip().lstrip("/").lower().startswith("sync")


@restrict_to_owner
async def handle_sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    with session_scope() as session:
        balances = get_balances(session, account="balance")
        repository.mark_pending_sync(session, chat_id=message.chat_id)
    tracked = ", ".join(format_amount(v, c) for c, v in balances.items()) if balances else "nothing recorded yet"
    await message.reply_text(
        "\U0001F4B3 Tracked balance: " + tracked + "\n\n"
        "Send a screenshot of your cards/accounts total in the next 10 minutes and I'll compare it "
        "to the tracked balance (summed across all cards) -- no caption needed. You can also caption "
        "any photo \"sync\" to trigger this without the command."
    )


async def build_sync_mismatch_response(image_data_url: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Cards-screenshot data URL -> the reply: either the "already in
    sync" text (no buttons) or the mismatch text with the "sync anyway" /
    "log missed expense or income" buttons. Shared by the live path
    (handle_sync_photo) and the retry-queue path (handlers/retry.py) so a
    delayed reply still asks instead of auto-applying. Raises LLMError if
    the LLM is unreachable -- callers decide what to do about that."""
    extracted = await _extract_card_amounts(image_data_url)

    if not extracted.amounts:
        return "I read the screenshot but couldn't confidently total a balance from it.", None

    total_amount = round(sum(extracted.amounts), 2)
    currency = extracted.currency.upper().strip() or settings.default_currency

    with session_scope() as session:
        current = get_balances(session, account="balance").get(currency, 0.0)
    delta = round(total_amount - current, 2)

    if delta == 0:
        return (
            "✅ Already in sync — tracked balance matches your cards: "
            f"{format_amount(total_amount, currency)}.",
            None,
        )

    missing = delta < 0  # tracked balance is higher than reality -> likely an unlogged expense
    kind = "expense" if missing else "income"
    text = (
        "⚠️ Balance mismatch\n\n"
        f"Tracked: {format_amount(current, currency)}\n"
        f"From your cards: {format_amount(total_amount, currency)}\n"
        f"Difference: {format_amount(abs(delta), currency)} ({'missing' if missing else 'extra'})\n\n"
        f"Sync anyway (an unexplained correction, not counted as income/spending), or log the "
        f"difference as a missed {kind} instead?"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"✅ Sync anyway ({format_amount(total_amount, currency)})",
                    callback_data=f"sync:apply:{total_amount:.2f}:{currency}",
                )
            ],
            [
                InlineKeyboardButton(
                    f"\U0001F4DD Log missed {kind} ({format_amount(abs(delta), currency)})",
                    callback_data=f"sync:{kind}:{abs(delta):.2f}:{currency}",
                )
            ],
        ]
    )
    return text, markup


@restrict_to_owner
async def handle_sync_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")

    photo = message.photo[-1]  # highest resolution
    file = await photo.get_file()
    image_data_url = _to_data_url(bytes(await file.download_as_bytearray()))

    # See handlers/text.py for why this is a persistent placeholder rather
    # than just the "typing..." action: this call can take up to ~90s
    # during a provider outage, well past when "typing..." disappears.
    placeholder = await message.reply_text("⏳ Reading your screenshot...")

    try:
        text, markup = await build_sync_mismatch_response(image_data_url)
    except LLMError as exc:
        logger.warning("LLM unreachable, queuing balance-sync image: %s", exc)
        with session_scope() as session:
            repository.enqueue_pending_message(session, chat_id=message.chat_id, text=image_data_url, kind="balance_sync")
        await placeholder.edit_text(UNREACHABLE_MESSAGE)
        return

    await placeholder.edit_text(text, reply_markup=markup)


@restrict_to_owner
async def handle_sync_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    _, action, amount_str, currency = query.data.split(":")
    amount = float(amount_str)

    if action == "apply":
        with session_scope() as session:
            delta = reconcile_balance(
                session, total_amount=amount, currency=currency, account="balance", note="Synced from cards screenshot"
            )
        if delta == 0:
            text = f"✅ Already in sync — tracked balance matches your cards: {format_amount(amount, currency)}."
        else:
            verb = "Added" if delta > 0 else "Subtracted"
            text = (
                f"\U0001F504 Synced with actual balance from your cards: {format_amount(amount, currency)}\n"
                f"({verb} an adjustment of {format_amount(abs(delta), currency)})\n"
                "(This is a correction, not counted as income or spending.)"
            )
    elif action in ("expense", "income"):
        chat_id = query.message.chat_id if query.message is not None else update.effective_chat.id
        with session_scope() as session:
            repository.mark_pending_missed_transaction(session, chat_id=chat_id, kind=action, amount=amount, currency=currency)
        text = f"\U0001F4DD What was this {format_amount(amount, currency)} for? Reply with a short description."
    else:
        return

    await query.edit_message_text(text)


async def handle_missed_transaction_description(message: Message, kind: str, amount: float, currency: str, description: str) -> None:
    """Consumes the user's reply to "What was this ... for?" (see the
    "expense"/"income" branch of handle_sync_callback above) and logs the
    amount decided at sync time -- never re-derived from this reply --
    with a category best-effort guessed from the description via the same
    LLM path as a normal typed expense, falling back to "Other" if that
    fails."""
    category = "Other"
    final_description = description
    try:
        intent = await parse_message(f"Log a {kind} of exactly {amount} {currency} for: {description}")
        if kind == "expense" and intent.type == "expense":
            category = intent.category
            final_description = intent.description or description
        elif kind == "income" and intent.type == "income":
            final_description = intent.description or description
    except LLMError as exc:
        logger.warning("LLM unreachable while categorizing missed %s, falling back to 'Other': %s", kind, exc)

    with session_scope() as session:
        if kind == "expense":
            repository.add_expense(
                session, amount=amount, currency=currency, category=category, description=final_description
            )
        else:
            repository.add_income(session, amount=amount, currency=currency, description=final_description)
        session.flush()
        balance = get_balances(session, account="balance").get(currency, 0.0)

    if kind == "expense":
        text = (
            f"\U0001F4DD Logged missed expense: {format_amount(amount, currency)} ({category}) — {final_description}\n\n"
            f"Current balance: {format_amount(balance, currency)}"
        )
    else:
        text = (
            f"\U0001F4B0 Logged missed income: {format_amount(amount, currency)} — {final_description}\n\n"
            f"Current balance: {format_amount(balance, currency)}"
        )
    await message.reply_text(text)
