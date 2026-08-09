"""Generates a self-contained, offline-readable HTML report -- for when
Telegram's chat format feels too cramped to eyeball trends. No JS/CSS CDN
dependency: the bar/trend visuals are plain inline CSS, so the file works
if you just double-click it, no internet connection required. Sent as a
document via /dashboard, mirroring handlers/edit_search.py's export pattern.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy.orm import Session

from expense_ai.config import settings
from expense_ai.finance import (
    category_breakdown,
    format_amount,
    get_balances,
    get_net_worth,
    total_expenses_by_currency,
)
from expense_ai.periods import month_range, shift_month

_STYLE = """
<style>
  body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; background: #0f1115; color: #e7e9ee; margin: 0; padding: 24px; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .generated { color: #8b8f9a; font-size: 13px; margin-bottom: 24px; }
  .cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
  .card { background: #1a1d24; border-radius: 10px; padding: 16px 20px; min-width: 180px; }
  .card .label { color: #8b8f9a; font-size: 13px; }
  .card .value { font-size: 20px; font-weight: 600; margin-top: 4px; }
  h2 { font-size: 16px; border-bottom: 1px solid #2a2e38; padding-bottom: 8px; margin-top: 32px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  td, th { text-align: left; padding: 6px 8px; font-size: 14px; }
  th { color: #8b8f9a; font-weight: 500; }
  .bar-track { background: #2a2e38; border-radius: 4px; height: 10px; width: 100%; }
  .bar-fill { background: #5b8cff; border-radius: 4px; height: 10px; }
  .trend { display: flex; align-items: flex-end; gap: 10px; height: 140px; margin-top: 16px; }
  .trend .col { display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; flex: 1; }
  .trend .col-bar { background: #5b8cff; width: 100%; border-radius: 4px 4px 0 0; }
  .trend .col-label { color: #8b8f9a; font-size: 11px; margin-top: 6px; }
  .trend .col-value { font-size: 11px; margin-bottom: 4px; }
  .empty { color: #8b8f9a; font-style: italic; }
  ul { padding-left: 20px; }
</style>
"""


def _card(label: str, value: str) -> str:
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div></div>'


def _balance_cards(session: Session) -> str:
    balance = get_balances(session, account="balance")
    savings = get_balances(session, account="savings")
    net_worth = get_net_worth(session)
    cards = []
    for label, amounts in (("Balance", balance), ("Savings", savings), ("Net worth", net_worth)):
        text = ", ".join(format_amount(v, c) for c, v in amounts.items()) or "—"
        cards.append(_card(label, text))
    return '<div class="cards">' + "".join(cards) + "</div>"


def _category_table(session: Session, *, year: int, month: int) -> str:
    start, end = month_range(year, month)
    breakdown = category_breakdown(session, start=start, end=end)
    if not breakdown:
        return '<p class="empty">No expenses recorded this month.</p>'
    max_total = max(c.total for c in breakdown)
    rows = []
    for c in breakdown:
        width = (c.total / max_total * 100) if max_total else 0
        rows.append(
            f"<tr><td>{c.category}</td><td>{format_amount(c.total, c.currency)} ({c.percentage:.0f}%)</td>"
            f'<td style="width:40%"><div class="bar-track"><div class="bar-fill" style="width:{width:.0f}%"></div></div></td></tr>'
        )
    return "<table><tr><th>Category</th><th>Amount</th><th></th></tr>" + "".join(rows) + "</table>"


def _monthly_trend(session: Session, *, year: int, month: int, months_back: int = 6) -> str:
    points = []
    y, m = year, month
    for _ in range(months_back):
        start, end = month_range(y, m)
        totals = total_expenses_by_currency(session, start=start, end=end)
        points.append((y, m, sum(totals.values())))
        y, m = shift_month(y, m, -1)
    points.reverse()

    max_value = max((value for _, _, value in points), default=0)
    cols = []
    for y, m, value in points:
        height = (value / max_value * 100) if max_value else 0
        label = dt.date(y, m, 1).strftime("%b")
        cols.append(
            f'<div class="col"><div class="col-value">{value:,.0f}</div>'
            f'<div class="col-bar" style="height:{height:.0f}%"></div>'
            f'<div class="col-label">{label}</div></div>'
        )
    return '<div class="trend">' + "".join(cols) + "</div>"


def generate_dashboard_html(session: Session) -> Path:
    today = dt.date.today()
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Expense Dashboard</title>{_STYLE}</head>
<body>
<h1>\U0001F4CA Expense Dashboard</h1>
<div class="generated">Generated {today.strftime('%B %d, %Y')}</div>

{_balance_cards(session)}

<h2>{today.strftime('%B %Y')} by category</h2>
{_category_table(session, year=today.year, month=today.month)}

<h2>Last 6 months spending</h2>
{_monthly_trend(session, year=today.year, month=today.month)}

</body></html>"""

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = settings.export_dir_full_path / f"dashboard_{timestamp}.html"
    path.write_text(html, encoding="utf-8")
    return path
