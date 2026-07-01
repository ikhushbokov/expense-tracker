"""CRUD operations for expenses and income.

This is the only module that should issue raw SQLAlchemy queries — every
other layer (finance, handlers, exports) goes through these functions so
storage details stay isolated.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from expense_ai.database.models import Expense, Income, Receipt


def add_expense(
    session: Session,
    *,
    amount: float,
    currency: str,
    category: str,
    description: str = "",
    source: str = "text",
    notes: str = "",
    when: dt.datetime | None = None,
) -> Expense:
    expense = Expense(
        amount=amount,
        currency=currency,
        category=category,
        description=description,
        source=source,
        notes=notes,
        datetime=when or dt.datetime.now(dt.timezone.utc),
    )
    session.add(expense)
    session.flush()
    return expense


def add_income(
    session: Session,
    *,
    amount: float,
    currency: str,
    description: str = "",
    when: dt.datetime | None = None,
) -> Income:
    income = Income(
        amount=amount,
        currency=currency,
        description=description,
        datetime=when or dt.datetime.now(dt.timezone.utc),
    )
    session.add(income)
    session.flush()
    return income


def attach_receipt(
    session: Session,
    *,
    expense_id: int,
    merchant: str = "",
    raw_text: str = "",
    image_path: str = "",
) -> Receipt:
    receipt = Receipt(
        expense_id=expense_id,
        merchant=merchant,
        raw_text=raw_text,
        image_path=image_path,
    )
    session.add(receipt)
    session.flush()
    return receipt


def get_expense(session: Session, expense_id: int) -> Expense | None:
    return session.get(Expense, expense_id)


def get_income(session: Session, income_id: int) -> Income | None:
    return session.get(Income, income_id)


def update_expense(session: Session, expense_id: int, **fields: object) -> Expense | None:
    expense = session.get(Expense, expense_id)
    if expense is None:
        return None
    for key, value in fields.items():
        if value is not None and hasattr(expense, key):
            setattr(expense, key, value)
    session.flush()
    return expense


def delete_expense(session: Session, expense_id: int) -> bool:
    expense = session.get(Expense, expense_id)
    if expense is None:
        return False
    session.delete(expense)
    return True


def delete_income(session: Session, income_id: int) -> bool:
    income = session.get(Income, income_id)
    if income is None:
        return False
    session.delete(income)
    return True


def last_expense(session: Session) -> Expense | None:
    stmt = select(Expense).order_by(Expense.datetime.desc(), Expense.id.desc()).limit(1)
    return session.scalars(stmt).first()


def last_income(session: Session) -> Income | None:
    stmt = select(Income).order_by(Income.datetime.desc(), Income.id.desc()).limit(1)
    return session.scalars(stmt).first()


def list_expenses(
    session: Session,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    category: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    keyword: str | None = None,
) -> list[Expense]:
    stmt = select(Expense)
    if start is not None:
        stmt = stmt.where(Expense.datetime >= start)
    if end is not None:
        stmt = stmt.where(Expense.datetime < end)
    if category is not None:
        stmt = stmt.where(Expense.category == category)
    if min_amount is not None:
        stmt = stmt.where(Expense.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Expense.amount <= max_amount)
    if keyword is not None:
        like = f"%{keyword}%"
        stmt = stmt.where(Expense.description.ilike(like) | Expense.notes.ilike(like))
    stmt = stmt.order_by(Expense.datetime.desc())
    return list(session.scalars(stmt).all())


def list_income(
    session: Session,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> list[Income]:
    stmt = select(Income)
    if start is not None:
        stmt = stmt.where(Income.datetime >= start)
    if end is not None:
        stmt = stmt.where(Income.datetime < end)
    stmt = stmt.order_by(Income.datetime.desc())
    return list(session.scalars(stmt).all())
