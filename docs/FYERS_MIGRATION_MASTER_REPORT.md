# FYERS Market-Data Migration — Master Investigation Report

**Date:** 2026-08-15
**Status:** Investigation and architecture only. Stop conditions respected — no backfill run, no production schema created, no dashboard change, no Groww code removed, no orders placed, no existing table modified.

---

## Evidence labels

| Label | Meaning |
|---|---|
| `[OFFICIAL FYERS DOCUMENTATION]` | FYERS's own 168-page API reference (read in full earlier in this session) |
| `[ACTUAL FYERS API TEST]` | A real HTTP call made today against `api-t1.fyers.in` with a live token |
| `[OUR CODE]` | Read directly from this repo |
| `[OUR DATABASE]` | Read directly from `grow_trading_bot`, read-only |
| `[SDK SOURCE]` | Read from `fyers-apiv3` 3.1.16 source (downloaded to /tmp for inspection; **not installed**) |
| `[INFERENCE]` | Reasoned conclusion, not directly observed |
| `[UNVERIFIED]` | Not established — explicitly not guessed |

Roughly **500 read-only API requests** were made today, paced at ≥0.45s (~133/min against a 200/min limit). No order endpoint was ever called.

> ### ⚠️ THIS REPORT HAS NOT BEEN ADVERSARIALLY REVIEWED
>
> An independent adversarial reviewer was launched to attack every empirical claim below — re-testing boundaries on symbols I didn't use, checking for off-by-one errors in trading-day counts, NSE holidays misread as retention floors, and inferences stated as fact. **It terminated early on a session limit before producing any findings.**
>
> Everything here therefore carries **only my own verification**. The claims most deserving independent re-testing before you act on them:
> - The **~25-vs-30 trading-day** seconds window (§8) — I counted weekdays without adjusting for NSE holidays, so my "~26 trading days" could be off.
> - The **1997 daily floor** (§8) — tested on RELIANCE only; could be confounded by that symbol's own listing history rather than being a platform-wide floor.
> - The **500-symbol quotes result** (§10) — I passed a repeated 10-symbol list cycled up to 500, which may have masked deduplication. Not tested with 500 *distinct* symbols.
> - **OI at intraday resolutions** (§11) — I verified `oi_flag` only at daily resolution.
> - Every `[SDK SOURCE]` claim in §13 — read from source code, **never executed against a live socket**.

---

## 1. Executive Summary

**FYERS can give you substantially more than Groww, and the ceiling is higher than its own documentation advertises.**

The three headline facts, all `[ACTUAL FYERS API TEST]`:

1. **1-minute equity data goes back to exactly 2017-07-03** — nine years, verified to the minute across four different symbols.
2. **Daily data goes back to ~mid-1997** — roughly 29 years, which is *not documented anywhere* in FYERS's reference.
3. **Seconds data exists but only for a ~26-trading-day rolling window** and **1-second is not supported at all** (the finest available is 5-second). Seconds history is therefore *structurally un-backfillable* — it can only be collected forward.

The single most important architectural consequence: **there is no one resolution to fetch.** The optimal strategy is a three-tier ladder (§16), because each tier has a genuinely different retention boundary.

**The biggest risk is not data availability — it's authentication.** Access tokens expire at a **fixed 06:00 IST daily cutoff**, and renewal requires the user's PIN. Unattended daily collection is therefore **not possible without a design decision about PIN handling** (§4–5). This is the one thing that could block the whole project, and it needs your input.

**The second biggest risk is volume semantics on the live feed.** The WebSocket delivers *cumulative* day volume via a *server-conflated snapshot* (not a per-trade stream), so per-candle volume must be computed by **differencing**, and naive summing of `last_traded_qty` will silently undercount (§13–14).

---

## 2. Existing Groww Data Pipeline

`[OUR CODE]`, full audit. Condensed — every call site, caller chain, and scheduler task was traced.

| Groww method | Purpose | Key call sites | Trigger |
|---|---|---|---|
| `get_historical_candle_data` | Candles (5min/1hr/daily/weekly-via-10080min) | `bot.py:181,258,285`, `scheduler.py:342`, `fetch_full_history.py:126`, `price_fetcher.py:59`, `market_context.py:110`, `paper_trader.py:313`, `trailing_stop.py:65`, `fno_trader.py:566`, `app.py` ×7 | Continuous; most fanned-out call in the app |
| `get_ltp` | Last traded price | `bot.py:317`, `fno_trader.py:1770` | Every prediction/trade/trailing-stop check; `record_pnl` (5s); `auto_close_trades` (5s) |
| `get_quote` | Full quote | `bot.py:328`, `fundamental_analysis.py:316,505`, `fii_tracker.py:28,80`, `fno_trader.py:746,1907,1964` | On-demand + `global_indices` (900s), `deep_analysis` (1800s) |
| `get_option_chain` | Chain **with Greeks + OI natively** | `fno_trader.py:398` | Option-chain route, `find_affordable_options`, F&O auto-trade |
| `get_expiries` | Expiry list | `fno_trader.py:377` | Dashboard, F&O auto-trade |
| `get_all_instruments` | Instrument master / search | `tijori_collector.py:600`, `app.py:4709,4753` | 1h TTL cache / process-lifetime cache |

**Market depth is never called anywhere** — so it is not a migration requirement (though FYERS provides it).

**28 scheduler tasks** registered in `scheduler.py:1249-1300`; 12 touch Groww market data. Highest-frequency: `fno_auto_trade` (5s), `cash_auto_trade` (5s), `auto_close_trades` (5s), `record_pnl` (5s).

---

## 3. Existing Groww Database

`[OUR DATABASE]`, exact counts.

| Table | Rows | Span | True data | Disk | Bloat |
|---|---|---|---|---|---|
| `candles` | **391,091** | 2020-01-02 → 2026-05-29 | 38 MB | **4,815 MB** | **127×** |
| `stock_prices` | **108,464** | 2020-01-02 → 2026-08-12 | 9.46 MB | 142 MB | 15× |
| `intraday_candles` | **2,625** | 2026-04-02 → 2026-05-12 (7 days) | 304 KB | 776 KB | 2.6× |

Critical facts:

- **`candles` is ~95% of the entire 5,043 MB database** and is 127× larger than its actual content. `pg_stat_user_tables` shows `last_autovacuum = NULL` and `n_live_tup = 0` for every market-data table — **autovacuum has never run on them**, and `n_live_tup` is untrustworthy database-wide (use `COUNT(*)`).
- **`candles` has no resolution column** and silently mixes daily, 5-minute, and (for at least one verified symbol/day) 1-minute bars.

### 🔴 `stock_prices` is NOT a daily EOD table — correction to a premise I held earlier

`[OUR CODE]`. This table has **five independent writers producing four different bar types into the same `(symbol, date)` rows**, with no column distinguishing them:

| Writer | file:line | What it actually writes |
|---|---|---|
| `price_fetcher.store_prices_in_db` | `price_fetcher.py:59-65,129` | **WEEKLY** bars (`interval_in_minutes=10080`) stamped on the week-start date |
| `scheduler._task_update_watchlist_prices` Phase 1 | `scheduler.py:202-206` | **Live LTP snapshot** — `close` only, OHLV left NULL |
| `scheduler._task_update_watchlist_prices` Phase 2 | `scheduler.py:244-248` | **yfinance** daily close only, NULL OHLV — not Groww data at all |
| `scheduler._task_aggregate_candles_to_daily` | `scheduler.py:738-756` | Daily OHLCV aggregated from `candles` |
| `fetch_google_prices.store_prices_in_db` | `fetch_google_prices.py:106,140` | yfinance daily OHLCV, preceded by `DELETE FROM stock_prices` |

