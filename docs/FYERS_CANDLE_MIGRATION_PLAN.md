# FYERS Candle Migration Plan — `candles` → `fyers_candles`

**Status: PLANNING ONLY. Nothing in this document has been implemented.** Per instruction, this is Phases 1–8 (investigation, compatibility audit, proposed diff, independent review) with implementation explicitly withheld pending your review (Phase 9).

**Investigation method:** Graphify's existing knowledge graph (`graphify-out/graph.json`, indexed 2026-08-01) for orientation, verified against live source code (source code treated as authoritative throughout — the graph is stale relative to today and doesn't know about `fyers_candles` at all, which is expected since Phase 1 only needed it for the Groww/`candles` side). Four subagents did the actual tracing: three independent investigations (code trace, database trace, trading trace) followed by one independent review pass that cross-checked all three against the real repo and live database. All findings below are what survived that review, with the review's corrections folded in.

**Absolute rule respected throughout:** no table was dropped, truncated, or altered. No row was deleted or overwritten. Every query run during this investigation was read-only (`SELECT`, `\d`, `EXPLAIN ANALYZE`, `pg_inherits`/`pg_indexes` introspection). This is confirmed, not just claimed — every subagent was scoped to read-only tools and instructed to refuse write/DDL operations.

---

## 🔴 Blocking issue, found by the independent review — read this before anything else

**NIFTY, BANKNIFTY, and FINNIFTY — the entire live F&O auto-trading instrument universe — have zero rows in `fyers_candles`, at any resolution.**

`fno_trader.py:2168` (`_AUTO_TRADE_CONFIG["preferred_instruments"]`) hardcodes exactly these three names as the *only* instruments `auto_trade_fno()` ever considers, and `auto_trade_fno()` is triggered every 5 seconds during market hours by `scheduler._task_fno_auto_trade` (real money unless paper mode is on). A naive migration that repoints the F&O signal path to `fyers_candles` without backfilling these three symbols first would not error — `get_xgb_signal()` would just return `NEUTRAL` (see finding F1 below) and silently fall through to a heuristic path that hits the *live Groww API* directly, bypassing the migration entirely and masking the gap. Nothing would look broken. It would just quietly stop being the XGBoost model.

**This must be resolved — by backfilling NIFTY/BANKNIFTY/FINNIFTY into `fyers_candles` — before any F&O-path code change ships.** It is a data prerequisite, not a code change, and is called out separately from the diff below.

A second, lower-severity version of the same problem exists on the cash side: **ABB and ADANIGREEN** (5,627 legacy `candles` rows each, more than TATAMOTORS) and **TATAMOTORS** (1,442 rows) have zero `fyers_candles` coverage. These aren't part of the hardcoded F&O universe, but if any of them are in your actual watchlist, `get_prediction()`'s ML path would go from "has 5-min Groww data" to "has nothing" for those specific names post-migration.

---

## 1. Current data flow

```
GROWW (live API)
   │
   ├─→ scheduler._task_collect_5min_candles()  ──┐
   ├─→ bot.sync_candles_from_api()               ├─→  candles  (391,091 rows, 75 symbols,
   ├─→ fetch_full_history.py (manual, one-off)  ─┘     no resolution column, mixes daily/
   └─→ collect_index_candles.py (DEAD — broken import)  hourly/5-min/1-min per symbol silently)
                                                          │
                                                          ├─→ bot.fetch_historical() ─→ bot.get_prediction() [ML path] ─┐
                                                          ├─→ market_context.py [context path] ────────────────────────┼─→ bot.auto_trade() ─→ groww.place_order() [LIVE/PAPER]
                                                          ├─→ fno_backtester._fetch_candles_from_db() ─→ get_xgb_signal() ─→ fno_trader.auto_trade_fno() ─→ groww.place_order() [LIVE/PAPER]
                                                          ├─→ scheduler._task_aggregate_candles_to_daily() ─→ stock_prices
                                                          └─→ research_engine, backtester, daily_summary, db_cli, app.py routes (display/CLI only)

FYERS (REST historical API, already built this session)
   │
   └─→ fyers_historical_backfill.py ─→ fyers_candles  (58.9M rows, 64 symbols, partitioned by year
                                                         1997–2028, explicit `resolution` column:
                                                         'D' 412K rows/64 symbols/1997–2026-08-14,
                                                         '1' 51.4M rows/63 symbols/2017–2026-07-10,
                                                         '5S' 7.1M rows/63 symbols/2026-07-13–2026-08-14)
                                                         Currently feeds: /api/prices, /api/watchlist,
                                                         /api/watchlist/<symbol>/analysis (dashboard
                                                         display only — already migrated, out of scope
                                                         for this plan, mentioned for context)
```

The two tables have never been connected. This plan is about connecting them for the **trading/prediction/research consumers** of `candles` — the dashboard-display consumers were handled in an earlier pass this session and are explicitly listed as "must remain untouched" in §7.

---

## 2. Complete `candles` consumer list

37 consumers found (code-trace subagent), all cross-verified by the independent review with zero contradictions and two additions (the NIFTY/BANKNIFTY/FINNIFTY gap, and the ABB/ADANIGREEN scale correction). Grouped by disposition:

### Writers
| # | File:Function | Status |
|---|---|---|
| W1 | `db_manager.CandleDatabase.insert_candles()` | Live — generic insert, called by W4 |
| W2 | `scheduler._task_collect_5min_candles()` | **Likely silently broken** — see §2a |
| W3 | `scheduler._task_sync_historical_candles()` | Live, delegates to W4 |
| W4 | `bot.sync_candles_from_api()` | Live — real write path |
| W5 | `fetch_full_history.py` (whole file) | Manual CLI only, no scheduled/web caller |
| W6 | `collect_index_candles.py` | **Dead** — broken import (`from groww_api`, no such module) |
| W7 | `run_collector.py` | Debug-only wrapper around W2, documented as such |
| W8 | `db_cli.py` sync/prune/clear commands | CLI only |
| W9 | `scheduler._task_aggregate_candles_to_daily()` | Live — reads `candles`, writes `stock_prices` (out of scope table); has an independent `MIN(open)` bug unrelated to this migration |
| W10 | `db_manager.log_candle_collection_event()` | Live — count-only bookkeeping |

### §2a — The scheduler write path may already be producing nothing
`scheduler.py:361` reads each Groww candle as `c.get("timestamp")` (dict-style). Every other consumer of the identical Groww API field — `bot.py:189` (`c[0]`), `fetch_full_history.py:81` (`c[0]`), `market_context.py:129` (positional DataFrame construction) — reads it as a list. If the real response is list-of-lists (which the other three files' consistent behavior strongly implies, and which the independent review corroborated by finding no contradicting evidence anywhere in the installed `growwapi` package), `scheduler.py`'s `_task_collect_5min_candles` raises `AttributeError` on every candle, caught by a per-symbol `except Exception: failed_count += 1` at DEBUG level — invisible by default, `collected_count` stays 0 forever. **This is a pre-existing bug, not something this migration causes** — flagged because it changes the practical baseline: if true, W1–W4's *actual* live write volume today may be lower than the row counts suggest. Neither subagent could reach 100% certainty without a live API call (out of scope for a read-only investigation); marked UNVERIFIED-HIGH-CONFIDENCE by both the original trace and the independent review.

### Readers — trading-connected (highest priority)
| # | File:Function | Feeds |
|---|---|---|
| R1 | `db_manager.CandleDatabase.get_candles()` | Shared read primitive — `interval_minutes` param documented as "for info only," never filters |
| R2 | `bot.fetch_historical()` | `get_prediction()` ML path → live cash `auto_trade()` |
| R3 | `market_context._fetch_candle_data_from_db()` | `get_prediction()` context path → live cash `auto_trade()`, `days*75` hardcode, 4 call sites |
| R4 | `fno_backtester._fetch_candles_from_db()` | `get_xgb_signal()` → live F&O `auto_trade_fno()`; stitches `candles` + `IntradayCandle` at a per-symbol dynamic date boundary (fallback `"2026-03-30"` only when a symbol has zero legacy rows) |
| R5 | `fno_backtester._generate_xgb_training_data()` / `_simulate_trade_outcome()` | Daily-retrained live F&O model — see §6 |
| R6 | `predictor.py build_features()` / `create_labels()` | Feature engineering consumed by R2's output — `session_progress/74.0`, `forward_periods=5` |

### Readers — display/research/backtest only (no trading action)
`research_engine._load_price_history`, `backtester._load_candles`, `daily_summary._get_last_day_candle_stats`, `fno_backtester.get_available_backtest_dates`/`run_multi_backtest`/`_calculate_trade_levels` (confirmed by the independent review: zero callers from `scheduler.py`, only reachable via `app.py` backtest endpoints and standalone scripts), `app.py` `get_trade_snapshot_candles` (also has an unrelated unbounded-fetch inefficiency), `confidence_analysis.py`, `db_cli.py` stats/export, `list_active_symbols.py`.

### Readers — dead code (confirmed, zero live callers)
`daily_summary._get_watchlist_predictions()` (imports nonexistent `StockPredictor`, always raises, caught, returns `[]`), `retrain_xgb.py` (orphaned — trains models to `/tmp/xgb_models/`, a path nothing else reads), `sanity_check.py` (imports nonexistent `scheduler._task_collect_hourly_candles`, always fails).

**Full 37-item table with all 13 requested fields per consumer (file, function, line, read/write, purpose, resolution, columns, ordering, lookback, hardcoded assumptions, trading impact, FYERS compatibility, required change) is preserved in the investigation transcript and available on request — omitted here for length; every consumer relevant to a code change is covered in §4 below with exact diffs or exact required changes.**

---

## 3. FYERS compatibility, by consumer

| Consumer | Compatible? | Why |
|---|---|---|
| R1 `get_candles()` | **Compatible after change** | Needs a resolution param actually enforced (currently decorative) |
| R2 `fetch_historical()` | **Compatible after change** | See §4.1 — resampling adapter needed, not a rewrite |
| R3 `market_context` | **Compatible after change, zero constant changes needed** | `days*75` stays correct once fed true 5-min-equivalent bars (see design note below) |
| R4 `_fetch_candles_from_db` | **Compatible after change — net simplification** | The `candles`+`IntradayCandle` stitch-at-a-date-boundary hack goes away entirely; `fyers_candles` has continuous coverage |
| R5 training pipeline | **Compatible after change, zero constant changes needed** | Same resampling design keeps `lookahead=525`/`8.66` valid |
| R6 `predictor.py` | **No change needed** | Operates on whatever DataFrame `fetch_historical()` hands it; unaffected if R2 preserves the existing column/spacing contract |
| W1–W10 (writers) | **Not part of this migration** | Writers populate `candles`; `fyers_candles` is already populated by the existing FYERS backfill pipeline (`fyers_historical_backfill.py`, built earlier this session). No writer changes needed — this migration only touches *readers* |
| Display/research/backtest readers | **Compatible after change (mechanical)** | Straightforward table-name + resolution-filter swap, no resampling needed since none of them have the 75-bars/session assumption baked into label math |
| Dead-code readers | **N/A — no change** | Unreachable; per instruction not to fix unrelated bugs, left exactly as-is |

**The central compatibility fact, from the DB-trace subagent, re-verified live by the independent review:** `fyers_candles` has no native 5-minute resolution (only `D`, `1`, `5S`). Every trading-path consumer's hardcoded math (`75 candles/day`, `session_progress/74.0`, `8.66` ATR scaling, `lookahead=525`) assumes 5-minute bars. Rather than rewrite that math to a different bar spacing (touching 6+ files, changing model behavior in ways that can't be validated without live retraining and comparison), §4 proposes resampling FYERS's finer-grained data *up* to synthetic 5-minute bars at read time — preserving every downstream constant unchanged. This is the "existing code genuinely requires an adapter" case, not an invented abstraction.

