"""Database engine/session management for the expense tracker.

Uses a single SQLite file (path from ``expense_ai.config.settings``). Call
``init_db()`` once at startup to create tables, then use ``session_scope()``
as a context manager for all reads/writes.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from expense_ai.config import settings
from expense_ai.database.models import Base

engine = create_engine(
    f"sqlite:///{settings.database_full_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
