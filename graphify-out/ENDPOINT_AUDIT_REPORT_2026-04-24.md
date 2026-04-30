# Endpoint Audit Report

Date: 2026-04-24

## Scope

This report is based on verified local code and data in:

- `app.py`
- `bot.py`
- `paper_trader.py`
- `trade_journal.py`
- `paper_trade_reconciliation.py`
- `index.html`
- `paper_trades.json`
- `trade_journal.json`
- `graphify-out/GRAPH_REPORT.md`

It focuses on the active dashboard, paper trading, journal, settings, and the specific LT quantity mismatch that was reported.

## Verified LT Discrepancy

### Raw local data before the fix

From the current local files on 2026-04-24:

- `paper_trades.json`
  - LT total records: 45
  - LT open records: 1
  - LT open quantity: 12

- `trade_journal.json`
  - LT total records: 88
  - LT open records: 86
  - LT open quantity: 432

### Why it differed

The mismatch was real and came from two separate bugs:

1. Paper trades had two identities.
   - `PaperTradeTracker.record_entry()` created tracker IDs like `LT-B-20260424151422998047`.
   - `trade_journal.create_pre_trade_report()` generated a second journal ID.
   - When the tracker later closed the trade, it tried to close the journal using the tracker ID, so the journal entry often stayed open.

2. Paper auto-trades were being journaled twice.
   - `bot.auto_trade()` created a pre-trade journal report before `place_buy()`.
   - In paper mode, `place_buy()` called `_paper_trade()`, which created another paper journal report again.
   - That produced duplicate LT journal rows and inflated open quantity in the journal.

### Verified state after reconciliation logic

Using the new canonical reconciliation path:

- LT paper records: 45
- LT open records: 1
- LT open quantity: 12

This now matches the tracker state and removes the phantom journal quantity inflation from the UI.

## Fixes Applied

### 1. Canonical paper trade view

Added `paper_trade_reconciliation.py`.

Purpose:

- merges tracker-backed paper trades with journal rows
- treats tracker status as authoritative for paper trades
- removes duplicate placeholder journal rows from the active UI view
- keeps DB-only paper entries (for example `PAPER-...` intraday records) visible if they do not map to tracker trades

Used by:

- `/api/paper-trading/status`
- `/api/journal`
- `/api/journal/open`
- `/api/journal/closed`
- `/api/journal/stats`
- `/api/journal/<trade_id>`

### 2. Paper trade ID alignment

Updated:

- `bot._paper_trade()`
- `trade_journal.create_pre_trade_report()`

Change:

- paper trades now write the journal record with the same `trade_id` as the tracker record
- duplicate journal creation for the same explicit `trade_id` is now blocked

### 3. Removed duplicate paper journal creation path

Updated:

- `bot.auto_trade()`

Change:

- in paper mode, the pre-trade journal is no longer created before `place_buy()`
- `_paper_trade()` is now the only paper-trade journal creation path

### 4. Re-enabled automated paper close sync

Updated:

- `paper_trader.close_trade()`
- `trade_journal.close_matching_paper_trade()`
- `/api/close-trade`
- `/api/journal/<trade_id>/close`

Change:

- tracker-backed closes now sync to the journal using the tracker ID
- legacy journal rows can still be closed through a symbol/side/quantity/price/time match if needed
- manual close now goes through the tracker instead of editing the JSON file directly

### 5. Fixed missing automation fields in new paper trades

Updated:

- `paper_trader.record_entry()`

Change:

- new paper trades now persist:
  - `side`
  - `stop_loss`
  - `projected_exit`
  - `entry_profit_target`

These fields were missing in newly created tracker trades and weakened target/stop-loss automation.

### 6. Fixed broken Settings navigation

Updated:

- `index.html`

Change:

- added an actual `Settings` tab
- replaced click-only tab logic with `activateTab(tabName)`
- header Settings button now activates the settings panel directly

### 7. Removed visible dashboard emoji

Updated:

- `index.html`

Change:

- removed emoji from visible buttons, labels, notices, toasts, and status chips
- left text-cleaning regexes/comments intact where they are part of parsing logic rather than UI

## Endpoint Connection Map

This section is limited to verified, code-backed connections that are active in the current dashboard.

### Paper trading status flow

Frontend:

- `index.html` `loadPaperTradingStatus()`

Endpoints and functions:

- `GET /api/paper-trading/status`
- `app.paper_trading_status()`
- `app._get_canonical_journal_views()`
- `paper_trade_reconciliation.build_canonical_trade_views()`

Data sources:

- `TradeJournalEntry` rows from DB
- `paper_trades.json`

Output:

- reconciled paper trade list for the Paper Trading tab

### Paper auto-trade creation flow

Entry point:

- `POST /api/auto-trade`
- `app.auto_trade()`
- `bot.auto_trade()`

Paper buy path:

- `bot.place_buy()`
- paper-mode branch
- `bot._paper_trade()`
- `PaperTradeTracker.record_entry()`
- `trade_journal.create_pre_trade_report()`

Persistence:

- tracker state to `paper_trades.json`
- paper journal state to `trade_journal` / DB
- trade log entry persisted separately

### Paper trade close flow