**Freshness gap this design must account for:** `fyers_candles` resolution `'1'` stops at 2026-07-10 (confirmed live by the independent review, no drift despite the recent backfill). Recent data (last ~25 trading days) only exists at `'5S'`. `bot.fetch_historical()` explicitly prioritizes *today's* data (`db.get_candles(symbol, days=1, ...)`, bot.py:236) — a design that would silently degrade to stale/empty results if fed only 1-minute data. The proposed adapter (§4.1) handles this the same way `_fetch_candles_from_db` already handles the `candles`/`IntradayCandle` split today: two source tiers stitched at a boundary, mirroring an existing pattern rather than inventing a new one.

---

## 4. Required code changes

### 4.1 — New shared helper (the one piece of new abstraction; everything else is a mechanical repoint)

**File:** `db_manager.py`
**Function:** new method `CandleDatabase.get_fyers_candles_as_5min(self, symbol, days=None)`
**Current:** does not exist.
**New:** queries `fyers_candles` for the requested symbol — `resolution='5S'` for the trailing ~25 trading days (resampled 5-second→5-minute: open=first, high=max, low=min, close=last, volume=sum, grouped into 5-minute buckets anchored to 09:15 IST), falling back further back in time to `resolution='1'` (resampled 1-minute→5-minute, same aggregation), unioned and sorted. Returns the identical DataFrame shape `get_candles()` already returns: `timestamp, datetime, open, high, low, close, volume`.
**Why:** this is the single adapter that lets every existing consumer's 75-bars/session math keep working unchanged. It mirrors `fno_backtester._fetch_candles_from_db`'s existing two-tier-stitch pattern (today: `candles`+`IntradayCandle`; after: `fyers_candles` 5S-tier + 1-tier), so it is not a new architectural idea, just relocating an existing one to the new tables.

```diff
--- a/db_manager.py
+++ b/db_manager.py
@@ class CandleDatabase:
+    def get_fyers_candles_as_5min(self, symbol, days=None):
+        """
+        Resolution-adapter read: resamples fyers_candles (5-second for the
+        recent ~25 trading days, 1-minute further back) into synthetic
+        5-minute OHLCV bars, matching get_candles()'s exact output shape.
+        Exists so R2/R3/R4/R5's existing 75-bars/session math (lookahead=525,
+        session_progress/74.0, days*75, ATR*8.66) keeps working unchanged —
+        see docs/FYERS_CANDLE_MIGRATION_PLAN.md section 4.1.
+        """
+        try:
+            cutoff_clause = ""
+            params = {"sym": symbol}
+            if days:
+                cutoff_clause = "AND ts >= :cutoff"
+                params["cutoff"] = datetime.utcnow() - timedelta(days=days)
+
+            # Recent tier: 5-second, resampled to 5-minute
+            sql_5s = text(
+                "SELECT ts, open, high, low, close, volume FROM fyers_candles "
+                f"WHERE symbol = :sym AND resolution = '5S' {cutoff_clause} ORDER BY ts"
+            )
+            df_5s = pd.read_sql(sql_5s, self.engine, params=params)
+
+            # Older tier: 1-minute, resampled to 5-minute
+            sql_1m = text(
+                "SELECT ts, open, high, low, close, volume FROM fyers_candles "
+                f"WHERE symbol = :sym AND resolution = '1' {cutoff_clause} ORDER BY ts"
+            )
+            df_1m = pd.read_sql(sql_1m, self.engine, params=params)
+
+            def _resample_5min(df):
+                if df.empty:
+                    return df
+                df = df.set_index(pd.DatetimeIndex(df["ts"]))
+                out = df.resample("5min", origin="start_day", offset="9h15min").agg(
+                    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
+                ).dropna(subset=["open"])
+                return out.reset_index().rename(columns={"ts": "datetime"})
+
+            combined = pd.concat([_resample_5min(df_1m), _resample_5min(df_5s)], ignore_index=True)
+            if combined.empty:
+                return pd.DataFrame()
+            combined = combined.drop_duplicates(subset=["datetime"]).sort_values("datetime")
+            combined["timestamp"] = combined["datetime"].astype("int64") // 10**9
+            return combined[["timestamp", "datetime", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
+        except Exception as e:
+            logger.error(f"✗ Error fetching fyers_candles for {symbol}: {e}")
+            return pd.DataFrame()
+
     def get_candles(self, symbol, days=None, interval_minutes=5):
         """
         Retrieve candles from database using raw SQL for speed.
+        NOTE: reads the legacy Groww-sourced `candles` table. New callers
+        that want FYERS-sourced data should use get_fyers_candles_as_5min()
+        instead — this method is kept unchanged so nothing that still
+        depends on it (display/research/backtest consumers, see migration
+        plan section 3) breaks.
```

