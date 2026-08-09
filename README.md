# Expense AI — AI-Powered Telegram Expense Tracker

A personal finance assistant you talk to like a human, over Telegram.
Send it a message like *"Spent 85,000 on groceries"* or *"How much did I
spend this month?"* and it understands, categorizes, stores, and answers
— powered by an LLM you configure (OpenAI, OpenRouter, Ollama, vLLM, or
any OpenAI-compatible endpoint).

```
"Spent 85,000 UZS on groceries."        -> recorded as an expense, categorized "Food"
"Salary came today: 6,500,000 UZS."     -> recorded as income
"How much did I spend this month?"      -> natural-language query, answered from SQLite
"Show me a pie chart of this month"     -> chart image sent back
```

---

## Features

- **Natural language** expense & income logging — no commands required.
- **LLM-driven intent understanding** — pluggable across OpenAI, OpenRouter,
  Ollama, vLLM, LM Studio, or any OpenAI-compatible server.
- **SQLite storage** (via SQLAlchemy) — expenses, income, and OCR'd receipt
  metadata.
- **Automatic categorization** into a starting set of categories (Food,
  Transport, Gym, Supplements, Health, Entertainment, Shopping, Education,
  Bills, Rent, Restaurants, Electronics, Subscriptions, Travel, Family,
  Gifts, Charity, Other), extendable any time with `/category add <name>` —
  new categories are only ever created by you, never guessed by the LLM.
  Anything edible/drinkable — meals, snacks, coffee, any drink — is
  categorized "Food", with the specific item left in the description (e.g.
  "Cold drink") rather than split into its own category. Donations
  (charity, mosque/church/temple, someone in need) are categorized
  "Charity", separate from "Gifts" (presents/money for a specific person
  you know).
- **Running balance** (income − expenses), tracked per currency.
- **Monthly/weekly/daily summaries** with category breakdowns and
  percentages.
- **Receipt photo OCR** (Tesseract) → LLM classification → stored expense.
- **Editing & deletion**: "Undo the last expense", "Change groceries to
  95,000", "Delete today's taxi" — entries are found by keyword, category,
  or date, not just "the last one".
