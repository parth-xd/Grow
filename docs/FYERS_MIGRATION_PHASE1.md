# Phase 1: Groww → FYERS Market-Data Migration Audit

**Status:** Phase 1 stop condition reached. Groww's execution path, the database schema, and the dashboard are all untouched. No orders were placed. No historical backfill was run. Waiting for approval before Phase 2.
**Date:** 2026-08-15

---

## Evidence labels

Every claim below is tagged. Read these as load-bearing, not decorative:

- **[DOCUMENTATION]** — FYERS's own API reference PDF (168 pages, read cover-to-cover in an earlier phase of this session; the Authentication section was re-read this phase to confirm exact field names before writing real auth code).
- **[CODE]** — read directly from this repo's `.py` files.
- **[DATABASE]** — read directly from `grow_trading_bot` via `psql`/`psycopg2`, read-only.
- **[ACTUAL API TEST]** — a real HTTP call made this session against `api-t1.fyers.in` with a live access token. No orders were placed by any test.
- **[INFERENCE]** — a conclusion drawn from the above, not a direct quote/observation/response.
- **[UNKNOWN — REQUIRES TESTING]** — explicitly not resolved. Not filled with a guess.

Where FYERS's documentation contradicted itself or left something ambiguous, both statements are shown rather than one being silently picked (Rule 9).

---

## A. Complete Groww data map

Full detail (file:line for every call site, every scheduler task, every reachability chain) is in the standalone audit output; condensed here to what's decision-relevant. **[CODE]**, audited 2026-08-15.

### A.1 Market data — capabilities actually used

| Groww SDK method | Purpose | Where | Frequency |
|---|---|---|---|
| `get_historical_candle_data` | Candles at 5min/1hr/daily/weekly(via 10080min) | `bot.py` (sync + fallback), `scheduler.py` (5-min collector), `fetch_full_history.py`, `price_fetcher.py`, `market_context.py`, `paper_trader.py`, `trailing_stop.py`, `fno_trader.py`, `app.py` (7 route call sites) | Continuous — this is the single most fanned-out Groww call in the app |
| `get_ltp` | Last traded price | `bot.py:317`, `fno_trader.py:1770` | Every prediction, every trade, every trailing-stop check, `_task_record_pnl` (5s), `_task_auto_close_trades` (5s) |
| `get_quote` | Full quote (ohlc, day-change, 52w hi/lo, circuits) | `bot.py:328`, `fundamental_analysis.py`, `fii_tracker.py`, `fno_trader.py` (dashboard + technicals + global indices) | On-demand + `_task_global_indices` (900s), `_task_deep_analysis` (1800s) |
| `get_option_chain` | Per-strike CE/PE with **Greeks + OI natively** | `fno_trader.py:398` | `/api/fno/option-chain`, `find_affordable_options`, auto-trade F&O selection |
| `get_expiries` | F&O expiry list | `fno_trader.py:377` | Dashboard, auto-trade F&O step 6 |
| `get_all_instruments` | Instrument master / company-name search | `tijori_collector.py`, `app.py` search routes | On-demand, 1h TTL cache (`tijori`) / process-lifetime cache (search, lost on restart) |

**Not used anywhere:** market depth. Groww's SDK may or may not offer a depth endpoint — irrelevant here because no code path calls one, so it's out of scope for a "don't lose functionality" migration.

### A.2 Broker/trading data (execution — explicitly out of scope this phase, staying on Groww)

`place_order`, GTT smart orders, `get_positions_for_user`, `get_holdings_for_user`, `get_order_list`, `get_available_margin_details`, `get_user_profile` (auth check), `GrowwAPI.get_access_token` (daily auto-refresh). Full inventory in the standalone audit; not reproduced here since it's explicitly not migrating.

### A.3 Gap/backfill behavior — the actual, tested-by-reading-the-code answer

**Scenario: DB's latest candle is Jan 1, today is Aug 15.**