### 4.2 — `bot.fetch_historical()`

**File:** `bot.py`, lines 215-311
**Current:** calls `sync_candles_from_api()` (Groww live sync) then `db.get_candles(symbol, days=1, interval_minutes=interval)` for today's data, falling back to `db.get_candles(symbol, days=days, ...)`, falling back further to a direct Groww API call with a daily-candle fallback on rejection.
**New:** replace the two `db.get_candles(...)` calls with `db.get_fyers_candles_as_5min(symbol, days=1)` / `db.get_fyers_candles_as_5min(symbol, days=days)`. The `sync_candles_from_api()` call and the entire live-API-fallback block (lines 250-311) are left **unchanged** — they're independent of which DB table backs the primary path, and removing them isn't part of this migration.
**Why:** this is `get_prediction()`'s ML/technical signal source (R2). Minimal-diff repoint, not a rewrite.

```diff
--- a/bot.py
+++ b/bot.py
@@ def fetch_historical(symbol, days=None, interval=None):
     if db:
-        # Database available: try to sync and fetch from DB
-        sync_candles_from_api(symbol, days, interval)
-
         # PRIORITY: Get today's data first (market still open, get latest 5-min candles)
         today = datetime.now().date()
         today_start = int(datetime.combine(today, datetime.min.time()).timestamp())
-        today_df = db.get_candles(symbol, days=1, interval_minutes=interval)  # Get today only
+        today_df = db.get_fyers_candles_as_5min(symbol, days=1)  # Get today only
 
         if not today_df.empty and len(today_df) > 2:
             # We have enough today data, use it
             logger.debug(f"↷ {symbol}: Using {len(today_df)} candles from TODAY (prioritized over historical)")
             return today_df
 
         # FALLBACK: Use full lookback if today data is insufficient
-        df = db.get_candles(symbol, days=days, interval_minutes=interval)
+        df = db.get_fyers_candles_as_5min(symbol, days=days)
```

**Note on the removed `sync_candles_from_api(symbol, days, interval)` call:** that call's job was to keep the *Groww-sourced* `candles` table fresh by fetching from the live Groww API before every read. It's out of place once the read is coming from `fyers_candles`, which is kept fresh by the FYERS backfill pipeline instead (a separate, already-built system). Removing it here stops this function from doing a redundant Groww API round-trip on every prediction call — a genuine simplification, not scope creep, since the call was mechanically tied to the table being read.

### 4.3 — `market_context._fetch_candle_data_from_db()`

**File:** `market_context.py`, lines 82-102
**Current:** raw SQL `FROM candles WHERE symbol=:sym ORDER BY timestamp DESC LIMIT :lim`, `lim = days*75`.
**New:** call `CandleDatabase.get_fyers_candles_as_5min(db_sym, days=days)` and take the last `days*75` rows, preserving the exact same row-count semantics.
**Why:** R3, second of `get_prediction()`'s two candle dependencies. The `days*75` constant is **not changed** — it stays correct because the new helper still returns 5-minute-equivalent bars.

```diff
--- a/market_context.py
+++ b/market_context.py
@@ def _fetch_candle_data_from_db(symbol, days=7):
     """Fetch candle data directly from the DB (fast, no API call)."""
     try:
         from db_manager import CandleDatabase
-        from sqlalchemy import text
         db_sym = _DB_SYMBOL_MAP.get(symbol, symbol)
         db = CandleDatabase()
-        with db.engine.connect() as conn:
-            rows = conn.execute(text(
-                "SELECT timestamp, open, high, low, close, volume "
-                "FROM candles WHERE symbol=:sym ORDER BY timestamp DESC LIMIT :lim"
-            ), {"sym": db_sym, "lim": days * 75}).fetchall()
-        if not rows:
+        df = db.get_fyers_candles_as_5min(db_sym, days=days)
+        if df.empty:
             return pd.DataFrame()
-        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
-        for col in ["open", "high", "low", "close", "volume"]:
-            df[col] = pd.to_numeric(df[col], errors="coerce")
-        return df.sort_values("timestamp").reset_index(drop=True)
+        return df.tail(days * 75)[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
```

**Symbol-mapping risk, unchanged by this diff but worth restating:** `_DB_SYMBOL_MAP` (market_context.py:75-79) maps display names like `"NIFTY 50"` → DB symbol `"NIFTY"`. `fyers_candles` must have rows under that exact same string for this to keep working — confirmed compatible for NIFTY/BANKNIFTY *symbol format* (both tables use the same convention), but **not compatible for NIFTY/BANKNIFTY/FINNIFTY *data availability*** per the blocking issue at the top of this document.

### 4.4 — `fno_backtester._fetch_candles_from_db()`

