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
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(16), default="text")  # "text" | "photo"
    notes: Mapped[str] = mapped_column(String(255), default="")

    receipt: Mapped["Receipt | None"] = relationship(
        back_populates="expense", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Expense id={self.id} amount={self.amount} {self.currency} category={self.category!r}>"


class Income(Base):
    __tablename__ = "income"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Income id={self.id} amount={self.amount} {self.currency}>"


class Receipt(Base):
    """OCR metadata for a receipt photo linked to an expense (Phase 2)."""

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), unique=True)
    merchant: Mapped[str] = mapped_column(String(255), default="")
    raw_text: Mapped[str] = mapped_column(String, default="")
    image_path: Mapped[str] = mapped_column(String(500), default="")

    expense: Mapped[Expense] = relationship(back_populates="receipt")