**The codebase contradicts itself about what this table holds:** `backtester.py:96` and `research_engine.py:100` call it *"weekly"*; `app.py:1997` and `bot.py:354` call it *"daily"*. **Any symbol added via `/api/watchlist/add` has weekly history; symbols only touched by the scheduler have daily.** There is no way to tell them apart from the data.

**This matters enormously for migration:** `bot.analyze_long_term_trend` (`bot.py:410-411`) reads `prices[-250:]` and labels it *"1-year support/resistance"* — true for daily bars, but **five years** for weekly-written symbols. That value feeds both live trade decisions and the dashboard's target prices.

- **`stock_prices` is also the de-facto universe registry** — `SELECT DISTINCT symbol FROM stock_prices` appears in **seven** places (`app.py:1244,1946,3165`, `scheduler.py:112,176`, `market_intelligence.py:835`, `tijori_collector.py:1012`). Moving price data without replacing this contract empties the watchlist, Tijori backfill list, deep-analysis symbol set, and data-health denominator at once.
- **`intraday_candles` has no `'1min'` rows from any live writer.** Both writers (`app.py:5371`, `app.py:5503`) pass `"5min"`/`"60min"`; the ORM default is `"1min"` (`db_manager.py:68`), so the 2,625 rows tagged `1min` are legacy. `bot.fetch_intraday_candles_for_today` filters on `interval == "1min"` (`bot.py:562`) — **that path is dead and silently falls through.**

---

## 4. FYERS Authentication

`[ACTUAL FYERS API TEST]` — the full flow was executed successfully today.

1. `GET /api/v3/generate-authcode` → user logs in **in their own browser** (this system never handles FYERS login credentials)
2. Redirect to `FYER_Redirect_URL` carrying `auth_code`
3. `POST /api/v3/validate-authcode` with `{grant_type:"authorization_code", appIdHash: SHA256("app_id:secret"), code}` → `access_token` + `refresh_token`
4. All subsequent calls: header `Authorization: {app_id}:{access_token}`

Implemented in [fyers_auth.py](../fyers_auth.py) and [fyers_client.py](../fyers_client.py). **Verified working** — `get_market_status()` returned live exchange status, HTTP 200.

`.env` variable names are `FYER_APP_ID`, `FYER_SECRET_ID`, `FYER_Redirect_URL` — **no trailing "S", inconsistent casing**. Code must match what is actually there.

**`[OFFICIAL FYERS DOCUMENTATION]`: Market Data is an independently-grantable permission template** (Basic / Transactions Info / Order Placement / Market Data). A data-only FYERS app that is *structurally incapable of placing orders* is a first-class supported configuration — strongly recommended, and it directly enforces the "FYERS = data, Groww/Zerodha = execution" separation at the credential level.

---

## 5. FYERS Token Persistence — **THE CRITICAL BLOCKER**

`[ACTUAL FYERS API TEST]` — JWT `exp`/`iat` claims decoded from the live tokens (token values themselves never printed):

| Token | Issued | Expires | Lifetime |
|---|---|---|---|
| Access | 2026-08-15 14:20:44 IST | **2026-08-16 06:00:00 IST** | 15.65 h |
| Refresh | 2026-08-15 14:20:44 IST | **2026-08-30 06:00:00 IST** | exactly 15 days |

**Access tokens expire at a fixed 06:00 IST daily cutoff, not 24 hours after issue.** A token minted at 23:00 IST would live ~7 hours; one minted at 07:00 IST lives ~23 hours. Any renewal scheduler must target the 06:00 IST boundary, not an interval.

**Refresh tokens are live.** FYERS's docs carry the line *"Refresh token will be discontinued from 1st April"* with **no year stated**; a nearby SEBI-related note says *April 1, 2026*, which has already passed. **A valid refresh token with a 15-day future expiry was issued to us today (2026-08-15)** — so whatever that line refers to, the mechanism is functioning now. `[INFERENCE]`: the note likely refers to a future April or to a different mechanism; it has demonstrably not taken effect.

**The blocker:** `[OFFICIAL FYERS DOCUMENTATION]` the refresh call requires `pin` — the user's FYERS PIN — on **every** renewal. `[SDK SOURCE]` the official SDK has **no token persistence and no auto-refresh whatsoever** (grep for `refresh`/`pickle`/`cache` in `fyersModel.py` → zero hits; nothing is written to disk).

**Conclusion — answering the required A/B/C/D:**

> **C — Manual login periodically required**, *unless* you accept storing the PIN.

Precisely:
- **Without a stored PIN:** interactive browser login **every single day** before 06:00 IST. Not viable for unattended collection.
- **With a stored PIN:** unattended for **up to 15 days** (refresh-token lifetime), then a full interactive browser login is required again. This makes it **B with a hard 15-day ceiling** — not truly unattended, just less frequent.

`[UNVERIFIED]` — I did **not** execute the refresh call. It requires your PIN, and handling your PIN is not something I will do. **You should test this yourself** to confirm the flow works before any architecture depends on it:

```bash
.venv/bin/python -c "import fyers_auth, os; from dotenv import load_dotenv; load_dotenv(); print(fyers_auth.refresh_access_token(os.getenv('FYER_REFRESH_TOKEN'), input('PIN: '))['s'])"
```

**This is the single most important open decision in the entire migration** (§28).

---

## 6. FYERS Historical API

`GET https://api-t1.fyers.in/data/history` — params `symbol`, `resolution`, `date_format` (0=epoch, 1=YYYY-MM-DD), `range_from`, `range_to`, `cont_flag`, `oi_flag`.

Response: `{"s":"ok", "candles": [[epoch, o, h, l, c, v], ...]}`, or `{"s":"no_data"}` when the range is valid but empty, or `{"s":"error","code":-50,"message":"Invalid input"}` when the request is malformed or over-long.

**`no_data` vs `error` is a meaningful distinction and was used throughout this investigation to separate "data doesn't exist" from "request rejected."**

---

## 7. FYERS Resolution × Year Matrix

`[ACTUAL FYERS API TEST]` — NSE:RELIANCE-EQ, 5-day window (July 10–14) of each year. 220 requests.

| Resolution | 2026 | 2025 | 2024 | 2023 | 2022 | 2021 | 2020 | 2019 | 2018 | 2017 |
|---|---|---|---|---|---|---|---|---|---|---|
| **1S** | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED |
| **5S** | AVAILABLE | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA |
| **10S** | AVAILABLE | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA |
| **15S** | AVAILABLE | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA |
| **30S** | AVAILABLE | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA |
| **45S** | AVAILABLE | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA | NO DATA |
| **1m** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE |
| **2m–240m** *(2,3,5,10,15,20,30,45,60,120,180,240)* | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE |
| **D** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE |
| **1W** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE |
| **1M** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE |

**"1S" returns error `-50 "Invalid input"`** for every year — it is rejected as a malformed parameter, i.e. genuinely unsupported, not merely empty. The finest supported resolution is **5-second**.

Candle counts validated against trading-day arithmetic throughout (e.g. 5S over 3 trading days = 13,500 = 3 × 4,500; 1m over one day = 375). This is a correctness check, not just a presence check.

---

## 8. FYERS Retention Boundaries

All `[ACTUAL FYERS API TEST]`.