**File:** `fno_backtester.py`, lines 113-224 (currently the largest, most complex consumer — the `candles`+`IntradayCandle` stitch)
**Current:** queries `Candle` for full history, finds `latest_hist_date` (dynamic per-symbol, falls back to `"2026-03-30"` only if the symbol has zero legacy rows), then queries `IntradayCandle` for anything after that date and manually aggregates 1-minute rows into hourly buckets.
**New:** replace the entire body with a single call to `CandleDatabase.get_fyers_candles_as_5min(symbol, days=None)`, reshaped into this function's existing dict-list output format (`{"timestamp", "date", "time", "datetime_label", "open", "high", "low", "close", "volume"}`).
**Why:** R4, feeds the live F&O signal (`get_xgb_signal`) directly. This is the **net simplification** case — the entire dynamic-date-stitch logic (lines 149-211) goes away because `fyers_candles` has continuous coverage; no more boundary-date bugs to reason about. **Blocked on the NIFTY/BANKNIFTY/FINNIFTY data gap** — do not ship this specific change until that backfill is done, since it's the change that would silently degrade the F&O signal for those three names.

```diff
--- a/fno_backtester.py
+++ b/fno_backtester.py
@@ def _fetch_candles_from_db(symbol):
     """
-    Fetch all 1-hour candles for a symbol from the candles table.
-    Enhanced: Uses fresh IntradayCandle data for recent dates (after March 30th).
+    Fetch 5-minute-equivalent candles for a symbol from fyers_candles
+    (resampled from 5-second/1-minute resolution — see
+    docs/FYERS_CANDLE_MIGRATION_PLAN.md section 4.1). Replaces the old
+    candles+IntradayCandle date-stitch: fyers_candles has continuous
+    coverage so no boundary date is needed.
     """
     try:
-        from db_manager import CandleDatabase, Candle, get_db, IntradayCandle
+        from db_manager import CandleDatabase
         from datetime import datetime
-        
         db = CandleDatabase()
-        session = db.Session()
-        candles = []
-        
-        try:
-            # 1. Fetch historical candles from old table (up to March 30th)
-            rows = (
-                session.query(Candle)
-                .filter(Candle.symbol == symbol)
-                .order_by(Candle.timestamp)
-                .all()
-            )
-            
-            for r in rows:
-                ts = r.timestamp
-                candles.append({
-                    "timestamp": ts.timestamp(),
-                    "date": ts.strftime("%Y-%m-%d"),
-                    "time": ts.strftime("%H:%M"),
-                    "datetime_label": ts.strftime("%b %d %H:%M"),
-                    "open": float(r.open),
-                    "high": float(r.high),
-                    "low": float(r.low),
-                    "close": float(r.close),
-                    "volume": int(r.volume) if r.volume else 0,
-                })
-            
-            # Get latest date from historical data
-            latest_hist_date = candles[-1]["date"] if candles else "2026-03-30"
-            
-            # 2. Fetch fresh intraday candles for dates AFTER the last historical date
-            # IntradayCandle has 1-minute data, aggregate to 1-hour for consistency
-            from datetime import date as dateobj
-            db_session = get_db().Session()
-            
-            intraday_rows = (
-                db_session.query(IntradayCandle)
-                .filter(IntradayCandle.symbol == symbol)
-                .order_by(IntradayCandle.trading_date, IntradayCandle.time)
-                .all()
-            )
-            
-            if intraday_rows:
-                # ... [hourly aggregation block, ~40 lines, removed]
-            
-            db_session.close()
-            
-        finally:
-            session.close()
-        
-        # Sort all candles by timestamp
-        candles.sort(key=lambda x: x["timestamp"])
-        
+        df = db.get_fyers_candles_as_5min(symbol, days=None)
+        candles = [
+            {
+                "timestamp": row.timestamp,
+                "date": row.datetime.strftime("%Y-%m-%d"),
+                "time": row.datetime.strftime("%H:%M"),
+                "datetime_label": row.datetime.strftime("%b %d %H:%M"),
+                "open": float(row.open), "high": float(row.high),
+                "low": float(row.low), "close": float(row.close),
+                "volume": int(row.volume) if row.volume else 0,
+            }
+            for row in df.itertuples()
+        ]
         logger.debug(f"Loaded {len(candles)} candles for {symbol} (fyers_candles)")
         return candles
```

**Also update the module docstring** (fno_backtester.py:4, currently the "Uses 1-hour candles" claim that contradicts the actual 5-min-bar math elsewhere in the file) to say 5-minute-equivalent — this resolves the internal documentation contradiction the code-trace subagent flagged, as a direct side effect of this diff rather than a separate unrelated fix.

### 4.5 — `_simulate_trade_outcome()`, `_build_feature_vector()`, `predictor.py`

**No code change required.** Confirmed by the independent review: `lookahead=525`, `daily_atr = candle_atr * 8.66`, `session_progress = candle_in_session / 74.0`, `create_labels(forward_periods=5)` all remain numerically valid because §4.1's adapter preserves the 5-minute-equivalent bar spacing every one of these constants assumes. This is the entire point of the resampling design — it converts a large, risky, many-file change into a zero-file change for the model math itself.

### 4.6 — Display/research/backtest consumers (mechanical, lower priority)

