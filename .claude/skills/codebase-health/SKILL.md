---
name: codebase-health
description: Audit this trading codebase against its engineering standards — N+1 database queries, unbounded reads, sequential blocking I/O, missing loading states, non-optimistic UI, unlabelled controls, invisible data gaps, and hardcoded config. Use when the user asks to check code health, find performance problems, run an audit, or before shipping a significant change. Also use when asked about N+1 queries, pagination, async/blocking calls, skeletons/loaders, or accessibility in this repo.
---

# Codebase Health Audit

Audits the Groww trading system against the eight standards in `CLAUDE.md`.
Every check below has caused a real bug in this repo — the greps are tuned to
those specific failure modes, not generic lint.

## How to run it

Work through the categories in order. Each has a detection command and a
judgement rule. **Report findings; do not fix anything without asking** —
`CLAUDE.md` requires confirmation before changes, and twice before deletions.

Severity: **HIGH** if it runs on a user-facing request path, **MEDIUM** if
scheduler/background, **LOW** otherwise.

---

## 1. N+1 database queries

```bash
# queries inside loops
grep -n -A12 "for .* in .*:" *.py | grep -E "session\.query|\.first\(\)|\.all\(\)|cur\.execute|conn\.execute"
# config reads inside loops (each is a round-trip unless batched)
grep -n -B6 "get_config(" *.py | grep -E "for .* in"
```

**Confirm before reporting:** is the call genuinely inside the loop body, and
does it hit the DB? `Stock.get_competitors()` looks like a query but is a
`json.loads` of an already-loaded column — a false positive.

**Report as:** "N queries for N items at `file:line` — batch with one
`IN (...)` query into a dict."

Known-good reference: `tijori_collector._load_snapshots_bulk`,
`app.py` `/api/raw-materials/supply-chain` (preload dict, zero queries in loop).

---

## 2. Unbounded reads

```bash
grep -nE "\.all\(\)" *.py | grep -v "limit(" | grep -vi "config"
grep -nE "SELECT \*|fetchall\(\)" *.py
grep -n "request.args.get(\"limit\"" app.py    # verify each is clamped
```

Large tables: `stock_prices` (~108k), `global_news` (~52k), `news_articles`
(~18k), `company_external_data` (append-only, grows every scrape),
`candles`, `trade_journal` (two JSON blobs per row).

**Flag:** any read of those with no LIMIT/date floor; any `?limit=` accepted
without `min(..., MAX)`; any `_load_snapshots_bulk` call without `data_types`.

Reference pattern: `min(int(request.args.get("limit", 50)), 200)`.

---

## 3. Sequential blocking I/O

```bash
grep -nE "requests\.(get|post)|yf\.|yfinance|time\.sleep" *.py
grep -n "ThreadPoolExecutor(max_workers=1)" *.py     # timeout guard, not parallelism
```

**Judgement:** consecutive network calls where none consumes another's output
should be parallel. Check whether the results are only read *after* all of them
complete — if so, they're independent.

Also flag any `requests.get` without a `timeout=`.

**Report as:** "N sequential network calls at `file:line`, each up to Xs —
independent, so wall time could be the slowest rather than the sum."

Reference idiom: `research_engine.py` (7 loaders, `ThreadPoolExecutor(max_workers=6)`
+ `as_completed`).

---

## 4. Non-optimistic mutations

```bash
grep -nE "method: '(POST|DELETE|PUT)'" index.html
```

For each, read the surrounding function. **Flag** if it `await`s the request
and only then updates the DOM (or calls a full reload) with no immediate
feedback. User-triggered mutations should apply instantly and roll back on
error.

Exception: destructive actions behind a `confirm()` still need the optimistic
update *after* confirmation.

---

## 5. Blank loading states

```bash
grep -c "innerHTML = ''" index.html
grep -nE "innerHTML = ['\`][^'\`]*Loading\.\.\." index.html    # plain text, no loader
# which tabs get a loading tier when activated
sed -n "/function handleTabActivation/,/^}/p" index.html | grep -E "tabName ===|withLoader|load[A-Z]"
```

Loaders are injected at runtime by `withLoader`, **not** present in static
markup — so grepping the panel HTML gives false negatives. Check
`handleTabActivation` instead: every branch that fetches should either wrap the
call in `withLoader(...)` or delegate to a function that manages its own
loading element (like `loadWatchlist` → `#watchlist-loading`).

**Flag:** a branch that calls a loader with neither; any region blanked before
an await with no placeholder; any bare "Loading..." text.

**Fix direction:** `withLoader(target, work, {tier, n})` — tiers are
`inline` / `text` / `cards` / `table` / `list` / `chart` / `orb`.

---

## 6. Unlabelled controls

```bash
grep -oE '<button[^>]*>[^<]{0,3}</button>' index.html    # icon-only buttons
grep -c "aria-label" index.html
grep -oE 'onclick="[a-zA-Z]+\([^)]*\)"[^>]*>[▸▾×✕⟳↻⋮]' index.html
```

**Flag:** icon-only or empty-text buttons without `aria-label` and `title`;
clickable `<div>`/`<span>` without `role` + `tabindex` + key handler; tooltips
that merely repeat the visible label instead of explaining the action.

---

## 7. Invisible data gaps

This is the check that matters most — it catches the class of bug where the
dashboard confidently shows nothing.

```bash
grep -n "add(" app.py | grep -A2 "data_health"      # what /api/data-health covers
grep -nE "no data|not collected|unavailable|N/A" index.html
```

**Ask for each dataset:** if this were 20% populated instead of 100%, would the
user notice? If not, it needs a `/api/data-health` check.

**Flag:**
- A dataset with a coverage notion that has no health check
- Any dead-end empty state — "no data" with no progress, reason, or next step
- Empty states that can't distinguish *loading* / *empty* / *failed*
- A renderer that silently drops backend fields (e.g. a hardcoded section
  whitelist that omits new keys — this exact bug hid the supply-chain section)

```bash
# renderers that filter backend data through a fixed list
grep -nE "sectionOrder|const .*Order = \[" index.html
```

---

## 8. Hardcoded operational values

```bash
grep -nE "= (300|600|900|1800|3600|86400)\b" *.py | grep -viE "config|test"
grep -nE "_FALLBACK|HARDCODED|^[A-Z_]{4,} = \{" *.py
```

**Flag:** intervals, limits, thresholds, or toggles not read from
`config_settings`. Fallback dicts are acceptable *as fallbacks* but the primary
source should be the DB.

Verify config reads use the memoized `get_config`, and that loops use
`get_configs()` / `get_configs_prefix()` instead of per-key calls.

---

## Output format

Group by severity, most severe first. For each finding give:

- `file:line`
- the offending snippet (2–4 lines)
- why it matters *in this codebase* (which endpoint, how many items)
- the concrete fix, naming the existing pattern to copy

Close with a one-line count per category. If a category is clean, say so —
that's information too.

**Then stop and ask** which findings to fix. Do not edit files as part of the
audit.