- **Search**: "Show everything over 500,000", "Search for protein".
- **Day-by-day history**: `/history` (or "show me my history", "what did
  I do on July 1st") shows one day's expenses/income/transfers at a time,
  with ◀/▶ buttons to page a day at a time — stays a fixed size no matter
  how much history accumulates.
- **Export**: CSV, Excel (.xlsx), JSON, or PDF.
- **Charts** (matplotlib): category pie chart, monthly/weekly spending bar
  charts, balance-over-time line chart.
- **Two separate money buckets — balance and savings**: "balance" is your
  day-to-day spendable money; "savings" is set aside for a goal and never
  counted in balance/spending queries unless you ask for it specifically.
  "Total" / "net worth" is the two combined.
- **Balance/savings correction**: declare your real balance or savings in
  plain language (e.g. "I have two cards, 9710 card: 411k, 3901 card:
  629k", or "I have 2,000,000 saved up") and the bot reconciles the
  stored total via a Transfer entry — this is a correction, never counted
  as income or spending.
- **Transfers**: "Transfer 200,000 from balance to savings" moves money
  between the two buckets without affecting your total net worth.
- **Lending & borrowing**: recorded as a plain expense/income rather than a
  separate ledger — "Gave Aziz 300,000, he'll pay me back" is an expense,
  "Aziz paid me back 300,000" / "Borrowed 200k from Vali" is income.
- **Month-over-month insights**: `/month` (and the month-end recap) call
  out how this month's spending compares to last month, overall and by
  category.
- **No-spend streaks**: `/today` and the daily recap note how many days
  it's been since your last expense.
- **Proactive scheduled messages**: an evening spending recap, a month-end
  summary with insights, and a monthly "does this balance still look
  right?" nudge — sent to you without asking, no LLM cost. Times are
  configurable (`DAILY_SUMMARY_HOUR`, `RECONCILIATION_HOUR`).
- **Automatic DB backups**: a consistent copy of the SQLite database is
  sent to you as a Telegram document on a schedule (`BACKUP_INTERVAL_HOURS`,
  default 24h) — a free offsite backup of your entire financial history.
- **Offline HTML dashboard**: `/dashboard` generates a self-contained
  report (balances, category breakdown, 6-month trend) as a single HTML
  file you can open in any browser, no internet connection needed.
- **Resilient to LLM/network outages**: if the LLM is unreachable when you
  message the bot, it tells you plainly, saves your message to a durable
  queue, and automatically retries every `RETRY_QUEUE_INTERVAL_SECONDS`
  (default 60s) once the LLM is back — you get the normal confirmation
  reply, just delayed, prefixed to make clear it was queued.
- **Docker packaging**: `docker compose up -d` with `restart: unless-stopped`
  so the bot survives reboots as long as Docker itself starts on boot.

---

## Project Structure

```
expense_tracker/
├── expense_ai/
│   ├── bot.py                # Entrypoint: builds & runs the Telegram bot
│   ├── config.py              # Typed settings loaded from .env
│   ├── logging_setup.py       # Console + rotating file logging
│   ├── llm.py                 # OpenAI-compatible client wrapper
│   ├── parser.py               # LLM prompt + intent classification
│   ├── local_parser.py          # No-LLM parsing for common expense/income/undo/export/chart messages
│   ├── finance.py              # Balance / summary / category math
│   ├── periods.py               # "this_month" -> (start, end) resolution
│   ├── keyboards.py               # Shared month/week ◀/▶ pagination keyboards
│   ├── ocr.py                   # Tesseract receipt OCR
│   ├── reports.py               # matplotlib chart generation
│   ├── history.py                # Day-by-day ledger (expenses/income/transfers)
│   ├── income.py                  # Month-by-month income log
│   ├── dashboard.py                # Self-contained offline HTML report generator
│   ├── database/
│   │   ├── __init__.py           # Engine/session management, init_db()
│   │   ├── models.py              # SQLAlchemy ORM models (incl. CustomCategory)
│   │   └── repository.py          # All CRUD queries
│   ├── models/
│   │   └── schemas.py             # Pydantic schemas for LLM-structured intents
│   ├── handlers/
│   │   ├── common.py               # Owner-only access guard
│   │   ├── commands.py              # /start, /help, /history, /income, /category, /dashboard, quick commands
│   │   ├── text.py                   # Routes text messages by intent
│   │   ├── photo.py                   # Receipt photo -> OCR -> expense
│   │   ├── queries.py                  # Read-only Q&A (balance, summaries...)
│   │   ├── edit_search.py               # Edit / delete / search / export
│   │   ├── history.py                    # /history Prev/Next pagination callback
│   │   ├── income.py                      # /income Prev/Next pagination callback
│   │   ├── summary.py                     # /month, /week Prev/Next pagination callback
│   │   ├── scheduled.py                    # Proactive daily/month-end/reconciliation jobs
│   │   └── backup.py                       # Periodic DB backup sent as a Telegram document
│   └── tests/                    # pytest suite
├── data/                       # SQLite DB + downloaded receipt photos (gitignored)
├── exports/                    # Generated CSV/XLSX/JSON/PDF/PNG files (gitignored)
├── logs/                       # Rotating log files (gitignored)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Prerequisites

- Python 3.12+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed
  and on your `PATH` (for receipt photo support):
  ```bash
  sudo apt install tesseract-ocr   # Debian/Ubuntu
  brew install tesseract           # macOS
  ```
- A Telegram bot token from [@BotFather](https://t.me/BotFather).

### 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | Your Telegram numeric user ID; restricts the bot to you only. Leave empty to allow anyone with the token. |
| `LLM_BASE_URL` | OpenAI-compatible base URL (see table below) |
| `LLM_API_KEY` | API key (leave as-is/blank for local servers that don't need one) |
| `LLM_MODEL` | Model name/id |
| `DATABASE_PATH` | Path to the SQLite file (default `data/expenses.db`) |
| `DEFAULT_CURRENCY` | Currency assumed when the user doesn't mention one |
| `TZ` | IANA timezone (e.g. `Asia/Tashkent`). **Set this explicitly for Docker** — a container's clock is UTC by default regardless of the host machine's timezone, which otherwise makes every date/time the bot shows off by your UTC offset. |
| `TESSERACT_CMD` | Path to the `tesseract` binary if not on `PATH` |

#### Switching LLM providers

Because every provider below speaks the OpenAI `/v1/chat/completions`
protocol, switching is just changing three `.env` values — no code changes:

| Provider | `LLM_BASE_URL` | Notes |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | Needs `LLM_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | Needs `LLM_API_KEY` |
| Ollama | `http://localhost:11434/v1` | `ollama pull <model>` first |
| vLLM | `http://localhost:8000/v1` | Run `vllm serve <model>` |
| LM Studio | `http://localhost:1234/v1` | Enable "Local Server" in LM Studio |

To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot).

### 4. Run

**Directly:**
```bash
python -m expense_ai.bot
```

**Or with Docker (recommended for always-on use):**
```bash
docker compose up -d --build
```
This runs the bot in a container with `restart: unless-stopped`, so as long
as Docker itself is enabled at boot (`systemctl enable docker`, which is the
default on most distros), the bot comes back automatically after every
reboot. Data/logs/exports are bind-mounted to `./data`, `./logs`,
`./exports` so nothing lives only inside the container. Check on it with
`docker compose logs -f` / `docker compose ps`.

The bot initializes the SQLite database automatically on first run and
starts polling for Telegram messages.

---

## Usage examples

**Quick commands** (instant, bypass the LLM entirely — work even during an
LLM outage): `/today`, `/week`, `/month` (spending summaries — `/week` and
`/month` have ◀/▶ buttons to page through past weeks/months, and `/month`
includes month-over-month insights), `/income` (this month's income, with
◀/▶ to page past months), `/budget` (balance), `/savings`, `/total`
(balance + savings), `/category list` / `/category add <name>`,
`/biggest`, `/chart`, `/dashboard` (offline HTML report), `/history`
(optionally `/history 2026-06-15` for a specific date).

**Recording:**
- "Spent 85,000 UZS on groceries."
- "Bought protein for 420,000."
- "Salary came today: 6,500,000 UZS."
- "Freelance payment 350 dollars."

**Querying:**
- "How much did I spend today?"
- "Show food expenses this month."
- "Biggest expenses this month?"
- "Current balance?"
- "Summarize June."

**Editing:**
- "Undo the last expense."
- "Change grocery expense to 95,000."
- "Move protein from Food to Supplements."

**Search & export:**
- "Show everything over 500,000."
- "Search for protein."
- "Export this month as Excel."

**History:**
- "Show me my history." (defaults to today; ◀/▶ buttons page a day at a time)
- "What did I spend on July 1st?"
- "Let me see last week's transactions."

**Charts:**
- "Show me a pie chart of this month's spending."
- "Show my monthly spending chart."

**Receipts:** just send a photo of a receipt — the bot OCRs it, asks the
LLM to classify it, and records the expense automatically.

**Balance & savings:**
- "My current balance is: I have two cards, 9710 card: 411k, 3901 card: 629k."
- "I actually have 2,000,000 left."
- "I have 2,000,000 saved up." (sets savings, not balance)
- "Transfer 200,000 from balance to savings."
- "How much are my savings?"
- "What's my total money?" / "What's my net worth?"

**Lending & borrowing:** recorded as a plain expense/income, not a separate
loan ledger.
- "Gave Aziz 300,000, he'll pay me back next week." (an expense)
- "Aziz paid me back 300,000." / "Borrowed 200k from Vali." (income)

**Categories:**
- `/category list` — shows every category currently in use.
- `/category add Freelance Clients` — adds a new one you can categorize
  expenses/income into; the bot never invents categories on its own.

**Proactive (no message needed):** an evening recap of the day, a month-end
summary with month-over-month insights, a monthly "does this balance still
look right?" nudge, and a periodic database backup sent as a document — all
on a schedule (`DAILY_SUMMARY_HOUR`, `RECONCILIATION_HOUR`,
`BACKUP_INTERVAL_HOURS` in `.env`).

---

## Testing

```bash
python -m pytest expense_ai/tests/ -v
```

Tests cover the repository (CRUD), finance calculations (balance,
summaries, percentages), period resolution, and LLM-output schema
validation. They run against an isolated temporary SQLite file — your
real data is never touched.

---

## Architecture notes

- **The LLM never touches the database directly.** `parser.py` asks the
  LLM for JSON, then validates it against a Pydantic schema
  (`models/schemas.py`) before anything is stored — malformed or
  hallucinated output becomes an `UnknownIntent` instead of bad data.
- **Multi-currency is additive, not converted.** Since there's no
  reliable exchange-rate source wired in, balances/summaries report each
  currency separately rather than guessing a conversion rate.
- **`database/repository.py` is the only place that writes raw SQL
  queries** — every other module (finance, handlers, exports, charts)
  goes through it, so storage details stay swappable.

---

## Extending

The architecture is designed so these can be added without restructuring:

- **Voice messages**: transcribe with Whisper (or an OpenAI-compatible
  STT endpoint), then feed the transcript into `parser.parse_message`
  exactly like a text message.
- **Budget planning / recurring expenses**: new SQLAlchemy models next to
  `Expense`/`Income` in `database/models.py`, new repository functions,
  a new intent type in `models/schemas.py`.
- **Multiple users**: add a `telegram_user_id` column to `Expense`/
  `Income`, scope every repository query by it, and drop the
  single-owner restriction in `handlers/common.py`.
- **Web dashboard**: the `database/repository.py` functions are already
  framework-agnostic — a FastAPI app could import them directly.

---

## Troubleshooting

- **"This bot is private."** — Set `TELEGRAM_ALLOWED_USER_ID` to your own
  ID, or leave it blank during testing.
- **OCR returns garbage / empty text** — make sure `tesseract-ocr` is
  installed and `TESSERACT_CMD` points to the right binary; try a
  clearer, well-lit, non-blurry photo.
- **LLM returns non-JSON / errors** — check `LLM_BASE_URL` and
  `LLM_MODEL` match what your provider expects; check `logs/bot.log` for
  the raw response.
- **Charts say "not enough data"** — you need at least one expense in the
  requested period for a chart to be generated.