For `research_engine._load_price_history`, `backtester._load_candles`, `daily_summary._get_last_day_candle_stats`, `db_cli.py` stats/export, `list_active_symbols.py`: same pattern as §4.3 — swap the raw `FROM candles` SQL (or `Candle` ORM query) for a call to `CandleDatabase.get_fyers_candles_as_5min()` or a direct `fyers_candles WHERE resolution='D'` query where the consumer wants genuinely daily bars (research_engine and backtester both currently read undifferentiated `candles` rows and would arguably be *more correct* reading explicit daily data — this is a judgment call for you, not decided here). None of these have resolution-dependent label/feature math, so no adapter is needed — a direct table+column swap suffices. Not diffed individually here since each is a 3-5 line mechanical change of the same shape as §4.3; happy to produce them if you want this section expanded before implementation.

### 4.7 — Writers (W1-W10)

**No changes proposed.** `fyers_candles` is already kept current by the existing `fyers_historical_backfill.py` pipeline (built earlier this session, triggered on Watchlist-add). The `candles`-table writers keep running exactly as they do today — per the absolute rule, `candles` stays intact, and per "don't fix unrelated bugs," the dict/list bug in W2 (§2a) is flagged but not fixed as part of this migration.

---

## 5. Database / index changes

**None required.** The independent review re-ran `EXPLAIN ANALYZE` on the exact query shape §4.1's adapter would issue (`symbol + resolution + ts range`) and confirmed it uses `idx_fyers_candles_lookup` via Index Scan Backward with partition pruning (1.7ms, only 3 of 32 partitions touched) — no new index is needed. This is an audit finding, not a proposal; no index was created or modified.

---

## 6. Trading impact — explicit

| Path | Trigger | Gate before real order | What changes |
|---|---|---|---|
| Cash equity (`bot.auto_trade()`) | `scheduler._task_cash_auto_trade`, 5s interval | `_portfolio_reviewed` flag — **but auto-bypassed in paper mode** (`scheduler.py:826-828`, confirmed exact code by independent review); real human gate only in live mode | ML signal (§4.2) and context signal (§4.3) both change data source |
| F&O (`fno_trader.auto_trade_fno()`) | `scheduler._task_fno_auto_trade`, 5s interval, **defaults enabled** (`fno_auto_trade_enabled` defaults `"true"`) | **No human-review gate exists at all** in `fno_trader.py` (confirmed zero references, independent review) — only automatic thresholds (capital, position count, confidence, liquidity) | Signal source changes (§4.4); **blocked on NIFTY/BANKNIFTY/FINNIFTY backfill** |
| Daily XGB retrain (`scheduler._task_retrain_xgb_daily`) | Daily, unconditional | None — new model swaps in with zero validation gate (`fno_backtester.py:452-453`) | Training data source changes; because §4.5 needs no constant changes, label calibration is preserved — this is the whole reason the resampling design matters here specifically |

**The single highest-risk mechanical fact in this entire investigation:** the F&O daily retrain has no human gate and no validation step before a freshly retrained model starts placing real orders. This isn't something this migration creates — it's the existing design — but it's why §4.4/§4.5's "preserve the constants exactly" approach was chosen over any alternative that would require re-validating model calibration.

---

## 7. Things that must remain untouched

