# Expense AI — CLAUDE.md

Personal (single-user) Telegram expense tracker. You message the bot in
plain language; an LLM classifies the message into a typed intent, which is
validated with Pydantic and then applied to a SQLite DB via SQLAlchemy.
Full feature list and setup steps are in `README.md` — this file covers
what a coding agent needs to work in the codebase productively.

## Architecture (read this before changing behavior)

Message flow: `handlers/text.py` → `parser.parse_message` (`parser.py`,
calls the LLM via `llm.py`) → returns one of the `AnyIntent` Pydantic
models from `models/schemas.py` → `handlers/dispatch.py::build_response`
performs the DB action and builds the reply → `database/repository.py` is
the **only** module allowed to write raw queries; everything else
(finance, handlers, exports, charts) goes through it.

**The LLM never touches the database.** It only ever returns JSON, which
is validated against a schema in `models/schemas.py` before anything is
stored. Malformed/hallucinated output becomes `UnknownIntent`, not bad
data. When adding a new capability, the pattern is always: new intent type
in `models/schemas.py` + `INTENT_MODELS` → prompt update in `parser.py` →
handling branch in `handlers/dispatch.py` (or a new handler module). The
`history` intent (`expense_ai/history.py`, dispatched to from
`dispatch.py`, also reachable via the `/history` command in
`handlers/commands.py`) is a reference example of this pattern end to end,
including a Telegram inline-keyboard reply (`BotResponse.reply_markup`)
and its own callback handler (`handlers/history.py`) for pagination.

### Two money buckets: balance vs. savings

This is the trickiest domain concept and has been the source of past
bugs — read `database/models.py`'s `Transfer` docstring before touching
balance logic.

- `Expense`/`Income` rows have an `account` field (`"balance"` or
  `"savings"`), almost always `"balance"`.
- `Transfer` rows represent movement between buckets (`from_account` →
  `to_account`) **or** an outside-world correction when one side is
  `None` (`SetBalanceIntent` → `finance.reconcile_balance`). Transfers are
  deliberately never counted as income/expense in summaries.
- "Total"/"net worth" = balance + savings combined.
- A `set_balance` intent is a *correction* ("I actually have 2,000,000"),
  never income. A `transfer` intent is an intentional move between the two
  buckets. Don't conflate the two when adding features — a past bug did
  exactly that (deleting a savings entry silently became a transfer).
- Lending/borrowing money is deliberately just a plain `Expense`/`Income`
  now, not a separate ledger — lending is an expense, getting repaid (or
  borrowing) is income. There used to be a dedicated `Debt` model/ledger;
  it was removed (along with `SavingsGoal`, which had zero real usage) in
  favor of this simpler model, at the cost of lending/repayment briefly
  distorting a month's spend/income totals — an accepted tradeoff given
  how rarely it happens. Don't reintroduce a separate debt ledger without
  discussing it first.

### Categories are dynamic, not just the fixed list

