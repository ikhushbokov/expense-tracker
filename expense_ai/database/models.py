"""SQLAlchemy ORM models for the expense tracker's SQLite database."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(16), default="text")  # "text" | "photo"
    notes: Mapped[str] = mapped_column(String(255), default="")
    # Which money bucket this came out of: "balance" (day-to-day spendable
    # money) or "savings" (set aside for a goal, not day-to-day). Almost
    # always "balance" -- moving money into/out of savings goes through
    # Transfer, not this field.
    account: Mapped[str] = mapped_column(String(32), default="balance", server_default="balance")

    receipt: Mapped["Receipt | None"] = relationship(
        back_populates="expense", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Expense id={self.id} amount={self.amount} {self.currency} category={self.category!r}>"


class Income(Base):
    __tablename__ = "income"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    # See Expense.account -- same "balance" vs "savings" bucket concept.
    account: Mapped[str] = mapped_column(String(32), default="balance", server_default="balance")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Income id={self.id} amount={self.amount} {self.currency}>"


class Transfer(Base):
    """Money moved between accounts (balance <-> savings), or a correction
    against the outside world (e.g. "my balance is actually X").

    Deliberately kept separate from Expense/Income: a transfer or balance
    correction is not a transaction you made, so it must never show up in
    "how much did I spend/earn this week" reports. ``from_account`` /
    ``to_account`` of ``None`` means "the outside world" (used for
    corrections rather than an internal move between accounts).
    """

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )
    from_account: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_account: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    note: Mapped[str] = mapped_column(String(255), default="")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Transfer id={self.id} {self.from_account}->{self.to_account} amount={self.amount} {self.currency}>"


class PendingMessage(Base):
    """A text message that couldn't be processed because the LLM was
    unreachable. Retried automatically once the LLM is back (see
    handlers/retry.py); the user gets the normal confirmation reply then,
    just delayed."""

    __tablename__ = "pending_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PendingMessage id={self.id} chat_id={self.chat_id} text={self.text!r}>"


class PendingSync(Base):
    """Marker left by /sync (handlers/balance_sync.py) so the *next* photo
    from that chat is treated as a balance-sync screenshot even without a
    "sync" caption -- consumed (deleted) by the first photo that arrives,
    stale or not; handlers/photo.py only actually routes to the sync flow
    if it was still fresh when consumed. DB-backed rather than in-memory
    so it isn't lost if the bot restarts between the command and the photo."""

    __tablename__ = "pending_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PendingSync id={self.id} chat_id={self.chat_id}>"


class Debt(Base):
    """Money lent to or borrowed from another person -- distinct from
    Expense/Income (it's not a spend or an earning, it's expected to be repaid)
    and from Transfer (it involves another person, not your own two buckets).

    ``direction`` is "lent" (you gave money out, they owe you -- reduces
    ``balance`` immediately) or "borrowed" (you received money, you owe them --
    increases ``balance`` immediately). Settling the debt reverses that effect
    via ``settled_amount`` (defaults to ``amount`` if the repayment matched
    exactly). Always against the "balance" bucket, never "savings".
    """

    __tablename__ = "debts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )
    person: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # "lent" | "borrowed"
    note: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")  # "open" | "settled"
    settled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    settled_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Debt id={self.id} {self.direction} {self.person} amount={self.amount} {self.currency} status={self.status}>"


class SavingsGoal(Base):
    """A named savings target the user is working toward. Progress is
    measured against the shared "savings" bucket total for ``currency`` --
    goals don't partition savings into separate pools (see database/models.py:
    Transfer docstring on why there are only two money buckets, not more).
    One active goal per currency: setting a new goal for a currency replaces
    the old one.
    """

    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    target_date: Mapped[dt.date | None] = mapped_column(nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SavingsGoal name={self.name!r} target={self.target_amount} {self.currency}>"


class Receipt(Base):
    """OCR metadata for a receipt photo linked to an expense (Phase 2)."""

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), unique=True)
    merchant: Mapped[str] = mapped_column(String(255), default="")
    raw_text: Mapped[str] = mapped_column(String, default="")
    image_path: Mapped[str] = mapped_column(String(500), default="")

    expense: Mapped[Expense] = relationship(back_populates="receipt")
