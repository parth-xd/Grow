# 🏗️ Groww Trading System - Claude Code Guidelines

## Core Principle: Build, Never Destroy

### ✅ DO:
- **Only build over what we have** - Add features, improve code, extend functionality
- **Preserve existing code** - Keep all working features intact
- **Ask before changes** - Check with me before modifying behavior
- **Additive only** - New features should layer on top, not replace

### ❌ DON'T:
- **Delete code** - Unless explicitly asked (and confirmed twice)
- **Change existing behavior** - Without discussion first
- **Break working features** - Ever
- **Modify endpoints** - Unless absolutely necessary and pre-approved

---

## Deletion Protocol

**If you want to delete/remove something:**
1. **First ask**: "Should I remove X?"
2. **Wait for confirmation**: Get explicit "yes, remove it"
3. **Ask again**: "Are you 100% sure you want to remove X? This cannot be undone."
4. **Wait for second confirmation**: Get another explicit "yes"
5. **Then delete** - Only after both confirmations

**Even if the user says "just remove it"** - Still ask twice. Better to be safe.

---

## What This Protects

- ✅ Accidental deletions
- ✅ Breaking changes
- ✅ Data loss
- ✅ Feature regressions
- ✅ Configuration overwrites

---

## Examples

**Good:**
- "Add a new scheduler task for cost updates" ✓
- "Fix the watchlist endpoint to..." ✓
- "Create new file: cost_scraper.py" ✓
- "Update the database config" ✓

**Ask First:**
- "Should I remove the old chart_cache directory?"
- "Can I change how WATCHLIST loads?"
- "Should I refactor the auth system?"

**Never Without Explicit Approval:**
- Delete files
- Remove database tables
- Change API endpoints
- Alter core configuration
- Overwrite existing functionality

---

## Current State (As of 2026-07-31)

- **Database**: PostgreSQL with 13 tables, full historical data
- **Watchlist**: 67 stocks in database (10 in config, 57 added dynamically)
- **Cost System**: Automated Groww scraper (3 new files)
- **Graphify**: Knowledge graph tracking 2,035 nodes, 114 communities
- **All Features**: Working and integrated

**Protect this. Build on this. Don't break this.**

---

## Questions Before Action

Always ask yourself:
1. Will this break existing functionality?
2. Can this be done without deleting?
3. Have I explained what I'm doing?
4. Did the user explicitly approve this change?

If any answer is "no" or "I'm not sure" → **ASK FIRST**

---

# 🛠️ Engineering Standards

These are the recurring problems we've hit in this codebase. Check new code
against them, and flag violations you notice in code you're passing through —
even if fixing them isn't the current task.

Run `/codebase-health` to audit the whole repo against this list.

## 1. No N+1 database queries

**What it is:** one query to fetch a list, then another query *per item* in that
list. The per-round-trip overhead (latency, planning, connection handling) is
the same whether one row comes back or a thousand — so N small queries cost
vastly more than one batched query returning N rows.

**Smell:** a `session.query(...)`, `.first()`, `.all()`, `cur.execute(...)`, or
a helper that queries (`get_config`, `_latest_two_snapshots`) *inside* a `for`
loop.

**Fix:** preload into a dict before the loop using one `IN (...)` query, then
look up in Python.

```python
# BAD — 1 + 3N queries
for partner in partners:
    returns = latest_snapshot(session, partner, "returns")

# GOOD — 1 query, grouped in Python
snaps = load_snapshots_bulk(session, partners, data_types=("returns",))
for partner in partners:
    returns = snaps.get((partner, "returns"))
```

Real example: `get_supply_chain_intel` went from 151 queries to **3**.

## 2. Bound every read that can grow

Any query over `stock_prices` (107k rows), `global_news` (52k),
`news_articles` (18k), `company_external_data` (append-only) or `trade_journal`
must have a `LIMIT`, a date floor, or an explicit cap. Accept `?limit=` /
`?days=` on endpoints and **clamp to a server-side maximum** — never trust the
client's number.

Also filter by the columns you actually need. `_load_snapshots_bulk` without a
`data_types` filter loads every historical snapshot on an append-only table.

Reference pattern: `min(int(request.args.get("limit", 50)), 200)`.

## 3. Parallelize independent I/O

If two network calls don't consume each other's output, they should not run one
after another. Sync Flask means each blocking call pins a thread for its whole
duration.

**Smell:** consecutive `requests.get` / yfinance / scrape calls, or
`ThreadPoolExecutor(max_workers=1)` — that's a timeout guard, not parallelism.

**Fix:** `ThreadPoolExecutor` + `as_completed`. Wall time becomes the slowest
single call instead of the sum. Match the existing idiom in
`research_engine.py` (7 loaders, `max_workers=6`).

Real example: watchlist analysis had 6 providers in series; news sentiment had
8 sequential HTTP calls at up to 10s each.

## 4. Optimistic UI for user actions

A mutation the user triggers should reflect **immediately**, with the request in
the background and a rollback on failure. Never make someone wait on a round
trip to see their own click register.

```javascript
const prev = row.style.display;
row.style.display = 'none';        // optimistic
try { await api(url, {method:'DELETE'}); row.remove(); }
catch (e) { row.style.display = prev; toast(e.message); }   // rollback
```

## 5. Never show a blank rectangle

Every async region needs a loading state, sized to the wait:

| Wait | Treatment |
|---|---|
| < 300ms | Nothing — `withLoader` delays so fast loads never flash |
| Small region | `inlineLoader()` |
| Card / table / list | `skeleton(kind, n)` shaped like the real content |
| Multi-second work | `panelOrb(text, sub)` |
| App-wide blocking | boot / backfill overlay |

Use `withLoader(target, work, {tier, n})` rather than hand-rolling. Prefer
skeletons over spinners in content areas: they prevent layout shift and tell
the user what's coming. On error, show a message and a retry — and if the
container already had content, keep it rather than destroying it.

## 6. Label every control

No icon-only button without `aria-label` **and** `title`. Tooltips should say
what the thing *does*, not repeat its label. Div-based controls need
`role`, `tabindex="0"`, and Enter/Space handlers. See `TAB_DESCRIPTIONS` in
`index.html`.

## 7. Missing data must be visible

**If data should be there and isn't, the user must be able to tell.** Silent
gaps are the worst failure mode — a supplier list quietly showed "not matched
to a listed NSE company" for Tata Steel for weeks.

- Add a check to `/api/data-health` for any new dataset with a coverage notion
- Never render a dead end ("no data") — show progress, a reason, or a next step
- Prefer "31% collected, queued" over "not collected"
- Empty states must distinguish *loading* / *genuinely empty* / *failed*

## 8. Config over constants

Anything operational (intervals, limits, thresholds, toggles) belongs in
`config_settings`, editable from Settings — not hardcoded. Read it via
`get_config` (memoized 30s); use `get_configs()` / `get_configs_prefix()` for
batches. Never call `get_config` in a loop.

---

# 🧭 Karpathy Guidelines

Behavioral guidelines to reduce common LLM coding mistakes, derived from
[Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876)
on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial
tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes,
simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it
work") require constant clarification.

**A measurement is a claim.** Before reporting a number, verify the metric
itself is sound — a wrong measurement produces a confident wrong conclusion,
which is worse than no measurement. If a result surprises you, suspect the
instrument before the code.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer
rewrites due to overcomplication, and clarifying questions come before
implementation rather than after mistakes.