- **Edge gap: detected.** `bot.sync_candles_from_api` computes `gap_seconds = now - latest_ts` and proceeds if `> 86400`.
- **Not chunked.** The entire 228-day span is requested in **one** `get_historical_candle_data` call at whatever interval was passed — no awareness of Groww's own documented per-interval max-days (`fetch_full_history.py`'s own comment says 5-min tops out at 15 days/request).
- **No retry.** Exception → logged, returns 0.
- **No interior-gap detection at all.** The only signal used is `MAX(timestamp)`. A hole in the *middle* of existing data (present Jan 1–10, missing Jan 11–31, present Feb 1 onward) is invisible to this path.
- **`CandleDatabase.get_missing_dates()` exists, models exactly this, and is never called anywhere** — confirmed by repo-wide grep. Dead code.
- **The one script that does this correctly** (`fetch_full_history.py`: per-interval chunking, dedup, `time.sleep(0.25)` rate limit) is a **manual CLI tool, not wired into the scheduler**, and has `now = datetime(2026, 4, 1)` hard-coded — as of today it would silently stop 4.5 months short of present.

**[INFERENCE]:** whatever backfill tooling gets built for FYERS should not copy `bot.sync_candles_from_api`'s pattern (single unchunked call, no retry, no interior-gap awareness) — it should generalize `fetch_full_history.py`'s pattern instead (per-resolution chunking + dedup + rate limit), fixed to not hard-code "now."

### A.4 Bugs found during this audit, unrelated to the migration but worth knowing

- `/api/intraday/enter-paper`, `/close-paper`, `/auto-trade-run-paper` call `fno_trader._groww_api` and `fno_trader.find_best_opportunity` — **neither attribute/function exists** (real names: `_get_groww()`, `_select_best_opportunity()`). Every call to these three routes raises `AttributeError`, silently caught, always returns an error response. **[CODE]**
- `collect_index_candles.py` does `from groww_api import get_historical_candles` — no such module exists (`growwapi` is the real one). Always fails at import. Nothing else calls it. **[CODE]**
- `IntradayCandle.interval == "1min"` filter in `bot.fetch_intraday_candles_for_today()` never matches — every writer in the codebase writes `"5min"` or `"60min"`. This silently disables an "enhance prediction with fresh intraday candles" code path, which falls back to the normal path with no error. **[CODE]**
- `stock_prices` is fed by three uncoordinated sources with no `source` column: Groww LTP (scheduler Phase 1), yfinance (scheduler Phase 2 backfill), and a dormant script (`fetch_google_prices.py`) whose `__main__` block unconditionally `DELETE`s the *entire* table before repopulating just 3 symbols from Yahoo Finance. Not currently scheduled, but live and runnable. **[CODE]**

---

## B. Complete FYERS data map (market-data relevant)

Full detail already delivered in `docs/FYERS_VS_GROWW_MARKET_DATA.md` from the prior research phase; summarized and where relevant **re-confirmed live this session**:

- **History** (`GET /data/history`): resolutions `5S/10S/15S/30S/45S`, `1..240` (min), `D`/`1D`, `1W`, `1M`. Minute data from **2017-07-03** [DOCUMENTATION, confirmed **[ACTUAL API TEST]** this session — see §H]. Seconds data: rolling **30-trading-day window only** [DOCUMENTATION] — this means seconds data is structurally not backfillable at all, only collectible going forward.
- **Quotes** (`GET /data/quotes`): up to 50 symbols/call [DOCUMENTATION]. Response shape **confirmed [ACTUAL API TEST]** this session — see §H.
- **Market Depth** (`GET /data/depth`): 5-level, 1 symbol/call [DOCUMENTATION]. Not tested this session (no Groww call site needs it, per A.1 — deprioritized).
- **Option Chain** (`GET /data/options-chain-v3`): Greeks + OI natively via `greeks=1` [DOCUMENTATION]. Not re-tested this session (Groww's equivalent already confirmed working with Greeks in `fno_trader.py`; parity is documented, live-testing FYERS's version is a Phase 2 item if F&O migrates).
- **WebSocket**: `SymbolUpdate`/`DepthUpdate`/Lite modes, 5,000-symbol subscription cap, General/Order socket, and a full Tick-by-Tick protobuf feed (NFO + NSE equity, 50-level depth, 3 connections/app/user, 5 symbols/connection). Not exercised this session — Phase 1 was REST-only per the stop condition.
- **Rate limits**: Standard 10/sec, 200/min, 100,000/day; Prime 10/sec, 600/min, 200,000/day [DOCUMENTATION]. Not stress-tested this session (would violate the "small tests only" constraint).
- **Auth**: OAuth-style authcode exchange, refresh token needs the user's PIN on every renewal (no unattended daily refresh like Groww has) [DOCUMENTATION, confirmed **[ACTUAL API TEST]** this session — see §G].

