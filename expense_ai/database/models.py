"""SQLAlchemy ORM models for the expense tracker's SQLite database."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    just delayed.

    ``kind`` tells the retry job which path to replay it through: "text"
    (default) goes through the normal build_response() flow, while
    "balance_sync" goes through balance_sync.build_sync_mismatch_response()
    instead, so a delayed cards-screenshot sync still asks via buttons
    rather than dispatch.py auto-applying whatever the LLM says."""

    __tablename__ = "pending_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="text")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PendingMessage id={self.id} chat_id={self.chat_id} kind={self.kind} text={self.text!r}>"


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


class PendingMissedTransaction(Base):
    """Marker left when the "Log missed expense/income" sync button is
    tapped (handlers/balance_sync.py), holding the amount/currency/kind
    while the bot waits for the user to reply with what it was for. The
    next plain-text message from that chat (handlers/text.py) consumes it
    and becomes the description -- the amount itself is never re-derived
    from that reply, only the category/description are."""

    __tablename__ = "pending_missed_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "expense" | "income"
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(), index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PendingMissedTransaction id={self.id} chat_id={self.chat_id} kind={self.kind} amount={self.amount}>"


class CustomCategory(Base):
    """A category added via /category, on top of the fixed CATEGORIES list
    in models/schemas.py. Deliberately created only by explicit user
    command, never invented by the LLM or guessed by local_parser.py --
    see finance.known_categories(), the single place fixed + custom
    categories get combined for validation everywhere a category is
    checked (ExpenseIntent/EditIntent no longer validate categories
    themselves, since a stateless Pydantic validator can't see this
    table)."""

    __tablename__ = "custom_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CustomCategory name={self.name!r}>"
