"""Tests for the automatic DB backup job (handlers/backup.py)."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

from expense_ai.config import settings
from expense_ai.database import repository, session_scope
from expense_ai.handlers.backup import send_db_backup


def test_send_db_backup_sends_a_consistent_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "telegram_allowed_user_id", 555)

    with session_scope() as s:
        repository.add_expense(s, amount=42_000, currency="UZS", category="Food", description="Snack")

    # The document is read via a temp file that's deleted before send_db_backup
    # returns, so capture its bytes *during* the (mocked) send_document call
    # rather than inspecting the file handle afterward.
    captured = {}

    async def _capture_document(*, chat_id, document, filename, caption):
        captured["chat_id"] = chat_id
        captured["filename"] = filename
        captured["bytes"] = document.read()

    ctx = MagicMock()
    ctx.bot.send_document = AsyncMock(side_effect=_capture_document)
    asyncio.run(send_db_backup(ctx))

    assert captured["chat_id"] == 555
    assert captured["filename"].startswith("expenses_backup_")

    backup_copy = tmp_path / "captured_backup.db"
    backup_copy.write_bytes(captured["bytes"])
    conn = sqlite3.connect(backup_copy)
    try:
        rows = conn.execute("SELECT amount, description FROM expenses").fetchall()
    finally:
        conn.close()
    assert (42_000.0, "Snack") in rows


def test_send_db_backup_skipped_without_owner_chat_id(monkeypatch):
    monkeypatch.setattr(settings, "telegram_allowed_user_id", None)

    ctx = MagicMock()
    ctx.bot.send_document = AsyncMock()
    asyncio.run(send_db_backup(ctx))

    ctx.bot.send_document.assert_not_awaited()
