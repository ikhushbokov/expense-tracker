"""Handlers for editing, deleting, searching, and exporting entries."""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from expense_ai.config import settings
from expense_ai.database import repository, session_scope
from expense_ai.database.models import Expense
from expense_ai.finance import format_amount
from expense_ai.models.schemas import DeleteIntent, EditIntent, ExportIntent, SearchIntent
from expense_ai.periods import resolve_period


def _find_target_expense(session, intent: EditIntent | DeleteIntent) -> Expense | None:
    if intent.target == "search" and intent.keyword:
        matches = repository.list_expenses(session, keyword=intent.keyword)
        return matches[0] if matches else None
    return repository.last_expense(session)


def handle_edit(intent: EditIntent) -> str:
    with session_scope() as session:
        if intent.target == "last_income":
            income = repository.last_income(session)
            if income is None:
                return "You don't have any income entries yet."
            before = format_amount(income.amount, income.currency)
            fields: dict[str, object] = {}
            if intent.new_amount is not None:
                fields["amount"] = intent.new_amount
            if intent.new_description is not None:
                fields["description"] = intent.new_description
            for key, value in fields.items():
                setattr(income, key, value)
            session.flush()
            return f"✏️ Updated income: {before} → {format_amount(income.amount, income.currency)}"

        expense = _find_target_expense(session, intent)
        if expense is None:
            return "I couldn't find a matching expense to edit."

        before = f"{format_amount(expense.amount, expense.currency)} / {expense.category} / {expense.description or '-'}"
        updated = repository.update_expense(
            session,
            expense.id,
            amount=intent.new_amount,
            category=intent.new_category,
            description=intent.new_description,
        )
        assert updated is not None
        after = f"{format_amount(updated.amount, updated.currency)} / {updated.category} / {updated.description or '-'}"
        return f"✏️ Expense updated\nBefore: {before}\nAfter: {after}"


def handle_delete(intent: DeleteIntent) -> str:
    with session_scope() as session:
        if intent.target == "last_income":
            income = repository.last_income(session)
            if income is None:
                return "You don't have any income entries yet."
            summary = format_amount(income.amount, income.currency)
            repository.delete_income(session, income.id)
            return f"\U0001F5D1 Deleted income entry: {summary}"

        if intent.target == "last_expense":
            expense = repository.last_expense(session)
            if expense is None:
                return "You don't have any expenses yet."
            summary = f"{format_amount(expense.amount, expense.currency)} ({expense.category})"
            repository.delete_expense(session, expense.id)
            return f"\U0001F5D1 Deleted expense: {summary}"

        # target == "search": delete every expense matching period/category/keyword
        start, end = resolve_period(intent.period)
        matches = repository.list_expenses(
            session, start=start, end=end, category=intent.category, keyword=intent.keyword
        )
        if not matches:
            return "No matching expenses found to delete."
        total_by_currency: dict[str, float] = {}
        for expense in matches:
            total_by_currency[expense.currency] = total_by_currency.get(expense.currency, 0.0) + expense.amount
            repository.delete_expense(session, expense.id)
        totals = ", ".join(format_amount(v, c) for c, v in total_by_currency.items())
        return f"\U0001F5D1 Deleted {len(matches)} expense(s) totaling {totals}"


def handle_search(intent: SearchIntent) -> str:
    with session_scope() as session:
        start, end = resolve_period(intent.period)
        matches = repository.list_expenses(
            session,
            start=start,
            end=end,
            category=intent.category,
            min_amount=intent.min_amount,
            max_amount=intent.max_amount,
            keyword=intent.keyword,
        )
        if not matches:
            return "No matching expenses found."

        lines = [f"Found {len(matches)} matching expense(s):"]
        for e in matches[:20]:
            date_str = e.datetime.strftime("%Y-%m-%d")
            lines.append(f"{date_str} — {format_amount(e.amount, e.currency)} — {e.category} — {e.description or '-'}")
        if len(matches) > 20:
            lines.append(f"...and {len(matches) - 20} more.")
        total_by_currency: dict[str, float] = {}
        for e in matches:
            total_by_currency[e.currency] = total_by_currency.get(e.currency, 0.0) + e.amount
        lines.append("")
        lines.append("Total: " + ", ".join(format_amount(v, c) for c, v in total_by_currency.items()))
        return "\n".join(lines)


def handle_export(intent: ExportIntent) -> tuple[str, Path | None]:
    with session_scope() as session:
        start, end = resolve_period(intent.period)
        expenses = repository.list_expenses(session, start=start, end=end)
        incomes = repository.list_income(session, start=start, end=end)

        if not expenses and not incomes:
            return "Nothing to export for that period.", None

        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = settings.export_dir_full_path

        if intent.format == "csv":
            path = export_dir / f"expenses_{timestamp}.csv"
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "amount", "currency", "category", "description", "source", "notes"])
                for e in expenses:
                    writer.writerow([e.datetime.isoformat(), e.amount, e.currency, e.category, e.description, e.source, e.notes])

        elif intent.format == "json":
            path = export_dir / f"expenses_{timestamp}.json"
            data = {
                "expenses": [
                    {
                        "date": e.datetime.isoformat(),
                        "amount": e.amount,
                        "currency": e.currency,
                        "category": e.category,
                        "description": e.description,
                    }
                    for e in expenses
                ],
                "income": [
                    {"date": i.datetime.isoformat(), "amount": i.amount, "currency": i.currency, "description": i.description}
                    for i in incomes
                ],
            }
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        elif intent.format == "xlsx":
            from openpyxl import Workbook

            path = export_dir / f"expenses_{timestamp}.xlsx"
            wb = Workbook()
            ws_expenses = wb.active
            ws_expenses.title = "Expenses"
            ws_expenses.append(["Date", "Amount", "Currency", "Category", "Description", "Source", "Notes"])
            for e in expenses:
                ws_expenses.append([e.datetime.isoformat(), e.amount, e.currency, e.category, e.description, e.source, e.notes])

            ws_income = wb.create_sheet("Income")
            ws_income.append(["Date", "Amount", "Currency", "Description"])
            for i in incomes:
                ws_income.append([i.datetime.isoformat(), i.amount, i.currency, i.description])
            wb.save(path)

        else:  # pdf
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            path = export_dir / f"expenses_{timestamp}.pdf"
            c = canvas.Canvas(str(path), pagesize=A4)
            width, height = A4
            y = height - 50
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, y, f"Expense Report — {intent.period.replace('_', ' ').title()}")
            y -= 30
            c.setFont("Helvetica", 10)
            for e in expenses:
                if y < 50:
                    c.showPage()
                    y = height - 50
                c.drawString(50, y, f"{e.datetime.strftime('%Y-%m-%d')}  {format_amount(e.amount, e.currency):>15}  {e.category:<15}  {e.description}")
                y -= 15
            c.save()

    return f"\U0001F4E4 Exported {len(expenses)} expense(s) as {intent.format.upper()}", path