| Data class | Oldest available | Evidence |
|---|---|---|
| **Equity intraday (1m–240m)** | **2017-07-03** | 2017-06-30 → `no_data`; 2017-07-03 → 375 candles from 09:15:00 IST. Identical for RELIANCE, TCS, INFY, SBIN. |
| **Index intraday (NIFTY50)** | **between 2017-07-14 and 2017-08-10** | 2017-07-03 and 2017-07-10..14 → `no_data`; 2017-08-10 → 376 candles. **Index floor is later than equity floor.** |
| **Equity daily** | **~mid-1997** | 1997-04 → `no_data`; 1997-07-01 → data. 1996 → `no_data`. |
| **Index daily** | at least 2000 | 2000-07-03 → data (older not probed) |
| **Seconds (5S–45S)** | **2026-07-10** as of test date 2026-08-15 | 2026-07-09 → `no_data`; 2026-07-10 → 4,500 candles |

### The seconds window — documentation vs reality

`[OFFICIAL FYERS DOCUMENTATION]`: *"For Seconds Charts the history will be available only for 30-Trading Days."*

`[ACTUAL FYERS API TEST]`: cutoff observed at **2026-07-10**, which is **~26 trading days** back from 2026-08-14 (counting weekdays, not adjusting for NSE holidays). A separate 100-day-window request saturated at exactly **112,500 candles = 25 trading days** of content.

**Both statements are reported as required.** The observed window is *narrower* than documented. `[INFERENCE]`: either the window is ~25–26 trading days in practice, or NSE holidays in the period account for the difference. Either way, **design for ~25 trading days, not 30** — treating 30 as guaranteed will produce gaps.

**Consequence: seconds data cannot be backfilled in any meaningful sense.** It must be collected forward from the live feed, or re-fetched at least every ~25 trading days.

---

## 9. FYERS Request Limits (max days per request)

`[ACTUAL FYERS API TEST]`, truncation-aware (checked whether the *returned* range matched the *requested* range, not merely that the call succeeded).

| Resolution | Max days/request | Boundary behavior |
|---|---|---|
| 1, 5, 60, 240 (all minute) | **exactly 100** | 100 → OK; **101 → error -50 "Invalid input"** |
| D | **exactly 366** | 366 → OK; **367 → error -50** |
| 1W | **exactly 366** | 366 → OK; **367 → error -50** |
| 1M | **exactly 366** | 366 → OK; **367 → error -50** |
| 5S | ≥100 accepted | No error at 100 days; content simply limited to what exists (~25 trading days) |

**This exactly matches `[OFFICIAL FYERS DOCUMENTATION]`** — one of the few places docs and reality agree precisely. The limit is enforced on **calendar days**, and over-long requests **fail loudly** rather than silently truncating, which is good for backfill correctness.

One methodological correction: my initial script flagged `1M` over 366 days as "TRUNCATED." That was a **false positive** — a monthly candle for August is legitimately timestamped 2026-08-01. Not truncation.

---

## 10. FYERS Rate Limits

`[OFFICIAL FYERS DOCUMENTATION]`:

| | Standard (free) | Prime (paid) |
|---|---|---|
| Per second | 10 | 10 |
| Per minute | 200 | 600 |
| Per day | **100,000** | 200,000 |

Corroborated internally by FYERS's own changelog (22 Aug 2024: *"Increased API rate limit from 10,000 requests per day to 1 Lakh"*). **User blocking:** exceeding the per-minute limit more than 3 times in a day blocks the account for the rest of that day — this is why every script here paced at ≥0.45s.

`[ACTUAL FYERS API TEST]`: ~500 requests made today with zero rate-limit errors.

### The re-download question — **ANSWERED DEFINITIVELY**

> *"If I download 3 years of historical data today, can I download the exact same 3 years again tomorrow?"*

**YES — no restriction beyond the ordinary daily request quota.** `[ACTUAL FYERS API TEST]`: the identical range (`5`-minute, 2026-07-01 → 2026-07-31) was requested twice in succession and returned **byte-identical results** (1,725 candles, same first/last timestamps), with no error, no cooldown, and no quota-specific rejection. Nothing in the documentation imposes a duplicate-download, monthly, or 30-day restriction. `[OFFICIAL FYERS DOCUMENTATION]` + `[ACTUAL FYERS API TEST]` agree.

### Quotes batching — documentation contradicted

`[OFFICIAL FYERS DOCUMENTATION]`: max **50** symbols per `/data/quotes` call.
`[ACTUAL FYERS API TEST]`: requests for **51, 100, 200, and 500** symbols all returned HTTP 200 with `s:"ok"` and the full count returned.

**Both are reported.** `[INFERENCE]`: the documented 50-symbol limit is not currently enforced. **Do not design against the undocumented 500 behavior** — it is unsupported and could be enforced at any time. Design to 50; treat anything above as opportunistic.

### Theoretical backfill times

`[INFERENCE]` from the measured limits. 1-minute backfill 2017-07-03 → present ≈ 3,330 calendar days ÷ 100 = **34 requests/symbol**. Paced at a safe 150 req/min:

| Symbols | Requests (1m full history) | Time | % of daily quota |
|---|---|---|---|
| 10 | 340 | ~2.3 min | 0.3% |
| 50 | 1,700 | ~11 min | 1.7% |
| 100 | 3,400 | ~23 min | 3.4% |
| 500 | 17,000 | ~113 min | 17% |

Adding full daily history (1997→now, 366-day chunks ≈ 29 requests/symbol) brings 500 symbols to ~31,500 requests ≈ **3.5 hours, still within a single day's 100,000 quota.** Backfill is not quota-constrained; it is wall-clock-constrained.

---

## 11. FYERS Instrument Master

`[HTTP TEST]` — all public, no auth required.

**CSV: `https://public.fyers.in/sym_details/{SEGMENT}.csv`** — all 7 segments resolve (NSE_CM 1.69 MB, NSE_FO 14.5 MB, NSE_CD, NSE_COM, BSE_CM, BSE_FO, MCX_COM).

**No header row.** 21 positional columns, mapping derived by cross-referencing identical records against the JSON master:

| # | Field | # | Field |
|---|---|---|---|
| 0 | `fyToken` | 11 | `segment` (10=CM, 11=FO) |
| 1 | `symbolDetails` | 12 | `exToken` |
| 2 | `exInstType` | 13 | `underSym` |
| 3 | `minLotSize` | 14 | underlying `exToken` |
| 4 | `tickSize` | 15 | `strikePrice` (-1.0 = N/A) |
| **5** | **`isin`** ✅ | 16 | `optType` (XX/CE/PE) |
| 6 | `tradingSession` | 17 | `underFyTok` |
| 7 | `lastUpdate` | 18 | `originalExpDate` (literal `None`) |
| 8 | `expiryDate` (epoch) | 19 | `is_mtf_tradable` |
| 9 | `symTicker` ← **subscribe key** | 20 | `mtf_margin` |
| 10 | `exchange` (10=NSE) | | |

**ISIN is present at column 5** for equities (empty for derivatives) — this is what enables provider-independent instrument identity.

