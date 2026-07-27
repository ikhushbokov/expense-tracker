"""Handles receipt photos: OCR -> LLM categorization -> stored expense.

Balance-sync screenshots are routed to handlers/balance_sync.py instead --
either because the photo is captioned "sync" (is_sync_photo()), or because
/sync armed a "the next photo is the screenshot" marker for this chat
(pop_pending_sync(), consumed here either way so a later, unrelated photo
doesn't get mistaken for one).
"""

from __future__ import annotations

import logging
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from expense_ai.config import settings
from expense_ai.database import repository, session_scope
from expense_ai.finance import format_amount, get_balances
from expense_ai.handlers.balance_sync import SYNC_PENDING_WINDOW_SECONDS, handle_sync_photo, is_sync_photo
from expense_ai.handlers.common import restrict_to_owner
from expense_ai.handlers.text import UNREACHABLE_MESSAGE
from expense_ai.llm import LLMError
from expense_ai.ocr import extract_image_text
from expense_ai.parser import parse_message

logger = logging.getLogger(__name__)

RECEIPTS_DIR = settings.database_full_path.parent / "receipts"


@restrict_to_owner
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return

    with session_scope() as session:
        pending_sync = repository.pop_pending_sync(
            session, chat_id=message.chat_id, max_age_seconds=SYNC_PENDING_WINDOW_SECONDS
        )
    if is_sync_photo(message.caption) or pending_sync:
        await handle_sync_photo(update, context)
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action="typing")

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    photo = message.photo[-1]  # highest resolution
    file = await photo.get_file()
    image_path = RECEIPTS_DIR / f"{uuid.uuid4().hex}.jpg"
    await file.download_to_drive(custom_path=str(image_path))

    try:
        raw_text = extract_image_text(image_path)
    except Exception as exc:
        logger.error("OCR failed for %s: %s", image_path, exc)
        await message.reply_text(
            "I couldn't read that receipt automatically. You can tell me the amount and "
            "category directly instead, e.g. \"Spent 45,000 on groceries\"."
        )
        return

    if not raw_text.strip():
        await message.reply_text("I couldn't find any readable text on that receipt. Try a clearer photo.")
        return

    caption_hint = f"\n\nUser caption: {message.caption}" if message.caption else ""
    receipt_prompt = (
        f"This text was OCR-extracted from a receipt photo, extract the total amount, "
        f"merchant, and category as an expense:\n\n{raw_text}{caption_hint}"
    )
    try:
        intent = await parse_message(receipt_prompt)
    except LLMError as exc:
        logger.warning("LLM unreachable, queuing receipt text: %s", exc)
        with session_scope() as session:
            repository.enqueue_pending_message(session, chat_id=message.chat_id, text=receipt_prompt)
        await message.reply_text(UNREACHABLE_MESSAGE)
        return

    if intent.type != "expense":
        await message.reply_text(
            "I read the receipt but couldn't confidently extract an expense from it. "
            "Raw text:\n\n" + raw_text[:500]
        )
        return

    with session_scope() as session:
        expense = repository.add_expense(
            session,
            amount=intent.amount,
            currency=intent.currency,
            category=intent.category,
            description=intent.description,
            source="photo",
        )
        session.flush()
        repository.attach_receipt(
            session,
            expense_id=expense.id,
            raw_text=raw_text,
            image_path=str(image_path),
        )
        session.flush()
        balances = get_balances(session)
        balance_text = balances.get(intent.currency, 0.0)

    await message.reply_text(
        "\U0001F9FE Receipt processed\n\n"
        f"Amount: {format_amount(expense.amount, expense.currency)}\n"
        f"Category: {expense.category}\n"
        f"Description: {expense.description or '-'}\n\n"
        f"Current balance: {format_amount(balance_text, intent.currency)}"
    )
