"""CRUD operations for expenses and income.

This is the only module that should issue raw SQLAlchemy queries — every
other layer (finance, handlers, exports) goes through these functions so
storage details stay isolated.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from expense_ai.database.models import Debt, Expense, Income, PendingMessage, PendingSync, Receipt, SavingsGoal, Transfer


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
        datetime=when or dt.datetime.now(),
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
        datetime=when or dt.datetime.now(),
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
        datetime=when or dt.datetime.now(),
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
    amount: float | None = None,
    currency: str | None = None,
) -> list[Transfer]:
    stmt = select(Transfer)
    if account is not None:
        stmt = stmt.where((Transfer.from_account == account) | (Transfer.to_account == account))
    if start is not None:
        stmt = stmt.where(Transfer.datetime >= start)
    if end is not None:
        stmt = stmt.where(Transfer.datetime < end)
    if amount is not None:
        stmt = stmt.where(Transfer.amount == amount)
    if currency is not None:
        stmt = stmt.where(Transfer.currency == currency)
    stmt = stmt.order_by(Transfer.datetime.desc())
    return list(session.scalars(stmt).all())


def last_transfer(session: Session) -> Transfer | None:
    stmt = select(Transfer).order_by(Transfer.datetime.desc(), Transfer.id.desc()).limit(1)
    return session.scalars(stmt).first()


def get_transfer(session: Session, transfer_id: int) -> Transfer | None:
    return session.get(Transfer, transfer_id)


def update_transfer(session: Session, transfer_id: int, **fields: object) -> Transfer | None:
    transfer = session.get(Transfer, transfer_id)
    if transfer is None:
        return None
    for key, value in fields.items():
        if value is not None and hasattr(transfer, key):
            setattr(transfer, key, value)
    session.flush()
    return transfer


def delete_transfer(session: Session, transfer_id: int) -> bool:
    transfer = session.get(Transfer, transfer_id)
    if transfer is None:
        return False
    session.delete(transfer)
    return True


def add_debt(
    session: Session,
    *,
    person: str,
    amount: float,
    currency: str,
    direction: str,
    note: str = "",
    when: dt.datetime | None = None,
) -> Debt:
    debt = Debt(
        person=person,
        amount=amount,
        currency=currency,
        direction=direction,
        note=note,
        datetime=when or dt.datetime.now(),
    )
    session.add(debt)
    session.flush()
    return debt


def list_debts(
    session: Session,
    *,
    status: str | None = None,
    keyword: str | None = None,
    currency: str | None = None,
) -> list[Debt]:
    stmt = select(Debt)
    if status is not None:
        stmt = stmt.where(Debt.status == status)
    if keyword is not None:
        stmt = stmt.where(Debt.person.ilike(f"%{keyword}%"))
    if currency is not None:
        stmt = stmt.where(Debt.currency == currency)
    stmt = stmt.order_by(Debt.datetime.desc())
    return list(session.scalars(stmt).all())


def last_debt(
    session: Session, *, status: str | None = None, keyword: str | None = None, currency: str | None = None
) -> Debt | None:
    matches = list_debts(session, status=status, keyword=keyword, currency=currency)
    return matches[0] if matches else None


def get_debt(session: Session, debt_id: int) -> Debt | None:
    return session.get(Debt, debt_id)


def settle_debt(session: Session, debt_id: int, *, settled_amount: float | None = None) -> Debt | None:
    debt = session.get(Debt, debt_id)
    if debt is None:
        return None
    debt.status = "settled"
    debt.settled_at = dt.datetime.now()
    debt.settled_amount = settled_amount if settled_amount is not None else debt.amount
    session.flush()
    return debt


def delete_debt(session: Session, debt_id: int) -> bool:
    debt = session.get(Debt, debt_id)
    if debt is None:
        return False
    session.delete(debt)
    return True


def upsert_savings_goal(
    session: Session, *, name: str, target_amount: float, currency: str, target_date: dt.date | None = None
) -> SavingsGoal:
    goal = session.scalars(select(SavingsGoal).where(SavingsGoal.currency == currency)).first()
    if goal is None:
        goal = SavingsGoal(name=name, target_amount=target_amount, currency=currency, target_date=target_date)
        session.add(goal)
    else:
        goal.name = name
        goal.target_amount = target_amount
        goal.target_date = target_date
    session.flush()
    return goal


def get_savings_goal(session: Session, currency: str) -> SavingsGoal | None:
    return session.scalars(select(SavingsGoal).where(SavingsGoal.currency == currency)).first()


def list_savings_goals(session: Session) -> list[SavingsGoal]:
    return list(session.scalars(select(SavingsGoal)).all())


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
        stmt = stmt.where(
            Expense.description.ilike(like) | Expense.notes.ilike(like) | Expense.category.ilike(like)
        )
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


def mark_pending_sync(session: Session, *, chat_id: int) -> None:
    """Arm the "next photo is a balance sync" marker for a chat, replacing
    any earlier one (there's only ever one meaningful marker per chat)."""
    for existing in session.scalars(select(PendingSync).where(PendingSync.chat_id == chat_id)).all():
        session.delete(existing)
    session.add(PendingSync(chat_id=chat_id))


def pop_pending_sync(session: Session, *, chat_id: int, max_age_seconds: int) -> bool:
    """Consume (delete) the pending-sync marker for ``chat_id`` if one
    exists, regardless of age. Returns whether it was still fresh enough
    to act on."""
    pending = list(session.scalars(select(PendingSync).where(PendingSync.chat_id == chat_id)).all())
    for item in pending:
        session.delete(item)
    if not pending:
        return False
    newest = max(item.created_at for item in pending)
    return (dt.datetime.now() - newest).total_seconds() <= max_age_seconds
