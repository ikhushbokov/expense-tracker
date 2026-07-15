"""Shared pytest fixtures: an isolated in-memory-backed DB per test."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch, tmp_path):
    """Point the app at a fresh SQLite file for every test."""
    db_path = tmp_path / "test_expenses.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))

    from expense_ai import config as config_module

    # Modules that already did `from expense_ai.config import settings` (at
    # their own first import, before this fixture ever ran) hold a direct
    # reference to this original singleton -- capture it *before* reassigning
    # config_module.settings below, or we'd end up patching the wrong object.
    original_settings = config_module.settings

    config_module.get_settings.cache_clear()
    test_settings = config_module.get_settings()
    monkeypatch.setattr(config_module, "settings", test_settings)

    # Patch the pre-existing shared instance's fields in place too, so every
    # module bound to it directly sees the isolated per-test paths.
    monkeypatch.setattr(original_settings, "database_path", test_settings.database_path)
    monkeypatch.setattr(original_settings, "export_dir", test_settings.export_dir)

    from expense_ai import database as db_module

    monkeypatch.setattr(db_module, "engine", db_module.create_engine(f"sqlite:///{db_path}"))
    monkeypatch.setattr(db_module, "SessionLocal", db_module.sessionmaker(bind=db_module.engine, expire_on_commit=False))

    db_module.init_db()
    yield