- **`candles`** — no rows deleted, no schema change, no writer disabled. Confirmed nothing in §4 touches a writer.
- **`fyers_candles`** and its 32 yearly partitions — read-only in every proposed diff.
- **`stock_prices`, `intraday_candles`** — out of scope, unmentioned in any diff.
- The already-completed dashboard migration (`/api/prices`, `/api/watchlist`, `/api/watchlist/<symbol>/analysis`, `sync-holdings`, `add_to_watchlist`'s FYERS backfill call) — done in an earlier pass this session, not touched here.
- `fyers_historical_backfill.py`, `build_master_ticker_table.py`, `master_ticker_table` — the existing FYERS infrastructure this plan builds on top of, unmodified.
- Groww order-execution code (`groww.place_order`, `bot.place_buy`/`place_sell`, `fno_trader.place_fno_buy`/`place_fno_sell`) — no diff touches these; only the *data feeding the decision* changes, never the execution mechanism.
- Dead code (`collect_index_candles.py`, `daily_summary._get_watchlist_predictions`, `retrain_xgb.py`, `sanity_check.py`) — confirmed unreachable, left exactly as broken/dead as they already are, per "don't fix unrelated bugs."
- The pre-existing `scheduler.py` dict/list bug (§2a) and `_task_aggregate_candles_to_daily`'s `MIN(open)` bug — flagged, not fixed, since neither is caused by or required to be fixed for this migration.

---

## 8. Independent review of this plan — results

**Revised.** The paragraph-form summary originally here was my own inline self-review, written by the same pass that wrote the diff. Per instruction, that was replaced with five genuinely independent subagents, each with no visibility into the others' output, each instructed to re-derive evidence from the live repo/database rather than trust this document's own claims. Two of them found real, previously-unflagged defects. This section reports what they actually found, not a rubber stamp.

**Reviewer 1 (diff corresponds to real code):** 3 of 4 hunks confirmed byte-for-byte accurate. **1 discrepancy found:** the fno_backtester.py hunk's final context line was written as `logger.debug(f"Loaded {len(candles)} candles for {symbol} (fyers_candles)")`, but that string doesn't exist in the current file — the real line 219 reads `"(historical + fresh intraday)"`. The diff needs an explicit `+`/`-` pair there, not a bare context line. Cosmetic, but exactly the kind of thing that would fail to apply cleanly if someone tried to patch from this document literally.

**Reviewer 2 (queries against real schema/indexes):** Schema, sample data, and index usage all confirmed correct with live query output. Two substantive findings from actually *running* the resample logic against real data (not just reading it):
- The `offset="9h15min"` parameter in the `resample()` call is **dead code** — it does nothing. `pd.read_sql` returns `ts` as UTC-tagged (not IST as this document originally claimed — see Reviewer 3's finding below, which is the same root cause), so `origin="start_day"` anchors at UTC midnight, not IST midnight. The buckets still land correctly on the 09:15 IST grid, but only because India's UTC+5:30 offset happens to be an exact multiple of 5 minutes — a numerical coincidence, not deliberate timezone handling. Manual spot-checks of 3 resampled bars against hand-computed OHLCV from raw rows matched exactly, so the *output* is correct today, but the mechanism is accidental.
- The tier-overlap "which resolution wins" question I raised in §4.1 doesn't fire in practice — checked all 63 symbols, the `'1'`→`'5S'` cutover is a clean, identical global boundary (2026-07-10 15:29 → 2026-07-13 09:15) with zero overlap anywhere. Real but dormant risk, not an active bug; worth a defensive one-line fix before implementation regardless.
- **New, unprompted finding:** §4.4's `get_fyers_candles_as_5min(symbol, days=None)` call (used for the F&O training/live-signal path) has no date bound, so it resamples RELIANCE's full 834K-row 1-minute history in pandas on every call. Given `get_xgb_signal()` is on the 5-second auto-trade hot path, this is an unaddressed performance regression, not just a correctness question.

**Reviewer 3 (trading paths):** Order-placement code itself confirmed untouched, traced hop-by-hop to `groww.place_order()` on both the cash and F&O sides. But **found the two most serious issues in the entire review:**
1. **Timezone bug (high severity).** Empirically confirmed — not hypothesized — that `pd.read_sql` against `fyers_candles.ts` (TIMESTAMPTZ) returns a UTC-tagged `datetime` column. `predictor.py`'s `time_of_day`/`is_opening`/`is_closing` features (lines 292-298) assume naive-IST wall-clock hours, exactly what the *old* `candles.timestamp` (naive, but IST) provided. Post-migration, real 09:15 IST market open reads as UTC hour 3, so `time_of_day` clips to 0 for nearly the entire session, `is_opening` fires almost all day, and `is_closing` never fires — silent, not an error, feeding wrong values into both live inference and the next model retrain. This directly contradicts §4.5's "no downstream constant needs to change" claim, and contradicts my own §8 (now superseded) claim that the tz-aware column has "confirmed IST semantics" downstream — it does, in Postgres; it does not once read into pandas via this exact call pattern, which apparently nobody had actually executed before this reviewer did.
2. **Freshness bug (high severity).** No scheduled task writes `fyers_candles` intraday — confirmed by grepping every `_register()` call in `scheduler.py`; only the Watchlist-add flow and a manual backfill script populate it. §4.2 removes `sync_candles_from_api()` (the thing that refreshed `candles` live on every call) without adding anything to keep `fyers_candles` current. Since the new source will always return *some* non-empty (but stale) data, `fetch_historical()` will never fall through to its live-API safety net — it will silently serve last-backfill data as if it were "today's" data, on both the cash and F&O paths, all day.
Point 3 (positional-indexing/gap risk in `fno_backtester`) was checked and did **not** materialize — measured gap patterns in the new source are no worse than the old, across 10 symbols including illiquid names.

**Reviewer 4 (no data deleted):** Confirmed clean — zero destructive statements, `insert_candles()` is insert-only (never updates/deletes), the full caller list of `get_candles()` was re-derived independently (5 real call sites found repo-wide; only the 2 in `bot.py` are touched, matching the plan). One non-blocking observation: removing `sync_candles_from_api()` also removes a freshness top-up that ~8 other call sites of `fetch_historical()` (`paper_trader.py`, `live_trade_executor.py`, `simulate_profit.py`, `threshold_analysis.py`, plus internal `bot.py` callers) incidentally relied on for keeping the *legacy* `candles` table fresh — not data loss, but a real staleness side-effect on a table other, later-phase consumers (§4.6) still read.

**Reviewer 5 (no unrelated changes):** Confirmed no renames, no reformatting, all four pre-existing bugs (§2a, the `MIN(open)` bug, etc.) correctly left untouched, no overlap with the already-migrated dashboard endpoints. The shared-helper abstraction was judged genuinely necessary (not premature) after independently reading all three call sites' real code. Two things flagged: (a) §4.4's promise to also update the `fno_backtester.py:4` module docstring has no actual diff hunk backing it — the document says it'll happen but doesn't show it, so it isn't really covered by "only these six locations change"; (b) the `sync_candles_from_api()` removal in §4.2, while reasonable, is a genuine behavior change *bundled into* the table-swap hunk rather than strictly required by it — flagged for explicit sign-off rather than folded silently into "repointing the read."

### What this means
Three of five reviewers found something a plain "looks fine" pass would have missed. The two from Reviewer 3 are real bugs that must be fixed before this diff should be implemented as-is — not stylistic nitpicks. Given this, and given the question you asked mid-review about whether resampling to 5-minute bars is even the right call in the first place, see §9 below before any of this gets implemented.

---

## 9. Design fork: resample to 5-minute, or feed 1-minute data natively?

You asked why this plan resamples everything to synthetic 5-minute bars instead of just feeding FYERS's native 1-minute data straight to the consumers. Direct answer: **both are legitimate, and I picked the one that avoids retraining, but that's a real tradeoff you should decide, not one I should make silently.**

**Why §4.1 resamples to 5-minute:**
Every trading-connected consumer has a hardcoded constant that means something specific *because* it was calibrated against 5-minute bars: `predictor.py`'s `session_progress = candle_in_session/74.0` (74 ≈ 75 bars/session), `create_labels(forward_periods=5)` (a 25-minute-ahead label), `market_context.py`'s `days*75`, `fno_backtester.py`'s `lookahead=525` (7 days × 75) and `daily_atr = candle_atr * 8.66` (√75). More importantly, **the two live models — `predictor.PricePredictor` for cash and the XGBoost long/short pair for F&O — were *trained* on data shaped this way.** A model's learned decision boundary encodes the statistical properties (noise, autocorrelation, typical swing size) of whatever bar spacing it saw during training. Resampling to 5-minute keeps feeding both models data that looks statistically like what they were trained on, so — modulo the two real bugs Reviewer 3 found — the existing models stay usable without retraining.

**What feeding native 1-minute data instead would actually require:**
- Update the same 5-6 constants, but to *different* values, not skip them — 74.0 → ~374.0, `days*75` → `days*375`, `lookahead=525` → ~2625, `8.66` (√75) → ~19.36 (√375). This is not fewer changes, it's the same set of files with different numbers.
- **Retrain both live models from scratch on 1-minute-cadence data, then validate the retrained models against the old ones' historical performance before trusting either with real orders.** This is the part that makes this the bigger decision: a model trained on 5-minute bars and one trained on 1-minute bars are not directly comparable — 1-minute data is noisier per-bar, has different autocorrelation, and a 25-bar-ahead label at 1-minute spacing (25 minutes) has different economics than a 5-bar-ahead label at 5-minute spacing even though both nominally mean "25 minutes." The F&O daily retrain already has **zero validation gate** before a new model goes live (§6) — swapping the entire input cadence makes that gate's absence far more consequential, right when you'd most want one.

**What resampling costs you, honestly, per what the reviewers just found:**
- A real timezone bug (Reviewer 3) — fixable, one `.dt.tz_convert()` call, but it was missed until an independent check actually ran the code.
- A real freshness gap (Reviewer 3) — `fyers_candles` isn't kept live intraday yet; either restore a lightweight sync call or build one for FYERS before removing the Groww one.
- Genuinely finer information is thrown away — a 1-minute bar has real information a 5-minute aggregate smooths over; if you ever want to *improve* the models rather than just port them, native 1-minute is the better long-term substrate.
- The resample step itself is ~35 lines of correctness-sensitive code (tier-stitching, bucket-anchoring) that didn't need to exist before.

**My honest recommendation:** resample-to-5-minute for this migration specifically, because it separates two decisions that are safer made one at a time — "which table backs the read" vs "should the models be retrained on finer data" — and the second one deserves its own deliberate backtest-and-compare pass, not something implicit in a data-source swap. But this is a real fork with real money downstream, not a technical detail, so it's your call. If you'd rather go straight to native 1-minute and treat the retrain as part of this same effort, say so and I'll rescope §4 accordingly — it changes which files need diffs (predictor.py and fno_backtester.py's constants, plus a retrain-and-validate step) but not the overall shape of the plan.

---

## 10. Unresolved issues — for you to decide before implementation

0. **§9's resample-vs-native-1-minute fork** — decide this first; it determines the actual shape of §4.
0a. **Two real bugs the independent reviewers found in §4.1, must be fixed before implementation regardless of §9's outcome:** the UTC-vs-IST timezone mismatch when `fyers_candles.ts` is read into pandas (Reviewer 3), and the lack of any intraday-freshness writer for `fyers_candles` now that `sync_candles_from_api()` would be removed (Reviewer 3). Also the fno_backtester.py diff's inaccurate context line (Reviewer 1) and the unbounded `days=None` resample cost on the F&O hot path (Reviewer 2).
1. **NIFTY/BANKNIFTY/FINNIFTY backfill** — must happen before §4.4 ships. This is a `fyers_historical_backfill.py` run against three new symbols, not a code change; want me to check whether `master_ticker_table` even has FYERS mappings resolved for these three (they're indices, not equities — the master table build only handled the 3 indices it knew about, and I have not verified NIFTY/BANKNIFTY/FINNIFTY are among them) before scoping that separately?
2. **ABB / ADANIGREEN / TATAMOTORS backfill** — same mechanism, lower urgency (cash side only, not hardcoded into the auto-trade universe like the F&O indices are).
3. **The paper-mode auto-review-bypass** (`scheduler.py:826-828`) — flagged by the trading-trace subagent as worth asking you about directly: is it intentional that paper-mode cash auto-trade skips the human portfolio-review step that live mode requires? Unrelated to this migration but surfaced during the trace.
4. **§4.6's scope** — do you want the display/research/backtest consumers included in the first implementation pass, or deferred? They're lower-risk but were not individually diffed above to keep this document's core (the trading-path changes) from being buried.
5. **The `scheduler.py` dict/list bug (§2a)** — not part of this migration, but you may want it investigated/fixed separately given it potentially means the `candles` table's live collector has been a no-op.

**Per Phase 9: stopping here. No code has been changed. Awaiting your review.**