`CATEGORIES` in `models/schemas.py` is the *starting* set, not the full
one — `finance.known_categories(session)` is the actual source of truth
(fixed list + anything added via `/category add <name>`, stored in the
`CustomCategory` table). Because that requires a DB session, categories
are **not** validated/coerced in `ExpenseIntent`/`EditIntent` themselves
(a stateless Pydantic validator can't see custom categories) — every
caller that stores a category (`dispatch.py`'s "expense" branch,
`edit_search.py`'s edit handling, `balance_sync.py`'s missed-transaction
flow) is expected to run it through `finance.coerce_category(session,
category)` first.
New categories are only ever created by explicit `/category add` command
— never invented by the LLM or guessed by `local_parser.py`; deciding
"is this worth its own category" is a call left to the user.

### Local-first parsing (`local_parser.py`)

Enabled via `LOCAL_PARSER_ENABLED` (on by default as of this writing).
`dispatch.py::build_response` tries `local_parser.try_parse_locally`
*before* calling the LLM at all, for a handful of common, unambiguous
message shapes (plain expense, income, "undo/delete the last X", export,
chart) — see that module's own docstring for the exact rules and why
each intent type is or isn't covered. It's intentionally paranoid about
false positives (wrong ABSTAIN just costs one LLM call; wrong ACCEPT
writes bad data), and when an expense's category can't be confidently
resolved it still doesn't call the LLM — it logs the expense as "Other"
with `category_confirmed=False`, and `dispatch.py` attaches a one-tap
recategorize keyboard instead of asking the LLM to guess.

### Local `/sync` screenshot OCR (`card_ocr.py`)

`handlers/balance_sync.py` tries `card_ocr.extract_card_read` before its
vision-LLM call, so a `/sync` normally costs nothing and keeps working
during an outage. Two design points that are load-bearing and were both
settled by measurement (numbers in that module's docstring):

- **RapidOCR (PP-OCRv4 via onnxruntime), not Tesseract.** Tesseract
  misreads digits on this app's font in a consistent `3`→`5` way in every
  configuration tried, and once dropped a whole card line; RapidOCR read
  all 12 amounts and 4 card numbers exactly across three real screenshots,
  cropped *or* full-frame — so no crop geometry is assumed, only the `sum`
  suffix every balance carries.
- **It runs as a short-lived subprocess** (`python -m expense_ai.card_ocr`),
  not in-process. onnxruntime never gives memory back within a process
  (`del engine; gc.collect()` recovered 8MB of 168MB), and inference is
  ~1.1s of CPU that would block the asyncio event loop. A process that
  exits returns everything; measured parent RSS stays flat at ~22MB across
  repeated syncs. Cold start is ~1.1s end to end, still faster than the
  LLM call it replaces.

`verify_read` is the safety boundary: it only trusts a read when every
card in `SYNC_CARD_LAST4` was found *and* the amount count matches, and
requires the two decimal places (a dropped separator would read
`1034226.06` as `103422606`). Anything else abstains → LLM. Keep it that
way: unlike a miscategorized expense, a wrong number here writes a
corrupted balance. The reply also itemizes each card's amount rather than
only the total, which is what makes a misread catchable by the user before
they tap a button — don't collapse that back to a single figure.

There used to be a free-text `query` intent (read-only "how much did I
spend"/"what's my balance" questions) and a receipt-photo OCR → LLM
classification flow (`ocr.py`, `Receipt` model). Both were removed: the
owner uses the equivalent slash commands (`/budget`, `/today`, `/month`,
`/total`, `/biggest`, ...) instead of free-text queries, and always types
expenses directly rather than photographing receipts. `handlers/photo.py`
now only routes `/sync` screenshots (see `balance_sync.py`) and points any
other photo back to typing the expense. Don't reintroduce either without
checking this is still true — see the "Product preferences" section below
for the general LLM-minimization direction this bot is moving in.

### Resilience / outage queue

If the LLM is unreachable, `parser.parse_message` raises `llm.LLMError`;
`handlers/text.py` catches it, stores the raw text in `PendingMessage`,
and tells the user plainly. `handlers/retry.py` runs on a
`RETRY_QUEUE_INTERVAL_SECONDS` job (default 60s), replays queued messages
through the same `dispatch.build_response` path once the LLM is back, and
sends the normal reply (prefixed to indicate it was queued) via
`send_response_via_bot`. Keep `build_response` the single source of truth
for "what happens for intent X" — both the live path and the retry path
depend on it staying decoupled from *how* the reply is delivered.

### Timezone

There is no per-request timezone handling — the whole app assumes the
process's own system clock *is* the user's local time, and everywhere
uses naive `dt.datetime.now()`/`dt.date.today()` (period boundaries in
`periods.py`, storage defaults in `database/models.py`/`repository.py`,
history-log dates in `history.py`, "today's date" fed to the LLM in
`parser.py`). `bot.py::_apply_timezone()` sets `TZ` (from `settings.timezone`,
env var `TZ`) and calls `time.tzset()` once at startup specifically so
that assumption holds — this matters most for Docker, where the
container's clock defaults to UTC regardless of the host machine's
timezone (this was a real bug: history timestamps were off by the user's
UTC offset until `TZ` was wired up). Don't reintroduce explicit
`dt.timezone.utc` anywhere in storage/period code — it would silently
diverge from every other naive-local `dt.datetime.now()` call again.

### Access control

`handlers/common.py::restrict_to_owner` rejects any Telegram user whose ID
doesn't match `TELEGRAM_ALLOWED_USER_ID`. This is a single-user bot by
design — see README's "Extending" section for what multi-user would
require (not currently implemented).

### Proactive scheduled jobs

`handlers/scheduled.py` (daily recap, month-end summary, monthly
reconciliation prompt) and `handlers/backup.py` (DB backup) aren't
triggered by a user message at all — they're `job_queue.run_daily`/
`run_monthly`/`run_repeating` jobs registered in `bot.py::build_application`,
so each sends directly via `context.bot.send_message`/`send_document` to
`settings.telegram_allowed_user_id` as the chat_id (valid because this is a
private 1:1 bot — chat_id equals user_id there) rather than replying to an
update. If `TELEGRAM_ALLOWED_USER_ID` isn't set, they log a warning and
skip rather than raising, since there's nowhere to send the message.
`run_daily`/`run_monthly` need an explicit `tzinfo` on the `time`/`when`
argument (`zoneinfo.ZoneInfo(settings.timezone)`) or APScheduler defaults
to UTC regardless of `_apply_timezone()`.

### Settings is a singleton captured at import time — a testing gotcha

Every module does `from expense_ai.config import settings`, which binds a
*direct reference* to whatever object `expense_ai.config.settings` was at
that module's own first import (during pytest collection, before any
fixture runs). `tests/conftest.py::isolated_db` reassigns the
`expense_ai.config.settings` *attribute* to a fresh test-specific
`Settings()` instance, but that reassignment is invisible to modules that
already hold the old direct reference — so mutating the module attribute
alone does **not** isolate them. The fixture works around this by also
patching fields directly on the original shared instance in place
(`monkeypatch.setattr(original_settings, "database_path", ...)`) — and
critically, it captures `original_settings = config_module.settings`
*before* reassigning `config_module.settings`, otherwise it grabs the new
object instead of the one everything else is bound to. This bit
`handlers/backup.py::send_db_backup` specifically, since it opens
`settings.database_path` via raw `sqlite3.connect` rather than going
through `session_scope()`/the SQLAlchemy engine (which the fixture patches
via `db_module.engine`/`SessionLocal`, sidestepping the singleton issue
entirely) — a test that looked isolated was silently reading the real
`data/expenses.db`. If you add a new field to `Settings` that a test needs
to vary (a new API key, a new path, ...), add it to the "patch fields on
`original_settings` too" block in `conftest.py`, not just the env var.

## Commands

```bash
source .venv/bin/activate
python -m pytest expense_ai/tests/ -v     # run tests (isolated temp SQLite, never touches data/expenses.db)
python -m expense_ai.bot                  # run the bot directly
docker compose up -d --build              # run in Docker (restart: unless-stopped)
```

## Conventions

- Settings are centralized in `config.py` (`pydantic-settings`, loaded
  from `.env`) — never hardcode secrets/paths or read `os.environ`
  directly elsewhere; import `expense_ai.config.settings`.
- Multi-currency amounts are **additive, not converted** — there's no
  exchange-rate source, so balances/summaries report each currency
  separately. Don't introduce implicit currency conversion.
- Categories are a fixed list (`CATEGORIES` in `models/schemas.py`);
  unknown categories from the LLM are coerced to `"Other"` by a validator,
  not rejected. Anything edible/drinkable (meals, snacks, coffee, any
  drink) is categorized `"Food"` — there is deliberately no separate
  "Coffee"/"drinks" category; specifics belong in the description instead
  (e.g. "Cold drink"). This was an explicit product decision, not an
  oversight — don't reintroduce a food-adjacent category without asking.
- `handlers/edit_search.py::handle_edit` always checks whether a requested
  edit would actually change anything (compares each `new_*` field against
  the current value) before writing, and replies "That's already what I
  have: ..." instead of a false-positive "Expense updated" when nothing
  changed. Keep this check when touching that function — a silent no-op
  that claims success reads as a bug (this was reported as one).
- Finding *which* expense an edit/delete targets (`target="search"`) uses
  `period`/`category`/`keyword` to narrow, and falls back to the most
  recent expense if nothing matches, rather than refusing — see
  `_find_target_expense` in `edit_search.py`. `list_expenses`'s keyword
  filter matches category too, not just description/notes, so "the food
  expense" finds something even when the description doesn't say "food".

## Product preferences (from prior sessions)

- This is genuinely single-user (the owner). Don't add aggressive
  guardrails/refusals for "out of scope" requests in the LLM prompt or
  handlers — the owner explicitly wants to be able to tell the bot
  unusual things (e.g. ad-hoc card-balance corrections) and have it
  figure out how to store them, not get filtered/refused.
- Cost-consciousness matters: the LLM model has been switched before
  specifically to reduce per-message cost (currently configured via
  `LLM_MODEL` in `.env`, default `gpt-4o-mini` in `config.py`). Don't
  casually suggest swapping to a more expensive model without flagging
  the cost tradeoff.
- Ongoing direction: minimize LLM usage generally, not just cost per call
  — features get moved to `local_parser.py` or plain slash commands
  whenever a shape is common/deterministic enough (see git history around
  the Debt/SavingsGoal removal, `/category`, and the free-text query/
  receipt-OCR removal for the pattern). When a feature is genuinely
  free-text/open-ended in a way a command can't replace (e.g. a totally
  novel message that doesn't fit any known shape), the LLM stays as a
  last-resort fallback rather than being ripped out — the goal is fewer
  calls in the common path, not zero LLM infrastructure. Financial writes
  with no confirmation step before applying (e.g. `set_balance`) are
  intentionally kept on the LLM rather than a local parser even where one
  would be technically easy to write — a locally-misparsed amount there
  would silently corrupt the tracked balance with nothing to catch it,
  unlike a miscategorized expense (which just needs a tap to fix).