Frontend paths:

- paper table manual close
- journal close button

Endpoints and functions:

- `POST /api/close-trade`
- `POST /api/journal/<trade_id>/close`
- `PaperTradeTracker.close_trade()`
- `trade_journal.close_matching_paper_trade()`
- `trade_journal.close_trade_report()`

Result:

- tracker closes
- journal closes
- canonical UI stays aligned

### Trailing stop / auto-close flow

Frontend:

- `index.html` `loadPaperTradingStatus()`

Endpoints and functions:

- `POST /api/update-trailing-stops`
- `app.update_trailing_stops()`
- `PaperTradeTracker.update_trailing_stop()`

- `POST /api/auto-close/check`
- `app.check_trailing_stop_exits()`
- `trailing_stop.check_and_close_trades_on_loss()`
- `trailing_stop.manage_loss_positions()`

Important note:

- the automation engine still reads `paper_trades.json`, so the tracker remains the operational source for paper-trade lifecycle
- the dashboard now reads the reconciled backend view instead of reading the file directly in the browser

### Trade journal flow

Frontend:

- `loadJournal()`

Endpoints:

- `GET /api/journal`
- `GET /api/journal/open`
- `GET /api/journal/closed`
- `GET /api/journal/stats`
- `GET /api/journal/<trade_id>`

Backend:

- canonicalized through `app._get_canonical_journal_views()`
- enriched with candle overlays through `trade_chart_manager`

### Settings flow

Frontend:

- `openSettings()`
- `activateTab('settings')`
- `loadPaperTradingSettings()`
- `loadSchedulerSettings()`

Endpoints:

- `GET /api/paper-trading/settings`
- `POST /api/paper-trading/settings`
- `GET /api/paper-trading/status`
- `GET /api/scheduler/settings`
- `POST /api/scheduler/settings`

Backend:

- DB-backed config read/write via `get_config()` / `set_config()`

### Trade snapshot flow

Frontend:

- `loadTradeSnapshots()`

Current connection:

- `GET /api/paper-trading/status`
- uses canonical paper trade data first
- then fetches per-trade market candles via snapshot/candle endpoints

This used to read `paper_trades.json` directly in the browser. That direct read was removed.

## No-Hallucination / Fake-Data Audit

### Fixed in this pass

- Paper Trading tab no longer invents its own truth by reading `paper_trades.json` separately from the backend.
- Trade Journal no longer surfaces duplicated paper rows as if they were additional live quantity.
- Manual close no longer edits only one store and leaves the other stale.

### Still important to improve

These are not all "fake data", but they are places where derived or fallback values can appear and should be clearly disclosed or tightened.

1. `GET /api/latest-price/<symbol>`
   - after-hours fallback to the latest stored close
   - acceptable if labeled as delayed/last available, but it is not live market data

2. `commodity_tracker._fallback_result()`
   - returns a neutral fallback when commodity data fails
   - this is synthetic fallback logic and should always remain clearly marked as fallback

3. `portfolio_analyzer.py`
   - contains `result["ltp"] = avg_price` fallback
   - this can silently turn cost basis into current price if real price lookup fails

4. `research_engine.py`
   - includes at least one default assumption path (`balance_sub = 60`)
   - this is heuristic scoring, not observed market data

5. `app.py /api/auth/demo`
   - explicitly creates demo data
   - fine for testing, not for production environments that require strict real-data semantics

## Functions That Should Be Improved Next

### High priority

1. `bot.auto_trade()`
   - does scanning, gating, journaling, order execution, GTT creation, and action reporting in one function
   - should be split into:
     - signal selection
     - trade sizing
     - order execution
     - journal persistence
     - post-order risk setup

2. `index.html loadPaperTradingStatus()`
   - still mixes fetching, live-price enrichment, trailing-stop refresh, auto-close orchestration, and rendering
   - should be split into:
     - fetch paper state
     - fetch prices
     - run background automation
     - render

3. `app.py`
   - route file is too large and mixes pages, auth, research, paper trading, journaling, snapshots, telegram, NLP, and options
   - should be split into blueprints/modules by domain

### Medium priority

4. `trade_journal.py`
   - persistence, reporting, matching, and narrative generation all live together
   - a service split between storage and analysis would reduce side effects

5. `paper_trader.py`
   - still relies on JSON-file persistence for operational state
   - long term, tracker state should move to DB so trailing-stop automation and dashboard reads share one durable store

6. `trailing_stop.py`
   - writes close results into tracker JSON directly
   - should call a shared paper-trade service so close logic is not duplicated across routes and automation

## Recommended Next Steps

1. Move paper-trade operational state from JSON into the DB.
2. Split `app.py` into domain blueprints.
3. Extract a dedicated paper-trade service used by:
   - auto-trade
   - manual close
   - journal close
   - trailing-stop automation
   - snapshot generation
4. Add a small regression test around LT-style duplicate paper trades:
   - create one paper trade
   - verify one journal row
   - close it
   - verify journal open quantity returns to zero

## Files Changed In This Fix

- `app.py`
- `bot.py`
- `paper_trader.py`
- `trade_journal.py`
- `paper_trade_reconciliation.py`
- `index.html`
