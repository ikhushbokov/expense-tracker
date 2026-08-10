# Expense AI — AI-Powered Telegram Expense Tracker

A personal finance assistant you talk to like a human, over Telegram.
Send it a message like *"Spent 85,000 on groceries"* and it understands,
categorizes, and stores it — most common messages are handled instantly
with no LLM call at all (see `local_parser.py`); an LLM you configure
(OpenAI, OpenRouter, Ollama, vLLM, or any OpenAI-compatible endpoint)
is the fallback for anything less common.

```
"Spent 85,000 UZS on groceries."        -> recorded as an expense, categorized "Food"
"Salary came today: 6,500,000 UZS."     -> recorded as income
"Show me a pie chart of this month"     -> chart image sent back
```

Read-only questions (balance, summaries, totals) go through slash commands
(`/budget`, `/today`, `/month`, `/total`, `/biggest`, ...) rather than
free text — instant, and no LLM involved.

---

## Features

- **Natural language** expense & income logging — no commands required.
- **Local-first parsing**: a plain expense/income message, "undo the last
  X", export, and chart requests are recognized instantly with regex and
  your own history, no LLM call needed. An LLM (pluggable across OpenAI,
  OpenRouter, Ollama, vLLM, LM Studio, or any OpenAI-compatible server)
  handles anything that doesn't match — editing/deleting a specific past
  entry, balance corrections, and anything genuinely unusual.
- **SQLite storage** (via SQLAlchemy).
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
- **Balance sync from a screenshot** (`/sync`): send a screenshot of your
  banking app's card list and the bot reads each card's balance, sums them
  in Python, and compares against the tracked balance. It shows the
  per-card amounts it read (so a misread is visible) and asks whether to
  apply it as a correction or log the difference as a missed
  expense/income — nothing is written until you tap a button. Reading is
  done locally with no LLM call when `SYNC_CARD_LAST4` is configured and
  every listed card is found; otherwise it falls back to a vision model.
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
- **Runs as a background service**: a launchd agent on macOS (~130MB, starts
  at login, relaunched automatically if it ever exits), or via Docker with
  `restart: unless-stopped` — both survive reboots; see Run below.

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
│   ├── card_ocr.py               # No-LLM OCR of /sync card screenshots (RapidOCR, in a subprocess)
│   ├── finance.py              # Balance / summary / category math
│   ├── periods.py               # "this_month" -> (start, end) resolution
│   ├── keyboards.py               # Shared month/week ◀/▶ pagination keyboards
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
│   │   ├── photo.py                   # Routes /sync screenshots; other photos get a hint to type instead
│   │   ├── edit_search.py               # Edit / delete / search / export
│   │   ├── history.py                    # /history Prev/Next pagination callback
│   │   ├── income.py                      # /income Prev/Next pagination callback
│   │   ├── summary.py                     # /month, /week Prev/Next pagination callback
│   │   ├── scheduled.py                    # Proactive daily/month-end/reconciliation jobs
│   │   └── backup.py                       # Periodic DB backup sent as a Telegram document
│   └── tests/                    # pytest suite
├── deploy/                     # launchd agent template for running as a service
├── data/                       # SQLite DB (gitignored)
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
- A Telegram bot token from [@BotFather](https://t.me/BotFather).

### 2. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then the local `/sync` screenshot OCR engine, which needs `--no-deps` so its
`opencv-python` dependency stays satisfied by the headless build pinned in
`requirements.txt` (the GUI build would drag in ~200MB of Mesa/X11 system
libraries this bot never uses):

```bash
pip install --no-deps rapidocr-onnxruntime==1.4.4
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
| `SYNC_CARD_LAST4` | Comma-separated last-4 digits of the cards shown in your banking app (e.g. `1111,2222,3333,4444`). Enables reading `/sync` screenshots locally with no LLM call; a read is only trusted when every listed card is found. Empty = always use the vision LLM. |

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

**In the foreground** (for development):
```bash
python -m expense_ai.bot
```

**As a background service on macOS (recommended for always-on use):**

```bash
sed "s|__PROJECT_DIR__|$PWD|g" deploy/com.expense-ai.bot.plist.example \
  > ~/Library/LaunchAgents/com.expense-ai.bot.plist
launchctl load ~/Library/LaunchAgents/com.expense-ai.bot.plist
```

`RunAtLoad` + `KeepAlive` in that plist mean the bot starts when you log in
and is relaunched automatically if it ever exits — the same guarantee
`restart: unless-stopped` gives in Docker, for ~130MB instead of the ~3.1GB
Docker Desktop costs on macOS (a Linux VM plus an Electron dashboard, to run
one Python process). Manage it with:

```bash
launchctl list | grep expense-ai      # PID and last exit status
tail -f logs/bot.log                  # what it's doing
```

To stop it, or to restart after changing the code:
```bash
launchctl unload ~/Library/LaunchAgents/com.expense-ai.bot.plist
```

**Or with Docker**, which still works and is the better option on a Linux
server (where Docker has no VM/GUI overhead):
```bash
docker compose up -d --build
```
`restart: unless-stopped` brings it back after a reboot as long as Docker
starts at boot. Data/logs/exports are bind-mounted to `./data`, `./logs`,
`./exports`, so the SQLite database is the same file either way and you can
switch between the two freely — just don't run both at once, since two
pollers on one bot token conflict.

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

**Querying:** there's no free-text query intent — balance/spending
questions ("how much did I spend today?", "current balance?") always go
through the quick commands above instead, so they're instant and need no
LLM call.

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
- **LLM returns non-JSON / errors** — check `LLM_BASE_URL` and
  `LLM_MODEL` match what your provider expects; check `logs/bot.log` for
  the raw response.
- **Charts say "not enough data"** — you need at least one expense in the
  requested period for a chart to be generated.
