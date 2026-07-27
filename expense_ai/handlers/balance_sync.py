"""Reconciles the tracked balance against a cards/accounts screenshot.

Triggered by a photo captioned "sync" (see is_sync_photo(), and
handlers/photo.py:handle_photo which routes to handle_sync_photo() instead
of the receipt flow when it matches). OCR's the screenshot, then hands the
raw text to the same set_balance path as a typed correction like "Card
9710: 411,000; Card 3901: 629,000" -- parser.py already knows to sum every
account mentioned into one total_amount, so no new intent type is needed.

A mismatch isn't applied blindly: it's usually either (a) something
genuinely unaccounted for (a bank fee, cashback, a correction with no
real transaction behind it) or (b) a transaction the user forgot to log
(cashed out and spent it, forgot to log income). Those need different
treatment -- (a) as a Transfer correction that never shows up as income
or spending, (b) as a real dated Expense/Income so it shows up in
category totals and monthly summaries. So handle_sync_photo asks via two
buttons instead of guessing; the callback data carries the amount/currency
directly (nothing is written to the DB, and there's no per-user session
state to lose, until the user actually taps one).
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from expense_ai.database import repository, session_scope
from expense_ai.finance import format_amount, get_balances, reconcile_balance
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.handlers.text import UNREACHABLE_MESSAGE
from expense_ai.llm import LLMError
from expense_ai.ocr import extract_image_text
from expense_ai.parser import parse_message

logger = logging.getLogger(__name__)

# How long after /sync the next photo is still assumed to be the screenshot
# it asked for (see handlers/photo.py, which consumes the marker either way).
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


@restrict_to_owner
async def handle_sync_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")

    photo = message.photo[-1]  # highest resolution
    file = await photo.get_file()
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / f"{uuid.uuid4().hex}.jpg"
        await file.download_to_drive(custom_path=str(image_path))
        try:
            raw_text = extract_image_text(image_path)
        except Exception as exc:
            logger.error("OCR failed for balance-sync screenshot: %s", exc)
            await message.reply_text(
                "I couldn't read that screenshot automatically. You can tell me the total "
                "directly instead, e.g. \"I have 3,614,000 across my cards\"."
            )
            return

    if not raw_text.strip():
        await message.reply_text("I couldn't find any readable text in that screenshot. Try a clearer photo.")
        return

    sync_prompt = (
        "This text was OCR-extracted from a screenshot of my banking app's list of cards/accounts "
        "and their balances (amounts are in Uzbek so'm/UZS unless stated otherwise). Sum every "
        "balance shown into one total and record it as a correction to my current total balance:\n\n"
        + raw_text
    )
    try:
        intent = await parse_message(sync_prompt)
    except LLMError as exc:
        logger.warning("LLM unreachable, queuing balance-sync text: %s", exc)
        with session_scope() as session:
            repository.enqueue_pending_message(session, chat_id=message.chat_id, text=sync_prompt)
        await message.reply_text(UNREACHABLE_MESSAGE)
        return

    if intent.type != "set_balance":
        await message.reply_text(
            "I read the screenshot but couldn't confidently total a balance from it. "
            "Raw text:\n\n" + raw_text[:500]
        )
        return

    with session_scope() as session:
        current = get_balances(session, account="balance").get(intent.currency, 0.0)
    delta = round(intent.total_amount - current, 2)

    if delta == 0:
        await message.reply_text(
            "✅ Already in sync — tracked balance matches your cards: "
            f"{format_amount(intent.total_amount, intent.currency)}."
        )
        return

    missing = delta < 0  # tracked balance is higher than reality -> likely an unlogged expense
    kind = "expense" if missing else "income"
    text = (
        "⚠️ Balance mismatch\n\n"
        f"Tracked: {format_amount(current, intent.currency)}\n"
        f"From your cards: {format_amount(intent.total_amount, intent.currency)}\n"
        f"Difference: {format_amount(abs(delta), intent.currency)} ({'missing' if missing else 'extra'})\n\n"
        f"Sync anyway (an unexplained correction, not counted as income/spending), or log the "
        f"difference as a missed {kind} instead?"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"✅ Sync anyway ({format_amount(intent.total_amount, intent.currency)})",
                    callback_data=f"sync:apply:{intent.total_amount:.2f}:{intent.currency}",
                )
            ],
            [
                InlineKeyboardButton(
                    f"\U0001F4DD Log missed {kind} ({format_amount(abs(delta), intent.currency)})",
                    callback_data=f"sync:{kind}:{abs(delta):.2f}:{intent.currency}",
                )
            ],
        ]
    )
    await message.reply_text(text, reply_markup=markup)


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
    elif action == "expense":
        with session_scope() as session:
            repository.add_expense(
                session,
                amount=amount,
                currency=currency,
                category="Other",
                description="Missed expense (found via cards sync)",
            )
            session.flush()
            balance = get_balances(session, account="balance").get(currency, 0.0)
        text = (
            f"\U0001F4DD Logged missed expense: {format_amount(amount, currency)} (Other)\n\n"
            f"Current balance: {format_amount(balance, currency)}"
        )
    elif action == "income":
        with session_scope() as session:
            repository.add_income(
                session, amount=amount, currency=currency, description="Missed income (found via cards sync)"
            )
            session.flush()
            balance = get_balances(session, account="balance").get(currency, 0.0)
        text = (
            f"\U0001F4B0 Logged missed income: {format_amount(amount, currency)}\n\n"
            f"Current balance: {format_amount(balance, currency)}"
        )
    else:
        return

    await query.edit_message_text(text)