---

## C. Groww → FYERS capability mapping

| Groww capability | FYERS equivalent | Match | Notes |
|---|---|---|---|
| `get_historical_candle_data` (5min/1hr/daily/weekly) | `/data/history` | **BETTER** | FYERS documents exact retention (2017-07-03 floor, stated in writing) vs. Groww's boundary being discovered by trial-and-error in this repo's own code comments (which disagree with each other — see the earlier session's report). FYERS also natively supports seconds resolution and true weekly/monthly candles; Groww synthesizes weekly via a 10080-minute trick. |
| `get_ltp` | `/data/quotes` (`lp` field) | **FULL MATCH** | Confirmed field-for-field this session (§H). |
| `get_quote` | `/data/quotes` | **PARTIAL MATCH** | Field names differ (`ch`/`chp`/`open_price` etc. vs Groww's shape) — this is a **DIFFERENT** format carrying similar information, not a drop-in swap. Any caller reading Groww's quote shape needs a translation layer, not just a provider swap. |
| `get_option_chain` (Greeks+OI native) | `/data/options-chain-v3` (`greeks=1`) | **FULL MATCH** | Confirmed on both sides this session/prior session — Groww via live code (`fno_trader.py` reading `opt["greeks"]`), FYERS via documentation with a worked example. |
| `get_expiries` | `expiryData[]` inside the option-chain response | **DIFFERENT** | FYERS doesn't have a standalone expiries endpoint — it's embedded in the option-chain call. An adapter can still expose the same interface (see `fyers_market_data_provider.py`), it just makes one extra round trip look free. |
| `get_all_instruments` (search/lookup) | Bulk Symbol Master CSV/JSON download | **WORSE for search-by-query** | Groww's SDK returns a queryable instrument list in one call; FYERS only offers bulk per-exchange-segment file downloads with no search endpoint — building equivalent search means downloading and locally indexing the files yourself. |
| Market depth (unused on Groww side) | `/data/depth`, 5-level | **N/A** | Not a Groww capability in use, so not a migration requirement — flagged as a bonus FYERS capability if ever needed. |
| Tick-by-tick / order-flow (not available via Groww SDK in this codebase) | Full TBT WebSocket, 50-level depth, protobuf | **BETTER** (net-new) | Nothing to lose here; this is a capability Groww doesn't offer through any path this codebase uses. |
| Groww's fully unattended daily token refresh (key+secret only) | FYERS refresh requires the user's **PIN** on every call | **WORSE** | This is an operational regression, not a data-capability one — a fully automated FYERS pipeline needs a different renewal design than Groww's `token_refresher.py` pattern. See §G. |

---

## D. Missing capabilities

1. **Instrument search-by-query.** Groww's SDK does this in one call; FYERS requires downloading the Symbol Master and building your own index. **[DOCUMENTATION]** — not a blocker, but real added engineering work, and `market_data_provider.search_instruments()` is left `NotImplementedError`'d on the FYERS side for exactly this reason rather than faked.
2. **Unattended daily auth.** FYERS's refresh-token flow needs a human-entered PIN each time (per docs, confirmed field-for-field this session). Groww's `token_refresher.py` pattern (fully automatic key+secret → token) has no FYERS equivalent as documented. **[DOCUMENTATION + INFERENCE]** — this needs a design decision before any unattended FYERS data collection can run daily without a human present. See §G and §M.
3. **Everything F&O/order-execution-side stays on Groww by design** — not "missing," out of scope.

---

## E. Historical data matrix

| Resolution | FYERS supports? | Oldest date | Max/request | Rate limit | Volume | OI | Tested? |
|---|---|---|---|---|---|---|---|
| 5S–45S | Yes [DOC] | Rolling 30 trading days only [DOC] | Not separately documented beyond the 30-day window | Standard/Prime tiers apply | Yes | N/A (equity) | Not tested |
| 1m–240m | Yes [DOC] | **2017-07-03** [DOC, confirmed **[ACTUAL API TEST]**] | 100 days/request [DOC] | Standard/Prime tiers apply | Yes | Yes, via `oi_flag=1` (F&O) | **Tested — 1m, 5m [ACTUAL API TEST]** |
| D / 1D | Yes [DOC] | Not documented as a fixed floor separate from minute data; **tested working back to 2018 and 2017 (pre-floor) — see caveat below** | 366 days/request [DOC] | Standard/Prime tiers apply | Yes | N/A | **Tested [ACTUAL API TEST]** |
| 1W | Yes [DOC] | Not independently tested | 366 days/request [DOC] | — | Yes | N/A | Not tested |
| 1M | Yes [DOC] — added **27 Mar 2026** per FYERS's own changelog, i.e. a young feature | Not independently tested | 366 days/request [DOC] | — | Yes | N/A | Not tested |

**Caveat on the daily-resolution row:** my first test design was flawed — I requested **daily** candles for June 2017 (before the documented 2017-07-03 floor) expecting it to fail, and it returned 7 real candles. That is *not* a contradiction: the documented floor is stated specifically for *minute* resolutions, and nothing in the docs claims daily data shares that exact floor. I corrected the test by re-running at **5-minute** resolution instead (the resolution the floor actually applies to) — see §H for the corrected, decisive result.

---

## F. Live data matrix

| | FYERS REST | FYERS WebSocket | Tested this phase? |
|---|---|---|---|
| LTP | `/data/quotes` → `lp` | `SymbolUpdate` mode | REST: **yes [ACTUAL API TEST]**. WebSocket: no (out of Phase 1 scope) |
| Full quote | `/data/quotes` | `SymbolUpdate` mode (superset of REST fields — includes `bid_size`/`ask_size`/`last_traded_qty`/`last_traded_time`, which the REST quotes endpoint does not) | REST: yes. WebSocket: no |
| Market depth | `/data/depth`, 5-level | `DepthUpdate` mode, 5-level (matches REST) | Neither (unused on Groww side, deprioritized) |
| Tick-by-tick / 50-depth | N/A | Dedicated TBT protobuf feed, NFO+NSE-EQ only | No |
| Option chain / Greeks | `/data/options-chain-v3` | N/A (not a WebSocket capability) | No (documented + Groww-side parity already confirmed) |

---

## G. Authentication status

**Working. [ACTUAL API TEST].**

Built `fyers_auth.py` (isolated module, mirrors the existing `token_refresher.py`'s `.env`-update pattern) and `fyers_client.py` (raw REST wrapper, no order-placement methods exist in it by design). Auth flow, field names confirmed against the primary-source docs before writing any code (not from memory):

1. `GET /api/v3/generate-authcode?client_id=...&redirect_uri=...&response_type=code&state=...` — user logs into FYERS **in their own browser**; this code never sees or handles FYERS login credentials.
2. User is redirected to `FYER_Redirect_URL` (already present in `.env`, just under different casing than what was stated — `FYER_Redirect_URL`, not `FYER_REDIRECT_URL`/`FYERS_REDIRECT_URL`) with an `auth_code`.
3. `POST /api/v3/validate-authcode` with `{"grant_type":"authorization_code","appIdHash": SHA256(app_id:secret),"code": auth_code}` → `access_token` + `refresh_token`.
4. Verified live: `get_market_status()` call returned real, current exchange status data with `HTTP 200`.

**Credential handling note:** `.env` actually stores the FYERS credentials as `FYER_APP_ID`/`FYER_SECRET_ID` (no "S"), not `FYERS_APP_ID`/`FYERS_SECRET_ID` as originally stated — the auth module was built against what's actually there. Also: **a Bash command I ran mid-session accidentally printed the full Groww access token into tool output** (fixing a grep pattern that matched the whole `.env` line instead of just the variable name). That token is short-lived (auto-refreshes daily ~6 AM IST per `token_refresher.py`), but should be treated as exposed — the FYERS credentials were not affected, all FYERS-related `.env` reads in this session used a values-safe grep pattern.

**Unresolved, flagged rather than assumed:** FYERS's docs state "Refresh token will be discontinued from 1st April" with no year on that specific line. A separate, nearby SEBI-driven note on rate-limit changes does specify **April 1, 2026** — which, if the same date applies here, has already passed as of today (2026-08-15). **[UNKNOWN — REQUIRES TESTING]** whether `validate-refresh-token` still works at all; this session only exercised the initial authcode exchange, not the refresh flow, so it's untested. This directly affects whether unattended daily FYERS auth is even possible going forward — see §M.

---

## H. Actual test results

All calls below used a live access token obtained via the flow in §G. No orders were placed. All requests were small, bounded-range GETs.

### H.1 History endpoint

| Test | Resolution | Range | HTTP | `s` | Candles | First ts (epoch) | Last ts (epoch) |
|---|---|---|---|---|---|---|---|
| daily-recent-30d | D | 2026-07-16 → 2026-08-14 | 200 | ok | 22 | 1784160000 | 1786665600 |
| 5min-recent-5d | 5 | 2026-08-10 → 2026-08-14 | 200 | ok | 375 | 1786333500 | 1786701300 |
| 1min-recent-3d | 1 | 2026-08-12 → 2026-08-14 | 200 | ok | 1125 | 1786506300 | 1786701540 |
| daily-2018-window | D | 2018-01-01 → 2018-01-10 | 200 | ok | 8 | 1514764800 | 1515542400 |
| daily-pre-2017-07-03 (flawed test — daily, not minute; see §E caveat) | D | 2017-06-01 → 2017-06-10 | 200 | ok | 7 | 1496275200 | 1496966400 |
| **5min-before-2017-07-03 (corrected test)** | **5** | **2017-06-01 → 2017-06-10** | **200** | **no_data** | **0** | — | — |
| **5min-straddle-2017-07-03 (corrected test)** | **5** | **2017-06-28 → 2017-07-08** | **200** | **ok** | **375** | **1499053500** | **1499421300** |

Candle counts all match exact expected trading-day arithmetic (e.g. 375 = 5 trading days × 75 five-minute bars/day for NSE's 09:15–15:30 session), which is itself a form of correctness check on the data, not just presence/absence.

**The corrected pre/post-2017-07-03 test is decisive:** zero candles before the documented floor, and the *very first* candle in a window straddling it lands at epoch `1499053500` — which converts to **2026-05-25... correction: 2017-07-03 09:15:00 IST**, exactly market open, to the minute. The documented retention floor is real and sharply enforced, not approximate.

### H.2 Quotes endpoint

Response shape confirmed live for `NSE:RELIANCE-EQ`:
```json
{"d": [{"n": "NSE:RELIANCE-EQ", "v": {"ask":0,"bid":1310,"chp":-0.53,"ch":-7,
  "high_price":1317.5,"low_price":1301.5,"lp":1310,"open_price":1317,
  "prev_close_price":1317,"volume":10497358,"atp":1308.27, ...}, "s":"ok"}], "s":"ok"}
```
Matches the documented field list exactly; used to correct the initial (guessed) response-parsing code in `fyers_market_data_provider.py` before it shipped.

### H.3 Groww-vs-FYERS comparison (overlapping window, RELIANCE)

**This is the finding to read most carefully — the two providers do NOT match cleanly, and that's the honest result, not a bug in the comparison.**

**Daily, 2026-05-01 → 2026-05-15** (Groww data from `stock_prices` table [DATABASE], FYERS from the test above):

- Groww's `stock_prices` has entries for **2026-05-01, 05-02, 05-03** — all three with an identical close of 1430.8. FYERS returned **no candles for those dates at all**. 2026-05-02/03 are a weekend; 2026-05-01 is a market holiday. **[INFERENCE]:** this looks like a stale/carried-forward LTP being written into `stock_prices` for non-trading days by the scheduler's `update_watchlist_prices` task, not a real closing price — FYERS correctly has no data for non-trading days, Groww's stored data appears to have phantom entries for them. This is a data-quality issue in this app's own Groww ingestion, not something FYERS does wrong.
- For the 10 real trading days both sides have data for, **close prices differ by roughly ±0.5%** (e.g. 2026-05-14: Groww close 1368.6 vs FYERS 1361.8, a 0.5% difference) — small, plausibly just different feed-snapshot timing between brokers, not concerning on its own.
- **Volume differs by roughly 20–50×, consistently, in the same direction (Groww always higher).** Example: 2026-05-04, Groww 787,525,029 vs FYERS 24,035,700 — a 32.8× difference. **[UNKNOWN — REQUIRES TESTING]** why. Possible explanations, none confirmed: different volume units/definitions between providers, or (more likely given the DB audit) `stock_prices.volume` for this period may be a rollup from `candles`-table 5-minute bars rather than a direct daily-candle volume field from Groww's own history API, and that rollup could double-count or use a different convention. **Do not use volume figures interchangeably between the two providers without resolving this first** — any strategy logic reading Groww-sourced volume today would be reading a very different number than FYERS-sourced volume tomorrow.

**5-minute, 2026-05-25 → 2026-05-29** (Groww from `candles` table [DATABASE]):

- FYERS returned a complete set: 300 candles = 4 trading days × 75 bars/day, exactly as expected.
- Groww's stored data has only **226** candles for the same window — a real completeness gap, consistent with the Groww audit's independent finding that the scheduler's 5-minute collector has no chunking/retry/interior-gap detection (§A.3).
- Only **28 timestamps overlap** between the two datasets (198 timestamps exist only in Groww's set, 272 only in FYERS's). The 28 that do overlap are concentrated at the very start of the window (the first ~8 bars of 2026-05-25 morning), consistent with Groww's collection being more complete near the start of a run and gappier afterward.
- **For the 28 candles that do share a timestamp, close-price differences run up to 2.18%** — noticeably larger than the ~0.5% seen at daily resolution. **[UNKNOWN — REQUIRES TESTING]** whether this reflects real intraday microstructure differences between feeds or a data-quality issue on the Groww side; not enough evidence from 28 samples to conclude either way.

**Bottom line for §H.3:** do not assume FYERS and Groww candles are interchangeable for backtesting or live comparison purposes without resolving the volume-unit discrepancy and the intraday completeness/alignment gap first. This is exactly the "test them, don't assume" finding Rule 7 asked for.

---

## I. Database recommendation

Full DDL: [db/fyers_candles_schema.sql](../db/fyers_candles_schema.sql) — **written, not yet executed** against the live database, pending your review.

Key decisions and why:

- **New table (`fyers_candles`), not an extension of `candles`.** The DB audit found `candles` already silently mixes ≥3 resolutions with no discriminator column, has no unique-constraint gap for a third provider, and is 127× disk-bloated from never being vacuumed. Extending it would compound an existing problem rather than fix it.
- **Explicit `resolution`, `provider`, `source_type` columns** — never inferred from timestamp spacing (per your requirement 22) or left implicit.
- **`TIMESTAMPTZ`, not naive `TIMESTAMP`** — the existing `candles` table uses naive timestamps, which is exactly the kind of ambiguity your requirement 16 (timestamp normalization) flags as a risk. This is a deliberate improvement, not a stylistic choice.
- **A `CHECK` constraint enforcing `low ≤ open,close ≤ high`** — moves part of your requirement 26 (data integrity) into the schema itself rather than a separate script that has to be remembered and run.
- **Range-partitioned by month** on `ts` — driven mainly by 1-minute data at multi-year scale (~126M rows for ~150 symbols across the 2017–2026 span FYERS documents), not by seconds data. Seconds data is structurally capped by FYERS to a rolling 30-trading-day window (§E) — it cannot be backfilled at all, so it doesn't drive the partitioning decision the way it would if years of it were retainable.
- **No TimescaleDB.** At this symbol count and with seconds data structurally bounded, native partitioning plus two indexes covers the real access pattern (`symbol + resolution + ts range`). Revisit only if this table's actual growth outpaces that — not preemptively.

---

## J. Backfill plan (design only — not run this phase, per Rule 5)

1. **Minute resolutions (1–240 min):** chunk by 100 days/request (FYERS's documented max), walk back to 2017-07-03, per symbol. Generalize `fetch_full_history.py`'s pattern (chunking + in-memory dedup set + DB `ON CONFLICT DO NOTHING` + `time.sleep` rate limit) rather than `bot.sync_candles_from_api`'s pattern (§A.3) — the latter has no chunking or retry and would fail immediately against FYERS's 100-day cap for a multi-year request.
2. **Daily/weekly/monthly:** chunk by 366 days/request, same pattern.
3. **Seconds resolutions:** **do not attempt a historical backfill — there is nothing to backfill.** FYERS only ever has the trailing 30 trading days available. If seconds data matters, the only option is starting a forward-collecting process now and accepting that history before "today" doesn't exist.
4. **Checkpointing/resume:** persist `(symbol, resolution, last_successful_chunk_end)` somewhere durable (a small Postgres table, not a JSON file, given this app's existing JSON state files aren't written atomically — see the earlier session's cloud-migration research on this exact issue) so a crash mid-backfill resumes rather than restarts.
5. **Rate limits:** at Standard tier (10/sec, 200/min, 100,000/day), a full 2017-2026 minute-level backfill for ~75 symbols is roughly: 75 symbols × (9 years × 365 days ÷ 100 days/chunk) ≈ 75 × 33 ≈ **2,475 requests** for one minute-resolution — comfortably within a single day's 100,000-request budget even accounting for multiple resolutions and retries. **[INFERENCE]** based on documented limits, not load-tested.
6. **Re-download question, answered from documentation:** nothing in FYERS's rate-limit or history-endpoint docs imposes any additional "already downloaded this data" restriction beyond the standard per-second/minute/day request caps — **[DOCUMENTATION]**, the same 3-years-of-1-minute-data could be re-requested tomorrow with no special cooldown, as long as you stay within the daily request budget. Not separately load-tested this session.

---

## K. Live collection plan (design only)

```
FYERS WebSocket (SymbolUpdate / DepthUpdate)
        ↓
Live candle builder (accumulate ticks → 1-min bar on each minute boundary)
        ↓
fyers_candles (source_type='websocket', resolution='1')
```

Not built this phase (WebSocket work is out of Phase 1's stop condition). Flagging one design constraint the audit surfaced: this app currently runs its scheduler as a **daemon thread inside the single Flask process** (per the earlier cloud-migration research in this same session) — a persistent WebSocket connection has the same "must not silently die with the process" concern as that research already flagged for the trading scheduler. Whatever runs the FYERS WebSocket listener should get the same SIGTERM-handling treatment recommended there, not be bolted on as another daemon thread with no shutdown discipline.

---

## L. Storage estimate

**[INFERENCE]** — based on the DB audit's measured true average row width for the existing `candles` table (101.3 bytes/row) adjusted upward for `fyers_candles`'s extra columns (provider/source_type/resolution strings, open_interest) to **~150 bytes/row true data**, and a **~3× disk multiplier for a well-maintained (regularly vacuumed) table** — explicitly *not* the 127× bloat ratio found on the existing `candles` table, which is a maintenance failure, not something inherent to any schema. Universe assumed: 75 symbols (matches `candles`' current coverage), 250 trading days/year, 375-minute equity session.

| Resolution | Rows/year (75 symbols) | 1 year (disk) | 3 years | 5 years |
|---|---|---|---|---|
| Daily | 18,750 | ~8 MB | ~24 MB | ~40 MB |
| 15-min | 468,750 | ~210 MB | ~630 MB | ~1.05 GB |
| 5-min | 1,406,250 | ~630 MB | ~1.9 GB | ~3.15 GB |
| 1-min | 7,031,250 | ~3.15 GB | ~9.5 GB | ~15.75 GB |

**Seconds resolution is deliberately not in this table as a multi-year figure** — per §E/§J, FYERS cannot supply more than a rolling 30 trading days of it, so there is no "5 years of 1-second data" to estimate for a backfill. If the app instead *collects and permanently retains* seconds data going forward every day (a design choice, not something FYERS provides), the same math gives roughly **~190 GB/year** at 75-symbol scale — flagging this explicitly so it isn't accidentally budgeted for as if it were backfillable, and so a retention policy (e.g. keep 90 days, not forever) gets decided deliberately rather than by default.

---

## M. Risks

1. **Volume-unit discrepancy between Groww and FYERS is unresolved** (§H.3) — a 20–50× difference is too large to hand-wave; anything reading volume needs this resolved before trusting either source, let alone comparing them.
2. **5-minute data completeness gap on the Groww side** (226 vs. 300 expected candles, only 28 timestamps overlapping) means any backtest that used this app's own stored Groww 5-minute data has been working with gappier data than it may have assumed.
3. **FYERS refresh-token status is genuinely unknown** (§G) — if "discontinued from 1st April [2026]" applies here and that date has passed, unattended daily FYERS auth may already require a full interactive re-login every day, which is a materially different automation story than Groww's fully unattended refresh. This needs a direct test before any daily-unattended FYERS collection is built.
4. **No instrument-search equivalent on FYERS** (§D) — building one means downloading and indexing the Symbol Master files yourself; not a blocker, but real scope.
5. **Existing `candles` table's 127× bloat and never-vacuumed state** will make any future full-database backup/restore or migration step slower and larger than it needs to be — unrelated to FYERS specifically, but will be hit again the moment anyone needs to move or dump this database.
6. **Two currently-broken routes** (`/api/intraday/*-paper`, three of them) and one broken standalone script (`collect_index_candles.py`) exist independent of this migration — worth a decision on whether to fix or formally retire them before building FYERS equivalents for functionality that may already be dead.
7. **`.env` casing mismatch risk**: the working variable names are `FYER_APP_ID`, `FYER_SECRET_ID`, `FYER_Redirect_URL` (inconsistent casing, no trailing "S") — any future code (including code written by an LLM from a spec that assumes `FYERS_*` naming) needs to match what's actually there, not what seems like the "natural" name.
8. **A Groww access token was accidentally exposed in this session's tool output** (§G) — short-lived and auto-refreshing, but worth a conscious rotation rather than relying on the schedule.

---

## Files added this phase (all additive, nothing existing modified)

- [fyers_auth.py](../fyers_auth.py) — isolated FYERS auth module
- [fyers_client.py](../fyers_client.py) — raw FYERS REST wrapper (read-only endpoints only)
- [market_data_provider.py](../market_data_provider.py) — provider-neutral interface
- [groww_market_data_provider.py](../groww_market_data_provider.py) — adapter over existing Groww call sites (nothing rewired to use it yet)
- [fyers_market_data_provider.py](../fyers_market_data_provider.py) — adapter over `fyers_client.py`
- [db/fyers_candles_schema.sql](../db/fyers_candles_schema.sql) — proposed schema, **not yet executed**
- `.env` — unchanged by this session except the two token fields FYERS's own login flow writes (`FYER_ACCESS_TOKEN`, `FYER_REFRESH_TOKEN`); nothing else added or renamed

**Nothing in `app.py`, `bot.py`, `fno_trader.py`, or any scheduler task was modified.** Groww remains the live data source and the live execution broker for everything. No table was dropped, altered, or renamed. No order was placed.

---

## Stop condition check (Rule 30)

1. Complete Groww audit — done (§A).
2. Complete FYERS audit — done (§B), reusing the earlier session's exhaustive documentation read plus this session's live confirmation.
3. Authentication working — done (§G), with one flagged unknown (refresh-token status).
4. Small FYERS historical tests working — done (§H.1).
5. Groww-vs-FYERS comparison for overlapping data — done (§H.3), and it surfaced real, unresolved discrepancies rather than a clean match.
6. Recommended database architecture produced — done (§I), not executed.

**Waiting for approval before Phase 2.** Open items I'd want a decision on before continuing: whether to resolve the volume-discrepancy question before building anything further on top of either provider's volume figures, whether to test the FYERS refresh-token flow (needs your PIN, so needs you present), and whether the `fyers_candles` DDL should actually be run now or stay a proposal until Phase 2.
