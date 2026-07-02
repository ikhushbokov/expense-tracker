"""Database engine/session management for the expense tracker.

Uses a single SQLite file (path from ``expense_ai.config.settings``). Call
``init_db()`` once at startup to create tables, then use ``session_scope()``
as a context manager for all reads/writes.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from expense_ai.config import settings
from expense_ai.database.models import Base, Expense, Income, Transfer

logger = logging.getLogger(__name__)

engine = create_engine(
    f"sqlite:///{settings.database_full_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create all tables if they don't already exist, then run any
    lightweight schema/data migrations needed for existing databases."""
    Base.metadata.create_all(engine)
    _add_column_if_missing("expenses", "account", "VARCHAR(32) DEFAULT 'balance' NOT NULL")
    _add_column_if_missing("income", "account", "VARCHAR(32) DEFAULT 'balance' NOT NULL")
    _migrate_legacy_balance_adjustments()
    _migrate_legacy_coffee_category()


def _add_column_if_missing(table: str, column: str, column_ddl: str) -> None:
    """`Base.metadata.create_all` only creates missing tables, it never adds
    columns to a table that already exists -- so a column added to a model
    after the DB file was first created has to be migrated in by hand."""
    with engine.begin() as conn:
        existing_columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in existing_columns:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")
            logger.info("Migrated schema: added %s.%s", table, column)


def _migrate_legacy_balance_adjustments() -> None:
    """One-time cleanup: earlier versions recorded "set my balance to X"
    corrections as plain Income/Expense rows (description starting with
    "Balance adjustment"), which incorrectly counted them as real income/
    spending in period reports. Move any such rows into the Transfer
    ledger instead, where they only affect the running balance. Idempotent:
    once migrated, the offending rows no longer exist to match again."""
    with session_scope() as session:
        stale_incomes = session.scalars(
            select(Income).where(Income.description.like("Balance adjustment%"))
        ).all()
        for income in stale_incomes:
            session.add(
                Transfer(
                    datetime=income.datetime,
                    from_account=None,
                    to_account="balance",
                    amount=income.amount,
                    currency=income.currency,
                    note=income.description,
                )
            )
            session.delete(income)

        stale_expenses = session.scalars(
            select(Expense).where(Expense.description.like("Balance adjustment%"))
        ).all()
        for expense in stale_expenses:
            session.add(
                Transfer(
                    datetime=expense.datetime,
                    from_account="balance",
                    to_account=None,
                    amount=expense.amount,
                    currency=expense.currency,
                    note=expense.description,
                )
            )
            session.delete(expense)

        if stale_incomes or stale_expenses:
            logger.info(
                "Migrated %d legacy balance-adjustment row(s) into the transfers table",
                len(stale_incomes) + len(stale_expenses),
            )


def _migrate_legacy_coffee_category() -> None:
    """Earlier versions auto-assigned a standalone "Coffee" category;
    food/drink purchases (coffee included) are now all grouped under
    "Food" instead, with the specific item left to the description.
    Idempotent: once migrated, no "Coffee" rows remain to match again."""
    with session_scope() as session:
        stale = session.scalars(select(Expense).where(Expense.category == "Coffee")).all()
        for expense in stale:
            expense.category = "Food"
        if stale:
            logger.info("Migrated %d expense(s) from category 'Coffee' to 'Food'", len(stale))


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
