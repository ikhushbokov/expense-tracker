"""CRUD operations for expenses and income.

This is the only module that should issue raw SQLAlchemy queries — every
other layer (finance, handlers, exports) goes through these functions so
storage details stay isolated.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from expense_ai.database.models import Expense, Income, PendingMessage, Receipt, Transfer


def add_expense(
    session: Session,
    *,
    amount: float,
    currency: str,
    category: str,
    description: str = "",
    source: str = "text",
    notes: str = "",
    account: str = "balance",
    when: dt.datetime | None = None,
) -> Expense:
    expense = Expense(
        amount=amount,
        currency=currency,
        category=category,
        description=description,
        source=source,
        notes=notes,
        account=account,
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
    account: str = "balance",
    when: dt.datetime | None = None,
) -> Income:
    income = Income(
        amount=amount,
        currency=currency,
        description=description,
        account=account,
        datetime=when or dt.datetime.now(dt.timezone.utc),
    )
    session.add(income)
    session.flush()
    return income


def add_transfer(
    session: Session,
    *,
    from_account: str | None,
    to_account: str | None,
    amount: float,
    currency: str,
    note: str = "",
    when: dt.datetime | None = None,
) -> Transfer:
    transfer = Transfer(
        from_account=from_account,
        to_account=to_account,
        amount=amount,
        currency=currency,
        note=note,
        datetime=when or dt.datetime.now(dt.timezone.utc),
    )
    session.add(transfer)
    session.flush()
    return transfer


def list_transfers(
    session: Session,
    *,
    account: str | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> list[Transfer]:
    stmt = select(Transfer)
    if account is not None:
        stmt = stmt.where((Transfer.from_account == account) | (Transfer.to_account == account))
    if start is not None:
        stmt = stmt.where(Transfer.datetime >= start)
    if end is not None:
        stmt = stmt.where(Transfer.datetime < end)
    stmt = stmt.order_by(Transfer.datetime.desc())
    return list(session.scalars(stmt).all())


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
    account: str | None = None,
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
    if account is not None:
        stmt = stmt.where(Expense.account == account)
    stmt = stmt.order_by(Expense.datetime.desc())
    return list(session.scalars(stmt).all())


def list_income(
    session: Session,
    *,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    account: str | None = None,
) -> list[Income]:
    stmt = select(Income)
    if start is not None:
        stmt = stmt.where(Income.datetime >= start)
    if end is not None:
        stmt = stmt.where(Income.datetime < end)
    if account is not None:
        stmt = stmt.where(Income.account == account)
    stmt = stmt.order_by(Income.datetime.desc())
    return list(session.scalars(stmt).all())


def enqueue_pending_message(session: Session, *, chat_id: int, text: str) -> PendingMessage:
    pending = PendingMessage(chat_id=chat_id, text=text)
    session.add(pending)
    session.flush()
    return pending


def list_pending_messages(session: Session) -> list[PendingMessage]:
    stmt = select(PendingMessage).order_by(PendingMessage.created_at.asc())
    return list(session.scalars(stmt).all())


def increment_pending_attempts(session: Session, pending_id: int) -> None:
    pending = session.get(PendingMessage, pending_id)
    if pending is not None:
        pending.attempts += 1
        session.flush()


def delete_pending_message(session: Session, pending_id: int) -> bool:
    pending = session.get(PendingMessage, pending_id)
    if pending is None:
        return False
    session.delete(pending)
    return True