**Richer JSON master (undocumented pattern):** `https://public.fyers.in/sym_details/{SEGMENT}_sym_master.json` — NSE_CM 10.98 MB, NSE_FO 82.1 MB. **44 named fields**, including several absent from the CSV: `upperPrice`, `lowerPrice`, `previousClose`, `previousOi`, `qtyFreeze`, `faceValue`, `tradeStatus`, `asmGsmVal`, `has_options`, `has_futures`. The documented `{SEGMENT}.json` pattern mostly **404s** (only `BSE_CM.json` resolves, and it's just a thin name map).

**Recommendation:** use `_sym_master.json` as the authoritative source. Key the internal instrument table on **ISIN** for equities, and on `(underSym, expiryDate, strikePrice, optType)` for derivatives. `tradeStatus` (1=Active/0=Inactive) is the delisting signal. Snapshot the master **daily** and retain history — otherwise expired F&O contracts and delisted symbols become unresolvable retroactively.

**F&O symbol format confirmed** `[ACTUAL FYERS API TEST]`: `NSE:NIFTY26AUGFUT`, `NSE:NIFTY26AUG24000CE`, `NSE:RELIANCE26AUGFUT` all work. `{YY}` is the 2-digit year (`26`), not the expiry-cycle year — an earlier guess of `25AUG` returned "Invalid symbol provided."

---

## 12. FYERS Live WebSocket

`[SDK SOURCE]` (fyers-apiv3 3.1.16) + `[OFFICIAL FYERS DOCUMENTATION]`.

**Two separate sockets:**

| | Data socket | TBT socket |
|---|---|---|
| URL | `wss://socket.fyers.in/hsm/v1-5/prod` | `wss://rtsocket-api.fyers.in/versova` |
| Protocol | Custom **HSM binary** | **Protobuf** |
| Depth | 5 levels | **50 levels** |
| Modes | SymbolUpdate (`sf`), DepthUpdate (`dp`), index (`if`), lite | DEPTH only (in SDK) |
| Subscription cap | **5,000 symbols** (client-enforced) | 5 symbols/connection, 3 connections/user |
| Sequence number | **NONE** | **YES** (`sequence_no`) |
| Auto-resubscribe on reconnect | **NO** | YES |

**`[SDK SOURCE]` — the SDK cannot be installed in this project:**
1. All three WebSocket modules do `from pkg_resources import resource_filename` at module level. This venv is **Python 3.14.4 with no setuptools** — `pkg_resources` was removed in setuptools 81+. Import fails immediately.
2. Hard-pinned deps would **downgrade** the project: `requests==2.31.0` (you have 2.33.1), `aiohttp==3.9.3` (you have 3.13.5), plus `aws_lambda_powertools` and a dead `asyncio` PyPI stub that shadows the stdlib module.

**Recommendation:** continue the current raw-REST approach (already working), and for WebSocket either use a separate venv or vendor only the decode logic. The existing hand-rolled [fyers_auth.py](../fyers_auth.py) is **strictly better than the SDK**, which has no token handling at all.

---

## 13. FYERS Tick/Update Structure — **VOLUME IS THE CRITICAL DETAIL**

`[SDK SOURCE]`. Data-socket full-mode field array (from bundled `map.json`):

```
[0] ltp               [8]  last_traded_qty   [16] Ylow
[1] vol_traded_today  [9]  tot_buy_qty       [17] lower_ckt
[2] last_traded_time  [10] tot_sell_qty      [18] upper_ckt
[3] exch_feed_time    [11] avg_trade_price   [19] open_price
[4] bid_size          [12] OI                [20] prev_close_price
[5] ask_size          [13] low_price         [21] type
[6] bid_price         [14] high_price        [22] symbol
[7] ask_price         [15] Yhigh
```

**Three findings that determine whether candle-building is even correct:**

1. **Volume is CUMULATIVE.** Field `[1]` is `vol_traded_today` — running total for the day. Corroborated by the TBT proto: `UInt64Value vtt = 4; // Volume Traded Today`. There is **no per-update delta field** on the data socket.

2. **The feed is a CONFLATED SNAPSHOT, not a trade stream.** `[SDK SOURCE]` `data_ws.py:1163-1216` — every packet carries the entire field array and replaces state wholesale. There is no trade record, no trade id, and **no sequence number**. Multiple exchange trades between two packets collapse into one update.
   → **Summing `last_traded_qty` will undercount, badly.** It only ever shows the last trade before each packet.
   → **Differencing `vol_traded_today` is correct**, because a cumulative counter absorbs both conflation and dropped updates.

3. **Correct formula:** `candle_volume = last_vtt_in_bucket − last_vtt_in_PREVIOUS_bucket`.
   **Not** `last_in_bucket − first_in_bucket` — that silently drops volume accrued between the previous bucket's close and this bucket's first tick.

**Three hazards that must be handled:**

- **🔴 INT32 overflow.** `[SDK SOURCE]` `data_ws.py:1173` decodes every field with `struct.unpack(">i", ...)` — **signed 32-bit**. `vol_traded_today` wraps past **2,147,483,647**. This is not theoretical: NSE names like IDEA routinely trade >2bn shares/day. A negative diff must be treated as suspect, not as volume.
- **Sentinel `-2147483648`** (INT32_MIN) means "field absent" — never treat as data.
- **🔴 Reconnect destroys the baseline.** `[SDK SOURCE]` `data_ws.py:1618-1626` wipes all cumulative state, **and `on_open` does not resubscribe**. You must resubscribe yourself and **discard the first post-reconnect diff**.

**Free cross-check:** `avg_trade_price × vol_traded_today` = turnover. Differencing turnover across a bucket yields that bucket's VWAP and **independently validates the volume diff** — recommended as a built-in integrity check.

**The documented "queue processing interval" (1ms–2000ms) does not exist in the SDK.** `[SDK SOURCE]` grep across the whole package finds only ping-keepalive docstrings. `[INFERENCE]`: conflation happens **server-side** and is neither observable nor controllable from the client.

**The irony worth knowing:** `[PROTO FILE]` the TBT protobuf *does* carry `vtt_diff` (per-update volume delta) **and** `sequence_no` (gap detection) — exactly what you'd want. But `[SDK SOURCE]` `SubscriptionModes` has a single member (`DEPTH = "depth"`) and `Depth._addDepth` reads only depth levels, silently discarding the `quote` field. **These fields are reachable only by parsing `msg_pb2.SocketMessage` yourself.** Whether the server populates `quote`/`vtt_diff` for a depth subscription is `[UNVERIFIED]` — it needs a live connection to confirm.

---

## 14. 1-Second Candle Feasibility

**Historical: IMPOSSIBLE.** `[ACTUAL FYERS API TEST]` — `1S` returns error -50. Finest historical resolution is **5-second**, and only for ~25 trading days.

**Live-constructed: POSSIBLE BUT QUALIFIED.**
- Volume **totals** are recoverable via `vtt` differencing.
- **Sub-second trade attribution is not recoverable** — `last_traded_time` and `exch_feed_time` are integer *seconds*, and the feed is server-conflated. A conflated packet's entire volume delta lands in whichever second the packet is attributed to.
- `[UNVERIFIED]` — the feed's actual update rate is unknown without a live connection. If it conflates to slower than 1 update/second for a given symbol, **many 1-second buckets will be empty or carry stale prices**.

**Honest assessment `[INFERENCE]`:** 1-second candles from this feed would be *approximations*, not tick-accurate bars. Their fidelity is proportional to the (undocumented, server-controlled) update rate. **Measure the real update rate on a live connection before committing to 1-second as a storage tier** — this is a cheap experiment and it determines a ~50 GB storage decision (§17).

---

## 15. 1-Minute Candle Feasibility

**Historical: EXCELLENT.** 2017-07-03 → present for equities, verified.

**Live-constructed: RELIABLE.** At 60-second buckets, the ~1-second timestamp granularity is effectively exact, and `vtt` differencing gives correct volume regardless of conflation. **This is the recommended primary live tier.**

**Best-of-both:** build 1-minute bars live, and **reconcile against the historical API after market close** — the same bar is available from both sources, giving a free daily correctness audit (§21).

---

## 16. Historical Resolution Ladder — **THE KEY DELIVERABLE**

Derived entirely from `[ACTUAL FYERS API TEST]` boundaries in §8. This is the maximum FYERS actually permits:

| Period | Best available resolution | Why |
|---|---|---|
| **~1997-07 → 2017-07-02** (~20 yrs) | **Daily** | Intraday does not exist before 2017-07-03 |
| **2017-07-03 → T−25 trading days** (~9 yrs) | **1-minute** | Equity intraday floor; index floor is ~2017-08 |
| **Last ~25 trading days** | **5-second** | Seconds window; **cannot be backfilled, only collected** |
| **Going forward** | **5-second live** (or 1-minute, see §14) | WebSocket |

**Notes:**
- Any coarser resolution (5m, 15m, 1h) is **derivable by aggregation** from 1-minute — there is no reason to fetch them separately, and doing so wastes quota. Fetch 1-minute, aggregate upward.
- **Exception:** daily/weekly/monthly should be fetched **natively** for the pre-2017 era where no intraday exists, and daily should *also* be fetched natively for the modern era as a cross-check against your own aggregation.
- **Index intraday starts ~1 month later than equity** — plan index backfill from 2017-08, not 2017-07.

---

## 17. Storage Requirements

**Row sizes are MEASURED, not estimated** `[OUR DATABASE]` — via 200,000-row temp tables inside a rolled-back transaction (nothing persisted; verified 0 tables remaining):

| Design | Heap/row | Total/row (incl. 1 index) |
|---|---|---|
| **Wide** (VARCHAR symbol/provider/source/resolution) | 134.3 B | **175.2 B** |
| **Narrow** (INT instrument_id, SMALLINT resolution/source) | 93.1 B | **124.9 B** |

**The narrow design is 29% smaller.** All figures below use **125 B/row**. Assumptions: 375-minute session, ~250 trading days/year.

### Rows per symbol

| Resolution | Per day | Per year |
|---|---|---|
| 5-second | 4,500 | 1,125,000 |
| 1-minute | 375 | 93,750 |
| 5-minute | 75 | 18,750 |
| 15-minute | 25 | 6,250 |
| Daily | 1 | 250 |

### Historical backfill (one-time)

| Dataset | Per symbol | 10 | 50 | 75 | 100 | 500 |
|---|---|---|---|---|---|---|
| **1-min, 2017-07→2026** (855k rows) | 107 MB | 1.07 GB | 5.3 GB | **8.0 GB** | 10.7 GB | 53.4 GB |
| **Daily, 1997→2026** (7,275 rows) | 0.9 MB | 9 MB | 45 MB | 68 MB | 90 MB | 455 MB |

### Forward live collection

| Tier | Per symbol/yr | 75 sym/yr | 75 sym × 5 yr | 500 sym × 5 yr |
|---|---|---|---|---|
| **5-second** | 141 MB | **10.5 GB** | **52.7 GB** | 352 GB |
| **1-minute** | 11.7 MB | 879 MB | 4.4 GB | 29 GB |
| 5-minute (aggregate) | 2.3 MB | 176 MB | 879 MB | 5.9 GB |
| 15-minute (aggregate) | 0.8 MB | 59 MB | 293 MB | 2.0 GB |

### The decision that dominates storage

| Plan (75 symbols, 5 years) | Total |
|---|---|
| Historical (1m + daily) + forward **1-minute** + aggregates | **≈ 14 GB** |
| Historical (1m + daily) + forward **5-second** + aggregates | **≈ 66 GB** |

**Storing 5-second data costs ~52 GB over 5 years at 75 symbols — roughly 4× the entire rest of the dataset.** `[INFERENCE]`: given §14's finding that sub-second fidelity is not recoverable anyway, **1-minute live + 5-second retained for only a rolling window (e.g. 90 days) is the better trade**. That would cost ~2.6 GB instead of 52.7 GB. This deserves an explicit decision (§28).

**Add ~30% headroom** for a second index, partition overhead, and WAL. All figures assume a **regularly vacuumed** table — the existing `candles` table's 127× bloat is a maintenance failure, not a schema property, and must not be replicated.

---

## 18. PostgreSQL Architecture

### Unified vs per-resolution tables

| | Unified (`fyers_candles` + `resolution` column) | Per-resolution (`fyers_1s`, `fyers_1m`, …) |
|---|---|---|
| Query simplicity | One table, one code path | Caller must pick the right table |
| Index efficiency | `(instrument_id, resolution, ts)` — one extra column | Marginally tighter indexes |
| Adding a resolution | Insert rows | **DDL required** |
| Partition count | Manageable (by month) | Multiplies (tables × months) |
| Mixed-resolution queries | Trivial | Requires UNION |
| Risk of resolution confusion | **Eliminated by NOT NULL column** | Eliminated by table name |

**RECOMMENDATION: unified table, range-partitioned by month, with a NOT NULL `resolution` column.** The per-resolution split's only real win is slightly tighter indexes, which the measured 29% saving from narrow typing already exceeds. The unified design also directly fixes the existing `candles` table's core defect (mixed resolutions with no discriminator).

**One qualification:** if 5-second data is retained long-term at 500-symbol scale (352 GB), splitting *just the seconds tier* into its own partitioned table is defensible, because its retention policy differs fundamentally from everything else. `[INFERENCE]` — revisit only if §28's seconds decision goes that way.

### Schema

Proposed DDL: [db/fyers_candles_schema.sql](../db/fyers_candles_schema.sql) — **written, not executed**. Key decisions:

- **`instrument_id INT` → separate `instruments` table** keyed on ISIN (equities) / contract tuple (derivatives). Avoids repeating symbol strings 100M+ times and survives renames.
- **`resolution SMALLINT NOT NULL`** — explicit always, never inferred from timestamp spacing.
- **`source_type SMALLINT NOT NULL`** — `historical` vs `websocket`, so "where did this candle come from?" is always answerable.
- **`ts TIMESTAMPTZ`** — the existing `candles` table uses naive `TIMESTAMP`; that ambiguity is exactly what §19 shows to be dangerous.
- **`UNIQUE (instrument_id, resolution, ts)`** → enables idempotent `ON CONFLICT DO NOTHING` upserts, which is what makes the backfill safely resumable.
- **`CHECK (low <= open, close <= high AND low <= high)`** — moves OHLC integrity into the schema rather than a script someone must remember to run.
- **Monthly range partitions** on `ts`.
- **No TimescaleDB** — native partitioning covers the access pattern (`instrument + resolution + ts range`) at this scale. Revisit only if continuous aggregates become genuinely needed.

**Concurrent writers:** the backfill and the live collector will both write. The unique constraint plus `ON CONFLICT DO NOTHING` makes this safe without coordination. Live writes should go to a small unlogged staging table and be flushed in batches, so the WebSocket thread never blocks on a partition lock.

---

## 19. Timezone & Timestamp Semantics — **A TRAP**

`[ACTUAL FYERS API TEST]`, verified on 2026-08-13:

| Resolution | Timestamp convention | Example |
|---|---|---|
| **Intraday (1m–240m, seconds)** | Candle **OPEN** time, real IST market time | First 1-min bar = epoch 1786592700 = **09:15:00 IST**; last = 15:29:00 IST; 375 bars |
| **Daily** | **00:00:00 UTC of the trade date** (= 05:30 IST) | 2026-08-13 → epoch 1786579200 = **05:30 IST** |
| **Weekly** | Anchored to **Monday** | 2026-08-10 |
| **Monthly** | Anchored to the **1st** | 2026-08-01 |

**Daily and intraday use different conventions.** A naive `JOIN ... USING (ts)` or a shared normalization path that assumes one convention will silently misalign daily against intraday.

**Canonical internal format:** store everything as `TIMESTAMPTZ` representing the **candle open instant**. For daily bars, `[INFERENCE]` normalize to **09:15:00 IST of the trade date** (true session open) rather than preserving FYERS's 00:00 UTC — and record the raw value if provenance matters. Make this transformation explicit and tested; it is exactly the class of bug that produces silently wrong backtests.

---

## 20. Historical Backfill Architecture

**Not built. Design only.**

```
instruments (ISIN-keyed)
      ↓
backfill_jobs (instrument_id, resolution, range_start, range_end, status, attempts, last_error)
      ↓
chunker: 100-day windows (minute) / 366-day (D,W,M)   ← §9 measured limits
      ↓
rate limiter: token bucket, ≤150 req/min, ≤8 req/sec  ← safety margin under §10
      ↓
fetch → VALIDATE → upsert ON CONFLICT DO NOTHING
      ↓
mark chunk complete ONLY after validation passes
```

**Validation before marking a chunk complete** (the requirement that a 200 response ≠ complete data):
1. `s == "ok"` and candle array non-empty (or `no_data` on a known holiday/pre-listing range)
2. **Expected vs actual count** — expected = trading_days_in_chunk × bars_per_day for that resolution
3. First/last timestamps fall within the requested range
4. Timestamps strictly increasing, no duplicates
5. Each bar within trading hours for its resolution
6. OHLC sanity: `low ≤ open,close ≤ high`
7. Row count after upsert matches expectation (catches silent conflict drops)

**Resumability:** `backfill_jobs` is the checkpoint. A chunk is `pending → in_progress → complete|failed`. On restart, re-queue anything not `complete`. Because upserts are idempotent, **re-running a partially-applied chunk is harmless** — this is what makes crash recovery trivial.

**Retry:** exponential backoff (1s, 2s, 4s, 8s, 16s, cap 60s), max 5 attempts, then `failed` with the error recorded. **Distinguish error classes:** `-50 Invalid input` is a *permanent* bug in chunking (do not retry — fix the request); HTTP 429 is *transient* (back off); auth errors should **halt the whole run**, not burn retries.

**Trading-day calendar:** the count-validation step needs a real NSE holiday calendar. `[INFERENCE]` derive it empirically — fetch daily candles for a liquid symbol across the whole period; every weekday absent from that series is a market holiday. This is self-bootstrapping and needs no external source.

---

## 21. Live Collection Architecture

**Not built. Design only.**

```
FYERS WebSocket (SymbolUpdate)
        ↓
normalizer  — reject sentinel -2147483648; detect int32 wrap
        ↓
per-symbol state: last_vtt, last_bucket, open/high/low/close accumulator
        ↓
bucket close → volume = vtt_now − vtt_at_previous_bucket_close    ← §13
        ↓
unlogged staging table (batched)
        ↓
flush → fyers_candles (source_type='websocket')
        ↓
aggregate upward: 1m → 5m → 15m (never re-derive from ticks)
```

**Handling the hard cases:**

| Case | Handling |
|---|---|
| Reconnect | Resubscribe explicitly (SDK does not); **discard first diff**, re-seed `last_vtt` |
| Int32 wrap | `diff < 0` → flag bar `suspect`, backfill that bar from the historical API after close |
| Late/duplicate updates | Bucket by `exch_feed_time`, not arrival time; unique constraint absorbs duplicates |
| Market open | Seed `last_vtt = 0` at session start (cumulative resets daily) |
| Market close | Flush the final partial bucket; mark session complete |
| Holidays | Market-status endpoint gates collection |
| Server restart | Staging table is unlogged → **on restart, re-fetch today's bars from the historical API** rather than trusting partial state |
| Clock drift | Never use local clock for bucketing — use `exch_feed_time` from the feed |
| Partial final candle | Mark `is_partial`; overwrite from historical API after close |

**Daily reconciliation (recommended):** after market close, re-fetch the day's 1-minute bars from the historical API and diff against the WebSocket-built bars. Any mismatch is a bug signal, and the historical version wins. This turns §14's uncertainty into a *measured* quantity instead of an assumption.

---

## 22. Historical → Live Continuity

**Requirement:** no duplicates, no gaps, no timezone shift at the boundary.

**Why this is tractable here:** both sources produce the **same bar identity** — `(instrument_id, resolution, ts)`. With the unique constraint, overlap is *automatically* deduplicated. The design therefore deliberately **overlaps rather than abuts**:

```
historical backfill →  ... up to T
live websocket     →  from T − 1 day  (deliberate overlap)
                       ↓
         UNIQUE(instrument_id,resolution,ts) absorbs the overlap
```

**Never try to make the two sources meet exactly at a boundary instant** — that is where off-by-one gaps live. Overlap and let the constraint do the work.

**Self-healing gap repair loop:**

```
every N minutes:
  last_ts = SELECT max(ts) WHERE instrument_id=? AND resolution=? AND source_type='websocket'
  if now() - last_ts > threshold:
      fetch historical [last_ts, now()]      ← fills the gap
      upsert (idempotent)
      resume/reconnect websocket
```

**This also fixes the existing Groww pipeline's worst flaw.** `[OUR CODE]` `bot.sync_candles_from_api` detects only the **edge gap** (`MAX(timestamp)` → now), never interior gaps; `CandleDatabase.get_missing_dates()` exists for exactly this and **is never called anywhere**. The FYERS design must detect **both**:

- **Edge gap:** `max(ts)` → now (what Groww does)
- **Interior gap:** generate the expected bar series for a range, `LEFT JOIN` actual, and find holes — cheap as a SQL query against the partitioned table, and the thing that would have caught the 226-vs-300 candle shortfall found in the Groww data.

---

## 23. Data Validation

Per your instruction, validation is **internal to FYERS**; Groww is reference-only and **volume differences with Groww do not block migration**.

| Check | Rule |
|---|---|
| OHLC integrity | `low ≤ open,close ≤ high`, `low ≤ high` — enforced by CHECK constraint |
| Volume | `≥ 0`; negative diff → int32 wrap suspect |
| Duplicates | Prevented by UNIQUE constraint |
| Missing intervals | Expected-vs-actual bar count per session |
| Session bounds | Every intraday bar within 09:15–15:30 IST |
| Monotonic time | Strictly increasing per (instrument, resolution) |
| Historical↔live agreement | Daily post-close reconciliation (§21) |
| Cross-resolution | 1-min aggregated to 5-min must equal natively-fetched 5-min — a strong end-to-end check |

**A note on the Groww comparison** (from the earlier phase, retained for context, not as a blocker): daily closes differed ~0.5%; **volume differed 20–50×**; Groww's stored 5-minute data had 226 of an expected 300 bars. `[INFERENCE]` the volume discrepancy is most likely a units/aggregation artifact in *our* Groww ingestion (`stock_prices.volume` appears to be a rollup), not a FYERS defect — but per your instruction this is explicitly **deferred, not resolved**.

---

## 24. Provider Abstraction

Skeleton exists (created earlier, **nothing rewired to use it**):

- [market_data_provider.py](../market_data_provider.py) — ABC with only methods the audit proved are used
- [groww_market_data_provider.py](../groww_market_data_provider.py) — wraps existing Groww call sites; **no behavior change**
- [fyers_market_data_provider.py](../fyers_market_data_provider.py) — wraps `fyers_client.py`

**Deliberately omitted:** `get_market_depth` (no Groww call site uses it), and `search_instruments` raises `NotImplementedError` on both sides with an explanatory message rather than a fake implementation — FYERS has **no search endpoint**, only bulk master downloads (§11).

**The required separation:**

```
FYERS ──→ MarketDataProvider ──→ strategy / model / dashboard
                                          │
                                          ↓
                                  TRADING SIGNAL
                                          │
                                          ↓
                            BrokerExecutionProvider ──→ Groww | Zerodha
```

Market data never knows who executes; execution never knows who supplied data. **`ExecutionProvider` is deliberately not designed in this phase** — execution is out of scope and designing it speculatively would violate the "nothing beyond what's proven necessary" principle.

---

## 25. Dashboard Migration

**Not touched.** A full consumer audit was run `[OUR CODE]` — 19 distinct SQL/ORM reads of `candles`, 18 of `stock_prices`, 5 of `intraday_candles`, ~25 Flask routes, and every frontend fetch mapped to `index.html` line numbers.

**Migration principle:**

```
CURRENT:  dashboard → route → candles / stock_prices  (Groww-sourced)
TARGET:   dashboard → route → fyers_candles           (FYERS-sourced)
```

**The old Groww tables remain intact throughout.** Recommended cutover: add a `provider` filter to the reading layer, default it to Groww, flip per-route once each route's numbers verify against the FYERS table. Rollback becomes a config change, not a restore.

### The frontend contract that must not break

**Two incompatible candle key conventions are live simultaneously:**
- **Short keys** `{time, o, h, l, c, v}` — `/api/1min-candles`, `/api/5min-candles`, `/api/trade-snapshots/candles`
- **Long keys** `{time, open, high, low, close, volume}` — `/api/trade-candles`, `/api/intraday-candles`

Only **one** renderer (`index.html:14390-14392`) tolerates both. **Unifying them during migration will silently blank charts** unless every render path is updated together.

### Dashboard migration map (abbreviated — full map in the audit output)

| Feature | CURRENT path | What must change |
|---|---|---|
| Watchlist table | `index.html:5563` → `/api/watchlist` → `stock_prices` | Repoint `app.py:3035-3045`; **also repoint the 7 universe queries** or the watchlist empties |
| Stock analysis chart | `index.html:6591` → `/api/prices/<sym>` → `stock_prices` | Repoint `app.py:4604-4624`, add `WHERE resolution='D'`; keep `{date,open,high,low,close,volume}` oldest-first |
| Analysis body (score/targets/price-action) | `index.html:6592` → `/api/watchlist/<sym>/analysis` | Repoint 5 queries `app.py:3402-3634`; the 1W/1M/3M/6M/1Y block must become resolution-aware |
| Live price cells / open-trade P&L | `index.html:12101,12122,12531` → `/api/live-prices`,`/api/price` | Repoint `_get_latest_symbol_price` (`app.py:6502-6562`); **add an interval filter** — a 60-min bar is currently served as spot |
| Multi-trade day chart | `index.html:12930` → `/api/5min-candles` | Repoint `app.py:7013-7017`; map FYERS `'5'` → current `'5min'` string |
| Full-day chart modal | `index.html:13792` → `/api/1min-candles` | **Both "1min" and "5min" routes query `interval=='5min'`** despite their names — fix or rename |
| Backtesting tab | `index.html:10666-11170` → `/api/fno/backtest/*` | **Resolve the 1-hour-vs-5-min contradiction first**, or numbers stay wrong at a new address |
| Data health panel | `index.html:7008` → `/api/data-health` | **Extend to cover the FYERS table BEFORE cutover** (project standard #7) — otherwise the tool you'd verify the migration with is reading the table being migrated |

### 🔴 Riskiest migration points — ranked by how *silently* they produce wrong numbers

1. **`fno_backtester._simulate_trade_outcome`** (`fno_backtester.py:754-793`) — `lookahead=525` ("7 days × 75 candles/day") and `daily_atr = candle_atr * 8.66` ("√75") are **5-minute constants**, applied to candles the same file's loader documents as **1-hour** (`fno_backtester.py:115`), drawn from a table holding daily + 5-min + 1-min. **This trains the model `fno_trader.py:1183` uses for live F&O orders.** Nothing errors; every label is simply wrong.
2. **`scheduler._task_aggregate_candles_to_daily`** (`scheduler.py:714-726`) — `MIN(open) as open_price` is wrong as a day-open under *any* resolution, combined with resolution-blind `SUM(volume)`. This is the single bridge feeding `stock_prices`, and the entire dashboard price display sits downstream.
3. **`market_context._fetch_candle_data_from_db`** (`market_context.py:93`) — `LIMIT days*75`. Off by 75× the moment bars aren't 5-minute; feeds `bot.get_prediction`.
4. **`db_manager.get_candles`** (`db_manager.py:758-794`) — **accepts `interval_minutes` and ignores it** (docstring: *"for info only"*). Every caller believes it filters by resolution; none do. **Cheapest place to introduce a real resolution filter — fix first.**
5. **`predictor.build_features`** (`predictor.py:292-324`) — session features (`/370.0`, `/74.0`) **degrade to constants instead of raising** on daily bars. A post-migration retrain looks successful while 8 features are zero-variance.
6. **`fno_backtester._fetch_candles_from_db`** (`fno_backtester.py:157-162`) — no `interval` filter, then `volumes +=` double-counts where 5-min and 60-min rows coexist.

---

## 26. Migration Risks

1. **🔴 Authentication is the project blocker** (§5) — daily 06:00 IST expiry, PIN-gated refresh, 15-day refresh ceiling. Without a decision here, unattended collection is impossible.
2. **🔴 Volume must be differenced, not summed** (§13) — getting this wrong produces plausible-looking but wrong volume, the worst failure mode.
3. **🔴 Int32 volume overflow** at 2.147bn — real for high-turnover names.
4. **🔴 Reconnect wipes state and does not resubscribe** — silent data loss if unhandled.
5. **Daily vs intraday timestamp convention differs** (§19) — silent misalignment.
6. **Index intraday floor ≠ equity floor** (§8) — a uniform 2017-07-03 backfill will fail for indices.
7. **Seconds window is ~25 trading days, not the documented 30** — designing for 30 creates gaps.
8. **Documented 50-symbol quote limit is unenforced** (§10) — do not build on the undocumented 500 behavior.
9. **SDK is uninstallable in this venv** (§12) — Python 3.14 / `pkg_resources`, plus dependency downgrades.
10. **Existing `candles` bloat (127×)** will slow any future dump/restore; unrelated to FYERS but will be hit.
11. **Storage decision on 5-second data** is a ~50 GB swing (§17).
12. `[UNVERIFIED]` **TBT `vtt_diff`/`sequence_no` availability** — would materially improve accuracy if the server populates them; needs a live test.

---

## 27. Known Bugs in the Existing Groww Pipeline

`[OUR CODE]` — all pre-existing, none introduced by this work:

1. **Three permanently-broken routes** — `/api/intraday/enter-paper`, `/close-paper`, `/auto-trade-run-paper` call `fno_trader._groww_api` (doesn't exist; real accessor is `_get_groww()`) and `fno_trader.find_best_opportunity` (doesn't exist; real name `_select_best_opportunity`). Every call raises `AttributeError`, caught and returned as a generic error.
2. **`collect_index_candles.py` never runs** — `from groww_api import ...`; no such module (`growwapi` is correct). Fails at import; nothing calls it.
3. **Backfill has no chunking, no retry, no interior-gap detection** — `bot.sync_candles_from_api` issues one unchunked call for an arbitrarily large gap; would fail against Groww's own 15-day/5-min limit.
4. **`get_missing_dates()` is dead code** — models interior gaps, never called anywhere.
5. **`fetch_full_history.py` has `now = datetime(2026, 4, 1)` hard-coded** — as of today it silently stops 4.5 months short.
6. **`IntradayCandle.interval == "1min"` never matches** — every writer writes `"5min"`/`"60min"`, silently disabling a prediction-enhancement path.
7. **`fetch_google_prices.py` `DELETE`s all of `stock_prices`** before repopulating only 3 symbols from Yahoo. Not scheduled, but live and runnable.

Found by the consumer audit `[OUR CODE]`:

8. **🔴 `segment='EQ'` is not a valid Groww segment.** `growwapi/groww/client.py:76,79` defines only `SEGMENT_CASH="CASH"` and `SEGMENT_FNO="FNO"`. **Four call sites pass `'EQ'`**: `app.py:6656` (`/api/intraday-candles`), `app.py:6742` (`/api/trade-candles`), `trailing_stop.py:68`, `paper_trader.py:316`. All swallow the exception and return empty. **`/api/trade-candles` is a live frontend dependency** (`index.html:14552`) that therefore *always* falls through to the fallback chart. Migrating to FYERS would "fix" this — changing dashboard behavior as a side effect.
9. **🔴 `/api/watchlist/remove/<symbol>` destroys price history** — `app.py:3220` issues `DELETE FROM stock_prices WHERE symbol=%s`. Since that table is the universe registry (§3), this is also how the universe silently shrinks.
10. **`scheduler.py:352-353` treats Groww candles as dicts** (`c.get("timestamp")`) while `bot.py:194-201` and every `app.py` handler treats them as **lists** (`c[0]`). If the SDK returns lists, `_task_collect_5min_candles` raises per-symbol, is caught at line 368, and logged at DEBUG — meaning **the 5-minute collector may be silently collecting nothing.** `[UNVERIFIED]` — needs one live call to settle.
11. **`daily_summary.py:164` imports `StockPredictor`, which doesn't exist** (the class is `PricePredictor`, `predictor.py:362`). Caught by a bare `except`, so `_get_watchlist_predictions` always returns `[]`.
12. **`scheduler.py:657`** opens a fresh psycopg2 connection **inside a per-symbol loop** for a `MAX(timestamp)` whose result is never read — pure N+1 with no consumer.

---

## 28. Open Questions — **DECISIONS NEEDED FROM YOU**

1. **🔴 PIN handling (blocks everything unattended).** Options: (a) interactive login daily before 06:00 IST — no secret stored, not unattended; (b) store the PIN encrypted, unattended for 15 days, then manual re-login; (c) accept market-hours-only operation with a manual morning login. **I will not store or handle your PIN without an explicit decision from you.**
2. **🔴 Does the refresh flow actually work?** `[UNVERIFIED]` — needs one test **you** run (command in §5).
3. **5-second retention policy** — permanent (~52.7 GB / 75 symbols / 5 yrs) vs rolling 90-day (~2.6 GB) vs skip entirely? §14 suggests its marginal value over 1-minute is low.
4. **Symbol universe** — 75 (current), or expand? Drives every storage and time estimate linearly.
5. **Index intraday from ~2017-08** — accept the ~1-month-later floor, or source indices differently?
6. **Groww volume discrepancy** — you deferred it; confirm it stays deferred.
7. **Should `fyers_candles` DDL be executed now**, or stay a proposal?

---

## 29. Recommended Next Steps

**Phase 2A — resolve the blocker (do this first, it may change everything):**
1. You test the refresh flow (§5). If it fails, the whole unattended design changes.
2. Decide PIN handling (§28.1).
3. Create a **Market-Data-only FYERS app** (no order permission) — enforces the data/execution split at the credential level.

**Phase 2B — prove the pipeline small:**
4. Execute the schema for **one instrument** (RELIANCE).
5. Backfill RELIANCE 1-minute 2017-07-03 → present (~34 requests, ~2 min). Validate every chunk.
6. Run a **live WebSocket session for one day on 2–3 symbols** and measure: actual update rate, whether `vtt` differencing reproduces the historical bars, and whether TBT exposes `vtt_diff`/`sequence_no`. **This single experiment resolves §14, §17.3, and §26.12 at once.**
7. Reconcile live-built vs historical 1-minute bars for that day.

**Phase 2C — scale:**
8. Extend to the full universe once 5–7 pass cleanly.
9. Build the interior-gap detector and self-healing loop (§22).

**Phase 3 — dashboard**, per-route with a provider flag and rollback (§25).

**Do not proceed past 2A until the auth question is answered** — everything downstream depends on it.

---

## 30. Evidence & Sources

- **`[OFFICIAL FYERS DOCUMENTATION]`** — 168-page API reference, read in full (pages 1–168, sequentially) earlier in this session; Authentication section re-read this phase to confirm exact field names before writing auth code.
- **`[ACTUAL FYERS API TEST]`** — ~500 read-only requests today against `api-t1.fyers.in`, live token, paced ≥0.45s. Raw results retained: `matrix_results.json`, `boundaries.json`, `probe2.json`, `fyers_test_results.json`.
- **`[SDK SOURCE]`** — `fyers-apiv3` 3.1.16 sdist+wheel downloaded to `/tmp` for inspection; **not installed**; project venv untouched.
- **`[PROTO FILE]`** — `https://public.fyers.in/tbtproto/1.0.0/msg.proto`, HTTP 200, 3,604 bytes.
- **`[OUR CODE]`** — full repository audit.
- **`[OUR DATABASE]`** — `grow_trading_bot`, read-only; row sizes measured via rolled-back temp tables (0 persisted).

### Files created this session (all additive)

| File | Status |
|---|---|
| [fyers_auth.py](../fyers_auth.py) | Working, tested |
| [fyers_client.py](../fyers_client.py) | Working, tested |
| [market_data_provider.py](../market_data_provider.py) | Interface only |
| [groww_market_data_provider.py](../groww_market_data_provider.py) | Adapter; nothing rewired to it |
| [fyers_market_data_provider.py](../fyers_market_data_provider.py) | Adapter |
| [db/fyers_candles_schema.sql](../db/fyers_candles_schema.sql) | **Proposal — not executed** |
| [docs/FYERS_VS_GROWW_MARKET_DATA.md](FYERS_VS_GROWW_MARKET_DATA.md) | Earlier comparison |
| [docs/FYERS_MIGRATION_PHASE1.md](FYERS_MIGRATION_PHASE1.md) | Earlier phase |

**Unchanged:** `app.py`, `bot.py`, `fno_trader.py`, `scheduler.py`, all Groww code, all existing tables, the dashboard. `.env` gained only the two token fields FYERS's own login flow writes.

---

## The 14 questions you asked, answered

| # | Question | Answer |
|---|---|---|
| 1 | What can FYERS give us? | 5-second to monthly candles, quotes, 5-level + 50-level depth, option chain with Greeks + OI, full instrument master with ISIN |
| 2 | How far back? | **Daily ~1997** (29 yrs) · **1-minute 2017-07-03** (9 yrs) · **seconds ~25 trading days** |
| 3 | At what resolution? | 5S/10S/15S/30S/45S, 1–240m, D, 1W, 1M. **1-second is NOT supported** |
| 4 | How much per request? | **100 days** (all minute) · **366 days** (D/W/M). 101/367 → hard error |
| 5 | How many requests? | 10/sec, 200/min, **100,000/day** (Standard) |
| 6 | Re-download tomorrow? | **YES — no restriction.** Verified byte-identical repeat |
| 7 | Unattended auth? | **NO** — daily 06:00 IST expiry; PIN-gated refresh; 15-day ceiling. **Decision needed** |
| 8 | 5-year storage? | **~14 GB** (1-min live) or **~66 GB** (5-sec live), 75 symbols, measured row sizes |
| 9 | How to build the dataset? | Unified partitioned table, ISIN-keyed instruments, explicit resolution, idempotent upserts (§18) |
| 10 | Historical → live transition? | **Deliberate overlap**, deduplicated by unique constraint (§22) |
| 11 | Auto-repair gaps? | Edge **and** interior gap detection + historical re-fetch loop (§22) |
| 12 | Groww functionality to replicate? | Historical candles, LTP, quote, option chain + Greeks, expiries, instrument search |
| 13 | What FYERS can't replace? | **Instrument search-by-query** (bulk files only) and **unattended daily auth** |
| 14 | Still to decide? | §28 — PIN handling, refresh test, seconds retention, symbol universe |
