# SYSTEM_BRAIN.md — Groww Trading System

> **Living documentation.** Every claim is labelled with its evidence source and verification date.
> A stale entry is worse than a missing one — update the body, don't just append a changelog.
> See the *Change Protocol* appendix for the rules.
>
> **Generated:** 2026-09-29 from branch `lock-screen-and-startup-fixes` (commit 1364f77 + uncommitted).
> **Verified by:** 4 independent read-only verifier agents, 2026-09-27/28.

---

## CLAUDE START HERE

### What is this system?

A **personal Indian-equity algorithmic trading system** — one user, one server, one database.
It watches ~67 NSE stocks, collects 5-second candles, trains ML models (XGBoost for cash equities,
GradientBoosting currently disabled), and auto-trades in paper mode via Groww's SDK. A Flask
backend (`app.py`, 8,217 lines) serves a vanilla-JS dashboard (`index.html`, 18,343 lines) over
HTTPS on port 8000. PostgreSQL (`grow_trading_bot`, ~22 GB, ~70.8M rows across 35 logical tables +
32 yearly `fyers_candles` partitions) is the durable store.

### Architecture at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│                        DASHBOARD (index.html)                   │
│   Lock screen → PIN → Vanilla JS SPA, 53 timers, ~441 functions│
│   Connects via api() with X-Requested-With + session cookie     │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTPS :8000
┌────────────────────────▼────────────────────────────────────────┐
│                      FLASK (app.py)                              │
│   187 route decorators · 2-layer auth (account session + PIN)    │
│   14 background threads at startup · @idempotent on money paths  │
│   _PUBLIC_PATHS allowlist · X-Requested-With gate on mutations   │
├─────────────────────────────────────────────────────────────────┤
│ SCHEDULER (scheduler.py)          │ BOT (bot.py)                │
│ 31 registered tasks               │ Cash auto_trade pipeline    │
│ ~15s dispatch loop                │ Paper/live gate (fail-closed)│
│ DB-overridable intervals          │ XGB signal → Groww order    │
│ Market-hours + warm-up gates      │                             │
├───────────────────────────────────┼─────────────────────────────┤
│ FNO_TRADER (fno_trader.py)        │ TRAILING_STOP               │
│ F&O auto_trade pipeline           │ check_and_close_trades_on_loss│
│ NIFTY/BANKNIFTY options           │ paper_trades.json ← source  │
│ Capital ledger (paper only)       │ of truth for open trades     │
├───────────────────────────────────┴─────────────────────────────┤
│ MARKET DATA                                                      │
│ FYERS: candles, quotes, historical │ Groww: orders, positions    │
│ Token-bucket rate limiter          │ Index quotes (6 indices)    │
│ 10 req/s, 200/min, 100k/day       │ No rate limiter             │
│ 3 breaches/day = account blocked   │                             │
├─────────────────────────────────────────────────────────────────┤
│ INTELLIGENCE                                                     │
│ news_sentiment · research_engine · auto_analyzer · tijori        │
│ cost_scraper · commodity_tracker · fii_tracker · auto_metadata   │
├─────────────────────────────────────────────────────────────────┤
│ ML MODELS                                                        │
│ XGBoost (cash, ACTIVE) · GBC (cash, DISABLED by config flag)     │
│ F&O model (XGBoost, active for F&O signals)                      │
├─────────────────────────────────────────────────────────────────┤
│ POSTGRESQL (grow_trading_bot, ~22 GB)                            │
│ 35 logical tables + 32 fyers_candles partitions (~70.8M rows)    │
│ + paper_trades.json / trade_journal.json (file-based mirrors)    │
│ 220 config_settings rows · memoized 30s via get_config()         │
└─────────────────────────────────────────────────────────────────┘
```

### The 10 things most likely to break

1. **FYERS rate limit** — 3 per-minute breaches in a day blocks the account for the rest of that day.
   Every FYERS call must go through `fyers_client._request()` which enforces a token-bucket limiter.
   The literal fallback rate must stay under the documented limit (currently 2.5/sec = 150/min).

2. **Paper/live gate** — `is_paper_mode()` must fail CLOSED (return True = paper on error).
   Currently correct in `bot.py`, but 13 other readers parse `paper_trading` with `.lower()=="true"`
   which disagrees with the engine's parser for edge-case values. A missing config row defaults to
   LIVE (the `get_config` default is `"false"`).

3. **Idempotency guard is INERT** — The ORM model has a `content_type` column not present in the
   live `idempotency_keys` table. Every claim INSERT fails and falls open. `migrate_idempotency.py`
   has never been run. Money-path requests go through unprotected.

4. **F&O trailing stop can never fire** — The peak price is only written when `ltp > peak_price`,
   but `peak_price` defaults to current LTP, so it's never stored. DB has 0 `fno_peak:*` rows.

5. **Scheduler restarts re-run everything** — `last_run` is in-memory only. Every restart triggers
   the ~25-min GBC retrain, cost scraper, and all other tasks immediately.

6. **trade_log schema drift** — The live table schema doesn't match the ORM model. Every INSERT
   fails silently at DEBUG level. The in-memory `_trade_log` is lost on every restart.

7. **XSS in news rendering** — 6 confirmed innerHTML sinks at `index.html:9204,9360,9412,9424,
   9563,10099` render `${x.title}` and `href="${a.url}"` unescaped. Mitigated by single-user + PIN,
   but news titles come from RSS feeds.

8. **Client-supplied prices mutate stop state** — `POST /api/update-trailing-stops` takes
   `{prices:{symbol:price}}` from the browser and feeds them into the trailing-stop ratchet.
   A bad client price can arm a stop that the auto-closer then acts on.

9. **`to_fyers_symbol()` is an N+1 query** — Opens a session and SELECTs `master_ticker_table` per
   symbol. With 67 symbols, makes 67 queries before the 2 FYERS calls, every ~15s XGB scan.

10. **Weekday GBC retrains fail for ALL symbols** — `days=1` fetches a trailing 24h window. On
    weekdays that's at most 75 five-minute bars, always below the 100-row minimum. GBC models
    refresh only on weekend/holiday runs.

### Current system state (LAST VERIFIED: 2026-09-29)

| Dimension | Value | Source |
|---|---|---|
| Active stocks | 67 | `SELECT count(*) FROM stocks WHERE is_active` |
| Database size | ~22 GB | `pg_database_size` |
| fyers_candles rows | ~70.8M across 32 partitions | `sum(reltuples)` |
| Config settings | 220 rows | `count(*)` |
| Paper mode | ACTIVE | `get_config("paper_trading")` |
| XGB cash model | ENABLED | `model.xgb_cash_enabled=true` |
| GBC cash model | DISABLED | `model.gbc_cash_enabled=false` |
| FYERS WebSocket | DISABLED | `fyers.ws_enabled=false`, `set_symbols()` has 0 callers |
| Open paper trades | 0 | `paper_trades.json` |
| trade_journal rows | 26 | DB `count(*)` |
| Scheduler tasks | 31 registered (+ 1 orphan DB row `collect_5min_candles`) |

---

## Cross-cutting maps

### Who Uses What — External Services

| Service | Provider | Used By | Purpose | Rate Limit | Cost |
|---|---|---|---|---|---|
| FYERS Data API | FYERS | fyers_client, fyers_market_data_provider, candle_collector, self_healing | Candles, quotes, historical data | 10/s, 200/min, 100k/day (Standard) | Free tier |
| FYERS Auth | FYERS | fyers_auth | OAuth token refresh | Same pool | — |
| Groww SDK | Groww | bot.py, fno_trader.py, price_fetcher.py | Order execution, positions, holdings, index quotes | No documented limiter | Free |
| Tijori Finance | Tijori | tijori_collector | Financials, supply chain, promoter data | Self-imposed 6s delay | Subscription |
| Google News RSS | Google | news_sentiment | News headlines (15 feeds + 23 queries) | None enforced | Free |
| Alpha Vantage | Alpha Vantage | research_engine | Analyst ratings, fundamentals | 5/min, 500/day (free) | Free tier |
| Telegram Bot API | Telegram | telegram_commander, alert functions, google_auth | Commands, alerts, daily summaries | 30 msg/s | Free |
| Google OAuth | Google | google_auth (untracked) | Account-layer sign-in | — | Free |
| Yahoo Finance | yfinance | research_engine | Peer analysis, institutional holders | Undocumented | Free |
| Groww website | Groww | cost_scraper | Scrape buy price/charges | Self-imposed delay | Free (scraping) |

### Where Is It Used — Config Keys (selected critical)

| Key | Read By | Default | Live Value | Sensitivity |
|---|---|---|---|---|
| `paper_trading` | bot.py:1286, app.py:5853/6552/6631, scheduler, telegram (13 sites) | `"false"` (= LIVE) | `true` | **CRITICAL** — missing row = LIVE |
| `model.xgb_cash_enabled` | bot.py | `"false"` | `true` | Controls real-money trading |
| `model.gbc_cash_enabled` | bot.py | `"false"` | `false` | — |
| `fyers.rate_per_sec` | fyers_client._acquire_token | 2.5 (literal) | 2.5 (DB) | Rate limiter; wrong value → account blocked |
| `fyers.ws_enabled` | app.py:926 | `"false"` | `false` | WebSocket toggle (disabled) |
| `auth.session.idle_timeout_minutes` | auth_session | 30 | 30 | — |
| `auth.session.absolute_timeout_hours` | auth_session | 12 | 12 | — |
| `idempotency.require_key` | app.py | 0 | 0 | 0 = keyless requests pass unprotected |

### When Does It Run — Scheduler Tasks (top 15)

| Task | Interval (DB override) | Market-hours gate | What it does |
|---|---|---|---|
| `cash_auto_trade` | 5s (→ ~15s actual) | 09:20-15:15 | XGB scan → paper/live trade → trailing-stop updates |
| `fno_auto_trade` | 5s (→ ~15s actual) | 09:20-15:15 | F&O signal scan → option selection → paper/live order |
| `auto_close_trades` | 5s (DB: 300s) | 09:20-15:15 | `check_and_close_trades_on_loss` |
| `record_pnl` | 5s (→ ~15s actual) | 09:20-15:15 | PnL snapshot to DB |
| `collect_candles` | 5s (→ ~15s actual) | 09:15-15:35 | 5-second candles from FYERS |
| `token_refresh` | 3600s | None | Groww `check_and_refresh()` |
| `fyers_token_refresh` | 3600s | None | FYERS `refresh_if_needed()` |
| `fyers_daily_topup` | 3600s | Outside market hours | `topup_daily` historical backfill |
| `self_healing` | 3600s | None | Detect/fill candle gaps |
| `retrain_models` | 86400s | None | GBC retrain (~25 min) |
| `retrain_xgb_daily` | 86400s | None | XGB cash retrain (~4 min) |
| `retrain_fno_model` | 86400s | None | F&O XGB retrain (~31 min) |
| `cost_scraper` | 3888000s (45 days) | None | Scrape Groww buy prices |
| `telegram_summary` | 1800s | None | EOD Telegram summary |
| `market_intelligence` | 900s | None | News + research collection |

**Dispatch reality:** The scheduler loop sleeps 15s between passes (`scheduler.py:1291`), so no
task runs more frequently than ~15s regardless of its registered interval. The registered 5s
interval for trading tasks is effectively a "run every dispatch cycle" marker.

### Data Flow — Critical Paths

**Price Collection:**
```
FYERS API → fyers_client._request() [rate-limited]
  → candle_collector.collect_candles() [every ~15s, 09:15-15:35]
  → INSERT fyers_candles (partitioned by year)
  → self_healing backfill [hourly, fills gaps]
```

**Cash Trade Pipeline:**
```
scheduler ~15s → bot.auto_trade()
  → XGB predict (all 67 symbols, batched quotes via get_ltp_batch)
  → Signal filter (confidence, cost, capital, duplicate, exposure)
  → is_paper_mode() check [fail-closed]
  → Paper: _paper_trade() → paper_trades.json + trade_journal
  → Live: groww.place_order() → trade_journal DB
```

**F&O Trade Pipeline:**
```
scheduler ~15s → fno_trader.auto_trade()
  → F&O XGB predict (NIFTY/BANKNIFTY)
  → Option selection (ATM ± strikes)
  → is_paper_mode() check
  → Paper: fno_paper_trade → fno_paper_trades.json
  → Live: groww.place_order() → capital ledger update
```

**Exit/Close Pipeline:**
```
scheduler 300s → check_and_close_trades_on_loss()
  → Read paper_trades.json (flock)
  → For each OPEN trade: check stop-loss, trailing stop, hard floor
  → Close if triggered → write paper_trades.json + trade_journal
  
ALSO: dashboard ~5s → POST /api/auto-close/check (same function)
ALSO: auto_trade ~15s → monitor_and_update_trailing_stops (ratchets only, cannot close)
```

### Source of Truth

| Data | Source of Truth | Copies / Caches | Divergence Risk |
|---|---|---|---|
| Open paper trades | `paper_trades.json` (flock) | `paper_trades` DB table (4 rows, EOD summary only) | DB has 4 rows vs 26 JSON — EOD summary under-reports |
| Trade history | `trade_journal` DB table (26 rows) | `trade_journal.json` (file mirror) | Generally in sync |
| Candle data | `fyers_candles` partitioned table | None | — |
| Config | `config_settings` DB table (220 rows) | `get_config()` 30s memo cache | Cache lag ≤30s |
| ML models | `.joblib` files on disk | In-memory after load | Stale file ≠ stale model in memory |
| Stock metadata | `stocks` DB table | Various caches (sector, commodity, etc.) | — |
| Auth sessions | `_sessions` in-memory dict in `auth_session.py` | SHA-256 hashes + 30s touch cache | Memory-only; lost on restart |
| PIN hash | `pin_hash.txt` file | — | — |
| F&O capital | `fno.capital` / `fno.used_capital` config keys | In-memory during trade cycle | Potential double-count in live mode |

### Rate Limits & Quotas

| Service | Limit | Enforced By | Consequence of Breach |
|---|---|---|---|
| FYERS Data API | 10 req/s, 200/min (Standard), 100k/day | `fyers_client._acquire_token` (token bucket) | **3 breaches/day → account blocked for rest of day** |
| FYERS literal fallback | 2.5/sec, burst 5 → worst case 7.5/1s, 155/min | Code literal if DB config missing | Must stay under 200/min |
| Alpha Vantage | 5/min, 500/day (free tier) | `research_engine` delay | 429 → skip |
| Telegram Bot | 30 msg/s | None in code | Rate limit error |
| Groww SDK | Undocumented | None in code | Unknown |
| Tijori | Self-imposed 6s between requests (live DB value) | `time.sleep(delay)` | — |

### Failure & Fallback Map

| Component | Failure Mode | Behaviour | Classification |
|---|---|---|---|
| `is_paper_mode()` | DB exception | Returns `True` (paper) | **FAIL-CLOSED** ✓ |
| `is_paper_mode()` | Missing `paper_trading` row | Returns `"false"` → LIVE | **FAIL-OPEN** ✗ |
| `_count_open_positions()` | Broker API failure | Returns `0` (was the old bug) | Currently returns `None`; callers refuse to act |
| FYERS rate limiter | Missing DB config | Uses literal fallback (2.5/sec) | ✓ (under cap) |
| Idempotency guard | Missing `content_type` column | Every claim fails → falls OPEN | **FAIL-OPEN** ✗ (guard inert) |
| Auth session load | Redis/memory error | Returns `None` → 401 | **FAIL-CLOSED** ✓ |
| `paper_trades.json` read | File locked/missing | `check_and_close` returns without acting | **FAIL-CLOSED** ✓ |
| Cost scraper | Groww page change | 7/9 values hardcoded, regex never runs | Silently wrong |
| GBC retrain | Weekday insufficient data | Logs warning, keeps stale model | Stale model served |
| Trailing stop | `update_trailing_stop` exception | Logged, trade stays open | Trade may miss exit |

### Database — Schema Drift (verified 2026-09-28)

| Table | ORM Model | Live Schema | Impact |
|---|---|---|---|
| `trade_log` | side, order_id, price, quantity, ..., created_at | action, timestamp (only) | Every INSERT fails silently; in-memory log lost on restart |
| `idempotency_keys` | includes `content_type` | Missing `content_type` | Idempotency guard is inert — claims always fail open |

### Dangerous Areas — Do Not Touch Without Reading

1. **Lock-screen intro animation** (`index.html`) — PROTECTED in CLAUDE.md with 7 invariants.
   Never remove, hide, disable, or shorten. If it glitches, fix the cause.

2. **Paper/live gate** (`bot.py:is_paper_mode`) — The difference between simulation and real money.
   13 other sites parse the config value differently.

3. **FYERS rate limiter** (`fyers_client.py`) — Account blocked for the day on 3 breaches.
   Every FYERS call must go through `_request()`.

4. **`paper_trades.json` writers** — Multiple concurrent writers (tracker, trailing_stop,
   auto-closer, dashboard). The flock/merge protocol prevents data loss but stale-overwrite
   race exists between concurrent readers.

5. **Scheduler task intervals** — DB-overridable via `scheduler_interval_<task>`. A wrong interval
   on a trading task (< 5s floor enforced in code) could machine-gun orders.

6. **`start-all.sh --stop`** — The ONLY safe way to restart. Raw `nohup python3 app.py &` skips
   PID cleanup and port sweep. Always verify with `lsof -nP -iTCP:8000 -sTCP:LISTEN`.

---

## API Endpoints — app.py part A (lines 1–2800)

Repo: `/Users/parthsharma/Desktop/Grow/app.py`. This section covers module-level setup
(imports, static allow-list, session/CSRF/CORS gates, PIN unlock/lockout, idempotency
decorator, startup config seeding) and every `@app.route` in lines 1–2800.
LAST VERIFIED: 2026-09-27. Evidence labelled per COMMON_RULES.md.

Full range 1-2800 now read. Live DB values checked (`psql`, read-only, LAST VERIFIED 2026-09-27):
`fyers.ws_enabled = false` (updated 2026-09-10), `auth.landing_enabled = false` (updated 2026-09-22),
`idempotency.require_key = 0` (updated 2026-08-11). Frontend-consumer greps run against
`index.html` / `landing.html` (login.html/setup.html exist but are the legacy JWT UI — see below).

### Module-level setup

| Component | Where | What / Why | Status |
|---|---|---|---|
| colorama neutralisation | app.py:33-37 | `colorama.init = lambda:...` before `import bot` pulls in growwapi, which otherwise stacks AnsiToWin32 stdout wrappers on every GrowwAPI client rebuild until `RecursionError`. Must run before growwapi import (binds `init` at import time). | ACTIVE — VERIFIED FROM CODE |
| Log rotation | app.py:101-136 | `RotatingFileHandler` → `~/Library/Logs/ParthS/app.log`, 20MB × 5 backups = 120MB ceiling. `StreamHandler` added only if `sys.stdout.isatty()` (avoids doubling lines under launchd, which separately redirects raw stdout to `raw.log`). Root logger catches werkzeug's per-request access log (propagates, no handler of its own). | ACTIVE |
| `get_pg_conn()` | app.py:150-167 | Context-manager for raw psycopg2 connections; always closes. Reads `DB_URL` via `os.getenv("DB_URL")` directly (not `config.DB_URL` import). | Used by several handlers below |
| `app = Flask(...)` | app.py:169 | `static_folder="."`, `static_url_path=""` — serves **every file in the project root** over HTTP by default (history: `GET /.env` once returned 200 with a live `GROWW_API_KEY`). | ACTIVE |
| `_PUBLIC_STATIC_FILES` / `_block_project_file_exposure` | app.py:185-203 (`@app.before_request`) | Allow-list (not deny-list): `manifest.json, apple-touch-icon.png, icon-192.png, icon-512.png, favicon.ico, deck.pdf`. Anything else through Flask's `static` endpoint → 404. | ACTIVE, security-critical |
| `_PUBLIC_PATHS` / `_ACCOUNT_ONLY_PATHS` / `_require_session` | app.py:221-252 (`@app.before_request`) | Deny-by-default session gate. Public: `/`, `/api/unlock`, `/api/session`, `/api/auth/providers`, `/api/auth/google/start`, `/api/auth/google/callback`, `/fyers_callback`. Account-only (no PIN needed): `/api/logout`. Service/loopback calls (`auth_session.is_service_call`) bypass entirely, `g.service_call=True`. Else: `/api/*` needs `pin_ok`; pages need only a live account session; otherwise 401 `{"error":"locked"}` for API paths or redirect `/` for pages. | ACTIVE, security-critical |
| CORS | app.py:255-269 | `ALLOWED_ORIGINS` env var (comma list) else defaults to `localhost:{FLASK_PORT}`, `127.0.0.1:{FLASK_PORT}`, `localhost:3000`, `127.0.0.1:3000` (Next.js frontend under `frontend/` — likely unused/legacy since the shipped dashboard is `index.html`). `CORS(app, origins=ALLOWED_ORIGINS)`. | ACTIVE |
| `_block_cross_origin_mutations` | app.py:285-291, 437-475 (`@app.before_request`) | For any non-safe method (not GET/HEAD/OPTIONS) except `/api/unlock`: Origin (or Referer fallback) must be in `ALLOWED_ORIGINS`, else 403. Then, unless `g.service_call`, requires `X-Requested-With` header, else 401. This is what CLAUDE.md operational rule #6 (`check_raw_fetch.py`) exists to enforce client-side. | ACTIVE, security-critical |
| `_device_token_is_valid()` / `APP_DEVICE_TOKEN` | app.py:294-299, 431-434 | Comment explicitly states this is "the previous model ... no longer consulted" — superseded by the session-cookie gate. Function still defined; **no call site found in any source file (0 callers, verifier-confirmed; `scheduler.py:17` imports the constant but never uses it)**. The `APP_DEVICE_TOKEN` env value itself is NOT dead: `unlock()` returns 500 if it is unset (app.py:333), so it is no longer consulted for auth but must still be set for `/api/unlock` to work. | `_device_token_is_valid()` DEAD (0 callers) — VERIFIED FROM CODE; `APP_DEVICE_TOKEN` env still REQUIRED by `unlock()` |
| Unlock rate limiter | app.py:301-329 | In-memory `_unlock_attempts` dict, IP→timestamps. 5 failures / 2 min window → 429 with `Retry-After` (**UNCOMMITTED**: committed HEAD has `_UNLOCK_WINDOW_SECONDS = 15 * 60`, i.e. 5 failures / 15 min; the 2-min window at app.py:301-303 is a working-tree edit. The running Flask process — PID 36337, started 2026-09-28 22:02:03 — runs the working-tree 5 / 120 s value). Not persisted — resets on process restart; not shared across workers (single-process Flask, so fine as deployed). | ACTIVE |
| `clamp_arg(name, default, maximum, minimum=1)` | app.py:501-520 | Bounds an int query param into `[minimum,maximum]`, falls back to default on non-numeric input. Implements CLAUDE.md standard #2 ("bound every read that can grow"). | Helper, used by several read endpoints |
| `_normalize_config_value` | app.py:532-573 | Type-checks a config write against the **existing** value's type: if old value was `true`/`false`, only accepts flag words; if old value was numeric, requires a finite number. Prevents e.g. a trailing space silently changing `paper_trading` semantics. | Used by `POST /api/config` |
| `require_finite_positive` | app.py:576-604 | Rejects `None`, bool, non-numeric, NaN/Infinity, and (unless `allow_zero`) ≤0. Closes a real hole: bare `float()` accepts `NaN`/`Infinity` JSON literals, which make `>`/`<` capital-checks always `False`. | **Used only once, in `fno_buy` (app.py:3245)** — verifier-confirmed. NOT applied to `/api/close-trade` (bare `float()` + `<= 0`, so NaN/Infinity exit prices pass) nor to `journal_close`. |
| `idempotent(scope)` decorator | app.py:607-753 | Wraps money-path endpoints. Reads `Idempotency-Key` header; if absent, behaves exactly as before unless `idempotency.require_key` config (default `"0"`) is `"1"`. Claims key via `db_manager.claim_idempotency_key`; REPLAY returns the stored response verbatim; IN_FLIGHT→409; MISMATCH (same key, different body hash)→422; on handler exception the key is left `in_flight` deliberately (broker may already have the order) rather than marked failed/re-claimable. Non-2xx responses are still stored as terminal (order-placing routes call the broker before returning 4xx). | ACTIVE. Seen applied to: `close_trade` (app.py:1261) |
| `SafeJSONProvider` | app.py:760-779 | Recursively replaces `NaN`/`Infinity` floats with `null` before JSON encoding (raw `NaN` is invalid JSON). | ACTIVE, applies to all responses |
| Startup seeding (module-level, runs at import) | app.py:781-950 | Sequence, each wrapped in its own try/except (non-fatal): `token_refresher.check_and_refresh()` (Groww token) → DB init (`get_db`, `seed_stocks`) → `costs.seed_cost_rates()` → `trade_journal.reconcile_with_tracker()` (self-heals journal vs tracker mismatches after a crash) → prediction weight seed (`prediction.weight.ml=0.40/trend=0.15/news=0.20/context=0.25`) → per-model paper caps (`paper.cap.gradientboosting=50000`, `paper.cap.xgboost=50000`, `paper.min_confidence=0.50`) → F&O capital seed **+ live call** `fno_trader.sync_capital_from_groww()` (hits Groww API at every app startup) → `auto_metadata.seed_fno_config()` → `tijori_collector.seed_tijori_config()` → batched Settings-key seed (one `get_configs()` call, not a loop — CLAUDE.md standard #1 compliant) covering `fno_auto_trade_enabled`, `lock.colour.1/2/3` (the PROTECTED lock-screen intro colours), `close_trade.max_price_divergence_pct=20`, `idempotency.require_key=0`, `idempotency.retention_hours=48`, `telegram_cost_notifications=true`, `news.cache_ttl_seconds=600`, `news.source.{google,newsapi,et_rss,moneycontrol,extra_rss,x_posts}=true`, `fyers.ws_*` (`ws_enabled=true` default, `ws_freshness_seconds=2`, `ws_watchlist_poll_seconds=60`, `ws_reconnect_retry=10`, `ws_backoff_max_seconds=300`, `ws_stall_seconds=60`). **All seeds are "if not already present" — the seeded literal is only what a *fresh* row gets, not necessarily today's live value.** | See DB verification below |
| Config editing guard-rail sets | app.py:1987-2015 | `_CONFIG_HIDDEN_PREFIXES` (`tijori.last_collected.*`, `earnings.last_qrev.*`, `tijori.onboarded.*` — internal state, hidden from Settings UI). `_CONFIG_READONLY_KEYS` (`tijori.backfill_status`, `fno.used_capital`, `portfolio_reviewed`). `_CONFIG_SENSITIVE_KEYS = {"telegram_bot_token"}` (masked in UI). `_CONFIG_DEAD_KEYS` (app.py:2007-2015) — a set of **lowercase** `cost.*` keys plus `cash_autotrade_enabled`, explicitly documented as unread (superseded by lowercase JSON-valued twins written by `cost_updater.py`), kept visible-hidden rather than deleted. The 11 UPPERCASE `cost.*` keys that `costs.py` actually reads (`cost.BROKERAGE_PER_ORDER`, `cost.GST_PCT`, `cost.STT_DELIVERY_PCT`, …; costs.py:26-38,51) all exist live in `config_settings` and are NOT in this set, so they are editable. | Read by `GET/POST /api/config` |

### Endpoint summary table

| METHOD | PATH | handler:line | auth | side effects | consumers | status |
|---|---|---|---|---|---|---|
| POST | /api/unlock | unlock:331 | public (rate-limited) | creates/rotates session cookie | index.html PIN pad | ACTIVE |
| GET | /api/session | session_status:376 | public | none | index.html boot check | ACTIVE |
| POST | /api/logout | logout:401 | account-only | revokes session cookie | index.html logout button | ACTIVE |
| POST | /api/session/verify | session_verify:411 | needs pin_ok | none | **NO CALLER FOUND** (0 references in any source file; the boot check uses GET `/api/session`, index.html:4421, 11915) | LEGACY STUB, UNCALLED |
| GET | / | index:967 | public | none | browser root | ACTIVE |
| GET | /app | dashboard_app:997 | account session | none | redirect target after landing sign-in | ACTIVE (depends on `auth.landing_enabled`, default off) |
| GET | /api/auth/providers | auth_providers:1004 | public | none | landing.html | ACTIVE |
| GET | /api/auth/google/start | google_start:1031 | public | sets FLOW_COOKIE, redirects to Google | landing.html "Sign in with Google" | ACTIVE if configured |
| GET | /api/auth/google/callback | google_callback:1043 | public | creates account session | Google OAuth redirect target | ACTIVE if configured |
| GET | /login | login_page:1070 | **blocked by session gate** (page, not public, needs account session) | none | UNCLEAR — see note | LIKELY DEAD |
| GET | /dashboard | dashboard:1076 | `@require_auth` (JWT) **+** session gate | none | none found in range | LEGACY — no in-app callers; reachable with any live account session (JWT-forgeable) |
| GET | /setup | setup:1086 | `@require_auth` (JWT) **+** session gate | none | none found in range | LEGACY — no in-app callers; reachable with any live account session (JWT-forgeable) |
| POST | /api/auth/signup | api_signup:1095 | `/api/*` blocked by `_require_session` (not in `_PUBLIC_PATHS`) | creates `User` row, JWT | none found | LEGACY — no callers; unreachable without a PIN session, but reachable (JWT-forgeable) once PIN-unlocked or with the service token — see JWT note |
| POST | /api/auth/login | api_login:1121 | same as above | none (auth check) | none found | LEGACY — no callers; unreachable without a PIN session, but reachable (JWT-forgeable) once PIN-unlocked or with the service token — see JWT note |
| GET | /api/auth/google | api_google_oauth:1146 | same as above | none | none found — legacy, superseded by `/api/auth/google/start` | LIKELY DEAD |
| GET | /api/auth/verify | api_verify:1163 | `@require_auth` + session gate | none | none found | LEGACY — no callers; unreachable without a PIN session, but reachable (JWT-forgeable) once PIN-unlocked or with the service token — see JWT note |
| GET | /api/auth/profile | api_profile:1173 | `@require_auth` + session gate | none | none found | LEGACY — no callers; unreachable without a PIN session, but reachable (JWT-forgeable) once PIN-unlocked or with the service token — see JWT note |
| POST | /api/auth/set-api-key | api_set_api_key:1186 | `@require_auth` + session gate | writes `groww_api_key`/secret to `User` row | none found | LEGACY — no callers; reachable once PIN-unlocked or with the service token (JWT-forgeable via the fallback secret) — security-relevant |
| POST | /api/auth/demo | api_demo:1207 | public but env-gated (`ALLOW_DEMO_LOGIN`) — still hits session gate first | creates demo `User` row via a **separate** raw SQLAlchemy engine (bypasses `db_manager`) | none found | DISABLED by default |
| POST | /api/close-trade | api_close_trade:1260 | session (pin_ok) + idempotent("close_trade") | **writes** `paper_trades.json`, `trade_journal.json`, DB `paper_trades`+`trade_journal` | index.html manual close button (grep pending) | ACTIVE, MONEY PATH |
| POST | /api/token/refresh | refresh_token_endpoint:1350 | session | refreshes Groww access token (external) | **NO CALLER FOUND** (0 references; the frontend uses `/api/refresh-token`, index.html:9285) | POSSIBLY DEAD / manual-only (the underlying `check_and_refresh()` is scheduler-driven) |
| GET | /api/token/status | token_status:1365 | session | may call Groww API (`get_user_profile`) as fallback | **NO CALLER FOUND** (0 references outside app.py) | POSSIBLY DEAD / manual-only |
| GET | /api/predict/<symbol> | predict:1421 | session | none | index.html:11637 | ACTIVE |
| GET | /api/scan | scan:1431 | session | none | index.html:6669 | ACTIVE |
| POST | /api/train/<symbol> | train:1441 | session | trains + (in bot.py, out of scope) likely saves model artifact | **NO CALLER FOUND** in index.html/scheduler.py/telegram_commander.py | POSSIBLY DEAD / manual-only |
| GET | /api/news/<symbol> | news:1453 | session | none | **NO CALLER FOUND** (grep `api/news/` empty in index.html; world-news tab uses `/api/world-news` instead) | POSSIBLY DEAD / manual-only |
| GET | /api/market-sentiment | market_sentiment:1464 | session | none | index.html:9327,13684 | ACTIVE |
| GET | /api/world-news | world_news:1475 | session | none, bounded (`limit`≤200, `days`≤30) | world news tab (grep pending exact line, feature confirmed via `/api/world-news/collect` sibling) | ACTIVE |
| POST | /api/world-news/collect | world_news_collect:1492 | session | background thread scrapes RSS/news sources | index.html:9594 | ACTIVE |
| GET | /api/deep-analysis/<symbol> | deep_analysis_stock:1511 | session | none | index.html:8475,11201 | ACTIVE |
| GET | /api/deep-analysis/portfolio | deep_analysis_portfolio:1523 | session | calls Groww (`bot.get_holdings`) | **NO CALLER FOUND** in index.html | POSSIBLY DEAD / manual-only |
| GET | /api/deep-analysis/watchlist | deep_analysis_watchlist:1548 | session | raw psycopg2 read of `stock_prices` (unbounded `SELECT DISTINCT symbol`, small cardinality) | index.html:11047 | ACTIVE |
| GET | /api/intelligence/<symbol> | market_intelligence:1578 | session | may write peer-comparison cache on-demand | index.html:8233 | ACTIVE |
| POST | /api/intelligence/<symbol>/collect | collect_intelligence:1610 | session | force scrape (sync, in-request) | index.html:8462 | ACTIVE |
| POST | /api/intelligence/collect-all | collect_all_intelligence:1623 | session | background thread scrapes entire watchlist | **NO CALLER FOUND** | POSSIBLY DEAD / manual-only |
| POST | /api/metadata/refresh | refresh_all_metadata:1643 | session | background thread scrapes Screener.in for all stocks | **NO CALLER FOUND** | POSSIBLY DEAD / manual-only |
| POST | /api/metadata/<symbol>/refresh | refresh_stock_metadata:1661 | session | sync scrape of Screener.in | **NO CALLER FOUND** | POSSIBLY DEAD / manual-only |
| GET | /api/metadata/status | metadata_status:1673 | session | none | **NO CALLER FOUND** | POSSIBLY DEAD / manual-only |
| GET | /api/research/<symbol> | research_stock:1708 | session | may write cached report if `?refresh=1` | research tab (leaderboard/all confirmed; per-symbol grep pending) | ACTIVE |
| POST | /api/research/<symbol>/refresh | research_stock_refresh:1724 | session | sync full research generation | index.html:13933, 14423 (`api(\`/api/research/${sym}/refresh\`, POST)`) | ACTIVE |
| GET | /api/research/leaderboard | research_leaderboard:1736 | session | none | index.html:13967 | ACTIVE |
| POST | /api/research/all | research_all:1756 | session | background thread, research on all stocks | index.html:13944 | ACTIVE |
| POST | /api/watchlist/refresh-prices | refresh_watchlist_prices:1774 | session | background thread; **mutates process env var `_FORCE_BACKFILL`** then pops it — the race concern is moot: the underlying `_task_update_watchlist_prices` is registered hourly (scheduler.py:1309) but has been **DISABLED since 2026-08-15** (its body, scheduler.py:192-320, is a docstring + `return`), and `_FORCE_BACKFILL` is read only in commented-out code (scheduler.py:224) — so both the task and this endpoint are no-ops | **NO CALLER FOUND** in index.html/scheduler.py/telegram_commander.py | POSSIBLY DEAD / manual-only; no-op (the task it targets is disabled) |
| GET | /api/raw-materials | raw_materials:1795 | session | sequential external calls per commodity (price + news + X posts) in a loop — not parallelized | index.html:10202 | ACTIVE, perf risk (CLAUDE.md standard #3) |
| GET | /api/raw-materials/supply-chain | raw_materials_supply_chain:1879 | session | reads `CommoditySnapshot`, `DisruptionEvent` tables | index.html:9615,9656,9685 | ACTIVE |
| POST | /api/supply-chain/refresh | supply_chain_refresh:1966 | session | background thread, external collection | index.html:9651 | ACTIVE |
| GET | /api/config | list_config:2018 | session | none, masks `telegram_bot_token` | index.html:5231,5657 (Settings tab) | ACTIVE |
| POST | /api/config | update_config:2053 | session | **writes** `config_settings`; reloads `costs` rates if key starts `cost.` (branch app.py:2088-2093 IS reachable — it is the working path for editing the 11 live uppercase `cost.*` rates; see note) | index.html:5328,5494,5514 | ACTIVE |
| GET | /api/risk-parameters | risk_parameters:2131 | session | none, read-only | index.html:5617 | ACTIVE |
| GET | /api/self-healing | self_healing_status:2279 | session | none | **NO CALLER FOUND** | POSSIBLY DEAD / manual-only |
| POST | /api/self-healing/run | self_healing_run:2295 | session | triggers repair actions (writes depend on self_healing.py, out of scope) | **NO CALLER FOUND** | POSSIBLY DEAD / manual-only |
| GET | /api/fyers-token-status | fyers_token_status:2306 | session | none | index.html:8706 | ACTIVE |
| GET | /fyers_callback | fyers_callback:2342 | **public** | exchanges auth_code for FYERS token, **writes token to `.env`** (per comment) | FYERS OAuth redirect_uri; referenced in index.html:8565,8612 (paste-back instructions) | ACTIVE, security-relevant |
| POST | /api/fyers/complete-login | fyers_complete_login:2379 | session | same token exchange (paste-back), parses `auth_code=` from pasted URL/text, rejects if `len(code)<20` or contains a space | index.html:8686 (Data Coverage panel "paste code") | ACTIVE |
| GET | /api/data-health | data_health:2419-2839 | session | none — read-only, but expensive multi-part aggregation (see detailed entry) | index.html:8494 | ACTIVE |
| GET | /api/tijori/backfill-status | tijori_backfill_status:2842 (decorator) | — | — | — | **OUT OF SCOPE** — decorator line is past 2800; body continues past this section's boundary, hand off to part B |

### Detailed entries — non-trivial (write/trade/delete/external/security)

#### `unlock` — POST /api/unlock
| Field | Detail |
|---|---|
| Where | app.py:331-373 |
| What / Why | Only way to obtain a session cookie. Fails closed (500) if `APP_PIN_HASH`/`APP_DEVICE_TOKEN` unset. |
| Auth | Public, but rate-limited: 5 failures / 2 min per IP → 429 + `Retry-After` (the 2-min window is an uncommitted working-tree edit; committed HEAD is 15 min — see the rate-limiter row above). |
| Inputs | JSON body `{pin}`. Hashed with unsalted `sha256` (app.py:342), compared to `APP_PIN_HASH` (env, `config.py`) with `!=` (app.py:344) — not a constant-time comparison. |
| Outputs / side effects | On success: revokes any existing cookie, creates a **new** session (`auth_session.create`/`promote`) — session-fixation defence (OWASP: renew ID on privilege change). Sets cookie via `auth_session.set_cookie`. |
| DB tables | via `auth_session` module (out of scope, not read directly here) |
| Failure behaviour | Wrong PIN → logs warning, 401 (or 429 if that failure trips the limiter); PIN not configured → 500 "App lock is not configured". |
| Security | CSRF-exempted deliberately (`_block_cross_origin_mutations` allows `/api/unlock` through) — "this IS how a client proves it knows the PIN". |
| Status | ACTIVE |

#### `api_close_trade` — POST /api/close-trade
| Field | Detail |
|---|---|
| Where | app.py:1260-1343 |
| What / Why | Manually close a trade at a client-supplied exit price. |
| Auth | session (pin_ok) + `@idempotent("close_trade")` |
| Inputs | JSON `{trade_id, symbol, exit_price}`; `exit_price` is checked only with a bare `float()` and `<= 0` (app.py:1274-1284): JSON `NaN`/`Infinity` parse (Flask uses `json.loads`) and pass (`NaN <= 0` is False), and the price-divergence check below also silently passes for NaN (app.py:1293-1302), so NaN/Infinity exit prices are accepted and recorded. `require_finite_positive` (app.py:576) is not used here. |
| Outputs / side effects | Compares `exit_price` to live price via `paper_trader.get_live_price`; if divergence > `close_trade.max_price_divergence_pct` (config, default 20) — **warns only, does not block** — logged as `logger.error("SUSPECT CLOSE PRICE...")`. Calls `PaperTradeTracker().close_trade(...)` → per CLAUDE.md rule #2, this writes **four** stores (`paper_trades.json`, `trade_journal.json`, DB `paper_trades` + `trade_journal`). |
| DB tables | `paper_trades`, `trade_journal` (written, via paper_trader.py — not read directly in this file) |
| Failure behaviour | Missing params → 400; trade not found → 404; unhandled exception → 500 with `logger.exception`. |
| Security | This is exactly the write path CLAUDE.md operational rule #2 says never to exercise against live data during testing. |
| Idempotency | Yes — `Idempotency-Key` header replay-safe. Required only if `idempotency.require_key` config is `1` (default `0`, i.e. **not yet enforced**). |
| Status | ACTIVE, MONEY PATH |

#### `fyers_callback` — GET /fyers_callback
| Field | Detail |
|---|---|
| Where | app.py:2342-2376 |
| What / Why | OAuth redirect_uri registered with FYERS; completes token exchange after human SEBI-mandated login. |
| Auth | Public (in `_PUBLIC_PATHS`) — necessarily, since the browser lands here before any session exists in the FYERS-login context. |
| Inputs | Query params `auth_code` or `code`. |
| Outputs / side effects | Calls `fyers_auth.complete_login(request.url)` (external FYERS token exchange) — per module comment elsewhere in the file, "the token lands in .env automatically", i.e. **writes to the `.env` file** on disk. Returns an HTML confirmation page that auto-closes. |
| External services | FYERS OAuth token endpoint. |
| Failure behaviour | No `auth_code` → 400 HTML; exchange exception → 500 HTML with the raw exception text `{e}` interpolated into the page (minor info-leak to whoever completes the OAuth redirect — low severity since only the person doing the FYERS login sees it, but note it echoes exception internals). |
| Status | ACTIVE, security-relevant (writes secrets to disk) |

#### `update_config` — POST /api/config
| Field | Detail |
|---|---|
| Where | app.py:2053-2106 |
| What / Why | The only way to edit `config_settings` from the UI. |
| Auth | session |
| Inputs | JSON `{key, value}`. |
| Validation | Rejects hidden-prefix/readonly/dead keys (403); rejects unknown keys not already in the table (404); `_normalize_config_value` enforces type continuity with the existing value. |
| Outputs / side effects | `set_config(key, normalized)` — DB write to `config_settings`. If `key` starts with `"cost."`, also calls `costs.reload_rates()` so the in-memory cache picks it up without a restart. |
| **`cost.*` reload (verified reachable)** | The `if key.startswith("cost."): costs.reload_rates()` branch (app.py:2088-2093) IS reachable and is the working path for editing the live cost rates: `costs.py:26-38,51` reads 11 UPPERCASE keys (`cost.BROKERAGE_PER_ORDER`, `cost.GST_PCT`, `cost.STT_DELIVERY_PCT`, …), all of which exist live in `config_settings` and none of which are in `_CONFIG_DEAD_KEYS` (app.py:2007-2015 lists the lowercase twins only). VERIFIED by the independent verifier, 2026-09-27/28. |
| Security | Sensitive keys (`telegram_bot_token`) never round-trip their real value — resubmitting the mask (`••••••••`) is a no-op rather than overwriting the live token with literal bullets. |
| Status | ACTIVE |

#### `data_health` — GET /api/data-health
| Field | Detail |
|---|---|
| Where | app.py:2419-2839 |
| What / Why | Single aggregated coverage/freshness panel for every dataset the dashboard depends on (CLAUDE.md standard #7 "missing data must be visible"), explicitly built after `/api/data-health` once timed out at ~190s from an unbounded `count(DISTINCT symbol)` over `fyers_candles` (~60M rows / 32 partitions) — fixed via `EXISTS` probes + a `ts` bound for partition pruning + a 300s cache (`_fyers_coverage_cached`, app.py:2236-2276). |
| Checks performed | (1) company supply-chain data coverage vs the `stock_prices` universe; (2) partner-name → NSE symbol match rate; (3) matched-partner performance-data coverage; (4) external slug-resolver success rate; (5) daily price-data freshness (`MAX(date)` from `stock_prices`); (6) Master Ticker Table directory coverage (FYERS-resolved vs Tijori-resolved sub-bars — Tijori sub-bar deliberately tagged `info`, not alarmed, because it "only ever grows" and isn't a completeness metric); (7) FYERS historical candle backfill coverage per resolution (D/1/5S), cached; (8) ML model training coverage+freshness for GBC cash, XGB cash, and F&O XGB (reads `models/` dir mtimes + live `training_progress.snapshot()`); (9) FYERS live WebSocket status (`fyers_ws_client.status()` — capped at `warn`, never `critical`, because "nothing prices off it yet"); (10) trade-store agreement between the paper-trade tracker file and the `trade_journal` DB table (catches the exact drift class described in the surrounding comment: a wrong-arg-list call to `close_matching_paper_trade()` silently desynced 25/26 closes for months). |
| DB tables | reads `stock_prices`, `company_external_data` (via `CompanyExternalData`), `company_connections`, `external_slug_map`, `master_ticker` (via `MasterTicker`), `trade_journal` (via `TradeJournalEntry`) |
| External/other | `fyers_ws_client.status()` (in-process client state, not a live network call here); reads `paper_trade_reconciliation.load_tracker_trades()` (JSON file) |
| Outputs | `{generated_at, overall_status, issues, training_active, checks:[...]}`; each check isolated in its own try/except so one failing sub-check cannot take down the whole panel |
| Failure behaviour | Top-level catch returns `{"overall_status":"unknown", "error":...}` with HTTP 200 (never 500) — a monitoring endpoint that itself needs monitoring stays visible rather than erroring out |
| Consumer | index.html:8494 |
| Status | ACTIVE |

### Cross-cutting facts (for the maps)

**External services + endpoints**
- Groww API: token refresh/status (`token_refresher`), holdings (`bot.get_holdings`), F&O capital sync (`fno_trader.sync_capital_from_groww()` — called at **every app startup**, app.py:862-864), user profile as a token-validity fallback (`GrowwAPI.get_user_profile`, app.py:1407-1409).
- FYERS: OAuth token exchange (`fyers_auth.complete_login`, both via `/fyers_callback` and the paste-back `/api/fyers/complete-login`), token expiry check (`fyers_auth.token_expiry`), live WebSocket (`fyers_ws_client`, module exists and is seeded default-on but **live-verified OFF**, see below).
- Screener.in: `auto_metadata` (stock metadata scrape).
- News: Google News RSS, NewsAPI, ET RSS, Moneycontrol RSS, extra RSS feeds, X/Twitter (`news_sentiment` module; each individually toggleable via `news.source.*` config).
- Google OAuth: `google_auth` module. The landing-page button is gated by `auth.provider.google` (via `/api/auth/providers`), but the OAuth flow itself (`/api/auth/google/start|callback`, both public) is gated only by `.env` credentials (`google_auth.configured()`) and the `auth.allowed_emails` allow-list — `google_start` does NOT check the flag (app.py:1031-1040).
- Tijori: `tijori_collector` (supply-chain/company data).
- Commodity prices: `commodity_tracker.fetch_commodity_price` — provider not identified within app.py; **UNKNOWN — NOT DETERMINABLE FROM app.py** (verify in commodity_tracker.py).
- Screener/Tijori/commodity/news calls inside `GET /api/raw-materials` (app.py:1795-1876) run **sequentially in a per-commodity loop** (price fetch, then Google News, then X posts) — a CLAUDE.md standard #3 violation candidate (not parallelized with ThreadPoolExecutor).

**Env vars read (name — where — sensitivity)**
- `DB_URL` — app.py:157 (`get_pg_conn`), and via `config.DB_URL` import — not sensitive to name, value is a DB connection string (secret).
- `ALLOWED_ORIGINS` — app.py:266 — not sensitive (just origin list).
- `ALLOW_DEMO_LOGIN` — app.py:1215 — not sensitive; gates `/api/auth/demo`, default off.
- `GROWW_ACCESS_TOKEN` — app.py:1375 — **secret, not recorded**.
- `_FORCE_BACKFILL` — app.py:1784-1786 — internal signalling var set/unset around a background thread call, not user-facing config. Read only in commented-out code (scheduler.py:224) since the watchlist-price task was disabled on 2026-08-15, so it currently has no effect.
- `APP_PIN_HASH`, `APP_DEVICE_TOKEN` — via `config.py` import — **secret, not recorded** (PIN hash / device token).

**config_settings keys read/written in this range**
- Seeded at startup (app.py:781-944, "if absent" only): `fno_auto_trade_enabled` (true), `lock.colour.1/2/3` (navy/olive/wine hexes — feeds the PROTECTED lock-screen intro), `close_trade.max_price_divergence_pct` (20), `idempotency.require_key` (0), `idempotency.retention_hours` (48), `telegram_cost_notifications` (true), `news.cache_ttl_seconds` (600), `news.source.{google,newsapi,et_rss,moneycontrol,extra_rss,x_posts}` (all true), `fyers.ws_enabled` (true default) + `ws_freshness_seconds/ws_watchlist_poll_seconds/ws_reconnect_retry/ws_backoff_max_seconds/ws_stall_seconds`, `prediction.weight.{ml,trend,news,context}`, `paper.cap.{gradientboosting,xgboost}`, `paper.min_confidence`, `fno.capital`, `fno.used_capital`.
- Read elsewhere in range: `auth.landing_enabled` (index.html routing), `auth.provider.{google,apple,email}` (auth_providers endpoint).
- Written via `POST /api/config`: any key already present and not in `_CONFIG_HIDDEN_PREFIXES`/`_CONFIG_READONLY_KEYS`/`_CONFIG_DEAD_KEYS`.
- **LIVE VALUES (VERIFIED FROM DATABASE, `psql`, LAST VERIFIED 2026-09-27):** `fyers.ws_enabled = false` (updated 2026-09-10) — the seed default is `true` but the live row was explicitly overridden false; the FYERS WebSocket described in `data_health`'s check #9 is **currently disabled**, consistent with COMMON_RULES.md's own illustrative example. `auth.landing_enabled = false` (updated 2026-09-22) — so `GET /` currently always serves the dashboard directly (app.py:987-988 `_dashboard_page()` branch), meaning `landing.html`, `/api/auth/providers`, `/api/auth/google/start|callback` are **reachable but not currently exercised** in normal use. `idempotency.require_key = 0` (updated 2026-08-11) — `Idempotency-Key` is accepted but not yet required on `/api/close-trade`.

**DB tables read/written (this range)**
- Read: `stock_prices`, `company_external_data`, `company_connections`, `external_slug_map`, `master_ticker`, `config_settings`, `commodity_snapshots` (`CommoditySnapshot`), `disruption_events` (`DisruptionEvent`), `trade_journal` (`TradeJournalEntry`), plus whatever `get_all_stocks()` reads (stocks table).
- Written: `config_settings` (`POST /api/config`, plus all the startup seeds), `paper_trades` + `trade_journal` (`POST /api/close-trade`, via `PaperTradeTracker`), `idempotency_keys` (via the `idempotent` decorator's `claim_idempotency_key`/`complete_idempotency_key`, table name not confirmed in this file — in `db_manager.py`, out of scope), `users` table (legacy `/api/auth/signup|demo`, no callers; unreachable without the PIN session but reachable post-PIN — see the JWT correction below).

**Every timed/triggered execution touched by this range**
- App startup (import time): token refresh, DB init + seeds, `fno_trader.sync_capital_from_groww()` (live Groww call), trade-journal reconciliation.
- Every request: `_block_project_file_exposure`, `_require_session`, `_block_cross_origin_mutations` (before_request hooks); `_release_db_session` (teardown).
- On-demand/background-thread (fired by a POST, not scheduled): world-news collect, intelligence collect(-all), metadata refresh(-all), research refresh/all, watchlist refresh-prices (now a no-op — see the endpoint row), supply-chain refresh, self-healing run.
- Polled by the dashboard (interval owned by index.html, not this file): `/api/data-health`, `/api/session`, `/api/fyers-token-status` — data_health has a coarse `_FY_COVERAGE_TTL=300` cache to stay cheap under polling.

**Rate limits & quotas**
- Unlock PIN attempts: 5 per 2 minutes per IP (in-memory, resets on restart) → 429 + `Retry-After`. UNCOMMITTED: committed HEAD is 5 per 15 minutes; the 2-min window is a working-tree edit, and the running process (PID 36337, started 2026-09-28 22:02:03) uses 5 / 120 s.
- No app.py-level rate limit on any other endpoint in this range (external API rate limits, e.g. FYERS, live in the called modules — out of scope for this file).

**Cost drivers**
- `fno_trader.sync_capital_from_groww()` at every process start — a Groww API call on every restart.
- `research_all`, `metadata refresh(-all)`, `intelligence collect-all`, `world_news_collect`, `supply_chain_refresh` — each spins an unbounded background thread hitting external services for the whole watchlist; no visible concurrency cap or de-dupe against an already-running pass in app.py itself (would need checking the called modules for their own guards — out of scope).

**Data flows (INPUT → TRANSFORM → STORAGE → CONSUMER), notable ones**
- PIN (client) → sha256 compare → `auth_session` cookie → gates all subsequent requests → dashboard.
- Client exit_price (close-trade) → bare `float()` + `<= 0` check (NaN/Infinity pass) → compared to live price (warn-only) → `PaperTradeTracker.close_trade()` → 4 stores (`paper_trades.json`, `trade_journal.json`, DB `paper_trades`, DB `trade_journal`) → Trade Journal tab + P&L.
- FYERS OAuth code (browser redirect or pasted text) → `fyers_auth.complete_login()` → token exchange → **written to `.env`** → read back by `fyers_auth`/`fyers_client` for subsequent API calls.
- Settings edit (client) → `_normalize_config_value` (type-continuity check) → `config_settings` row → for `cost.*` keys, triggers `costs.reload_rates()` (the branch is reachable — the 11 live uppercase cost keys are editable).

**Failure modes (fail-open / fail-closed)**
- Fail-closed (correct): `unlock()` when `APP_PIN_HASH`/`APP_DEVICE_TOKEN` unset → 500, never "any PIN works" (app.py:333-335). `_require_session` denies by default. `_block_project_file_exposure` denies by default (allow-list).
- Fail-open (deliberate, documented): CSRF guard treats a request with **no** Origin/Referer as a legitimate non-browser caller (curl, scheduler, Telegram) — correct for the loopback model but means any local process can still mutate state without a session cookie's `pin_ok`... except `_require_session` still runs first and would 401 it unless it's a recognized service call (`auth_session.is_service_call`) — so this is layered, not a real gap, but worth a future reviewer double-checking `is_service_call`'s own criteria (in `auth_session.py`, out of scope here).
- `data_health()`: every individual check wrapped so one failure can't crash the whole panel; overall endpoint never 500s to the client meaningfully (returns 200 with `overall_status: unknown` on total failure).
- `close_trade`'s idempotency wrapper leaves a key `in_flight` (not `failed`) on an unhandled exception, deliberately preventing an automatic retry from double-ordering — a stuck `in_flight` key requires the retention-window prune (`idempotency.retention_hours`, default 48h) to clear.

**Dead / legacy / retired code found in this range**
- **Legacy, no callers (VERIFIED FROM CODE — comment + no caller); NOT structurally unreachable — see the correction at the end of this bullet**: the entire JWT-based multi-user auth system — `/login` (app.py:1070), `/dashboard` (app.py:1076, `@require_auth`), `/setup` (app.py:1086, `@require_auth`), `/api/auth/signup` (1095), `/api/auth/login` (1121), `/api/auth/google` legacy GET (1146), `/api/auth/verify` (1163), `/api/auth/profile` (1173), `/api/auth/set-api-key` (1186), `/api/auth/demo` (1207, also env-gated off by default). Evidence: (a) none of these paths appear in `_PUBLIC_PATHS`/`_ACCOUNT_ONLY_PATHS`, so `_require_session` blocks every one of them for any caller without the PIN-session cookie the JWT flow doesn't issue; (b) grep of `index.html`/`landing.html` finds **zero** calls to any of `/dashboard`, `/setup`, `/api/auth/signup`, `/api/auth/login`; (c) index.html:18310-18311 says outright: *"This used to clear localStorage.auth_token and redirect to /login (the multi-user auth page, still a stub)."* — the app's own comment calls it a stub. Matches memory note "multi-tenancy phase plan — Phase 0 done, Phases 1-2 on hold." **Correction (verifier):** `@require_auth` is on exactly 5 routes — `/dashboard` (1077), `/setup` (1087), `/api/auth/verify` (1164), `/api/auth/profile` (1174), `/api/auth/set-api-key` (1187) — and none of them is in `_PUBLIC_PATHS`; `_require_session` (app.py:227-252) runs first. So no request reaches them without (a) a PIN-verified session cookie (API paths) / any live account session (page paths), or (b) a loopback call carrying the in-memory per-process `X-Service-Token`. With such a session they ARE reachable, and a JWT signed with the fallback literal (auth_manager.py:18; `JWT_SECRET` is absent from the `.env` names and from the launchd plist) would pass `require_auth`. `/api/auth/signup`, `/api/auth/login`, `/login` and `/api/auth/demo` (403 unless `ALLOW_DEMO_LOGIN`) are likewise reachable post-PIN. Forging a JWT adds only the ability to act as another `users` row (1 row live, no `groww_api_key`; `User.groww_api_key` is read nowhere outside these routes) — anyone already PIN-unlocked or holding the service token already has everything.
- `_device_token_is_valid()` (app.py:431-434) and module-level `APP_DEVICE_TOKEN` check — comment at app.py:294-299 states it is "the previous model ... no longer consulted"; 0 callers in any source file (`scheduler.py:17` imports the constant but never uses it). The `APP_DEVICE_TOKEN` env value itself is still required: `unlock()` returns 500 if it is unset (app.py:333).
- Likely-dead HTTP endpoints (no frontend or scheduler/telegram caller found by grep, though their underlying functions may be invoked directly elsewhere): `POST /api/train/<symbol>`, `GET /api/news/<symbol>`, `GET /api/deep-analysis/portfolio`, `POST /api/intelligence/collect-all`, `POST /api/metadata/refresh`, `POST /api/metadata/<symbol>/refresh`, `GET /api/metadata/status`, `POST /api/watchlist/refresh-prices` (the task it targets, `_task_update_watchlist_prices`, is registered hourly but DISABLED since 2026-08-15 — its body is a docstring + `return` — so the endpoint is a no-op), `GET /api/self-healing`, `POST /api/self-healing/run`, `POST /api/session/verify` (legacy stub, 0 references), `GET /api/token/status` (0 references outside app.py), `POST /api/token/refresh` (underlying `check_and_refresh()` IS called at startup and by scheduler.py:698 directly). These may simply be manual/dev-console endpoints (curl-only) rather than truly dead — flagged as "possibly dead" per COMMON_RULES, not asserted dead.

**Contradictions between code, config, comments or docs**
1. `fyers.ws_enabled` seed default is `"true"` (app.py:920-922, "if absent") but the live DB row is `false` (verified). Not a bug — just means the seed's literal default no longer describes the running system; a reader trusting the seed block alone would wrongly conclude the WebSocket is on.
2. The legacy JWT auth system's routes are simultaneously present, partially still linked-to in comments/dead code (`/login` string literals), and self-documented as "still a stub" — i.e. the code has not been cleaned up even though the team already knows it is retired (matches the multi-tenancy-phase-plan memory: Phase 0 done, 1-2 on hold, so this is expected, not a surprise). They are not "structurally unreachable" though: unreachable without the PIN session, but reachable (and JWT-forgeable via the fallback secret) once PIN-unlocked or with the service token — see the correction in the dead-code list above.

**Open unknowns**
- Commodity price provider behind `commodity_tracker.fetch_commodity_price` — UNKNOWN — NOT DETERMINABLE FROM app.py.
- `idempotency_keys` table name/schema — referenced only via `db_manager` functions, not confirmed directly in this file.
- Whether the "possibly dead" endpoints listed above are called by any external tool (curl scripts, cron, a browser bookmark) outside this repo — NOT DETERMINABLE FROM CODE.

## API Endpoints — app.py part B (lines 2800–5600)

Overview: this range covers Tijori data-health, core trading (buy/sell/auto-trade/trailing-stop monitor),
portfolio (holdings/positions/orders/margin), token refresh, cost calculators, the full F&O (futures &
options) module (dashboard, buy/sell, backtesting, auto-trade), intraday paper-trading, watchlist CRUD +
deep analysis, live price/quote, trade journal, portfolio analysis/review, two parallel personal-thesis
systems, and price-fetch/read utilities. **78 `@app.route` decorators** enumerated via
`/usr/bin/grep -n "^@app.route" app.py` **VERIFIED FROM CODE** (2026-09-27).

Global gates apply to every path below unless noted: `_require_session` (app.py:229) requires a
PIN-verified session cookie on every `/api/*` path not in `_PUBLIC_PATHS` (app.py:221) — none of this
range's 78 paths are public, so every one 401s `{"error":"locked"}` without a valid session, or accepts a
loopback call carrying `auth_session.SERVICE_TOKEN` (app.py:240, `is_service_call`). `_block_cross_origin_mutations`
(app.py:437) requires an allowed Origin/Referer + `X-Requested-With` header (or the service-token loopback)
on every non-GET/HEAD/OPTIONS request, else 403/401. `@idempotent(scope)` (app.py:632) adds replay-safe
dedup keyed on an `Idempotency-Key` header — enforced only if `config_settings.idempotency.require_key=1`
(app.py:625-629, default `"0"`), else optional — a caller that omits the header gets **no** dedup protection
even on money-moving routes that carry the decorator.

**Frontend-consumer method**: `/usr/bin/grep -n "<path>" index.html landing.html login.html setup.html
telegram_commander.py scheduler.py`, several quoting styles per path (`'`,`"`,backtick, raw `fetch(API + ...)`).
telegram_commander.py makes **zero** HTTP calls into this app (only to `api.telegram.org`) — it calls
`bot.py`/`fno_trader.py` functions directly in-process. scheduler.py makes exactly two HTTP loopback calls
in the whole file (`/api/live-prices` and `/api/paper-trading/build-daily-snapshots-with-candles`, both
**outside** this range) — every other scheduler trading action (`bot.auto_trade()`, `fno_trader.auto_trade_fno()`,
`trailing_stop.check_and_close_trades_on_loss`) calls the function directly, not through this range's HTTP
endpoints. So `/api/auto-trade`, `/api/monitor-trailing-stops` and `/api/fno/auto-trade/run` are **manual/UI
triggers only** (`/api/auto-trade` and `/api/fno/auto-trade/run` run the same underlying function the scheduler independently calls on its own timer; `/api/monitor-trailing-stops` runs `bot.monitor_and_update_trailing_stops()`, which the scheduler reaches through `bot.auto_trade()` and Telegram calls directly — it is not `trailing_stop.check_and_close_trades_on_loss`, which belongs to `/api/auto-close/check` and the `auto_close_trades` task).

### Summary table

| METHOD | PATH | handler:line | auth | side effects | consumers | status |
|---|---|---|---|---|---|---|
| GET | /api/tijori/backfill-status | tijori_backfill_status:2843 | session | none (reads) | index.html:7277,11904 | ACTIVE |
| GET | /api/supply-chain-intel/<symbol> | supply_chain_intel:2928 | session | none (reads DB, Tijori snapshots) | index.html:8905,11030 | ACTIVE |
| POST | /api/supply-chain-intel/<symbol>/refresh | supply_chain_intel_refresh:2939 | session+CSRF | starts bg thread `tijori_collector.onboard_symbol` (external Tijori scrape) | **no caller found** | DEAD/orphan — see note |
| GET | /api/stock/<symbol>/news-detail | stock_news_detail:2957 | session | none (reads + live Google-News fetch) | index.html:9441 | ACTIVE |
| POST | /api/auto-trade | auto_trade:3008 | session+CSRF | **MONEY**: `bot.auto_trade()` — cash equity order(s) | **no caller found** (scheduler calls `bot.auto_trade()` directly instead) | DEAD as HTTP path; `@idempotent("auto_trade")` unused in practice |
| POST | /api/monitor-trailing-stops | monitor_trailing_stops:3018 | session+CSRF | **MONEY**: updates/exits trailing stops via `bot.monitor_and_update_trailing_stops()` (app.py:3021) | **no caller found** (the scheduler reaches that same function through `bot.auto_trade()` — bot.py:2056, `cash_auto_trade` task, 5 s — and Telegram calls it directly, telegram_commander.py:1088; `trailing_stop.check_and_close_trades_on_loss` is a different function, used by `/api/auto-close/check` and the `auto_close_trades` task) | DEAD as HTTP path; no @idempotent |
| POST | /api/buy | buy:3030 | session+CSRF | **MONEY**: `bot.place_buy` | call site exists but is unreachable: index.html:6872 `quickBuy` (sends an Idempotency-Key); its only button (index.html:6728-6729) is rendered into `_el('predictions-body')`, an element that no longer exists (`_DEAD_UI_SINK`, index.html:6627-6645, 6677, 6750), so it never reaches the DOM | UNREACHABLE from the current UI (removed predictions table); `@idempotent("buy")` |
| POST | /api/sell | sell:3046 | session+CSRF | **MONEY**: `bot.place_sell` | call site exists but is unreachable: index.html:6893 `quickSell` (sends an Idempotency-Key); its only button (index.html:6728-6729) is rendered into `_el('predictions-body')`, an element that no longer exists (`_DEAD_UI_SINK`, index.html:6627-6645, 6677, 6750), so it never reaches the DOM | UNREACHABLE from the current UI (removed predictions table); `@idempotent("sell")` |
| GET | /api/holdings | holdings:3063 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/positions | positions:3071 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/orders | orders:3079 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/margin | margin:3087 | session | none | index.html:9233 | ACTIVE |
| POST | /api/refresh-token | api_refresh_token:3095 | session+CSRF | refreshes Groww token via `token_refresher.refresh_token()` | index.html:9285 (comment at 8563 notes it's "disabled for SEBI [reasons]" now that FYERS is the data source) | ACTIVE but noted as functionally moot |
| GET | /api/trade-log | trade_log:3111 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/costs/<symbol> | cost_estimate:3116 | session | none (calc only) | **no caller found** | DEAD/orphan |
| POST | /api/net-profit | net_profit:3136 | session+CSRF | none (calc only) | **no caller found** | DEAD/orphan |
| GET | /api/fno/dashboard | fno_dashboard:3157 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/fno/instruments | fno_instruments:3167 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/fno/expiries/<instrument> | fno_expiries:3173 | session | none | index.html:12175,12204 — only inside F&O-selector code that cannot run live (required DOM ids are missing; see the F&O UI reachability note) | EFFECTIVELY UNCALLED from the live UI |
| GET | /api/fno/option-chain/<instrument>/<expiry> | fno_option_chain:3183 | session | none | call site exists but is unreachable: index.html:12319 `fnoLoadChain`, never invoked | UNREACHABLE from the current UI |
| GET | /api/fno/affordable/<instrument>/<expiry> | fno_affordable:3193 | session | none | call site exists but is unreachable: index.html:12273 `fnoFindAffordable`, reached only via shadowed/dead code and it needs `#fno-expiry`, which does not exist | UNREACHABLE from the current UI |
| GET | /api/fno/analyze/<instrument> | fno_analyze:3203 | session | none | index.html:12205 (inside the shadowed F&O-selector code; see the F&O UI reachability note) | EFFECTIVELY UNCALLED from the live UI |
| GET | /api/fno/best-opportunity | fno_best_opportunity:3213 | session | none (scans NIFTY/BANKNIFTY/FINNIFTY) | index.html:12105,13617 (13617 is the live caller) | ACTIVE |
| POST | /api/fno/buy | fno_buy:3236 | session+CSRF | **MONEY**: `fno_trader.place_fno_buy` (option buy) | index.html:12361 (`fnoBuyOption` — its only button is in the affordable table, which never renders) | EFFECTIVELY UNCALLED from the live UI; `@idempotent("fno_buy")`; validates premium via `require_finite_positive` |
| POST | /api/fno/sell | fno_sell:3260 | session+CSRF | **MONEY**: `fno_trader.place_fno_sell` (close position) | index.html:12399 (`fnoSellPosition`, reached only via the EXIT button rendered by the shadowed `intradayLoadDashboard` at 12011-12099, which never runs) | EFFECTIVELY UNCALLED from the live UI; `@idempotent("fno_sell")` |
| GET | /api/fno/positions | fno_positions:3278 | session | none | index.html:12032,13522 (13522 is live; 12032 is inside the shadowed `intradayLoadDashboard`) | ACTIVE |
| GET | /api/fno/margin | fno_margin:3287 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/fno/trades | fno_trades:3296 | session | none | index.html:12032 (inside the shadowed `intradayLoadDashboard`, which never runs) | EFFECTIVELY UNCALLED from the live UI |
| GET | /api/fno/capital | fno_capital:3305 | session | none | index.html:12030,13466,13521 (13466 and 13521 are live; 12030 is inside the shadowed `intradayLoadDashboard`) | ACTIVE |
| POST | /api/fno/costs | fno_costs:3315 | session+CSRF | none (calc only) | **no caller found** | DEAD/orphan |
| GET | /api/fno/rules | fno_rules:3332 | session | none (returns constant `fno_trader.FNO_RULES`) | index.html:12033 (inside the shadowed `intradayLoadDashboard`, which never runs) | EFFECTIVELY UNCALLED from the live UI |
| GET | /api/fno/technicals/<instrument> | fno_technicals:3338 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/fno/oi/<instrument> | fno_oi:3348 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/fno/global-indices | fno_global_indices:3361 | session | none (external index fetch) | index.html:12428 (`fnoRefreshGlobal`, reached only from the shadowed dashboard/selector code) | EFFECTIVELY UNCALLED from the live UI |
| POST | /api/fno/auto-trade/run | fno_auto_trade_run:3373 | session+CSRF | **MONEY**: one F&O auto-trade cycle | index.html:13449 (manual "run once" button; scheduler calls `fno_trader.auto_trade_fno()` directly, separately, every 5s) | ACTIVE (manual trigger); `@idempotent("fno_auto_trade_run")` |
| GET | /api/fno/auto-trade/log | fno_auto_trade_log:3384 | session | none | index.html:13480,13898 | ACTIVE |
| GET,POST | /api/fno/auto-trade/config | fno_auto_trade_config:3393 | session (+CSRF on POST) | POST writes auto-trade config in-process (not `config_settings` — see `fno_trader._AUTO_TRADE_CONFIG`) | **no caller found** | DEAD/orphan |
| POST | /api/intraday/enter-paper | intraday_enter_paper:3408 | session+CSRF | writes `TradeJournalEntry` (OPEN, is_paper=True) at real market price | index.html:13742 | ACTIVE; `@idempotent(...)`; paper only, no broker call |
| POST | /api/intraday/close-paper | intraday_close_paper:3482 | session+CSRF | updates `TradeJournalEntry` to CLOSED, computes P&L | index.html:13797 | ACTIVE; `@idempotent(...)` |
| POST | /api/intraday/auto-trade-run-paper | intraday_auto_trade_run_paper:3555 | session+CSRF | writes paper `TradeJournalEntry`; gated by `bot._check_capital_cap_allows_trade` | index.html:13852 (dispatched when paper mode is on, in place of `/api/fno/auto-trade/run`) | ACTIVE; `@idempotent(...)` |
| GET | /api/intraday/trades | intraday_trades:3654 | session | none (today's paper trades only) | index.html:13523 | ACTIVE |
| GET,POST | /api/fno/sync-capital | fno_sync_capital:3705 | session (+CSRF on POST) | writes `config_settings` fno.capital/fno.used_capital from Groww (only when the Groww fetch returns `capital`, app.py:3716-3717) | index.html:13880 (called as POST) | ACTIVE; **GET also mutates config** — a GET with side effects, breaks HTTP semantics/caching assumptions; the CSRF guard skips GET and the session cookie is SameSite=Lax, so a cross-site top-level GET link would trigger it in a PIN-unlocked browser |
| GET | /api/signals/tomorrow | get_tomorrow_signals:3740 | session | none | **no caller found** | DEAD/orphan |
| POST | /api/fno/backtest/run | fno_backtest_run:3771 | session+CSRF | none (single-day backtest sim) | index.html:12984 | ACTIVE |
| POST | /api/cash/backtest/run | cash_backtest_run:3786 | session+CSRF | none (~60s walk-forward backtest) | index.html:12660 | ACTIVE |
| GET | /api/cash/backtest/dates/<symbol> | cash_backtest_dates:3810 | session | none; `limit` clamped to 250 | index.html:12629 | ACTIVE |
| GET | /api/fno/backtest/dates/<instrument> | fno_backtest_dates:3821 | session | none | index.html:12530 (raw `fetch`, not `api()` — GET only, no CSRF risk) | ACTIVE |
| POST | /api/fno/backtest/multi | fno_backtest_multi:3831 | session+CSRF | none; `num_days` clamped to 20 | index.html:13394 | ACTIVE |
| GET | /api/fno/backtest/instruments | fno_backtest_instruments:3846 | session | none | index.html:12475 (raw `fetch`) | ACTIVE |
| GET | /api/watchlist | get_watchlist:3878 | session | none (reads `stocks` LEFT JOIN `fyers_candles`) | index.html:6916,7017,9315,12599 | ACTIVE |
| POST | /api/watchlist/add | add_to_watchlist:3946 | session+CSRF | inserts/reactivates `Stock` row; bg thread: metadata, market_intelligence, Tijori onboarding, FYERS backfill (~64 calls, deferred if market open), model (re)training | index.html:7003 | ACTIVE; no @idempotent |
| GET | /api/watchlist/<symbol>/footprint | watchlist_footprint:4174 | session | none (dry-run of what removal deletes) | index.html:7127 | ACTIVE |
| DELETE | /api/watchlist/remove/<symbol> | remove_from_watchlist:4190 | session+CSRF | **DELETES DATA** across many tables + model files + caches; kept: trade_journal/paper_trades/theses; 409 if the symbol has an open tracker trade or any OPEN `trade_journal` row (paper or actual), or if a trade store is unreadable (fail-closed; symbol_purge.py:108-129) | index.html:7147 | ACTIVE — see detail below |
| POST | /api/watchlist/<symbol>/note | save_watchlist_note:4272 | session+CSRF | writes `WatchlistNote` row + `watchlist_notes.json` backup file | index.html:8215 | ACTIVE |
| GET | /api/watchlist/<symbol>/analysis | watchlist_stock_analysis:4281 | session | none (reads, 90s ThreadPoolExecutor(1) timeout wrapper — the timeout does not free the request thread, see detail); fans out 6 providers via `ThreadPoolExecutor(max_workers=6)` | index.html:8038,11012 | ACTIVE — see detail below |
| GET | /api/live-price/<symbol> | live_price:4822 | session | none | **no caller found** (frontend uses the plural `/api/live-prices` POST endpoint, outside this range) | DEAD — superseded by a different endpoint |
| GET | /api/quote/<symbol> | quote:4831 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/journal | journal_all:5030 | session | none; attaches cached/filtered candles per entry | index.html:10305,10321 | ACTIVE |
| GET | /api/journal/stats | journal_stats:5064 | session | none | index.html:10312 | ACTIVE |
| GET | /api/journal/open | journal_open:5071 | session | none | index.html:10306,10625 | ACTIVE |
| GET | /api/journal/closed | journal_closed:5078 | session | none | index.html:10307 | ACTIVE |
| GET | /api/journal/<trade_id> | journal_entry:5085 | session | none | **NO CALLER FOUND** (resolved by the verifier: only `/api/journal/${tradeId}/close`, index.html:10594, exists) | UNCALLED |
| POST | /api/journal/<trade_id>/close | journal_close:5110 | session+CSRF | **MONEY**: closes a trade — tracker path (`PaperTradeTracker.close_trade`) for paper positions, else `trade_journal.close_trade_report` (the same function every automatic exit uses) | index.html:10594 | ACTIVE; `@idempotent("journal_close")`; no `exit_price` validation (see detail) |
| GET | /api/portfolio-analysis | portfolio_analysis:5184 | session | none; serves from in-process cache `_pa_cache`, kicks a bg refresh thread | index.html:10660,11621,11990 | ACTIVE |
| POST | /api/portfolio-review | portfolio_review:5253 | session+CSRF | `bot.mark_portfolio_reviewed()` — unlocks auto-trade gate | index.html:10649 | ACTIVE |
| GET | /api/portfolio-review-status | portfolio_review_status:5263 | session | none | **no caller found** | DEAD/orphan |
| GET | /api/check-updates | check_updates:5269 | session | **runs `bot.analyze_portfolio()` (full AI analysis of every Groww holding) on every call**, result discarded; **hardcoded to always return `has_update: false`**, a `TODO` stub | index.html:11468/11471 (polled every 60 s) | ACTIVE call site, but the handler is an expensive stub that never reports real updates |
| GET | /api/thesis/<symbol> | get_stock_thesis:5309 | session | none (`stock_thesis` module) | **no caller found** | DEAD — superseded by /api/my-thesis |
| GET | /api/thesis | get_all_thesis:5318 | session | none | **no caller found** | DEAD |
| POST | /api/thesis | save_stock_thesis:5325 | session+CSRF | writes via `stock_thesis.add_or_update_thesis` | **no caller found** | DEAD |
| DELETE | /api/thesis/<symbol> | delete_stock_thesis:5350 | session+CSRF | deletes via `stock_thesis.delete_thesis` | **no caller found** | DEAD |
| GET | /api/my-thesis | get_my_theses:5363 | session | none (`ThesisManager`, separate module/table from `stock_thesis`) | index.html:11690 | ACTIVE |
| GET | /api/my-thesis/<symbol> | get_my_thesis:5375 | session | none | **NO CALLER FOUND** (resolved by the verifier: only `DELETE /api/my-thesis/${symbol}`, index.html:11876, exists) | UNCALLED |
| POST | /api/my-thesis | create_my_thesis:5398 | session+CSRF | writes via `ThesisManager.add_thesis` | index.html:11581 | ACTIVE |
| DELETE | /api/my-thesis/<symbol> | delete_my_thesis:5429 | session+CSRF | deletes via `ThesisManager.delete_thesis` | index.html:11876 | ACTIVE |
| GET | /api/my-thesis/<symbol>/projection | get_thesis_projection:5442 | session | none | **NO CALLER FOUND** (resolved by the verifier) | UNCALLED |
| POST | /api/prices/fetch | fetch_stock_prices:5466 | session+CSRF | bg thread: `price_fetcher.fetch_and_store_all_stocks` (legacy Groww weekly-candle path — see watchlist/add's `bg_fetch` comment: this path is largely superseded by FYERS backfill) | **no caller found** | DEAD/orphan (and calls a de-emphasized data path) |
| GET | /api/prices/<symbol> | get_stock_prices:5499 | session | none; `?period=1D/1W` aggregates 5-second FYERS candles on the fly; `days`/`limit` both clamped (days≤1825, limit≤5000) | index.html:7951,8037,11209 | ACTIVE |

### Detailed entries

#### `remove_from_watchlist` / `symbol_purge.purge_symbol` — DELETE /api/watchlist/remove/<symbol>
| Field | Detail |
|---|---|
| Where | app.py:4190-4220; logic in `symbol_purge.py` |
| What / Why | Full removal of a symbol: `purge_symbol` (symbol_purge.py:177) deletes rows in one DB transaction from `PURGE_TABLES` (symbol_purge.py:42: stocks, stock_prices, fyers_candles, candles, intraday_candles, predictions, news_articles, shareholding_patterns, peer_comparisons, company_external_data, external_slug_map, company_connections, thesis_analysis, watchlist_notes), plus matching `analysis_cache` rows (symbol_purge.py:227) and the `config_settings` key `tijori.last_collected.<symbol>` (symbol_purge.py:254), plus glob-matched model files and in-memory caches, only after commit. |
| Used by (callers) | index.html:7147 (`api('/api/watchlist/remove/${symbol}', {method:'DELETE'})`) — ACTIVE |
| Calls | `symbol_purge.open_positions` (gate), `symbol_purge.purge_symbol` |
| When | User-triggered from the watchlist UI, after `/api/watchlist/<symbol>/footprint` shows a preview |
| Inputs | `symbol` path param, uppercased, alnum+`-`/`&` validated (ValueError → 400) |
| Outputs / side effects | 200 with `{success, symbol, message, report}`; 409 `PermissionError` if `open_positions(symbol)` finds an open tracker trade or any OPEN `trade_journal` row (paper or actual), or cannot read a trade store — fail-closed (symbol_purge.py:108-129, 190-192) — the route explicitly treats closing a position as belonging to the trade flow, not this button |
| DB tables | Deletes from `PURGE_TABLES` (14 tables, symbol_purge.py:42) + `analysis_cache` + one `config_settings` row; explicitly **keeps** `trade_journal`, `paper_trades`, `trade_log`, `trade_snapshots`, `theses`, `stock_theses`, `master_ticker_table`, `nse_instruments`, `commodity_snapshots` (symbol_purge.py:62-66), and `company_connections.related_symbol` rows belonging to *other* companies (KEEP_COLUMNS, symbol_purge.py:67) |
| External services | None directly |
| Failure behaviour | Any DB failure rolls back the whole transaction (symbol_purge.py:179-184 docstring); unclassified tables (a symbol-like column found in neither PURGE_TABLES nor KEEP_TABLES) are **not touched** and reported under `unclassified` so a new table can't be silently skipped or silently purged |
| Security | CSRF-gated (DELETE is a mutating method); session-gated |
| Blast radius | Irreversible data deletion for a stock — protected by the CLAUDE.md deletion double-confirmation policy for any *code* change to this path, but the *feature itself* is designed to delete on a single confirmed UI click plus a dry-run footprint |
| Status | ACTIVE |

#### `add_to_watchlist` — POST /api/watchlist/add
| Field | Detail |
|---|---|
| Where | app.py:3946-4171 |
| What / Why | Adds a symbol to the `stocks` table (membership) synchronously, then backgrounds a multi-stage enrichment pipeline |
| Used by (callers) | index.html:7003 — ACTIVE |
| Calls | `MasterTicker` lookup (must be `instrument_type=="EQ"` and `fyers_resolution_status=="resolved"`, else 400) → `Stock` insert/reactivate → bg thread: `auto_metadata.refresh_stock_metadata`, `market_intelligence.collect_all_intelligence`, `tijori_collector.onboard_symbol`, `fyers_historical_backfill.backfill_symbol` (~64 FYERS calls, **deferred** if `fno_trader._is_market_open()` is true — recorded into `self_healing._record` so it's visible at `/api/self-healing`), then `bot.train_model` + `bot.train_xgb_model` only if backfill succeeded |
| Inputs | JSON `{symbol}` |
| Outputs / side effects | 200 `{success, message, symbol, backfill_status, market_open}`; `backfill_status` is `"deferred_market_open"` or `"running"` |
| DB tables | Writes `stocks`; downstream bg pipeline writes many more (fyers_candles, tijori tables, model artifacts on disk) |
| External services | FYERS (historical backfill), Tijori (scrape via `tijori_collector`), market_intelligence providers |
| Failure behaviour | Market-hours check failure fails toward NOT deferring (comment app.py:4009-4013: "fail toward NOT deferring" so new symbols aren't silently starved) — a fail-open choice, explicitly reasoned, distinct from the "fail closed" default elsewhere in this codebase |
| Security | CSRF-gated; no @idempotent (a double-click is separately guarded by an `IntegrityError` catch on the `Stock` insert, app.py:3985-3992) |
| Status | ACTIVE |

#### `watchlist_stock_analysis` / `_do_watchlist_analysis` — GET /api/watchlist/<symbol>/analysis
| Field | Detail |
|---|---|
| Where | app.py:4281-4818 |
| What / Why | The "should I buy this?" composite view: 5Y price stats (fyers_candles), AI prediction (`bot.get_prediction`), 6 fan-out providers in parallel (`ThreadPoolExecutor(max_workers=6)`, app.py:4447 — fundamentals, annual financials, institutional holdings, commodity impact, geopolitical news, news sentiment), a hand-rolled scoring model (app.py:4596-4710) producing a recommendation (STRONG BUY..STRONG AVOID) and a 3-tier buy zone |
| Used by (callers) | index.html:8038, 11012 — ACTIVE |
| Calls | `bot.fetch_live_price`, `bot.get_prediction`, `fundamental_analysis`, `fii_tracker`, `commodity_tracker`, `news_sentiment`, `tijori_collector.get_supply_chain_intel` |
| When | On-demand, wrapped in `ThreadPoolExecutor(max_workers=1)` with a 90s timeout (app.py:4292-4298) — on timeout it returns a 504, but that `return` sits inside the `with ThreadPoolExecutor(...)` block, whose `__exit__` calls `shutdown(wait=True)`, so the 504 is only sent after the analysis actually finishes: the 90 s timeout does not free the request thread or bound request time. (The inner 6-worker pool uses `shutdown(wait=False)`, app.py:4447-4454, and is fine.) |
| Outputs / side effects | Large JSON: price stats, recommendation, target levels, ai/fundamentals/financial_growth/institutional/commodity/geopolitical/news_headlines/price_action/note/buy_zone/supply_chain — none persisted (read-only) |
| DB tables | `fyers_candles` (bounded to 5 years, app.py:4325-4331 comment explains the bound exists because the table now holds ~29 years and an unbounded query would silently redefine "5Y" as "all-time") |
| External services | Google News (via `news_sentiment._fetch_google_news`), Tijori-backed fundamentals |
| Performance | 6-way fan-out explicitly to avoid CLAUDE.md violation #3 (sequential I/O) — each provider has its own timeout (30-45s) |
| Failure behaviour | Each of the 6 providers fails independently and is logged as a warning, degrading gracefully to partial data rather than a full 500 |
| Status | ACTIVE |

#### `journal_close` — POST /api/journal/<trade_id>/close
| Field | Detail |
|---|---|
| Where | app.py:5108-5166 |
| What / Why | Manual close of a trade, routed through the **same close paths automatic exits use** — explicitly not a separate ad hoc write (comment app.py:5154-5156 notes a prior version wrote `exit_time=utcnow()` directly with no charges/net P&L/post-trade report, mixing UTC into an IST-keeping journal) |
| Used by (callers) | index.html:10594 — ACTIVE |
| Calls | If `is_paper` and still tracked: `PaperTradeTracker.close_trade` (paper_trader.py); else `trade_journal.close_trade_report` |
| Inputs | JSON `{exit_price?, exit_reason}`; if `exit_price` omitted, falls back to `bot.fetch_live_price`. **No `exit_price` validation at all**: `if not exit_price` only catches 0/None, so negative/NaN/Infinity values are accepted. A tracker-close exception falls through to `trade_journal.close_trade_report` (app.py:5146-5160). |
| Outputs / side effects | Updates `TradeJournalEntry`/tracker state to CLOSED with computed P&L | 404 if trade not found/already closed |
| Security | `@idempotent("journal_close")` — replay-safe only if caller sends `Idempotency-Key` |
| Status | ACTIVE |

#### `/api/fno/sync-capital` — GET,POST (fno_sync_capital:3705)
| Field | Detail |
|---|---|
| Note | **GET has side effects** — both methods run the identical body, which calls `fno_trader.get_fno_account_balance()` (external Groww margin call) and writes `config_settings` keys `fno.capital`/`fno.used_capital` only when the Groww fetch returns `capital` (app.py:3716-3717). A GET here is not idempotent/cacheable in the HTTP sense; any prefetching, monitoring, or link-preview tooling that GETs this URL would silently rewrite live capital config. Frontend only calls it as POST (index.html:13880), so the GET path appears unused but is still reachable and mutating. Extra risk: the CSRF guard skips GET and the session cookie is SameSite=Lax, so a cross-site top-level GET link would trigger it in a PIN-unlocked browser. |
| Status | ACTIVE (as POST); GET side-effect flagged as a risk |

#### Two parallel personal-thesis systems (contradiction)
`stock_thesis.py` (module) backs `/api/thesis*` (app.py:5308-5357); a separate `ThesisManager` (`get_thesis_manager()`) backs `/api/my-thesis*` (app.py:5362-5460). The dashboard's "My Thesis" tab (index.html:3143, 3262) exclusively calls the `/api/my-thesis*` family — grep for `/api/thesis'`/`"`/backtick across index.html/landing.html/login.html/setup.html returns **zero** matches. The `/api/thesis*` family and its `stock_thesis` backing module appear to be a fully superseded, orphaned system — candidate for confirming with the user before any further work touches it (not touched here, per repo rules).

#### `/api/check-updates` — stub, not dead but non-functional
app.py:5268-5303: handler runs `bot.analyze_portfolio()` (real work) but the `changes` object is hardcoded empty with an explicit `# TODO: Implement state tracking to detect actual changes` (app.py:5276-5277) and always returns `has_update: False`. It has a live caller (index.html:11468/11471) polling it every 60 s, so the full AI analysis of every Groww holding (`bot.analyze_portfolio()`) runs on every poll with its result discarded, and callers currently always get "no update" regardless of real portfolio changes — a silent no-op disguised as a feature, worth flagging under CLAUDE.md standard #7 (missing data must be visible) since the poll gives no indication it never signals true.

### Cross-cutting facts (for the maps)

- **External services used in this range**: FYERS (historical candle backfill via `fyers_historical_backfill.backfill_symbol`, quotes via `fno_trader._groww_api.get_quotes` — note: variable named `_groww_api` used for FYERS-era quotes, naming is stale/misleading); Groww (margin/capital sync in `fno_sync_capital`, token refresh in `api_refresh_token`); Tijori (scrape via `tijori_collector.onboard_symbol`/`get_supply_chain_intel`); Google News (`news_sentiment._fetch_google_news`).
- **Env vars read (this range)**: `DB_URL` (raw psycopg2 connections in `get_watchlist`, `_do_watchlist_analysis`, `get_stock_prices` — bypassing the SQLAlchemy `db_manager` layer used elsewhere).
- **config_settings keys**: `idempotency.require_key` (default "0"); `fno.capital`, `fno.used_capital` (written by `fno_sync_capital`); `tijori.backfill_status`, `tijori.block_below_coverage_pct` (default 95, read by `tijori_backfill_status`); `tijori.last_collected.<symbol>` (deleted by symbol purge).
- **DB tables read/written**: `stocks`, `fyers_candles` (heavily, always resolution-filtered but NOT always date-bounded — `get_watchlist`'s JOIN has no date floor, relying on GROUP BY aggregation not full retrieval), `TradeJournalEntry`/`trade_journal`, `WatchlistNote`, `config_settings`, plus everything symbol_purge touches (14 PURGE_TABLES).
- **Every timed/triggered execution found in this range**: none of this range's endpoints are scheduler-triggered directly; all are HTTP-triggered (manual or dashboard-poll). `_pa_cache` (app.py:5171) gives `/api/portfolio-analysis` a self-refreshing background thread once warmed, not a scheduler task.
- **Rate limits/cost drivers**: `add_to_watchlist`'s bg pipeline is ~64 FYERS calls per new symbol (comment app.py:3999); deferred to after market close to avoid competing with the live trading path for FYERS's rate limit (see CLAUDE.md operational rule 9).
- **Fail-open vs fail-closed**: `add_to_watchlist`'s market-hours check explicitly fails OPEN (app.py:4009-4013, "fail toward NOT deferring") — the one deliberate exception to this repo's usual fail-closed doctrine, reasoned as "worst case is today's existing behaviour," not a guard being silently defeated.
- **Dead/orphan candidates found (no caller in index.html/landing.html/login.html/setup.html/telegram_commander.py/scheduler.py)**: `/api/supply-chain-intel/<symbol>/refresh`, `/api/auto-trade`, `/api/monitor-trailing-stops`, `/api/buy`, `/api/sell`, `/api/holdings`, `/api/positions`, `/api/orders`, `/api/trade-log`, `/api/costs/<symbol>`, `/api/net-profit`, `/api/fno/dashboard`, `/api/fno/instruments`, `/api/fno/option-chain`, `/api/fno/affordable`, `/api/fno/margin`, `/api/fno/costs`, `/api/fno/technicals`, `/api/fno/oi`, `/api/fno/auto-trade/config`, `/api/signals/tomorrow`, `/api/live-price/<symbol>` (superseded by plural `/api/live-prices` elsewhere), `/api/quote/<symbol>`, `/api/portfolio-review-status`, `/api/thesis` (all 4 methods), `/api/prices/fetch`. **23 of 78 endpoints** (verifier correction: 19 have no call site anywhere in source, and 4 — `/api/buy`, `/api/sell`, `/api/fno/option-chain`, `/api/fno/affordable` — have call sites that are unreachable from the current UI; `loadTradeLog()` is also flagged undefined in index.html; see the F&O UI reachability note below for further effectively-uncalled endpoints) — INFERENCE: many look like earlier UI iterations (raw Groww holdings/positions/orders, a pre-FYERS cost calculator) superseded by the F&O/paper-trading/portfolio-analysis views, not confirmed removable without asking the user (per CLAUDE.md deletion protocol — this is documentation only, no deletion proposed here).
- **F&O UI reachability (verifier-corrected)**: seven endpoints previously listed ACTIVE are effectively UNCALLED from the live UI — `/api/fno/trades` (12032), `/api/fno/rules` (12033), `/api/fno/global-indices` (12428), `/api/fno/expiries` (12175, 12204), `/api/fno/analyze` (12205), `/api/fno/buy` (12361) and `/api/fno/sell` (12399). `intradayLoadDashboard` is declared TWICE in the same `<script>` (index.html:12011 and 13518); the later one wins, so 12011-12099 (which calls fno/trades, fno/rules, `fnoAutoPick`, `fnoRefreshGlobal` and renders the EXIT button that leads to `fnoSellPosition`) never runs. The DOM ids `fno-instrument`, `fno-expiry`, `fno-analysis`, `fno-affordable`, `fno-chain` and `fno-capital` do not exist anywhere in index.html, so `fnoAutoPick`/`fnoInstrumentChanged` throw on null before any fetch, and `fnoBuyOption`'s only button lives in the affordable table. The live F&O callers are only: `fno/capital` (13466, 13521), `fno/positions` (13522), `fno/best-opportunity` (13617), `fno/auto-trade/run` (13449/13852), `fno/auto-trade/log`, `fno/sync-capital` and the backtest endpoints. Three formerly-UNCERTAIN endpoints (`/api/journal/<trade_id>`, `/api/my-thesis/<symbol>`, `/api/my-thesis/<symbol>/projection`) are now confirmed UNCALLED.
- **Contradictions**: (1) two live personal-thesis systems, only one wired to UI (see above); (2) `/api/check-updates` has a real caller but a stub body that can never return `has_update: true` (and it runs a full `bot.analyze_portfolio()` on every 60 s poll); (3) `fno_sync_capital` accepts GET and POST with identical mutating behavior; (4) money-moving `/api/auto-trade` and `/api/monitor-trailing-stops` carry no UI wiring while the scheduler achieves the same effect by calling the underlying functions directly (for `/api/monitor-trailing-stops` the underlying function is `bot.monitor_and_update_trailing_stops()`, reached via `bot.auto_trade()`) — the HTTP routes exist only for manual/curl triggering, which given CLAUDE.md operational rule 2 ("never exercise a write path against live trading records") is a real risk if used for testing.
- **Open unknowns**: none remaining from the earlier list — `/api/journal/<trade_id>`, `/api/my-thesis/<symbol>` and `/api/my-thesis/<symbol>/projection` were resolved by the verifier as UNCALLED (only `/api/journal/${tradeId}/close`, index.html:10594, and `DELETE /api/my-thesis/${symbol}`, index.html:11876, exist).

## API Endpoints — app.py part C (lines 5600–end) & Application Startup

Overview: this range covers thesis/search/fundamentals lookups, backtesting, the
full paper-trading surface (status/toggle/settings/auto-close/snapshots),
manual-holdings & "real trading" scaffolding, trade-snapshot replay, P&L
history, Telegram config, options-Greeks calculators, two SSE streams
(`/api/stream/prices`, `/api/events`), price/candle lookups, and
scheduler-interval admin — then the `if __name__ == "__main__"` startup block.
All 54 `@app.route` decorators in [5600, 8217] sit under `/api/*`, so the
global `_require_session` gate (app.py:227–249, confirmed by reading it) makes
every one of them require a PIN-verified session (`pin_ok`) unless the caller
is a loopback service call bearing `X-Service-Token` (auth_session.py:56,320,324).
None of this range's paths are in `_PUBLIC_PATHS` (app.py:221) or
`_ACCOUNT_ONLY_PATHS` (app.py:224). Mutating methods additionally pass through
`_block_cross_origin_mutations` (app.py:438, registered as a `before_request`)
which requires an allowed Origin/Referer **and** an `X-Requested-With` header
for non-service callers — `api()` in index.html sends both; a raw `fetch()`
would 401 (per CLAUDE.md Operational Rule 6). Only one endpoint in this range
carries `@idempotent`: `/api/auto-close/check`.

### A) Endpoint summary table

| METHOD | PATH | handler:line | auth | side effects | consumers | status |
|---|---|---|---|---|---|---|
| GET | /api/thesis/<symbol>/performance | thesis_performance:5635 | pin_ok | reads `theses` table, runs ThesisAnalyzer | none found | UNCALLED |
| GET | /api/search-stocks | search_stocks_api:5676 | pin_ok | reads stock_search index; on sparse results, lazily loads+caches Groww `get_all_instruments()` in `_instruments_cache` | index.html:11495 | ACTIVE |
| GET | /api/search | search_stocks:5724 | pin_ok | loads/caches Groww instruments (external call), in-memory filter | none found (frontend only uses `-stocks` variant) | UNCALLED / LEGACY |
| GET | /api/fundamentals/<symbol> | fundamentals:5759 | pin_ok | `fundamental_analysis.get_fundamental_analysis` via Groww client | none found | UNCALLED |
| GET | /api/auto-analysis | get_auto_analysis:5773 | pin_ok | reads auto_analyzer's cached results | index.html:11356 | ACTIVE |
| POST | /api/auto-analysis/run | run_auto_analysis_now:5780 | pin_ok+CSRF | spawns daemon thread → `auto_analyzer.auto_analyze_watchlist` | index.html:11392 | ACTIVE |
| GET | /api/backtest/strategies | backtest_strategies:5797 | pin_ok | `backtester.get_strategies()` | none found | UNCALLED |
| POST | /api/backtest/<symbol> | run_backtest_endpoint:5804 | pin_ok+CSRF | `backtester.run_backtest` (reads historical prices) | index.html:12918,12949 | ACTIVE |
| POST | /api/backtest/<symbol>/compare | compare_strategies_endpoint:5826 | pin_ok+CSRF | `backtester.compare_strategies` | none found | UNCALLED |
| GET | /api/paper-trading/status | paper_trading_status:5849 | pin_ok | `get_config`, `_get_canonical_journal_views` (DB via `_load_journal_entries_from_db`) | index.html:4710,5014,14448,14578,15072 | ACTIVE |
| POST | /api/update-trailing-stops | update_trailing_stops:5887 | pin_ok+CSRF | reads/mutates `paper_trades.json` via `PaperTradeTracker.update_trailing_stop` (no `@idempotent`) | index.html:14571 | ACTIVE — money-adjacent write path |
| GET | /api/paper-trading/closed-trades | get_closed_trades:5933 | pin_ok | DB `TradeJournalEntry`, bounded by `_JOURNAL_MAX_ROWS`=2000 | none found | UNCALLED |
| GET | /api/trade-snapshots/candles/<symbol>/<trade_date> | get_trade_snapshot_candles:5960 | pin_ok | `CandleDatabase.get_fyers_candles_as_5min`, bounded by computed `_days_back` | index.html:15368,15958 | ACTIVE |
| GET/POST | /api/paper-trading/build-daily-snapshots | build_daily_snapshots:6045 | pin_ok (+CSRF for POST) | reads `paper_trades.json`, fyers_candles; writes `daily_snapshots.json` | none found | UNCALLED — superseded by the `-with-candles` sibling |
| GET/POST | /api/paper-trading/build-daily-snapshots-with-candles | build_daily_snapshots_with_candles:6166 | pin_ok/service-token (+CSRF for POST) | reads `paper_trades.json`, fyers_candles; **writes** `IntradayCandle` rows (deletes same symbol/date first) + `daily_snapshots.json`; uses `trade_chart_manager` cache | scheduler.py:1182 (loopback, `_DEVICE_HEADERS` = X-Service-Token, "called automatically after 4 PM") | ACTIVE |
| POST | /api/auto-close/check | check_trailing_stop_exits:6465 | pin_ok+CSRF; **@idempotent("auto_close_check")** | `trailing_stop.check_and_close_trades_on_loss` + `manage_loss_positions`; fetches live prices per open symbol; reads/writes `paper_trades.json` | index.html:14593 (per its own docstring, dashboard-driven ~5s loop; the dashboard POST sends no Idempotency-Key, so the decorator never dedups it) — plus the scheduler task `auto_close_trades` (scheduler.py:826-878, every 5 s, registered at scheduler.py:1331) calls the same `trailing_stop.check_and_close_trades_on_loss` in-process | ACTIVE — money path; two independent 5-s closers act on `paper_trades.json` while the market is open (the dashboard one only while a tab is open) |
| POST | /api/paper-trading/toggle | toggle_paper_trading:6549 | pin_ok+CSRF | `set_config("paper_trading", …)` | index.html:5588,15102 | ACTIVE |
| GET | /api/paper-trading/settings | get_paper_trading_settings:6559 | pin_ok | `get_config("paper_trade_amount_limit")` | no direct caller found in grep | LIKELY UNCALLED (GET) |
| POST | /api/paper-trading/settings | update_paper_trading_settings:6580 | pin_ok+CSRF | `set_config("paper_trade_amount_limit", …)` | index.html:5069 | ACTIVE |
| POST | /api/cash-auto-trade/toggle | toggle_cash_auto_trade:6616 | pin_ok+CSRF | `set_config("cash_auto_trade_enabled", …)` | index.html:5595,6840 | ACTIVE |
| GET | /api/cash-auto-trade/status | cash_auto_trade_status:6626 | pin_ok | `get_config` x2 | index.html:5563,5605,6760,6832 | ACTIVE |
| POST | /api/manual-holdings/register | register_manual_holding:6643 | pin_ok+CSRF | `trade_origin_manager.register_manual_holding` | none found | UNCALLED |
| GET | /api/manual-holdings/list | list_manual_holdings:6687 | pin_ok | `trade_origin_manager.get_manual_holdings` | none found | UNCALLED |
| POST | /api/real-trading/enable | enable_real_trading:6708 | pin_ok+CSRF | writes `real_trading_config.json` (`enabled: true`, real capital figures) — app.py:6741-6752; NOTHING reads that file (grep of all source: only app.py writes it; the file is .gitignored and was last written Apr 2), so it has no effect on trading | none found | UNCALLED — NOT a live-trading switch (the real gate is the `paper_trading` config); reachable only via curl+session |
| GET | /api/trading-parity/verify | verify_trading_parity:6783 | pin_ok | returns a **hardcoded** dict of "identical: True" claims — no live comparison performed | none found | UNCALLED — safety-theater endpoint (see notes) |
| GET | /api/trade-snapshots | trade_snapshots_list:6834 | pin_ok | DB `TradeSnapshot`, else JSON fallback from `paper_trades.json` | none found | UNCALLED (list form; detail form below is used) |
| GET | /api/trade-snapshots/<int:snap_id> | trade_snapshot_detail:6914 | pin_ok | DB `TradeSnapshot.to_dict()`, else JSON fallback | index.html:17382 | ACTIVE |
| GET | /api/pnl-history | pnl_history:6978 | pin_ok | DB `PnLSnapshot`, bounded via `clamp_arg` (minutes ≤1440, limit ≤5000) | none found | UNCALLED |
| GET | /api/pnl-stats | pnl_stats:7065 | pin_ok | reads `paper_trades.json` + latest DB `PnLSnapshot` | index.html:9257 | ACTIVE — **has a bug**, see notes |
| GET | /api/cumulative-pnl | cumulative_pnl:7123 | pin_ok | reads `paper_trades.json`, computes running P&L in Python | none found | UNCALLED |
| GET | /api/telegram/status | telegram_status:7218 | pin_ok | `get_config` x3 | index.html:17396 | ACTIVE |
| POST | /api/telegram/configure | telegram_configure:7229 | pin_ok+CSRF | `set_config` for `telegram_bot_token`/`telegram_chat_id`/`telegram_enabled` | index.html:17417,17440 | ACTIVE — stores bot token via plain `set_config` |
| POST | /api/telegram/test | telegram_test:7243 | pin_ok+CSRF | `telegram_alerts.test_connection()` (external Telegram Bot API call); returns `jsonify(telegram_alerts.test_connection())`, i.e. `{ok:true, bot_name}` / `{ok:false, error}`, always HTTP 200 (app.py:7243-7247) | index.html:17430 (reads `data.success \|\| data.ok`, index.html:17431) | ACTIVE (wins the route — see duplicate-route note) |
| GET | /api/options/strategies | options_strategy_list:7255 | pin_ok | `options_strategies.get_strategy_list()` | none found | UNCALLED |
| POST | /api/options/greeks | options_greeks:7262 | pin_ok+CSRF | `options_strategies.full_analysis` (pure calc) | none found | UNCALLED |
| POST | /api/options/iv | options_iv:7281 | pin_ok+CSRF | `options_strategies.implied_volatility`/`iv_rank` | none found | UNCALLED |
| POST | /api/options/strategy/build | options_build_strategy:7303 | pin_ok+CSRF | `options_strategies.build_strategy` | none found | UNCALLED |
| GET | /api/stream/prices (SSE) | stream_prices:7328 | pin_ok | infinite generator, `bot.fetch_live_price` per symbol every 10s, holds a worker thread for connection lifetime | none — `startPriceStream()` (index.html:17472) is only invoked by its own onerror retry (17486); the page-load call is commented out (index.html:17490-17491 `// startPriceStream();`), so nothing opens the stream | UNCALLED — the "no cap on concurrent streams" risk (see notes) is latent |
| GET | /api/events (SSE) | change_events:7364 | pin_ok | `change_feed.subscribe()`/`unsubscribe()`; capped (503 "Too many event streams") | index.html:17651 | ACTIVE |
| GET | /api/nlp/info | nlp_info:7414 | pin_ok | `enhanced_nlp.get_model_info()` | index.html:17454 | ACTIVE |
| POST | /api/nlp/score | nlp_score:7424 | pin_ok+CSRF | `enhanced_nlp.score_with_details` (FinBERT) | none found | UNCALLED |
| GET | /api/daily-summary | api_daily_summary:7439 | pin_ok | `daily_summary.generate_daily_summary()` | none found | UNCALLED |
| POST | /api/daily-summary/send | api_send_daily_summary:7449 | pin_ok+CSRF | `daily_summary.send_daily_summary()` → Telegram | none as HTTP call; the function is scheduler-driven — `_task_telegram_daily_summary` (scheduler.py:1129-1142) imports and calls `daily_summary.send_daily_summary()` in-process (task `telegram_summary`, every 1800 s, scheduler.py:1342), verified | UNCALLED (as endpoint); the function itself is scheduler-driven |
| POST | /api/live-prices | get_live_prices_endpoint:7525 | pin_ok+CSRF | `_get_latest_symbol_price` per symbol (live → IntradayCandle → stock_prices fallback chain) | index.html:14511,14961 | ACTIVE |
| GET | /api/price/<symbol> | get_live_price_endpoint:7559 | pin_ok | `_get_latest_symbol_price` | index.html:14985,16787 | ACTIVE |
| GET | /api/latest-price/<symbol> | get_latest_price:7574 | pin_ok | `_get_latest_symbol_price` (byte-identical body to /api/price/<symbol>) | index.html:14527 (chosen when market closed) | ACTIVE — duplicate logic |
| GET | /api/intraday-candles | get_intraday_candles:7589 | pin_ok | `CandleDatabase.get_fyers_candles_as_5min(days=1)` | none found | UNCALLED |
| GET | /api/trade-candles | get_trade_candles:7627 | pin_ok | `CandleDatabase.get_fyers_candles_as_5min`, windowed by entry/exit time | index.html:16981 | ACTIVE |
| GET | /api/1min-candles | get_1min_candles:7703 | pin_ok | DB `IntradayCandle` (interval="5min") first, else `CandleDatabase` fallback — name says 1-min, data is 5-min | index.html:16221 | ACTIVE |
| GET | /api/5min-candles | get_5min_candles:7821 | pin_ok | same pattern as /api/1min-candles | index.html:15359,16238 | ACTIVE |
| GET | /api/scheduler/settings | get_scheduler_settings:8010 | pin_ok | `scheduler.get_task_registry()`, one bulk `get_configs_prefix("scheduler_interval_")` | index.html:5106 | ACTIVE |
| POST | /api/scheduler/settings | update_scheduler_settings:8065 | pin_ok+CSRF | `set_config` per task; floors trading tasks (`cash_auto_trade`,`fno_auto_trade`,`auto_close_trades`,`record_pnl`) at 5s, others at 1s | index.html:5180 | ACTIVE |
| GET | /api/scheduler/status | get_scheduler_status:8111 | pin_ok | reads `scheduler._task_stats` module global | none found | UNCALLED |
| POST | /api/telegram/test | test_telegram:8129 | pin_ok+CSRF | `telegram_alerts.test_connection()` (same call, different response shape than 7243) | index.html:17430 (same URL — see duplicate-route note) | **DEAD CODE — unreachable** |

### B) Notable endpoints (detail)

### `/api/auto-close/check` — money-path endpoint
| Field | Detail |
|---|---|
| Where | app.py:6464–6543 |
| What/Why | Universal automated trade management: closes profit-eroded trades, closes/reverses/scales loss positions |
| Idempotency | `@idempotent("auto_close_check")` (app.py:632) — dedupes by `Idempotency-Key` header + SHA-256 body fingerprint; keyless requests pass through unchanged unless `idempotency.require_key` config is "1" (**LAST VERIFIED 2026-09-27: `idempotency.require_key`=0**, i.e. keys are not enforced); the dashboard's ~5 s POST (index.html:14593) sends no Idempotency-Key, so the decorator never dedups it |
| Second caller | scheduler task `auto_close_trades` (scheduler.py:826-878, every 5 s, registered at scheduler.py:1331) calls the same `trailing_stop.check_and_close_trades_on_loss` in-process — so two independent 5-s closers act on `paper_trades.json` while the market is open (the dashboard one only while a tab is open) |
| Inputs | none (reads `paper_trades.json` directly) |
| Calls | `trailing_stop.check_and_close_trades_on_loss`, `trailing_stop.manage_loss_positions`, `paper_trader.get_live_price` per open symbol |
| DB/files | reads+writes `paper_trades.json` (via the called modules) |
| Failure | broad `except Exception` → `{"success": False, "error": ...}`, 500 |
| Blast radius | can close/reverse real paper positions; per CLAUDE.md Operational Rule 2, never exercise this against live trade data in testing |

### `/api/real-trading/enable` and `/api/trading-parity/verify` — unused real-money scaffolding
| Field | Detail |
|---|---|
| Where | app.py:6707–6826 |
| What/Why | Intended to switch on real-money auto-trading with manual-holdings segregation; parity endpoint was meant to assert paper/real logic parity |
| Status | **UNCALLED from any frontend/loopback caller found** — reachable only by a manually-authenticated curl call. `/api/real-trading/enable` only writes `real_trading_config.json` (app.py:6741-6752) and nothing reads that file, so it is NOT a live-trading switch. |
| Security note | `enable_real_trading` requires only `pin_ok` + CSRF, same bar as any other toggle; there is no separate confirmation step in this route itself (INFERENCE — no second-factor or confirmation flag in the request body). However, the route has no effect on trading: it only writes `real_trading_config.json`, which nothing in the codebase reads; the real gate is the `paper_trading` config. |
| Data note | `verify_trading_parity` doesn't compute anything — every "identical: True" is a Python literal in the handler, not derived from comparing paper vs real code paths |

### SSE endpoints
| Field | Detail |
|---|---|
| `/api/stream/prices` (app.py:7327) | `while True` generator per connection, `bot.fetch_live_price` for up to 20 symbols every 10s; blocks a thread for the connection's lifetime; no documented cap on concurrent connections (unlike `/api/events`, which 503s past its subscriber cap in change_feed.py). **UNCALLED**: `startPriceStream()` (index.html:17472) is only invoked by its own onerror retry (17486); the page-load call is commented out (index.html:17490-17491), so nothing opens the stream and the no-cap risk is latent. |
| `/api/events` (app.py:7363) | Thin notification stream from `change_feed.py`; carries only topic+id, client re-fetches via normal endpoints; 15s ping keeps proxies alive; GET-only so no CSRF header required, but still behind `pin_ok` |

### Duplicate route — `/api/telegram/test` POST (contradiction)
Two handlers are bound to the identical rule `POST /api/telegram/test`: `telegram_test` (app.py:7242) and `test_telegram` (app.py:8128). Flask does not error on this (different function/endpoint names, same URL+method), but Werkzeug's routing only ever dispatches to one of them. **CONFIRMED** by the verifier (read-only source reading, not executed): Werkzeug 3.1.8's matcher appends rules in registration order (routing/matcher.py:53) and returns the first method-matching rule (:91-97), so the earlier-registered `telegram_test` (7242) wins and `test_telegram` (8128) is unreachable dead code. Both call `telegram_alerts.test_connection()` but shape the response differently: the winning `telegram_test` returns `jsonify(telegram_alerts.test_connection())` (app.py:7243-7247) = `{ok:true, bot_name}` / `{ok:false, error}` (telegram_alerts.py:69-94), always HTTP 200; the shadowed `test_telegram` returns `{"ok": True, "message": f"✅ Connected to @{bot_name}"}`. The frontend (index.html:17430) does `await api('/api/telegram/test', {method:'POST'})` and reads `data.success || data.ok` (index.html:17431), so it works through `ok`.

### Bug found — `/api/pnl-stats` NameError when `paper_trades.json` is missing
app.py:7072–7101. `trades` is only assigned inside `if os.path.exists(trades_json_path): with open(...) as f: trades = json.load(f)` (7075–7078), guarded by a bare `except: pass`. Line 7101 then does `len([t for t in trades if os.path.exists(trades_json_path)])` unconditionally. If the file does not exist, `trades` was never bound, so this line raises `NameError`, caught by the *outer* handler's `except Exception as e` (7117), yielding a 500 `{"error": "..."}` instead of the presumably-intended zero-trade response. **VERIFIED FROM CODE** (not executed — read-only rule). The same NameError also fires when `paper_trades.json` is corrupt: the bare `except: pass` at app.py:7079 swallows the parse error and leaves `trades` unbound. Latent today: the file exists (36 KB). Separately, even when the file exists, that same list comprehension's condition doesn't depend on `t`, so it just re-counts `len(trades)` — functionally harmless but dead logic.

### Config-driven behavior in this range
| Key | Where read | Default | Live value (LAST VERIFIED 2026-09-27) |
|---|---|---|---|
| `paper_trading` | 5853, 6552 | "false" | `true` |
| `paper_trade_amount_limit` | 6564, 6596 | "0" | `50000.00` |
| `cash_auto_trade_enabled` | 6619, 6630 | "false" | `true` |
| `telegram_enabled`/`telegram_bot_token`/`telegram_chat_id` | 7217–7238 | n/a | `telegram_enabled=true` (secret values not recorded) |
| `idempotency.require_key` (used by `idempotent()`, defined ~line 620s, invoked by `/api/auto-close/check`) | — | "0" | `0` (keyless calls still accepted) |
| `scheduler_interval_<task>` | 8009–8107 | per-task default from scheduler registry | not queried (would need per-key SELECT) |

---

## Application Startup

### Ordered startup sequence (`if __name__ == "__main__":`, app.py:8142–8217)
1. Log `"Starting Groww AI Trading Bot on {FLASK_HOST}:{FLASK_PORT}"` (8143).
2. Guard: only run the block below if `WERKZEUG_RUN_MAIN=="true"` or `not app.debug` (8147) — prevents double-start under the Werkzeug reloader (`use_reloader=False` is actually set at the bottom, so this guard is effectively always true in the shipped config). Nuance: steps 6-8 below (Telegram listener, change feed, session housekeeping) sit outside this `WERKZEUG_RUN_MAIN`/`app.debug` guard.
3. **FYERS boot warm-up** (8156–8160): `import fyers_boot_warmup; fyers_boot_warmup.start_in_background()`. Own daemon thread, never blocks `app.run()`. Module-level `_active=True` from import time (fyers_boot_warmup.py:80); cleared to `False` in an `except` (fyers_boot_warmup.py:354-357, not a `finally`) if warm-up fails to start, so bulk-task guards aren't left paused. Comment says it runs *before* the scheduler specifically so `_active` is set before the first scheduler tick evaluates bulk-task guards.
4. **FYERS WebSocket** (8167–8171): `import fyers_ws_client; fyers_ws_client.start_in_background()`. Own daemon thread. Gated on `fyers.ws_enabled` config (`_cfg("fyers.ws_enabled", "true")`, fyers_ws_client.py:78,138) — **LAST VERIFIED 2026-09-27 (psql SELECT): `fyers.ws_enabled = false`**, so `start_in_background()` logs "FYERS WS disabled" and returns without connecting (fyers_ws_client.py:564). Note the code-level fallback default is `"true"` (fyers_ws_client.py:78) — if the config row were ever absent, this would default to *enabled*, opposite of today's explicit `false`; comment in app.py additionally says the client is "INERT... nothing in the trading path reads it."
5. **Master scheduler** (8173–8189): `from scheduler import start_scheduler; start_scheduler()`. On failure, falls back to starting `auto_analyzer.start_auto_analyzer(interval_seconds=300)` and a one-off `supply_chain_collector.collect_once` thread + `start_collector(interval_seconds=900)` individually.
6. **Telegram command listener** (8192–8196): `from telegram_commander import start_commander; start_commander()` — polls for `/status`, `/stop`, `/balance`, etc. Runs regardless of the scheduler's success/failure (separate try/except, not nested).
7. **Change feed** (8200–8204): `import change_feed; change_feed.start()` — watches tracker/journal files so open dashboards receive `/api/events` notifications for trades closed from Telegram or after-hours.
8. **Session housekeeping** (8208–8214): `import auth_session; auth_session.ensure_schema(); auth_session.seed_config(); auth_session.purge_expired()` — creates/verifies session-table schema, seeds idle/absolute-timeout config so they're editable from Settings, deletes session rows dead >1 week (per module, not re-verified here).
9. **`app.run()`** (8217): `app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False, threaded=True)`. `threaded=True` → one thread per request/connection (relevant to the SSE endpoints above, which hold a thread for the connection's life). `use_reloader=False` for faster startup (comment, 8216).

Each of steps 3, 4, 5, 6, 7, 8 is independently wrapped in its own `try/except Exception`, logging a warning and continuing — a failure in any one does not stop the others or prevent `app.run()`.

### Host/port/env
- `FLASK_HOST` — config.py:42, `os.getenv("FLASK_HOST", "127.0.0.1")`.
- `FLASK_PORT` — config.py:43, `int(os.getenv("FLASK_PORT", "5000"))`. Note: start-all.sh/stop-all.sh/status.sh all hardcode `8000`, and the launchd plist hardcodes `lsof -ti:8000`, so the effective port in practice is 8000 regardless of the config.py default of 5000 — **presumably `.env` sets `FLASK_PORT=8000`** (not verified here: `.env` values are secret-adjacent and only variable *names* may be listed per COMMON_RULES; a name-only check would need a separate grep, not run this pass).
- `ALLOWED_ORIGINS` env var (app.py, out-of-range but referenced near the session gate) drives CORS; defaults include `localhost:{FLASK_PORT}` and the Next.js dev origins.

### How the app is actually launched (scripts)
| Script | Purpose | Key behavior |
|---|---|---|
| `start-all.sh` | Full-stack launcher: Flask (8000) + Next.js frontend (3000) + Graphify watcher | `--dashboard-only` skips frontend+graphify. Always `kill_port 8000/3000` before starting (no PID-file trust on the way up). Creates `.venv` and installs `requirements.txt` if missing, plus a **separate** `pip install --no-deps fyers-apiv3==3.1.17` (kept out of requirements.txt because it pins `requests==2.31.0`/`aiohttp==3.9.3`, incompatible with growwapi's pins — non-fatal if it fails). Starts Flask via `nohup .venv/bin/python3 app.py`, waits for the port, writes PIDs to `.groww-pids`. `--stop` mode: kills by PID file **then unconditionally sweeps ports 8000/3000 regardless**, then verifies via `lsof` and exits 1 if still bound (the fix for the stale-PID-file incident documented in CLAUDE.md Operational Rule 1). |
| `stop-all.sh` | Same PID-file + port-sweep pattern as `start-all.sh --stop`, plus **launchd-awareness**: `stop_flask_via_launchd()` checks `launchctl print gui/$UID/com.parthsharma.parths.flask` and does `launchctl bootout` instead of a raw `kill`, because the plist's `KeepAlive.SuccessfulExit=false` would otherwise cause launchd to relaunch a merely-killed process within `ThrottleInterval` (10s). Falls back to PID/port kill only if not running under launchd. |
| `status.sh` | Read-only status: checks PID file entries via `kill -0`, else falls back to `nc -z localhost <port>`; prints log line counts for `server.log`/`frontend/nextjs.log`/`graphify.log`. `-w` = watch mode (loop, 2s refresh). |
| `start.sh` | Standalone auto-restart supervisor (**not** how the app runs today — the plist's own comment says the launchd job supersedes it, but that plist is not installed; the app currently runs via `start-all.sh`). Kills port 8000, loops `python3 app.py \| tee -a server.log`, tracks restart/rapid-crash counts (max 50 restarts, 5 rapid crashes within 60s each stop it). Plist explicitly avoids this: piping through `tee` without `pipefail` means the checked exit code is `tee`'s, not Python's, so crash detection here "likely never actually fires" (plist's own comment, launchd/com.parthsharma.parths.flask.plist:9-15). |
| `launchd/com.parthsharma.parths.flask.plist` | **Not currently installed/loaded** (verified 2026-09-28: `launchctl print gui/501/com.parthsharma.parths.flask` → "Could not find service"; no plist in `~/Library/LaunchAgents`; `raw.log` last written 2026-08-09). The plist exists in the repo, but the app currently runs via `start-all.sh` (nohup → `server.log`, plus the in-process `app.log`; the process running at 22:02 on 2026-09-28 was started by `start-all.sh`, per `.groww-pids` + the Flask banner in `server.log`). If installed, it would be the production launcher: `RunAtLoad=true`, `ProgramArguments` = `bash -c "cd ... && lsof -ti:8000 \| xargs kill -9 2>/dev/null; exec .venv/bin/python3 app.py"` (the `exec` replaces the shell so launchd sees Python's real exit code). `KeepAlive.SuccessfulExit=false` → restarts on any non-zero/crash exit, `ThrottleInterval=10`s floor between restarts. Correct stop is `launchctl bootout`, not `kill` (see stop-all.sh). When loaded, it logs to `~/Library/Logs/ParthS/raw.log` (both stdout+stderr) — **not** `server.log` under the project (TCC-sandboxed for xpcproxy on this macOS) and **not** `app.log` (owned by app.py's in-process `RotatingFileHandler`, would race with launchd's own fd on rotation). |

### Cross-cutting facts (for the maps)

- **External services called in this range**: Groww API (`bot._get_groww().get_all_instruments()` — search endpoints, fundamentals; `get_live_price`/`fetch_live_price` price paths), Telegram Bot API (`telegram_alerts.test_connection()`, `daily_summary.send_daily_summary()`), FYERS (via `fyers_candles` table reads/adapters — no direct outbound FYERS HTTP call in this line range itself; the live calls are in the boot-warmup/WS modules started at startup).
- **Env vars referenced**: `FLASK_HOST` (config.py:42, default `127.0.0.1`), `FLASK_PORT` (config.py:43, default `5000`; effectively `8000` in every launch script — likely `.env` override, names-only not re-verified this pass), `WERKZEUG_RUN_MAIN` (checked at startup, not app-set), `ALLOWED_ORIGINS` (CORS, referenced near session gate).
- **config_settings keys read/written in this range**: `paper_trading`, `paper_trade_amount_limit`, `cash_auto_trade_enabled`, `telegram_enabled`, `telegram_bot_token` (secret), `telegram_chat_id`, `idempotency.require_key`, `scheduler_interval_<task>` (per-task, bulk-read via `get_configs_prefix`), `fyers.ws_enabled` (read at startup by fyers_ws_client, not by app.py directly).
- **DB tables read/written in this range**: `theses` (read), `trade_journal`/`TradeJournalEntry` (read, heavily — closed-trades, canonical journal views), `trade_snapshots`/`TradeSnapshot` (read), `pnl_snapshots`/`PnLSnapshot` (read), `intraday_candles`/`IntradayCandle` (read + **write/delete-then-insert** in `build-daily-snapshots-with-candles`), `fyers_candles` (read-only, via `CandleDatabase` adapter, always bounded by a computed `days` argument), `stock_prices` (read, fallback price source), `config_settings` (read/write throughout).
- **Files read/written**: `paper_trades.json` (read everywhere in this range; written by `update_trailing_stops` and indirectly by the trailing-stop/loss-management modules called from `/api/auto-close/check`), `daily_snapshots.json` (written by both build-snapshot endpoints), `real_trading_config.json` (written by `/api/real-trading/enable`, uncalled today; nothing in the codebase reads it).
- **Every timed/triggered execution found in this range**: `/api/auto-close/check` — dashboard-driven, ~5s per its own docstring, and the same closer also runs from scheduler task `auto_close_trades` (scheduler.py:826-878, every 5 s, registered at 1331); `build-daily-snapshots-with-candles` — scheduler.py loopback call, "after 4 PM" (scheduler task `build_daily_snapshots`, every 900 s, scheduler.py:1344; POST loopback at scheduler.py:1181-1184 with `_DEVICE_HEADERS`); `/api/stream/prices` — 10s in-generator sleep per open SSE connection (currently no client opens it — UNCALLED); `/api/events` — 15s ping per open SSE connection.
- **Rate limits/quotas**: none enforced directly in this range beyond `clamp_arg` row caps (`pnl-history` ≤5000 rows/≤1440 min, `closed-trades` ≤2000, `trade-snapshots` ≤200/500) and the SSE subscriber cap in `change_feed.py` (not opened this pass).
- **Fail-open / fail-closed**: `/api/auto-close/check`'s idempotency is fail-open by design while `idempotency.require_key=0` (keyless requests proceed unprotected — live value confirmed 0). `fyers_ws_client`'s code-level default (`_DEFAULT_ENABLED="true"`) is fail-open if the config row were ever missing, though the current explicit row is `false` (fail-closed in practice today). SSE `/api/stream/prices` has no concurrency cap (fail-open on resource exhaustion — latent, since nothing currently opens the stream) vs. `/api/events` which fails closed (503) past its cap.
- **Dead/legacy/contradictory code**: duplicate `POST /api/telegram/test` route (7242 vs 8128) — the second (`test_telegram`, 8129) is unreachable; `/api/search` (bare) appears superseded by `/api/search-stocks` with no callers; `/api/trading-parity/verify` returns hardcoded claims, not a real check, and is uncalled; `/api/real-trading/enable` and `/api/manual-holdings/*` are fully-built but uncalled from any frontend/loopback path found (and `/api/real-trading/enable` only writes `real_trading_config.json`, which nothing reads, so it is not a live-trading switch); `/api/stream/prices` is uncalled (its page-load `startPriceStream()` call is commented out, index.html:17490-17491); `start.sh`'s crash detection is acknowledged dead by the plist's own comment (tee swallows Python's exit code).
- **Bug**: `/api/pnl-stats` (app.py:7101) raises `NameError` → 500 whenever `paper_trades.json` is absent or corrupt, because `trades` is only bound inside the `if os.path.exists(...)` block above it.
- **Open unknowns**: (resolved) `daily_summary.send_daily_summary()` is called in-process by scheduler task `telegram_summary` (scheduler.py:1129-1142, 1342) — the `/api/daily-summary/send` route itself is uncalled; the actual `.env` value of `FLASK_PORT` (name-only check not re-run this pass, inferred as 8000 from launch scripts); (resolved) which of `telegram_test`/`test_telegram` Werkzeug dispatches — `telegram_test` wins, confirmed by the verifier from Werkzeug 3.1.8's matcher source (routing/matcher.py:53, 91-97).

## Authentication, Sessions & Security

Two parallel auth systems coexist. **ACTIVE**: cookie-based two-layer sessions
(`auth_session.py` + `google_auth.py`, wired into `app.py`'s `_require_session`
gate) — this is what the dashboard, landing page and PIN lock actually use.
The landing page and the Google/Apple/email buttons are currently switched
**off** by config (`auth.landing_enabled=false`, `auth.provider.google=false` —
LAST VERIFIED 2026-09-27 via DB), so in practice today the system is PIN-only
and `/` serves the dashboard directly; BUT the flag only hides the landing
button — the Google OAuth flow itself is live (see the `google_auth.py`
section). **LEGACY**: a JWT + `auth_manager.py` system (`/api/auth/signup`,
`/login`, `/dashboard`, `/setup`, `@require_auth`) that predates the session
gate. It is unreachable without the PIN session, but NOT structurally
unreachable: it is reachable (and JWT-forgeable) by anyone already
PIN-unlocked or holding the service token — see the Legacy JWT section. PIN
hash lives in `.env` (`APP_PIN_HASH`); the device token (`APP_DEVICE_TOKEN`) is
no longer consulted for auth (superseded by the session cookie, per the
`app.py:294-299` comment) but must still be set: `unlock()` returns 500 if it
is unset (app.py:333). Uncommitted working-tree changes to `auth_session.py`,
`app.py`, `db_manager.py` and new file `google_auth.py` are the current state
(base commit ccb9e28).

### `auth_session.py` — module (ACTIVE, two-layer session store)
| Field | Detail |
|---|---|
| Where | `auth_session.py:1-325` |
| What / Why | One row in `auth_sessions` + one HttpOnly cookie (`sid`, 256-bit `secrets.token_urlsafe(32)`; only its SHA-256 stored). Two booleans read off one row: `account` ("we know who this is", lives `auth.account_days` days) and `pin_ok` ("PIN entered recently": `pin_verified_at` stamped, within `auth.absolute_hours`, AND used within `auth.idle_minutes`). |
| Key functions | `create(user_id, pin_verified=False)` new row+cookie; `load(sid, touch=True)` → dict incl. `pin_ok`, never raises — DB error reads as locked (fail-closed); `promote(sid)` re-issues a NEW session id when PIN is entered on an existing account session, old one revoked (OWASP session-fixation defense); `revoke(sid)`; `purge_expired(days=7)`; `is_service_call(request)` — loopback (127.0.0.1/::1) + `X-Service-Token` == in-memory `SERVICE_TOKEN` (`secrets.token_urlsafe(32)` minted fresh at process start, `auth_session.py:56`, not persisted). |
| Caching | In-memory `_cache` dict keyed by sid_hash, `CACHE_SECONDS=30`; `last_seen_at` touched at most once per `TOUCH_SECONDS=60`. Revocation clears cache entry immediately (logout instant). |
| DB table | `auth_sessions`: `sid_hash`, `user_id`, `created_at`, `last_seen_at`, `expires_at`, `revoked_at`, `pin_verified_at`, `sudo_until` (unused — see below), `ip`, `user_agent`. `ensure_schema()` idempotently adds `pin_verified_at` if missing, backfilling from `created_at` once at startup (`auth_session.py:98-116`). |
| Config keys | `auth.idle_minutes` (default 30, live 30), `auth.absolute_hours` (default 12, live 12), `auth.account_days` (default 30, live 30), `auth.allowed_emails` (empty = nobody), `auth.landing_enabled` (default "false", live **false**), `auth.provider.google/apple/email` (default "false", live **all false**). LAST VERIFIED 2026-09-27 (`SELECT key,value FROM config_settings`). |
| Cookie flags | `HttpOnly=True`, `SameSite=Lax`, `Path=/`, `Secure` only when `request_is_secure()` — NOT secure on plain `http://127.0.0.1` (Safari refuses Secure cookies there; deliberate tradeoff). |
| Failure behaviour | Fail-closed throughout. `SERVICE_TOKEN` is per-process — a restart invalidates it (no persistence, by design; the scheduler is in the same process so this is transparent). |
| Status | ACTIVE — sole session mechanism gating `app.py`'s `_require_session`. |

### `google_auth.py` — module (untracked/new file; code ACTIVE, landing button hidden by config but OAuth flow LIVE)
| Field | Detail |
|---|---|
| Where | `google_auth.py:1-260` (new, untracked in git) |
| What / Why | Standard OIDC authorization-code flow. `GET /api/auth/google/start` (app.py:1031) builds `state`+`nonce`, signs into a 10-min cookie (`g_oauth`, `itsdangerous.URLSafeTimedSerializer`, per-process random signing secret `google_auth.py:54`), redirects to Google. `GET /api/auth/google/callback` (app.py:1043) verifies `state`, exchanges `code` server-side over TLS, verifies `id_token` via `google.oauth2.id_token.verify_oauth2_token` (signature/issuer/audience/expiry), then checks `nonce` and `email_verified` itself. |
| Allow-list | `_allowed_emails()` reads `auth.allowed_emails` fresh on EVERY sign-in. Empty list = nobody admitted. Live: non-empty (1 entry — verifier-confirmed; the value is not printed, treated as sensitive-adjacent PII). |
| Linking rule | New `sub` + existing email with `password_hash` set → refused (`verify_first`), blocking pre-registration account takeover. Existing email linked to a different `google_id` → refused (`linked_elsewhere`). |
| Outputs | Success → `auth_session.create(user_id, pin_verified=False)` (account layer only; PIN pad still required). Best-effort Telegram notification on every sign-in (email + IP + truncated UA) via `telegram_alerts.send_message`. |
| Errors | Never leak detail to visitor — redirect `/?auth_error=<code>` (cancelled/state/expired/google/not_allowed/linked_elsewhere/verify_first/not_configured); detail goes to `logger` only. |
| DB | `users` table via `auth_manager.User` ORM (shared model with the legacy JWT system). |
| External services | `https://accounts.google.com/o/oauth2/v2/auth`, `https://oauth2.googleapis.com/token`, Google's JWKS (via `google-auth` lib). |
| Config/env | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` — **both present as .env var names** (VERIFIED, names only). The landing-page Google button is shown only when `auth.provider.google=true` (via `/api/auth/providers`, app.py:1017-1022), but `google_start` checks only `google_auth.configured()` (both env vars set; app.py:1031-1040) and never `auth.provider.google`, and `/api/auth/google/start` + `/callback` are in `_PUBLIC_PATHS` (app.py:221-222). The live DB flag is **false** (2026-09-27), so: button hidden, flow live — anyone can start the OAuth flow by URL; the one allow-listed Google account can complete it and get an account-layer session (PIN still required for `/api/*`). |
| Status | Code ACTIVE/complete; landing button hidden by config (`auth.provider.google=false`) but the OAuth flow is LIVE and reachable by URL, LAST VERIFIED 2026-09-27/28. |

### Legacy JWT auth system — `auth_manager.py` (User model ACTIVE; JWT flow LEGACY, no callers)
| Field | Detail |
|---|---|
| Where | `auth_manager.py:1-229` |
| What | `User` ORM model (`users` table — same table `google_auth.py` writes to). `generate_jwt`/`verify_jwt` (HS256, `JWT_SECRET` env var with an **insecure hardcoded fallback** `"your-super-secret-key-change-in-production-32chars!!"` at line 18 — `JWT_SECRET` is **not** in the `.env` var-name list found, so this fallback is what's actually in effect if this code path is ever hit — VERIFIED FROM CODE + `.env` grep). `register_user`, `authenticate_email` (manual SHA-256(salt+password) via `hashlib`, not bcrypt/scrypt/argon2, lines 44-66). `authenticate_google` (a second, unused Google auth path with no callers found — dead). `require_auth` decorator (Bearer JWT header). |
| Callers | `app.py:54-57` imports it; routes: `/api/auth/signup` (1095), `/api/auth/login` (1121), `/api/auth/google` GET (1146 — itself a stub that just redirects with the raw code, never exchanges it, i.e. incomplete/broken on its own terms), `/api/auth/verify` (1163), `/api/auth/profile` (1173), `/api/auth/set-api-key` (1186), `/api/auth/demo` (1207, disabled unless `ALLOW_DEMO_LOGIN=1` env), `/dashboard` (1076, `@require_auth`), `/setup` (1086, `@require_auth`). |
| **CONTRADICTION (corrected by verifier)** | `@require_auth` is on exactly 5 routes: `/dashboard` (1077), `/setup` (1087), `/api/auth/verify` (1164), `/api/auth/profile` (1174), `/api/auth/set-api-key` (1187). None of the routes listed above is in `_PUBLIC_PATHS` (app.py:221-222) or `_ACCOUNT_ONLY_PATHS` (226), and `_require_session` (227-252) runs first as `before_request`. So NO request reaches them without (a) a PIN-verified session cookie (API paths) / any live account session (page paths), or (b) a loopback call carrying the in-memory per-process `X-Service-Token`. They are therefore unreachable without the PIN session — but NOT "chicken-and-egg unreachable": with such a session they ARE reachable, and a JWT signed with the fallback literal (auth_manager.py:18; `JWT_SECRET` is absent from the `.env` names and from the launchd plist) would pass `require_auth`. `/api/auth/signup`, `/api/auth/login`, `/login` and `/api/auth/demo` (403 unless `ALLOW_DEMO_LOGIN`) are likewise reachable post-PIN. Forging a JWT adds only the ability to act as another `users` row (1 row live, no `groww_api_key`; `User.groww_api_key` is read nowhere outside these routes) — anyone already PIN-unlocked or holding the service token already has everything. Frontend confirms nothing calls these: `login.html`'s `handleSignIn`/`handleSignUp` (lines 854-877) only set `localStorage` (`user_email`, `logged_in`) and redirect — **no `fetch` to any `/api/auth/*` endpoint at all** (VERIFIED — grepped `login.html` for `fetch(`/`/api/auth`: zero hits besides none). `login.html`/`setup.html`/`/dashboard`/`/setup` are orphaned relative to both auth systems. |
| Status | `User` model: ACTIVE (shared table with google_auth.py). JWT signup/login/verify/profile/set-api-key/demo/`/dashboard`/`/setup`/`login.html`: LEGACY, no callers; unreachable without the PIN session but reachable (and JWT-forgeable) post-PIN or with the service token — flagged, not removed (read-only task). |

### `migrate_auth.py` / `migrate_idempotency.py` — one-off migration scripts
| name | file:line | purpose | callers | status |
|---|---|---|---|---|
| `migrate_auth.py: migrate()` | migrate_auth.py:15 | `Base.metadata.create_all` for `users` table | manual (`python migrate_auth.py`) | LEGACY/manual, table already exists |
| `migrate_idempotency.py: migrate()` | migrate_idempotency.py:46 | Creates `idempotency_keys` if absent + adds `content_type` column if missing + seeds `idempotency.require_key` (default "0") and `idempotency.retention_hours` (default "48") | manual (`python migrate_idempotency.py`) | ACTIVE (table in use) |

### `idempotent(scope)` decorator + `idempotency_keys` table — ACTIVE
| Field | Detail |
|---|---|
| Where | Decorator `app.py:632-` (claim/replay/in-flight/mismatch logic continues past 700); model `db_manager.py:771-807` (`IdempotencyKey`). |
| What / Why | Duplicate-order protection on money-path endpoints. Client sends `Idempotency-Key` header (≤255 chars, `IDEM_KEY_MAX_LEN`). First request: row inserted `state="in_flight"` BEFORE the handler runs (`db_manager.py:1569 claim_idempotency_key`) — a concurrent duplicate sees the claim and is rejected (`IDEM_IN_FLIGHT`), not double-executed. On completion, `complete_idempotency_key` (db_manager.py:1720) stores `response_json`/`status_code`/`content_type` for byte-identical replay (`IDEM_REPLAY`). Body is fingerprinted (`sha256`) so key reuse for a different order is caught (`IDEM_MISMATCH`), not silently replayed wrong. Concurrency primitive is the DB unique index `idx_idem_key_scope` on `(key, scope)`, not app logic. |
| Opt-in | Backward compatible: no header = old behaviour, unless `idempotency.require_key="1"` (checked live via `_idempotency_required()`, app.py:623-629). **Live value is "0"** (LAST VERIFIED 2026-09-27) — keyless requests to money paths are currently NOT rejected. |
| Retention | `prune_idempotency_keys(retention_hours=48)`; live config `idempotency.retention_hours=48`. |
| Status | ACTIVE mechanism; enforcement opt-in, currently off. |

### App-lock (PIN) — `/api/unlock` + lockout — ACTIVE, primary gate today
| Field | Detail |
|---|---|
| Where | `app.py:294-373` |
| What / Why | The correct PIN (checked here) is the only way to obtain a session cookie. Client sends raw PIN in JSON body over HTTPS/localhost POST (`index.html` `pinKey()`, line 4303-4360 — sends `{pin: entered}` via `fetch`, never a client-side hash); server computes an unsalted `sha256(pin)` (app.py:342) and compares it to `APP_PIN_HASH` (`.env`, presumably pre-hashed) with `!=` (app.py:344) — not a constant-time comparison. Fail-closed: unset `APP_PIN_HASH`/`APP_DEVICE_TOKEN` → 500 "not configured", never "any PIN works". |
| Rate limiting | Keyed by `request.remote_addr` (IP) — in-memory dict `_unlock_attempts` (not per-account, not persisted across restart). `_UNLOCK_MAX_ATTEMPTS=5` per `_UNLOCK_WINDOW_SECONDS=120` (2 min), sliding window (app.py:301-303). **UNCOMMITTED**: committed HEAD has `_UNLOCK_WINDOW_SECONDS = 15 * 60` (line 291), i.e. 5 attempts / 15 min; the 2-min window is a working-tree edit. The running Flask process (PID 36337, started 2026-09-28 22:02:03; app.py mtime 2026-09-25 22:43) uses the working-tree 5 / 120 s. `_unlock_retry_after(ip)` computes seconds until the oldest of the 5 ages out; 429 with `Retry-After` header. Frontend surfaces this as a live countdown (`_pinStartTimeout`, index.html:4279). **IP-keyed only** — behind Tailscale/NAT all devices could share an IP and share the counter (not verified as an actual issue, just a property of IP-keying); also resettable by app restart (in-memory). |
| Session issuance | On success: if the browser already carries an account-session cookie (Google sign-in pending PIN), `auth_session.promote()` re-issues a NEW id with `pin_verified=True`, revoking the old — anti session-fixation. Else revokes any existing cookie and creates a fresh session for the hardcoded single user id `1`, `pin_verified=True`. |
| Status | ACTIVE, the actual front line of defense today (Google layer is off). |

### `/api/session`, `/api/logout`, `/api/session/verify` — session/logout ACTIVE; session_verify UNCALLED
| name | file:line | purpose | notes |
|---|---|---|---|
| `session_status` | app.py:376-398 | "am I logged in" boot check | Public, `touch=False` (asking must not count as activity); returns only booleans + expiry timestamps, never identity. |
| `logout` | app.py:401-408 | Revoke session, clear cookie | In `_ACCOUNT_ONLY_PATHS` — reachable without PIN (ending a session must not require re-entering the PIN). |
| `session_verify` | app.py:411-428 | Legacy compatibility stub | Always returns `{"valid": true}` once reached (reaching the handler IS the answer, since the gate already checked the cookie) — comment notes this replaced an old `APP_DEVICE_TOKEN`-staleness problem. **No caller anywhere** (0 references in any source file; the boot check uses GET `/api/session`, index.html:4421, 11915) — legacy stub. |

### `_require_session` / `_PUBLIC_PATHS` / `_ACCOUNT_ONLY_PATHS` — deny-by-default gate (ACTIVE)
| Field | Detail |
|---|---|
| Where | app.py:206-252 |
| What | `before_request` hook. `_PUBLIC_PATHS = {"/", "/api/unlock", "/api/session", "/api/auth/providers", "/api/auth/google/start", "/api/auth/google/callback", "/fyers_callback"}` plus Flask's `static` endpoint (itself gated by `_block_project_file_exposure`) and `OPTIONS`. Everything else needs a live cookie mapping to a session row: `/api/*` needs `pin_ok`; page routes need only `account` (so a signed-in-but-PIN-pending browser lands on `/app`'s PIN pad, not the landing page). Service calls (`auth_session.is_service_call`, loopback + `X-Service-Token`) bypass entirely. |
| Why it matters | Before this gate existed (per module docstring), every GET — trades, journal, holdings, tokens — was readable by anyone who knew the URL; only writes were checked, against one static token shared by every device. |
| Blast radius | A route added without considering this gate is automatically locked (fail-closed) — the safe default. Conversely, adding a route to `_PUBLIC_PATHS` by mistake exposes it to anyone with no cookie at all. |

### Cross-origin / CSRF layers — ACTIVE
| Layer | Where | Mechanism |
|---|---|---|
| CORS | app.py:255-269 | `ALLOWED_ORIGINS` env-configurable (names only — env var `ALLOWED_ORIGINS`), defaults to `localhost:{FLASK_PORT}`, `127.0.0.1:{FLASK_PORT}`, `localhost:3000`, `127.0.0.1:3000`. Replaces an earlier bare `CORS(app)` (`Access-Control-Allow-Origin: *`). |
| CSRF — Origin/Referer check | `_block_cross_origin_mutations`, app.py:437-475 | Any mutating method (not GET/HEAD/OPTIONS) with an Origin/Referer present and not in `ALLOWED_ORIGINS` → 403. Absent Origin (curl, scheduler loopback, Telegram) is allowed through (non-browser caller, nothing to spoof). `/api/unlock` is explicitly exempted (it IS the proof-of-PIN). |
| CSRF — custom header | same function, app.py:468-473 | Non-service mutating requests must carry `X-Requested-With` (added by `index.html`'s `api()` wrapper on every write, index.html:5862-5867 — `'X-Requested-With': 'XMLHttpRequest'`; note the comments at index.html:5068 and 14500, and CLAUDE.md operational rule 6, still say `api()` sends `X-Device-Token` — stale) — a cross-site page cannot add a custom header without a preflight the browser blocks. Combined with `SameSite=Lax` cookies, closes CSRF for state-changing calls. |
| Frontend discipline | `check_raw_fetch.py` (per CLAUDE.md, not independently re-verified in this pass) | Guards against a raw `fetch()` bypassing `api()` and missing `X-Requested-With`, which has caused silent permanent-401 regressions 4 times historically (CLAUDE.md operational rule 6). |

### `/api/paper-trading/toggle` — no re-auth on a money-mode switch
| Field | Detail |
|---|---|
| Where | app.py:6548-6555 |
| What | Flips `paper_trading` config true/false with a single `set_config` call. It is a TOGGLE (it flips the current value), so a retried/duplicated POST flips the mode straight back; and a missing `paper_trading` row reads as "false" = LIVE mode (app.py:6548). Gated only by the general session (`pin_ok`) — **no step-up/re-auth check**, no idempotency wrapper, no confirmation beyond whatever the frontend's `confirm()` dialog does client-side (and per `DashboardWebView.swift:106-110`, `confirm()` in the iOS wrapper is a real native alert, not a no-op). |
| `sudo_until` | `AuthSession.sudo_until` column exists (`db_manager.py:515`, comment: `"step-up window (unused until D)"`) — matches user's memory note that hardening phase C/D/E are planned-but-not-built. VERIFIED FROM CODE: column is read into the session dict (`auth_session.py:183`) but nothing in `app.py` checks it anywhere (grepped `sudo_until` repo-wide: only the two definitions, no consumer). |
| Risk | Anyone holding a live PIN-unlocked session (e.g. a stolen/observed cookie within the idle/absolute window) can flip real trading on with one POST + the `X-Requested-With`/Origin CSRF headers `api()` already supplies automatically — no extra prompt from the server side. |

### `/fyers_callback` (public) and `/api/fyers/complete-login` (session-gated) — single-use code exchange
| Field | Detail |
|---|---|
| Where | app.py:2342-2416 |
| What | FYERS OAuth redirect target (public — the session cookie rides along via `SameSite=Lax` on the top-level redirect, but the route itself is in `_PUBLIC_PATHS` so it works even without one). Exchanges a one-time `auth_code` for a FYERS access token via `fyers_auth.complete_login()`, writes to `.env`/token store (not detailed in this pass — see FYERS section owner). `/api/fyers/complete-login` is a paste-back path for phones whose loopback redirect can't reach the Mac (NOT public: it is not in `_PUBLIC_PATHS`, and as a POST under `/api/` it needs a `pin_ok` session + `X-Requested-With`, app.py:227-252, 462-473); accepts a pasted URL/code, regexes out `auth_code=...`, length/space sanity check (`len(code) < 20 or " " in code` → reject) before use. Code is "used once and never logged" per comment (not independently verified beyond reading the comment — INFERENCE from code intent). |
| Risk | `/fyers_callback` is a public, unauthenticated endpoint (`/api/fyers/complete-login` is not — it needs a PIN session); its only protection is that FYERS's one-time code is worthless to a third party without also controlling the registered redirect_uri. Out of this section's direct scope (FYERS integration is presumably owned elsewhere) but flagged since it's in `_PUBLIC_PATHS`. |

### Frontend auth surfaces
| File | Behaviour | Status |
|---|---|---|
| `index.html` lock screen | `pinKey()` (4303-4360) sends raw PIN to `/api/unlock`; `_setLocked`/`_setUnlocked` (4394-4403) + `_whenUnlocked()`/`_parkedGets` gate ALL `api()` calls client-side so a locked page doesn't fire a burst of 401s (server-side gate is the real one). `verifySessionOnBoot` (4406-4438) asks `/api/session` before deciding to show the lock — cookie itself is HttpOnly and never read by JS. **PROTECTED**: the lock-screen intro animation (wordmark drop-in, card fade/expand, colour alternation) is explicitly off-limits per CLAUDE.md — documented here, not touched, not suggested for removal. | ACTIVE |
| `index.html` `api()` wrapper | Lines ~5832-5906+. Adds `X-Requested-With` to every write; on any non-2xx response with no JSON content-type, builds a synthetic error from the raw body (guards against an HTML error page being parsed as JSON); on 401 re-locks the UI and re-arms the parking gate. | ACTIVE |
| `landing.html` | Sign-in/sign-up forms (`handleSignIn`/`handleSignUp`, lines 972-989) **send nothing to the server** — VERIFIED: both just call `notRegisteredYet()`, which shows a static "you're not a registered client yet, download the deck" message. It's a lead-capture/waitlist page, not a working auth form. The Google button (`handleGoogleSignIn`, line 945) DOES correctly navigate to `/api/auth/google/start`, gated on `PROVIDERS.google` fetched from the live `/api/auth/providers` endpoint. The Apple button goes to `/api/auth/apple/start` (landing.html:946), a route that does not exist; `/api/auth/providers` reports apple from the flag alone (app.py:1022). Currently unreachable in normal flow (`auth.landing_enabled=false` → `/` serves the dashboard directly, per app.py:967-994). | Forms: decorative/inert. Google button: wired, hidden by flag (backend flow live). Apple button: points at a non-existent route. |
| `login.html` | Entirely disconnected legacy page: `handleSignIn`/`handleSignUp`/`handleGoogleSignIn` (854-877) just write `localStorage.setItem('logged_in','true')` and redirect to `setup.html`/`index.html` — **no server call at all**, no relation to either auth system. The `/login` route (app.py:1070) is NOT public — it is not in `_PUBLIC_PATHS` (app.py:221-222), so it needs a live account session, else `redirect("/")` (app.py:247-252). login.html then links to `setup.html`/`index.html` as static files, which `_block_project_file_exposure` 404s (they are not on the allow-list, app.py:183-190). | DEAD/decorative — a fake client-side-only login with no real gate. |
| `setup.html` | Similarly localStorage-only (`api_key`, `api_secret`, `setup_skipped`) — a leftover onboarding page for the legacy JWT/API-key model, gated server-side by `@require_auth` (JWT) which is unreachable without the PIN session but reachable post-PIN (see the corrected contradiction above). | LEGACY/orphaned. |

### iOS wrapper — `BiometricGateView.swift` / `DashboardWebView.swift`
| Field | Detail |
|---|---|
| Where | `ios/ParthS/ParthS/BiometricGateView.swift`, `ios/ParthS/ParthS/DashboardWebView.swift` |
| What | `BiometricGateView` is a THIRD, OS-level gate in front of the dashboard's own PIN screen (device Face ID/passcode via `LocalAuthentication`'s `.deviceOwnerAuthentication` policy) — answers "is this Parth's device", not "does this session hold the API secret". If no biometrics/passcode configured on the device, falls through to the dashboard's own PIN screen (`status = .unavailable; onUnlocked()`) rather than blocking entirely. `DashboardWebView` loads the real `index.html` unmodified in a `WKWebView` (comment: "same lock screen, same 13 tabs" — nothing duplicated). Supplies a `WKUIDelegate` for JS `alert`/`confirm`/`prompt` dialogs — without it, WKWebView silently drops these and `confirm()` resolves `false`, which per the code comment previously made 14 confirm-gated actions (Buy/Sell/Close-all/F&O orders/Logout) silently do nothing in the app (fail-closed, but confusing). |
| Network target | `DashboardTarget.url`: Simulator → `http://localhost:8000` (shares the Mac's network stack directly); real device → `https://parths-macbook-air.tailfba767.ts.net` (a Tailscale MagicDNS name). Comment claims this is served via **Tailscale Serve** proxying to `127.0.0.1:8000`, terminating TLS with a real Let's Encrypt cert, restricted to devices on the same tailnet — this is a code-comment CLAIM, **UNKNOWN — NOT DETERMINABLE FROM THIS REPO** whether Tailscale Serve/Funnel is actually configured/running (no tailscale config file in repo; per COMMON_RULES this can't be verified from the repo alone). |
| Status | ACTIVE per code; live Tailscale exposure state unverified. |

### Network exposure
| Field | Detail |
|---|---|
| `FLASK_HOST` | `config.py:42`, env var `FLASK_HOST`, default `"127.0.0.1"` (loopback-only default). Set in `.env` (name confirmed present; value not read here per COMMON_RULES). |
| `FLASK_PORT` | `config.py:43`, env var `FLASK_PORT`, default `"5000"`. Set in `.env` (name confirmed present). Code elsewhere (fyers redirect_uri comment, iOS wrapper) references port 8000, implying the live `.env` value is 8000, not the coded default — INFERENCE, not a direct read of the value. |
| `ALLOWED_ORIGINS` | env var, comma-separated, defaults built from `FLASK_PORT` + hardcoded `localhost:3000`/`127.0.0.1:3000` (a `frontend/` Next.js app referenced in a comment, not investigated — out of scope). |
| launchd | `launchd/com.parthsharma.parths.flask.plist` — exists in the repo but is **not installed/loaded** (verified 2026-09-28: `launchctl print gui/501/com.parthsharma.parths.flask` → "Could not find service"; the app currently runs via `start-all.sh`). If loaded, it runs via a `/bin/bash` wrapper; no `FLASK_HOST`/`FLASK_PORT` overrides found in the plist itself (checked `EnvironmentVariables`/`ProgramArguments` keys — none set there), so these come from `.env` at process start via `config.py`'s `load_dotenv()`. |
| Tailscale | UNKNOWN — NOT DETERMINABLE FROM CODE (per COMMON_RULES and the iOS wrapper's own comment caveat above). Referenced only in code comments (app.py:177 "the moment Tailscale made this reachable from other devices on the tailnet", DashboardWebView.swift) as established historical fact for *why* static-file exposure and CORS were hardened, not as current live proof. |

### Secrets inventory (env var NAMES only, from `.env`)
`ALLOWED_ORIGINS`, `APP_DEVICE_TOKEN`, `APP_PIN_HASH`, `DB_URL`, `FLASK_HOST`, `FLASK_PORT`, `FYER_ACCESS_TOKEN`, `FYER_APP_ID`, `FYER_PIN`, `FYER_REFRESH_TOKEN`, `FYER_Redirect_URL`, `FYER_SECRET_ID`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GROWW_ACCESS_TOKEN`, `GROWW_API_KEY`, `GROWW_API_SECRET`, `MAX_POSITIONS`, `MAX_TRADE_QUANTITY`, `MAX_TRADE_VALUE`, `NEWS_API_KEY`, `STOP_LOSS_PCT`, `TARGET_PCT`, `WATCHLIST`, `XGB_LIVE_TRADING`.
Notably **absent from `.env`**: `JWT_SECRET` (auth_manager.py falls back to a hardcoded insecure literal — see Legacy JWT section), Telegram's `telegram_bot_token`/`telegram_chat_id` (these live in `config_settings`, a DB table, not `.env`).
Secret-looking literal committed to git: `git grep -n -I -E "eyJ[A-Za-z0-9_-]{20,}\."` → **one hit**, `archive/dead_code/check_token.py:5` — matches the already-known expired Groww JWT (per task brief); no new hits found. Value not printed.

### XSS sinks — external text rendered unescaped via `innerHTML` (verified current line numbers)
| File:line | Field rendered | Source |
|---|---|---|
| `index.html:9204` | `${a.title}` inside an `<a>` | news article title (relevant/connected global news) |
| `index.html:9360` | `${a.title}` | market-news article title |
| `index.html:9412` | `${a.title}` | article title, `_newsArticleRow()` helper |
| `index.html:9424` | `${p.title}` | X/Twitter post title, `_xPostRow()` helper |
| `index.html:9563` | `${a.title}` | stock-news-detail article title |
| `index.html:10099` | `${h.title}` | supply-chain-disruption headline title |
All six confirmed unchanged from the task brief's estimates (grepped fresh against current working tree). Each is built via a JS template literal assigned to `.innerHTML` with no escaping of `.title`/`.source`/`.tags` fields, all of which originate from external feeds (`global_news`, `news_articles`, scraped X posts, disruption headlines) rather than the user's own input — so this is a stored/reflected XSS risk if any upstream feed ever contains HTML/script in a headline, not a risk from the operator's own actions. The same lines also interpolate `href="${a.url}"` unescaped (attribute break-out / `javascript:` URLs). Not fixed (read-only task).

### Error-detail leakage
`jsonify({"error": str(e)})` (or the `str(e)`-in-body pattern) appears **115** times in `app.py` (`grep -c`, exact pattern; 140 lines including variants such as `"error": str(e)`) — each exposes the raw Python exception string to the client on a 500/400. Not audited line-by-line for which specific ones might leak a stack detail vs. a safe message (out of scope for a line-by-line pass here); flagged as a broad pattern per the task brief.

### Telegram command authorization — `telegram_commander.py`
| Field | Detail |
|---|---|
| Where | `telegram_commander.py:1277-1333` |
| What | Every inbound Telegram update (both `_handle_callback` for button presses and `_handle_message` for text/commands) compares the sender's chat id against the configured `telegram_chat_id` (`_get_config()`, line 51-53, itself read from `config_settings` — secret, not printed) via `str(sender_chat_id) != str(chat_id)` / `str(msg_chat_id) != expected_chat_id`. Mismatch → button press gets "Unauthorized" answered inline (1284); message is silently ignored with a `logger.warning` (1312) — no reply sent, so an unauthorized prober gets no signal the bot exists. |
| Assessment | Single-operator system: one hardcoded allowed chat id from config, string-compared (not constant-time, but chat ids are not secrets you'd brute-force meaningfully here — Telegram's own auth already gates who can message the bot at all). Fail-closed on mismatch (ignore/reject, not default-allow). |
| Status | ACTIVE. |

### Security-boundary map (who can reach what, with what credential)
| Caller | Credential | Can reach |
|---|---|---|
| Anyone on the network path to the Flask port, no cookie | none | `/`, static allow-listed files (manifest/icons/deck.pdf), `/api/session` (boolean only), `/api/auth/providers`, `/api/unlock` (rate-limited to 5/2min per IP), `/fyers_callback` (`/api/fyers/complete-login` is NOT reachable without a PIN session: it is a POST under `/api/`, needing `pin_ok` + `X-Requested-With`), Google OAuth start/callback (public by necessity — no session exists yet) |
| Browser with correct PIN | session cookie, `pin_ok=true` | every `/api/*` endpoint including money paths (buy/sell/paper-toggle/cash-auto-trade) — no further re-auth step-up exists today (`sudo_until` unused) |
| Browser with Google-signed-in cookie, PIN not yet entered | session cookie, `account=true` only | `/app` page shell (renders the PIN pad), `/api/logout` — NOT any other `/api/*` |
| Scheduler / same-process background tasks | `X-Service-Token` (per-process random, loopback-only) | everything `_require_session` gates, bypassing PIN entirely — by design, same trust boundary as the process itself |
| Telegram bot commands | Telegram's own chat-id match against `telegram_chat_id` config | the bot's own command surface (trading overview, pause/resume, paper-mode toggle, etc. — a parallel money-affecting control plane outside the HTTP session model entirely) |
| iOS app | device Face ID/passcode (`BiometricGateView`) THEN the same PIN as the web dashboard (rendered inside `WKWebView`, no bypass of the HTTP session gate) | same as "browser with correct PIN" above, once through both gates |
| Anyone who obtains a live `sid` cookie (theft, XSS via the sinks above, shared device) | the cookie itself | everything the PIN-unlocked browser could do, until idle/absolute timeout — this is the actual value of the XSS sinks: a compromised feed title could exfiltrate or ride the session, though the cookie is HttpOnly so JS can't read the raw value, only ride along with same-origin fetches |

### Cross-cutting facts (for the maps)

- **External services**: `accounts.google.com` (OIDC authorize), `oauth2.googleapis.com` (token exchange + JWKS via google-auth lib), `api.telegram.org/bot{token}/{method}` (Telegram Bot API, polling), FYERS OAuth (redirect_uri `http://127.0.0.1:8000/fyers_callback` — see FYERS section owner for rate limits).
- **Env vars read (auth-relevant)**: `APP_PIN_HASH`, `APP_DEVICE_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_ORIGINS`, `FLASK_HOST`, `FLASK_PORT`, `JWT_SECRET` (NOT set — insecure hardcoded fallback in effect), `ALLOW_DEMO_LOGIN` (gates `/api/auth/demo`, unset by default).
- **config_settings keys (auth/session/idempotency, all confirmed present in DB, LAST VERIFIED 2026-09-27)**: `auth.idle_minutes`=30, `auth.absolute_hours`=12, `auth.account_days`=30, `auth.allowed_emails` (value not queried, PII-adjacent), `auth.landing_enabled`=false, `auth.provider.google`=false, `auth.provider.apple`=false, `auth.provider.email`=false, `idempotency.require_key`=0, `idempotency.retention_hours`=48. Telegram: `telegram_bot_token`, `telegram_chat_id` (values secret), `telegram_enabled`=true, `telegram_cost_notifications`, `scheduler_interval_telegram_summary`.
- **DB tables read/written**: `auth_sessions` (rw, `auth_session.py`), `users` (rw, shared by `auth_manager.py` + `google_auth.py`), `idempotency_keys` (rw, `db_manager.py` + `app.py`'s `idempotent()`), `config_settings` (r, all of the above).
- **Timed/triggered execution**: session cache eviction is time-based-on-read (`CACHE_SECONDS=30`, no separate timer); `purge_expired(days=7)` runs at startup only (its only caller is app.py:8212 — verified across all source; no scheduler task); idempotency key pruning (`prune_idempotency_keys`) runs from scheduler task `prune_idempotency` (scheduler.py:673-678; registered every 3600 s with `initial_delay=120`, scheduler.py:1335) and reads `idempotency.retention_hours`.
- **Rate limits & quotas**: PIN unlock — 5 attempts / 2 min / source IP, sliding window, in-memory (resets on app restart). The 2-min window is an UNCOMMITTED working-tree edit; committed HEAD is 15 min. No rate limit found on `/api/auth/google/start` or `/callback` (relies on Google's own throttling + the allow-list).
- **Data flows**: PIN entry (index.html) → `POST /api/unlock` → SHA-256 compare → `auth_session.create/promote` → `Set-Cookie` → every subsequent `/api/*` call reads the cookie via `_require_session`. Google sign-in: landing.html button → `/api/auth/google/start` → Google consent → `/api/auth/google/callback` → `users` table (create/link) → `auth_session.create(pin_verified=False)` → redirect to `/` → dashboard's own PIN pad.
- **Failure modes**: `auth_session.load()` fails closed (locked) on any exception. `/api/unlock` fails closed if `APP_PIN_HASH`/`APP_DEVICE_TOKEN` unset (500, not open). CSRF/Origin check fails closed (403/401) on disallowed origin. Telegram command auth fails closed (ignore/reject on chat-id mismatch). Counter-example / known-risky pattern: `sudo_until` exists but is **unused** — no step-up re-auth guards `/api/paper-trading/toggle` (a real-money-mode switch) beyond the general PIN session.
- **Dead / legacy / retired code**: `auth_manager.py`'s JWT signup/login/verify/profile/set-api-key/demo routes, `/dashboard`, `/setup` (unreachable without the PIN session, but reachable — and JWT-forgeable via the fallback secret — by anyone already PIN-unlocked or holding the service token); `auth_manager.authenticate_google` (no callers); `login.html` (localStorage-only fake login, no server calls); `setup.html` (localStorage-only, orphaned); `/api/auth/google` GET (app.py:1146, an incomplete stub distinct from the real `/api/auth/google/start`+`/callback` pair); `archive/dead_code/check_token.py` (known expired Groww JWT, confirmed present, value not printed).
- **Contradictions found**: (1) Legacy JWT auth routes exist and are imported/wired in `app.py` but have no callers and are unreachable without the PIN session (or a service token), but are NOT structurally unreachable — post-PIN they are reachable and JWT-forgeable via the fallback secret — the two auth generations were never reconciled or removed. (2) `google_auth.py` + `.env` Google credentials are fully implemented and wired, but the `auth.provider.google` config switch is off, so the landing-page button is hidden — yet the OAuth flow itself is live (`/api/auth/google/start|callback` are public and never check that flag, app.py:1031-1040), so anyone can start it by URL and the one allow-listed Google account can complete it. (3) `landing.html`'s email/password forms exist with client-side validation but are provably inert (no network call) — a visitor could reasonably believe they're creating an account; nothing to fix, per read-only task, but worth the user knowing the form is decorative if they haven't already accounted for that in their plan. (4) CLAUDE.md's Security hardening A-E note (C = scrypt PIN, lockout, PIN→8 digits, "waiting for go") matches what's found: PIN hashing is still SHA-256 (no salt visible in `/api/unlock`'s comparison — it hashes the raw PIN with no per-install salt beyond `APP_PIN_HASH` itself being a fixed target), 4-digit PIN (`index.html` `_pinBuf.length >= 4`), and lockout (5/2min IP-keyed — the 2-min window is an uncommitted edit, committed HEAD is 15 min; the PIN comparison is also a non-constant-time `!=`) is already built — consistent with "A+B built, C planned."
- **Open unknowns**: live value of `auth.allowed_emails` (the verifier confirmed it is non-empty, 1 entry; the value itself is not recorded, borderline PII); whether `.env`'s `APP_PIN_HASH` was generated with any per-install salt or is a bare `sha256(pin)` (the server-side compare in `/api/unlock` is a bare `sha256` with no salt, so VERIFIED: no salting occurs no matter how the hash was produced, since the compare itself is saltless); actual live Tailscale Serve/Funnel configuration (not in repo); whether any code path still calls `auth_manager.authenticate_google`/legacy routes from a context that already holds a session (would make them theoretically reachable, if pointless); FYERS-specific auth details (owned by another section).
## Market Data (FYERS, Groww, candles, quotes, tokens)

Overview: FYERS is the **live** market-data provider (quotes, candles) for the whole trading path since the Groww migration; Groww is retained for F&O option chains, Indian index quotes (`fno_trader._fetch_groww_indices`), portfolio/holdings, order placement (out of scope here) and a handful of legacy/manual historical-data scripts that write to the pre-FYERS `stock_prices`/`candles` tables. All FYERS REST calls funnel through one chokepoint (`fyers_client._request`) with a token-bucket limiter, a two-layer quote cache, and 429 cooldown. Candles live in the partitioned `fyers_candles` table (resolutions D/1/5S), backfilled per-symbol on watchlist-add and kept fresh by throttled top-up jobs. FYERS access tokens expire daily at 06:00 IST with **no working unattended refresh** (FYERS disabled it for SEBI compliance) — a human OAuth login is required every day. The Groww token, by contrast, IS renewed unattended while the app runs: scheduler task `token_refresh` fires hourly (scheduler.py:1301 -> `_task_token_refresh` -> `check_and_refresh()`) and `check_and_refresh()` also runs once at app import (app.py:781-786). The FYERS WebSocket client exists, is wired to start at boot, but is **disabled by live config** (`fyers.ws_enabled=false`) and its `set_symbols()` has zero callers anywhere in the repo — it is fully inert.

LAST VERIFIED: 2026-09-27 (config/DB values below; FYERS token 15:36 IST; Groww token 10:07 UTC). The two token LIVE CHECK rows are a **2026-09-27 snapshot**: on re-verification at 2026-09-28 21:59 IST (local JWT decode) BOTH tokens were **EXPIRED** and the app was not running (nothing listening on :8000; `.env` mtime 2026-09-27 09:23), so the hourly Groww refresh was not firing either.

---

### `fyers_client.py` — module (REST chokepoint)
| Field | Detail |
|---|---|
| Where | `fyers_client.py:1-336` |
| What / Why | Thin wrapper over FYERS Data API v3 (read-only market data). Single outbound chokepoint (`_request`, line 171) for every FYERS HTTP call — token bucket, cooldown, JSON-safety all live here. |
| Used by (callers) | `fyers_market_data_provider.py` (`to_fyers_symbol` DB lookup aside, all HTTP goes through here), `fyers_historical_backfill.py`, `fyers_ws_client.py` (auth header only, NOT `_request` — WS bypasses the REST limiter by design, see below) |
| Calls | FYERS Data API (`https://api-t1.fyers.in/data/...`), `fyers_auth.auth_header()` |
| When | Every live quote/candle/backfill request |
| Inputs | `path`, `params`, `timeout` |
| Outputs / side effects | `(status_code, payload_dict)`; never raises on non-JSON (429 HTML page handled explicitly, `fyers_client.py:193-199`) |
| DB tables | none directly (config read via `db_manager.get_config`) |
| Config / env | `fyers.rate_per_sec` (DB, default 2.5/s), `fyers.burst` (DB, default 5), `fyers.quote_ttl_seconds` (not in DB — literal fallback 2.0s, VERIFIED FROM DATABASE absent), env fallback via `KEY.upper().replace('.','_')` |
| External services | FYERS Data API v3 |
| Rate limits / cost | Token bucket `_acquire_token` (line 108); 429 → `_note_429` exponential backoff 5s→10s→20s...capped 300s (line 138); lock-protected (`_bucket_lock`) after a proven race (see docstring 138-155 and CLAUDE.md op-rule 9) |
| Failure behaviour | Fail toward safety: literal rate default (2.5/s=150/min) intentionally kept UNDER the 200/min Standard cap after an incident where the old default (5.0/s=300/min) was unsafe (lines 56-70). `in_cooldown()` short-circuits without a network call. |
| Security | No secrets logged; `auth_header()` reads token from env |
| Performance | `_ReqCounter` (line 205) — real outbound call count, exposed via `request_count()`, used to measure cache effectiveness |
| Blast radius | Every live price, every quote, every candle fetch in the whole system |
| Status | ACTIVE |

### `get_quotes` / `get_ltp` / caching layers — functions in fyers_client.py
| Field | Detail |
|---|---|
| Where | `get_quotes` `fyers_client.py:265-309`; `get_ltp` `fyers_client.py:312-321`; cache `_quote_cache` line 75, `quote_ttl()` line 104 |
| What / Why | **Cache layer 1** (module-level, TTL from `quote_ttl()` = `fyers.quote_ttl_seconds` config, literal default `_DEFAULT_QUOTE_TTL=2.0`s). Symbols with a fresh cache entry are served without a network call; only stale/missing symbols go out as ONE batched `quotes` call (up to whatever the caller passed — chunking to 50 happens one layer up). |
| Used by (callers) | `fyers_market_data_provider._get_quotes_cached` (line 76, in a loop over 50-symbol chunks) → this is **cache layer 2**, a SEPARATE dict (`_quote_cache` in `fyers_market_data_provider.py:33`, TTL `_QUOTE_CACHE_TTL=2.0`s hardcoded, not config-driven) |
| Calls | `_request("quotes", ...)` |
| TWO CACHE LAYERS (as required) | (1) `fyers_client._quote_cache` / `quote_ttl()` — config-driven, 2.0s default; (2) `fyers_market_data_provider._quote_cache` / `_QUOTE_CACHE_TTL` — hardcoded 2.0s constant, not read from config. A quote request from `FYERSMarketDataProvider` can be served from layer 2 without ever reaching layer 1's cache check; only a layer-2 miss reaches `fyers_client.get_quotes`, which then applies its own cache again. |
| 50-symbol chunking | `fyers_market_data_provider.py:26` `_QUOTES_BATCH_SIZE = 50`, applied in `_get_quotes_cached` (line 74 loop). `fyers_client.get_quotes` itself does **not** chunk — it trusts the caller. |
| Status | ACTIVE |

### Full live-price path — call sites (VERIFIED FROM CODE via grep + docs/function_inventory.json edges)
`bot.fetch_live_price(symbol)` (`bot.py:309-327`) → `FYERSMarketDataProvider().get_ltp()` (`fyers_market_data_provider.py:96-102`) → `_get_quotes_cached([sym])` → `fyers_client.get_quotes` → `_request`. Per-symbol, not batched, unless caller pre-batches.

Batched path: `FYERSMarketDataProvider().get_ltp_batch(symbols)` (`fyers_market_data_provider.py:104-111`) — used only by `bot.scan_watchlist_xgb()` (`bot.py:633`) and `bot.monitor_and_update_trailing_stops()` (`bot.py:1961`, MONEY PATH, trailing-stop evaluation, with per-symbol `fetch_live_price` fallback for symbols the batch missed, line 1977).

22 real call sites of `fetch_live_price` (grep-confirmed against `docs/function_inventory.json` edges, which lists the same count):
| Caller | file:line | Context |
|---|---|---|
| `bot.get_prediction` | bot.py:1073 | GBC model inference |
| `bot._predict_one` | bot.py:1218 | fallback price |
| `bot.place_buy` | bot.py:1658 | **MONEY PATH** — order entry pricing |
| `bot.place_sell` | bot.py:1789 | **MONEY PATH** — order exit pricing |
| `bot.monitor_and_update_trailing_stops` | bot.py:1977 | **MONEY PATH** — per-symbol fallback only |
| `bot.auto_trade` | bot.py:2229, 2397 | loop, entry/exit sizing |
| `bot.analyze_portfolio` | bot.py:2532 | display |
| `groww_market_data_provider.GrowwMarketDataProvider.get_ltp` | groww_market_data_provider.py:51 | class itself has ZERO callers (see below) |
| `paper_trader.get_live_price` | paper_trader.py:385 | aliased `bot_fetch_live_price` |
| `peer_analyzer.update_peer_prices` | peer_analyzer.py:258 | loop |
| `telegram_commander._cmd_positions/_cmd_watchstock/(unnamed)` | telegram_commander.py:494,595,899 | Telegram bot commands |
| `app.cost_estimate` | app.py:3119 | endpoint |
| `app._do_watchlist_analysis` | app.py:4358 | endpoint |
| `app.live_price` | app.py:4824 | `/api/live-price` endpoint |
| `app.journal_close` | app.py:5123 | endpoint |
| `app.get_my_thesis / create_my_thesis / get_thesis_projection` | app.py:5385,5415,5449 | endpoints |
| `app.stream_prices.generate` | app.py:7350 | SSE stream, loop |
| `check_groww_market_data.py:46` | manual diagnostic script | not an active path |

`paper_trader.get_live_price` (`paper_trader.py:373`) wraps `bot.fetch_live_price` and is itself called from: `app.api_close_trade` (app.py:1293), `app.check_trailing_stop_exits` (app.py:6495, loop), `app._get_latest_symbol_price` (app.py:7468), `paper_trader.main` (line 519, loop), `scheduler._task_auto_close_trades` (scheduler.py:862, loop — **MONEY PATH**), `analyze_losses.py:32` (manual script).

`bot.fetch_quote` (`bot.py:330-372`, normalizes FYERS shape to Groww-era keys) has 5 callers: `app.quote` endpoint (app.py:4833), `fundamental_analysis._get_groww_quote_fundamentals` (line 337), `fundamental_analysis._fetch_competitor_prices` (line 584, loop), `groww_market_data_provider.GrowwMarketDataProvider.get_quote` (unused class), `peer_analyzer.update_peer_prices` (line 264, loop).

`get_ltp_batch`: **0 static callers found by function_inventory** but grep confirms 2 real call sites (`bot.py:633`, `bot.py:1961`) — a static-analysis gap (dynamic import inside functions), noted per COMMON_RULES limitation.

**N+1 query (CLAUDE.md standard #1)**: `FYERSMarketDataProvider.to_fyers_symbol()` opens a session and SELECTs `master_ticker_table` once per symbol (`fyers_market_data_provider.py:47-52`). `get_ltp_batch` over the 67-symbol watchlist therefore makes 67 DB queries before its 2 FYERS calls, on every XGB scan (~every 15s) and on every `fetch_live_price`.

---

### Rate limiting — computed (INFERENCE + VERIFIED FROM CODE/DB)
| Parameter | Value | Source |
|---|---|---|
| `fyers.rate_per_sec` | 2.5/s = 150/min | VERIFIED FROM DATABASE (config_settings), LAST VERIFIED 2026-09-27 |
| `fyers.burst` | 5 | VERIFIED FROM DATABASE |
| Worst-case bucket output (single process) | 7.5 requests in any 1s window (burst 5 + rate 2.5) and 155 in any 60s (5 + 150) — both under the 10/s and 200/min caps | INFERENCE from token-bucket math (verified 2026-09-27) |
| Literal fallback rate | 2.5/s (`_DEFAULT_RATE`, fyers_client.py:71) | VERIFIED FROM CODE — deliberately matches the tuned-safe DB value after a prior unsafe-fallback incident (lines 56-70) |
| FYERS documented cap | 10/s, 200/min Standard; 600/min Prime | documented-in-repo, `docs/FYERS_MIGRATION_MASTER_REPORT.md` §10 |
| Watchlist size | 67 active (`SELECT count(*) FROM stocks WHERE is_active`) | VERIFIED FROM DATABASE, LAST VERIFIED 2026-09-27 |
| Requests per watchlist scan (batched, `get_ltp_batch`) | ceil(67/50) = 2 requests | INFERENCE from `_QUOTES_BATCH_SIZE=50` chunking |
| Requests per watchlist scan (unbatched/cold-cache worst case) | up to 67 (one per symbol, if cache misses and no batching) | INFERENCE |
| Sustainable requests/day at 150/min cap, 24h | 216,000 theoretical; FYERS's documented account-level cap is 100,000/day | documented-in-repo — the daily cap binds first, not the per-minute rate |
| 429 cooldown | starts 5s, doubles per consecutive 429, capped 300s (`_note_429`, fyers_client.py:138-161) | VERIFIED FROM CODE |
| Locking | `_bucket_lock` reused for `_cooldown_step`/`_cooldown_until` read-modify-write after a proven unsafe race (measured: 5 threads racing an unlocked update lost updates) | VERIFIED FROM CODE (docstring cites the measurement, lines 144-155) |

Boot-time burst risk (separate mechanism, `fyers_boot_warmup.py`): without coordination, a 67-symbol watchlist scan on process restart would fire ~67 uncoordinated FYERS requests (measured historically to trigger 429→300s cooldown, `fyers_boot_warmup.py:12-16`). Fixed by a sequential, paced (`_DEFAULT_EXTRA_PACE_SECONDS=0.3`s), single-worker warm-up pass gated on a valid token (`_wait_for_token`, timeout 45s default) before any bulk scanning resumes. `fyers.boot_warmup_*` keys are **not present in config_settings** (VERIFIED FROM DATABASE — 0 rows), so all boot-warmup behavior currently runs on literal fallbacks (enabled=true, timeout=150s, pace=0.3s, token_wait=45s).

---

### Candles — storage & backfill
| Field | Detail |
|---|---|
| Resolutions stored | `D` (daily), `1` (1-minute), `5S` (5-second) — `fyers_historical_backfill.py:46` `MAX_DAYS = {"D":366, "1":100, "5S":100}` (confirmed hard request-window caps, comment "101+/367+ returns error -50") |
| Backfill ranges | `DAILY_FLOOR = 1997-06-25` (line 42, confirmed on RELIANCE+ITC); `MINUTE_FLOOR = 2017-07-03` (line 43); `SECONDS_LOOKBACK_DAYS = 35` (line 44, real window ~25-30 trading days, FYERS truncates) |
| Trigger | `backfill_symbol()` runs per-symbol from the Watchlist-add flow AND automatically from the hourly `self_healing` scheduler task (scheduler.py:704-724, registered scheduler.py:1303 -> `self_healing.py:205`) for watchlist symbols missing FYERS data (capped per run, deferred while the market is open); also manual via `fyers_backfill_all_watchlist.py:57`. Never a full-universe automatic job (module docstring, lines 22-24) |
| `_store` ON CONFLICT behaviour | `INSERT ... ON CONFLICT (symbol, provider, resolution, ts) DO NOTHING` (fyers_historical_backfill.py:164) — **re-backfilling does NOT create duplicates or re-download DB rows**, but it DOES re-fetch the full API range every time `backfill_symbol()` is called directly (no fetch-level skip inside that function itself) — VERIFIED FROM CODE, doc comment at `topup_daily` (lines 271-289) states this explicitly: "64 API calls per symbol, ~947k rows re-fetched to insert a few hundred". Row-count is measured via before/after `count(*)`, not `cur.rowcount`, because `execute_values` pagination made `rowcount` reflect only the last internal page (measured: reported 51, actual 834,251 — lines 143-145) |
| Resume-level dedup | `fyers_backfill_all_watchlist.py` (bulk driver) DOES skip fetch-level work for symbols already having all 3 resolutions (`_EXPECTED_RESOLUTIONS`, lines 19, 33-39) — this is the only script-level skip; `backfill_symbol()` itself has no such guard |
| OHLC repair | Malformed bars (high/low not bracketing open/close) are REPAIRED (max/min reconstruction) not dropped — measured 227/835,641 KOTAKBANK 1-min bars (0.027%) affected, 85% simple transpositions (fyers_historical_backfill.py:88-131). Only non-positive-price bars are dropped (a handful of pre-2001 daily bars). |
| `ensure_recent()` freshness top-up | `fyers_historical_backfill.py:226-259`; TTL 300s in-process throttle (`_FRESHNESS_TTL_SECONDS`), lookback 3 days, tops up '5S' tier only. Called from `bot.fetch_historical()` (bot.py:275) on effectively every prediction. |
| `topup_daily()` | `fyers_historical_backfill.py:271-347` — separate daily-tier top-up (ensure_recent only refreshes '5S'), one API call per symbol in steady state, batched latest-bar + FYERS-symbol lookups (no N+1). **Scheduled hourly** as `fyers_daily_topup` (`_task_fyers_daily_topup`, scheduler.py:885-910, registered scheduler.py:1321, initial_delay 200s), skipped while the market is open / during boot warm-up |
| `fyers_fill_1min_gap.py` | fills the ~37-day gap left by the 1-min/5S tier split, per-symbol single fetch from last stored '1' bar forward; manual/maintenance script, no scheduler reference found in scope |
| Partitions | Yearly, 1997–2028 (`db/fyers_candles_schema.sql:50-59`); 32 partitions confirmed VERIFIED FROM DATABASE (pg_class query, LAST VERIFIED 2026-09-27) |
| Row estimates (pg_class.reltuples) | Sum ≈ 70.8M rows across populated partitions (1997-2026); 2026 partition alone ≈ 19.0M (current year, densest 5S/1-min data); 2027/2028 empty (-1 = never analyzed). VERIFIED FROM DATABASE. |
| `resolution='D'` symbol coverage | 69 distinct symbols with daily bars, VERIFIED FROM DATABASE |
| Unique constraint | `UNIQUE (symbol, provider, resolution, ts)`, composite `PRIMARY KEY (id, ts)` required because Postgres partitioned-table PKs must include the partition key (schema comment, lines 12-17) |
| OHLC sanity | `CHECK (low<=open AND low<=close AND high>=open AND high>=close AND low<=high)` — DB-enforced (schema line 36-40); backfill repair logic exists precisely so no row can violate this |
| Status | ACTIVE (primary candle store for training + inference) |

---

### FYERS token lifecycle
| Field | Detail |
|---|---|
| Login | OAuth authcode flow — human logs into FYERS in their own browser, pastes back auth_code/redirect URL (`fyers_auth.get_login_url`, `complete_login`, lines 41-144) |
| Expiry | Fixed 06:00 IST daily `exp` claim in the JWT (`token_expiry()`, fyers_auth.py:147-166, local decode, no API call) |
| **LIVE CHECK (2026-09-27 15:36 IST — SNAPSHOT)** | Token was valid until **2026-09-28 06:00:00+05:30** (~14.4h remaining at check time) — VERIFIED via local JWT decode, not a log line. **Re-check 2026-09-28 21:59 IST: EXPIRED** (local JWT decode via `fyers_auth.token_expiry`); app not running |
| Unattended refresh | `refresh_if_needed()` (fyers_auth.py:169-229) exists and would work in theory (refresh_token + PIN, no user interaction) BUT: **FYERS's refresh-token API is DISABLED for SEBI compliance** — confirmed live 2026-08-16, error `code=-16 "Refresh token API is currently disabled to comply with SEBI regulations"` (lines 211-226, hardcoded detection of this exact error). So unattended renewal is **impossible today** despite the code path existing — a docstring/behavior contradiction: the "runs unattended, same as Groww's" wording lives in `refresh_access_token()`'s docstring (fyers_auth.py:95-98) and in the `_task_fyers_token_refresh` docstring (scheduler.py:728-735, "renews unattended"), NOT in the module docstring (which says the opposite — no fully-unattended daily refresh like Groww's, fyers_auth.py:13-18); the actual FYERS endpoint returns a hard block. The scheduler still calls it: `_task_fyers_token_refresh` runs hourly (scheduler.py:727-740, registered scheduler.py:1302) -> `fyers_auth.refresh_if_needed()`, which today always fails with code=-16 and logs an ERROR once the token is within 30 min of expiry. |
| What happens on expiry | Every FYERS REST call fails (`_request` gets non-200/error from `auth_header()`'s stale token); `fyers_boot_warmup._wait_for_token` will abort warm-up after 45s if a restart happens with an expired token (aborts rather than retrying — no amount of waiting fixes a SEBI-blocked refresh); WS supervisor (`_run`, ws client) simply stops issuing connection attempts and polls every `fyers.ws_token_recheck_seconds` (default 60s) until a human re-logs in |
| Where saved | `.env` (`FYER_ACCESS_TOKEN`, `FYER_REFRESH_TOKEN`) via `_update_env_file` (fyers_auth.py:117-128) — line-replace-or-append pattern |
| Status | ACTIVE, but daily-manual-login is a hard operational dependency (not automatable currently) |

### Groww token lifecycle
| Field | Detail |
|---|---|
| Model | key+secret exchange (`GrowwAPI.get_access_token`), NOT OAuth — `token_refresher.py:18-79` |
| Expiry | Daily ~6 AM IST (module docstring, token_refresher.py:4) |
| **LIVE CHECK (2026-09-27 10:07 UTC — SNAPSHOT)** | Token was valid until **2026-09-28 00:30:00 UTC** (= 06:00 IST) — VERIFIED via local JWT decode. **Re-check 2026-09-28 21:59 IST: EXPIRED** — the app was not running, so the hourly refresh below was not firing |
| Refresh | `refresh_token()` fully unattended (no PIN needed) — updates `os.environ`, `config` module, `.env`, and resets cached clients in `bot.py`/`price_fetcher.py` (lines 45-74) |
| Check-and-refresh | `check_and_refresh()` (line 110) does a live `get_user_profile()` call to test the token, refreshes only on an auth-shaped error string match (`"auth"`/`"expired"`/`"invalid"`/`"401"`) |
| Scheduled | **ACTIVE, hourly**: scheduler task `token_refresh` (registered scheduler.py:1301, every 3600s, initial_delay 0) -> `_task_token_refresh` (scheduler.py:695-700) -> `token_refresher.check_and_refresh()`; also run once at app import (app.py:781-786) |
| CLI/manual tools | `refresh_token_cli.py` (`--check`/`--refresh`), `get_token.py` (one-time setup script), `refresh-token.sh` (shell wrapper calling `token_refresher.check_and_refresh` via `.venv`) |
| What happens on expiry | Any Groww call (F&O option chain, holdings, order placement — order placement out of this section's scope) fails until refreshed; unlike FYERS this path IS unattended-refreshable, and a scheduled task DOES call `check_and_refresh()` hourly (scheduler task `token_refresh`, scheduler.py:1301; plus once at app import, app.py:781-786), so it stays alive automatically while the app is running |
| Status | ACTIVE for F&O/holdings; NOT the source of equity live prices or candles (that's FYERS-only, per `bot.fetch_live_price`/`fetch_quote` docstrings). Token renewal: ACTIVE (hourly scheduler task) |

---

### FYERS WebSocket (`fyers_ws_client.py`) — actual live state, not docstring
| Field | Detail |
|---|---|
| Enabled? | **`fyers.ws_enabled = false`** — VERIFIED FROM DATABASE (config_settings), LAST VERIFIED 2026-09-27. Description in DB: "Disabled: Portfolio Analysis uses the REST path and nothing else consumes the feed." |
| Started? | `fyers_ws_client.start_in_background()` IS called at boot (`app.py:8167-8171`), but `_enabled()` check (line 563) makes it a no-op — returns `None` immediately without starting a thread, since `_active` is set only after the enabled check passes |
| `set_symbols()` callers | **ZERO** anywhere in the repo — VERIFIED via `grep -rn "set_symbols"` (only definition + docstring self-references + a comment, `fyers_ws_client.py:263,14,525,550`). The docstring claims "Portfolio analysis already fetches holdings, so it calls set_symbols() instead" — this is **INTENT, not verified behavior**; no such call site exists. |
| Trading-path usage | None. Module docstring states "INERT BY DESIGN" (lines 4-9) and this is corroborated: `fetch_live_price`, `place_buy`/`place_sell`, trailing-stop monitor all read FYERS REST only. |
| Dashboard usage | `app.py:2748-2764` reads `fyers_ws_client.status()` for `/api/data-health` observability only, explicitly never marked "critical" (comment: "a red row for a feed nothing trades on would train the eye to ignore this panel") |
| Rate limiting | Deliberately NOT routed through `fyers_client._acquire_token()` — a long-lived connection isn't metered requests (module docstring, lines 30-35) |
| Token gating | `_token_ok()` (line 439) — local JWT decode only; connects zero times while the token is invalid, rechecks every `fyers.ws_token_recheck_seconds` (default 60s, not in DB — literal fallback) |
| Status | **DISABLED (by live config) + effectively DEAD CODE at the call-graph level** (`set_symbols` has no caller, so even if enabled, nothing would ever populate `_fy_to_nse` and the feed would track zero symbols). Everything else (reconnect supervisor, stall watchdog, freshness accessors `get_price`/`get_last_price`) is implemented and would work if both gaps were closed. |

---

### Groww vs FYERS — which data comes from which provider today
| Data | Provider | Evidence |
|---|---|---|
| Equity live price (`fetch_live_price`) | **FYERS only**, no Groww fallback | bot.py:309-327 docstring + code — explicit design choice |
| Equity quote (`fetch_quote`) | **FYERS only** | bot.py:330-372, normalized to Groww-era keys for compatibility |
| Equity historical/intraday candles (training + inference) | **FYERS only** (`fyers_candles` table) | bot.py:247-306 `fetch_historical`; explicit comment "No Groww fallback... the only path now" (lines 296-306) |
| F&O option chains / expiries | **Groww** (`fno_trader.get_option_chain`/`get_expiries`, fno_trader.py:377, 393) | `FYERSMarketDataProvider.get_option_chain` exists (fyers_market_data_provider.py:121-132) and has NO caller anywhere (verified: repo-wide grep for provider option-chain calls finds none) |
| Indian index quotes (NIFTY/BANKNIFTY/FINNIFTY/SENSEX/MIDCPNIFTY/INDIAVIX) | **Groww** (`fno_trader._fetch_groww_indices`, sequential `groww.get_quote` calls for 6 indices, fno_trader.py:1957-1999) | Feeds `get_global_sentiment`, which drives F&O and XGB-signal confidence — a Groww market-data dependency outside the FYERS pipeline |
| Legacy `stock_prices`/`candles` tables | **Groww** (`price_fetcher.py`, manual `/api/prices/fetch` endpoint, app.py:5465-5469) and ad-hoc **yfinance** (`fetch_google_prices.py`) | Both are legacy/manual, not part of the live FYERS pipeline |
| NSE instrument directory (`nse_instruments`, search/autocomplete) | **Groww** (`get_all_instruments`) | load_nse_instruments.py:19-52, manual/idempotent re-run |
| `master_ticker_table` universe + ISIN | **Groww** (universe+ISIN) joined with **FYERS public CSV master** (symbol mapping) by ISIN | build_master_ticker_table.py:46-93 |
| `GrowwMarketDataProvider` class | Defined, **wraps existing Groww call sites**, but **ZERO callers** anywhere (grep-confirmed) — matches its own docstring "Nothing currently calls this class... foundation for a future rewire" | groww_market_data_provider.py:1-10 |
| `collect_index_candles.py` | **BROKEN**: imports `from groww_api import get_historical_candles` — **`groww_api.py` does not exist in this repo** (confirmed: `ls groww_api.py` → No such file). The import sits inside `try/except ImportError`, so the script logs an error and returns — a silent no-op, not a crash (collect_index_candles.py:16-20). No caller found anywhere. | VERIFIED FROM CODE + filesystem check |

---

### `master_ticker_table` / `nse_instruments`
| Field | Detail |
|---|---|
| Built by | `build_master_ticker_table.py` — Groww universe (equities+3 known indices) joined to FYERS public NSE_CM.csv master by ISIN, plus read-only Tijori slugs from `external_slug_map` |
| Idempotency | Only rows whose mapped fields (`_MAPPED_FIELDS`, lines 111-116) actually changed are updated; deactivation for tickers no longer in the Groww universe (`is_active=False`), never deleted |
| Fields | `nse_ticker` (PK), `company_name`, `isin`, `exchange`, `segment`, `instrument_type`, `fyers_historical_symbol`, `fyers_websocket_symbol`, `fyers_token`, `fyers_isin`, `fyers_resolution_status`, `fyers_unresolved_reason`, `tijori_ticker`, `tijori_resolution_status`, `tijori_unresolved_reason`, `is_active`, `first_seen_at`, `last_seen_at`, `updated_at` (db_manager.py:256-296) |
| Resolution status counts | VERIFIED FROM DATABASE, LAST VERIFIED 2026-09-27: `fyers_resolution_status`: resolved=2465, unresolved=2 (total 2467, all `is_active`); `tijori_resolution_status`: not_attempted=2181, resolved=286 |
| `nse_instruments` row count | 2464 — VERIFIED FROM DATABASE. Separate, superseded-for-search table per `MasterTicker`'s own docstring (db_manager.py:266) |
| Directory vs collection | Explicitly a DIRECTORY — adding a row never fetches prices/subscribes/triggers Tijori collection (build_master_ticker_table.py:5-8) |
| Status | ACTIVE, re-run manually (no scheduler reference found in this section's scope) |

---

### Trivial / support scripts
| name | file:line | purpose | callers | status |
|---|---|---|---|---|
| `market_data_provider.MarketDataProvider` | market_data_provider.py:20-57 | Abstract provider-neutral interface | `FYERSMarketDataProvider`, `GrowwMarketDataProvider` implement it; no caller depends on the interface itself yet (docstring: "No existing Groww call site has been rewired to use it") | EXPERIMENTAL / FOUNDATION-ONLY |
| `fyers_backfill_all_watchlist.py` | 1-79 | Bulk-run `backfill_symbol()` over all `stock_prices` symbols, resumable | manual (`__main__`) | MANUAL/MAINTENANCE |
| `fyers_fill_1min_gap.py` | 1-81 | Fill the ~37-day 1-min gap left by tier split | manual (`__main__`); no scheduler reference in scope | MANUAL/MAINTENANCE |
| `collect_index_candles.py` | 1-87 | Fetch index candles via `groww_api` (module missing) into legacy `Candle` table | none found; the ImportError is caught (logs an error and returns — silent no-op) | BROKEN/DEAD |
| `price_fetcher.py` | 1-215 | 5-year Groww weekly-candle fetch into `stock_prices` | `app.py:5469` `/api/prices/fetch` endpoint (manual POST, background thread) | ACTIVE (manual trigger) |
| `fetch_full_history.py` | 1-247 | Multi-timeframe Groww V1 API fetch into legacy `candles` table, hardcoded `now = datetime(2026,4,1)` | none found (`__main__` only) | MANUAL/STALE (hardcoded date suggests one-off run) |
| `get_real_prices.py` | 1-54 | Print current prices for a hardcoded symbol list via Groww | none found (`__main__` script) | MANUAL/DIAGNOSTIC |
| `fetch_google_prices.py` | 1-176 | yfinance 5-year fetch for 3 hardcoded symbols into `stock_prices`, **unscoped `DELETE FROM stock_prices` (no WHERE) wipes the ENTIRE table** before re-inserting only 3 symbols (line 140, inside `__main__` at line 132; symbols at line 22) | none found (`__main__` only) | MANUAL/DESTRUCTIVE — dangerous if re-run casually |
| `load_nse_instruments.py` | 1-58 | Groww instrument master → `nse_instruments`, idempotent upsert | none found as an importer (`__main__` only) | MANUAL |
| `token_refresher.py` | 1-137 | Groww token auto-refresh | `scheduler._task_token_refresh` (hourly), app.py:781-786 (import-time), `refresh_token_cli.py`, `refresh-token.sh`; `bot._get_groww()` re-reads env independently (bot.py:142-160) rather than calling this module directly | ACTIVE (scheduled hourly via scheduler task `token_refresh`, scheduler.py:1301 -> `_task_token_refresh`, scheduler.py:695-700, plus app import app.py:781-786; also manual/CLI-triggered) |
| `refresh_token_cli.py`, `get_token.py`, `refresh-token.sh` | — | Manual Groww token CLI utilities | human-invoked | MANUAL |
| `check_groww_market_data.py` | 1-99 | One-shot diagnostic comparing control symbols vs TATAMOTORS via `bot.fetch_live_price` | manual | DIAGNOSTIC |
| `verify_api.py` | 1-32 | curls `localhost:8000/api/fno/backtest/instruments` to sanity-check the Flask API is up | manual | DIAGNOSTIC |

---

### DATA-FLOW diagram

```
PRICES (live):
  Dashboard poll / scheduler tasks (record_pnl, cash_auto_trade, fno_auto_trade:
  registered 5s, effective ~15s loop tick; auto_close_trades: DB interval 300s)
  / Telegram commands / place_buy/place_sell
        │
        ▼
  bot.fetch_live_price(symbol) / bot.fetch_quote(symbol)
        │
        ▼
  FYERSMarketDataProvider.get_ltp / get_quote / get_ltp_batch
        │  (to_fyers_symbol via master_ticker_table lookup — one SELECT per symbol, N+1)
        ▼
  _get_quotes_cached()  ── CACHE LAYER 2 (2.0s hardcoded TTL) ──┐
        │ (miss, chunked ≤50)                                   │ hit → return
        ▼                                                       │
  fyers_client.get_quotes() ── CACHE LAYER 1 (fyers.quote_ttl_seconds, 2.0s default) ──┐
        │ (miss)                                                                        │ hit → return
        ▼                                                                               │
  fyers_client._request() → _acquire_token (token bucket) → HTTP GET FYERS /quotes ◄────┘
        │
        ├─ 200 → _note_ok(), cache both layers
        └─ 429 → _note_429() cooldown (5s→300s), surfaced to caller as error dict

CANDLES (historical/backfill):
  Watchlist-add ──► fyers_historical_backfill.backfill_symbol()
        │  (D: 1997→today, 1: 2017→today-35d, 5S: today-35d→today, chunked ≤100/366 days)
        ▼
  fyers_client.get_historical_candles() → FYERS /history
        │
        ▼
  _fetch_resolution() [repairs malformed OHLC, drops non-positive]
        │
        ▼
  _store() → psycopg2 execute_values, ON CONFLICT DO NOTHING → fyers_candles (partitioned by year)
        │
        ▼
  Freshness top-ups: ensure_recent() [5S tier, called from bot.fetch_historical
  every prediction, 300s in-process throttle] + topup_daily() [D tier, 1 call/symbol]
        │
        ▼
  db_manager.CandleDatabase.get_fyers_candles_as_5min() / get_fyers_1min() / get_fyers_daily()
        │  (UTC→IST→naive conversion, tier-dedup per 5-min bucket to avoid double-counting volume)
        ▼
  bot.fetch_historical() / fetch_5min_for_training() / fetch_5min_for_inference()
        │
        ▼
  GBC / XGB predictors (training + live inference)

TOKENS:
  Human OAuth login (FYERS, daily, unattended refresh SEBI-disabled) ──► .env FYER_ACCESS_TOKEN
  Groww key+secret (unattended refresh works; hourly scheduler task token_refresh) ──► .env GROWW_ACCESS_TOKEN
  FYERS hourly scheduler task fyers_token_refresh → refresh_if_needed() → fails code=-16 today.
  Both expire ~06:00 IST daily.
```

---

### Cross-cutting facts (for the maps)

**External services + endpoints**
- FYERS Data API v3: `https://api-t1.fyers.in/data/{history,quotes,depth,options-chain-v3,marketStatus}` (fyers_client.py)
- FYERS Auth API v3: `https://api-t1.fyers.in/api/v3/{generate-authcode,validate-authcode,validate-refresh-token}` (fyers_auth.py)
- FYERS public instrument master (no auth): `https://public.fyers.in/sym_details/NSE_CM.csv` (build_master_ticker_table.py)
- FYERS WebSocket: `fyers_apiv3.FyersWebsocket.data_ws.FyersDataSocket` (fyers_ws_client.py) — DISABLED live
- Groww: `growwapi.GrowwAPI` SDK — `get_historical_candle_data`, `get_all_instruments`, `get_access_token`, `get_user_profile` (various files); F&O option chain/expiries and `get_quote` for the 6 Indian index quotes (fno_trader.py, `_fetch_groww_indices`)
- yfinance / Yahoo Finance (`fetch_google_prices.py`) — legacy/manual only

**Env vars read** (name / where / sensitivity)
- `FYER_APP_ID`, `FYER_SECRET_ID`, `FYER_Redirect_URL`, `FYER_ACCESS_TOKEN`, `FYER_REFRESH_TOKEN`, `FYER_PIN` — fyers_auth.py — (secret, not recorded)
- `GROWW_API_KEY`, `GROWW_API_SECRET`, `GROWW_ACCESS_TOKEN` — token_refresher.py, get_token.py, price_fetcher.py — (secret, not recorded)
- `DB_URL`, `DB_USER/PASSWORD/HOST/PORT/NAME` — fyers_historical_backfill.py, db_manager.py — (secret, not recorded)
- `XGB_TRAIN_DAYS` — bot.py:437 — non-sensitive, default unset→full history

**config_settings keys** (key / where / default / LIVE VALUE 2026-09-27)
- `fyers.rate_per_sec` / fyers_client.py / literal 2.5 / **DB: 2.5**
- `fyers.burst` / fyers_client.py / literal 5 / **DB: 5**
- `fyers.quote_ttl_seconds` / fyers_client.py / literal 2.0 / **DB: absent → literal used**
- `fyers.ws_enabled` / fyers_ws_client.py / literal "true" / **DB: false**
- `fyers.ws_freshness_seconds` / fyers_ws_client.py / literal 2.0 / **DB: 2**
- `fyers.ws_reconnect_retry` / fyers_ws_client.py / literal 10 / **DB: 10**
- `fyers.ws_backoff_max_seconds` / fyers_ws_client.py / literal 300 / **DB: 300**
- `fyers.ws_stall_seconds` / fyers_ws_client.py / literal 60 / **DB: 60**
- `fyers.ws_token_recheck_seconds` / fyers_ws_client.py / literal 60 / **DB: absent → literal used**
- `fyers.ws_backoff_start_seconds` / fyers_ws_client.py / literal 5 / **DB: absent → literal used**
- `fyers.boot_warmup_enabled/timeout_seconds/extra_pace_seconds/token_wait_seconds` / fyers_boot_warmup.py / literals true/150/0.3/45 / **DB: all absent → literals used**
- `fyers.ws_watchlist_poll_seconds` — present in DB (60) and **orphaned**: seeded at app.py:926, read nowhere in the repo (verified repo-wide) — flagged as a contradiction

**DB tables read/written**
- `fyers_candles` (read+write) — partitioned, ~70.8M est. rows
- `master_ticker_table` (read+write)
- `nse_instruments` (write via load_nse_instruments.py; read by search endpoints out of scope)
- `stock_prices`, `candles` (legacy, written by manual Groww/yfinance scripts only)
- `config_settings` (read-only from this layer)
- `stocks` (read: `is_active` watchlist count)

**Every timed/triggered execution (WHEN → WHAT)**
- App boot → `fyers_boot_warmup.start_in_background()` (sequential warm-up, one-time)
- App boot → `fyers_ws_client.start_in_background()` (no-op today, ws_enabled=false)
- App boot (module import) → `token_refresher.check_and_refresh()` (Groww token, app.py:781-786)
- Every prediction call → `bot.fetch_historical()` → `fyers_historical_backfill.ensure_recent()` (throttled 300s/symbol)
- Watchlist-add → `fyers_historical_backfill.backfill_symbol()` (full ladder, one-time per symbol); also the hourly `self_healing` task → `backfill_symbol()` for watchlist symbols missing FYERS data (self_healing.py:205; capped per run, deferred while the market is open)
- Every 3600s (hourly) scheduler tasks: `token_refresh` → Groww `check_and_refresh()` (scheduler.py:1301); `fyers_token_refresh` → `fyers_auth.refresh_if_needed()` (scheduler.py:1302; fails with code=-16 today); `self_healing` (scheduler.py:1303); `fyers_daily_topup` → `topup_daily()` (scheduler.py:1321; outside market hours, after boot warm-up)
- Manual/CLI only: `fyers_fill_1min_gap.py`, `fyers_backfill_all_watchlist.py`, `build_master_ticker_table.py`, `load_nse_instruments.py`, `price_fetcher` (via `/api/prices/fetch` endpoint)
- Scheduler tasks record_pnl, cash_auto_trade, fno_auto_trade (registered at 5s, but the scheduler loop sleeps 15s between dispatch passes, scheduler.py:1291, so the effective cadence is ≈ every 15s) and auto_close_trades (DB override `scheduler_interval_auto_close_trades=300` → every 300s, market hours only) → converge on `fetch_live_price`/`get_live_price`, protected by the shared 2s quote cache

**Rate limits & quotas table**
| Limit | Unit | Enforced where | Current usage | Worst case | On exceed |
|---|---|---|---|---|---|
| FYERS Standard | 10 req/s | documented, not directly enforced locally | token bucket caps at 2.5/s (well under) | worst case 7.5 requests in any 1s window (burst 5 + rate 2.5), under the 10/s cap | 429 from FYERS |
| FYERS Standard | 200 req/min | documented | local limiter ≈150/min max | worst case 155 in any 60s (burst 5 + 150), under the 200/min cap (single process); boot-warmup + concurrent scheduler tasks could stack | 429, escalating backoff |
| FYERS daily | 100,000 req/day | documented | not tracked/metered locally (no daily counter found in this scope) | unbounded across a trading day | account block risk if sustained |
| FYERS 429×3/day | account block | FYERS-side | mitigated by cooldown+bucket | a bug bypassing `_request` could still trigger it | **account blocked for rest of day** |
| Local token bucket | rate=2.5/s, burst=5 | `fyers_client._acquire_token`, locked | — | 3s acquire timeout → local 429 stub | caller sees `{"s":"error","code":-429}` |
| Quotes batch | 50 symbols/call | `_QUOTES_BATCH_SIZE`, documented FYERS cap | 67-symbol watchlist → 2 calls | — | not chunked inside `fyers_client.get_quotes` itself — caller's responsibility |

**Cost drivers**: FYERS REST calls (rate-limited, no $ cost per docs found in scope, risk is the account-block, not billing); Groww calls (F&O, holdings — no cost data in scope); yfinance (free, unmetered, legacy only).

**Failure modes (fail-open / fail-closed)**
- `fyers_client._cfg()` — fails toward literal defaults, never raises (fail-open on config lookup, but the literal itself is deliberately safe — see rate-limit incident writeup)
- `fyers_client._request()` — 429/non-JSON never raises, returns error dict (fail-open at the transport layer; callers must check status)
- `bot.fetch_live_price` — **raises** on failure (fail-closed by design: "a FYERS outage visible rather than papered over", bot.py:313-320); `place_buy`/`place_sell` refuse to proceed on price≤0
- `fyers_boot_warmup` — aborts (does not retry) if no valid token after 45s; `_active` always cleared in `finally` so bulk tasks never stay paused forever (fail-open on the pause, fail-fast on the token wait)
- `fyers_ws_client` — fails closed on trading (`get_price()` returns None if not FRESH, "no REST fallback... so a caller can never trade on a stale WebSocket price", lines 166-176); fails open on display (`get_last_price()` returns last-ever tick regardless of age)
- `ensure_recent()` — never raises, best-effort, returns 0 on any exception (freshness must not break a prediction)

**Dead / legacy / retired code**
- `fyers_ws_client.set_symbols()` — zero callers, module effectively inert even if enabled
- `GrowwMarketDataProvider` — zero callers, foundation-only per its own docstring
- `market_data_provider.MarketDataProvider` (ABC) — no caller depends on the interface yet
- `collect_index_candles.py` — imports nonexistent `groww_api` module inside `try/except ImportError`, so it is a silent no-op (logs an error and returns)
- `fetch_full_history.py` — hardcoded `now = datetime(2026,4,1)`, one-off historical run, no live callers
- `get_real_prices.py`, `verify_api.py`, `check_groww_market_data.py` — one-shot diagnostic scripts

**Contradictions between code, config, comments or docs**
- `fyers_ws_client.py` module docstring says holdings flow "calls set_symbols() instead" of polling — **false**, zero call sites exist (verified via grep, matches the exact example already flagged in CLAUDE.md's Research Rule)
- The "runs unattended, same as Groww's" framing of PIN-based refresh lives in `refresh_access_token()`'s docstring (fyers_auth.py:95-98) and the `_task_fyers_token_refresh` docstring (scheduler.py:728-735) — NOT in the `fyers_auth.py` module docstring, which says the opposite (no fully-unattended daily refresh, fyers_auth.py:13-18). The code path is real, but the live FYERS endpoint returns a hard SEBI-compliance block (`code=-16`), so it never actually succeeds today (the hourly scheduler task logs an ERROR each time)
- `config_settings.fyers.ws_watchlist_poll_seconds` exists in the DB (value 60, with a description) but is **orphaned**: seeded at app.py:926 and read nowhere in the repo (verified repo-wide)
- `fyers_market_data_provider.py`'s `_QUOTE_CACHE_TTL` (2.0s hardcoded) duplicates `fyers_client.quote_ttl()` (config-driven) rather than reading the same config value — two independently-tunable TTLs that happen to match today but could silently diverge if only one is changed via Settings

**Open unknowns**
- RESOLVED (was: whether any scheduler.py task calls `token_refresher.check_and_refresh()`): yes — scheduler task `token_refresh` every 3600s (scheduler.py:1301 -> `_task_token_refresh`, scheduler.py:695-700) and once at app import (app.py:781-786)
- RESOLVED (was: rate limiting of `fno_trader._groww_api.get_quotes`): that attribute does not exist — `_groww_api` is not defined anywhere in fno_trader.py, so the app.py:3427/3496/3574 call sites raise AttributeError (see Trading F&O Finding #4). The real Groww quote path in F&O is `_get_groww()` / `_fetch_groww_indices` (sequential `groww.get_quote`, fno_trader.py:1957-1999); its rate limiting was not examined
- Actual daily FYERS request volume against the 100,000/day documented cap — no local counter/metric found in scope beyond the in-process `_ReqCounter` (which resets and isn't persisted) — UNKNOWN — NOT DETERMINABLE FROM CODE

---

## Trading Engine — Cash Equity (signals → orders → exits)

Overview: this section traces the cash-equity (non-F&O) algo pipeline in
/Users/parthsharma/Desktop/Grow: watchlist selection → ML/trend/news signal
scan (`bot.py`) → confidence gating & ranking → `auto_trade` risk gates →
order placement (paper via `paper_trader.py` / live via `live_trade_executor.py`,
`real_market_trading.py`) → GTT stop-loss → trailing-stop monitoring
(`trailing_stop.py`, `trailing_strategy.py`) → exits (target/stop/reversal/EOD)
→ journaling & reconciliation (`trade_journal.py`, `paper_trade_reconciliation.py`,
`trade_chart_manager.py`, `trade_origin_manager.py`). Cost gating in `costs.py`.

### Pipeline diagram
```
get_active_watchlist() [DB stocks table, fallback config.WATCHLIST]
        │
        ▼
scan_watchlist() ── ThreadPoolExecutor(6) ── _predict_one(sym) ── get_prediction(sym)
scan_watchlist_xgb() ── batched get_ltp_batch() pre-fetch (refuses whole scan if any
        │                symbol unpriced) ── ThreadPoolExecutor(6) ── get_prediction_xgb
        │                    (which itself calls get_prediction with ml_predictor=XGB)
        ▼
get_prediction(): 4-source weighted consensus
   Source1 ML (GBC or XGB predictor.predict(df))         W_ML=0.40
   Source1b 5-yr trend (analyze_long_term_trend)          W_TREND=0.15
   Source2 news_sentiment.get_news_sentiment              W_NEWS=0.20
   Source3 market_context.analyze_market_context          W_CTX=0.25
   Source4 costs.min_profitable_move -> cost_data (display only, not in combined_score)
   combined_score>0.15 → BUY; <-0.15 → SELL; else HOLD
   volatility HIGH → confidence*0.8; multi-TF aligned → confidence*1.15 (cap 1.0)
        ▼
auto_trade(skip_new_entries=False):
  0. gate: _portfolio_reviewed must be True (else abort, PORTFOLIO_NOT_REVIEWED) —
     binds in LIVE mode only: in paper mode _task_cash_auto_trade auto-calls
     mark_portfolio_reviewed() (scheduler.py:811-812)
  1. monitor_and_update_trailing_stops() ALWAYS runs first (even boot warmup)
  2. if skip_new_entries: return early (boot warmup — only trailing stops run)
  3. model enable gates: model.gbc_cash_enabled (default True), model.xgb_cash_enabled
     (default XGB_LIVE_TRADING env) — read fails closed (trade with NEITHER model)
  4. predictions = scan_watchlist() [+ scan_watchlist_xgb() if xgb_on]
  5. open_symbols = broker positions (qty>0) UNION open paper positions (status OPEN)
     — lookup failure on EITHER source aborts the whole cycle (fail closed)
  6. predictions.sort(by confidence desc, stable) — highest conviction first
  7. per prediction:
     a. min-confidence gate: paper.min_confidence (default 0.50) if paper mode,
        else CONFIDENCE_THRESHOLD (live, 0.65 — config.py:22) — skip if confidence <= threshold
     b. BUY path (symbol not in open_symbols, len(open_symbols) < MAX_POSITIONS):
        - trade_budget = get_model_trade_budget(model_source) [per-model pot AND
          global cap; both count only PAPER positions — in LIVE mode the pot is always full, see gates 6/9] → skip if <=0 ("capital pot exhausted")
        - qty = int(trade_budget/price), min 1 — sized to what will ACTUALLY be
          ordered (place_buy does NOT clamp model-driven qty to MAX_TRADE_QUANTITY, but DOES
          enforce price*qty <= MAX_TRADE_VALUE, bot.py:1706-1710; live .env ₹50,000)
        - cost_info = costs.min_profitable_move(price, qty) → breakeven_pct
        - MIN VIABLE POSITION gate: trade.max_breakeven_pct (default 0.60) — skip
          if breakeven_pct exceeds it
        - COST GATE: expected_return_pct = confidence * TARGET_PCT; skip if
          expected_return_pct < breakeven_pct
        - CAPITAL CAP gate (again, on actual qty*price): _check_capital_cap_allows_trade
        - live mode only: trade_journal.create_pre_trade_report BEFORE order
        - place_buy(qty, price, prediction) → place_gtt_stop_loss(sl_price)
     c. SELL path (symbol in open_symbols):
        - EXIT FREEZE check: trailing_stop.automated_exits_allowed()
        - qty resolution: broker position first, else open PAPER positions
          (BUY side) summed; if neither → SKIP "no_open_long_to_close" (refuses
          to open a short)
        - closes matching trade_journal open report (exit_reason=signal_reversed)
        - place_sell(qty, price, prediction)
        - explicitly closes the paper position row(s) via tracker.close_trade()
          (documented historical bug: record_entry() always creates status=OPEN,
          so a SELL without this explicit close created a NEW open row instead
          of closing the BUY → self-reinforcing duplicate-sell loop)
        - CAVEAT (latent, see money-safety finding 9): this closes only the BUY rows;
          place_sell → _paper_trade("SELL") → record_entry ALSO creates a new status:'OPEN'
          SELL row + SELL journal report that nothing closes — a phantom short
     d. else → HOLD action recorded
        ▼
place_buy/place_sell (bot.py) → is_paper_mode() gate → _paper_trade() [paper]
    or groww.place_order() [live]
        ▼
_paper_trade(): writes PaperTradeTracker.record_entry() (paper_trades.json +
  paper_trades DB table) + trade_journal.create_pre_trade_report() (trade_journal.json
  + trade_journal DB table) + telegram alert + _capture_trade_snapshot (trade_snapshots
  DB table)
        ▼
monitor_and_update_trailing_stops() [every auto_trade cycle]: exit-freeze gate
  (automated_exits_allowed) → batched get_ltp_batch() for open trade symbols →
  tracker.update_trailing_stop(trade_id, price) per trade → 'closed'/'costs_covered'/
  'trailing_updated'
```

### `get_prediction` — signal combination
| Field | Detail |
|---|---|
| Where | `bot.py:944-1185` |
| What / Why | 4-source weighted consensus producing BUY/SELL/HOLD + confidence for one symbol. Central to both GBC and XGB paths (XGB routes through this too, per bot.py:561-568, so both models see identical non-ML sources). |
| Used by (callers) | `_predict_one` (bot.py:1212), `get_prediction_xgb` (bot.py:584), `analyze_portfolio`'s wrapper (bot.py:2529), trailing_stop.py (signal-reversal check, see below) |
| Calls | `_predictors[symbol].predict(df)` or `ml_predictor.predict(df)`; `analyze_long_term_trend`; `news_sentiment.get_news_sentiment`; `market_context.analyze_market_context`; `costs.min_profitable_move`; `get_model_trade_budget` |
| Inputs | symbol, optional intraday_candles/ml_predictor/ml_df/model_source/live_price |
| Weights (VERIFIED FROM CODE, bot.py:1105-1112, DB-configurable) | W_ML=`prediction.weight.ml` default 0.40; W_TREND=`prediction.weight.trend` default 0.15; W_NEWS=`prediction.weight.news` default 0.20; W_CTX=`prediction.weight.context` default 0.25 — read via `get_config`, exception fallback uses same literals |
| Formula | `combined_score = W_ML*ml_score + W_TREND*long_term_score + W_NEWS*news_score + W_CTX*ctx_score`; signal: score>0.15 BUY, <-0.15 SELL, else HOLD (bot.py:1121-1126, thresholds are bare literals, not config) |
| Confidence formula | weighted avg of per-source confidences, capped 1.0; HIGH volatility regime ×0.8 (bot.py:1129-1130); multi-TF aligned ×1.15 capped 1.0 (bot.py:1133-1134) |
| Outputs | dict: symbol, signal, confidence, combined_score, model_source, indicators, reason, costs, long_term_trend, sources{ml,news,market_context,long_term} |
| Failure behaviour | df empty → HOLD/"No data"; news/context exceptions caught → neutral 0 score, logged warning (fail-open on non-critical sources); ML predictor load/train failure → HOLD with message |
| Blast radius | Every BUY/SELL decision in the system depends on this; the weights and 0.15 thresholds directly gate order flow |
| Status | ACTIVE |

### Confidence thresholds & ranking
| Rule | Formula/Value | Where set | Risk if changed |
|---|---|---|---|
| Paper min confidence | `paper.min_confidence` config, default **0.50** | bot.py:2218, `_check` inside auto_trade loop | Lower → more (weaker) paper trades; higher → fewer entries |
| Live min confidence | `CONFIDENCE_THRESHOLD` constant = **0.65** | config.py:22 | Same as above but for real money |
| Ranking | `predictions.sort(key=confidence, reverse=True)`, stable sort | bot.py:2204 | Without it, MAX_POSITIONS fills by watchlist-order not conviction (documented regression fixed) |

### `auto_trade` — gates, in order (bot.py:2022-2455)
| # | Gate | Formula / threshold | Where | Fail mode |
|---|---|---|---|---|
| 1 | Portfolio reviewed | `_portfolio_reviewed` bool, DB config `portfolio_reviewed` | bot.py:2043 | Fails closed — returns error, no trading until user clicks review. **Binds in LIVE mode only**: in paper mode `_task_cash_auto_trade` calls `mark_portfolio_reviewed()` automatically (scheduler.py:811-812); live DB `portfolio_reviewed=true` (2026-09-27 03:53) |
| 2 | Model enable | `model.gbc_cash_enabled` default True; `model.xgb_cash_enabled` default `XGB_LIVE_TRADING` env (code default false; live `.env` `XGB_LIVE_TRADING=true`, moot because DB `model.xgb_cash_enabled=true` overrides, bot.py:2090-2096) | bot.py:2087-2105 | Config read exception → **both disabled** (fail closed) |
| 3 | Position lookup (dup-entry / MAX_POSITIONS) | `open_symbols` = broker positions ∪ open paper trades | bot.py:2138-2196 | Either lookup failing **aborts entire cycle** (fail closed) — historical bug: paper mode alone caused 385 duplicate entries/day, ₹24,242 wasted (comment cites this) |
| 4 | Min confidence | `paper.min_confidence` (0.50) / `CONFIDENCE_THRESHOLD` (0.65, config.py:22) | bot.py:2215-2225 | Skip if `confidence <= threshold` |
| 5 | MAX_POSITIONS | `len(open_symbols) < MAX_POSITIONS` | bot.py:2227, config.py | Skip BUY once full |
| 6 | Per-model capital pot | `get_model_trade_budget(model_source)`: `cap - deployed`, cap from `paper.cap.gradientboosting`/`paper.cap.xgboost` (default ₹50,000 each), bounded by global `paper_trade_amount_limit` | bot.py:1405-1431, 2242-2250 | Skip "capital pot exhausted". **PAPER-only**: `get_model_trade_budget`/`get_current_deployed_capital` sum only PAPER positions (bot.py:1377-1402), so in LIVE mode each BUY is sized from an always-full ₹50k pot. Fails OPEN: `get_current_deployed_capital()` returns 0.0 on any exception (bot.py:1400-1402) and `get_paper_trade_amount_limit()` returns 0.0 (= unlimited) on exception (bot.py:1332-1333) |
| 7 | Min viable position (breakeven cap) | `trade.max_breakeven_pct` config, default **0.60%** — skip if `costs.min_profitable_move()`'s `min_move_pct` exceeds it | bot.py:2273-2287 | Skip "Position too small" — prevents small positions where fixed charges dominate |
| 8 | Cost gate | `expected_return_pct = confidence * TARGET_PCT` must be `>= breakeven_pct` | bot.py:2290-2296, TARGET_PCT in config.py | Skip "Cost-gated" |
| 9 | Capital cap (again, actual qty) | `_check_capital_cap_allows_trade(new_trade_value, model_source)` — checks BOTH per-model and global caps | bot.py:1434-1464, 2298-2310 | Skip. **PAPER-only**: `_check_capital_cap_allows_trade` returns True when not paper (bot.py:1445-1446), and the per-model budget counts only paper positions, so in LIVE mode no per-model/global capital cap applies — the only limits are MAX_POSITIONS=5 and MAX_TRADE_VALUE=₹50,000 per order (`.env`), about ₹2.5L of exposure. Both helpers also fail open on exceptions (bot.py:1332-1333, 1400-1402) |
| 10 | Exit freeze (SELL path only) | `trailing_stop.automated_exits_allowed()` | bot.py:2347-2352 | Skip "exit frozen" |
| 11 | SELL quantity resolution | broker position qty, else sum of open PAPER BUY positions; neither → refuse (no short) | bot.py:2362-2390 | Skip "no_open_long_to_close" / "zero_quantity" |

### `is_paper_mode` / `_paper_flag_means_live` — money-safety gate
| Field | Detail |
|---|---|
| Where | `bot.py:1276-1323` |
| What / Why | Single source of truth for paper-vs-live. Fails closed ONLY on an exception: any exception reading config → PAPER (logs SAFETY error). A MISSING row or a row with NULL `value` resolves to the default `"false"` → LIVE (see LATENT RISK below). |
| Formula | Only `raw` normalized to one of `{"false","0","no","off"}` is treated as "live" (`_paper_flag_means_live` returns True → is_paper_mode returns False). Everything else (including unrecognized strings) → PAPER, with a warning logged for unrecognized values. Deliberately asymmetric: old code used `value.lower()=="true"` which meant almost anything selected LIVE. |
| Config key | `paper_trading` (DB config_settings), default `"false"` string passed to get_config — NOTE: the default arg is `"false"` but semantically `_paper_flag_means_live("false")` = True (means live!). Need runtime check — **see LIVE DB VALUE below**. A row that EXISTS with a NULL `value` resolves the same way as a missing row (`get_config` returns `default` when the row is absent OR `value IS NULL`, db_manager.py:1444-1462) → LIVE. |
| Callers | `place_buy`, `place_sell`, `place_gtt_stop_loss`, `_check_capital_cap_allows_trade` |
| Other readers of `paper_trading` (old parser) | **13 other call sites** parse the key with the OLD `.lower()=="true"` parser: app.py:5853, 6552, 6631; scheduler.py:1043; telegram_commander.py:675, 701, 714, 1019, 1051, 1137, 1151, 1173; paper_trader.py:30. For values like `1`, `yes`, `on` or `TRUE ` the dashboard, Telegram and the toggle report "LIVE" while the engine is in PAPER. For a missing row they agree with the engine (LIVE). Display risk only, but it can mislead the operator about real-money state. |
| Blast radius | Every order-placement site. If this ever fails open, real orders fire. |
| Status | ACTIVE |

### LIVE config_settings values (VERIFIED FROM DATABASE, `SELECT key,value FROM config_settings WHERE key IN (...)`, LAST VERIFIED: 2026-09-27)
| key | live value | code default |
|---|---|---|
| `paper_trading` | **true** (updated 2026-09-10 04:02) | "false" (bot.py:1286) — see note below |
| `model.gbc_cash_enabled` | **false** | True |
| `model.xgb_cash_enabled` | **true** | XGB_LIVE_TRADING env (default false; live `.env` = true) |
| `paper_trade_amount_limit` | 50000.00 | 0 (unlimited) |
| `paper.cap.gradientboosting` | 50000 | 50000 |
| `paper.cap.xgboost` | 50000 | 50000 |
| `paper.min_confidence` | 0.50 | 0.50 |
| `trade.max_breakeven_pct` | 0.60 | 0.60 |
| `prediction.weight.ml/.trend/.news/.context` | 0.40/0.15/0.20/0.25 | same |
| `portfolio_reviewed` | **true** (updated 2026-09-27 03:53) | False (unset) |
| `trade.no_auto_exit_enabled` | **true** | True |
| `trade.no_auto_exit_after` | **15:15** | "15:15" |
| `scheduler_interval_auto_close_trades` | **300** (updated 2026-08-26 04:26) | 5 (registered interval) |
| `scheduler_interval_cost_scraper` | **3888000** (45 days) | 3888000 (registered interval, scheduler.py:1348) |

**CONTRADICTION FOUND**: code comment at bot.py:597-601 says `XGB_LIVE_TRADING` defaults OFF "until a GBC-vs-XGB backtest exists," and auto_trade's model-enable gate (bot.py:2074-2105) was built to let both be toggled — but the LIVE DB config currently has **GradientBoosting cash DISABLED and XGBoost cash ENABLED**, the opposite of history (GBC was the only original model). Right now the only cash-equity model actually placing trades is XGBoost. Whether a backtest comparison was actually done before this flip is UNKNOWN — NOT DETERMINABLE FROM CODE. Also note: live `.env` has `XGB_LIVE_TRADING=true` (the code default at bot.py:601 is "false"); this is moot for trading because the DB `model.xgb_cash_enabled=true` overrides it (bot.py:2090-2096).

**LATENT RISK (fail-open on missing key, not currently triggered)**: `is_paper_mode()` (bot.py:1276) calls `get_config("paper_trading", "false")`. If the `paper_trading` row is ever missing from `config_settings` (fresh DB, restored backup), the DEFAULT `"false"` is passed to `_paper_flag_means_live("false")`, which returns **True** (means live) — so `is_paper_mode()` would return **False (LIVE)** by default, not paper. This is the opposite of the stated safety intent ("if we cannot read the setting we must assume paper mode") and only that intent's *exception path* (DB unreachable) actually fails closed to paper; a present-but-missing-key path fails open to LIVE. Currently moot because the live row is `"true"`, but worth flagging per the CLAUDE.md "guards must fail closed" standard (paper_trader.py:26-34 is NOT the same pattern: `paper_trader.is_paper_trading_enabled()` uses a different parser, `.lower()=="true"`; a missing row or an exception returns False ("paper disabled"), and its only caller, `main()` (paper_trader.py:401), then `sys.exit(1)` — the safe direction). The same fail-open-to-LIVE resolution also applies when the row EXISTS but its `value` is NULL (`get_config` returns `default` for `value IS NULL` as well as for a missing row, db_manager.py:1444-1462; the default is `"false"`). Mitigation: the Settings writer normalizes values to exact `true`/`false` (app.py:523-545), but direct DB edits and restores bypass it.

### `PaperTradeTracker` (paper_trader.py) — paper order store
| Field | Detail |
|---|---|
| Where | `paper_trader.py:37-370` |
| What / Why | Cash-equity-only in-process + JSON-file simulated order book. `record_entry` creates trades (always status OPEN — see finding below); `close_trade` closes them and computes P&L via `bot.costs.net_profit`; `update_trailing_stop` delegates entirely to `trailing_strategy.evaluate()`. |
| Storage | `paper_trades.json` (source of truth for the in-process tracker) via `_save_trades()`: takes an **exclusive flock**, re-reads disk, merges by trade `id` (own fields win) before writing — prevents one writer's save from erasing a field owned by another writer (documented MARUTI `peak_pnl` corruption incident). Falls back to unlocked plain write on lock failure. **Caveat (inference from code, not observed)**: the merge-by-id save does NOT stop stale overwrites — both `PaperTradeTracker._save_trades` (paper_trader.py:81-89) and trailing_stop's writer (trailing_stop.py:672-675) merge each writer's FULL trade dicts, and every dict carries `status`/`exit_*`, so a tracker loaded before a concurrent close can write `status:'OPEN'` back over the close. This can happen when the ~15s `monitor_and_update_trailing_stops` overlaps with `/api/auto-close/check` or the 300s task. The "a writer can never erase another's fields" guarantee holds only for keys the stale copy lacks. |
| record_entry | Computes `stop_loss` via `trailing_strategy.build_trade()` (RULE 1: capped at `MAX_CASH_SL_PCT`=1.0% from config.py), `breakeven_price`/`breakeven_pct` via `trailing_stop.calculate_breakeven_price`/`breakeven_pct_for` (costs-based, per-quantity) — stamped ONCE at entry, never recomputed, because breakeven is size-dependent. **Always sets `status: 'OPEN'` regardless of side** (BUY or SELL) — this is the root cause bot.py:2416-2444 explicitly works around: a SELL calling `_paper_trade`→`record_entry` creates a NEW open row rather than closing the matching BUY, so callers (bot.auto_trade) must explicitly call `tracker.close_trade()` afterward. |
| close_trade | Computes P&L via `bot.costs.net_profit`; sets status HIT_TARGET/HIT_SL/CLOSED by comparing exit_reason and exit_price vs the trade's own armed `stop_loss` (no more hardcoded ×0.98); syncs to `trade_journal.close_matching_paper_trade`; **swallows the journal-sync exception** (logs CRITICAL/ERROR but does not fail the trade close) — the paper trade is closed in `paper_trades.json` even if the journal never learns, which is the exact desync pattern documented in the file's own comments (MARUTI, TITAN, HINDUNILVR incidents). |
| update_trailing_stop | Delegates 100% to `trailing_strategy.evaluate()` (see below); persists returned state; DOES NOT close trades itself — `evaluate()`'s action is read by monitor_and_update_trailing_stops's caller (bot.py) which calls `tracker.close_trade()` separately when `result=='closed'`... **NOTE**: actually re-checking bot.py:1983, `tracker.update_trailing_stop()` returns only `'trailing_updated'`/None, never `'closed'` — bot.py:1985 checks `result == 'closed'` which this function never returns. **CONTRADICTION / POSSIBLE DEAD CODE PATH**: `PaperTradeTracker.update_trailing_stop` (paper_trader.py:334-363) only ever returns `'trailing_updated'` or `None`; it never returns `'closed'` or `'costs_covered'`. bot.py's `monitor_and_update_trailing_stops()` (bot.py:1983-2013) branches on `result == 'closed'` and `result == 'costs_covered'` — those branches appear UNREACHABLE via this call path. Actual closing on a trailing-stop breach therefore happens only through the SEPARATE `trailing_stop.check_and_close_trades_on_loss()` path (scheduler `_task_auto_close_trades`), not through `bot.auto_trade()`'s own trailing-stop monitor. Needs a second opinion / runtime trace to confirm — flagged as HIGH-VALUE finding for the money-safety review. **VERIFIED 2026-09-27**: paper_trader.py:334-363 (`res = evaluate(trade, price, confidence_fn=None)`; `trade.update(res["state"])`; `return 'trailing_updated'`), so the bot.py:1983-2013 `'closed'`/`'costs_covered'` branches are unreachable. Nuances: it passes `confidence_fn=None`, so even the reprieve logic is off on this path; and when breakeven is missing it OVERWRITES `stop_loss` with `build_trade()`'s capped SL (paper_trader.py:351-358). |
| `main()` (CLI) | Manual/local test entrypoint, not imported/scheduled elsewhere. Status: TEST ONLY / MANUAL. |
| Status | ACTIVE (class); the closed-detection gap above is a CONFIRMED defect (verified 2026-09-27) |

### Duplicate/parallel exit authorities (IMPORTANT — verify carefully)
Two independent scheduler tasks are registered at 5s and BOTH can close paper trades; their effective cadences differ (the scheduler loop sleeps 15s between dispatch passes, scheduler.py:1291, and a DB override slows one of them to 300s):
1. `scheduler._task_cash_auto_trade` (registered 5s; effective ≈ every 15s) → `bot.auto_trade()` → `monitor_and_update_trailing_stops()` → `tracker.update_trailing_stop()` → `trailing_strategy.evaluate()`. Per the finding above, this path's `bot.py` caller checks for a `'closed'` return value that `update_trailing_stop` never produces — so this path may only ever UPDATE the trailing-stop numbers, never actually CLOSE a trade on a soft-stop breach (hard stop-loss is likewise not enforced here — `trailing_strategy.evaluate()`'s `ACTION_CLOSE` return is stored in `_r["action"]` inside `check_and_close_trades_on_loss`, not inside `PaperTradeTracker.update_trailing_stop`, which discards the action and returns a fixed string).
2. `scheduler._task_auto_close_trades` (registered interval 5s, `app.py:7988`, BUT DB `scheduler_interval_auto_close_trades=300` overrides it — read via `_load_interval_overrides`/`_resolve_interval`, scheduler.py:1202-1233, 1285 — so it runs **every 300s (5 min)**, and only 09:20-15:15 via `fno_trader._is_market_open`, scheduler.py:836-839) → `trailing_stop.check_and_close_trades_on_loss()`, which DOES read `trailing_strategy.evaluate()`'s action (CHECK 0.5) and DOES close on `ACTION_CLOSE`, plus its own CHECK 0 (hard SL) and target-hit check run first. Live prices fetched **serially per symbol** (`paper_trader.get_live_price` in a `for symbol in open_symbols` loop, trailing_stop.py caller at scheduler.py:855-862) — NOT batched, unlike `monitor_and_update_trailing_stops`'s batched `get_ltp_batch()`. This is the actual closing authority for trailing-stop / hard-SL / target exits.
3. `/api/auto-close/check` (app.py:6464, `@idempotent`) — same `check_and_close_trades_on_loss` + `manage_loss_positions`, callable manually/from frontend; also serial per-symbol price fetch. Between server runs of the 300s task, trades close only if a browser has the Paper Trader open — index.html:14593 POSTs `/api/auto-close/check` on its 5s loop.
All three are gated by `automated_exits_allowed()` and write through the same flock+merge-by-id save, and re-running on an already-closed trade is a no-op (`status != 'OPEN'` skip), so duplication does not cause duplicate CLOSES — but it does mean **auto_trade's advertised "monitors and updates trailing stops on open positions" (bot.py:1914 docstring) does not actually close anything**, and the real closing cadence/latency is governed by the separate `_task_auto_close_trades` (300s) with un-batched per-symbol quote calls — a CLAUDE.md standard-3 violation (sequential blocking I/O that should be parallelized/batched) for any watchlist of open positions > 1 symbol.

### `trailing_strategy.evaluate()` — the single authoritative trailing-exit rule (trailing_strategy.py, PURE function, no I/O)
| Field | Detail |
|---|---|
| Where | `trailing_strategy.py:92-196`, config table `trailing_strategy.py:33-44` |
| Rule order | (1) HARD_STOP_LOSS: `current_price` vs `trade.stop_loss`, checked first, unconditional. (2) Ratchet peak (`highest_price_reached`/`lowest_price_reached`) → `peak_pnl`. (3) ARM: only once `peak_pnl >= max(breakeven_pct*1.2, 0.20)` (literal constants). (4) Compute soft trailing stop via `_tier_giveback()`, clamped to never go below/above `breakeven_price`, and ratcheted (never loosens vs previous `trailing_stop`). (5) Existing `hard_floor` (an active reprieve) is absolute — closes immediately if breached, else stays in reprieve. (6) On a soft-stop breach: consult `confidence_fn` (bot.get_prediction_xgb) ONCE; if model agrees with position direction at `confidence >= trail.confidence_min` (0.60), grant ONE reprieve (`hard_floor`) instead of closing; else CLOSE. |
| Give-back tiers (`_tier_giveback`) | Big winner (`peak_pnl >= 1.5%` from entry) or `peak_pnl >= be*4` → 0.5% tier; `>= be*2.5` → 0.75%; else 1.0% — always `min(tier, peak_pnl*0.5)` (half-peak cap) — and if `entry>0 and qty>0`, additionally capped so give-back never exceeds `trail.max_giveback_rs` (₹100 default) once GROSS peak profit (`peak_pnl% * entry * qty`) reaches `trail.peak_profit_trigger_rs` (₹300 default). All values are DEFAULTS dict literals in trailing_strategy.py:33-44, not DB config — a change requires a code edit. |
| Inputs | `trade` dict (signal/side, entry_price, quantity, stop_loss, breakeven_pct, breakeven_price, highest/lowest_price_reached, trailing_stop, hard_floor), `current_price`, optional `confidence_fn` |
| Outputs | `{"action": HOLD|CLOSE, "reason": str, "state": {...fields to merge back onto the trade...}}` — caller owns all persistence (pure function, explicitly designed for testability without touching live records) |
| Consumers | `paper_trader.PaperTradeTracker.update_trailing_stop` (state only, action effectively discarded per finding above); `trailing_stop.check_and_close_trades_on_loss` CHECK 0.5 (acts on both state AND action) |
| Risk if changed | `trail.confidence_min`, `trail.peak_profit_trigger_rs`, `trail.max_giveback_rs`, `trail.big_winner_pct` are hardcoded module constants (not DB-configurable) — changing exit tightness requires a code deploy, not a Settings change (inconsistent with CLAUDE.md standard 8 "config over constants") |
| Status | ACTIVE (the intended single source of truth per its own docstring, superseding two other historical mechanisms in trailing_stop.py that are now dead-but-retained, see below) |

### `trailing_stop.py` — breakeven math, exit freeze, legacy closers
| Function | Detail |
|---|---|
| `automated_exits_allowed(now=None)` | EOD exit freeze. Config: `trade.no_auto_exit_enabled` (default **True**, fails to True/frozen-enabled on config error) + `trade.no_auto_exit_after` (default **"15:15"** IST). Blocks ALL automated closes (trailing stop, hard SL, signal reversal) after cutoff — CNC delivery so an unclosed position just carries overnight; manual closes (`is_manual_exit`, checks `"manual" in exit_reason.lower()`) bypass entirely. Consumed by: `check_and_close_trades_on_loss`, `manage_loss_positions`, `bot.monitor_and_update_trailing_stops`, `bot.auto_trade`'s SELL-signal-reversal path. **Live values (2026-09-27): `trade.no_auto_exit_enabled`=true, `trade.no_auto_exit_after`=15:15.** Note: `monitor_and_update_trailing_stops`'s comment says stop LEVELS still update during the freeze, but the code returns before any update (bot.py:1929-1931). |
| `calculate_breakeven_price` / `breakeven_pct_for` | Per-position breakeven (price and %), computed via `costs.calculate_costs(entry, qty, sell_price=entry).breakeven_pct` — a round-trip at the same price isolates pure cost drag. **Raises** (no silent default) on non-positive qty/price — "a guard that invents a breakeven when it cannot compute one removes itself exactly when it is least safe." |
| `check_and_close_trades_on_loss()` | Real closing authority (see duplicate-authority note above). CHECK 0 = hard stop-loss (absolute, first). Target-hit check (before CHECK 0 in code order, actually runs first at line ~320) closes on target regardless of P&L sign. CHECK 0.5 = delegates to `trailing_strategy.evaluate()`. **CHECK 1 (breakeven floor) and CHECK 2 (a second, independent peak-erosion ladder + PEAK_EROSION_60) are DEAD CODE** — wrapped in `if False and ...` (lines 488, 787-equivalent in manage_loss_positions) — retained only as commented rationale, per Karpathy "don't delete, note it" style; confirmed inert. Persists ALL state changes (not just closes) under the same flock+merge-by-id pattern as PaperTradeTracker. |
| `manage_loss_positions()` | Classifies OPEN losing trades into CRITICAL/HIGH/MEDIUM/LIGHT bands; only REVERSE/SCALE_OUT/HOLD branches are live (annotate-only, no order placed) — the actual CLOSE branch for CRITICAL losses is dead (`if False`) since the hard SL (tighter, checked earlier) always fires first. Called back-to-back with `check_and_close_trades_on_loss` from both `scheduler._task_auto_close_trades`... **actually NOT from the scheduler task** (scheduler.py:827-881 calls only `check_and_close_trades_on_loss`, not `manage_loss_positions`) — `manage_loss_positions` is called only from `/api/auto-close/check` (app.py:6464-6511). |
| Status | `check_and_close_trades_on_loss`: ACTIVE. `manage_loss_positions`: ACTIVE but its CLOSE branch DISABLED/DEAD; REVERSE/SCALE_OUT are advisory-only (no execution). |

### `costs.py` — cost model (config-driven, DB-cached)
| Field | Detail |
|---|---|
| Where | `costs.py` (435 lines, fully read) |
| Rates | 11 rate constants (`cost.BROKERAGE_PER_ORDER` ₹20, `cost.STT_DELIVERY_PCT` 0.1%, `cost.EXCHANGE_TXN_NSE_PCT` 0.00345%, `cost.SEBI_FEE_PCT` 0.0001%, `cost.GST_PCT` 18%, `cost.STAMP_DUTY_DELIVERY_PCT` 0.015%, `cost.DP_CHARGES` ₹15.93, etc.) — DB `config_settings` keys prefixed `cost.*`, in-memory-cached (`_rate_cache`, loaded once, `reload_rates()` invalidates), hardcoded `_DEFAULTS` fallback if DB unavailable |
| `calculate_costs(price, qty, sell_price, product, exchange)` | Full round-trip cost breakdown (brokerage+STT+exchange txn+SEBI+GST+stamp duty+DP), CNC (delivery) vs MIS (intraday) branching |
| `min_profitable_move` | breakeven price/pct — feeds bot.py cost-gate (Source 4) and the min-viable-position gate |
| `net_profit(buy, sell, qty)` | gross/net P&L after full costs — used by `paper_trader.close_trade`, `trade_journal.close_trade_report`, `paper_trade_reconciliation._build_tracker_post_trade` |
| `update_cost_rates()` | Scheduled (per module docstring: "every 45 days") scraper of groww.in/charges via `cost_scraper`/`cost_updater`/`cost_notifications`; has a raw-requests+BeautifulSoup fallback if those modules fail. **Scheduler registration verified**: task `cost_scraper` runs every 3,888,000s = 45 days (scheduler.py:1348; DB override `scheduler_interval_cost_scraper=3888000`). 45 days is correct; the `costs.py:6` docstring ("every 3 days") is stale. |
| Status | ACTIVE — every cost/breakeven number in the whole pipeline traces to this one module |

### DB tables touched by cash-equity trading (each writer VERIFIED FROM CODE)
| Table | Model (db_manager.py) | Writers | Readers |
|---|---|---|---|
| `paper_trades` | `PaperTrade` (db_manager.py:522) | `bot._paper_trade()` (bot.py:1546-1556, one row per BUY/SELL) | trade-history endpoints |
| `trade_journal` | `TradeJournalEntry` (db_manager.py:309) | `trade_journal._save()` (trade_journal.py:143-262) — DB-first, one query preloading all touched rows (N+1 fixed per its own comment), raises on DB failure so file mirror never masks a lost write | `trade_journal._load()`, `paper_trade_reconciliation` (via `build_canonical_trade_views`'s DB-entries input, sourced elsewhere) |
| `trade_snapshots` | `TradeSnapshot` (db_manager.py:545) | `bot._capture_trade_snapshot()` (bot.py:781-878) — candles/indicators/news/reasoning at trade time, own session with explicit `rollback()` in except + `close()` in finally |
| `trade_log` | `TradeLogEntry` (db_manager.py:403) | `bot._persist_trade_log_entry()` (bot.py:121-139) — every place_buy/place_sell/_paper_trade entry, own short-lived session, swallows failures (debug-log only) |
| `pnl_snapshots` | `PnLSnapshot` (db_manager.py:616) | `scheduler._task_record_pnl()` (scheduler.py:912+, registered **5s**, effective ≈ every 15s (scheduler loop tick); market-hours gated) — reads `paper_trades.json` OPEN trades + live prices, writes unrealised P&L snapshot. (scheduler.py outside this section's assigned file list; read only to confirm this one writer per the task's DB-table checklist.) |
| `config_settings` | n/a | Read everywhere via `get_config` (memoized ~30s per CLAUDE.md); written by Settings UI / seeding functions (`costs.seed_cost_rates`, etc.) |
| `fyers_candles` | n/a | READ-ONLY from this module's perspective (`analyze_long_term_trend`, `market_context.py`, `paper_trade_reconciliation._peak_net_pnl`) — all bounded by date range or `days=`, none full-scan |

### JSON file stores (source of truth for the paper tracker, NOT the DB)
| File | Owner / writers | Notes |
|---|---|---|
| `paper_trades.json` | `PaperTradeTracker._save_trades()` (paper_trader.py), `trailing_stop.check_and_close_trades_on_loss`/`manage_loss_positions` (direct read-modify-write, same flock+merge-by-id pattern) | THE tracker's real state; the `paper_trades` DB table is a write-once-per-event mirror, not kept in sync on every field change (e.g. `peak_pnl`, `trailing_stop`, `hard_floor` only ever live in the JSON file, never written to the `paper_trades` DB row) |
| `trade_journal.json` | `trade_journal._save()` — written only AFTER a successful DB write (mirror, not source of truth) | |
| `trade_origins.json` / `manual_holdings.json` / `trade_boundary_log.json` | `trade_origin_manager.py` | `trade_origins.json` never populated (see finding) |
| `chart_cache/*.json` | `trade_chart_manager.cache_trade_candles` | display cache only |

### Money-safety audit findings (report only, per the standard checklist)
1. **Paper-mode fail-closed / exchange calls gated** — MOSTLY GOOD. `place_buy`, `place_sell`, `place_gtt_stop_loss` all check `is_paper_mode()` before touching `groww.place_order`/`create_smart_order`. `is_paper_mode()` fails closed to PAPER only on a config-READ EXCEPTION (bot.py:1288-1294); if the `paper_trading` row is simply MISSING (not an exception, just absent), the code path (`get_config("paper_trading","false")` → `_paper_flag_means_live("false")==True` → `is_paper_mode()==False`) fails OPEN to LIVE. Currently moot (live DB value is `"true"`) but is a latent gap — a row that EXISTS with a NULL `value` resolves the same way (`get_config` returns `default` for `value IS NULL` as well as for a missing row, db_manager.py:1444-1462); the Settings writer normalizes values to exact `true`/`false` (app.py:523-545), but direct DB edits and restores bypass it. `paper_trader.is_paper_trading_enabled()` (paper_trader.py:26-34) is NOT a duplicate of this gap: it uses a different parser (`get_config("paper_trading","false").lower()=="true"`); a missing row or exception returns False ("paper disabled") and its only caller, `main()` (paper_trader.py:401), then `sys.exit(1)` — the safe direction. Two different parsers of the same config key is still a maintenance hazard: **13 other call sites** use the old `.lower()=="true"` parser (app.py:5853, 6552, 6631; scheduler.py:1043; telegram_commander.py:675, 701, 714, 1019, 1051, 1137, 1151, 1173; paper_trader.py:30), so for values like `1`, `yes`, `on` or `TRUE ` the dashboard, Telegram and the toggle report "LIVE" while the engine is in PAPER (display risk only). Broker check (verified 2026-09-27): a repo-wide grep for `.place_order(`/`create_smart_order(` finds exactly 5 order sites (bot.py:1743, 1832, 1897; fno_trader.py:1678, 1753), all via `growwapi.GrowwAPI`, each behind a paper gate (bot.py:1713, 1816, 1875; fno_trader.py:1646-1660, 1736-1749); no FYERS order call exists.
2. **Client never decides paper vs live** — GOOD, confirmed. Every gate reads `config_settings` server-side (`get_config`); no request parameter selects paper/live in any function read. Caveat: this covers the paper/live selection only — client-supplied PRICES do feed stop state (see finding 10).
3. **Idempotency / frontend withBusy** — partially verified from this scope: `/api/auto-trade` and `/api/buy` carry `@idempotent(...)`; `/api/monitor-trailing-stops` (app.py:3017) does NOT carry `@idempotent`, though it only mutates trailing-stop numbers and (per the finding above) never actually closes a trade via that path, so its blast radius if double-fired is limited to redundant state writes, not duplicate orders. `/api/auto-close/check` DOES carry `@idempotent("auto_close_check")`. Frontend `withBusy`/`Idempotency-Key` usage is in index.html, outside this section's scope — not verified here.
4. **Auto-exit loops can't machine-gun orders** — MOSTLY GOOD by construction: every close path checks `trade['status']=='OPEN'` before acting and flips it immediately; the file-lock+merge-by-id save pattern (shared by `PaperTradeTracker._save_trades` and `trailing_stop`'s direct writers) prevents two concurrent closers (the scheduler tasks and the browser-driven `/api/auto-close/check`) from both successfully closing the same trade twice, though see finding below re: `PaperTradeTracker.update_trailing_stop` never actually acting on its own CLOSE decision (so it cannot machine-gun, but also cannot close at all via that path). Caveat: the merge does not stop a stale copy overwriting a close — see finding 11.
5. **Capital ledger symmetry / TOCTOU** — `get_current_deployed_capital()` / `get_model_trade_budget()` are check-then-act with NO lock between the check (`bot.py:2242` `get_model_trade_budget`) and the later capital-cap re-check (`bot.py:2301` `_check_capital_cap_allows_trade`) and the actual `place_buy` write — in the current single-threaded-per-cycle scheduler design (one `_task_cash_auto_trade` invocation at a time, per-symbol loop within one thread) this is not exploitable concurrently, but there is no DB-level lock/constraint enforcing the per-model or global cap — it is enforced purely by re-reading `paper_trades.json`/DB on each check. If ever parallelized across symbols, this would TOCTOU. Also: the caps are enforced ONLY in paper mode (`_check_capital_cap_allows_trade` returns True when not paper, bot.py:1445-1446; the budget helpers sum only paper positions, bot.py:1377-1402) and both helpers fail open on exceptions (bot.py:1332-1333, 1400-1402) — see gates 6 and 9.
6. **Swallowed exceptions on money paths** — MIXED. `PaperTradeTracker.close_trade()` swallows the `trade_journal.close_matching_paper_trade` exception (paper_trader.py:327-328, logs CRITICAL but the trade stays closed in `paper_trades.json` regardless) — this is the exact class of desync the code's own comments describe as having caused real incidents (MARUTI, TITAN, HINDUNILVR). `bot._persist_trade_log_entry` and `bot._capture_trade_snapshot` also swallow failures (by design — non-critical side stores), each logging appropriately.
7. **Session rollback on trade commits** — GOOD where checked: `bot._paper_trade`'s manual `db.Session()` write explicitly rolls back on exception (bot.py:1557-1567); `bot._capture_trade_snapshot` likewise (bot.py:864-872); `trade_journal._save()` uses `with db.Session() as session:` (context-manager auto-close/rollback semantics) rather than manual try/rollback — consistent, no bare un-rolled-back session found in this scope.
8. **Standalone scripts bypass auto_trade's gates (but NOT the paper gate)** — NEW FINDING, not in the standard checklist but material: `execute_high_confidence_trades.py` (hardcoded historic TCS/NIFTY trade list, calls `place_fno_buy` directly, bypassing auto_trade's confidence, cost and capital gates) and `live_trade_executor.py`/`real_market_trading.py` (predict-only, do not actually call any order function) are unimported standalone scripts. None are called by app.py or scheduler.py (confirmed via `git grep`), so they pose no *automatic* risk. Correction (2026-09-27 verification): `execute_high_confidence_trades.py` bypasses auto_trade's confidence, cost and capital gates, but NOT the paper gate — `place_fno_buy` checks paper mode itself (fno_trader.py:1646-1660). In paper mode (the live config) the paper path calls `_paper_trade(segment="FNO")`, which raises, so the call returns `{"error": "Paper trade failed, no live order placed"}` and the script places nothing. In live mode 'TCS' is rejected as an unknown instrument (not in `ALL_FNO_INSTRUMENTS`); 'NIFTY' passes `_contract_belongs_to_instrument` but could only reach Groww if F&O capital ≥ ₹35,302.9 + charges, and it would send the underlying `trading_symbol="NIFTY"` rather than an option contract. Status: LEGACY/MANUAL, low residual risk.
9. **Paper SELL leaves an orphan OPEN short row (latent)** — In auto_trade's SELL path, `place_sell` → `_paper_trade("SELL")` → `record_entry` creates a NEW `status:'OPEN'` SELL row plus a SELL journal report. bot.py:2432-2436 closes only the BUY rows. The SELL row stays open as a phantom short, blocks new BUYs on that symbol, and is managed as a short by `check_and_close_trades_on_loss`. It has never happened yet: paper_trades.json holds 26 rows, all BUY/CLOSED.
10. **Client-supplied prices mutate stop state** — `POST /api/update-trailing-stops` (app.py:5886, no `@idempotent`) takes `{prices:{symbol:price}}` from the browser and feeds them into `update_trailing_stop`, which ratchets peak, `trailing_stop` and `hard_floor`. A bad client price can arm or ratchet a stop that the 300s closer then acts on. This touches the CLAUDE.md money-safety point "client never decides".
11. **The merge-by-id save does not stop stale overwrites** (inference from code, not observed) — see the `PaperTradeTracker` Storage row: each writer merges its FULL trade dicts, every dict carries `status`/`exit_*`, so a tracker loaded before a concurrent close can write `status:'OPEN'` back over it (paper_trader.py:81-89, trailing_stop.py:672-675).
12. **Cash exits have no server check at 09:15-09:20 or between 300s ticks** — `_task_auto_close_trades` is gated by `fno_trader._is_market_open` (09:20-15:15 only) and its DB interval is 300s. auto_trade's own monitor cannot close anything (see the Dead code table, first row). The hard stop-loss is therefore enforced by the server at most every 5 minutes, unless a dashboard tab has the Paper Trader open (index.html:14593).
13. **An XGB scan fails for ALL symbols if ONE symbol is unquotable** — `scan_watchlist_xgb`'s batched price prefetch raises `RuntimeError("live-price batch incomplete…")` when any symbol is unpriced (bot.py:633-647), caught at bot.py:2126-2129 ("XGB scan failed"). The only enabled cash model (live: XGB) then produces no entries for that cycle, logged at WARNING only. CLAUDE.md standard 7 ("missing data must be visible") applies.
14. **Every `fetch_live_price`/`get_ltp_batch` incurs an N+1 query** — `to_fyers_symbol()` SELECTs `master_ticker_table` once per symbol (fyers_market_data_provider.py:47-52): 67 queries per XGB scan before the 2 FYERS calls (see Market Data section). Violates CLAUDE.md standard #1.

### Dead / disabled / suspect code found in this scope
| Item | Where | Status |
|---|---|---|
| `PaperTradeTracker.update_trailing_stop` never returns `'closed'`/`'costs_covered'`, discards `trailing_strategy.evaluate()`'s CLOSE action | paper_trader.py:334-363 vs bot.py:1983-2013 | **CONFIRMED FROM CODE** — `bot.monitor_and_update_trailing_stops()` (part of every `auto_trade()` cycle, i.e. ≈ every 15s — registered 5s, scheduler loop tick 15s) can never close a trade or report one closed; its `summary["closed"]`/telegram "closed" alert (bot.py:1994-2001) branch is unreachable via this path. Real closing happens only via the parallel `trailing_stop.check_and_close_trades_on_loss` scheduler task. |
| CHECK 1 (breakeven floor), CHECK 2 (independent peak-erosion ladder incl. `PEAK_EROSION_60`) | trailing_stop.py:477-547 | DEAD — wrapped in `if False and ...`, superseded by `trailing_strategy.evaluate()`, retained only as documentation of prior rationale |
| CRITICAL-loss auto-close branch in `manage_loss_positions` | trailing_stop.py:787 | DEAD — `if False and ...`, superseded by the tighter hard stop-loss which always fires first |
| `trade_origin_manager.track_trade_origin` / `get_trade_origin` / `can_system_close_trade` (MANUAL-trade protection) | trade_origin_manager.py:73-129, consumed at trailing_stop.py:553-565 | Effectively DEAD — `track_trade_origin` has **zero call sites** anywhere in the repo, so `trade_origins.json` is never populated and `can_system_close_trade()` always returns its "no origin recorded" default of `True`. The MANUAL-trade close-protection feature does not currently protect anything. (Separately, `register_manual_holding`/`get_manual_holdings`/`calculate_available_capital_for_auto_trading` — a DIFFERENT, capital-exclusion feature in the same file — ARE wired to app.py endpoints and presumably active, though not independently traced further in this pass.) |
| `close_trades.py`, `live_trade_executor.py`, `real_market_trading.py`, `execute_high_confidence_trades.py` | repo root | LEGACY/MANUAL standalone scripts, zero callers anywhere in the repo (confirmed via `git grep`); `close_trades.py` and `execute_high_confidence_trades.py` hardcode specific historic prices/trades for a one-time manual run. `close_trades.py` additionally RUNS AT IMPORT (no `__main__` guard) and rewrites paper_trades.json with hardcoded prices via a plain unlocked `json.dump` (close_trades.py:7, 64-65), bypassing the flock/merge; it has zero importers. `execute_high_confidence_trades.py` bypasses auto_trade's gates but NOT the paper gate (money-safety finding 8) |
| `_apply_paper_trade_amount_limit()` | bot.py:1467-1470 | Explicitly a documented no-op ("Legacy helper... no longer caps per-trade") kept only for call-site compatibility |

### Cross-cutting facts (for the maps)

**External services + endpoints**: FYERS (market data: LTP/quote/batch LTP/historical candles — via `fyers_market_data_provider.FYERSMarketDataProvider`, rate-limited per CLAUDE.md rule 9, NOT re-verified in this pass since fetch_* functions were out of scope); Groww API (`growwapi.GrowwAPI` — order placement `place_order`, GTT `create_smart_order`, `get_positions_for_user`, `get_holdings_for_user`, `get_available_margin_details`, `get_order_list` — LIVE trading only, paper mode never reaches it except reading positions for the duplicate-entry guard, which itself is a live-mode-only signal since paper mode returns no positions); groww.in/charges (cost-rate scraper, `costs.update_cost_rates`, best-effort with a raw-HTML regex fallback); Telegram (`telegram_alerts`, best-effort, all calls in try/except).

**config_settings keys read in this scope** (key → default in code → LIVE value where checked):
`paper_trading` (false→**true**) · `model.gbc_cash_enabled` (True→**false**) · `model.xgb_cash_enabled` (XGB_LIVE_TRADING env→**true**) · `paper_trade_amount_limit` (0→**50000**) · `paper.cap.gradientboosting`/`paper.cap.xgboost` (50000→**50000**/**50000**) · `paper.min_confidence` (0.50→**0.50**) · `trade.max_breakeven_pct` (0.60→**0.60**) · `prediction.weight.{ml,trend,news,context}` (0.40/0.15/0.20/0.25→**same**) · `trade.no_auto_exit_enabled` (True→**true**, verified live 2026-09-27) · `trade.no_auto_exit_after` ("15:15"→**15:15**, verified live) · `portfolio_reviewed` (unset→False→**true**) · `scheduler_interval_auto_close_trades` (5→**300**) · `scheduler_interval_cost_scraper` (**3888000**) · `cost.*` (11 keys, hardcoded defaults documented in costs.py, not re-verified live in this pass).

**Env vars read in this scope** (name, file, default — secret values NOT read per SECRETS rule; live values are shown only for the non-secret limits, from the 2026-09-27 verification): `MAX_TRADE_QUANTITY` (config.py, code default 1000; **live `.env` = 10**; NOT applied to model-driven qty in `place_buy`, bot.py:1692-1695) · `MAX_TRADE_VALUE` (config.py, code default 999999999; **live `.env` = 50000** — a hard ₹50k per-order cap enforced by `place_buy` on every path, bot.py:1706-1710) · `CONFIDENCE_THRESHOLD` (config.py:22, **0.65**) · `STOP_LOSS_PCT` (config.py, 2.0, clamped to `MAX_CASH_SL_PCT`=1.0 literal) · `TARGET_PCT` (config.py, 4.0) · `MAX_POSITIONS` (config.py, 5) · `WATCHLIST` (config.py, 10-symbol CSV fallback only — DB is the real source via `get_active_watchlist`) · `XGB_TRAIN_DAYS` (bot.py, unset→full history) · `XGB_PREDICT_DAYS` (bot.py, 10) · `XGB_LIVE_TRADING` (bot.py:601, code default false; **live `.env` = true**, moot because DB `model.xgb_cash_enabled=true` overrides, bot.py:2090-2096) · `LTT_YEARS` (bot.py, 5) · `GROWW_ACCESS_TOKEN`/`GROWW_API_KEY`/`GROWW_API_SECRET` (config.py, secrets — names only).

**Timed/triggered execution (WHEN → WHAT)**, cash-equity relevant, from scheduler.py registrations seen in this pass:
- Registered 5s, effective ≈ every 15s (the scheduler loop sleeps 15s between dispatch passes, scheduler.py:1291) → `_task_cash_auto_trade` → `bot.auto_trade()` (gated by `cash_auto_trade_enabled` config, default **false** per scheduler.py:802, live value **true** — NOTE: separate from `model.gbc_cash_enabled`/`model.xgb_cash_enabled`; three independent on/off switches govern whether cash trading actually runs, plus market-hours + boot-warmup)
- **Every 300s (5 min)** — registered 5s, but DB `scheduler_interval_auto_close_trades=300` (updated 2026-08-26 04:26) overrides it → `_task_auto_close_trades` → `trailing_stop.check_and_close_trades_on_loss` (09:20-15:15 only; the REAL trailing/hard-SL/target closer). Between runs, closes happen only while a browser has the Paper Trader open (index.html:14593)
- Registered 5s, effective ≈ every 15s → `_task_record_pnl` → `PnLSnapshot` writes (market-hours gated)
- Every 300s → scheduler task `auto_analysis` (scheduler.py:1325; skipped during boot warm-up, scheduler.py:102-103) → `auto_analyzer.auto_analyze_watchlist()` → `bot.scan_watchlist()` (auto_analyzer.py:172; read-only, display/dashboard only — NOT gated by `cash_auto_trade_enabled`). `start_auto_analyzer` is only the FALLBACK thread when `start_scheduler()` raises (app.py:8173-8181)
- App start → `trade_journal.reconcile_with_tracker()` (per its own docstring; call site is in app.py, not verified in this pass)
- Every 3,888,000s (45 days) → scheduler task `cost_scraper` → `costs.update_cost_rates()` (scheduler.py:1348; DB override `scheduler_interval_cost_scraper=3888000`). VERIFIED 2026-09-27: 45 days is correct; the `costs.py:6` docstring ("every 3 days") is stale.

**Rate limits / cost drivers**: `scan_watchlist()`/`scan_watchlist_xgb()` fan out ThreadPoolExecutor(6) over ~70-73 symbols ≈ every 15s (when cash auto-trade enabled; registered 5s, scheduler loop tick 15s) PLUS every 300s from `auto_analyzer` — each symbol prediction pulls FYERS candles, a batched LTP, news sentiment, and market/sector context (itself 3-4 more candle reads, DB-first with live-API fallback). `analyze_long_term_trend` runs one `psycopg2` connection + query per symbol per prediction (own connection, not pooled through `db_manager` — a small resource-per-call cost across ~70 symbols every cycle). FYERS rate limits themselves (10/sec, 200/min Standard) were NOT re-verified in this pass (fetch layer explicitly out of scope). Each `get_ltp_batch`/`fetch_live_price` also incurs one `master_ticker_table` SELECT per symbol via `to_fyers_symbol()` (N+1, see Market Data section) — 67 queries per XGB scan before the 2 FYERS calls.

**Fail-open vs fail-closed summary**: fail-closed (confirmed) — position-lookup failure in `auto_trade` (both broker and paper), model-enable config-read failure, `automated_exits_allowed` config-read failure (defaults to enabled/frozen), `is_paper_mode` on a config EXCEPTION. Fail-open (confirmed) — `is_paper_mode` on a config row that is ABSENT or has a NULL value (defaults to "false"=live, currently masked by the live DB value being `"true"`; NOTE `paper_trader.is_paper_trading_enabled` is fail-safe — missing row → False → `main()` exits); `_check_capital_cap_allows_trade` returns True (no cap) in LIVE mode and both capital helpers fail open on exceptions (bot.py:1332-1333, 1400-1402); `can_system_close_trade` defaults to "can close" when no origin recorded (feature is unpopulated, so this is permanently the fallback).

**Contradictions between code/config/comments found in this pass**:
1. bot.py:597-601 comment ("XGB defaults off until backtest exists") vs LIVE config (XGB cash ON, GBC cash OFF) — the actual live setup is the reverse of the documented rationale's assumed state.
2. `costs.py` docstring ("scheduled task refreshes rates every 3 days") vs `update_cost_rates()`'s own docstring ("Called by scheduler every 45 days") — internally inconsistent; RESOLVED: the actual interval is 45 days (scheduler.py:1348), so the "3 days" docstring at costs.py:6 is stale.
3. `bot.monitor_and_update_trailing_stops()` docstring/summary implies it can close trades ("Returns a summary of actions taken" incl. `closed` count) but its only closing signal (`tracker.update_trailing_stop() == 'closed'`) is never produced by the callee.
4. `manage_loss_positions()`'s module-level docstring in trailing_stop.py describes CRITICAL positions as "Close immediately" but that branch is dead (`if False`).
5. `monitor_and_update_trailing_stops`'s comment says stop LEVELS keep updating during the exit freeze, but the code returns before any update (bot.py:1929-1931).
6. `paper_trader.py`/`bot.py` docstrings present `update_trailing_stop` as the trailing-stop actor, but it always returns `'trailing_updated'` (or None) and never acts on CLOSE (paper_trader.py:334-363).

**Open unknowns (UNKNOWN — NOT DETERMINABLE FROM CODE in this pass)**:
- RESOLVED: live `trade.no_auto_exit_enabled` = true and `trade.no_auto_exit_after` = 15:15 (verified 2026-09-27).
- Whether the XGB-vs-GBC backtest referenced in bot.py comments was actually completed before the live flip to XGB-only cash trading.
- RESOLVED: `costs.update_cost_rates()` runs every 45 days (scheduler.py:1348; `cost_scraper` = 3,888,000s).
- RESOLVED (a finding rather than an unknown): a `paper_trading` row with a NULL `value` also falls through to LIVE (see money-safety finding 1).
- Whether `app.py`'s call to `trade_journal.reconcile_with_tracker()` at app start is unconditional or gated (app.py not read in full in this pass; only specific line ranges around known call sites were read).
- Frontend (`index.html`) `withBusy`/`Idempotency-Key` usage on the cash-trading endpoints — out of this section's file scope.

Files fully read for this section (16): bot.py (2581 lines), paper_trader.py (592), trailing_stop.py (872), trailing_strategy.py (221), trade_journal.py (1056), paper_trade_reconciliation.py (448), costs.py (435), live_trade_executor.py (159), real_market_trading.py (153), execute_high_confidence_trades.py (175), trade_origin_manager.py (192), trade_chart_manager.py (326), close_trades.py (80), auto_analyzer.py (288), market_context.py (308), config.py (59). Plus targeted greps/line-ranges into scheduler.py and app.py to confirm callers, intervals, and DB-writer verification (not full reads — outside this section's assigned scope, flagged as such above).

---

## Trading Engine — F&O, Intraday & Options Strategies

Overview: `fno_trader.py` (2,627 lines) is the F&O (index/stock/MCX options) auto-trading engine — opportunity
scoring, option-chain selection, order placement, exits, capital ledger. Intraday/MIS equity trading is NOT a
separate backend module — it is a small set of endpoints in `app.py` (~3403-3702) backed by the `TradeJournalEntry`
DB table, and it is **currently broken** (see Money-safety findings). `fno_backtester.py` (1,935 lines) is an
offline/on-demand swing backtester + XGBoost signal generator used both for manual backtests and as the primary
live F&O signal source (`fno_trader.analyze_fno_opportunity` calls `fno_backtester.get_xgb_signal` first).
`options_strategies.py` not yet read — pending.

---

### F&O instrument knowledge base — `fno_trader.py:57-122`
| Field | Detail |
|---|---|
| What | `_FALLBACK_FNO_LOT_SIZES` / `_FALLBACK_MCX_CONTRACTS` hardcoded dicts (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY, HDFCBANK; MCX: CRUDEOILM, NATURALGAS, NATGASMINI, GOLDM, SILVERM), merged with DB overrides via `auto_metadata.get_fno_lot_config()` in `_load_fno_lot_sizes`/`_load_mcx_contracts` (fno_trader.py:78-114); `get_fno_lot_config` reads prefixes `fno.lot.` then `mcx.lot.` (auto_metadata.py:520-531), so the seeded `mcx.lot.*` rows override the MCX fallback |
| Loaded | At import time (module-level `FNO_LOT_SIZES = _load_fno_lot_sizes()`, line 118) — NOT re-read per call. A DB lot-size change requires a process restart to take effect. |
| Source of truth | DB `config_settings` (`auto_metadata.seed_fno_config`, per comment line 56) overrides the hardcoded fallback; fallback used if DB read throws. |
| Status | ACTIVE |

### `calculate_fno_costs()` — F&O round-trip cost calculator, `fno_trader.py:171-244`
| Field | Detail |
|---|---|
| What/Why | Computes brokerage, STT, exchange txn, SEBI fee, GST, stamp duty for a buy(+optional sell) leg. Used both for pre-trade cost display and inside every buy/auto-trade gate to compute all-in cost. |
| Config keys (fno.* prefix, via `auto_metadata.get_fno_cost_rate`) | `stt.option_sell_pct` (0.0625 fallback), `stt.futures_sell_pct` (0.0125), `exchange.nse_pct` (0.0495), `exchange.bse_pct` (0.0325), `exchange.mcx_pct` (0.0260), `sebi_pct` (0.0001), `gst_pct` (18.0), `stamp_duty_pct` (0.003), `brokerage_per_order` (₹20), `brokerage_pct_cap` (0.05%) |
| Failure behaviour | Any exception loading DB rates → falls back silently to the literal fallback constants (fail-open on cost calc, not on trade gating) |
| Status | ACTIVE |

### Capital ledger — `sync_capital_from_groww` / `get_fno_capital` / `get_used_capital` / `update_used_capital` / `get_available_capital` — `fno_trader.py:252-344`
| Field | Detail |
|---|---|
| What/Why | Single ₹-denominated capital pot for F&O, stored in `config_settings` keys `fno.capital` and `fno.used_capital`. `get_available_capital = fno.capital - fno.used_capital`, floored at 0. |
| Paper mode | `sync_capital_from_groww()` explicitly SKIPS syncing real Groww margin when `bot.is_paper_mode()` is true — preserves a virtual capital pot (seeds `fno.capital=10000` if currently 0). Only syncs real Groww `option_buy_balance_available`/`clear_cash` (whichever higher) when NOT paper mode. |
| When | Called by scheduler task `fno_capital_sync` every 600s (`scheduler.py:1332`), and at the start of every `auto_trade_fno()` cycle (registered 5s, effective ≈ every 15s — the scheduler loop sleeps 15s between dispatch passes, scheduler.py:1291 — so it is effectively re-synced every cycle since auto_trade_fno calls it directly, not just the 600s task) |
| **Money-safety finding** | `update_used_capital` (deploy) is applied at buy time using `all_in` cost (entry premium + charges) — but `place_fno_sell`'s capital release (fno_trader.py:1769-1786) frees capital based on **current LTP × qty at sell time**, not the original entry deployment. Comment in code (lines 1764-1786) explicitly flags this as a known asymmetry: "creates asymmetry and a growing gap in the ledger over time" and recommends manual `sync_capital_from_groww()` reconciliation. This is a genuine capital-ledger drift bug, self-documented, unresolved. `sync_capital_from_groww()` already runs every cycle and only rewrites `fno.capital`, never `fno.used_capital`, so it cannot repair the drift. **Live-mode double count (inference, not observed)**: `sync_capital_from_groww` sets `fno.capital` to the broker's available balance (fno_trader.py:283-294), which is already net of open positions, and the ledger then subtracts `fno.used_capital` again, so `get_available_capital()` likely double-counts deployed F&O capital in live mode. |
| DB keys | `fno.capital`, `fno.used_capital` (config_settings) |
| Status | ACTIVE |

### `find_affordable_options()` — `fno_trader.py:409-504`
| Field | Detail |
|---|---|
| What/Why | Given instrument+expiry+budget, fetches option chain, filters strikes whose premium×lot_size + round-trip costs ≤ budget, reserving ₹40 for brokerage. Scores by OI (30%), cost/breakeven (40%), abs(delta) (30%); returns top 20 sorted by score. |
| Inputs | `budget` defaults to `get_available_capital()` if not passed |
| Blast radius | Feeds directly into `auto_trade_fno()`'s option selection (best-scored, OI ≥ 10,000 filter) |
| Status | ACTIVE |

### `analyze_fno_opportunity()` / `_analyze_fno_opportunity_heuristic()` — `fno_trader.py:1161-1550`
| Field | Detail |
|---|---|
| What/Why | Primary signal generator for one instrument. Tries `fno_backtester.get_xgb_signal()` first (ML); if XGBoost unavailable/neutral, falls back to a 7-source weighted heuristic. |
| XGBoost path | If XGB direction != NEUTRAL and `xgb_available`, boosts confidence up to +30% when global sentiment agrees (`confidence > 0.55` gate), or ×0.8 if global sentiment contradicts (`abs(global_score) > 0.4`). Returns immediately — heuristic is NOT blended in when XGB fires. |
| Heuristic weights (`_SIGNAL_WEIGHTS`, line 1150-1158) | technicals 0.25, news 0.15, x_social 0.10, oi_pcr 0.15, trend 0.10, geopolitical 0.10, global 0.15 (sums to 1.00) |
| Decision thresholds | `weighted_score > 0.10` → BULLISH (BUY CE); `< -0.10` → BEARISH (BUY PE); else NEUTRAL. `confidence = abs(weighted_score)`. `strength`: "strong" if confidence>0.3, "moderate" if >0.15, else "weak" (fno_trader.py:1523-1538) |
| Sub-signals | Technicals: RSI/MACD/EMA-crossover/Bollinger/Stochastic/candlestick patterns/RSI-divergence/DOW-volume-confirmation, averaged. News: `news_sentiment.get_news_sentiment()`, score×2 clamped ±1. X/social: Google-RSS-sourced X posts via `news_sentiment._fetch_x_posts`. OI: PCR>1.2 bullish / <0.7 bearish + max-pain (`_analyze_oi`, fno_trader.py:1051-1144). Trend: today's %change /3, clamped. Geopolitical: commodity risk level from `commodity_tracker.get_geopolitical_context` (bullish for commodities on high risk, bearish for indices). Global: `get_global_sentiment()` weighted VIX-inverted + equity-index score. |
| Failure behaviour | Each of the 7 signal sources is independently try/excepted — a failing source is silently skipped (its weight contributes 0), never blocks the others. Fail-open per-signal, not fail-closed. |
| Status | ACTIVE (XGB primary, heuristic fallback) |

### `place_fno_buy()` / `place_fno_sell()` — order placement, `fno_trader.py:1606-1809`
| Field | Detail |
|---|---|
| What/Why | Only BUY (opening) and SELL (closing an existing buy) are supported — no naked option writing (module docstring: "With ₹1000 capital, ONLY option buying is feasible"). |
| Safety validation (buy) | `_contract_belongs_to_instrument()` (fno_trader.py:1581-1603) — refuses if `trading_symbol` doesn't start with the instrument's `underlying`, preventing e.g. a NIFTY instrument_key placing a BANKNIFTY-symbol order at NIFTY's lot size (found + fixed bug, per inline comment: previously "five times the intended position, on real money"). `_finite_positive()` (fno_trader.py:1557-1578) rejects NaN/Infinity/non-finite/≤0 premium and quantity — explicit defense because `float('nan') > x` is always False, so a naive `if cost > available: refuse` gate silently passes NaN through. |
| Paper gate (buy) | `from bot import is_paper_mode, _paper_trade`; if the paper-mode **check itself** throws, the function refuses and returns an error (does NOT fall through to a live order) — explicit "SAFETY" comment: this block "must never fall through to the live order below." If paper: records via `bot._paper_trade(...)` and returns; any exception there also aborts (does not fall through). Only reaches the live Groww `place_order()` call if `is_paper_mode()` returns False cleanly. In paper mode the capital gates below are skipped entirely — they sit AFTER the paper intercept (fno_trader.py:1646-1660). For FNO/COMMODITY segments `_paper_trade` always raises (see Finding #1). |
| Live order (buy) | `groww.place_order(..., product="NRML", order_type="MARKET", transaction_type="BUY")`. Two capital gates before order: `all_in > available_capital` → refuse; `all_in > total_fno_capital` → refuse (redundant second check). On success: `update_used_capital(+all_in)`, `_log_fno_trade(...)`. |
| Live order (sell) | Same paper-gate pattern (fail-closed on check failure). On success: capital-release uses **current LTP**, not entry cost (see capital-ledger finding above) — if the LTP fetch itself fails, logs a warning and capital stays marked deployed (ledger drifts high, i.e. fails toward *understating* available capital, which is the safer direction). |
| Idempotency | NOT idempotent internally — protection is entirely the `@idempotent("fno_buy")` / `@idempotent("fno_sell")` decorators at the Flask route level (`app.py:3234-3274`). The scheduler's automated call path (`auto_trade_fno()` → `place_fno_buy`) bypasses the Flask decorator entirely — its only duplicate-order defenses are the `max_positions` cap and (for exits) the 5-minute `_RECENT_EXITS` cooldown; entries have no equivalent per-cycle cooldown beyond `_count_open_positions()`. |
| Status | ACTIVE |

### Position exits — `_check_position_exits()`, `fno_trader.py:2223-2326`
| Rule | Formula | Threshold (config) | Where set |
|---|---|---|---|
| Stop-loss | `pnl_pct = (ltp-buy_price)/buy_price*100` | exit if `pnl_pct <= -50` | `_AUTO_TRADE_CONFIG["stop_loss_pct"]=50`, fno_trader.py:2164 |
| Target | same pnl_pct | exit if `pnl_pct >= 80` | `_AUTO_TRADE_CONFIG["target_pct"]=80`, line 2165 |
| Trailing stop | INTENDED rule: track `peak` LTP per symbol in DB cache (`fno_peak:{symbol}`, 24h TTL); exit if `pnl_pct > 30` (trailing_sl_pct, line 2166) AND price has drawn down **>15% from peak** (hardcoded literal, line 2305 — NOT config-driven). **It can NEVER fire**: `peak_price = peak_data.get("peak", ltp) if peak_data else ltp`, and the peak is only written `if ltp > peak_price`; on first read `peak_price == ltp`, so the peak is never persisted (fno_trader.py:2292-2305) and drawdown is always 0. DB check: `SELECT count(*) FROM analysis_cache WHERE cache_key LIKE 'fno_peak:%'` → 0 rows. Latent — F&O has not traded. The rule also only applies while 30% < pnl < 80% (`elif` chain) | activation 30%, drawdown trigger 15% (hardcoded) — dead mechanism | fno_trader.py:2292-2305 |
| Exit-storm guard | `_RECENT_EXITS` dict, key=(symbol,reason), 300s (5 min) cooldown (fno_trader.py:27-48) | prevents the `_task_fno_auto_trade` scheduler cycle (registered 5s, effective ≈ 15s) from re-selling the same position 2-3× before broker fills reflect in the position lookup (documented root cause in module header comment) | — |
| All exits | call `place_fno_sell()` (same paper-gate as above) | — | — |
Note: exits do NOT respect `max_positions` — they run unconditionally whenever a position qualifies, independent of the entry-side room check. Confirmed no in-flight/pending-order guard beyond the 5-min per-(symbol,reason) cooldown — a stop-loss and a target could theoretically both fire for the same symbol in the same cycle if both conditions were simultaneously true (mutually exclusive in this code: `elif` chain, so only one fires per cycle) — **safe by `elif`, not by an explicit lock**.

### `_count_open_positions()` — fail-closed guard, `fno_trader.py:2198-2220`
| Field | Detail |
|---|---|
| What/Why | Wraps `get_fno_positions()`; returns `len(positions)` on success. |
| Fail-closed | On ANY exception, explicitly returns `None` (not `0`) with a `logger.error` "SAFETY" message — callers (`auto_trade_fno`) must treat `None` as unknown and refuse new entries. Comment explicitly rejects `0`-on-error as the wrong behaviour ("returning 0 on error... reads as no positions are open"). `auto_trade_fno()` (line 2444) checks `if open_positions is None:` explicitly before the `>=` comparison (also avoids a `TypeError` from `None >= int`). |
| Status | ACTIVE — correctly implements CLAUDE.md operational rule #8 ("guards must fail closed") |

### `_select_best_opportunity()` — `fno_trader.py:2329-2388`
| Field | Detail |
|---|---|
| What/Why | Scans `_AUTO_TRADE_CONFIG["preferred_instruments"]` = `["NIFTY","BANKNIFTY","FINNIFTY"]` (line 2168) in order, runs `analyze_fno_opportunity` per instrument, skips NEUTRAL, requires `strength >= "moderate"` (config `min_strength`) and `confidence >= 0.20` (config `min_confidence`), then adjusts confidence by global sentiment alignment (×(1+|global|×0.5) if aligned, ×0.7 if global contradicts and \|global_score\|>0.3), and picks the single highest adjusted-confidence instrument. |
| Note | Only 3 preferred instruments scanned even though `ALL_FNO_INSTRUMENTS` includes SENSEX, MIDCPNIFTY, HDFCBANK, and 5 MCX contracts — those are tradeable manually via `/api/fno/buy` but never auto-selected. |
| Status | ACTIVE |

### `auto_trade_fno()` — main automated pipeline, `fno_trader.py:2391-2566`
Full pipeline, called by scheduler (`scheduler.py:1329`, `_task_fno_auto_trade`, registered 5s, initial_delay=2s; effective cadence ≈ every 15s because the scheduler loop sleeps 15s between dispatch passes, scheduler.py:1291) AND manually via `POST /api/fno/auto-trade/run` (`app.py:3371-3380`, idempotent-wrapped):
1. **Market hours check** — `_is_market_open()` (fno_trader.py:2177-2195): weekday<5 AND 9:20–15:15 IST (`nse_open_hour/min`, `nse_close_hour/min` in `_AUTO_TRADE_CONFIG`, lines 2171-2172). Skips (does not proceed) if closed, when `market_hours_only=True` (default True, line 2169).
2. **Capital sync** — `sync_capital_from_groww()` (paper-mode-aware, see above).
3. **Guard**: `available < 50` (fno_trader.py:2423) → **returns immediately**, logging `skipped_reason` — this is BEFORE the exit check runs.
4. **Exit check** — `_check_position_exits()` (step "3" in the function's own comments, fno_trader.py:2429) only runs if the ₹50 gate above passed. **Money-safety finding: if `get_available_capital()` reads <₹50 (e.g. because a big loss already consumed the capital pot, or the ledger-drift bug above has pushed `used_capital` up), stop-loss/target/trailing-stop exits are skipped for that entire scheduler cycle (≈15s)** — the one path that should never be gated by capital availability (closing a position frees capital, it doesn't need it) is fail-open in the wrong direction here: low capital silently disables the exit check rather than only disabling new entries.
5. **Position-room check** — `_count_open_positions()`; `None` → refuses entry (logs SAFETY); `>= max_positions(2)` → skip.
6. **`_select_best_opportunity()`** as above.
7. **Expiry + option selection** — nearest expiry from `get_expiries()`; `find_affordable_options()`; filter by `CE`/`PE` matching direction; take top-scored candidate; **additional liquidity gate: reject if `open_interest < 10000`** (line 2499, hardcoded literal, not config).
8. **Execute** — `place_fno_buy()` with a reasoning string embedding the top-5 heuristic/XGB reasons.
9. Every branch writes a `log_entry` (timestamp, actions, analysis, skipped_reason) via `_log_auto_trade()` → DB cache key `fno_auto_trade_log`, keeps last 200 entries, 30-day TTL.
`_AUTO_TRADE_CONFIG` full values: `enabled=True` (**dead — never read, see kill-switch finding below**), `min_confidence=0.20`, `min_strength="moderate"`, `max_positions=2`, `stop_loss_pct=50`, `target_pct=80`, `trailing_sl_pct=30`, `avoid_expiry_day=True` (**declared but never checked anywhere in the file — dead flag, confirmed by grep: no `avoid_expiry_day` read outside the dict literal**), `preferred_instruments=[NIFTY,BANKNIFTY,FINNIFTY]`, `market_hours_only=True`, NSE open 9:20/close 15:15, MCX close 23:30 (`mcx_close_hour`/`min` — **also declared but never read; no MCX-hours check exists in `_is_market_open()`, which only checks NSE hours** — so MCX contracts, if ever auto-selected, would be gated by NSE hours only, and since MCX isn't in `preferred_instruments` this is currently moot but is a latent bug if MCX is ever added to the preferred list).
Runtime-mutable via `update_auto_trade_config()` (`app.py:3392-3399`, `POST /api/fno/auto-trade/config`) — **in-memory only, not persisted to DB/config_settings; a restart reverts to the hardcoded dict.** The endpoint also accepts arbitrary keys and values with no validation or idempotency (app.py:3392-3399) — e.g. `market_hours_only:false`, any `max_positions`, or string thresholds that would raise TypeError in the gates.

### THE REAL KILL SWITCH — `scheduler.py:636-659` (`_task_fno_auto_trade`), NOT in fno_trader.py
| Field | Detail |
|---|---|
| Config key | `fno_auto_trade_enabled` (config_settings) |
| Default | `"true"` if the DB row is absent (`get_config("fno_auto_trade_enabled", "true")`) — **fails OPEN (trading stays on) if the config row is missing**, deliberately, per inline comment: "Defaults to true — seeding this key must not silently stop F&O trading. Turning it off is the deliberate action." |
| Why this exists | Code comment states plainly: `fno_trader._AUTO_TRADE_CONFIG["enabled"]` is defined but **nothing ever reads it** — this scheduler-level gate is the only thing that ever stops the auto-trade loop besides paper mode. Confirmed by repo-wide grep: no reference to `_AUTO_TRADE_CONFIG["enabled"]` or `CONFIG.get("enabled")` anywhere in `fno_trader.py` or its callers. |
| Scope | Only gates the **scheduler's automatic** cycle (≈ every 15s). Manually calling `POST /api/fno/auto-trade/run` calls `fno_trader.auto_trade_fno()` directly and is NOT gated by `fno_auto_trade_enabled` — a manual trigger runs even if the kill switch is off. |
| Status | ACTIVE gate on the scheduler path only |

### Global sentiment / global indices — `fno_trader.py:1936-2151`
| Field | Detail |
|---|---|
| Sources | Indian indices (NIFTY/BANKNIFTY/FINNIFTY/SENSEX/MIDCPNIFTY/INDIAVIX) live from Groww `get_quote`; international (S&P500/NASDAQ/DowJones/US-VIX/Nikkei/HangSeng) via yfinance, parallelized `ThreadPoolExecutor(max_workers=4)` with per-ticker 20s timeout (`_fetch_intl_indices`, line 2029) — correctly parallel, satisfies engineering standard #3. |
| Caching | `fetch_global_indices()` result cached in DB (`global_indices` key); `get_global_sentiment()` reads that cache with 1800s (30 min) TTL before recomputing. |
| Scheduler | `_task_global_indices` every 900s (15 min) (`scheduler.py:1338`) refreshes the cache; `get_global_sentiment` inside a live `analyze_fno_opportunity` call will use the 30-min-stale cache unless it's expired. |
| Scoring | VIX/India-VIX: `-change_pct/10` clamped ±1 (inverted — rising VIX = bearish). Equity indices: `change_pct/3` clamped ±1. Weighted by per-index `weight` (sums to <1.0 across all sources; not renormalized to exactly 1 — normalized only by `total_weight` actually present, so missing sources don't bias the average incorrectly). |
| Status | ACTIVE |

---

## MONEY-SAFETY FINDING #1 (headline): F&O paper trading is currently non-functional end-to-end

**VERIFIED FROM CODE.** `fno_trader.place_fno_buy()`/`place_fno_sell()` route paper trades through
`bot._paper_trade(trading_symbol, side, quantity, price, segment=inst["segment"], product="NRML", ...)`
(fno_trader.py:1655, 1745). For every F&O instrument `inst["segment"]` is `"FNO"` or `"COMMODITY"` — never
`"CASH"`. `bot._paper_trade()` (bot.py:1473-1500) now explicitly **refuses any non-CASH segment**:
```
seg = str(segment or "").upper()
if seg != "CASH":
    raise ValueError(f"Paper trader is cash-equity only; refusing {seg or 'UNKNOWN'} order for {symbol}")
```
The comment block above it (bot.py:1479-1494) explains why: F&O paper trades used to land in the same
`paper_trades.json`/tracker as cash trades, indistinguishable by segment, and got double-wrong-costed (charged
as equity INTRADAY on entry, equity DELIVERY on exit) — "two different wrong charge models on one option". The
fix was to hard-refuse F&O/COMMODITY segments from this tracker entirely, and it was correctly reasoned to
**raise** (not return an error dict) so a caller cannot mistake the refusal for a recorded trade.
**Net effect today**: `place_fno_buy`/`place_fno_sell` catch this raised exception (their own try/except around
the `_paper_trade` call) and return `{"error": "Paper trade failed, no live order placed: ..."}` — so this
fails safe (no money moves, no live order) — but it means **every F&O paper buy/sell attempt currently errors
out and records nothing**, whether triggered manually via `/api/fno/buy`/`/api/fno/sell` or automatically via
the `_task_fno_auto_trade` scheduler loop (≈ every 15s, when its kill switch is on). Given `paper_trading=true`
LIVE (see below), and F&O being option-buying-only with no live-mode alternative in this state, **the F&O
engine cannot currently complete a single trade in either direction** — paper is refused, and live is gated
off by paper mode. No separate FNO-specific paper-trade store exists (`git grep` for `fno_paper`/`FnoPaperTrade`
returns nothing) — the refusal is DELIBERATE and documented (`_paper_trade`'s docstring, bot.py:1476-1495, explicitly names `place_fno_buy`/`place_fno_sell`), and `logger.exception` fires on every attempt, so it is not "silently" broken — it is a known consequence of the CASH-only hardening with no replacement F&O paper store. Also: in paper mode F&O skips the capital gates entirely (they sit after the paper intercept).

## MONEY-SAFETY FINDING #2: exits are skipped when capital reads low (see auto_trade_fno step 3/4 above)
`_check_position_exits()` only runs if `get_available_capital() >= 50`. A stop-loss/target/trailing-stop check
should never depend on *available* capital (closing a position frees capital, it doesn't consume it) — this
gate can silently suppress exits precisely when the account is already under stress. fno_trader.py:2423-2429.

## MONEY-SAFETY FINDING #3: capital ledger deploy/release asymmetry (documented in-code, unresolved)
`update_used_capital` deploys `all_in` (entry premium + charges) on buy but `place_fno_sell` releases capital
using **sell-time LTP × qty**, not the original entry deployment (fno_trader.py:1764-1786, comment explicitly
calls this out as "asymmetry... a growing gap in the ledger over time"). Drift direction: since options are
usually sold either as a loss (LTP < entry) or gain (LTP > entry), the ledger's "used capital" figure will
systematically diverge from reality in either direction depending on win/loss mix — there is no periodic
reconciliation task; the code comment suggests a manual `sync_capital_from_groww()` call, but that is misleading — the function already runs every cycle (and every 600s) and only rewrites `fno.capital`, never `fno.used_capital`, so it cannot repair the ledger drift. In LIVE mode there is a further likely double count (inference, not observed): `sync_capital_from_groww` sets `fno.capital` to the broker's available balance (fno_trader.py:283-294), which is already net of open positions, and the ledger subtracts `fno.used_capital` again.

## MONEY-SAFETY FINDING #4: three /api/intraday endpoints + /api/fno/sync-capital call functions that don't exist (AttributeError)
Confirmed by grep — `fno_trader.py` defines `_get_groww()` (not `_groww_api`) and `_select_best_opportunity()`
(not `find_best_opportunity`), and has no `get_fno_account_balance()` (only `get_fno_capital()`/
`sync_capital_from_groww()`). Yet:
| Endpoint | Broken call | app.py line |
|---|---|---|
| `POST /api/intraday/enter-paper` | `fno_trader._groww_api.get_quotes(...)` | 3427 |
| `POST /api/intraday/close-paper` | `fno_trader._groww_api.get_quotes(...)` | 3496 |
| `POST /api/intraday/auto-trade-run-paper` | `fno_trader.find_best_opportunity()` AND `fno_trader._groww_api...` | 3563, 3574 |
| `POST /api/fno/sync-capital` | `fno_trader.get_fno_account_balance()` | 3709 |
All four fail on the AttributeError — `auto-trade-run-paper` and `sync-capital` return HTTP 500 with the exception text, while `enter-paper` and `close-paper` catch it in an inner `except` and return HTTP **503** "Cannot fetch live price … market data unavailable" (app.py:3433-3435 and the matching block after 3496), a misleading message that misdiagnoses a code bug as a market-data outage — so they
fail **before** any DB write or broker call, which is safe, but the features are **completely non-functional**.
The frontend actively calls the first three: `index.html:13742` (enter-paper), `13797` (close-paper), `13852`
(auto-trade-run-paper, when the Intraday module's paper-mode toggle is ON — the default). `intradaySyncCapital()` also calls `/api/fno/sync-capital` at `index.html:13880`, which always fails. **Clicking "enter
long" or "close position" or "run auto-trade" in the dashboard's Intraday tab in paper mode currently always
fails.** In non-paper ("real") mode, `intradayEnterTrade`/`intradayClosePosition` (index.html:13766-13770,
13822-13825) only show a toast and contain `// TODO: Call real trade endpoint` (index.html:13769) / `TODO: Call real close endpoint` (index.html:13826) — **no live intraday equity
order path exists in the frontend at all**; the only wired "real" action is `intradayRunAutoTrade`'s real-mode
branch, which calls `/api/fno/auto-trade/run` (the F&O options engine, not equity MIS) — a UI/label vs.
backend-behaviour mismatch: the "Intraday" module's real auto-trade button actually runs F&O options
auto-trading, not equity intraday trading.
Also: no scheduled task ever auto-closes a `TradeJournalEntry` row (the intraday paper-trade table) — the only
close path is the (broken) manual endpoint, so even if entry worked, nothing would ever exit automatically.

## MONEY-SAFETY FINDING #5 (positive, with caveats): idempotency on F&O endpoints is solid only for callers that send `Idempotency-Key` (not required by live config)
`/api/fno/buy`, `/api/fno/sell`, `/api/fno/auto-trade/run` are `@idempotent(scope)`-wrapped (app.py:632-753).
DB-backed claim/replay keyed on `(Idempotency-Key, scope)` + a SHA-256 body fingerprint (catches key-reuse for a
different order). If the wrapped handler raises, the key is left `in_flight` deliberately (a retry gets 409, not
a silent re-run) — "marking it failed here would make it re-claimable, which is exactly how a crash after a fill
turns into a duplicate trade" (app.py:704-720). Non-2xx responses are still stored as terminal/replayable, since
these routes call the broker before returning 4xx, so a 400 does not prove no order was placed. **Caveat**: this
protection only covers the two manual Flask routes — the scheduler's direct call `fno_trader.auto_trade_fno()`
(≈ every 15s) bypasses the decorator entirely; its only duplicate-order defenses are the `max_positions` cap on
entries and the 5-minute `_RECENT_EXITS` cooldown on exits (fno_trader.py:27-48) — a deliberate, documented
mitigation for "broker position data lags fills by seconds", not a full in-flight guard. If a broker fill takes
>5 minutes to reflect in `get_fno_positions()`, a stop-loss/target could in theory fire a second sell for the
same symbol+reason after the cooldown expires.

**Second caveat (live config)**: the mechanism only covers requests that send an `Idempotency-Key`. Keyless requests bypass it entirely unless `idempotency.require_key` is on (app.py:643-651), and the live DB has `idempotency.require_key=0`. The frontend sends keys from index.html:12363/12401/13744/13799/15039 (per the verifier; the per-endpoint mapping of those lines was not individually confirmed), but `/api/fno/auto-trade/run` (index.html:13449) sends none.

---

### `fno_backtester.py` (1,935 lines) — swing backtester + XGBoost live-signal engine
| Field | Detail |
|---|---|
| What/Why | Two roles in one file: (1) an on-demand swing backtester (`run_fno_backtest`, `run_multi_backtest`) that scans 5-min candles for entry, simulates a multi-day option-premium trade with SL/TP/trailing, and returns a chart+result dict for the dashboard; (2) `get_xgb_signal()`, the actual **live** signal source `fno_trader.analyze_fno_opportunity()` calls first every cycle (≈ every 15s). |
| Data source | `_fetch_candles_from_db()` (fno_backtester.py:142-190) → `db_manager.CandleDatabase.get_fyers_candles_as_5min(symbol, days, as_of)`, reading the `fyers_candles` table (~60M rows/32 partitions). |
| **Standard-2 finding (bound every read that can grow)** | `run_fno_backtest`/`run_multi_backtest` call `_fetch_candles_from_db(instrument_key)` with **no `days` argument** → `days=None` → per `get_fyers_candles_as_5min`'s own docstring (db_manager.py:985-988): "None = all available history... unbounded reads resample a symbol's entire multi-year 1-minute history (measured ~5s / ~770MB peak for a liquid name)." Every manual backtest run therefore does a full-history unbounded read. By contrast, `get_xgb_signal()` (the ≈15s hot path) correctly bounds to `FNO_SIGNAL_DAYS=30` (env-configurable, fno_backtester.py:139, 1836), and `_generate_xgb_training_data()` correctly bounds to `FNO_TRAIN_DAYS=180` (line 136, 794) — with an explicit comment citing a prior incident: "Unbounded, this walked ~94k candles per instrument across 69 instruments... and never finished." The backtest entry points were missed by that same fix (the two call sites are fno_backtester.py:1471, 1724). ALSO unbounded: `get_available_backtest_dates` (fno_backtester.py:1683, behind `GET /api/fno/backtest/dates/<instrument>`) — a third unbounded `fyers_candles` read. |
| XGBoost model lifecycle | `_get_xgb_models()` (fno_backtester.py:823-964): in-memory cache → load from `models/xgb_backtester.joblib` (validates `n_features` matches current `FEATURE_NAMES`) → else trains fresh (30-40 min, `n_estimators=150, max_depth=3`, on all `BACKTEST_INSTRUMENTS`). Saved atomically: temp file + `os.replace()` (correct pattern; explicit comment cites CLAUDE.md operational rule 4 and a real incident — training killed 16 min in on 2026-08-25 previously left a truncated/corrupt file that still loaded and produced silent garbage signals). **Historical bug, now fixed and commented**: the daily retrain task (`scheduler.py:324-440`, `_task_retrain_xgb_daily`, every 86400s) used to set `fno_backtester._xgb_models` as an in-memory global only — "every daily retrain since April trained for ~30 minutes and then discarded its work on exit" because the disk save happened separately and the timestamp field was stamped *after* the dump, so a fresh process loaded `trained_at=None`, `.strftime()` on it raised `AttributeError`, and every subsequent backtest silently re-triggered a full 30-40 min retrain instead of loading the cached model. Both the ordering bug and the `.get(key, default)` vs `.get(key) or default` bug (None being a valid-but-wrong stored value) are now fixed with inline comments documenting exactly why. |
| `get_xgb_signal()` thresholds | confidence>0.65→strong, >0.50→moderate, >0.40→weak, else NEUTRAL/"WAIT" (fno_backtester.py:1907-1916). Feeds `analyze_fno_opportunity`'s sentiment-boost gate (`confidence>0.55`, fno_trader.py:1196). |
| Storage of backtest results | **None persisted** — `run_fno_backtest`/`run_multi_backtest` compute and return a dict directly to the Flask response; no DB table or cache write. Re-running is the only way to see a result again (and will not reproduce identically since `run_fno_backtest` with no `target_date` picks a scan-start at the midpoint of currently-available data, which shifts as new candles accumulate). |
| Trigger | 100% on-demand via `app.py` endpoints — NOT scheduled: `POST /api/fno/backtest/run` (app.py:3770 → `run_fno_backtest`), `GET /api/fno/backtest/dates/<instrument>` (app.py:3820 → `get_available_backtest_dates`), `POST /api/fno/backtest/multi` (app.py:3830 → `run_multi_backtest`), `GET /api/fno/backtest/instruments` (app.py:3845). Only the XGBoost model *retraining* is scheduled (daily). |
| Status | ACTIVE (XGB signal path, daily retrain); backtester endpoints ACTIVE but on-demand/manual only |

### `options_strategies.py` (576 lines) — Black-Scholes / Greeks / strategy payoff calculator
| Field | Detail |
|---|---|
| What/Why | Pure-function analytics library: Black-Scholes call/put pricing (`bs_call_price`/`bs_put_price`), full Greeks (`greeks()`), Newton-Raphson implied volatility (`implied_volatility()`, max 100 iterations, tol 1e-6, sigma clamped [0.001, 5.0]), IV rank, and 7 strategy builders (bull call spread, bear put spread, long straddle, long strangle, iron condor, iron butterfly, covered call) each returning legs + max profit/loss + breakevens + a 100-point payoff curve. `analyze_option_chain()` enriches a raw chain with per-strike IV/Greeks/moneyness + PCR + max pain (`_calculate_max_pain`, O(n²) brute force over strikes). |
| State / side effects | **None** — no DB read/write, no order placement, no external API calls. Purely computational; safe by construction (cannot move money). |
| Callers | `app.py`: `GET /api/options/strategies` (7254→`get_strategy_list`), `POST /api/options/greeks` (7261→`full_analysis`), `POST /api/options/iv` (7280→`implied_volatility`+`iv_rank`), `POST /api/options/strategy/build` (7302→`build_strategy`). All 4 exist and import correctly (verified: functions referenced all exist in options_strategies.py). |
| **Finding** | `git grep` of `index.html` for `/api/options/` finds **zero** frontend call sites — these 4 endpoints are fully implemented and reachable but **not surfaced anywhere in the dashboard UI**. Backend-complete, orphaned from the UI (not dead code, just unused by the app today — reachable only via direct HTTP call). |
| Status | ACTIVE (backend) / UNUSED (no frontend integration) |

### Intraday/MIS module — location and architecture
There is **no `intraday_trader.py` or similar module**. "Intraday trading" in this codebase is:
1. A DB table `TradeJournalEntry` (db_manager.py:309) reused for MIS paper trades (`is_paper=True`, no dedicated intraday table).
2. Three Flask endpoints in `app.py` (3406-3646) — all three broken, see Finding #4.
3. One working read endpoint, `GET /api/intraday/trades` (app.py:3653-3701) — queries `TradeJournalEntry` for today's `is_paper=True` rows directly from DB (not cache); this one has no `fno_trader` dependency and works.
4. Frontend module in `index.html` (~12005 onward, "INTRADAY TRADING MODULE (MIS - 4x Leverage)") that reuses `/api/fno/*` endpoints for capital/positions/rules display, and the three broken `/api/intraday/*` endpoints for actual trade entry/exit.
5. No scheduler task exists for intraday MIS specifically — it is 100% manual/on-demand, and (per Finding #4) currently non-functional even manually.
6. Live/real intraday order placement: **not implemented** — frontend has literal `// TODO: Call real trade endpoint` stubs for entry and close in real mode.

---

### Cross-cutting facts (for the maps)

**External services / endpoints**
- Groww API (`growwapi.GrowwAPI`, via `fno_trader._get_groww()`): `get_expiries`, `get_option_chain`, `get_historical_candle_data` (V1, CASH segment for F&O underlyings), `get_quote`, `place_order` (FNO/COMMODITY segment, product NRML), `get_positions_for_user`, `get_available_margin_details`, `get_ltp`.
- yfinance: MCX commodity historical fallback (`_fetch_historical_candles`), international indices (`_fetch_intl_indices`, `ThreadPoolExecutor(max_workers=4)`, correctly parallel).
- `news_sentiment` module (Google News RSS-derived): news sentiment + X/social sentiment signals feeding the F&O heuristic.
- `commodity_tracker.get_geopolitical_context()`: geopolitical risk signal for commodities/indices.

**Config_settings keys — LAST VERIFIED 2026-09-27 (live DB values via read-only SELECT)**
| Key | Live value | Meaning |
|---|---|---|
| `fno_auto_trade_enabled` | **`false`** | THE real F&O kill switch (scheduler.py:648). F&O auto-trading is currently OFF. |
| `cash_auto_trade_enabled` | `true` | Separate cash-equity auto-trade switch (unrelated engine, `bot.auto_trade`). |
| `paper_trading` | `true` | Global paper/live gate (`bot.is_paper_mode()`); only `{false,0,no,off}` mean LIVE, everything else (including "true") means PAPER — deliberately asymmetric fail-safe design (bot.py:1276-1305). |
| `fno.capital` | `10000` | Description: "F&O paper trading virtual capital" — confirms paper-mode intent. |
| `fno.used_capital` | `0` | No capital currently marked deployed. |
| `fno.brokerage_per_order` | `20.0` | ₹ per order leg |
| `fno.brokerage_pct_cap` | `0.05` | % cap on brokerage |
| `fno.stt.option_sell_pct` / `fno.stt.futures_sell_pct` | `0.0625` / `0.0125` | STT rates |
| `fno.exchange.nse_pct` / `.bse_pct` / `.mcx_pct` | `0.0495` / `0.0325` / `0.0260` | Exchange txn charges |
| `fno.gst_pct` | `18.0` | GST on brokerage+exchange+SEBI |
| `fno.sebi_pct` | `0.0001` | SEBI turnover fee |
| `fno.stamp_duty_pct` | `0.003` | Stamp duty (buy side) |
| `fno.lot.NIFTY/BANKNIFTY/FINNIFTY/SENSEX/MIDCPNIFTY/HDFCBANK` | seeded JSON lot configs | Overrides `_FALLBACK_FNO_LOT_SIZES` at import time only (process restart needed to pick up changes) |
| `mcx.lot.CRUDEOILM/GOLDM/NATGASMINI/NATURALGAS/SILVERM` | seeded JSON lot configs | Read via `auto_metadata.get_fno_lot_config` (prefixes `fno.lot.` then `mcx.lot.`, auto_metadata.py:520-531); they override the hardcoded `_FALLBACK_MCX_CONTRACTS` (fno_trader.py:69-75) at import (process restart needed to pick up changes). |
| `idempotency.require_key` | `0` | Keyless requests bypass the `@idempotent` decorator (app.py:643-651) — see Finding #5. |
Runtime-only (NOT in config_settings, in-memory dict reset on every restart): `_AUTO_TRADE_CONFIG` (fno_trader.py:2159-2174) — `min_confidence=0.20`, `min_strength="moderate"`, `max_positions=2`, `stop_loss_pct=50`, `target_pct=80`, `trailing_sl_pct=30`, `preferred_instruments=[NIFTY,BANKNIFTY,FINNIFTY]`, `market_hours_only=True`, NSE hours 9:20-15:15. Mutable via `POST /api/fno/auto-trade/config` but changes do not survive a restart.

**Every timed/triggered execution (WHEN → WHAT)**
- Registered 5s (`scheduler.py:1329`, initial_delay 2s), effective ≈ every 15s (the scheduler loop sleeps 15s between dispatch passes, scheduler.py:1291): `_task_fno_auto_trade` → gated by `fno_auto_trade_enabled` (currently **false**, so this is a no-op right now) → `fno_trader.auto_trade_fno()` (market-hours check → capital sync → exit check → entry scan → buy).
- Every 600s (10 min): `_task_fno_capital_sync` → `fno_trader.sync_capital_from_groww()` (no-ops in paper mode beyond seeding a default).
- Every 900s (15 min): `_task_global_indices` → `fno_trader.fetch_global_indices()`.
- Daily (86400s): `_task_retrain_xgb_daily` → retrains + atomically saves `models/xgb_backtester.joblib`.
- On-demand only (no schedule): F&O backtester endpoints, options-strategy endpoints, all `/api/intraday/*` endpoints, `/api/fno/buy`/`/sell`, `/api/fno/auto-trade/run` (manual trigger of the same pipeline as the scheduler task, bypasses `fno_auto_trade_enabled`).

**Dead / declared-but-unused config & flags**
- `_AUTO_TRADE_CONFIG["enabled"]` (fno_trader.py:2160) — never read anywhere; superseded by `fno_auto_trade_enabled` in scheduler.py (self-documented in scheduler.py:640-647).
- `_AUTO_TRADE_CONFIG["avoid_expiry_day"]` (line 2167) — never checked in `auto_trade_fno()` or anywhere else; the `/api/risk-parameters` panel (app.py:2184) presents it to the user as an active behaviour ("Skip new entries on expiry day") when it is not enforced.
- `_AUTO_TRADE_CONFIG["mcx_close_hour"/"mcx_close_min"]` (line 2173) — never read; `_is_market_open()` only implements NSE hours, no MCX-hours branch exists at all.
- `options_strategies.py` — fully wired backend, zero frontend callers.

**Fail-closed vs fail-open inventory**
- Fail-closed (correct): `_count_open_positions()` → `None` on error, not `0` (fno_trader.py:2198). `is_paper_mode()` → assumes PAPER on config-read failure (bot.py:1276). `place_fno_buy/sell` paper-mode-check failure → refuses the order rather than falling through to live. `_paper_flag_means_live` → only exact `{false,0,no,off}` select live; anything else (including garbage/typos) is PAPER.
- Fail-open (risk): `_check_position_exits()` is skipped whenever `available_capital < 50` (Finding #2) — the one check that should never depend on available capital. Each of the 7 heuristic signal sources in `_analyze_fno_opportunity_heuristic` fails open per-source (a failing source contributes 0 weight rather than aborting the whole analysis) — acceptable for a scoring blend, not a safety gate. Capital-ledger release uses sell-time LTP not entry cost — drifts the ledger's accuracy over time in either direction (Finding #3). The F&O trailing-stop exit can never fire because its peak price is never persisted (see the exit table above).

**Open unknowns**
- Whether `fno_auto_trade_enabled=false` was a deliberate operator decision or a leftover from testing — no changelog/description beyond "Master switch for F&O auto-trading" in config_settings.
- RESOLVED: the F&O paper-trade refusal (Finding #1) is DELIBERATE and documented in `bot._paper_trade`'s docstring (bot.py:1476-1495, which explicitly names `place_fno_buy`/`place_fno_sell`), and `logger.exception` fires on every attempt; it is a known consequence of the CASH-only hardening with no replacement F&O paper store.
- Whether `models/xgb_backtester.joblib` on disk currently has a valid (non-`None`) `trained_at` and matches the live `FEATURE_NAMES` count — not checked (would require reading a binary artifact; out of scope for a read-only doc pass beyond code review).
## ML Models, Training, Inference & Backtesting

Scope: CASH-side ML only — two independent models predicting the same
BUY/HOLD/SELL vocabulary for cash-equity symbols: `PricePredictor`
(sklearn GradientBoostingClassifier, `predictor.py`) and `XGBPricePredictor`
(XGBoost, `xgb_predictor.py`, subclasses `PricePredictor` and reuses its
`build_features`/`create_labels`/`train`/`predict` verbatim — only the
estimator differs). F&O's own XGBoost model (`fno_backtester.py`,
`models/xgb_backtester.joblib`, `_task_retrain_xgb_daily` in scheduler.py) is
out of scope, noted only where it shares infrastructure (scheduler stagger
group, `candle_training_metadata` table).

**LIVE STATE (LAST VERIFIED: 2026-09-27, DB `config_settings`):**
`model.gbc_cash_enabled = false`, `model.xgb_cash_enabled = true`,
`paper_trading = true`, `cash_auto_trade_enabled = true`,
`paper.min_confidence = 0.50` — i.e. right now **cash auto-trading is live
(paper mode), and cash XGBoost is the only model allowed to place trades;
GradientBoosting is disabled** — the reverse of both models' compiled-in
defaults (GBC defaults to `True`, XGB gated off by `XGB_LIVE_TRADING` env
default `false` — bot.py:2094-2095, 601). This is a DB override, not a code
change — flip-able from Settings, takes effect on the next scheduler dispatch pass (<=15s) after the 30s `get_config` memo expires (bot.py:2087-2105; the scheduler loop sleeps 15s between passes, scheduler.py:1291).
**Flag history (LAST VERIFIED 2026-09-28):** `model.gbc_cash_enabled` and `model.xgb_cash_enabled` carry the identical `updated_at` **2026-08-27 10:04:22.018836** — both were flipped in ONE settings save (one transaction), i.e. a single deliberate settings write, not two independent toggles.

---

### `PricePredictor` — model (GradientBoosting, cash)
| Field | Detail |
|---|---|
| Where | `predictor.py:362-530` |
| Algorithm / library | `sklearn.ensemble.GradientBoostingClassifier` (`predictor.py:8,364-371`): `n_estimators=200, max_depth=4, learning_rate=0.05, min_samples_split=10, min_samples_leaf=5, random_state=42` |
| Version (installed, venv) | MEASURED: scikit-learn 1.8.0, numpy 2.4.4, pandas 2.3.3, joblib 1.5.3 (`.venv/bin/python3 -c "import sklearn..."`, this session). `requirements.txt:5-7` lists `numpy`, `pandas`, `scikit-learn` with **no version pins at all**. |
| Inputs | OHLCV DataFrame (`open,high,low,close,volume[,datetime]`) from `bot.fetch_historical` |
| Features | `build_features()` (`predictor.py:189-331`), full list (~46 cols): `sma_5/10/20/50_ratio`, `ema_9/21_ratio`, `rsi_14`, `macd`, `macd_signal`, `macd_histogram`, `bb_position`, `bb_width`, `atr_14`, `volume_ratio`, `return_1/3/5/10`, `hl_range`, `vwap_distance`, `ema_9_21_cross`, `ema_50_100_cross`, `stochastic_k`, `stochastic_d`, `stochastic_cross`, `candle_doji/hammer/inverted_hammer/bullish_engulfing/bearish_engulfing/bullish_piercing/bearish_piercing/morning_star/evening_star` (9), `fib_236/382/500/618/786_dist` (5), `support_dist`, `resistance_dist`, `sr_position`, `rsi_divergence`, `stoch_divergence`, `dow_volume_confirm`, `day_of_week`, `time_of_day`, `is_opening`, `is_closing`, `gap_open`, `prev_session_return`, `intraday_return`, `session_progress`. Scaled with `StandardScaler` (`predictor.py:372,396`). |
| Label definition | `create_labels()` (`predictor.py:334-359`): `close.shift(-5)/close - 1` (forward_periods=5 bars); cost-aware threshold = `1.5 × costs.min_profitable_move(median_price, qty=10, product="CNC")["min_move_pct"]`, floored at 0.5%. `1=BUY` (>threshold), `-1=SELL` (<-threshold), `0=HOLD`. |
| Bar width | **5-minute**, training AND inference alike — `bot.fetch_historical()` → `db.get_fyers_candles_as_5min()` (bot.py:253-294) for both `train_model()` and the default `get_prediction()` path. |
| Training data source/window | `bot.fetch_historical(symbol)` → DB `fyers_candles` via `CandleDatabase.get_fyers_candles_as_5min`, `days=PREDICTION_LOOKBACK_DAYS` (config) — see KNOWN ISSUE below: on every weekday it is pre-empted by a `days=1` (trailing-24h) branch, so weekday GBC training fails for every symbol; only weekend/holiday runs reach the full lookback. |
| Persistence | `bot._save_predictor` (bot.py:73-99): `joblib.dump` → `tempfile.mkstemp` in `models/gbc_cash/` → `os.replace()` — **atomic**, matches CLAUDE.md op-rule 4. Path: `models/gbc_cash/{symbol}.joblib`. Load: `bot._load_predictor` (bot.py:52-70) checks `models/gbc_cash/` then read-only fallback to legacy `models/` (nothing written there any more). |
| Confidence / thresholds | `predict()` returns `max(predict_proba)` (predictor.py:430-431) as confidence, 0-1 scale. Feeds `bot.get_prediction()`'s weighted consensus at `W_ML=0.40` (DB `prediction.weight.ml`, LAST VERIFIED 2026-09-27 = 0.40); final BUY/SELL needs `combined_score` beyond ±0.15 (bot.py:1121-1126). Live trade gate: `paper.min_confidence` (DB, LAST VERIFIED = 0.50) in paper mode, else `config.CONFIDENCE_THRESHOLD=0.65` (bot.py:2215-2223). |
| Consumers | `bot.get_prediction()` (Source 1, bot.py:944-1185) → `scan_watchlist()` → `auto_trade()` (gated by `model.gbc_cash_enabled`, DB=`false` LAST VERIFIED) → trade record tagged `model_source="GradientBoosting"`. Also: `backtester.py`'s `ml_walkforward` strategy (daily bars — see contradiction below); `cash_backtester.py`'s walk-forward `gbc` model. |
| Retrain schedule | `scheduler._task_ml_retrain` (scheduler.py:478-511), task `ml_retrain`, every 86400s (DB `scheduler_interval_ml_retrain=86400`, LAST VERIFIED), `initial_delay=150s` (scheduler.py:1378); `last_run` is in-memory, so it also reruns once after every app restart (after the initial delay). Iterates `bot.get_active_watchlist()` (67 DB symbols), calling `bot.train_model()` per symbol; progress via `training_progress` key `cash_gbc`. |
| Measured runtime | Code comment: **~25 min for 73 symbols** (scheduler.py:1357,1370) — stale symbol count (now 67), MEASURED-from-comment, not re-measured this session. |
| On-disk state | `models/gbc_cash/`: **59 `.joblib`** (LAST VERIFIED 2026-09-27 `ls -la`; `ls models/gbc_cash/*.joblib \| wc -l` = 59 re-checked 2026-09-28) vs 67 DB watchlist symbols (`SELECT count(*) FROM stocks` = 67; `is_active` = 67) → **9 active symbols with no GBC model**: BANKBARODA, INOXWIND, IOC, KANSAINER, PNB, SPICEJET, SUZLON, TATASTEEL, WIPRO. The 59 files = **58 active-symbol models + 1 orphan `TCS.joblib`** (TCS is not in `stocks` at all — 67 − 9 = 58). **10 of the 58 active files are STALE** — NOT refreshed by the 2026-09-27 retrain, and still served by `get_prediction()`: BERGEPAINT (Aug 31), BPCL / NTPC / ONGC / POWERGRID (Jun 13), DABUR / ITC (Aug 24), GEMAROMA (Apr 1), KOTAKBANK (Apr 24), TATAPOWER (Sep 21). The Sunday 2026-09-27 retrain's files carry Sep 27 09:23-09:31 mtimes (see KNOWN ISSUE). See "Why cheap stocks get no GBC model" below for the likely cause of both the 9 missing and the 10 stale. Working tree: pre-migration flat `models/*.joblib` show as git-deleted (54 `D` in `git status --short models/`) while `models/gbc_cash/` and `models/xgb_cash/` are untracked (`??`) — a plain `mv` reorg (not `git mv`); files exist ONLY in the new subdirectories now. |
| Status | **ACTIVE** (the task runs daily and after every app restart, but the retrain only succeeds on weekend/holiday runs — see KNOWN ISSUE; cheap stocks never succeed) but **DISABLED for live trading** (`model.gbc_cash_enabled=false`, LAST VERIFIED) — `auto_trade()`'s `gbc_on` gate (bot.py:2094,2108-2111) skips `scan_watchlist()` entirely while false. |

### KNOWN ISSUE — GBC "today-only" branch is really a trailing-24h window: every WEEKDAY GBC retrain fails for ALL symbols (VERIFIED FROM CODE + FILE MTIMES; corrected 2026-09-28)
`bot.fetch_historical()` (bot.py:247-306), used by `train_model()` (bot.py:383-395)
and by `get_prediction()`'s default path (bot.py:1002), **prioritizes a `days=1`
5-minute candle window over the full lookback window**. NOTE: `days=1` is NOT
"today" — `_resolve_window` (db_manager.py) computes `lower = now - timedelta(days=1)`,
a **rolling trailing-24h window**. After the close and before the next open, the
previous 24h still holds the whole last session (<=75 bars):
```
today_df = db.get_fyers_candles_as_5min(symbol, days=1)   # bot.py:282
if not today_df.empty and len(today_df) > 2:               # bot.py:284
    return today_df                                        # bot.py:287 — SKIPS the days= branch
```
`PricePredictor.train()` requires `len(df) >= 100` (predictor.py:381-382). One
session yields far fewer than 100 5-minute bars (≤75), so **whenever the
trailing 24h holds more than 2 bars, the fetch returns that window and
`train()` fails the 100-row minimum** — it never reaches the `days=` fallback
(bot.py:290) that would have enough rows. The full-lookback fallback runs
**only when the trailing 24h holds ≤2 bars — i.e. weekends and holidays
(~Sat 15:30 → Mon ~09:25) or days with no data**. Consequences:
- **Every weekday GBC retrain (and every add-time GBC training) fails for EVERY
  symbol**, not just newly added ones (≤75 rows < 100). GBC models are refreshed
  only on weekend/holiday runs. Retrain success depends on the day of the week,
  not on the data.
- The on-demand train in `get_prediction()` (bot.py:983-991) → `train_model()` →
  `fetch_historical()` and the watchlist-add training (app.py:4049-4137,
  section 10) hit the same branch on a trading day and return `"Not enough
  data"`; on a trading day only XGB gets a model at add time.
- Evidence (file mtimes, VERIFIED): the Sunday 2026-09-27 GBC retrain wrote files
  stamped Sep 27 09:23-09:31 (fallback path used, 30-day window). Re-checked Mon
  2026-09-28 22:06: GBC files are being rewritten after the app restart at
  22:02:03 (pid 36337) — also consistent, because Monday has NO candles in the
  DB (no `fyers_candles` rows for 2026-09-28; cause unverified: holiday vs
  collection outage), so the trailing 24h is empty and the 30-day fallback ran.
  If that gap was an outage, it is also why tonight's retrain "succeeded".
- This bug does **NOT** explain the 9 missing / 10 stale models — see next
  sub-section. (The earlier draft's "circumstantial" link was contradicted: the
  Sep 27 run was a Sunday and used the fallback path.)

#### Why cheap stocks get no GBC model (MEASURED; cause = INFERENCE, strong)
The 9 active symbols with no GBC file are exactly **SPICEJET** (0 `fyers_candles`
rows ever, no `master_ticker_table` row — a ghost symbol; no GBC or XGB model can
be built for it and `self_healing` cannot backfill it) plus the **8 lowest-priced
actives** (latest D close: SUZLON 40.8, INOXWIND 74.8, PNB 116.6, IOC 135.7,
WIPRO 164, KANSAINER 180.6, TATASTEEL 188, BANKBARODA 235.3). The 10 stale files
are the next-cheapest names. SUZLON and WIPRO have the same 85,579 5S rows in 30
days as RELIANCE (bounded `fyers_candles` query), so this is not a data-volume
problem.
Likely mechanism: `create_labels` (predictor.py:333-359) uses a qty-10 CNC cost
(fixed ≈₹56 round trip — ₹20×2 flat + ₹15.93 DP — plus ≈0.23% variable), ×1.5,
floored at 0.5%. On a cheap stock that fixed cost is a large % of a 10-share
notional, so the threshold reaches several % to >20% for a 25-min (5-bar
`forward_periods`) move. Hand-computed thresholds (`min_profitable_move` was NOT
executed): ≈29% SUZLON, 5.4% WIPRO, 3.9% BANKBARODA, 3.5% ITC, 3.5% VEDL, 2.9%
NTPC, 1.0% RELIANCE. Measured max |25-min move| over 30 days: SUZLON ₹44 3.06%,
WIPRO ₹167 3.62%, BANKBARODA ₹236 2.05%, ITC ₹265 3.31%, VEDL ₹268 4.00% (9 bars
>2%), NTPC ₹328 1.56%, RELIANCE ₹1259 1.54%. Any name whose max move is below
its threshold gets **all-HOLD labels**, and `GradientBoostingClassifier.fit`
rejects a single class (`PricePredictor.train`, predictor.py:376-406, has no
class weighting and no single-class guard — unlike XGB's balanced sample weights).
This matches the files: WIPRO/BANKBARODA/SUZLON missing, ITC (Aug 24) and NTPC
(Jun 13) stale, VEDL (max 4.00% > 3.5%) and RELIANCE fresh. **GBC is
structurally unable to model cheap stocks** while the qty-10 cost threshold is
fixed; the 10 stale models (some from June) are still served for predictions,
although `model.gbc_cash_enabled=false` currently limits the impact.

---

### `XGBPricePredictor` — model (XGBoost, cash)
| Field | Detail |
|---|---|
| Where | `xgb_predictor.py:105-128`, subclasses `predictor.PricePredictor` |
| Algorithm / library | `xgboost.XGBClassifier` wrapped by `_XGBLabelAdapter` (xgb_predictor.py:43-102) to translate sklearn's `-1/0/1` labels to XGBoost's required `0..n-1` and back. Params (xgb_predictor.py:117-128): `n_estimators=200, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, random_state=42, n_jobs=2, eval_metric="mlogloss", tree_method="hist"` — depth/lr/trees deliberately mirrored from GBC so the comparison isolates the algorithm. **Balanced sample weights at fit time** (`_XGBLabelAdapter.fit`, xgb_predictor.py:57-83): inverse-frequency class weights, because cost-aware labels are measured (comment) at 0.18% minority on 1-min bars vs 1.41% on 5-min bars — unweighted XGBoost would just predict HOLD always (~0.986 "accuracy", useless). Labels/threshold themselves are untouched. |
| Version (installed) | MEASURED this session: xgboost 3.4.1. **Not listed in `requirements.txt` at all** (`requirements.txt:1-46` has no xgboost; only imported at point of use, `xgb_predictor.py:53`; `start-all.sh:237` only runs `pip install -r requirements.txt`) — an undeclared dependency. It is also imported by `fno_backtester.py` and `scheduler.py` (the F&O model), so the F&O path depends on it too. Likewise `beautifulsoup4` (`bs4` — imported by `tijori_collector`, `auto_metadata`, `cost_scraper`, `costs`) is **undeclared** in `requirements.txt`. Installed versions (MEASURED via `importlib.metadata`): sklearn 1.8.0, numpy 2.4.4, pandas 2.3.3, joblib 1.5.3, xgboost 3.4.1; `requirements.txt:5-7` unpinned. |
| Inputs / Features / Labels | IDENTICAL to `PricePredictor` — same `build_features()`/`create_labels()` (predictor.py), inherited `train()`/`predict()` unchanged (xgb_predictor.py:1-25 docstring). |
| Bar width | **5-minute for training** (resampled from native 1-minute FYERS bars); **5-minute for inference too, but via a different reader** — see split below. Both are bit-identical wherever they overlap (comment cites a 92,345-bar RELIANCE verification, bot.py:418-420). |
| Training data source/window | `bot.fetch_5min_for_training()` (bot.py:444-476): `db.get_fyers_1min(symbol, days=XGB_TRAIN_DAYS)` resampled 1min→5min via `.resample("5min").agg({open:first,high:max,low:min,close:last,volume:sum})`. `XGB_TRAIN_DAYS = int(os.getenv("XGB_TRAIN_DAYS","0")) or None` (bot.py:437) → **env unset = FULL history** (~843k 1-min rows/symbol from 2017-07-03 per comment, bot.py:434-436), NOT the `days=` lookback GBC uses. |
| Inference data source | `bot.fetch_5min_for_inference()` (bot.py:479-491): `db.get_fyers_candles_as_5min(symbol, days=XGB_PREDICT_DAYS)` — unions FYERS `'5S'` and `'1'` tiers so the newest session is present (the `'1'` tier alone runs ~2 sessions behind per comment). `XGB_PREDICT_DAYS = int(os.getenv("XGB_PREDICT_DAYS","10"))` (bot.py:595). |
| Persistence | `xgb_predictor.save_model()` (xgb_predictor.py:148-176): `joblib.dump` → `tempfile.mkstemp` in `models/xgb_cash/` → `os.replace()` — **atomic**. Path: `models/xgb_cash/{symbol}.joblib`. Load: `xgb_predictor.load_model()` (xgb_predictor.py:135-145), no legacy fallback (this model never lived elsewhere). |
| Confidence / thresholds | Same `predict_proba`-max convention as GBC (inherited). Runs through the SAME `bot.get_prediction()` four-source blend (`get_prediction_xgb()`, bot.py:547-590) rather than returning raw model output — this was a deliberate fix (comment bot.py:561-568) so XGB isn't judged on technicals alone (40%) while GBC gets all four sources. |
| Consumers | `bot.get_prediction_xgb()` → `bot.scan_watchlist_xgb()` → `auto_trade()` (gated by `model.xgb_cash_enabled` OR module const `XGB_LIVE_TRADING` default False, bot.py:2095) → trade tagged `model_source="XGBoost"`. Also `backtester.py`'s `ml_walkforward_xgb` (daily bars) and `cash_backtester.py`'s `xgb` model (walk-forward on native 1-min). |
| Retrain schedule | `scheduler._task_xgb_cash_retrain` (scheduler.py:514-556), task `xgb_cash_retrain`, every 86400s (DB `scheduler_interval_xgb_cash_retrain=86400`, LAST VERIFIED), `initial_delay=1800s` (30 min after start, scheduler.py:1379) — scheduled to start only after GBC's ~25min retrain finishes. Iterates `bot.get_active_watchlist()`, calls `bot.train_xgb_model()`; progress via `training_progress` key `cash_xgb`. |
| Measured runtime | Comment: **~10.3 min for 73 symbols** (~8.5s/symbol, full-history 5-min bars, ~168.8k bars/symbol) and **~1.4GB peak RSS per symbol** (bot.py:434-436, scheduler.py:1357,1371-1372) — MEASURED-from-comment. |
| On-disk state | `models/xgb_cash/`: **66 `.joblib`** (LAST VERIFIED `ls -la`) vs 67 watchlist symbols → only **SPICEJET** missing (ghost symbol: 0 `fyers_candles` rows ever). Far more complete than GBC (58 active-symbol files / 67, plus an orphan `TCS.joblib`) — XGB trains on full history with class-balanced sample weights, so it is neither exposed to the trailing-24h branch (XGB's own fetch path, `fetch_5min_for_training`, does NOT have the shortcut `fetch_historical` has) nor to the single-class label failure that blocks GBC on cheap stocks. |
| Status | **ACTIVE and the only cash model currently allowed to trade** (`model.xgb_cash_enabled=true`, `cash_auto_trade_enabled=true`, `paper_trading=true` — all LAST VERIFIED 2026-09-27). Documented default in code comments (bot.py:597-601) says XGB should be evaluation-only until a GBC-vs-XGB backtest exists — the current DB config has moved past that intent without GBC being re-enabled alongside it (see contradiction below). |

### CONTRADICTION — code comments describe XGB as "evaluation-only" but DB config has it live-trading alone
bot.py:597-601 states cash XGB trains and can be inspected but "auto_trade
ignores them until a GBC-vs-XGB backtest exists." LIVE DB state (LAST
VERIFIED 2026-09-27) is `model.xgb_cash_enabled=true` AND
`model.gbc_cash_enabled=false` — XGBoost is not being evaluated alongside GBC,
it has fully replaced it as the live trader, with no code evidence a
comparative backtest was the trigger (candle_training_metadata has no cash-model
rows at all — see below). UNKNOWN — NOT DETERMINABLE FROM CODE whether this
was a deliberate operator decision or a leftover Settings toggle.

---

### `retrain_all_models.py` — script (manual/legacy)
| Field | Detail |
|---|---|
| Where | `retrain_all_models.py:1-121` |
| What | CLI script (`if __name__=="__main__"`) calling `retrain_gradient_boosting()` (loops `config.WATCHLIST` — the **static 10-symbol seed list**, not the 67-symbol DB watchlist `bot.get_active_watchlist()` uses — calls `bot.train_model()` per symbol) then `retrain_xgboost()`, which despite its name **retrains the F&O XGBoost model** (`fno_backtester._generate_xgb_training_data`, sets `fno_backtester._xgb_models` in-memory only — no disk save here, unlike scheduler's `_task_retrain_xgb_daily` which does persist). |
| Callers | None found (`git grep` for `retrain_all_models` outside itself: no hits) — **not wired into scheduler.py**; manual/legacy, presumably superseded by `_task_ml_retrain` + `_task_xgb_cash_retrain` + `_task_retrain_xgb_daily`. |
| Status | LEGACY / manual-only. Its GBC path uses the stale 10-symbol `WATCHLIST`, its "XGBoost" path is F&O not cash, and its F&O retrain doesn't persist to disk — running it today would silently retrain only 10/67 cash symbols and leave the F&O model in memory-only state. |

### `retrain_xgb.py` — script (dead/legacy)
| Field | Detail |
|---|---|
| Where | `retrain_xgb.py:1-105` |
| What | CLI script training THREE F&O-data XGBoost models (`immediate`/`conservative`/`balanced`, thresholds 0.5/1.0/0.75 on `fno_backtester._generate_xgb_training_data()`'s continuous target) — unrelated to either cash model. Params: `max_depth=7, learning_rate=0.1, n_estimators=150, subsample=0.8, colsample_bytree=0.8`. |
| Persistence | `pickle.dump()` (NOT joblib, NOT atomic) to `/tmp/xgb_models/xgb_{label}_model.pkl` (retrain_xgb.py:85-96) — outside `models/` entirely, in a path nothing else reads (`git grep xgb_models` finds only this file's own path string). |
| Callers | None (`git grep retrain_xgb` outside itself: no hits) — not scheduled, not imported anywhere. |
| Status | **DEAD** — writes to `/tmp` (wiped on reboot), nothing loads from there, no scheduler/endpoint reference. Not atomic-save (violates CLAUDE.md op-rule 4) but moot since it's unreachable. |

---

### `training_progress.py` — module (cross-process progress tracking)
| Field | Detail |
|---|---|
| Where | `training_progress.py:1-178` |
| What / Why | Cross-process job progress for the Data Coverage panel's ETA, since training runs both inside the Flask scheduler thread and standalone scripts — an in-memory counter would be invisible to whichever process serves `/api/data-health`. |
| Storage | `training_progress.json` next to this file, `.lock` sidecar. Writes: `tempfile.mkstemp` + `fsync` + `os.replace()` — atomic (training_progress.py:79-97). Read-modify-write (advance()) is additionally serialized with `fcntl.flock` (training_progress.py:34-64) — comment cites an observed counter-goes-backwards bug (13→11) from two concurrent trainers racing an unlocked increment. |
| API | `start(job, total, label)`, `advance(job, current=None, n=1)`, `finish(job)`, `snapshot()` (returns per-job `pct`, `eta_seconds` — None if nothing to project from, not fabricated — `done`, `state`). `STALE_AFTER_SECONDS=300`: a job silent >5min flips from `running` to `stale`. |
| Jobs used by cash ML | `cash_gbc` (`_task_ml_retrain`), `cash_xgb` (`_task_xgb_cash_retrain`); F&O uses `fno_xgb`. |
| Consumers | `/api/data-health` (app.py) — not traced further here (out of scope). |
| Status | ACTIVE. |

---

### `cash_backtester.run_cash_backtest()` — backtester (cash, single-trade replay)
| Field | Detail |
|---|---|
| Where | `cash_backtester.py:605-933`; endpoint `app.py:3785-3806` (`POST /api/cash/backtest/run`) |
| What it simulates | ONE decision on one historical session for one symbol: "what did the bot decide, and was it right?" — mirrors `fno_backtester.run_fno_backtest()`'s output contract (byte-identical key sets) plus `segment="cash"` and `signal_meta` (cash_backtester.py:26-40). Scans a session bar-by-bar for the first non-neutral combined signal, then simulates the resulting trade forward (SL/TP/trailing-stop/max-hold) with REAL cash cost model (`costs.calculate_costs`), not the F&O flat-premium formula. |
| Leakage safeguards (VERIFIED, `test_cash_backtest_leak.py`) | (1) **Walk-forward retrain**: `_train_walk_forward()` (cash_backtester.py:208-271) fits a FRESH `PricePredictor`/`XGBPricePredictor` on data strictly before `as_of` — the module docstring explicitly calls out that F&O's approach (one model trained on ALL history, including the date being graded) is "optimistically biased" and that grading nightly-retrained `models/gbc_cash/*.joblib` against a past date would leak months of price action. (2) Every slow source (`_load_slow_sources`: long-term trend, news, market context) is bounded by `as_of` (cash_backtester.py:278-341). (3) `_fidelity_notes()` (cash_backtester.py:129-173) surfaces what could NOT be reconstructed faithfully (news coverage gaps, pre-FYERS-migration market context) directly in the output rather than hiding it — CLAUDE.md standard #7 applied to a measurement. (4) Training cutoff is `session_open - 1 minute`, not `as_of` (15:30), so the opening bar of the graded session itself isn't leaked into training (cash_backtester.py:671-678). (5) `_load_slow_sources` for the session is anchored at session OPEN not at `as_of`/close — comment states this exact fix flipped one RELIANCE case from a +0.155 entry to no-entry (cash_backtester.py:703-710). Test file asserts all of this end-to-end (candle readers respect `as_of`, news replay sees fewer articles than live and doesn't poison the live cache, market-context replay never calls the live API, walk-forward model differs from the production artifact object, chart never extends past the ceiling month). |
| Outputs | Dict: `analysis` (4-source weighted consensus + `signal_meta`), `chart` (labels/prices/predicted path), `discrepancy` (predicted vs actual), `trade_simulation` (would_trade, entry/exit, P&L, charges), `fidelity` notes, `technicals`. |
| Where stored | Walk-forward MODEL artifacts cache to `models/backtest_cache/{symbol}_{gbc\|xgb}_{as_of:%Y%m%d}_{n_rows}.joblib` (cash_backtester.py:198-205) — **atomic** save (tempfile+`os.replace`, cash_backtester.py:257-269), explicitly kept OUT of `models/gbc_cash/`/`models/xgb_cash/` so a date-truncated backtest model can never overwrite the live trading artifact. Row-count is part of the cache key so a later backfill invalidates stale entries automatically. Result payload itself is NOT cached (recomputed every call) — no DB cache row, unlike `backtester.py` below. LAST VERIFIED on-disk: 17 files in `models/backtest_cache/` (RELIANCE, INFY, MARUTI, CIPLA, LT, NIFTY — a mix of symbols; the `as_of` dates encoded in the file names are 2026-05-13 and 2026-08-14 through 2026-08-21, `ls -la`). |
| Trigger | Manual only — `POST /api/cash/backtest/run` from the dashboard; ~60s per run (comment, app.py:3792) because it retrains walk-forward. No scheduler task. |
| Params | `CASH_TRAIN_DAYS=180` (env override), `CASH_BT_CAPITAL=50000`, `ENTRY_SCORE_THRESHOLD=0.15` (mirrors live), `MAX_HOLD_BARS=7×75=525` bars (env override), weights read live from `prediction.weight.*` and renormalized if they don't sum to 1. |
| Status | ACTIVE, manual/on-demand. |

### `backtester.run_backtest()` (`ml_walkforward` / `ml_walkforward_xgb` strategies) — backtester (general, multi-strategy)
| Field | Detail |
|---|---|
| Where | `backtester.py:1-742`; `ml_walkforward`/`ml_walkforward_xgb` at `backtester.py:237-296`; endpoints `/api/backtest/<symbol>` `app.py:5803` (`run_backtest`) and `/api/backtest/<symbol>/compare` `app.py:5825` (`compare_strategies`) |
| What it simulates | One of 8 strategies (6 pure-technical + 2 ML walk-forward) over a symbol's **DAILY** bars (falls back to weekly `stock_prices` if <100 daily rows exist, `backtester.py:129-138) — a config-selectable stop-loss/target simulation with the real Indian cost model, Sharpe/Sortino/CAGR/drawdown/win-rate/profit-factor metrics (`_metrics`, `backtester.py:450+`) and a buy-and-hold benchmark. |
| ML walk-forward mechanics | `_sig_ml()`/`_sig_ml_xgb()` (backtester.py:237-296): rolling `train_window=120` (days) / `test_window=20` / `confidence=0.6` gate — fit `PricePredictor` (or `XGBPricePredictor` via `predictor_factory`) fresh on each 120-bar window, predict the next 20, roll forward. No look-ahead within a window (train strictly precedes test window). |
| **CONTRADICTION vs live/cash_backtester bar width** | This module trains/predicts on **DAILY** bars end-to-end (`_load_candles` reads `fyers_candles` resolution='D' via `get_fyers_daily`, backtester.py:77-101), whereas the LIVE system and `cash_backtester.py` both operate on **5-minute** (GBC) or native-1-minute-resampled-5-minute (XGB) bars. `build_features()`'s rolling windows (sma_50, atr_14, session-based features like `time_of_day`/`gap_open`/`session_progress`) all assume intraday 5-min structure — many are degenerate or meaningless on daily bars (e.g. `session_progress` normalizes by 74 5-min candles/session; on daily bars every row has 1 "candle"). This means `ml_walkforward`/`ml_walkforward_xgb` results here do **not** represent what the live model actually does — a materially different, less-faithful backtest than `cash_backtester.py`'s same-bar-width walk-forward. No comment in the file acknowledges this gap. INFERENCE, but strongly supported by direct code comparison. |
| Outputs / storage | Result dict (`metrics`, `trades`, `equity_curve`, `benchmark`, `data_info`) cached via `db_manager.set_cached(f"backtest_{symbol}_{strategy}", result, cache_type="backtest")` (backtester.py:729-734) — a DB cache row, TTL 86400s (`get_cached_backtest`, backtester.py:737-742+) — distinct from `cash_backtester.py`'s filesystem model-cache. |
| Trigger | Manual only — `/api/backtest/<symbol>` and `/api/backtest/<symbol>/compare` (`run_backtest`/`compare_strategies`, app.py:5803,5825). No scheduler task. |
| Status | ACTIVE (reachable, presumably still used for the 6 pure-technical strategies), but its two ML strategies are methodologically questionable per the bar-width mismatch above. |

---

### Manual analysis / diagnostic scripts (compact)
| name | file | purpose | data source | status |
|---|---|---|---|---|
| `simulate_profit.py` | simulate_profit.py:1-193 | Top-level (no `main()`) CLI: fetches today's data + `bot.get_prediction()` for `WATCHLIST[:5]`, prints 3 "scenarios" (>80% conf, >50% conf, today's moves) | `bot.fetch_historical`/`bot.get_prediction` (live) | **BUGGY**: compares `confidence >= 80` / `>= 50` against `bot.get_prediction()`'s confidence, which is 0-1 scale (capped at 1.0, bot.py:1118) — these thresholds can never be met; "STRICT"/"MODERATE" scenarios are permanently empty. Manual-only, not imported elsewhere. |
| `threshold_analysis.py` | threshold_analysis.py:1-146 | Same live-prediction gather as above, sweeps thresholds `[0.01..0.80]` (correctly 0-1 scale) to suggest a confidence cutoff by same-day win rate | `bot.fetch_historical`/`bot.get_prediction` (live) | Correct scale; manual CLI only, `WATCHLIST[:5]` only (static 10-symbol list, first 5). |
| `confidence_analysis.py` | confidence_analysis.py:1-120 | Top-level script computing a **hand-rolled** trend+volatility "confidence" (does NOT call `PricePredictor`/`XGBPricePredictor` at all) over `db_manager.Candle` (`candles` table) | Legacy `candles` table | **DEAD**: `candles` table has **0 rows** (VERIFIED FROM DATABASE, `SELECT max(timestamp), count(*) FROM candles` → count=0, LAST VERIFIED 2026-09-27) — this is the pre-FYERS-migration Groww table; every symbol will report "Insufficient data" today. |
| `find_high_confidence_trades.py` | find_high_confidence_trades.py:1-130 | Scans `fno_backtester.get_backtest_instruments()` via `run_fno_backtest`, ranks by a win-rate/profit-factor "confidence" | F&O backtester | **Out of cash scope** — entirely F&O despite being in the read list; does not touch `predictor.py`/`xgb_predictor.py`. |
| `find_quick_trades.py` | find_quick_trades.py:1-123 | Same pattern as above, restricted to 10 liquid index/stock symbols | F&O backtester | **Out of cash scope** — F&O only. |
| `analyze_losses.py` | analyze_losses.py:1-118 | CLI: loads `paper_trades.json` directly, computes live P&L per open position, recommends CLOSE/HOLD/SCALE-OUT | `paper_trades.json` (file, not DB) + `paper_trader.get_live_price` | **BUGGY (money-relevant)**: lines 31-39 — `if not current_price: ...; else: pnl = ((entry-current_price)/entry)*100  # SELL`. The `else` branch (price WAS fetched) unconditionally applies the **SELL** P&L formula regardless of `trade['signal']` — there is no BUY branch at all (dead `pnl=` line after the `continue` at line 37 is unreachable). Since cash trading is long-only (BUY-only, per `cash_backtester.py` comment), this **inverts the sign of P&L for every real open position** — a profitable BUY shows as a loss and vice versa, and the printed "CLOSE NOW"/"HOLD/REVERSE" recommendations would be backwards. Standalone manual script, not imported/scheduled. |

### Tests
| name | file | verifies | execution note |
|---|---|---|---|
| `test_cash_backtest_leak.py` | test_cash_backtest_leak.py:1-137 | 6 groups of look-ahead-leak assertions on `cash_backtester.py` (candle readers respect `as_of`; news replay sees fewer articles than live and doesn't poison the live cache; market-context replay never calls the live API; long-term trend bounded by `as_of`; walk-forward model is a distinct object from the production `models/gbc_cash/{symbol}.joblib` artifact, and that artifact's mtime is AFTER the graded date — "proving the fix matters"; end-to-end chart never shows post-ceiling months) | Standalone script (not pytest), touches DB/news/market_context live reads — **not executed this session** (COMMON_RULES: no scripts with side effects); documented from source only. |
| `test_xgb_price_batching.py` | test_xgb_price_batching.py:1-249 | `fyers_market_data_provider` batch quote chunking (ceil(n/50), cap 50/chunk); `scan_watchlist_xgb()` prefetches ONE batch and forwards price to every worker (never falls back to per-symbol `fetch_live_price`, never runs the retired GBC scan); a batch that's missing/zero/negative/None-prices any symbol, or returns empty/None/raises, must ABORT (raise), never silently degrade; `get_prediction_xgb`/`get_prediction` forward a supplied `live_price` verbatim and only fetch when none is given | Fully mocked per its own docstring ("No network, no DB, no trading paths") — **not executed this session** (out of caution per COMMON_RULES read-only mandate); documented from source only. |

---

### Cross-cutting facts (for the maps)

**External services**: none directly from these modules — training/inference read FYERS candles already persisted in Postgres by other components (out of this section's scope); no direct API calls from `predictor.py`, `xgb_predictor.py`, or either backtester.

**Env vars** (name — where — default — sensitivity): `XGB_TRAIN_DAYS` (bot.py:437, default `0`→full history, non-sensitive), `XGB_PREDICT_DAYS` (bot.py:595, default `10`, non-sensitive), `XGB_LIVE_TRADING` (bot.py:601, default `false`, non-sensitive — superseded in practice by DB `model.xgb_cash_enabled`), `CASH_BT_MAX_HOLD_BARS` (cash_backtester.py:71, default `525`), `CASH_BT_TRAIN_DAYS` (cash_backtester.py:76, default `180`), `CASH_BT_CAPITAL` (cash_backtester.py:82, default `50000`), `CASH_BT_ENTRY_THRESHOLD` (cash_backtester.py:85, default `0.15`).

**config_settings keys** (key — where read — default — LAST VERIFIED 2026-09-27 live value): `model.gbc_cash_enabled` (bot.py:2094, default `true` → **live `false`**), `model.xgb_cash_enabled` (bot.py:2095, default = `XGB_LIVE_TRADING` env i.e. `false` → **live `true`**), `paper.cap.gradientboosting` / `paper.cap.xgboost` (bot.py:1351-1352, default `50000` each → live `50000`/`50000`), `prediction.weight.ml/trend/news/context` (bot.py:1107-1110, defaults `0.40/0.15/0.20/0.25` → live identical), `scheduler_interval_ml_retrain` / `scheduler_interval_xgb_cash_retrain` / `scheduler_interval_retrain_xgb_daily` (scheduler.py `_load_interval_overrides`, default `86400` each → live `86400` each, i.e. no override in effect), `paper.min_confidence` (bot.py:2218, default `0.50` → live `0.50`), `paper_trading` (default unclear elsewhere, live `true`), `cash_auto_trade_enabled` (scheduler.py:802, default `false` → live `true`).

**DB tables**: READ — `fyers_candles` (via `CandleDatabase.get_fyers_candles_as_5min`/`get_fyers_1min`/`get_fyers_daily`), `stocks` (67 rows, `get_active_watchlist`), `config_settings`. READ (legacy, dead) — `candles` (0 rows, LAST VERIFIED). WRITTEN — `candle_training_metadata` (via `log_xgb_training_event`, called ONLY from `scheduler._task_retrain_xgb_daily` — **F&O only**; 88 rows, all `event_type='training'`, `model_version='both'`, LAST VERIFIED 2026-09-27 — **cash GBC and cash XGB retrains write NO rows here**, a real gap: neither `_task_ml_retrain` nor `_task_xgb_cash_retrain` logs to this table, so there is no historical retrain-quality record for either cash model, only the current on-disk artifacts).

**Timed/triggered execution** (WHEN → WHAT): every 86400s (`initial_delay=150s` after scheduler start) → `_task_ml_retrain` (retrain all 67 GBC cash models); every 86400s (`initial_delay=1800s`) → `_task_xgb_cash_retrain` (retrain all 67 XGB cash models); every ~15s scheduler dispatch pass (the `cash_auto_trade` task's 5s interval is bounded by the 15s loop sleep, scheduler.py:1291; details in the scheduler section) → `auto_trade()` reads `model.gbc_cash_enabled`/`model.xgb_cash_enabled` live and runs `scan_watchlist()`/`scan_watchlist_xgb()` accordingly; on-demand via dashboard → `POST /api/cash/backtest/run` (`cash_backtester.run_cash_backtest`, ~60s) and `run_backtest`/`compare_strategies` (backtester.py, `ml_walkforward*` strategies).

**Rate limits / cost drivers**: no external API calls in this section's modules; cost driver is compute — GBC retrain ~25min/67 symbols (and it reruns after every app restart — see Missed items), XGB cash retrain ~10.3min/67 symbols (~8.5s + ~1.4GB peak RSS per symbol, full-history 5-min resample), `cash_backtester` walk-forward fit ~55s of a ~60-64s single backtest (cached after first run per symbol/date/model).

**Data flows**: `fyers_candles` (1-min FYERS ticks) → [GBC: `get_fyers_candles_as_5min` `days=`lookback / trailing-24h (`days=1`) window tried first — weekday runs stop there and fail the 100-row minimum] → `build_features`+`create_labels` → `StandardScaler`+`GradientBoostingClassifier` → `models/gbc_cash/{symbol}.joblib` → `get_prediction()` 40%-weight Source 1 → `auto_trade()` (currently gated OFF) → paper/live trade record. `fyers_candles` (1-min, full history) → [XGB: resample 5min] → same features/labels → `_XGBLabelAdapter`(class-weighted)+`XGBClassifier` → `models/xgb_cash/{symbol}.joblib` → `get_prediction_xgb()`→`get_prediction()` same 40%-weight blend → `auto_trade()` (currently the ONLY active cash model) → paper/live trade record. `cash_backtester`: `fyers_candles` (bounded by `as_of`) → walk-forward `PricePredictor`/`XGBPricePredictor` (cached in `models/backtest_cache/`) → 4-source consensus replay → simulated trade with real cost model → JSON to dashboard (not persisted). `backtester.py`: `fyers_candles` resolution='D' (or `stock_prices` weekly fallback) → rolling walk-forward `PricePredictor`/`XGBPricePredictor` → simulated trade → cached in DB `analysis_cache`-style table via `set_cached(..., cache_type="backtest")`.

**Failure modes**: GBC/XGB save — fail CLOSED in the safe direction (atomic temp+replace means a crash mid-save just leaves the OLD model in place, never a corrupt one) — both `bot._save_predictor` and `xgb_predictor.save_model` follow CLAUDE.md op-rule 4 correctly. Model-enable config read failure in `auto_trade()` — fails CLOSED (skips the whole scan rather than guessing, bot.py:2096-2105). `get_prediction()`'s news/market-context/cost sub-blocks each fail to a neutral default inside a `try/except` (bot.py:1047-1051,1058-1062,1100-1101) rather than aborting the whole prediction — fails OPEN for those three sources specifically (a broken news fetch silently zeroes 20% of the blend rather than surfacing the outage), unlike the model-enable gate.

**Dead / legacy / retired code**: `retrain_xgb.py` (writes to `/tmp/xgb_models/*.pkl`, non-atomic, nothing reads it — DEAD); `retrain_all_models.py` (not scheduler-wired, uses stale 10-symbol `WATCHLIST` for its GBC path — LEGACY/manual); `confidence_analysis.py` (queries the now-empty legacy `candles` table — DEAD); legacy flat `models/*.joblib` GBC location (`bot._LEGACY_MODELS_DIR`) — read-only fallback, nothing writes there since the `gbc_cash`/`xgb_cash` subdirectory migration, and the working tree shows all 54 old files gone from that path already.

**Contradictions found**: (1) bot.py comments describe cash XGBoost as "evaluation-only… until a GBC-vs-XGB backtest exists," but live DB config has XGB as the SOLE active cash model with GBC fully disabled, and there is no metadata-table evidence a comparative backtest ran. (2) `backtester.py`'s `ml_walkforward`/`ml_walkforward_xgb` strategies run the SAME feature/label code on DAILY bars, while live trading and `cash_backtester.py` both use 5-minute (or 1-min-resampled) bars — many features (`session_progress`, `time_of_day`, `is_opening/closing`, `gap_open`) are built for intraday structure and are degenerate on daily bars, so this backtester's ML results do not represent live behavior, unlike `cash_backtester.py`'s matched-bar-width walk-forward. (3) `simulate_profit.py` compares a 0-1 confidence value against 80/50 thresholds meant for a 0-100 scale — permanently dead code paths in that script. (4) `analyze_losses.py` computes every open position's P&L with the SELL formula regardless of actual trade side, inverting the sign for the long-only cash trades it's meant to analyze.

**Open unknowns**: whether the `model.xgb_cash_enabled=true` / `model.gbc_cash_enabled=false` DB state was a deliberate operator decision following some (unlogged) comparison, or a leftover/accidental Settings change — UNKNOWN, NOT DETERMINABLE FROM CODE OR DB (candle_training_metadata has no cash-model rows to check against). What IS known: both flags share one `updated_at` (2026-08-27 10:04:22.018836), so they were flipped in a single settings save — a single deliberate write, not two independent toggles. **Resolved (was open):** the 9 missing GBC models are NOT explained by the trailing-24h/"today-only" bug — SPICEJET has no candle data at all and the other 8 are the lowest-priced actives (qty-10 cost threshold > their max 25-min move → single-class labels → `fit` fails; cause = strong INFERENCE, see "Why cheap stocks get no GBC model"). The 1 missing XGB model (SPICEJET) is explained by the same no-candles ghost symbol. No per-symbol training-failure log is retained, so the labelling mechanism itself is inferred, not logged.

**Missed items surfaced by verification (2026-09-28):** (a) `SPICEJET` is a ghost symbol — active in `stocks`, 0 `fyers_candles` rows ever, no `master_ticker_table` row; no model can be built and `self_healing.check_missing_symbols` can never heal it. (b) Weekday GBC retrains fail for all symbols; retrain success depends on the weekday, not the data. (c) Restarts re-run every scheduler task after its `initial_delay` (`last_run` is in-memory, scheduler.py:60-71,1279-1283), including this section's ~25-min GBC retrain — a restart at 2026-09-28 22:02 immediately re-ran the GBC retrain. (d) Undeclared dependencies: `xgboost` (cash + F&O) and `beautifulsoup4`.

## Scheduler, Background Workers, Self-Healing & Notifications

Covers `scheduler.py` (master task-pool scheduler, `_register`'d tasks with live config overrides),
`self_healing.py` (periodic health checks/repairs), `change_feed.py` (file/config-change SSE feed),
`telegram_commander.py` + `telegram_alerts.py` (bot polling loop, commands/callbacks, outbound alerts),
`daily_summary.py`, `cost_notifications.py`, `sanity_check.py`, and every `threading.Thread(`/
`start_in_background` background worker in the repo (22 confirmed, matching the inventory). All findings
below are VERIFIED FROM CODE unless marked otherwise. LAST VERIFIED: 2026-09-27 (independently re-verified and corrected through 2026-09-28 22:07 IST).

### 1. Scheduler engine mechanics — `scheduler.py`

| Field | Detail |
|---|---|
| Where | `scheduler.py:1253` (`_scheduler_loop`), `:1294` (`start_scheduler`), `:1236` (`_run_task_safe`) |
| Thread pool | `ThreadPoolExecutor(max_workers=MAX_WORKERS)`, `MAX_WORKERS = 4` (`scheduler.py:34`), name prefix `sched` |
| Dispatch loop | `_scheduler_loop()`: `time.sleep(5)` warm-up, then every 15s (`time.sleep(15)`, `scheduler.py:1291`) iterates all `_tasks`, resolves each task's live interval, submits due tasks to the pool. Per-pass, not per-task, it does ONE query for all `scheduler_interval_*` overrides (`_load_interval_overrides`, `:1202`) — avoids ~83k config queries/day (CLAUDE.md std #1 in the code's own words). **Effective cadence floor = ~15s:** the loop only submits a task when `now - last_run >= interval` and only checks once per pass, so a task registered at 5s can fire at most once per ~15s pass. Every "5s" task (`record_pnl`, `cash_auto_trade`, `fno_auto_trade`, and `auto_close_trades` had it not been overridden) therefore runs at ~15s effective cadence. Minor side-effect: a task with an 1800s period and a 30-minute daily window (`telegram_summary`, `paper_eod_summary`) can occasionally miss its window, because each period lands on a 15s pass boundary slightly after 1800s. |
| Restarts re-run everything | `_register` sets `last_run=0` and the loop re-zeroes it once `initial_delay` elapses (`scheduler.py:60-71,1279-1283`); intervals are in-process only. So **every task — including `cost_scraper`, the 3 retrains, `market_intelligence`, `auto_metadata` — runs once after EVERY app restart** (after its `initial_delay`), and thereafter per interval only while the process survives that long. The 45-day, weekly and daily intervals only apply to a process that stays up that long. Frequent restarts multiply scraper traffic and retrain load (a restart at 2026-09-28 22:02 immediately re-ran the ~25-min GBC retrain). |
| Per-task lock | `_task_locks[name] = threading.Lock()` (`:71`); `_run_task_safe` does `lock.acquire(blocking=False)` — if already running, the tick is skipped (logged at debug), never queued |
| last_run stamping | **Two places, different semantics**: `_scheduler_loop` stamps `task["last_run"] = now` at submit time (`:1289`, "even if lock skips it") so a long-running task doesn't get re-submitted every 15s tick; `_run_task_safe` ALSO stamps `task["last_run"] = time.time()` after `task["fn"]()` completes (`:1245`). Net effect: last_run is set optimistically at dispatch, then overwritten with the real completion time once the task returns — VERIFIED by reading both lines; a skipped (locked) task's last_run was already advanced at submit, so it is not retried before the next full interval. |
| Telegram pause | Top of loop: `from telegram_commander import is_scheduler_paused; if is_scheduler_paused(): time.sleep(10); continue` (`:1265-1271`) — ALL tasks stop, including the 5s-interval (~15s effective) `record_pnl`/`auto_close_trades`/`fno_auto_trade`/`cash_auto_trade`. The pause flag and `is_scheduler_paused` live in `telegram_commander.py:40-45`, not in `scheduler.py`. Fails open on import error (bare `except: pass`, loop proceeds as unpaused). |
| Staggering (CLAUDE.md op-rule 5) | `initial_delay` staggers startup bursts; the 3 daily retrains are explicitly offset by MEASURED runtime + margin: `ml_retrain` T+150 (~25min GBC), `xgb_cash_retrain` T+1800 (~10.3min), `retrain_xgb_daily` T+3000 (~31min F&O XGB) — comments at `scheduler.py:1356-1380` cite the exact prior incident (two 30-min jobs starting 10s apart) this fixes. |
| `_boot_warmup_active()` | `scheduler.py:37-57`. Wraps `fyers_boot_warmup.is_active()`; **fails OPEN** (returns False / tasks run) on any import/attribute error, by design ("the dangerous direction is everything stays paused"). Gates: `auto_analysis`, `cache_refresh`, `self_healing`, `fyers_daily_topup`, `tijori_daily_partners` (also gated on market-closed), and half of `cash_auto_trade` (only the new-entry scan; trailing-stop management on existing positions is NEVER gated — `bot.auto_trade(skip_new_entries=_boot_warmup_active())`). |
| `get_task_registry()` | `:74-92`. Lists every registered task's NAME + compiled DEFAULT interval + initial_delay for the settings UI; does not reflect live DB overrides (empty until `start_scheduler()` has run). |

### 2. COMPLETE SCHEDULER TASK TABLE (31 tasks, VERIFIED — matches inventory count)

Live interval = value read from `config_settings` (`scheduler_interval_<name>`), queried 2026-09-27 (re-verified 2026-09-28).
**30 of the 31 tasks have a `scheduler_interval_*` DB row** (31 rows in total: those 30 + the orphan
`collect_5min_candles`); **`tijori_daily_partners` has NO row** and runs on its code default (1800). Every
row present **exactly equals its code default** except one (flagged: `auto_close_trades`). "Effective" cadence
of any interval below 15s is ~15s (dispatch-tick floor, see §1). Gate values are LIVE
(queried 2026-09-27): `cash_auto_trade_enabled=true`, `fno_auto_trade_enabled=false`, `paper_trading=true`,
`telegram_enabled=true`, `fyers.ws_enabled=false`.

| Name | Function:line | Default (s) | LIVE (s) | Initial delay | Gates | Calls | Produces | External calls | Status |
|---|---|---|---|---|---|---|---|---|---|
| token_refresh | `_task_token_refresh:695` | 3600 | 3600 | 0 | none | `token_refresher.check_and_refresh` | Groww token refresh | Groww auth | ACTIVE |
| fyers_token_refresh | `_task_fyers_token_refresh:727` | 3600 | 3600 | 1 | requires `FYER_PIN` in `.env` | `fyers_auth.refresh_if_needed` | refreshed FYERS access token | FYERS auth | ACTIVE |
| self_healing | `_task_self_healing:704` | 3600 | 3600 | 90 | `_boot_warmup_active()` | `self_healing.run_all()` | backfills/alerts, `_HISTORY` | FYERS (bulk, gated) | ACTIVE |
| cache_refresh | `_task_cache_refresh:128` | 3600 | 3600 | 240 | `_boot_warmup_active()` | `fundamental_analysis.get_fundamental_analysis` per symbol (~67, up to ~400 quote calls cold) | fundamentals cache, `earnings.last_qrev.*` config, queues Tijori refresh on new quarter | FYERS quotes (bulk) | ACTIVE |
| update_watchlist_prices | `_task_update_watchlist_prices:192` | 3600 | 3600 | 10 | — | **no-op**: a docstring opened at `:193` runs until the `"""` embedded in the commented `cursor.execute("""` at `:253`; the rest is comments and the only statement is `return` at **`:320`** (end of function, not top) | nothing | none | **DISABLED** (since 2026-08-15, migrated to FYERS; body fully commented, see `:194-320`). Its docstring claim that `bot.analyze_long_term_trend()` reads `stock_prices` is stale — `bot.py:690-692` now reads `fyers_candles` |
| fyers_daily_topup | `_task_fyers_daily_topup:885` | 3600 | 3600 | 200 | `_boot_warmup_active()`; market must be CLOSED | `fyers_historical_backfill.topup_daily()` | forward-fills `fyers_candles` DAILY tier | FYERS (~1 call/symbol steady-state) | ACTIVE |
| record_pnl | `_task_record_pnl:912` | 5 | 5 (effective ~15s) | 8 | market must be OPEN | reads `paper_trades.json`, POSTs `http://127.0.0.1:8000/api/live-prices` | `PnLSnapshot` DB row (`session.add(snapshot)` at `scheduler.py:1023`) — **only while `paper_trades.json` has OPEN trades** (currently 0 → newest row 2026-09-22 09:32; a gap in the P&L chart is expected, not a failure) | internal HTTP (loopback) | ACTIVE |
| auto_analysis | `_task_auto_analysis:95` | 300 | 300 | 15 | `_boot_warmup_active()` | `auto_analyzer.auto_analyze_watchlist()` | predictions cache for dashboard | FYERS (bulk) | ACTIVE |
| news_prefetch | `_task_news_prefetch:108` | 600 | 600 | 20 | — | `news_sentiment.get_news_sentiment` per WATCHLIST symbol | warms news cache | news APIs | ACTIVE |
| fno_auto_trade | `_task_fno_auto_trade:636` | 5 | 5 (effective ~15s) | 2 | `fno_auto_trade_enabled` (default "true"; **LIVE = false**) | `fno_trader.auto_trade_fno()` | F&O orders/actions | Groww orders, FYERS quotes | **gated-off LIVE** (config disables it) |
| cash_auto_trade | `_task_cash_auto_trade:797` | 5 | 5 (effective ~15s) | 3 | `cash_auto_trade_enabled` (default "false"; **LIVE = true**); market must be OPEN; new-entry half also gated by `_boot_warmup_active()` | `bot.auto_trade(skip_new_entries=...)` | cash orders (paper or real per `paper_trading`, **LIVE = true → paper**), trailing-stop moves | Groww orders, FYERS quotes | ACTIVE (paper mode) |
| auto_close_trades | `_task_auto_close_trades:827` | 5 (effective ~15s) | **300 (DB override)** | 4 | market must be OPEN | `paper_trader.get_live_price`, `trailing_stop.check_and_close_trades_on_loss` | closes `paper_trades.json` entries hitting TP/SL | FYERS via `get_live_price` | ACTIVE — **but see contradiction below** |
| fno_capital_sync | `_task_fno_capital_sync:662` | 600 | 600 | 40 | — | `fno_trader.sync_capital_from_groww()` | syncs F&O capital figure | Groww account balance | ACTIVE |
| prune_idempotency | `_task_prune_idempotency_keys:673` | 3600 | 3600 | 120 | `idempotency.retention_hours` (LIVE=48) | `db_manager.prune_idempotency_keys` | deletes expired idempotency rows | DB only | ACTIVE |
| global_indices | `_task_global_indices:685` | 900 | 900 | 60 | — | `fno_trader.fetch_global_indices()` | global indices cache for F&O decisions | external index feed | ACTIVE |
| world_news | `_task_world_news:743` | 900 | 900 | 65 | — | `world_news_collector.collect_world_news()` | `global_news` rows | RSS/Google News | ACTIVE |
| geopolitical | `_task_geopolitical_collect:627` | 1800 | 1800 | 70 | — | `commodity_tracker.collect_geopolitical_news()` | geopolitical news rows | news sources | ACTIVE |
| supply_chain | `_task_supply_chain:119` | 900 | 900 | 75 | — | `supply_chain_collector.collect_once()` | commodity data | external commodity sources | ACTIVE |
| telegram_summary | `_task_telegram_daily_summary:1129` | 1800 | 1800 | 80 | `telegram_enabled` (LIVE=true); only fires 15:30-16:00 IST window | `daily_summary.send_daily_summary()` | Telegram message | Telegram Bot API | ACTIVE, once/day |
| paper_eod_summary | `_task_paper_eod_summary:1037` | 1800 | 1800 | 85 | `telegram_enabled` AND `paper_trading` both true (LIVE: both true); 15:30-16:00 IST window | `_send_paper_eod_summary()` (queries `PaperTrade` table — the ONLY reader of that model, `scheduler.py:1059-1084`) | Telegram message | Telegram Bot API | ACTIVE, once/day. **Under-reports**: the `paper_trades` DB table holds 4 rows against 26 trades in `paper_trades.json` (the operational source of truth), so this summary is built from a partial order-fill log |
| build_daily_snapshots | `_task_build_daily_snapshots:1147` | 900 | 900 | 86 | window 16:05-16:30 IST; skips if already built today (`daily_snapshots.json`) | POSTs `http://localhost:8000/api/paper-trading/build-daily-snapshots-with-candles` | `daily_snapshots.json` | internal HTTP (loopback) | ACTIVE, once/day |
| cost_scraper | `_task_cost_rate_update:559` | 3888000 (45d) | 3888000 | random 0-170s | — | `costs.update_cost_rates()` | trading cost rate config | scrapes Groww cost page | ACTIVE — but NOT "rare": `last_run` is in-memory, so it runs once after **every app restart**; the 2026-08-24 and 2026-09-27 scraper runs are 34 days apart, i.e. restarts, not the 45-day timer |
| deep_analysis | `_task_deep_analysis:752` | 1800 | 1800 | 120 | — | `deep_analysis.generate_deep_analysis` for top 6 WATCHLIST symbols | cached deep-analysis text | LLM/data sources | ACTIVE |
| market_intelligence | `_task_market_intelligence:769` | 86400 | 86400 | 130 | — | `market_intelligence.collect_all_watchlist()` | institutional holdings/peer data | scraped site (rate-limited to 1 page/stock/day) | ACTIVE |
| research_engine | `_task_research_engine:788` | 14400 | 14400 | 140 | — | `research_engine.generate_research_all()` | research verdicts/leaderboard | internal analysis | ACTIVE |
| ml_retrain | `_task_ml_retrain:478` | 86400 | 86400 | 150 | — | `bot.train_model` per `bot.get_active_watchlist()` symbol (~73) | GradientBoosting model files | none (local compute) | ACTIVE, ~25min |
| xgb_cash_retrain | `_task_xgb_cash_retrain:514` | 86400 | 86400 | 1800 | — | `bot.train_xgb_model` per active-watchlist symbol | cash XGBoost model files | none | ACTIVE, ~10.3min |
| retrain_xgb_daily | `_task_retrain_xgb_daily:324` | 86400 | 86400 | 3000 | — | `fno_backtester._generate_xgb_training_data`, `xgb.XGBClassifier.fit` | `models/xgb_backtester.joblib` (atomic `os.replace`), `log_xgb_training_event` | none | ACTIVE, ~31min |
| auto_metadata | `_task_auto_metadata:779` | 604800 | 604800 | 170 | — | `auto_metadata.refresh_all_metadata()` | stock metadata (name/sector/peers) | Screener.in scrape | ACTIVE, weekly |
| tijori_refresh | `_task_tijori_refresh:568` | 21600 | 21600 | 180 | `tijori.refresh_interval_days` (LIVE=7) governs which symbols count as stale | `tijori_collector.collect_stale_symbols()` | Tijori fundamentals/supply-chain data | Tijori scrape | ACTIVE |
| tijori_daily_partners | `_task_tijori_daily_partners:578` | 1800 | 1800 (**no DB row** — runs on the code default) | 195 | `_boot_warmup_active()`; market must be CLOSED; once/IST-day (`tijori.last_partner_refresh` config marker); mutex via `threading.enumerate()` name check | own daemon thread → `tijori_collector.collect_missing_partner_snapshots(limit=10000)` | partner company snapshots | Tijori scrape (~45min pass, 6s pacing) | ACTIVE, once/day |

**CONTRADICTION — `auto_close_trades` live interval**: code registers it at `5` seconds with the comment
"Check every 5s for TP/SL hits" (`scheduler.py:1331`), but `config_settings.scheduler_interval_auto_close_trades = 300`
(VERIFIED FROM DATABASE, 2026-09-27) overrides it to every 300s (5 minutes). `_resolve_interval` always prefers
a positive DB override over the code default (`scheduler.py:1223-1233`), so **the scheduler's
`check_and_close_trades_on_loss` TP/SL path for paper trades currently runs every 5 minutes, not every 5 seconds** — a real,
currently-live gap between comment/intent and behaviour. The override's `updated_at` is 2026-08-26 04:26:51, the same
time as ~28 other `scheduler_interval_*` rows (a bulk seed from the settings UI), so it is a stored setting, not a
one-off edit. **Scope of the gap (corrected):** only the scheduler's `check_and_close_trades_on_loss` path is 5-minute.
Trailing-stop exits still run about every ~15s via `cash_auto_trade` → `bot.auto_trade()` →
`monitor_and_update_trailing_stops()` (`bot.py:2056`; market open, `cash_auto_trade_enabled=true`), and an open dashboard
also POSTs `/api/auto-close/check` (`index.html:14593` → `app.py:6464-6502` → the same
`check_and_close_trades_on_loss`) while a browser is open. `record_pnl`, `fno_auto_trade`, `cash_auto_trade` resolve to
their coded 5s default (their DB rows equal 5) — i.e. ~15s effective cadence because of the 15s dispatch tick.

**Stale config row**: `config_settings` also has `scheduler_interval_collect_5min_candles = 300` (the 31st of the 31 `scheduler_interval_*` rows; the other 30 map to live tasks, and `tijori_daily_partners` has none) — no task
named `collect_5min_candles` is registered (scheduler.py's own comment at `:1315-1320` says this task, along
with `sync_historical_candles`/`aggregate_candles_to_daily`, was REMOVED because it wrote to the legacy
`candles` table which has had 0 rows since the FYERS migration). This config row is now inert — `_resolve_interval`
only ever looks it up by an active task's name, so it is orphaned data, not a live effect.

### 3. Background threads — every `threading.Thread(`/`start_in_background` (22, matches inventory)

| # | Name (or "—" if unnamed) | Where started | Target | Started by / when | What it does | Gating |
|---|---|---|---|---|---|---|
| 1 | `master-scheduler` | `scheduler.py:1389` | `_scheduler_loop` | `start_scheduler()`, app.py `__main__` startup | Runs the 31-task dispatch loop forever (see §1-2) | none — this is the scheduler |
| 2 | `tijori-daily-partners` | `scheduler.py:621` | `_run` → `tijori_collector.collect_missing_partner_snapshots(limit=10000)` | Nested one-shot launched FROM inside scheduler task `tijori_daily_partners`, so a ~45min pass doesn't occupy a pool worker | Refreshes every partner company once/day | boot-warmup, market-closed, once/IST-day marker, `threading.enumerate()` name-mutex |
| 3 | `change-feed-watcher` | `change_feed.py:140` | `_watch_loop` | `change_feed.start()`, app.py startup | Polls `paper_trades.json`/`trade_journal.json` every 1s (stat+hash), emits SSE `notify()` events | none |
| 4 | `fyers-boot-warmup` | `fyers_boot_warmup.py:350` | `run` | `start_in_background()`, app.py startup, BEFORE `start_scheduler()` | Sequentially warms the FYERS freshness cache for the watchlist once, avoiding a 73-way request burst on restart | waits up to `fyers.boot_warmup_token_wait_seconds` (default 45s) for a valid token; hard timeout `fyers.boot_warmup_timeout_seconds` (default 150s); `fyers.boot_warmup_enabled` (default true) |
| 5 | `fyers-ws` | `fyers_ws_client.py:572` | `_run` (supervisor) | `start_in_background()`, app.py startup | Maintains FYERS live-tick WebSocket; self-describes as INERT (nothing on the trading path reads its state) | `fyers.ws_enabled` — **LIVE = false (VERIFIED FROM DATABASE 2026-09-27) → this thread does not start** |
| 6 | (unnamed) | `auto_analyzer.py:285` | `background_loop` (self-looping, `time.sleep(interval_seconds)`) | `start_auto_analyzer(300)`, called ONLY from app.py:8186 **fallback path** if `start_scheduler()` itself raises | Would run watchlist auto-analysis every 300s | Dormant under normal operation — `auto_analysis` scheduler task already covers this |
| 7 | `supply-chain-collector` | `supply_chain_collector.py:372` | `_collector_loop` (self-looping) | `start_collector(900)`, same app.py:8186 fallback-only path | Would run supply-chain collection every 900s | Dormant under normal operation — `supply_chain` scheduler task already covers this |
| 8 | `supply-chain-init` | `app.py:8186` | `collect_once` (one-shot) | Same fallback block, immediately before #7 | One immediate supply-chain pass | Fallback-only, dormant |
| 9 | `telegram-commander` | `telegram_commander.py:1418` | `_polling_loop` | `start_commander()`, app.py startup (own try/except, independent of scheduler success) | Long-polls Telegram `getUpdates` (30s) forever; dispatches commands/callbacks | Requires `telegram_bot_token` + `telegram_chat_id` configured, else never starts |
| 10 | `telegram-auto-analysis` | `telegram_commander.py:998` | `auto_analyzer.auto_analyze_watchlist` (one-shot) | `_cmd_runanalysis` — user taps "Run AI Now" / `/runanalysis` | Runs one watchlist analysis pass | user-triggered, no cooldown |
| 11 | `telegram-research-batch` | `telegram_commander.py:1008` | `research_engine.generate_research_all` (one-shot) | `_cmd_runresearch` — user taps "Run Research" / `/runresearch` | Runs one research batch | user-triggered, no cooldown |
| 12 | (unnamed) | `app.py:1503` | `_run` → `world_news_collector.collect_world_news` | POST `/api/world-news/collect` | Manual world-news collection | dashboard-triggered |
| 13 | (unnamed) | `app.py:1633` | `bg_collect` → `market_intelligence.collect_all_watchlist` | POST `/api/intelligence/collect-all` | Force-refresh institutional/peer data | dashboard-triggered |
| 14 | (unnamed) | `app.py:1653` | `bg_refresh` → `auto_metadata.refresh_all_metadata` | POST `/api/metadata/refresh` | Force stock metadata refresh | dashboard-triggered |
| 15 | (unnamed) | `app.py:1767` | `_run` → `research_engine.generate_research_all` | POST `/api/research/all` | Full research batch, all tracked stocks | dashboard-triggered |
| 16 | (unnamed) | `app.py:1789` | `_run` → `scheduler._task_update_watchlist_prices()` with `_FORCE_BACKFILL=1` | POST `/api/watchlist/refresh-prices` | Intends to force-refresh watchlist prices | **The underlying function is a no-op** (disabled since 2026-08-15, body fully commented — see task table). This endpoint (`app.py:1778-1790`) still spawns the thread, which does nothing regardless of the env override it sets — the user sees a "refresh" that refreshes nothing. |
| 17 | (unnamed) | `app.py:1972` | `collect_once` (supply chain) | POST `/api/supply-chain/refresh` | Manual supply-chain collection pass | dashboard-triggered |
| 18 | (unnamed) | `app.py:2946` | `tijori_collector.onboard_symbol(symbol)` | POST `/api/supply-chain-intel/<symbol>/refresh` | Full Tijori onboarding (page + partner match) for one symbol | dashboard-triggered |
| 19 | (unnamed) | `app.py:4150` | `bg_fetch` | POST `/api/watchlist/add` | Backfills FYERS candles + trains models for a newly added watchlist symbol; defers backfill/training if market is open (self-healing picks it up after close) | market-open defers part of the work |
| 20 | (unnamed) | `app.py:5191` | `_pa_refresh_background` → `bot.analyze_portfolio()` | GET `/api/portfolio-analysis`, when a cached result already exists | Optimistic-UI pattern (CLAUDE.md std #4): serves cached result instantly, refreshes in background | `_pa_cache["refreshing"]` flag prevents concurrent refreshes |
| 21 | (unnamed) | `app.py:5485` | `bg_fetch` → `fetch_and_store_all_stocks(symbols)` | POST `/api/prices/fetch` | Fetch historical prices from Groww into DB | dashboard-triggered |
| 22 | (unnamed) | `app.py:5784` | `auto_analyzer.auto_analyze_watchlist` (one-shot) | POST `/api/auto-analysis/run` | Manual auto-analysis trigger (dashboard equivalent of #10) | dashboard-triggered |

Startup order (VERIFIED FROM CODE, `app.py` `__main__` block, ~8150-8190): (1) `fyers_boot_warmup.start_in_background()` →
(2) `fyers_ws_client.start_in_background()` → (3) `scheduler.start_scheduler()` (falls back to threads #6-8 only on
exception) → (4) `telegram_commander.start_commander()` → (5) `change_feed.start()`.

### 4. `self_healing.py` — FYERS data-pipeline healers

| Field | Detail |
|---|---|
| Where | `self_healing.py`, entry point `run_all():289` |
| Design rules (from module docstring) | Never touches order execution/positions (data only); every remediation must be idempotent + insert-only; unfixable faults are reported, not guessed at; per-symbol cooldown + per-run cap; no backfill while market open |
| Healer 1 — token | `check_token():94`. Detects FYERS token expiry via `fyers_auth.token_expiry()`. NOT auto-fixable (FYERS disabled the refresh API for SEBI compliance) — always produces an "alert", never "healed", when dead. Threshold: alerts once remaining validity < 1800s. |
| Healer 2 — missing symbols | `check_missing_symbols():130`. Finds active `stocks` rows with zero `fyers_candles` rows, backfills via `fyers_historical_backfill.backfill_symbol()`. Guardrails: `_MAX_BACKFILLS_PER_RUN=2`, `_BACKFILL_COOLDOWN_SECONDS=21600` (6h) per symbol. Deferred (report-only) while market open. **Cannot heal SPICEJET**: it is active in `stocks` but has 0 `fyers_candles` rows ever and no `master_ticker_table` row (ghost symbol), so it will be reported every run and never fixed. |
| Healer 3 — stale intraday | `check_stale_intraday(max_symbols=10):222`. Finds symbols whose newest `5S` bar lags the market leader by >1 day, tops up via `fyers_historical_backfill.ensure_recent(ttl_seconds=0)`. Deferred while market open. |
| When it runs | Scheduler task `self_healing`, every 3600s (LIVE=3600), gated by `_boot_warmup_active()` (`scheduler.py:704-724`) |
| Order in `run_all()` | Token checked FIRST; if EXPIRED, the other two healers are skipped entirely (recorded as a "skipped" action) rather than cascading unrelated failures from the same root cause |
| Market-hours check | `_market_is_open()` reuses `fno_trader._is_market_open()`; **fails CLOSED** on its own error (assumes market OPEN → skips backfill) — the harmful direction here is backfilling during hours, not skipping a repair |
| History | `_HISTORY = deque(maxlen=100)`, each entry `{at, kind, target, status: healed\|failed\|alert\|skipped, detail}`; surfaced at `/api/self-healing` (per module docstring; endpoint itself lives in app.py, not verified line-by-line in this pass) |
| Failure behaviour | Every healer wraps its body in try/except and returns a `"failed"` record rather than raising — `run_all()` itself never raises |
| Status | ACTIVE |

### 5. `change_feed.py` — SSE change notification

| Field | Detail |
|---|---|
| Where | `change_feed.py`; `start():134`, `notify():55`, `subscribe():72` |
| Watches | Two files by content hash, not just mtime: `paper_trades.json` → topic `trades`, `trade_journal.json` → topic `journal` (`WATCHED_FILES:41`). Poll interval 1.0s. A byte-identical rewrite (e.g. the periodic tracker rewrite during market hours; the scheduler's 5s-interval tasks actually fire at most once per ~15s pass) does NOT emit an event — SHA1 digest is compared, so this replaces fixed-interval dashboard polling only for genuine changes. |
| Explicit `notify()` callers | `db_manager.set_config` — topic `config`, per module docstring (not independently re-verified line-by-line for every call site in this pass; the module comment is the source) |
| Consumer | `/api/events` SSE route in `app.py` (per docstring — route itself out of this section's file list) |
| Subscriber model | Bounded per-subscriber `queue.Queue(maxsize=100)`; `MAX_SUBSCRIBERS=16`; a stalled subscriber's queue fills and further events are dropped for it (`queue.Full` swallowed) rather than blocking other subscribers |
| Failure behaviour | `notify()` never raises (try/except around the whole broadcast); explicitly "nothing here is on a money path" per docstring |
| Status | ACTIVE |

### 6. `telegram_commander.py` — interactive bot (polling)

| Field | Detail |
|---|---|
| Polling loop | `_polling_loop():1345`, started by `start_commander():1403` on thread `telegram-commander`. Long-polls `getUpdates` with `timeout=30`; on Telegram API error sleeps 5s, aborts after 10 consecutive; on other exceptions aborts after 20 consecutive. Sends an "online" message with the main menu on start. |
| Authorization — message path | `_handle_message():1304`. `msg_chat_id = str(message["chat"]["id"])` compared to `str(chat_id)` (the configured `telegram_chat_id`) at `:1310-1313`; mismatch → logged and silently dropped. **VERIFIED enforced.** |
| Authorization — callback path | `_handle_callback():1277`. `sender_chat_id` pulled from `callback_query["message"]["chat"]["id"]`, compared to `str(chat_id)` at `:1283-1285`; mismatch → `_answer_callback(..., "Unauthorized")` and drop. **VERIFIED enforced, independently of the message path.** |
| Pause flag | Module-level `_scheduler_paused` (in-process bool, NOT persisted to DB/config — a restart clears it), read by `telegram_commander.is_scheduler_paused()` (defined at `telegram_commander.py:40-45`; imported into `_scheduler_loop()` from `telegram_commander`, NOT a `scheduler.is_scheduler_paused()`) at the top of `_scheduler_loop()`. |

Command / callback table — every entry in `_COMMANDS`/`_CALLBACKS` (`:1215-1274`), what it does, and whether it can move money or change config:

| Command(s) | Handler:line | What it does | Moves money? | Changes config? |
|---|---|---|---|---|
| `/help`, `/menu`, `/start` | `_cmd_help:526`, `_cmd_start:660` | Show menu / resume scheduler | no | no (resume is in-memory `_scheduler_paused=False`) |
| `/dashboard`, `/trading`, `/positions`, `/holdings`, `/market`, `/worldnews`, `/rawmat`, `/news`, `/watchlist`, `/watch`, `/analysis`, `/research`, `/journal`, journal-stats, `/controls`, `/summary` (read variant only) | various `_cmd_*` | Read-only status/data display, formatted from the same reconciled data the dashboard reads | no | no |
| `/runanalysis` | `_cmd_runanalysis:995` | Spawns thread `telegram-auto-analysis` → `auto_analyzer.auto_analyze_watchlist()` | no (analysis only) | no |
| `/runresearch` | `_cmd_runresearch:1005` | Spawns thread `telegram-research-batch` → `generate_research_all()` | no | no |
| `/autotrade` (button "Run Auto-Trade") | `_cmd_autotrade:1046` | **Calls `bot.auto_trade()` directly and synchronously**, reporting buys/sells/skips | **YES — places real or paper orders per current `paper_trading` mode, immediately, in-request** | no |
| `/stops` | `_cmd_stops:1085` | Calls `bot.monitor_and_update_trailing_stops()` | Moves stop-loss levels on open positions (not new orders) | no |
| `/summary` | `_cmd_summary:1199` | Calls `daily_summary.send_daily_summary()` on demand | no | no |
| `/papermode` → confirm | `_cmd_toggle_paper:1147` → `_cmd_paper_confirm:1169` | Two-step confirm, flips `paper_trading` config | Changes whether FUTURE trades are real vs simulated | **YES** — `set_config("paper_trading", ...)` |
| `/cashtrade` → confirm | `_cmd_cashtrade:668` → `_cmd_cashtrade_confirm:694` | Two-step confirm, flips `cash_auto_trade_enabled` | Enables/disables the scheduler's automated cash trading | **YES** — `set_config("cash_auto_trade_enabled", ...)` |
| `/stop` → confirm | `_cmd_stop:1183` → `_cmd_stop_confirm:1193` | Two-step confirm, sets in-memory `_scheduler_paused=True` — **pauses the ENTIRE scheduler, including the TP/SL monitors (the `auto_close_trades` path and `cash_auto_trade`'s trailing-stop management)**; the confirmation text itself warns "open positions will not be protected while paused" | Indirectly risks money (removes protection) | no (in-memory only, not `config_settings`) |

**FINDING — `/autotrade` bypasses the scheduler's own gate**: the scheduler's `_task_cash_auto_trade` (scheduler.py:797-824)
checks `cash_auto_trade_enabled` before calling `bot.auto_trade()`. `_cmd_autotrade` (telegram_commander.py:1046-1082)
calls `bot.auto_trade()` directly with no such check — pressing "Run Auto-Trade" (or `/autotrade`) in Telegram runs a
real trading cycle even if `cash_auto_trade_enabled=false`. **VERIFIED (2026-09-28, resolves the earlier open unknown):**
`bot.auto_trade` (bot.py:2022-2110) never reads `cash_auto_trade_enabled` and has **no market-hours check** either — the
scheduler adds that at scheduler.py:806-809, so the Telegram path also runs outside market hours. The Telegram call also
omits the scheduler's `skip_new_entries=_boot_warmup_active()` boot-warm-up gate. Internal gates that DO still apply
inside `bot.auto_trade`: `_portfolio_reviewed` (bot.py:2043), `model.*_cash_enabled` (bot.py:2094-2095), the broker + paper
position lookup (fail-closed) and the confidence floor. There is no master-switch or market-hours gate of its own.

### 7. `telegram_alerts.py` — outbound alert formatters

| Field | Detail |
|---|---|
| Core send | `send_message():42` — raw Telegram `sendMessage`; gated by `is_enabled()` (`telegram_bot_token` + `telegram_chat_id` + `telegram_enabled=true` all required) |
| Actually-called functions (VERIFIED — grepped every call site repo-wide) | `is_enabled()`, `send_message()`, `test_connection()` (from `app.py` `/api/telegram/test` and boot diagnostics), `alert_trade_executed()` (2 callers, `bot.py:1636,1777`), `alert_trade_closed()` (1 caller, `bot.py:1998`) |
| **DEAD CODE — zero callers anywhere in the repo** | There are **9 `alert_*` functions** in `telegram_alerts.py` (lines 117-282). **6 have zero callers**: `alert_fno_trade()`, `alert_stop_loss_hit()`, `alert_target_hit()`, `alert_signal()`, `alert_portfolio_warning()`, `alert_research()`; `alert_daily_summary()` is dead transitively (its only caller, `telegram_alerts.py:321`, is inside the also-dead `send_scheduled_summary()`); plus `send_scheduled_summary()` itself (not an `alert_*` name). The remaining 2 (`alert_trade_executed`, `alert_trade_closed`) are live. The dead ones are fully implemented, formatted, gated by `is_enabled()` — just never invoked. F&O trades, target hits, and research signals currently generate NO Telegram alert despite dedicated formatters existing for exactly those events. **Stop-loss nuance (corrected):** a trailing-stop hit closed via `bot.auto_trade` → `monitor_and_update_trailing_stops()` DOES send `alert_trade_closed` (`bot.py:1996-1999`). Only closes made by `trailing_stop.check_and_close_trades_on_loss` (scheduler `auto_close_trades`, `/api/auto-close/check`) send no alert. |
| Callers actually sending messages | `bot.py` (trade executed/closed), `cost_notifications.py:198` (`send_message`), `scheduler.py:1087,1124` (paper EOD summary), `daily_summary.py:391-394` (daily summary, possibly split across 2 messages if >4000 chars), and **`google_auth.py:242-245`** (UNTRACKED file — calls `send_message("Signed in with Google: ...")` on every Google sign-in; it also creates/links `users` rows, see database section) |
| Config keys | `telegram_bot_token` (secret, not recorded), `telegram_chat_id` (secret, not recorded — treated as sensitive per COMMON_RULES), `telegram_enabled` (LIVE=true) |
| Status | Core send path ACTIVE; of the 9 `alert_*` formatters, 2 are live, 6 have no callers and `alert_daily_summary` is transitively dead (plus dead `send_scheduled_summary`) — LEGACY/DEAD |

### 8. `daily_summary.py`

| Field | Detail |
|---|---|
| Entry point | `send_daily_summary():371`, called from scheduler task `telegram_summary` (15:30-16:00 IST window) and Telegram `/summary` on demand |
| Builds | `generate_daily_summary()` gathers: global indices (`fno_trader.fetch_global_indices`, 15s timeout via its own 1-worker pool), market sentiment (`news_sentiment.get_market_sentiment`), top research signals (`research_engine.get_cached_leaderboard`), portfolio snapshot (`bot.get_holdings`), watchlist predictions (`bot.scan_watchlist()` — same path the dashboard uses, per a documented rewrite fixing 4 independent bugs that used to make this always return `[]`), key news (`world_news_collector.get_recent_news`), last-day candle stats (direct `fyers_candles` query for NIFTY/BANKNIFTY/RELIANCE/TCS/HDFCBANK) |
| Sends to | `telegram_alerts.send_message()`, split into 2 messages if the formatted text exceeds 4000 chars |
| Gate | `telegram_alerts.is_enabled()` — LIVE=true |
| Failure behaviour | Every data gatherer wrapped in `_safe()` (returns default on any exception) — a failure in one section (e.g. candle stats) never blocks the rest of the summary |
| Status | ACTIVE |

### 9. `cost_notifications.py`

| Field | Detail |
|---|---|
| Entry point | `send_cost_change_notification(update_result, scrape_result, db)`, called only from `costs.py:199` inside `update_cost_rates()` — which is the scheduler's `cost_scraper` task (45-day / 3,888,000s interval, but in-process only — it also runs once after every app restart, so actual runs are 2026-08-24 and 2026-09-27, 34 days apart) |
| What it sends | Formatted HTML message: count of costs updated/failed, per-cost old→new value with % change and a "suspicious" flag (>10% change, from `costs.py`'s own logic, not this file), validation warnings, source URL/timestamp |
| Sent via | `telegram_alerts.send_message()`, gated by BOTH `telegram_enabled` (LIVE=true) AND `telegram_cost_notifications` (LIVE=true, default "true") |
| Also does | Intends to log every notification to a `cost_notifications` DB table (auto-created via `CREATE TABLE IF NOT EXISTS` on first use, `_ensure_notification_table_exists():266`) for dashboard display; `get_unread_notifications()` / `mark_notification_as_read()` support a dashboard notification list. **Observed (VERIFIED 2026-09-28): the table has 1 row (created 2026-07-31 22:20) and nothing since** — even though the cost pipeline ran and wrote config rows on 2026-08-24 and 2026-09-27 (only caller: scheduler → `costs.update_cost_rates`, `costs.py:187-199`). Those runs left NO notification row, so `_log_dashboard_notification` has been failing or the notification step was not reached (cause UNVERIFIED; failures are only logged as warnings). |
| DB table | `cost_notifications` (id, type, message, data JSON, is_read, created_at) — self-provisioning, not in the original schema migration |
| Status | ACTIVE as a sender path (triggered by the scheduler's cost run — 45-day timer plus once per app restart), but the dashboard-notification logging has left no row since 2026-07-31 (see above) |

### 10. `sanity_check.py` — STALE / BROKEN standalone script

| Field | Detail |
|---|---|
| Where | `sanity_check.py`, `main():10` |
| Purpose (per docstring) | Manual smoke test: candle availability, XGBoost model readiness, live signal generation, scheduler task presence, metadata table count |
| **BROKEN** | Line 48: `from scheduler import _task_collect_hourly_candles, _task_retrain_xgb_daily` — `_task_collect_hourly_candles` **does not exist** in the current `scheduler.py` (VERIFIED — `grep` for the name returns nothing; the corresponding collection tasks were removed per `scheduler.py:1315-1320`'s own comment, since they wrote to the legacy `candles` table with 0 rows post-FYERS-migration). Running this script now raises `ImportError` inside the try/except and reports `"Sanity check failed"` on Test 4 (or earlier, depending on Python's import resolution order — the whole `from ... import a, b` fails atomically if either name is missing). |
| Callers | None found in scheduler/app/cron — appears to be a manual/CLI-only diagnostic (`if __name__ == "__main__"`), not wired into any automated path |
| Status | LEGACY / BROKEN — would need `_task_collect_hourly_candles` removed from its import list to run at all |

### 11. `groww-commands.sh` — developer quick-reference (no automation)

Plain shell script that `echo`s a cheat-sheet of commands when sourced (`source groww-commands.sh`); despite the
header comment promising `groww-start`/`groww-stop`/`groww-status` shell functions, it defines none — it only
prints text, including the literal strings `./start-all.sh`, `./stop-all.sh`, `./status.sh`. **Note**: this printed
cheat-sheet suggests `./stop-all.sh` (a separate script, confirmed to exist) as part of a full restart, which is
a different sequence from the one CLAUDE.md's Operational Rule 1 mandates (`./start-all.sh --stop && ./start-all.sh
--dashboard-only`, chosen specifically because it verifies the port is actually freed). Not independently verified
here whether `stop-all.sh` has the same PID/port-verification safety as `start-all.sh --stop` — out of this
section's file list (start-all.sh/stop-all.sh are startup scripts, not scheduler/ops modules). Flagged as a
possible contradiction between this helper script's suggested workflow and the documented safe-restart procedure.
Status: informational only, zero automation, zero side effects from sourcing it.

### 12. TIMING MAP — WHEN → WHAT RUNS → WHAT IT CALLS → WHAT IT PRODUCES

| Frequency | Task(s) | Calls | Produces |
|---|---|---|---|
| Every 1s | `change-feed-watcher` thread | `os.stat` + conditional SHA1 on 2 JSON files | SSE `notify()` events to `/api/events` subscribers |
| Every ~15s (5s interval, bounded by the 15s dispatch tick) (LIVE) | `record_pnl`, `fno_auto_trade` (gated off), `cash_auto_trade` | `PnLSnapshot` write (only while `paper_trades.json` has OPEN trades); `fno_trader.auto_trade_fno`; `bot.auto_trade` | P&L snapshot row; F&O/cash orders + trailing-stop moves (incl. trailing-stop closes with `alert_trade_closed`) |
| Every 15s | Scheduler dispatch tick (`_scheduler_loop`) | `_load_interval_overrides()` (1 config query), then per-task interval check | Task submissions to the 4-worker pool |
| Every 300s (5min, LIVE override) | `auto_close_trades` | `get_live_price`, `check_and_close_trades_on_loss` | Closes `paper_trades.json` entries at TP/SL (silent — no Telegram alert) — **was every 5s (~15s effective) by code intent, now 300s live**; trailing-stop exits still run ~every 15s via `cash_auto_trade`, and an open dashboard polls `/api/auto-close/check` into the same close path |
| Every 300s (coded default) | `auto_analysis` | `auto_analyzer.auto_analyze_watchlist` | Watchlist predictions cache |
| Every 600s | `news_prefetch`, `fno_capital_sync` | news sentiment per symbol; Groww balance sync | warmed news cache; synced F&O capital |
| Every 900s | `global_indices`, `world_news`, `supply_chain`, `build_daily_snapshots` (window-gated) | index feed; RSS/Google News; commodity sources; internal HTTP | indices cache; `global_news` rows; commodity data; `daily_snapshots.json` (once/day) |
| Every 1800s | `geopolitical`, `telegram_summary` (window-gated), `paper_eod_summary` (window-gated), `tijori_daily_partners` (day-gated) | geopolitical news collect; `daily_summary.send_daily_summary`; PaperTrade query; Tijori partner pass | geopolitical rows; Telegram daily summary (once/day); Telegram paper EOD summary (once/day); partner snapshots (once/day) |
| Every 3600s (hourly) | `token_refresh`, `fyers_token_refresh`, `self_healing`, `cache_refresh`, `update_watchlist_prices` (no-op), `fyers_daily_topup` (close-gated), `prune_idempotency` | Groww/FYERS token checks; 3 self-healers; fundamentals per symbol; FYERS daily top-up; idempotency-key delete | refreshed tokens; healed/alerted data faults; fundamentals cache; `fyers_candles` D-tier; smaller `idempotency_keys` table |
| Every 6h (21600s) | `tijori_refresh` | `tijori_collector.collect_stale_symbols` | refreshed Tijori fundamentals for stale symbols |
| Daily (86400s, staggered; each also reruns once after every app restart) | `market_intelligence`, `research_engine` (14400s = 4h, not daily), `ml_retrain` (T+150), `xgb_cash_retrain` (T+1800), `retrain_xgb_daily` (T+3000) | scraped holdings/peers; unified research; 3 separate model retrains | institutional data; research verdicts; GBC + cash-XGB + F&O-XGB model files (the GBC retrain only succeeds on weekend/holiday runs — see ML section) |
| Weekly (604800s) | `auto_metadata` | Screener.in scrape | stock metadata refresh |
| Every 45 days (in-process timer) **and once after every app restart** | `cost_scraper` | `costs.update_cost_rates` → Groww charges page → `cost_notifications` | updated cost config + Telegram notification (DB notification row: none since 2026-07-31) |
| Market-open only | `record_pnl`, `auto_close_trades`, `cash_auto_trade` (market gate) | (see above) | live P&L/exit enforcement |
| After-close only | `fyers_daily_topup`, `tijori_daily_partners`, self-healing's backfill/top-up repairs | (see above) | end-of-day data completion |
| Event-driven | 19 of the 22 background threads (dashboard button / Telegram command / `/api/watchlist/add`) | varies (§3) | on-demand analysis/refresh/backfill |
| Boot-once | `fyers-boot-warmup`, `fyers-ws` (if enabled), `master-scheduler`, `telegram-commander`, `change-feed-watcher` | (see §3 startup order) | warmed FYERS cache; live WS (disabled); scheduler running; bot online message; file watcher running |

### Cross-cutting facts (for the maps)

- **External services + endpoints**: Telegram Bot API (`api.telegram.org/bot{token}/...` — sendMessage, getUpdates, answerCallbackQuery, getMe); FYERS (quotes, historical candles, WS — via `fyers_client`/`fyers_historical_backfill`/`fyers_ws_client`, rate-limited per CLAUDE.md op-rule 9); Groww (order placement, account balance, token refresh); Screener.in (scrape, `auto_metadata`, `market_intelligence` — self-rate-limited to 1 page/stock/day after being blocked at 6h×7 pages); Tijori (scrape, supply-chain/fundamentals); RSS/Google News (`world_news_collector`); internal loopback HTTP to `127.0.0.1:8000` (`/api/live-prices`, `/api/paper-trading/build-daily-snapshots-with-candles`) authenticated via `SERVICE_TOKEN` + `X-Requested-With` header (`scheduler.py:24-27`).
- **Env vars**: `DB_URL` (self_healing.py, direct psycopg2 connects), `FYER_PIN` (required for `fyers_token_refresh`, logs ERROR if missing), `_FORCE_BACKFILL` (transient, set/unset by `/api/watchlist/refresh-prices` around a no-op call).
- **config_settings keys read in this section** (key — where — LIVE value, 2026-09-27): `scheduler_interval_*` (31 keys, scheduler.py, all read via `_load_interval_overrides`) — 30 of the 31 tasks have a row (`tijori_daily_partners` has none; the 31st row is the orphan `collect_5min_candles`), and all equal code defaults except `auto_close_trades`=300 (see contradiction); `cash_auto_trade_enabled` — scheduler.py/telegram_commander.py — **true**; `fno_auto_trade_enabled` — scheduler.py — **false**; `paper_trading` — many — **true**; `telegram_enabled` — telegram_alerts.py — **true**; `telegram_cost_notifications` — cost_notifications.py — **true**; `telegram_bot_token`/`telegram_chat_id` — (secret, not recorded; both present since the bot is live); `idempotency.retention_hours` — scheduler.py — **48**; `tijori.refresh_interval_days` — tijori_collector — **7**; `fyers.ws_enabled` — fyers_ws_client.py — **false**; `fyers.boot_warmup_enabled`/`_timeout_seconds`/`_extra_pace_seconds`/`_token_wait_seconds` — fyers_boot_warmup.py — defaults true/150/0.3/45 — **VERIFIED 2026-09-28: `SELECT key FROM config_settings WHERE key LIKE 'fyers.boot%'` returns 0 rows, so the code defaults apply**; `tijori.last_partner_refresh`, `earnings.last_qrev.<symbol>`, `tijori.last_collected.<symbol>` — day/state markers, not operator-facing toggles.
- **DB tables read/written**: `config_settings` (r/w), `PnLSnapshot` (w, at most once per ~15s pass while the market is open AND `paper_trades.json` has OPEN trades — currently 0, so the newest row is 2026-09-22 09:32), `PaperTrade` (r, EOD summary — the only reader; 4 DB rows vs 26 JSON trades), `stocks`/`fyers_candles`/`stock_prices` (r, self-healing + cache_refresh + daily_summary candle stats), `idempotency_keys` (w, pruned), `cost_notifications` (r/w, self-provisioning table), `CandleTrainingMetadata` (r, via `log_xgb_training_event` and sanity_check.py).
- **Every timed/triggered execution**: see §2 task table and §12 timing map in full.
- **Rate limits & quotas**: FYERS 10 req/s, 200/min standard (600/min Prime), 100k/day, per CLAUDE.md op-rule 9 — enforced centrally in `fyers_client._request()`, not in this section's files directly, but `_boot_warmup_active()` gating exists specifically to protect that limiter from a 73-symbol burst. Telegram has no documented rate limit encountered in this code; `_polling_loop` self-limits via long-poll `timeout=30`.
- **Cost drivers**: `cache_refresh` (up to ~400 FYERS quote calls when cold, hourly, gated to run after boot warm-up), the 3 daily model retrains (25-31 min of CPU each), `market_intelligence`/`auto_metadata` scraping (rate-limited to avoid being blocked again).
- **Data flows**: watchlist symbol → `fyers_candles`/`stock_prices` (FYERS/collectors) → `bot.scan_watchlist`/`auto_analyzer` (predictions) → dashboard + `daily_summary` + Telegram alerts. Trade lifecycle: `bot.auto_trade`/`fno_trader.auto_trade_fno` → `paper_trades.json`/DB → `change_feed` SSE → open dashboards; → `telegram_alerts.alert_trade_executed/closed` → Telegram.
- **Failure modes**: `_boot_warmup_active()` fails OPEN (safe direction: never stuck paused); `self_healing._market_is_open()` fails CLOSED (safe direction: never backfills during a hallucinated "closed"); `_load_interval_overrides()` fails to `{}` (scheduler keeps running on compiled defaults); `telegram_commander` pause check fails open (bare except → loop continues unpaused) if `is_scheduler_paused` import itself breaks; `notify()`/`send_message()` never raise, by design.
- **Dead / legacy / retired code found in this section**: `_task_update_watchlist_prices` (scheduler.py, no-op since 2026-08-15, ~130 lines of dead commented code left in place); `auto_analyzer.start_auto_analyzer` + `supply_chain_collector.start_collector`/its init thread (fallback-only, dormant unless `start_scheduler()` itself throws); 6 of `telegram_alerts.py`'s 9 `alert_*` formatters (zero callers repo-wide) plus `alert_daily_summary` (transitively dead) and `send_scheduled_summary()`; `sanity_check.py` (broken import, `_task_collect_hourly_candles` no longer exists); stray `config_settings` row `scheduler_interval_collect_5min_candles` (orphaned, no matching task).
- **Contradictions found**: (1) `auto_close_trades` — code comment says "every 5s", live DB override makes it 300s (VERIFIED FROM DATABASE) — affects only the scheduler's `check_and_close_trades_on_loss` path; trailing-stop exits still run ~every 15s via `cash_auto_trade`; (2) `/api/scheduler/status` (app.py:8110-8125) imports `scheduler._task_stats`, which **does not exist anywhere in scheduler.py** (grep of tracked + untracked files confirms zero definitions; only app.py:8114/8118 reference it) — this endpoint always falls into its except branch, returns **HTTP 500** and reports `{"scheduler_running": false, "status": "error"}` even while the scheduler is healthy and running, and **nothing in index.html/JS calls this route** (dead route); (3) Telegram's `/autotrade` command calls `bot.auto_trade()` directly, unlike the scheduler's `_task_cash_auto_trade`, without checking `cash_auto_trade_enabled` OR market hours OR the boot-warm-up `skip_new_entries` gate — a user can trigger a real/paper trading cycle via Telegram regardless of that master toggle (VERIFIED: `bot.auto_trade` has no master-switch or market-hours gate of its own; see §6 FINDING); (4) `groww-commands.sh`'s printed cheat-sheet suggests `./stop-all.sh` + `./start-all.sh`, a different sequence from CLAUDE.md's mandated `./start-all.sh --stop && ./start-all.sh --dashboard-only`.
- **Open unknowns**: none remaining from the first pass — **RESOLVED 2026-09-28:** the `fyers.boot_warmup_*` keys have NO DB rows (code defaults true/150/0.3/45 apply); `bot.auto_trade()` has no `cash_auto_trade_enabled` master-switch and no market-hours gate (the internal gates that do apply are `_portfolio_reviewed`, `model.*_cash_enabled`, fail-closed position lookup, confidence floor), so the `/autotrade` Telegram bypass in finding (3) is a real bypass of both. `/api/self-healing` (`app.py:2279`) and `/api/events` (`app.py:7363`) are VERIFIED to exist as routes (their internal behaviour was not read line-by-line in this pass, only confirmed present).
- **Missed items surfaced by independent verification (2026-09-28, applied to this section):** (1) **Effective dispatch cadence is ~15s, not 5s** — every "5s" task is bounded by the 15s `time.sleep(15)` at `scheduler.py:1291`; a 1800s task with a 30-min daily window can occasionally miss its window. (2) **Restarts re-run every task** — `last_run` is in-memory, so `cost_scraper`, the 3 retrains, `market_intelligence`, `auto_metadata` etc. all rerun after every restart (the 2026-09-28 22:02 restart immediately re-ran the ~25-min GBC retrain); the 45-day/weekly/daily intervals only apply to a process that stays up that long, so frequent restarts multiply scraper traffic and retrain load. (3) **`/api/scheduler/status` is a dead route** — permanent HTTP 500, no UI caller. (4) **`_task_update_watchlist_prices` is still spawned** by `/api/watchlist/refresh-prices` (app.py:1778-1790) as a thread that does nothing. (5) **`google_auth.py` (untracked) has side effects** — it sends a Telegram message on every Google sign-in and creates `users` rows; earlier passes omitted it. (6) **`SPICEJET` is a ghost symbol** that `self_healing` can never heal (0 `fyers_candles` rows ever, no `master_ticker_table` row). (7) **Weekday GBC retrains fail for every symbol** (trailing-24h `days=1` branch, ≤75 bars < 100-row minimum) — see the ML section; and GBC is structurally unable to model cheap stocks. (8) **`pnl_snapshots` has no rows since 2026-09-22** — snapshots are written only while a JSON trade is OPEN (0 now), so a P&L-chart gap is expected. (9) **`paper_trades` DB (4 rows) vs `paper_trades.json` (26 records)** — the EOD Telegram summary, the DB table's only reader, under-reports. (10) **No `fyers_candles` for Mon 2026-09-28** (cause unverified: holiday vs collection outage). (11) **Undeclared dependencies**: `xgboost` (cash + F&O) and `beautifulsoup4` are not in `requirements.txt`. (12) **Money-path schema drift** (see Database section): the `idempotency_keys` guard is INERT (missing `content_type` column → every claim falls open) and every `trade_log` INSERT fails silently (schema drift).


## Research, News, Fundamentals & External Data Collectors

Overview: This section covers the research/news/fundamentals subsystem — news ingestion + NLP
sentiment (`news_sentiment.py`, `enhanced_nlp.py`, `world_news_collector.py`), company intelligence
orchestration (`market_intelligence.py`, `research_engine.py`, `deep_analysis.py`), Tijori financial-data
scraping (`tijori_collector.py` + backfill/migration scripts), supply-chain graph
(`supply_chain_collector.py`), fundamentals/peers/FII/commodities (`fundamental_analysis.py`,
`peer_analyzer.py`, `fii_tracker.py`, `commodity_tracker.py`), portfolio analytics
(`portfolio_analyzer.py`), stock search/thesis tooling (`stock_search.py`, `stock_thesis.py`,
`thesis_manager.py`, `thesis_analyzer.py`), watchlist lifecycle (`auto_metadata.py`, `symbol_purge.py`),
and the brokerage-cost scraper/updater (`cost_scraper.py`, `cost_updater.py`). Read-only research pass;
no repo files modified. There is no dedicated "geopolitical collector" file — "geopolitical" is a
category/tag used inside `world_news_collector.py` (RSS category) and `commodity_tracker.py`
(`get_geopolitical_context`, `collect_geopolitical_news` — documented in the commodity section below).

---

### `news_sentiment.py` — per-symbol news sentiment engine

| Field | Detail |
|---|---|
| Where | `news_sentiment.py` (997 lines) |
| What / Why | Fetches financial news for one stock symbol from 6 sources, scores sentiment (bullish/bearish/neutral, -1..1), persists articles, returns a `NewsSentiment` for use in predictions/UI. |
| Used by (callers) | `scheduler._task_news_prefetch` (warms cache for `config.WATCHLIST` every 600s); `bot.py` prediction pipeline (news component — see Cross-cutting); dashboard endpoints in `app.py` (news panel) — VERIFIED FROM CODE at call sites in scheduler.py:108-116; app.py callers not individually re-verified in this pass, INFERENCE from grep hits only. |
| Calls | `enhanced_nlp.score_text` (FinBERT/keyword fallback), `TextBlob`, `feedparser`, `requests`, `db_manager.get_db`/`get_configs`, `commodity_tracker.get_geopolitical_context` (from `_fetch_x_posts` and `get_geopolitical_news`). |
| When | Live: on-demand via `get_news_sentiment(symbol)`, cached in-process `_cache` dict keyed by symbol, TTL from config `news.cache_ttl_seconds` (default `CACHE_TTL=600`s, `news_sentiment.py:333`); also scheduler `news_prefetch` every 600s. Replay: `as_of` param exists for backtesting (reads DB only, never live sources — `news_sentiment.py:749-753`). |
| Inputs | `symbol` (str), `force_refresh` (bool), `as_of` (datetime, optional replay ceiling). |
| Outputs / side effects | Returns `NewsSentiment` dataclass; writes new articles to `news_articles` table (`_persist_articles`, news_sentiment.py:46-86); in-memory cache. |
| DB tables | Read/write `news_articles` (via `db_manager.NewsArticle`). Also reads `config_settings` via `get_configs`. |
| Config / env | `NEWS_API_KEY` (env, via `config.py`) — VERIFIED FROM CODE news_sentiment.py:25. `config_settings` keys: `news.cache_ttl_seconds`, `news.source.google`, `news.source.newsapi`, `news.source.et_rss`, `news.source.moneycontrol`, `news.source.extra_rss`, `news.source.x_posts` (all default "true"/on if unset except cache_ttl default 600 via literal fallback) — news_sentiment.py:337-341, 380-382. |
| External services | (1) Google News RSS — `https://news.google.com/rss/search?q=...&hl=en-IN&gl=IN&ceid=IN:en`, no key, free (news_sentiment.py:390). (2) NewsAPI.org — `https://newsapi.org/v2/everything`, needs `NEWS_API_KEY` (free tier per module docstring: "100 free req/day", EXTERNAL VERIFICATION REQUIRED for current pricing) (news_sentiment.py:426). (3) Economic Times RSS — `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` (news_sentiment.py:470). (4) MoneyControl RSS — `https://www.moneycontrol.com/rss/marketreports.xml` (news_sentiment.py:502). (5) Extra RSS: LiveMint `https://www.livemint.com/rss/markets`, NDTV Profit `https://feeds.feedburner.com/ndtvprofit-latest`, Business Standard `https://www.business-standard.com/rss/markets-106.rss` (news_sentiment.py:532-536). (6) "X posts" — NOT a real X/Twitter API; it's Google News RSS searches with `site:x.com` filters (news_sentiment.py:584-646) — mislabeled, no Twitter/X auth used. |
| Rate limits / cost | NewsAPI circuit breaker: `_NEWSAPI_FAIL_LIMIT=3` consecutive 429s → `_newsapi_disabled_until = now + _NEWSAPI_COOLDOWN(3600s)`, logs "NewsAPI rate-limited N times — disabled for 1 hour" (news_sentiment.py:148-152, 437-442) — matches CLAUDE.md's own example verbatim. Other sources (Google/ET/MoneyControl/extra RSS) have no explicit rate-limit/backoff logic beyond a per-request 10-12s timeout and blanket try/except. 6 sources fetched concurrently via `ThreadPoolExecutor(max_workers=6)` per symbol (news_sentiment.py:762-787) — satisfies engineering standard #3. |
| Caching | In-process dict `_cache` (symbol → (ts, NewsSentiment)), TTL configurable; DB (`news_articles`) is the durable de-duped store — dedup key `title_hash` = md5 of normalized lowercase title (first 80 chars). |
| Failure behaviour | Every fetcher wrapped in try/except returning `[]`/logging warning — fail-open (missing source ≠ error, just fewer articles). DB session failures caught and logged, function returns empty list/no persist. |
| Security | None of the fetched HTML/RSS text is escaped here — this module only returns dicts; XSS risk depends on the frontend renderer (see Cross-cutting / XSS flag). |
| Performance | Bulk `_persist_articles` preloads existing hashes with one `IN (...)` query (news_sentiment.py:53-59) — good pattern, no N+1. |
| Blast radius | Feeds `bot.get_prediction()`'s news-sentiment weight (see Cross-cutting) and the dashboard news panel; breaking this silently degrades prediction quality without raising errors (fail-open). |
| Status | ACTIVE |

### `_score_articles` / `_classify_sentiment` / `_parse_published_date` — helpers

| name | file:line | purpose | callers | status |
|---|---|---|---|---|
| `_score_articles` | news_sentiment.py:812 | Shared scorer for live path AND `as_of` replay path (recency-weighted average, confidence = agreement×coverage×|score|) — explicitly written once so backtests grade the same formula as live trading | `get_news_sentiment` | ACTIVE |
| `_classify_sentiment` | news_sentiment.py:286 | score>0.15→BULLISH, <-0.15→BEARISH, else NEUTRAL | multiple | ACTIVE |
| `get_market_sentiment` | news_sentiment.py:870 | Overall Nifty/Sensex sentiment from 15 Google News articles, cached under `__MARKET__` key | UNKNOWN (not traced to a caller in this pass) | ACTIVE |
| `get_geopolitical_news(symbol)` | news_sentiment.py:897 | For symbols with a commodity dependency (via `commodity_tracker.get_geopolitical_context`), fetches geopolitical Google-News + "X" articles; cached under `__GEO_{symbol}__` | UNKNOWN caller (dashboard geopolitical panel, inferred) | ACTIVE |

### `enhanced_nlp.py` — sentiment scoring backend

| Field | Detail |
|---|---|
| Where | `enhanced_nlp.py` (282 lines) |
| What / Why | Provides `score_text()` used by both `news_sentiment.py` and `world_news_collector.py`. Tries FinBERT (`ProsusAI/finbert` via HuggingFace `transformers`) at import time; falls back to an enhanced keyword lexicon with negation/intensifier handling and sentence-level scoring. |
| Used by (callers) | `news_sentiment._score_text` (news_sentiment.py:253), `world_news_collector._score_text` (indirectly via `news_sentiment._score_text` fallback, world_news_collector.py:134). |
| Calls | `transformers.pipeline("sentiment-analysis", model="ProsusAI/finbert")` if importable. |
| When | Loaded once at process import (module-level try/except, enhanced_nlp.py:23-36); every call to `score_text`/`finbert_score`/`batch_score` thereafter uses whichever path succeeded. |
| Inputs | Raw text string. |
| Outputs | Float -1..1 (`score_text`), or dict via `score_with_details` (score/label/confidence/model). |
| DB tables | None. |
| Config / env | None — model choice is load-time capability detection only, not a config toggle. |
| External services | HuggingFace model download for `ProsusAI/finbert` (~2GB per docstring) — only if `transformers`/`torch` installed; **VERIFIED FROM CODE this is optional** (enhanced_nlp.py:8-9, try/except ImportError). Not confirmed installed in this env — UNKNOWN whether `HAS_FINBERT` is True in production; would require checking installed packages (out of scope / not verified). |
| Rate limits / cost | None (local inference or local keyword model; no network call per scoring request). |
| Failure behaviour | FinBERT exceptions fall back to keyword model per-call (`finbert_score`/`batch_score` try/except). |
| Performance | Keyword path is O(len(text)) regex/sentence split; FinBERT path truncates to 512 chars/tokens. |
| Blast radius | Silently changes sentiment scoring precision app-wide if FinBERT availability changes (e.g. a fresh venv without `torch` silently downgrades to keyword scoring — no alert). |
| Status | ACTIVE (dual-mode) |

### `world_news_collector.py` — global macro/sector/geopolitical news collector

| Field | Detail |
|---|---|
| Where | `world_news_collector.py` (474 lines) |
| What / Why | Collects market-wide (not per-symbol) news across 5 categories: macro, sector, geopolitical, market, global. Stores into `global_news` table, independent of any one stock. |
| Used by (callers) | `scheduler._task_world_news` (scheduler.py:743-749), every 900s (15 min), initial_delay 65 — matches module docstring "Runs every 15 minutes via scheduler." |
| Calls | `feedparser`, `requests`, `news_sentiment._score_text` (fallback to raw TextBlob if that import fails, world_news_collector.py:131-140), `db_manager.GlobalNews`. |
| When | Scheduler task `world_news` every 900s. |
| Inputs | None (fixed feed/query lists). |
| Outputs / side effects | Inserts rows into `global_news`; returns summary dict (new/rss/google counts, elapsed). |
| DB tables | Read+write `global_news` (dedup via `title_hash`, one preloading `_known_hashes()` query then per-article insert — note: inserts are still one-row-at-a-time inside a loop with individual try/except+rollback per failure, `world_news_collector.py:217-235`; not a read-N+1 but is a write-N — acceptable at these volumes (≤ ~30/feed × 15 feeds + ≤10/query × 23 queries ≈ well under 1000/run)). |
| Config / env | None (no config_settings keys; source lists and categories are hardcoded module-level constants `RSS_FEEDS`, `GOOGLE_NEWS_QUERIES`). |
| External services — RSS_FEEDS (15 feeds — `RSS_FEEDS` list, `world_news_collector.py:32`; name → url → category) | Economic Times Markets `.../markets/rssfeeds/1977021501.cms` (market); Economic Times Economy `.../news/economy/rssfeeds/1373380680.cms` (macro); LiveMint Markets `https://www.livemint.com/rss/markets` (market); LiveMint Economy `https://www.livemint.com/rss/economy` (macro); MoneyControl Markets `https://www.moneycontrol.com/rss/marketreports.xml` (market); MoneyControl Business `https://www.moneycontrol.com/rss/business.xml` (macro); NDTV Profit `https://feeds.feedburner.com/ndtvprofit-latest` (market); Business Standard Markets `https://www.business-standard.com/rss/markets-106.rss` (market); Business Standard Economy `https://www.business-standard.com/rss/economy-102.rss` (macro); Reuters Business `https://feeds.reuters.com/reuters/businessNews` (global); Reuters World `https://feeds.reuters.com/Reuters/worldNews` (geopolitical); CNBC Top News `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114` (global); CNBC World `...id=100727362` (geopolitical); MarketWatch Top Stories `https://feeds.marketwatch.com/marketwatch/topstories/` (global); Bloomberg Markets `https://feeds.bloomberg.com/markets/news.rss` (global). |
| External services — GOOGLE_NEWS_QUERIES (23 targeted Google-News RSS searches — `GOOGLE_NEWS_QUERIES` list, `world_news_collector.py:54`) | RBI monetary policy; India GDP/inflation; FII/DII flows; India budget/fiscal; rupee/forex; Fed rate decision; US jobs report; China PMI; crude oil OPEC; gold price; India-China border; Russia-Ukraine; US-China trade war; Middle East conflict; Indian banking NPA; India IT sector; India pharma; India auto/EV; India real estate; India FMCG; India telecom 5G; Indian IPO; Nifty/Sensex technical — each tagged with category + default tags (world_news_collector.py:54-85), fetched via `https://news.google.com/rss/search?q=...` with `time.sleep(0.5)` between queries (world_news_collector.py:348-349) as the only inter-request pacing/backoff. |
| Rate limits / cost | No API key needed for any of these (all RSS/Google News scraping). No circuit breaker / disabling logic (unlike `news_sentiment.py`'s NewsAPI breaker) — failures per-feed are caught individually and logged at debug level, collection continues. 0.5s sleep between the 23 Google queries is the only throttle. |
| Caching | None beyond DB dedup by `title_hash`; no in-memory cache (unlike news_sentiment.py). |
| Failure behaviour | Fail-open per feed/query (try/except → skip, continue others). |
| Security | Article `summary` HTML-stripped via regex `<[^>]+>` (world_news_collector.py:283, 328) before storage — reduces but does not guarantee full XSS-safety (regex strip, not a real HTML sanitizer); `title` is stored raw, un-sanitized. |
| Performance | Full pass fetches 15 RSS feeds (≤30 entries each) + 23 Google queries (≤10 entries each, with 0.5s delay) ⇒ up to ~11.5s just in Google-query sleeps, plus network time for 38 HTTP requests, serially (no ThreadPoolExecutor here, unlike news_sentiment.py) — MEASURED: not measured directly, INFERENCE from code structure that this task takes tens of seconds per run; runs on the 900s scheduler tick so unlikely to overlap itself under normal conditions but no explicit overlap guard exists. |
| Blast radius | Feeds `global_news` table read by `get_recent_news`/`get_news_stats` (world_news_collector.py:392-473) — used by UNKNOWN dashboard panel(s) (not traced to app.py endpoint in this pass). |
| Status | ACTIVE |

### `market_intelligence.py` — institutional holdings, peer ratios (retired), volume seasonality

| Field | Detail |
|---|---|
| Where | `market_intelligence.py` (920 lines) |
| What / Why | Three sub-engines: (1) shareholding-pattern scraper (FII/DII/promoter trend), (2) peer-ratio comparison (**RETIRED 2026-09-12**, see below), (3) volume/return seasonality analysis from local `stock_prices`. `collect_all_intelligence(symbol)` runs all three; `collect_all_watchlist()` is the scheduler entry point. |
| Used by (callers) | `scheduler._task_market_intelligence` → `mi.collect_all_watchlist()`, every 86400s (24h), initial_delay 130 (scheduler.py:769-776, 1354). |
| Calls | `requests` (direct HTML scrape, not via a shared client), `psycopg2` directly (not through `db_manager`'s SQLAlchemy session — a second, separate DB-access style in this module), `fundamental_analysis._get_competitors`/`_get_sector_display` (for the retired peer step). |
| When | Daily scheduler pass, one page per stock, `delay` seconds between stocks (config `intel.request_delay_seconds`, default 5.0s, market_intelligence.py:899) — stops the whole run on first Screener refusal (403/429/503) so it doesn't hammer the rest (market_intelligence.py:911-914). |
| Inputs | `symbol` (str) for single-stock functions; watchlist scope pulled from `stocks WHERE is_active=true` (market_intelligence.py:891, explicitly NOT the legacy `stock_prices` table — comment notes newly-added stocks were missed and removed ones lingered when it used to query `stock_prices`). |
| Outputs / side effects | Writes `shareholding_patterns` (upsert by symbol+quarter_date) and `peer_comparisons` (upsert by symbol) tables; returns dict summaries. |
| DB tables | Read/write `shareholding_patterns`; read/write `peer_comparisons`; read `stock_prices` (for seasonality) and `stocks` (watchlist membership). |
| Config / env | `DB_URL` (env, direct `psycopg2.connect`); `config_settings` key `intel.request_delay_seconds` (default 5.0). |
| External services | Screener.in — `https://www.screener.in/company/{symbol}/consolidated/` (falls back to `.../company/{symbol}/` on 404), scraped via raw regex/HTML parsing (NOT BeautifulSoup) for both shareholding (`scrape_shareholding`, market_intelligence.py:79) and the retired peer ratios (`_scrape_peer_ratios`, line 402). No API key — plain HTML scrape with a browser `User-Agent`. |
| Rate limits / cost | No formal rate limiter; politeness enforced only via the per-stock `delay` and "stop run on first refusal" behaviour, added **after an incident**: comment at market_intelligence.py:850-856 records Screener.in blocking the host on 2026-09-12 after 67 stocks × 7 pages every 6h with no delay, from 3 different scrapers hitting the same page. Fix: one page/stock, `intel.request_delay_seconds` pacing, `_refreshed_today()` skip-if-already-done, stop-on-first-403/429/503. |
| Caching | `_refreshed_today()` (market_intelligence.py:866) — quarterly shareholding data only needs a fresh scrape once/day; skips symbols whose `shareholding_patterns.updated_at` is already today (IST). |
| Failure behaviour | `scrape_shareholding` returns `{"refused": True}` distinctly from `[]` (no data) on 403/429/503 so the batch loop can detect "host is blocking us" and stop early (market_intelligence.py:171-178) — a deliberate fail-fast, not fail-open, specifically to protect against repeating the 2026-09-12 incident. |
| Security | Regex-based HTML parsing of untrusted third-party HTML (Screener.in) — fragile to markup changes but not itself an XSS vector since output is numeric/text fields stored server-side, not rendered raw. |
| **CONTRADICTION / DEAD CODE** | `_PEER_RATIOS_RETIRED = True` (market_intelligence.py:399) makes `_scrape_peer_ratios()` **immediately return `{}`** for every symbol (line 407-408). `collect_peer_comparison()` (line 445) and therefore `store_peer_comparison()`/the `peer_comparisons` table are consequently **no-ops in production** — `collect_all_intelligence` always logs `{"peers": {"count": 0}}`. The retirement comment (market_intelligence.py:391-398) says the dashboard's peer table is now served from the daily Tijori snapshot instead (`tijori_collector.get_supply_chain_intel`'s `peers` block / `get_fundamentals`'s peer-derived `industry_pe`). **VERIFIED FROM CODE**: `peer_comparisons` table is effectively dead/frozen at whatever was scraped before 2026-09-12 unless something else still writes to it (not found — VERIFIED: `peer_comparisons` `max(collected_at)` = 2026-09-12 17:35; see `peer_analyzer.py` below, which is a separate, ORPHANED peer module with no callers and whose tables do not exist). |
| Blast radius | If `peer_comparisons`/`get_peer_comparison()` is read anywhere in the UI expecting live data, it is silently stale since 2026-09-12 — a "missing data must be visible" risk if any panel binds to it (engineering standard #7); not traced to a specific UI panel in this pass — UNKNOWN. |
| Status | Shareholding + seasonality: ACTIVE. Peer-ratio scraping: **RETIRED** (dead code path, guarded by `_PEER_RATIOS_RETIRED=True`, kept for reference per module comment). |

### `tijori_collector.py` — supply-chain & fundamentals scraper (Tijori Finance)

| Field | Detail |
|---|---|
| Where | `tijori_collector.py` (1666 lines) — the largest and most heavily engineered collector in this pass; extensive inline incident-history comments. |
| What / Why | For every tracked stock: resolves a Tijori Finance URL slug from the company name, scrapes the company page for suppliers/customers/competitors (→ `company_connections`), ratios/peers/returns/forensics/market-share/corporate-actions (→ `company_external_data`, one row per (symbol, data_type, day) — append-only history). Also resolves partner (supplier/customer) names to NSE symbols and fetches THEIR pages too, so `get_supply_chain_intel()` can show partner health. This is the replacement data source for peer ratios after Screener.in peer-scraping was retired (see market_intelligence.py above) — `get_fundamentals()` docstring explicitly says so (tijori_collector.py:1221-1226). |
| Used by (callers) | `scheduler._task_tijori_refresh` → `collect_stale_symbols()` every 21600s (6h), initial_delay 180 (scheduler.py:568-575, 1384). `scheduler._task_tijori_daily_partners` → `collect_missing_partner_snapshots(limit=10000)` once/day post-close, run on its own daemon thread (not the scheduler pool) because the pass takes ~45 min at 6s pacing (scheduler.py:578-624, registered every 1800s but self-gates to once per IST day via `config_settings["tijori.last_partner_refresh"]`). `tijori_backfill.py` (one-time/manual full backfill script). `auto_metadata`/onboarding flow calls `onboard_symbol(symbol)` when a new stock is added (per task description; not independently re-verified against auto_metadata.py in this row — see auto_metadata section). `fundamental_analysis.py` and `research_engine.py` read `get_fundamentals()` / `get_supply_chain_intel()` (see their sections). |
| Calls | `requests` + `BeautifulSoup` (real HTML parser, unlike market_intelligence.py's regex approach; **`beautifulsoup4` is NOT declared in `requirements.txt`** — undeclared dependency, also imported by `auto_metadata`, `cost_scraper`, `costs`); `db_manager` (`get_db`, `ExternalSlugMap`, `CompanyConnection`, `CompanyExternalData`, `get_config`/`set_config`/`get_configs_prefix`); `bot._get_groww().get_all_instruments()` (for local NSE-symbol resolution, no network to Tijori). |
| When | See scheduler tasks above. `onboard_symbol()` is the synchronous new-stock-add path (company page + partner resolve + partner snapshots, scoped to just that symbol, `tijori.onboard_partner_limit` default 20). |
| Inputs | `symbol`; internal config-driven limits (all below). |
| Outputs / side effects | `company_external_data` (7 snapshot types: `company_info`, `ratios`, `peers`, `returns`, `forensics`, `market_share`, `corporate_actions`, plus an 8th audit-only type `collection_attempt` recording failed/gated fetches so they aren't retried every run); `company_connections` (supplier/customer/competitor edges, append-only with `is_active` soft-delete — "Disappeared → mark is_active=False (never delete)", tijori_collector.py:450); `external_slug_map` (company-name → Tijori-slug → NSE-symbol cache, verified against the page's embedded `company_details_data` JSON, not trusted on name-match alone). |
| DB tables | Read/write `company_external_data`, `company_connections`, `external_slug_map`; reads `stock_prices` (universe), `stocks` (fallback universe), `config_settings`. |
| Config / env (all keys, `_CONFIG_DEFAULTS` tijori_collector.py:39-58, seeded via `seed_tijori_config()`) | `tijori.enabled` (default "true" — master kill switch, checked at top of every entry point, fails closed to "skipped" not silently); `tijori.base_url` (`https://www.tijorifinance.com`); `tijori.request_delay_seconds` (2); `tijori.timeout_seconds` (15); `tijori.refresh_interval_days` (7 — how stale before `collect_stale_symbols` re-fetches a principal); `tijori.max_symbols_per_run` (10); `tijori.max_slug_resolutions_per_run` (15); `tijori.block_below_coverage_pct` (95 — gates analysis sections while coverage below this AND collection active, consumed elsewhere e.g. research_engine/UI, not in this file); `tijori.local_index_ttl_seconds` (3600); `tijori.max_partner_snapshots_per_run` (12); `tijori.partner_retry_days` (14, legacy path only per its own description); `tijori.max_partner_discovery_per_run` (15 — rotating quota for *unresolved* partners, since discovery costs ~5x a resolved-slug refresh); `tijori.onboard_partner_limit` (20); `tijori.user_agent` (Chrome UA string). Freshness markers: `tijori.last_collected.{symbol}`, `tijori.last_partner_refresh`, `tijori.onboarded.{symbol}`. |
| External services | Tijori Finance (`tijorifinance.com`) — no API key, plain scrape of embedded `<script id="...">` JSON blocks (`company_details_data`, `ratios_table`, `peers_table_data`, `price_returns`, `ms-charts`, `corporate_actions`) plus server-rendered HTML sections (`#suppliers`, `#customers`) via BeautifulSoup. **Important verified quirk**: Tijori returns HTTP 200 for ANY slug including invented/nonexistent ones — `_page_is_company()` (line 721) treats only the presence of `company_details_data` JSON (and matching NSE symbol) as proof of a real page; status code alone is not trustworthy (tijori_collector.py:726-731, "verified live against several invented slugs"). |
| Rate limits / cost | Custom token-less pacing: `_sleep_politely()` waits only the remaining time since `_last_request_at` (a shared `threading.Lock`-guarded monotonic timestamp) rather than unconditional sleeps, to avoid double-counting when nested calls (slug resolution × connection resolution) each want a delay (tijori_collector.py:90-127). Discovery (unresolved-partner slug search, ~5 requests each) is explicitly separated from refresh (1 request, cached slug) and capped by its own quota (`max_partner_discovery_per_run`) specifically because a full daily re-search of ~500 pending partners was judged too costly (tijori_collector.py:857-868). |
| Caching | `external_slug_map` (permanent slug cache, failed resolutions not retried for 30 days — `resolve_slug`, line 217-220); in-process `_LOCAL_INDEX` (company-name→NSE-symbol built from 3 merged local sources: scraped `company_info` payloads, `external_slug_map`, and Groww's NSE CASH instrument master as the authoritative overwrite — `_build_local_symbol_index`, line 627-680), TTL `tijori.local_index_ttl_seconds`; `company_external_data` upserts are unique per (symbol, data_type, day) via a **partial unique index** `uq_ext_symbol_type_day` (excludes `collection_attempt` rows) added by `migrate_tijori_daily_snapshot.py` — this is what makes same-day re-collection idempotent instead of duplicating rows. |
| Failure behaviour | Fail-open at the per-block level ("Every parser is independent... a failed scrape NEVER deletes previously stored data", module docstring); `collect_for_symbol` never raises, catches everything into `summary["error"]`; a page that resolves but yields no usable "returns" snapshot is recorded via `_mark_collection_attempt()` so it isn't retried forever (tijori_collector.py:879-887); stale slugs self-heal by re-resolving and overwriting (`_fetch_partner_html`, line 745-777) rather than retrying a dead URL forever. |
| Security | HTML parsed with BeautifulSoup (safer than raw regex); JSON payloads stored as `payload_json` text and re-`json.loads`'d on read — no `eval`. No obvious XSS surface found in this file (data is numeric ratios/company names, not rendered as raw HTML anywhere read in this pass). |
| Performance | `get_supply_chain_intel()` was rewritten to use `_load_snapshots_bulk()` — one batched query (filtered to only the 5 data_types actually consumed) for the target symbol + ALL its resolved partners, replacing "3 queries per partner" (tijori_collector.py:1331-1359, 1411-1422) — this is the exact "`get_supply_chain_intel` went from 151 queries to 3" example cited verbatim in CLAUDE.md engineering standard #1. `collect_stale_symbols` and `get_fundamentals`-adjacent code batch config reads via `get_configs_prefix("tijori.last_collected.")` instead of per-symbol `get_config` (tijori_collector.py:1165-1171) — also matches standard #8's "never call get_config in a loop." |
| Blast radius | `get_fundamentals()` is the **single source** for both the stock panel (`fundamental_analysis.py`) and Research engine's Fundamental dimension (tijori_collector.py:1221-1226, explicitly "replacing the retired Screener ratio scrapes") — if Tijori collection stops or is disabled, both of those consumers silently degrade to `None`/stale data. `get_supply_chain_intel()` feeds `deep_analysis.py` and the dashboard supply-chain panel. |
| Status | ACTIVE (all three sub-flows: principal collection, partner discovery/refresh, connection resolution) |

### Tijori auxiliary scripts

| name | file | purpose | callers | status |
|---|---|---|---|---|
| `tijori_backfill.py` | 63 lines | One-time/manual full backfill: loops `collect_stale_symbols(max_symbols=15)` until no stale symbols remain, then 3 extra `resolve_pending_connections` passes. Sets `config_settings["tijori.backfill_status"]` to running/complete/interrupted. | Manual: `.venv/bin/python tijori_backfill.py` (per its own docstring) | MANUAL / TEST-ONLY (not scheduler-invoked) |
| `migrate_tijori_daily_snapshot.py` | 93 lines | One-time DB migration: creates the partial unique index `uq_ext_symbol_type_day` on `company_external_data(symbol, data_type, scraped_at::date) WHERE data_type <> 'collection_attempt'` via `CREATE INDEX CONCURRENTLY`, with a pre-check refusing to build if duplicate (symbol,type,day) groups already exist, and a post-check verifying `pg_index.indisvalid`. | Manual, run once before enabling daily partner refresh (per docstring) | MANUAL — migration applied: the index is relied upon by `_store_snapshots` in tijori_collector.py, and **VERIFIED IN DB (2026-09-28, `pg_index`/`pg_class` join): `uq_ext_symbol_type_day` is present on `company_external_data` with `indisvalid = t`** (resolves the earlier open unknown). |

### `supply_chain_collector.py` — commodity price + disruption-news heatmap collector

| Field | Detail |
|---|---|
| Where | `supply_chain_collector.py` (379 lines) |
| What / Why | Distinct from `tijori_collector.py` despite the similar name: this tracks macro **commodities** (oil, steel, gold, aluminium, zinc, coal, USD/INR) and geopolitical **disruption events** per commodity/region, not per-company supply chains. Feeds a heatmap UI that reads only from Postgres (module docstring: "The heatmap API just reads from Postgres — no live fetches at request time"). |
| Used by (callers) | `scheduler._task_supply_chain` → `collect_once()` every 900s (15 min), initial_delay 75 (scheduler.py:119-125, 1341). Manual trigger: `POST /api/supply-chain/refresh` (app.py:1966-1977, spawns a background thread). Fallback boot path: `app.py:8183-8189` starts `supply_chain_collector.start_collector(interval_seconds=900)` (its own internal `while True: sleep` daemon-thread loop, `supply_chain_collector.py:353-379`) **only if** `scheduler.start_scheduler()` itself fails to start — under normal operation the scheduler's `_task_supply_chain` is the sole driver and `start_collector`'s loop is unused redundant code. |
| Calls | `commodity_tracker.fetch_commodity_price(ticker)` (delegates all yfinance access — "single source of truth", supply_chain_collector.py:128-139), `commodity_tracker.COMMODITY_SUPPLY_CHAIN` (disruption metadata used to auto-generate watch queries), `news_sentiment._parse_feed`/`_score_text`/`_is_recent` (reused, not reimplemented). |
| When | Every 900s via scheduler; ticker list and disruption watch entries are static/derived at import, not configurable via `config_settings` (no config keys found in this file). |
| Inputs | None (fixed `COMMODITY_TICKERS` dict, `COMMODITY_SUPPLY_CHAIN` from commodity_tracker). |
| Outputs / side effects | Upserts `commodity_snapshots` (one row per commodity, tracks `prev_price`/`prev_trend` for change detection) and `disruption_events` (one row per commodity+region, tracks `prev_severity`/`prev_description`). |
| DB tables | Read+write `commodity_snapshots`, `disruption_events`. Preloads all `CommoditySnapshot` rows in ONE query before the loop (supply_chain_collector.py:241-245, explicit comment citing the N+1 pattern it replaced) — engineering standard #1 compliant. `DisruptionEvent` lookups, however, are still one `.filter_by(...).first()` **per disruption entry inside the loop** (line 305-307) — a smaller-scale N+1 (bounded by ~7 commodities × a handful of disruption entries each, so low absolute cost, but not batched like the snapshot preload). |
| External services | yfinance (via `commodity_tracker.fetch_commodity_price`) for `CL=F` (Crude Oil), `TIO=F` (Iron Ore/Steel), `GC=F` (Gold), `ALI=F` (Aluminium), `ZNC=F` (Zinc/Base Metals), `BTU` (Coal), `USDINR=X` (USD/INR) (supply_chain_collector.py:23-31). Google News RSS for disruption headlines, same `news.google.com/rss/search` pattern as other collectors, per-disruption auto-generated queries (`_auto_queries`, capped at 3 queries/disruption, 6 headlines/query, supply_chain_collector.py:95-116, 142-182). |
| Rate limits / cost | No explicit rate limiter/backoff; relies on yfinance's own behaviour and Google News' general tolerance of scraping; each pass = 7 commodity price fetches + up to (disruptions × 3) Google News queries. No sleep/delay between requests within a pass (unlike tijori_collector's `_sleep_politely` or world_news_collector's 0.5s). |
| Caching | `_disruption_watch_cache` (module-global, built once from `COMMODITY_SUPPLY_CHAIN` and reused — never rebuilt unless process restarts, so a change to `COMMODITY_SUPPLY_CHAIN` at runtime would not be picked up without a restart — INFERENCE). Severity/description/timestamp only updated when actually changed (avoids needless `updated_at` churn, supply_chain_collector.py:259-267, 314-330) — good practice for "last checked" vs "last changed" UI distinction. |
| Failure behaviour | Per-commodity try/except with `session.rollback()` on failure, continues to next commodity (fail-open, one bad commodity doesn't kill the pass). |
| Severity scoring | `_score_severity()` (line 185-224): additive score from news volume (0-3) + sentiment negativity (0-3) + 1-month price move magnitude (0-3) → critical(≥7)/high(≥5)/medium(≥3)/low. Heuristic, not externally calibrated — INFERENCE-based thresholds hardcoded in code, not config. |
| Blast radius | Feeds the supply-chain/commodity heatmap UI; also indirectly referenced by `news_sentiment.get_geopolitical_news`/`commodity_tracker.get_geopolitical_context` for per-symbol geopolitical news (shared `COMMODITY_SUPPLY_CHAIN` data structure — see commodity_tracker.py section, not yet read in this pass). |
| Status | ACTIVE (scheduler-driven); `start_collector`/`_collector_loop` own-thread path is DORMANT/fallback-only under normal boot. |

### `research_engine.py` — unified multi-dimensional research/Alpha-score engine

| Field | Detail |
|---|---|
| Where | `research_engine.py` (1918 lines) |
| What / Why | One algorithm applied identically to every tracked stock, producing a 0-100 "Alpha Score" from 5 weighted dimensions (Technical 25/35/15/30% depending on regime, Fundamental, Institutional, Sentiment, Risk — see weights below), a Verdict (STRONG_BUY..SELL), Conviction (0-100, based on inter-dimension agreement), catalysts, risk/reward levels, and long-term (5y) structure. Explicitly **display/leaderboard only** — see Blast radius. |
| Used by (callers) | `scheduler._task_research_engine` → `generate_research_all()` every 14400s (4h), initial_delay 140 (scheduler.py:788-794, 1355). Dashboard endpoints: `GET /api/research/<symbol>` (serves cached or generates live), `POST /api/research/<symbol>/refresh`, `GET /api/research/leaderboard`, `POST /api/research/all` (app.py:1708-1771). **VERIFIED FROM CODE**: grep across `bot.py`/`fno_trader.py` finds NO caller of `generate_research`/`get_cached_report` — the Alpha Score is **not** part of `bot.get_prediction()`'s trading decision (see Cross-cutting: prediction weights are ML/Trend/News/Context only, no research_engine input). |
| Calls | `tijori_collector.get_fundamentals(symbol)` (fundamentals — replaces retired Screener scrape, research_engine.py:1648-1661), `db_manager.CandleDatabase.get_fyers_daily` (365d daily OHLCV), direct `psycopg2` reads of `stock_prices` (5y weekly) and `shareholding_patterns`, `db_manager.NewsArticle` (14d recent news), `db_manager.Stock`/`CommoditySnapshot` (commodity linkage), `db_manager.set_cached`/`get_cached` (persistence). |
| When | Scheduler batch every 4h; ad-hoc single-symbol generation on any dashboard tap of an uncached/stale symbol (TTL `CACHE_TTL_SECONDS = 2*86400` = 48h — comment explains this was deliberately widened from `get_cached`'s 600s default because a 4h batch cadence meant the leaderboard was "fresh" only 10 min out of every 240, research_engine.py:39-44). |
| Inputs | `symbol` (str). 7 data loads run in parallel via `ThreadPoolExecutor(max_workers=6)` (research_engine.py:1681-1695) — good pattern per engineering standard #3. |
| Outputs / side effects | Returns a full report dict (see What/Why); `generate_research_all()` also writes `analysis_cache` via `set_cached(f"research_{symbol}", ..., cache_type="research")` and `set_cached("research_leaderboard", ...)` (research_engine.py:1841-1876). |
| DB tables | Read: `stock_prices`, `shareholding_patterns`, `news_articles`, `global_news` (buggy query, see below), `company_external_data`/`company_connections` (via `tijori_collector.get_fundamentals`), `fyers_candles` (via `CandleDatabase.get_fyers_daily`), `stocks`. Write: `analysis_cache` (via `set_cached`). |
| Config / env | None found directly in this file (no `config_settings` keys read here) — the ONLY external tunability is via `bot.py`'s separate `prediction.weight.*` keys, which this file does NOT read (its own dimension/regime weights are hardcoded constants, e.g. `w = {"technical": 0.25, "fundamental": 0.25, "institutional": 0.15, "sentiment": 0.15, "risk": 0.20}` at research_engine.py:1331, regime-adapted at lines 1335-1354). |
| External services | **NONE live** in the current code path — `_scrape_screener_ratios()` (research_engine.py:225) is dead code, gated by `_SCREENER_RATIOS_RETIRED = True` (line 222), retired 2026-09-12 alongside `market_intelligence.py`'s peer scraper for the same root cause (comment at lines 214-221: "ratio regexes read the wrong cells... ROCE 33.0 where the page says 22.0... 67 of [1,270 Screener hits/day] came back 429"). Fundamentals now come exclusively from `tijori_collector.get_fundamentals()` (DB read, zero network per the loader's own comment, research_engine.py:1649-1650). |
| Rate limits / cost | `generate_research_all()` still does `time.sleep(2)` between symbols (research_engine.py:1818-1819) commented "Rate-limit Screener.in scraping" — **STALE COMMENT / minor dead reasoning**: Screener scraping in this file is retired, so this sleep no longer protects anything it claims to; it still adds ~2s × (N-1) wall time to every 4-hourly batch (~130s+ for a 67-stock watchlist) for no currently-active reason. One research batch at a time enforced via `_batch_lock`/`_batch["running"]` (a concurrent second call returns `[]` immediately rather than doubling load, research_engine.py:46-50, 1780-1784). |
| Caching | `analysis_cache` table (`cache_type="research"`), keys `research_{symbol}` and `research_leaderboard`, TTL 48h. |
| **CONFIRMED BUG** | `_score_sentiment()`'s "Sector Momentum" sub-factor (25% of the Sentiment dimension) runs `SELECT sentiment FROM global_news WHERE category IN ('sector','market') AND created_at >= %s AND tags LIKE %s` (research_engine.py:1098-1102) — **`global_news` has no `created_at` column** (VERIFIED FROM CODE: `db_manager.py:180-196`, class `GlobalNews` only has `published_at` and `fetched_at`). This raises `UndefinedColumn` on every call, silently swallowed by the bare `except Exception: pass` (line 1111), so `sector_sub` is hardcoded to its unmodified baseline of 50 (neutral) on every single research report, for every stock, always — i.e. Sector Momentum has been permanently inert since (at least) this code was written, contributing a constant 50 × its weight into the Sentiment score with zero actual sector signal. Nothing in logs would show this (exception is discarded, not logged even at debug level) — matches CLAUDE.md's "log line is a snapshot, not a status" caution: there is no log line at all here to check. **SECOND BUG in the same block (VERIFIED 2026-09-28, research_engine.py:1097-1111; live `global_news` columns: id, title_hash, title, source, url, published, published_at, category, tags, sentiment_score, sentiment, summary, fetched_at):** the query selects `sentiment`, which is a **varchar** ('BULLISH'/'BEARISH'/'NEUTRAL'), and feeds it to `np.mean` — so fixing only `created_at` would still raise and still leave `sector_sub` at 50; the fix needs `sentiment_score` (numeric) as well as a valid time column (`published_at`/`fetched_at`). The psycopg2 connection also leaks on the exception path. |
| Failure behaviour | Each dimension scorer defaults to a neutral score of 50 with a `"note"` explaining insufficient data when its input is empty (e.g. `_score_fundamental({})` → `{"score": 50, "factors": {"note": "No fundamental data available"}}`) — fail-open/neutral rather than raising. `generate_research_all()` per-symbol try/except keeps the batch going on individual failures; explicitly re-checks `_active(sym)` (queries `stocks.is_active`) both before scoring a symbol and again before writing the leaderboard, specifically because of a fixed race: "VODAFONEIDEA re-cached 25s after its purge" on 2026-09-12 (research_engine.py:1791-1806, 1825) — a purged symbol could otherwise get a fresh report/rank from a batch that started before its removal. |
| Security | No unescaped-external-text-to-UI issue found directly in this file (news titles pass through as already-scored/stored `NewsArticle` rows — see news_sentiment.py/world_news_collector.py XSS notes; this file doesn't re-render raw HTML). |
| Performance | Batch is strictly sequential over symbols (no parallelism across stocks, only within one stock's data loads) — a 67-symbol watchlist run is dominated by ≥2s×66 sleep plus DB/CPU time per symbol; not measured directly in this pass (`elapsed_seconds` is recorded per-report in the output but the aggregate batch duration is only visible via logs, not re-verified here — MEASURED-would-require-log-read, not done). |
| Blast radius | **Display-only**: feeds the "Research" tab / leaderboard UI and nothing in the live/paper trading path. If this whole engine broke, live trading (`bot.get_prediction`) would be unaffected; only the dashboard's Alpha Score / verdict panel would degrade. This is an important architectural fact for anyone assuming "Alpha Score" drives trades — it does not. |
| Status | ACTIVE (Technical/Institutional/Risk dimensions fully live; Fundamental dimension live via Tijori; Sentiment dimension's Sector Momentum sub-factor is silently DEAD/BROKEN per the bug above; legacy Screener-based fundamental/risk scraping is RETIRED dead code). |

#### Alpha Score composition (regime-adaptive weights, research_engine.py:1330-1354)

| Regime | Technical | Fundamental | Institutional | Sentiment | Risk |
|---|---|---|---|---|---|
| Base (unrecognized regime) | 0.25 | 0.25 | 0.15 | 0.15 | 0.20 |
| TRENDING_UP / TRENDING_DOWN | 0.35 | 0.20 | 0.10 | 0.15 | 0.20 |
| RANGE_BOUND | 0.15 | 0.35 | 0.20 | 0.10 | 0.20 |
| BREAKOUT_IMMINENT / BREAKDOWN_IMMINENT | 0.30 | 0.15 | 0.25 | 0.15 | 0.15 |

Conviction = `clamp(100 - stddev(5 dimension scores)*3, 0, 100)`, +15 bonus if all 5 dimensions agree (all ≥60 or all ≤40). Verdict thresholds on Alpha: ≥70 STRONG_BUY, ≥60 BUY, ≥50 ACCUMULATE, ≥40 HOLD, ≥30 REDUCE, else SELL.

### `deep_analysis.py` — narrative "WHY" synthesis engine

| Field | Detail |
|---|---|
| Where | `deep_analysis.py` (898 lines) |
| What / Why | Synthesizes a human-readable narrative ("WHY is this stock behaving this way") from 7 sources: commodity impact, geopolitical risk, relevant global news, AI prediction (`bot.get_prediction`) + market context, fundamentals, FII/MF shareholding, and Tijori supply-chain intel. Produces `risk_score` (weighted sum of tailwind/headwind factors), `overall_sentiment` (BULLISH..BEARISH), `risk_level`, `key_factors[]`, and a formatted multi-section narrative string. This is the ONLY collector in this pass that directly calls `bot.get_prediction()` — i.e. it is downstream of, not a source for, the live trading signal. |
| Used by (callers) | `GET /api/deep-analysis/<symbol>` (app.py:1511-1520), `GET /api/deep-analysis/portfolio` (app.py:1523-1545, holdings from `bot.get_holdings()`), `GET /api/deep-analysis/watchlist` (app.py:1548-1573, symbols from `stock_prices` DISTINCT or `config.WATCHLIST` fallback). `scheduler._task_deep_analysis` pre-warms the first 6 `config.WATCHLIST` symbols every 1800s (30 min), initial_delay 120 (scheduler.py:752-764, 1351) — NOTE: only pre-warms 6 of potentially 67 watchlist stocks; the rest are generated live/uncached on first dashboard request. |
| Calls | `commodity_tracker.get_commodity_impact`/`get_geopolitical_context`, `world_news_collector.get_recent_news` (tag-filtered via `SECTOR_TAG_MAP`, deep_analysis.py:25-40), `bot.get_prediction(symbol)` (full ML+news+context prediction — expensive, live), `fundamental_analysis.get_fundamental_analysis`, `fii_tracker.get_shareholding_breakdown`, `tijori_collector.get_supply_chain_intel`. |
| When | On-demand per endpoint call (no internal caching in this file itself — unlike `research_engine.py`'s `analysis_cache` use, `deep_analysis.py` has no `set_cached`/`get_cached` calls found); scheduler pre-warm every 30 min for top 6 watchlist symbols only. |
| Inputs | `symbol` (single) or `holdings`/`symbols` list (portfolio/watchlist variants, parallelized `ThreadPoolExecutor(max_workers=3)`, 120s timeout, deep_analysis.py:817-836). |
| Outputs / side effects | Returns dict only — **no DB writes found in this file** (pure read/synthesize, unlike most other collectors in this pass). |
| DB tables | Read (indirectly, via the modules it calls): `stocks`, `global_news`, `company_external_data`/`company_connections` (Tijori), `shareholding_patterns`/FII data, plus whatever `bot.get_prediction`/`fundamental_analysis.get_fundamental_analysis` read (news_articles, stock_prices, fyers data, etc). |
| Config / env | None directly in this file. |
| External services | None directly — all data comes through other modules' collectors (this file makes no `requests` calls itself). |
| Rate limits / cost | Because it calls `bot.get_prediction()` (live price fetch + news fetch + ML inference) for EVERY symbol with no caching, `generate_portfolio_deep_analysis` over a full watchlist (up to 67 symbols) at `max_workers=3` is one of the more expensive read-endpoints in the app — no explicit cap found on `/api/deep-analysis/watchlist`'s symbol count (engineering standard #2 "bound every read that can grow" risk: the endpoint has no `?limit=`, scales with `stock_prices` DISTINCT symbol count). |
| Failure behaviour | Each of the 7 sections independently try/excepted — a failure in one (e.g. Tijori unavailable) just omits that section rather than failing the whole narrative; `generate_portfolio_deep_analysis` substitutes a placeholder "Analysis unavailable for {sym}" result (risk_level UNKNOWN) for any per-symbol exception (deep_analysis.py:821-836) rather than dropping the symbol — satisfies "missing data must be visible" (standard #7). |
| Security | Narrative strings interpolate stock/news data (e.g. `sc_parts.append(f"⚠ {flag}.")` from Tijori forensic flag text, and article titles via `_build_news_narrative`) into a plain string returned as JSON — rendering/escaping responsibility is on the frontend; not itself unsafe here but worth checking the dashboard's render path for the `narrative` field (see Cross-cutting XSS flag). |
| Performance | No caching layer — every call regenerates from scratch, including a live `bot.get_prediction()`. Combined with no watchlist-size cap, this is the most likely of the collectors in this pass to be slow/costly on `/api/deep-analysis/watchlist`. |
| Blast radius | Feeds the "WHY" panel per-stock and portfolio/watchlist risk-concentration insights (sector/commodity correlation warnings); since it also calls `bot.get_prediction`, a slowdown/error in the live prediction path shows up here too (though caught and reported as `"AI signal"` factor simply missing, not a hard failure). |
| Status | ACTIVE |

### `auto_metadata.py` — metadata discovery (company/sector/peers/commodity) + F&O config seeding

| Field | Detail |
|---|---|
| Where | `auto_metadata.py` (543 lines) |
| What / Why | Two unrelated responsibilities in one file: (1) scrapes Screener.in for company name, sector classification (4-level breadcrumb), peer/competitor discovery, and rule-based commodity-dependency inference (`_COMMODITY_RULES`, sector/keyword→commodity/ticker/relationship/weight table, auto_metadata.py:45-79); (2) seeds F&O/MCX lot-size and cost-rate config into `config_settings` (`seed_fno_config`, hardcoded `_FNO_LOTS`/`_MCX_LOTS`/`_FNO_COSTS` dicts as one-time defaults, editable thereafter via DB). **Screener.in scraping for metadata is still ACTIVE** — unlike the ratio-scraping in `market_intelligence.py`/`research_engine.py`, which was retired 2026-09-12; this file scrapes different page sections (`<h1>`, `.about`, `#peers` breadcrumbs) not the ratio table, so it wasn't implicated in that incident. |
| Used by (callers) | `scheduler._task_auto_metadata` → `refresh_all_metadata()` every 604800s (7 days), initial_delay 170 (scheduler.py:779-785, 1381). `POST /api/watchlist/add` (app.py:3945-4152) calls `auto_metadata.refresh_stock_metadata(symbol)` synchronously-in-background-thread as STEP 1 of the new-stock onboarding pipeline (see below). `GET/POST /api/refresh-stock-metadata/<symbol>` (app.py:1662-1666, manual single-stock trigger). |
| Calls | `requests`+`BeautifulSoup` (Screener.in; `beautifulsoup4` is undeclared in `requirements.txt`), `db_manager.get_db`/`Stock`/`get_competitors`/`get_all_stocks`/`get_config`/`set_config`. |
| When | Weekly scheduler batch (all tracked stocks, 2s between stocks); on-demand at watchlist-add time; manual endpoint. |
| Inputs | `symbol`. |
| Outputs / side effects | Updates `stocks` table: `company_name`, `sector` (mapped code), `sector_display`, competitors (via `stock.set_competitors(peer_symbols)`), and `commodity`/`commodity_ticker`/`commodity_relationship`/`commodity_weight` — **but only if the stock doesn't already have a commodity set** (auto_metadata.py:360-365, "preserve manual overrides"). Also seeds `config_settings` keys (F&O/MCX lot configs, cost rates) via `seed_fno_config()` — a one-time-per-key seed (`if get_config(key) is None`), unrelated to the per-symbol scraping. |
| DB tables | Read/write `stocks`; read/write `config_settings` (F&O keys). |
| Config / env | Seeds (defaults only set if absent): `fno.lot.{SYMBOL}` for NIFTY/BANKNIFTY/FINNIFTY/SENSEX/MIDCPNIFTY/HDFCBANK (JSON blob: lot_size/exchange/type/tick/weekly_expiry); `mcx.lot.{SYMBOL}` for CRUDEOILM/NATURALGAS/NATGASMINI/GOLDM/SILVERM; `fno.stt.option_sell_pct` (0.0625%), `fno.stt.futures_sell_pct` (0.0125%), `fno.exchange.nse_pct` (0.0495%), `fno.exchange.bse_pct` (0.0325%), `fno.exchange.mcx_pct` (0.0260%), `fno.sebi_pct` (0.0001%), `fno.gst_pct` (18.0%), `fno.stamp_duty_pct` (0.003%), `fno.brokerage_per_order` (₹20), `fno.brokerage_pct_cap` (0.05%) — these are **EXTERNAL VERIFICATION REQUIRED** (NSE/SEBI/exchange rates as of whenever this was written; not re-verified against current NSE circulars in this pass). |
| External services | Screener.in — `https://www.screener.in/company/{symbol}/consolidated/` (404 fallback to non-consolidated), plus `https://www.screener.in{href}` industry/market pages for peer discovery (`_scrape_industry_page`, auto_metadata.py:209-233). No API key. |
| Rate limits / cost | `time.sleep(1)` between the metadata scrape and peer discovery, another `time.sleep(1)` before the commodity/DB-update step, `time.sleep(0.5)` between peer-discovery fallback levels, and `time.sleep(2)` between stocks in `refresh_all_metadata()` (comment: "max ~30 stocks/minute") — no circuit breaker / stop-on-403 logic like `market_intelligence.py` gained after the 2026-09-12 incident; **this file was NOT mentioned in that incident's retrospective comments** even though it scrapes the same site — POTENTIAL RISK not verified either way in this pass. |
| Caching | None in this file directly; `_invalidate_caches()` (auto_metadata.py:440-456) clears three OTHER modules' in-process caches (`commodity_tracker._commodity_map_cache`, `market_context._sector_map_cache`, `news_sentiment._symbol_names_cache`) after a full refresh, so sector/commodity/name lookups elsewhere pick up new DB values without a restart. |
| Failure behaviour | Fail-open per-stock in the weekly batch (try/except, continues); `refresh_stock_metadata` returns `{"error": ...}` on scrape or DB failure without raising. |
| Blast radius | `stocks.sector`/`.commodity`/competitors feed `deep_analysis.py` (`SECTOR_TAG_MAP` news filtering, commodity narrative), `research_engine.py` (`_load_commodity_data`, sector-momentum query), `commodity_tracker.py` (geopolitical context), and `fundamental_analysis.py` (`_get_competitors`/`_get_sector_display`, used for the retired peer-ratio path and possibly elsewhere). |
| Status | ACTIVE (metadata scraping + F&O config seed); note the peer-comparison CONSUMER of this data (`market_intelligence.collect_peer_comparison`) is itself retired, so `discover_peers()`'s output is still stored on `stocks.competitors` (consumed by `fundamental_analysis._get_competitors` etc.) even though the specific peer-ratio-scrape flow that used to pair with it is dead. |

### Watchlist-add onboarding pipeline (`POST /api/watchlist/add`, app.py:3945-4152)

Verified end-to-end sequence when a stock is added:

1. **Synchronous membership check**: validates `symbol` against `master_ticker_table` (must be `instrument_type=EQ` and `fyers_resolution_status="resolved"`), inserts/reactivates a `stocks` row (`is_active=True`). Concurrent double-add guarded by catching `IntegrityError` on commit (app.py:3969-3992).
2. **Background thread `bg_fetch()`** (fire-and-forget, `threading.Thread(daemon=True)`), in order:
   a. `auto_metadata.refresh_stock_metadata(symbol)` — Screener.in scrape → `stocks.company_name`/`.sector`/`.sector_display`/competitors/commodity (app.py:4047-4052).
   b. `market_intelligence.collect_all_intelligence(symbol)` — shareholding scrape (Screener.in) + peer comparison (**no-op, retired**) + volume seasonality (app.py:4057-4062).
   c. `tijori_collector.onboard_symbol(symbol)` — Tijori company page + partner slug resolution + partner snapshot fetch, scoped to just this symbol (app.py:4066-4079).
   d. Market-hours-gated FYERS historical backfill: if market is open, **deferred** (recorded via `self_healing._record("missing_data", ...)` so `/api/self-healing` shows it immediately) and picked up later by `self_healing.check_missing_symbols()`; if closed, `fyers_historical_backfill.backfill_symbol(symbol)` runs immediately (~64 FYERS calls: full daily+1-min+5-sec ladder) (app.py:4085-4118).
   e. Model training (`bot.train_model` + `bot.train_xgb_model`) — runs **only if** the backfill in step (d) succeeded this same pass, specifically to avoid training on an empty `fyers_candles` table (app.py:4120-4148). **Caveat (VERIFIED 2026-09-28):** the add-time GBC training goes through `bot.fetch_historical`, so on a trading day it hits the trailing-24h (`days=1`) branch and fails the 100-row minimum (≤75 bars) — **only XGB gets a model at add time**; GBC will only get one from a weekend/holiday retrain (and not at all for cheap stocks, see ML section).
3. The legacy Groww weekly-candle fetch into `stock_prices` is explicitly DISABLED (commented out, not deleted) since 2026-08-15 — the comment block (app.py:4018-4044) flags an **acknowledged live inconsistency**: several read paths (`/api/prices`, `/api/watchlist/<symbol>/analysis`, the scheduler, the Tijori-trigger universe) still read `stock_prices` as "the watchlist" and have not yet been repointed to `fyers_candles`, so a newly-added stock's chart/analysis can appear empty even though the FYERS backfill succeeded.

### `symbol_purge.py` — watchlist-removal cleanup (validation + deletion + retention)

| Field | Detail |
|---|---|
| Where | `symbol_purge.py` (341 lines) |
| What / Why | Single place that deletes "everything the system holds ABOUT a stock" when it leaves the watchlist, in one DB transaction, after a previous bug left 6 "ghost" symbols (VODAFONEIDEA, NEROLAC, TATAMOTORS, AKZONOBEL, JSWEN, LTI found 2026-09-12) with an active `stocks` row but no data — costing failed FYERS lookups every scan. Self-auditing: `_symbol_columns()` introspects `information_schema.columns` for ANY column named/looking like `symbol`/`stock`/`ticker` across ALL public tables at purge time, so a newly added table is never silently skipped — anything not explicitly classified DELETE or KEEP is reported as `unclassified` rather than silently ignored or silently destroyed. |
| Used by (callers) | `GET /api/watchlist/<symbol>/footprint` → `symbol_purge.footprint(symbol)` (read-only preview for a confirm dialog, app.py:4173-4186). `DELETE /api/watchlist/remove/<symbol>` → `symbol_purge.purge_symbol(symbol)` (app.py:4189-4212+). |
| Calls | Direct `psycopg2` (own transaction, not via `db_manager`'s SQLAlchemy session); `paper_trader.PaperTradeTracker`, `db_manager.TradeJournalEntry` (open-position check); `change_feed.notify` on success. |
| When | User-triggered only (watchlist Remove button) — not scheduler-driven. |
| Inputs | `symbol` (validated: non-empty, alnum after stripping `-`/`&`). |
| **DELETE** (`PURGE_TABLES`, symbol_purge.py:43-58) | `stocks`, `stock_prices`, `fyers_candles` (parent — cascades through all partitions), `candles`, `intraday_candles`, `predictions`, `news_articles`, `shareholding_patterns`, `peer_comparisons`, `company_external_data`, `external_slug_map` (by symbol, plus a second pass for slug-cache rows recorded under the company name with no symbol yet resolved), `company_connections` (own rows, i.e. where THIS symbol is the principal), `thesis_analysis`, `watchlist_notes`; also `analysis_cache` rows keyed `research_{symbol}`/`fundamentals_{symbol}`/`fundamentals_v2_{symbol}`/`backtest_{symbol}_*` (matched via `= ANY()` + regex, explicitly NOT `LIKE`, because `LIKE`'s `_` wildcard would make `backtest_LT_%` also match LTI, symbol_purge.py:70-74); entries for the symbol are cut out of cached list blobs `research_leaderboard` and `auto_analysis_latest` rather than waiting for the next batch rebuild; `config_settings` key `tijori.last_collected.{symbol}`; model files (`models/gbc_cash/{s}.joblib`, `models/xgb_cash/{s}.joblib`, `models/{s}.joblib`, `models/backtest_cache/{s}_*.joblib`, `chart_cache/{s}.*`) deleted from disk AFTER commit (so a failed transaction deletes no files); the symbol's entry in `watchlist_notes.json`. |
| **KEEP** (`KEEP_TABLES`, symbol_purge.py:62-67) | `trade_journal`, `paper_trades`, `trade_log`, `trade_snapshots` (financial history — "never deleted by a UI action"); `theses`, `stock_theses` (user's own writing); `master_ticker_table`, `nse_instruments` (exchange universe reference data); `commodity_snapshots`; and the column `company_connections.related_symbol` (another company's row that merely names this symbol as ITS partner — that's the other company's data, not this symbol's). |
| **Refuses** | `purge_symbol` raises `PermissionError` if `open_positions(symbol)` finds any OPEN paper trade or open `TradeJournalEntry` — "closing it is a money action and belongs to the trade flow, not to a watchlist button" (symbol_purge.py:28-29, 108-129, 190-192); if either the paper tracker or the journal is unreadable, it is treated as an (unknown → blocking) open position rather than fail-open, per CLAUDE.md's "guards must fail closed" principle. |
| Outputs / side effects | Returns a `report` dict with `deleted`/`kept`/`unclassified` row counts + `files` removed; `footprint()` is the read-only dry-run version with identical classification logic (so the confirm dialog matches the actual purge exactly) plus `open_positions` info. |
| DB tables | See DELETE/KEEP above; also reads `information_schema.columns` to discover all symbol-like columns dynamically. |
| Failure behaviour | All DB deletes are one transaction — `except: conn.rollback(); raise` (symbol_purge.py:259-261) — "either every row goes or none does." File deletions and in-memory cache clears happen only after commit. |
| In-memory cache invalidation (`_forget_in_memory`, symbol_purge.py:305-341) | Pops the symbol from: `bot._predictors`, `fundamental_analysis._cache` (under `fa._cache_lock`), `news_sentiment._cache`; resets `commodity_tracker._commodity_map_cache` and `tijori_collector._LOCAL_INDEX["map"]` to `None` (full rebuild next use, not just this symbol); filters the symbol out of `auto_analyzer._latest_analysis["predictions"]`; calls `db_manager.invalidate_config_cache` for the `tijori.last_collected.{symbol}` key. |
| Security | Table/column names are validated against `information_schema` (not user input) before being interpolated into f-string SQL (`f'DELETE FROM "{table}" WHERE "{col}" = %s'`) — the identifiers come from the DB catalog query, not the request, so this isn't a raw SQL-injection surface from the `symbol` parameter (which IS bound as a query parameter, `%s`). |
| Blast radius | This is the authoritative "what does Remove actually do" reference — any new intelligence table added to this codebase (e.g. a hypothetical new collector) that isn't added to `PURGE_TABLES` or `KEEP_TABLES` will show up under `unclassified` in both `footprint()` and `purge_symbol()`'s report, which is a visible signal (not a silent gap) but still requires a human to notice and classify it. |
| Status | ACTIVE |

### `fundamental_analysis.py` — per-stock fundamentals rating (Tijori-sourced, Screener retired)

| Field | Detail |
|---|---|
| Where | `fundamental_analysis.py` (725 lines) |
| What / Why | Produces a 0-9.5-scaled "fundamental score" / STRONG..POOR rating for a stock, blending fundamentals (now Tijori-sourced), a live quote, 52-week position, and up-to-5 competitor price comparison. Two scoring functions exist: `_analyze_financials()` (line 360, the ORIGINAL Screener-keyed scorer — **now dead code, zero callers found**) and `_analyze_tijori()` (line 516, the ACTIVE scorer, field-conditional so a bank missing "promoter holding" isn't marked down for a field that doesn't apply — explicitly fixes an observed HDFC Bank false-negative). |
| Used by (callers) | `GET /api/watchlist/<symbol>/analysis` (app.py:4280+) — fans out `get_fundamental_analysis`, `scrape_annual_financials`, `fii_tracker.get_shareholding_breakdown`, `commodity_tracker.get_commodity_impact`, `news_sentiment.get_geopolitical_news`, `news_sentiment.get_news_sentiment` via `ThreadPoolExecutor(max_workers=6)` (app.py:4417-4454) — this is the concrete instance of CLAUDE.md engineering standard #3's cited example ("watchlist analysis had 6 providers in series" — now parallel, each with its own `.result(timeout=...)`). `scheduler._task_cache_refresh` calls `get_fundamental_analysis(None, symbol)` hourly (initial_delay 240) for every `stock_prices` symbol, to keep the 6h cache warm (scheduler.py:128-169) — also detects new-quarter earnings via `_detect_new_quarter` (compares `financials.latest_quarterly_revenue`) to trigger an early Tijori refresh. `deep_analysis.py` (`_build_fundamental_narrative`) also calls `get_fundamental_analysis`. |
| Calls | `tijori_collector.get_fundamentals(symbol)` (fundamentals — replaces retired Screener ratio scrape, fundamental_analysis.py:647-653), `bot.fetch_quote` (live quote via FYERS, `_get_groww_quote_fundamentals` — name is legacy, no longer calls Groww, fundamental_analysis.py:329-357), `bot.fetch_quote` again for up to 5 competitors (`_fetch_competitor_prices`), `db_manager.get_competitors`/`get_stock`/`get_cached`/`set_cached`. |
| When | On-demand (dashboard tap) with 6h cache; hourly scheduler warm (`cache_refresh` task, `_boot_warmup_active()`-gated to avoid competing with FYERS token auth at boot — comment cites a 2026-08-25 incident: 65 blocked calls compounding a token-auth failure into a 300s rate-limit cap, scheduler.py:140-146). |
| Inputs | `groww_api` (legacy param name, unused — FYERS via `bot.fetch_quote` is the actual source), `symbol`. |
| Outputs / side effects | Returns a rich dict (`financials`, `fundamental_score`/`_pct`/`_rating`, `positive_flags`, `concerns`, `quote`, `volume_signal`, `52w_position_pct`, `competitors`, `vs_peers`); writes `analysis_cache` key `fundamentals_v2_{symbol}` (versioned key — deliberately bumped from a `fundamentals_{symbol}` v1 so a result cached under the old Screener-sourced format is never served after the Tijori cutover, fundamental_analysis.py:627-629). |
| DB tables | Read (via `tijori_collector`) `company_external_data`; read `stocks`/`config_settings` (competitors/sector); read/write `analysis_cache` (`fundamentals_v2_{symbol}`). |
| Config / env | None directly (cache TTL `_CACHE_TTL = 6 hours` is a hardcoded constant, not a `config_settings` key — inconsistent with engineering standard #8 "config over constants" but low-severity). |
| External services | `scrape_annual_financials()` (line 97) is a **live, ACTIVE** Screener.in scrape (`https://www.screener.in/company/{symbol}/consolidated/`, 404-fallback to non-consolidated) for year-wise P&L (revenue/expenses/operating profit/net profit/EPS/OPM/dividend payout) + YoY growth — this is DISTINCT from the retired ratio scraper (`_scrape_screener`, line 233, gated `_SCREENER_RATIOS_RETIRED = True` since 2026-09-12) and was NOT retired, so Screener.in is still hit once per `/api/watchlist/<symbol>/analysis` call for this data. `bot.fetch_quote` → FYERS (live LTP/OHLC/volume/change%). |
| Rate limits / cost | No explicit delay/backoff in this file for `scrape_annual_financials`; relies on the caller's own timeout (`_f_annual.result(timeout=40)` in app.py) and whatever global politeness other Screener-scraping modules apply (none shared — each scraper in this codebase manages its own Screener.in access independently: `auto_metadata.py`, `market_intelligence.py` (shareholding only now), and this file's `scrape_annual_financials` are the three still-active Screener touch points; `_scrape_screener` here and `_scrape_screener_ratios`/`_scrape_peer_ratios` elsewhere are retired). |
| **RETIRED, documented in-code (fundamental_analysis.py:214-230)** | `_scrape_screener()`'s regex ratio extraction was verified wrong against the live DIVISLAB page: ROCE showed 33.0 vs the page's 22.0, "book value"/"P/B" both read 9,322 (that's the share price; real book value 631), ROE/market cap/dividend yield/52-week range missing entirely, and revenue/profit/OCF/FCF trends all collapsed to the same number (373860) — only P/E and promoter holding were correct. This scraper was "one of four hits on the same Screener page per symbol per cycle (~1,270/day, 67 rejected 429)" — i.e. one of the four concurrent Screener scrapers (this file, `market_intelligence.py`, `research_engine.py`, `auto_metadata.py`) that collectively caused the 2026-09-12 blocking incident. `get_fundamental_analysis()` now reports rating `"N/A"` for a symbol with no Tijori snapshot, rather than scoring an empty result "POOR" (which the stock panel used to read out as "Fundamentals are poor — high risk", a false negative for missing-vs-bad data — good instance of engineering standard #7, "missing data must be visible" as N/A rather than misrepresented as a real bad score). |
| Caching | Two-tier: in-process `_cache` dict (`_cache_lock`-protected, 6h TTL) checked first, then `analysis_cache` DB row (`fundamentals_v2_{symbol}`, same 6h TTL) as a persistent fallback surviving process restarts, then a full Tijori-DB + live-quote + competitor recompute on double-miss. |
| Failure behaviour | Every external call (Tijori read, FYERS quote, competitor quotes) individually try/excepted; an entirely empty Tijori snapshot degrades to the explicit `"N/A"`/0-score sentinel rather than raising or mis-scoring. |
| Security | Fallback hardcoded competitor/sector maps (`_FALLBACK_COMPETITORS`, `_FALLBACK_SECTOR`) only used if DB lookup fails — static data, no injection surface. |
| Blast radius | Feeds the watchlist analysis panel's fundamentals card, `deep_analysis.py`'s fundamentals narrative, and (indirectly) nothing in `bot.get_prediction` (which does NOT call this module — VERIFIED FROM CODE, `bot.py`'s prediction weights are ML/Trend/News/Context only per Cross-cutting facts). |
| Status | Tijori-based scoring (`_analyze_tijori`, `get_fundamental_analysis`) ACTIVE; Screener ratio scraper (`_scrape_screener`) and its scorer (`_analyze_financials`) RETIRED/DEAD (the scorer has zero callers at all, live or dead-gated); `scrape_annual_financials` (separate Screener endpoint, P&L trend only) ACTIVE. |

### `peer_analyzer.py` — separate peer-price tracking system (own tables, DB-agnostic to db_manager)

| Field | Detail |
|---|---|
| Where | `peer_analyzer.py` (380 lines) |
| What / Why | A THIRD, independent peer-comparison mechanism alongside `market_intelligence.py`'s (retired) Screener peer-ratio scrape and `tijori_collector.py`'s peer-table snapshots. This one tracks daily peer **price/change%** (not fundamentals) in its own bespoke tables created via raw `CREATE TABLE IF NOT EXISTS` DDL at runtime (`_ensure_peer_tables()`, peer_analyzer.py:33-99) — `peers`, `peer_prices`, `peer_analysis` — entirely separate from `db_manager.py`'s SQLAlchemy models and NOT listed in `symbol_purge.py`'s `PURGE_TABLES`/`KEEP_TABLES` (see CONTRADICTION below). |
| Used by (callers) | **No caller exists — CONFIRMED ORPHAN (VERIFIED 2026-09-28)**: `grep -rln` across the whole repo (tracked + untracked `.py`/`.html`/`.js`/`.sh`) for `peer_analyzer` and its 5 functions (`collect_peers_for_stock`, `update_peer_prices`, `analyze_peer_comparison`, `get_peers_from_database`, …) finds only `peer_analyzer.py` itself and a comment at `bot.py:338`. Its own docstring says `collect_peers_for_stock` is "Called when stock is added to watchlist" and `update_peer_prices` "Called daily by scheduler" — **neither claim matches the verified `POST /api/watchlist/add` pipeline** (auto_metadata → market_intelligence → tijori_collector, no `peer_analyzer` call) **nor `scheduler.py`'s task registrations** (no `_task_*` references this module). Docstring is INTENT, not behaviour, per CLAUDE.md's own research rule — and here the intent appears to have never been wired up, or was wired up and later removed. |
| Calls | Raw `psycopg2` (own connection helper, `_get_db_connection()`, independent of `db_manager.get_db()`); `fundamental_analysis._get_competitors` (peer symbol list); `bot.fetch_live_price`/`bot.fetch_quote` (FYERS, for `update_peer_prices`). |
| Tables created at runtime by this file | `peers` (parent_symbol, peer_symbol, peer_name, sector, added_date), `peer_prices` (peer_symbol, date, ltp, prev_close, change_pct, volume), `peer_analysis` (parent_symbol, analysis_date, outperformers/underperformers/at_parity as comma-joined text, avg_peer_change, analysis_json) — all created lazily on first call via `_ensure_peer_tables()`, not via a tracked migration. |
| **CONTRADICTION** | If this module were ever exercised (even manually/via a REPL), its three tables would hold live symbol-keyed data that `symbol_purge.py` does NOT know about — they are absent from both `PURGE_TABLES` and `KEEP_TABLES`. `symbol_purge._symbol_columns()` would catch them via its `information_schema` introspection (columns `parent_symbol`/`peer_symbol` match `%symbol%`) and correctly bucket them as `unclassified` (visible, not silently dropped or deleted) — so the purge safety net holds, but a human would need to notice and classify them. Currently moot because **the tables do NOT exist — VERIFIED IN DB 2026-09-28: `information_schema.tables` has no `peers`, `peer_prices` or `peer_analysis`** (never created, since nothing calls `_ensure_peer_tables()`). |
| Status | **ORPHANED / UNREACHABLE in the current wiring** (no verified caller); if ever re-wired, would duplicate functionality already covered by `tijori_collector.get_supply_chain_intel()`'s partner-returns health metric. |

### `fii_tracker.py` — FII/mutual-fund/promoter shareholding via Groww quote API

| Field | Detail |
|---|---|
| Where | `fii_tracker.py` (166 lines) |
| What / Why | Attempts to read institutional shareholding breakdown (promoters/FIIs/mutual funds/retail %) directly off a Groww `get_quote()` call, then derives simple `fii_signal`/`mf_signal` (STRONG_BUY/BUY/NEUTRAL/SELL) from hardcoded thresholds (FII>15% strong-buy, >8% buy, <3% sell; MF>12% strong-buy, >6% buy). |
| Used by (callers) | `deep_analysis.py` step 6 ("FII/MF Interest", deep_analysis.py:634-655) via `get_shareholding_breakdown`; `GET /api/watchlist/<symbol>/analysis` fan-out (`_p_inst`, app.py:4431-4433). `format_institutional_holdings()` (line 115) — no caller found in this pass (possibly dead/legacy helper superseded by the two call sites above doing their own formatting; UNKNOWN). |
| Calls | `growwapi.GrowwAPI(token).get_quote(trading_symbol=symbol, exchange="NSE", segment="CASH")`. |
| Config / env | `GROWW_ACCESS_TOKEN` (env) — **VERIFIED FROM CODE this var name still exists in `.env`** (`/usr/bin/grep -oE` listing), and `growwapi`/`GrowwAPI`/`GROWW_ACCESS_TOKEN` are still referenced in ~15 other files including `bot.py`/`fno_trader.py`/`trailing_stop.py` (broker/order-placement path), so the Groww connection itself is still live for trading. **UNKNOWN / not verified in this pass**: whether `groww.get_quote()`'s response actually contains any of the `shareholding`/`promoter_holding`/`fii_holding`/`mf_holding`/`retail_holding` fields this code probes for — the code itself is defensive about this ("Try various field names for shareholding... If no real data available, return empty"), which is circumstantial evidence the author was not confident these fields are reliably present. Given CLAUDE.md's "no Groww fallback any more" note for market DATA (Groww migrated to FYERS for prices/candles as of 2026-08-15), and that this module was never updated to use FYERS, it is plausible `get_shareholding_breakdown()` silently returns `{}` on every call in current production — **UNVERIFIED, flagged as a risk to check**, not asserted as fact. |
| External services | Groww API (`growwapi` package) — the BROKER's own quote endpoint, not a scrape; needs `GROWW_ACCESS_TOKEN`. |
| Failure behaviour | Fail-open to `{}` / empty dict on any exception or missing token — silently degrades `deep_analysis`'s "FII/MF Interest" section and the watchlist-analysis institutional-holdings card to absent, with no visible error (a "missing data must be visible" gap per engineering standard #7 — nothing distinguishes "Groww returned no shareholding fields" from "this stock genuinely has low institutional interest" in the UI, since a low/zero fii/mf percentage and an empty dict both render as "no signal"). |
| Blast radius | If confirmed silently broken, this only removes one `key_factor` line from `deep_analysis` narratives and one card from the watchlist-analysis panel — `shareholding_patterns` (the FII/DII data actually used by `research_engine._score_institutional` and `market_intelligence.analyze_institutional_trend`) is a SEPARATE, Screener-sourced table unaffected by this module. |
| Status | ACTIVE (wired into 2 call sites) but **reliability UNVERIFIED** — worth a live spot-check (out of scope for this read-only pass). |

### `commodity_tracker.py` — canonical commodity price fetch + geopolitical context + static supply-chain reference data

| Field | Detail |
|---|---|
| Where | `commodity_tracker.py` (695 lines) |
| What / Why | Three distinct things: (1) `fetch_commodity_price(ticker)` — the documented **single source of truth** for all yfinance commodity price fetching in the codebase (module docstring, commodity_tracker.py:25-28), used by `supply_chain_collector.py` and `app.py`; (2) `get_commodity_impact(symbol)`/`get_geopolitical_context(symbol)` — per-stock commodity-dependency and geopolitical-risk lookups, backed by a DB-loaded `stocks`-table map (`_get_commodity_map`, fallback `_FALLBACK_COMMODITY_MAP` for 23 hardcoded symbols) and a static `GEOPOLITICAL_CONTEXT` dict (**7 commodities** — commodity_tracker.py:180-~300: Crude Oil, Iron Ore / Steel, Gold, Aluminium, Zinc / Base Metals, USD/INR, Coal — the same set as the 7 yfinance tickers, and matching the 7 `geopolitical:*` `analysis_cache` rows); (3) `COMMODITY_SUPPLY_CHAIN` — a large **static reference dataset** (producers/importers/chokepoints/active disruptions per commodity, with ISO country codes for a world map) consumed by `supply_chain_collector._build_disruption_watch()` and the `/api/supply-chain` heatmap endpoints (app.py:1884-1891). |
| Used by (callers) | `supply_chain_collector.py` (`fetch_commodity_price` delegate, `COMMODITY_SUPPLY_CHAIN` for disruption-watch generation); `scheduler._task_geopolitical_collect` → `collect_geopolitical_news()` every 1800s (30 min), initial_delay 70 (scheduler.py:627-633, 1340); `news_sentiment.get_geopolitical_news`/`_fetch_x_posts` (via `get_geopolitical_context`); `deep_analysis.py` (`get_commodity_impact`, `get_geopolitical_context`); `research_engine._load_commodity_data` (reads `stocks.commodity`/`CommoditySnapshot` directly, NOT via this module — a parallel path, see Cross-cutting); `app.py` commodity/supply-chain endpoints (lines 1799, 1884-1891, 2975-2976, 4436-4437); `auto_metadata._invalidate_caches()` resets `commodity_tracker._commodity_map_cache`. |
| Calls | `yfinance.download(ticker, period="3mo", interval="1d")` via a 2-worker `ThreadPoolExecutor` with a 15s timeout (`fetch_commodity_price`, commodity_tracker.py:41-124) — every numeric result is passed through `_safe_float()` so NaN/Inf can never leak out (explicit design note, lines 30-38, 52-53); `news_sentiment._fetch_google_news` (for geopolitical article collection); `db_manager.get_commodity_map`/`get_cached`/`set_cached`. |
| DB tables | Reads `stocks` (commodity mapping, via `db_manager.get_commodity_map`); reads/writes `analysis_cache` (`geopolitical:{commodity_name}` keys, `cache_type="geopolitical"`, 24h TTL) — NOT `commodity_snapshots`/`disruption_events` (those are `supply_chain_collector.py`'s tables; this module's geopolitical data lives entirely in `analysis_cache`). |
| Config / env | None (`config_settings` not read in this file). |
| External services | yfinance for commodity tickers (same 7 tickers as `supply_chain_collector.COMMODITY_TICKERS`: `CL=F` Crude Oil, `TIO=F` Iron Ore/Steel, `GC=F` Gold, `ALI=F` Aluminium, `ZNC=F` Zinc, `BTU` Coal, `USDINR=X`); Google News RSS (via `news_sentiment._fetch_google_news`) for geopolitical article collection, keyed off `GEOPOLITICAL_CONTEXT[commodity]["search_terms"]` (3 terms/commodity/run). |
| **CONFIRMED BUG** | `collect_geopolitical_news()` (commodity_tracker.py:339-437) calls `news_sentiment._fetch_google_news(term, limit=5)`, which returns a `List[NewsItem]` — `NewsItem` is a `@dataclass` (news_sentiment.py:201-209), **not a dict**. The very next line does `a.get("title", "")[:200]` (commodity_tracker.py:360) — dataclass instances have no `.get()` method, so this raises `AttributeError` on the FIRST article of every search term, every commodity, every run. The whole per-term `try/except Exception: pass` block (lines 354-366) swallows it silently, so `new_articles` is **always empty** — `collect_geopolitical_news()` has never actually ingested a single live Google News article since this code path was written. **DB-PROVEN (2026-09-28): all 7 `analysis_cache` rows `geopolitical:*` have `article_count=0`, an EMPTY article list and `risk_level='low'` (updated 2026-09-27 04:22-04:23)** — so there is nothing "already existing" being re-persisted: every stored list is empty, and **every commodity is permanently reported `risk_level="low"`. That "low" is fabricated — the truth is "unknown"** (a violation of CLAUDE.md standard #7, missing data must be visible; every consumer reading it treats "low risk" as a real reading). Every scheduled run (every 30 min) re-persists these empty lists. This directly undercuts the module's own docstring ("Incrementally builds context from new articles while keeping history") and silently starves `news_sentiment.get_geopolitical_news()`/`deep_analysis.py`'s geopolitical narrative of fresh signal — no log line surfaces this (the exception is discarded before even a debug log). Same class of failure as the `research_engine.py` `global_news.created_at` bug: a data-shape mismatch caught by an overly broad `except Exception: pass`. |
| Rate limits / cost | `_executor = ThreadPoolExecutor(max_workers=2)` module-level, shared across all `fetch_commodity_price` calls (bounds concurrent yfinance calls); geopolitical collection limits to 3 search terms × 5 articles per commodity per run (would be, if not for the bug above). |
| Caching | `_commodity_map_cache` (module-global, in-process, invalidated by `auto_metadata._invalidate_caches()` and `symbol_purge._forget_in_memory` resetting it to `None`); `analysis_cache` 24h TTL for geopolitical data. |
| Failure behaviour | `fetch_commodity_price` returns `None` on any failure (invalid ticker, timeout, insufficient data, non-positive price) — callers (`get_commodity_impact`) fall back to `_fallback_result()`, a neutral/UNKNOWN-trend dict with an explicit "data unavailable" summary rather than a fabricated number (fail-open to explicit-unknown, not fail-open to a wrong value — good practice) — **applies to prices only**: the geopolitical path does the opposite, reporting a fabricated `risk_level="low"` from empty data (see bug above). |
| Security | `GEOPOLITICAL_CONTEXT`/`COMMODITY_SUPPLY_CHAIN` are static hardcoded Python dicts (author-written risk narratives and production statistics) — **EXTERNAL VERIFICATION REQUIRED** for currency of the figures (e.g. "101.0 million barrels/day" global crude production, OPEC shares, etc. — these are point-in-time estimates baked into source code with no refresh mechanism, so they age silently with no "last updated" marker on the static portions, unlike the dynamic `geopolitical:{commodity}` cache which does carry `last_updated`). |
| Blast radius | Feeds: the supply-chain heatmap UI (static data), `deep_analysis.py`'s commodity/geopolitical narrative sections, `news_sentiment.get_geopolitical_news`, and `research_engine._score_sentiment`'s "Commodity Alignment" sub-factor indirectly (that one reads `CommoditySnapshot`/`stocks.commodity` directly via `research_engine._load_commodity_data`, not through this module — two parallel commodity-linkage read paths exist, both ultimately keyed off the same `stocks.commodity*` columns that `auto_metadata.infer_commodity_links` writes). |
| Status | Price fetching (`fetch_commodity_price`) ACTIVE and correct; commodity-impact/geopolitical-context lookups ACTIVE; **live geopolitical news collection (`collect_geopolitical_news`) is silently non-functional** per the confirmed bug above — it runs on schedule, logs no error, and does nothing but re-save EMPTY article lists with a fabricated `risk_level="low"` for all 7 commodities (unknown, not low). |

### `portfolio_analyzer.py` — read-only per-holding action recommendation engine

| Field | Detail |
|---|---|
| Where | `portfolio_analyzer.py` (1051 lines) |
| What / Why | For every real Groww holding AND open position, runs full AI prediction + fundamentals + competitor comparison + cost-aware P&L + technicals, then computes an 8-component composite score (`pnl_score + ai_score + fund_score + tech_score + val_score + peer_score + inst_score + env_score`) mapped through a P&L-bucketed decision tree to one action: HOLD / ADD MORE / BOOK PROFIT / EXIT / WATCH. Explicitly **read-only** — module docstring: "No trades are placed." |
| Used by (callers) | `bot.analyze_portfolio()` (bot.py:2502-2532) wraps `portfolio_analyzer.analyze_portfolio(groww, get_prediction_with_fresh_candles, fetch_live_price)`; called from 3 places in `app.py` (lines 5176, 5206, 5273 — portfolio-analysis dashboard endpoint(s), exact route not re-verified in this pass beyond the call sites). |
| Calls | `groww_api.get_holdings_for_user()` / `.get_positions_for_user()` (live broker holdings/positions — Groww still used for actual account state, not just FYERS-for-prices); `get_prediction_fn` (= `bot.get_prediction`, full ML+news+context signal per holding); `fetch_live_price_fn` (= `bot.fetch_live_price`); `costs.net_profit`/`costs.min_profitable_move` (charges-aware P&L); `fundamental_analysis.get_fundamental_analysis`; `fii_tracker.format_institutional_holdings`; `commodity_tracker.get_commodity_impact`; internal `_apply_tijori_fallbacks()` (fills fundamentals/peers/commodity gaps from stored Tijori snapshots when live data is missing — "additive — live Groww/Screener data always wins when present", portfolio_analyzer.py:385-390). |
| When | On-demand per dashboard portfolio-analysis request (not scheduler-driven — no `scheduler.py` registration found). |
| Inputs | None from the caller besides the injected `groww_api`/prediction/price functions — pulls the FULL current holdings+positions from Groww each call. |
| Outputs / side effects | Returns dict only (`timestamp`, `summary`, `holdings[]`, `positions[]`) — no DB writes in this file. |
| Target/stop-loss logic | NOT a blind percentage: uses `prediction["long_term_trend"]` (5-year resistance/support/max/avg price from `bot.py`'s long-term-trend analysis) to set 3 target tiers (conservative = 5Y resistance, strategic = midpoint to all-time-high, optimistic = 95% of ATH) and picks the primary target by AI signal direction; falls back to `config.TARGET_PCT`/`STOP_LOSS_PCT` fixed percentages only when no 5Y data exists (portfolio_analyzer.py:237-297). |
| DB tables | None written directly; reads flow through `fundamental_analysis`/`fii_tracker`/`commodity_tracker`/Tijori (see their sections) — this file itself makes no direct DB calls. |
| Config / env | `config.DEFAULT_EXCHANGE`, `DEFAULT_PRODUCT`, `MAX_TRADE_QUANTITY`, `MAX_TRADE_VALUE`, `STOP_LOSS_PCT`, `TARGET_PCT` (imported constants, fallback-only for target/SL as noted above). |
| External services | None directly (Groww for holdings/positions is the only live account-state call; everything else is delegated to other already-documented modules). |
| Failure behaviour | Extremely defensive: every sub-section (prediction, fundamentals, Tijori fallback) individually try/excepted with explicit fallback values (e.g. missing prediction → `{"signal": "HOLD", "confidence": 0, "reason": "Prediction unavailable"}`; missing LTP → `price_unavailable: True` and `ltp: None` rather than silently substituting the average buy price, which the code explicitly notes "would render a cost price as though it were live" — portfolio_analyzer.py:159-169, a direct instance of engineering standard #7 "missing data must be visible"). |
| Minor code-quality note | `_analyze_stock` (lines 380-383) has a second, unreachable `except Exception as e:` clause duplicating the one immediately above it (lines 363-379) — harmless dead code, not a functional bug, but worth cleaning up if this function is touched again. |
| Blast radius | Purely advisory/display — feeds a dashboard panel only; does not feed `bot.get_prediction` or any auto-trade path (it CONSUMES `bot.get_prediction`, not the reverse). |
| Status | ACTIVE |

### `stock_search.py` — symbol/name autocomplete

| name | file:line | purpose | callers | status |
|---|---|---|---|---|
| `search_stocks(query)` | stock_search.py:91 | Autocomplete: matches `stocks` table directory (symbol-prefix then name-substring), then tops up from `MasterTicker` (full NSE directory, active-only) via `_search_nse_instruments`, capped at 20 results. Falls back to a small hardcoded `_FALLBACK_DIRECTORY` (34 symbols) if DB unavailable. | Presumed dashboard search box endpoint in app.py (not individually re-verified in this pass — UNKNOWN exact route). | ACTIVE |
| `get_all_stocks()` / `get_stock_name()` / `validate_symbol()` | stock_search.py:118-136 | Directory helpers over the same `stocks`-table-or-fallback source. | UNKNOWN callers (not traced) | ACTIVE (assumed) |

Note: `_search_nse_instruments` explicitly documents that it searches the full `master_ticker_table` (all NSE tickers) for autocomplete purposes only — matching a symbol there does NOT mean it can be added to the watchlist; `/api/watchlist/add` separately re-validates against `MasterTicker.instrument_type=="EQ"` and `fyers_resolution_status=="resolved"` (stock_search.py:44-50, cross-checked against app.py:3969-3976).

### Three overlapping "thesis" subsystems — `stock_thesis.py`, `thesis_manager.py`, `thesis_analyzer.py`

These three files are easy to conflate; they are NOT three views of one system — one pair intentionally shares a table, and the third is an orphaned relic pointing at a different, undocumented table.

#### `stock_thesis.py` (130 lines) + `thesis_manager.py` (231 lines) — intentionally unified

| Field | Detail |
|---|---|
| What / Why | Two independent modules, each with its own DB read/write functions, that **deliberately share one table**: `db_manager.StockThesis` (`__tablename__ = "stock_theses"`), whose class docstring literally says "Unified thesis table — personal outlook + investment projection" (db_manager.py:438-439) and whose `comments` column is annotated "# thesis_manager comments field" (line 449) — i.e. the schema was consciously merged to hold both modules' fields in one row, keyed by `symbol` (unique). `stock_thesis.py` owns the narrative fields (`thesis_text`, `timeframe`); `thesis_manager.py`'s `Thesis`/`ThesisManager` class owns the projection fields (`target_price`, `entry_price`, `quantity`, `comments`) and adds `calculate_projection()` (charges-aware target P&L via `costs.net_profit`, same helper `portfolio_analyzer.py` uses). |
| Used by (callers) | `stock_thesis.py` → `GET/POST/DELETE /api/thesis[/<symbol>]` (app.py:5308-5357). `thesis_manager.get_manager()` → `GET/POST/DELETE /api/my-thesis[/<symbol>]` + `GET /api/my-thesis/<symbol>/projection` (app.py:5362-5449+) — app.py's own section comment calls this out explicitly: `# ── Personal Investment Thesis (separate from stock thesis) ──` (app.py:5360). |
| **Gotcha (not a bug, but a real footgun)** | Each module only reads/writes ITS OWN subset of `stock_theses` columns and leaves the other's columns untouched on update — so a thesis created via `/api/thesis` (narrative-only) will have `NULL` `entry_price`/`quantity`/`comments` until someone also posts via `/api/my-thesis`, and vice versa. Both modules' `delete_thesis()` does a full row DELETE (not a partial-field clear), so deleting via EITHER endpoint destroys BOTH systems' data for that symbol — a user who thinks of "my narrative thesis" and "my price-target thesis" as separate could lose one while clearing the other. |
| DB tables | Read/write `stock_theses` (both); JSON file backups: `stock_thesis.json` (`stock_thesis.py`) and `.theses.json` (`thesis_manager.py`) — TWO SEPARATE backup files, each only capturing its own module's view of the data (fallback path is used only if DB read/write fails). |
| Failure behaviour | Both fail over DB→JSON gracefully; `thesis_manager._save_to_db` failures are logged at debug and swallowed (non-fatal — JSON backup still written). |
| Blast radius | `stock_theses` IS in `symbol_purge.KEEP_TABLES` (kept on watchlist removal — "the user's own writing" — symbol_purge.py:64), so removing a stock from the watchlist does NOT delete its thesis data from either system. |
| Status | Both ACTIVE, wired to distinct, clearly-separated API namespaces. **`stock_theses` is the live target of BOTH `/api/thesis` (stock_thesis.py) and `/api/my-thesis` (thesis_manager.py)** (VERIFIED: thesis_manager.py:110-125,158-170,202 and stock_thesis.py:18-114 both read/write `StockThesis`); it currently holds **0 rows**. The Database section's earlier claim that `theses` is the store read/written by thesis_manager.py, and that `stock_theses` is an unfinished migration target, was WRONG — this section's account is the correct one. |

#### `thesis_analyzer.py` (209 lines) — ORPHANED relic pointing at a different, undocumented table

| Field | Detail |
|---|---|
| What / Why | `ThesisAnalyzer.analyze_thesis_performance()` reads a thesis by `id` from a table called **`theses`** (singular-different-schema, NOT `stock_theses`) — columns `id, symbol, entry_price, target_price, quantity, created_date, current_price, last_updated` — joins it against `stock_prices` history to compute return/progress-to-target/max-min price, then upserts a row into `thesis_analysis` (a table that IS in `symbol_purge.PURGE_TABLES`, unlike `theses` itself — see contradiction below). |
| Used by (callers) | `GET /api/thesis/<symbol>/performance` (app.py:5634-5670) — this endpoint does its OWN raw `SELECT * FROM theses WHERE symbol = %s` first (not through any shared helper), then calls `ThesisAnalyzer(db_url).analyze_thesis_performance(thesis["id"])`. |
| **VERIFIED FROM DATABASE (LAST VERIFIED: 2026-09-27)** | `SELECT count(*) FROM information_schema.tables WHERE table_name='theses'` → 1 (table exists). `SELECT * FROM theses` → exactly **1 row**: `id=1, symbol=ASIANPAINT, entry_price=2250.39, target_price=3500, quantity=16, created_date=2025-09-30`. |
| **CONFIRMED ORPHAN / write-path missing** | Grepping the entire repo (`.py`/`.sql`) for `INSERT INTO theses`, a SQLAlchemy `__tablename__ = "theses"` model, or any `CREATE TABLE theses` finds **nothing** — there is no code path anywhere in this codebase that can create a new row in `theses`. The one existing row (ASIANPAINT) must have been inserted manually (direct SQL / since-removed script) rather than through the app. `thesis_analyzer.update_current_price()` can UPDATE an existing row's `current_price`, but nothing can INSERT a new one. Practically: `GET /api/thesis/ASIANPAINT/performance` works today (the one relic row), but the feature is otherwise **dead for every other symbol** and has no UI path to create a new entry — a classic "looks like a feature, is actually a fossil" trap for a future session that sees the working endpoint and assumes the write side exists too. |
| DB tables | Reads `theses`, `stock_prices`; writes `thesis_analysis` (upsert by `thesis_id`, `ON CONFLICT (thesis_id) DO UPDATE`). |
| **CONTRADICTION with symbol_purge.py** | `symbol_purge.PURGE_TABLES` includes `"thesis_analysis": ["symbol"]` (deleted on watchlist removal) but does **not** list `theses` at all — neither in `PURGE_TABLES` nor `KEEP_TABLES` (only `"theses", "stock_theses"` appear together in `KEEP_TABLES` per symbol_purge.py:64 — re-checking: yes, `"theses"` IS actually listed in `KEEP_TABLES`, so it IS classified, just as KEEP not PURGE). Removing ASIANPAINT from the watchlist today would therefore delete its `thesis_analysis` row (PURGE) but keep its `theses` row (KEEP) — leaving an orphaned `theses` row with no matching `thesis_analysis`, which is at least consistent with "financial-history-like records are kept," though `theses` (a price TARGET, not a trade record) sits awkwardly in the same KEEP bucket as `trade_journal`/`paper_trades`. |
| Status | **RETIRED / ORPHANED in practice** — reachable through one working endpoint for one legacy row, no functioning create path, not scheduler-driven, not referenced by any other module in this pass. |

### Brokerage cost system — `cost_scraper.py`, `cost_updater.py`, and `costs.py` (consumer)

**Top-line finding, DB-VERIFIED (LAST VERIFIED: 2026-09-27):** the automated cost-scraper pipeline runs successfully on schedule and logs success, but **writes to `config_settings` keys that `costs.py` (the actual cost-calculation engine used for real trade P&L/breakeven math) never reads.** The scraper's output has had zero effect on live cost calculations since the system was built. This directly matches CLAUDE.md's cited "confident answers built on unverified sources are worse than 'I haven't checked'" caution — the logs say "✓ Database updated successfully" every 45 days while nothing downstream changes. (Runs happen every 45 days AND once after every app restart — the last two were 2026-08-24 and 2026-09-27.)

| Field | Detail |
|---|---|
| Where | `cost_scraper.py` (571 lines, scrape+validate), `cost_updater.py` (601 lines, DB write+audit), orchestrated by `costs.update_cost_rates()` (`costs.py:98-227`). |
| Scheduler | `scheduler._task_cost_rate_update` → `costs.update_cost_rates()` every 3,888,000s (45 days), `initial_delay = random.randint(0, 170)` (scheduler.py:559-565, 1347-1348). **The 45-day interval is in-process only**: `last_run` is in-memory (`scheduler.py:60-71,1279-1283`), so the task also runs once after EVERY app restart. Evidence: the config rows were written 2026-08-24 and 2026-09-27 — 34 days apart, i.e. restarts, not the 45-day timer. |
| What `cost_scraper.scrape_groww_charges()` does | Fetches 3 Groww pages — `https://groww.in/pricing/stocks`, `https://groww.in/pricing/futures-and-options`, `https://groww.in/calculators/brokerage-calculator` (`GROWW_PRICING_URLS`, cost_scraper.py:72-76) — and regex-parses each for known rate patterns (`_parse_groww_pricing_page`). **7 of the 9 stock-page values are hardcoded unconditionally whenever the page parses — the page content is never consulted for them (VERIFIED 2026-09-28, cost_scraper.py:237-248):** for every pattern with a non-None fallback value, the code sets `charges[key] = fallback_value` **without running the regex at all** (the value is the one ALREADY hardcoded in `GROWW_CHARGES_CANONICAL`, e.g. `"0.025%"`); only the two `None`-fallback patterns — `brokerage_pct_per_order` and `brokerage_flat_per_order` — call `re.search` for a real capturing-group extraction. (The earlier description, that the code "checks whether a literal substring is still present", was wrong: it never checks.) If nothing at all is extracted from any page, it falls back wholesale to `GROWW_CHARGES_CANONICAL` (Jan-2026 snapshot, cost_scraper.py:35-69, 206-212) and still reports `success: True`. |
| `compare_costs()` / `validate_costs()` | Flag a >10% change as `"suspicious"` and flag a bounds violation, but **neither blocks the write** — `scrape()` logs "Will proceed with caution" and proceeds regardless (cost_scraper.py:502-506); `cost_updater.update_costs()` writes every key it's given regardless of the suspicious flag, only logging a warning (cost_updater.py:266-293) — a violation of the "guards must fail closed" principle (CLAUDE.md operational rule 8): a value that looks wrong (whether a real Groww rate change or a scraper bug) is written to the live config anyway. |
| What `cost_updater.update_cost_in_db()` writes | `config_settings` rows keyed `cost.{scraped_key}` where `{scraped_key}` is **lowercase snake_case exactly as it appears in `cost_scraper`'s output** (e.g. `cost.brokerage_flat_per_order`, `cost.stt_pct_delivery_sell`, `cost.exchange_charge_nse_pct`, `cost.gst_rate`, `cost.stamp_duty_pct_delivery_buy`, `cost.stt_fno_sell`, `cost.dp_charge_delivery_groww` — 18 keys observed). The **value is stored as a JSON blob**, not a plain number: `{"value": 20.0, "data_type": "float", "unit": "₹", "min_value":..., "max_value":..., "category":..., "source_url": "https://groww.in/charges", "last_verified_date": "..."}` (cost_updater.py:157-170). |
| What `costs.py` actually reads | `costs._load_rates()` reads `config_settings` keys `cost.{UPPERCASE_CONSTANT_NAME}` — e.g. `cost.BROKERAGE_PER_ORDER`, `cost.STT_DELIVERY_PCT`, `cost.STT_INTRADAY_SELL_PCT`, `cost.EXCHANGE_TXN_NSE_PCT`, `cost.EXCHANGE_TXN_BSE_PCT`, `cost.SEBI_FEE_PCT`, `cost.GST_PCT`, `cost.STAMP_DUTY_DELIVERY_PCT`, `cost.STAMP_DUTY_INTRADAY_PCT`, `cost.DP_CHARGES`, `cost.BROKERAGE_INTRADAY_PCT` (costs.py:26-38, 45-55) — and does `float(val)` directly on the DB value, i.e. it expects a **plain numeric string**, not a JSON blob. These 11 keys are seeded ONCE by `costs.seed_cost_rates()` (called at app startup, app.py:801-802) and otherwise **never written by anything else in the codebase** — no other module writes `cost.BROKERAGE_PER_ORDER` etc. |
| **VERIFIED FROM DATABASE** (`psql -U postgres -h localhost -d grow_trading_bot -c "SELECT key, value, updated_at FROM config_settings WHERE key ILIKE 'cost.%' ORDER BY key;"`, run 2026-09-27) | The table holds **both** key families side by side, proving the mismatch is real and live, not a hypothetical reading of the code: e.g. `cost.BROKERAGE_PER_ORDER` = `"20.0"` (plain string), `updated_at = 2026-03-30 20:19:55` (the one-time seed — every UPPERCASE key shares this exact same timestamp, confirming none has been touched since) vs. `cost.brokerage_flat_per_order` = `{"value": 20.0, ...}` (JSON), `updated_at = 2026-09-27 03:51:53` (today — the scraper just ran, hours before this audit). Other lowercase rows date to 2026-08-24 (an earlier scraper run). **All 11 of `costs.py`'s actual UPPERCASE keys are frozen at their 2026-03-30 seed values; none has ever been updated by the scraper.** (By coincidence several values happen to still match — e.g. both `BROKERAGE_PER_ORDER` and `brokerage_flat_per_order` currently read 20.0 — but `EXCHANGE_TXN_NSE_PCT`=0.00345 (seeded) vs the scraped `exchange_charge_nse_pct`=0.00297 already **disagree today**, and `costs.py` is using the former.) |
| A THIRD, separate scraper exists, dormant | If `costs.update_cost_rates()`'s primary workflow (`cost_scraper`+`cost_updater`) raises ANY exception, `costs.py` has its own inline fallback scraper (costs.py:229-283) that hits a fourth URL (`https://groww.in/charges`, distinct from `cost_scraper.py`'s three) and — critically — **does** write to the correct UPPERCASE keys (`STT_DELIVERY_PCT`, `STT_INTRADAY_SELL_PCT`, `STAMP_DUTY_DELIVERY_PCT`, `DP_CHARGES` only — 4 of the 11) and correctly calls `reload_rates()` afterward. Because the primary workflow does NOT throw (it "succeeds" by the broken definition above), this fallback never runs, so even its narrower correct-key coverage never gets exercised in practice. |
| `reload_rates()` | Correctly implemented (clears `_cache_loaded`, re-reads all 11 UPPERCASE keys) and correctly invoked after both the primary workflow (costs.py:207) and the dormant fallback (costs.py:275), plus a manual admin path (`app.py:2091`, `costs.reload_rates()`). The reload mechanism itself is not the bug — it faithfully reloads from the keys nobody (in the live path) writes to. |
| DB tables | `config_settings` (all of the above); `cost_updater._ensure_audit_table_exists`/`_log_audit_trail`/`get_cost_history`/`rollback_costs` maintain a `cost_audit_log` table (created on demand) recording every scrape-driven update with old/new value, for potential rollback. **CORRECTED (VERIFIED 2026-09-28): `cost_audit_log` is structurally always empty — it does NOT function** (`SELECT count(*) FROM cost_audit_log` = 0 after 3 pipeline runs). Mechanism (cost_updater.py:141-146, 334-346; INFERENCE from code, consistent with the 0 rows): `old_value = float(existing.value)` fails on the stored JSON blob, so `old_value` becomes the JSON **string**; `_log_audit_trail` then computes `new_val - old_val` (float − str) → `TypeError` → the whole insert is rolled back ("Could not log audit trail"). On a first run `old_value` is `None` → the row is skipped. So: the first run skips, every later run crashes on float − str and rolls back; and the intended semantics ("writes only when a cost changes; 0 rows = no change detected") are wrong — it attempts an insert for every update, and 0 rows means the audit path is broken, not that nothing changed. `get_cost_history`/`rollback_costs` therefore have no history to read. |
| `cost_notifications` DB table (written via `cost_notifications.py`, see Scheduler/Ops section) | 1 row, created 2026-07-31 22:20. The pipeline wrote config rows on 2026-08-24 and 2026-09-27 (only caller: scheduler → `costs.update_cost_rates`, `costs.py:187-199`) yet left **no** notification row since, so `_log_dashboard_notification` has been failing or the notification step is not reached (cause UNVERIFIED; failures are only logged as warnings). |
| Consumers of `costs.py` (the correct, still-2026-03-30-frozen rates) | `bot.py` (cost-aware breakeven/`min_profitable_move` display in predictions), `portfolio_analyzer.py` (`costs.net_profit` for P&L-if-sold, target/stop-loss profit projections), `thesis_manager.Thesis.calculate_projection` (`costs.net_profit`), `fno_trader.py` (F&O order sizing — not independently re-verified in this pass). All of these have been computing costs against Groww's March-2026 rate snapshot for the life of the system, regardless of any real Groww rate changes since, and regardless of the scraper "successfully" running every 45 days. |
| Costs: paid vs free | Nothing in this subsystem requires a paid API — it's all HTML scraping of Groww's own public pricing pages, no API key. **EXTERNAL VERIFICATION REQUIRED** for whether Groww's actual current rates still match either key family's stored numbers (the whole point of the scraper, which isn't reaching its target). |
| Blast radius | Every profitability check, breakeven price, and net-P&L-if-sold figure shown anywhere in the dashboard is computed from March-2026 rates. If Groww has changed brokerage, STT, exchange charges, or GST since, every one of these figures is silently wrong by whatever that delta is — with no error, no log warning, nothing to indicate it (the scraper's own success logging actively obscures this). This is a strong candidate to flag as a real fix: either rename `cost_updater`'s write keys to match `costs.py`'s `_DEFAULTS`, or change `costs._load_rates()` to read the lowercase JSON-blob keys and parse the `"value"` field. |
| Status | Scraper + updater pipeline: ACTIVE (runs on schedule, "succeeds") but **functionally dead** for its stated purpose. `costs.py`'s actual rate cache: ACTIVE but **stale since 2026-03-30 seed**, unmaintained by automation. |

---

### Cross-cutting facts (for the maps)

**External services + endpoints used**
- Google News RSS (`news.google.com/rss/search`) — no key, used by `news_sentiment.py`, `world_news_collector.py`, `supply_chain_collector.py`, `commodity_tracker.py` (via `news_sentiment`).
- NewsAPI.org (`newsapi.org/v2/everything`) — needs `NEWS_API_KEY`, ~100 free req/day per module docstring (EXTERNAL VERIFICATION REQUIRED for current plan/pricing).
- RSS feeds (no key): Economic Times (markets + economy), LiveMint (markets + economy), MoneyControl (marketreports + business), NDTV Profit, Business Standard (markets + economy), Reuters (business + world), CNBC (top news + world), MarketWatch, Bloomberg Markets — full list/URLs in `news_sentiment.py` and `world_news_collector.py` sections above.
- Screener.in (no key, HTML scrape) — THREE still-active touch points: `auto_metadata.py` (name/sector/peers/about + industry pages), `fundamental_analysis.scrape_annual_financials` (P&L trend), `market_intelligence.scrape_shareholding` (FII/DII/promoter %). THREE retired touch points (return `{}` immediately, kept as dead code): `market_intelligence._scrape_peer_ratios`, `research_engine._scrape_screener_ratios`, `fundamental_analysis._scrape_screener`.
- Tijori Finance (`tijorifinance.com`, no key, HTML/embedded-JSON scrape) — `tijori_collector.py`, now the primary fundamentals/peer source (replacing retired Screener ratio scrapes).
- yfinance (no key) — `commodity_tracker.fetch_commodity_price` (single source of truth), tickers `CL=F` (Crude Oil), `TIO=F` (Iron Ore/Steel), `GC=F` (Gold), `ALI=F` (Aluminium), `ZNC=F` (Zinc), `BTU` (Coal), `USDINR=X`.
- Groww API (`growwapi`, needs `GROWW_ACCESS_TOKEN`) — still live for broker holdings/positions (`portfolio_analyzer.py`) and attempted (reliability UNVERIFIED) for shareholding via `fii_tracker.py`; Groww is NOT used for market-data prices any more (migrated to FYERS 2026-08-15, per scheduler.py comments).
- Groww public pricing pages (`groww.in/pricing/stocks`, `/futures-and-options`, `/calculators/brokerage-calculator`, and a 4th `groww.in/charges` used only by a dormant fallback) — `cost_scraper.py`/`costs.py`, no key.

**Env vars** (name, where read, sensitivity)
- `NEWS_API_KEY` — `config.py` → `news_sentiment.py`. Not secret-critical but a paid-tier key; value never printed.
- `GROWW_ACCESS_TOKEN`, `GROWW_API_KEY`, `GROWW_API_SECRET` — `.env`, read via `os.getenv` in `fii_tracker.py`/`market_intelligence.py`/others; SENSITIVE, values never printed (per COMMON_RULES).
- `DB_URL` — `.env`/`config.py`, read directly (bypassing `db_manager`) by `market_intelligence.py`, `research_engine.py` (weekly prices, shareholding, sector-momentum), `thesis_analyzer.py`, `symbol_purge.py`, `peer_analyzer.py`, `migrate_tijori_daily_snapshot.py`.

**config_settings keys read/written in this scope** (key — default — where)
- `news.cache_ttl_seconds`, `news.source.{google,newsapi,et_rss,moneycontrol,extra_rss,x_posts}` — all default "true"/600s — `news_sentiment.py`.
- `intel.request_delay_seconds` — default 5.0 — `market_intelligence.py`.
- `tijori.*` (12 keys, full list in the Tijori section) — `tijori_collector.py`.
- `fno.lot.{SYMBOL}`, `mcx.lot.{SYMBOL}`, `fno.stt.*`, `fno.exchange.*`, `fno.sebi_pct`, `fno.gst_pct`, `fno.stamp_duty_pct`, `fno.brokerage_*` — seeded once, never re-verified against NSE — `auto_metadata.py`.
- `cost.{UPPERCASE}` (11 keys, read by `costs.py`) vs `cost.{lowercase}` (18+ keys, written by `cost_updater.py`) — **see cost-system contradiction above, this is the headline finding of this section.**
- `earnings.last_qrev.{symbol}`, `tijori.last_collected.{symbol}` — cross-module signal: `scheduler._detect_new_quarter` compares the former to trigger an early Tijori refresh via the latter.

**DB tables read/written in this scope**
- Written: `news_articles`, `global_news`, `shareholding_patterns`, `peer_comparisons` (dead writer since 2026-09-12), `company_external_data`, `company_connections`, `external_slug_map`, `commodity_snapshots`, `disruption_events`, `analysis_cache` (`research_*`, `fundamentals_v2_*`, `geopolitical:*`), `stocks`, `stock_theses`, `theses` (no live writer — read/update only), `thesis_analysis`, `config_settings`, `cost_audit_log` (**nominally written, but structurally always empty — 0 rows; every insert fails and rolls back, see cost system section**), `cost_notifications` (1 row, none since 2026-07-31). Note `stock_theses` is the live target of both thesis APIs (currently 0 rows).
- Read-only (in this scope): `stock_prices`, `fyers_candles`, `master_ticker_table`.
- Orphaned/never-created (VERIFIED absent from `information_schema.tables`, 2026-09-28): `peers`, `peer_prices`, `peer_analysis` (`peer_analyzer.py` — `_ensure_peer_tables()` never invoked by any caller).

**Every timed/triggered execution in this scope** (WHEN → WHAT)
- Every 600s: `news_prefetch` → warm news-sentiment cache for `WATCHLIST`.
- Every 900s: `world_news`, `supply_chain` (commodity prices + disruption news).
- Every 1800s: `geopolitical` (commodity geopolitical news — **silently broken**, see bug below), `deep_analysis` (top-6 watchlist pre-warm), `tijori_daily_partners` (self-gated to once/IST-day post-close).
- Every 3600s: `cache_refresh` (fundamentals for all `stock_prices` symbols, boot-warmup-gated).
- Every 4h (14400s): `research_engine` batch (all active stocks).
- Every 6h (21600s): `tijori_refresh` (stale-symbol Tijori collection).
- Every 24h (86400s): `market_intelligence` (shareholding + retired peer step + seasonality).
- Every 7 days (604800s): `auto_metadata` (Screener name/sector/peer refresh for all stocks).
- Every 45 days (3,888,000s, in-process timer) **and once after every app restart**: `cost_scraper` → `costs.update_cost_rates()` — **writes to keys `costs.py` never reads (see above).**
- On watchlist add (`POST /api/watchlist/add`): `auto_metadata.refresh_stock_metadata` → `market_intelligence.collect_all_intelligence` → `tijori_collector.onboard_symbol` → (market-hours-gated) FYERS backfill → model training.
- On watchlist remove (`DELETE /api/watchlist/remove/<symbol>`): `symbol_purge.purge_symbol` — one-transaction delete across every table in this section's scope, financial/thesis/reference data kept.

**Rate limits & quotas**
- NewsAPI: circuit-breaker disables for 1h after 3 consecutive 429s (`news_sentiment.py`).
- Screener.in: no formal rate limiter; politeness via per-stock delays + "stop on first 403/429/503" (added after the 2026-09-12 blocking incident: 4 concurrent scrapers × 67 stocks × up to 7 pages every 6h ≈ 1,270 req/day, 67 rejected 429).
- Tijori: custom `_sleep_politely()` minimum-spacing limiter (config `tijori.request_delay_seconds`, default 2s) plus separate quotas for principal collection (`max_symbols_per_run`=10), partner refresh (`max_partner_snapshots_per_run`=12), and partner discovery (`max_partner_discovery_per_run`=15, deliberately smaller since discovery costs ~5x a refresh).
- yfinance/commodity fetches: bounded by a 2-worker `ThreadPoolExecutor` + 15s timeout in `commodity_tracker.py`.
- FYERS: governed by `fyers_client._request()` (documented in CLAUDE.md operational rule 9), consumed here by `bot.fetch_quote`/`fetch_live_price` calls throughout this scope (fundamentals, portfolio analyzer, deep analysis, peer prices).

**Data flows (INPUT → TRANSFORM → STORAGE → CONSUMER)** — representative examples
- Google/ET/MoneyControl/LiveMint/NDTV/BizStd RSS → sentiment-scored (`enhanced_nlp`/keyword+TextBlob) → `news_articles`/`global_news` → `bot.get_prediction` (news weight 0.20), `research_engine._score_sentiment`, `deep_analysis` narrative.
- Tijori company page → parsed JSON blocks → `company_external_data`/`company_connections` → `tijori_collector.get_fundamentals`/`get_supply_chain_intel` → `fundamental_analysis.py`, `research_engine.py`, `deep_analysis.py`.
- Screener.in name/sector/peers → `stocks` table → `deep_analysis` (sector news tags), `research_engine` (sector momentum — broken, see bug), `commodity_tracker` (commodity map).
- yfinance commodity price → `commodity_snapshots`/in-memory → `supply_chain_collector` (disruption severity), `commodity_tracker.get_commodity_impact` → `deep_analysis`, `research_engine`.
- Groww holdings/positions → `portfolio_analyzer._analyze_stock` (full prediction+fundamentals+cost stack) → advisory-only dashboard panel (no trade execution).

**Failure modes**
- Fail-open (missing data → neutral/absent, not an error): virtually every collector in this scope (news sources, commodity fetch, Tijori per-block parsing, fundamentals).
- Fail-closed / fail-fast (deliberately, to protect against a repeat incident): `market_intelligence.scrape_shareholding` stops the whole batch on first Screener 403/429/503; `symbol_purge.purge_symbol` refuses on any open position, treating an unreadable position store as blocking (not permissive).
- Silently broken (confirmed, not merely suspected): (1) `research_engine._score_sentiment`'s Sector Momentum sub-factor — queries a nonexistent `global_news.created_at` column (and also averages the varchar `sentiment` column instead of `sentiment_score`, so fixing only `created_at` is not enough), exception swallowed, always contributes neutral 50. (2) `commodity_tracker.collect_geopolitical_news` — calls `.get()` on a `NewsItem` dataclass (no such method), exception swallowed, never ingests a new article; all 7 `geopolitical:*` cache rows are empty lists and every commodity is reported `risk_level="low"` (fabricated — the truth is unknown). (3) The entire cost-scraper pipeline — see dedicated section above (incl. 7 of 9 scraped values hardcoded, and `cost_audit_log` structurally always empty).

**Dead / legacy / retired code**
- `market_intelligence._scrape_peer_ratios`/`collect_peer_comparison` (retired 2026-09-12, `peer_comparisons` table frozen).
- `research_engine._scrape_screener_ratios` (retired 2026-09-12).
- `fundamental_analysis._scrape_screener` + its scorer `_analyze_financials` (retired 2026-09-12; `_analyze_financials` has zero callers even before the retirement flag).
- `peer_analyzer.py` — entire module orphaned, no caller (VERIFIED); its 3 tables (`peers`, `peer_prices`, `peer_analysis`) do NOT exist in the live DB (VERIFIED).
- `thesis_analyzer.py` / `theses` table — a relic: read only by `/api/thesis/<s>/performance` (and one UPDATE in `thesis_analyzer.py:159`), reachable for one relic row (ASIANPAINT, inserted outside any known code path); no functioning create path. `stock_theses` (not `theses`) is the live thesis store.
- `supply_chain_collector.start_collector`/`_collector_loop` — dormant fallback-only thread, unused when the scheduler is healthy.

**Contradictions found (code vs config vs comments vs DB)**
1. Cost-scraper writes lowercase JSON-blob keys; `costs.py` reads uppercase plain-float keys — DB-verified live mismatch (headline finding).
2. `research_engine._score_sentiment` queries `global_news.created_at`, which doesn't exist in the ORM schema (`db_manager.py:180-196` only has `published_at`/`fetched_at`) — and additionally averages the varchar `sentiment` column (needs `sentiment_score`).
3. `commodity_tracker.collect_geopolitical_news` treats `NewsItem` dataclass instances as dicts — so all 7 geopolitical cache rows are empty and every commodity is reported `risk_level="low"` (fabricated; unknown in truth).
4. `market_intelligence.py`'s peer-ratio retirement left `collect_peer_comparison` wired into `collect_all_intelligence`/the watchlist-add pipeline, always producing `{"peers": {"count": 0}}` — harmless but slightly misleading log noise on every add/daily run.
5. Two intentionally-merged-but-independently-touched "thesis" UIs (`/api/thesis` vs `/api/my-thesis`) share one row per symbol; deleting via either path deletes both systems' data.
6. `symbol_purge.KEEP_TABLES` treats `theses` (a price target) the same as `trade_journal`/`paper_trades` (real financial history), which is defensible but not obviously the same category.

**Open unknowns**
- Whether `fii_tracker.get_shareholding_breakdown()`'s Groww `get_quote()` call ever actually returns non-empty shareholding fields in production (code is defensively written as if unsure) — not verified live in this pass.
- ~~Whether `peer_analyzer.py`'s `peers`/`peer_prices`/`peer_analysis` tables exist~~ — **RESOLVED 2026-09-28: they do NOT exist** (`information_schema.tables`).
- ~~Whether `migrate_tijori_daily_snapshot.py`'s partial unique index `uq_ext_symbol_type_day` is present/valid~~ — **RESOLVED 2026-09-28: present on `company_external_data`, `indisvalid = t`.**
- Why `cost_notifications` has received no row since 2026-07-31 despite cost-pipeline runs on 2026-08-24 and 2026-09-27 — cause UNVERIFIED (failures are only logged as warnings).
- Exact current Groww brokerage/STT/exchange/GST rates vs. what either `costs.py` (frozen 2026-03-30) or the scraper's lowercase keys hold — EXTERNAL VERIFICATION REQUIRED.
- Whether `bot.py`'s `research_engine.py` comment reference ("existing idiom in research_engine.py") was ever accurate, or always meant the `app.py` fan-out pattern found at `/api/watchlist/<symbol>/analysis` instead.

## Database (PostgreSQL grow_trading_bot)

Single-user (`users` has 1 row) Indian-equity trading system on Postgres, accessed almost
entirely through SQLAlchemy ORM in `db_manager.py` (1,972 lines, 24 `Base` models) plus one
model in `auth_manager.py` (`User`). A meaningful slice of tables are **raw-SQL only** — no ORM
model exists for them even though they hold live, actively-written data (`stock_prices`,
`shareholding_patterns`, `peer_comparisons`, `cost_audit_log`, `cost_notifications`,
`predictions`, `theses`, `thesis_analysis`). `fyers_candles` is the only partitioned table (32
yearly partitions, 1997–2028) and by far the largest object in the database. All dates below are
**LAST VERIFIED: 2026-09-27**, re-verified and corrected through 2026-09-28 21:57 IST via read-only
`SELECT`/`pg_class` queries. **Row-count caveat (corrected):** the counts first published in the
quick-reference table were `pg_class.reltuples` planner estimates, NOT `count(*)`; `pg_stat_user_tables`
shows `paper_trades` and `trade_journal` were never analyzed, so their `reltuples` were stale (e.g.
trade_journal said 22, exact is 26). The table below now carries exact `count(*)` values (2026-09-28
21:57 IST) where they were re-measured — marked "(exact)" — and `reltuples` estimates otherwise.

35 non-partition relations found live (34 regular tables + the `fyers_candles` partitioned
parent); 24 have an ORM model, 11 are raw-SQL-only (incl. the `fyers_candles` parent, which is
read via `text()` SQL in `CandleDatabase` rather than the ORM). Biggest drift found: two
**parallel, barely-connected auth systems** (session-cookie gate that runs the whole app, and a
JWT/`users` system whose `@require_auth` decorator gates only 5 routes — though `users` is the live
identity table behind the Google sign-in → cookie-session flow), and three **uuid `user_id`
columns with no ORM field and no code writer** (`refresh_tokens`, and undeclared `user_id` columns
on `trade_journal`/`pnl_snapshots`) — remnants of an on-hold multi-tenancy migration. The COMPLETE
ORM-vs-live-DB drift list (only 4 tables differ, VERIFIED 2026-09-28): `trade_journal` (+`user_id`
uuid), `pnl_snapshots` (+`user_id` uuid), **`trade_log` (8 ORM columns missing from the live table,
2 live-only columns)** and **`idempotency_keys` (ORM `content_type` column missing from the live
table — makes the duplicate-order guard INERT)**. Note `auth_sessions.user_id` and
`idempotency_keys.user_id` are `integer` (ORM-declared), unlike the uuid ones.

### Quick reference — every non-partition table

| Table | ORM model (file:line) | Rows ("(exact)" = `count(*)` 2026-09-28; otherwise `reltuples` estimate 2026-09-27, stale for never-analyzed tables) | Size | Status |
|---|---|---|---|---|
| fyers_candles (+32 partitions) | none — raw SQL, `db_manager.py:929-1132` (`get_fyers_candles_as_5min`/`get_fyers_1min`/`get_fyers_daily`) | ~70.8M across partitions (planner estimate — sum of partition `reltuples`; an exact full count is forbidden; 2026 alone: 19.0M) | ~22 GB total (sum of partition sizes; ≈ the ENTIRE database — `pg_database_size` is also 22 GB; earlier "~28 GB / ~61.9M" was wrong) | ACTIVE — primary market-data store |
| stock_prices | none — raw SQL | 101,502 (exact) | 80 MB | LEGACY — last write 2026-05-29, superseded by fyers_candles daily |
| company_external_data | `CompanyExternalData` db_manager.py:720 | 33,185 (exact) | 68 MB | ACTIVE, append-only (Tijori snapshots) |
| global_news | `GlobalNews` db_manager.py:180 | 74,016 (exact) | 59 MB | ACTIVE |
| news_articles | `NewsArticle` db_manager.py:157 | 45,454 (exact) | 37 MB | ACTIVE |
| pnl_snapshots | `PnLSnapshot` db_manager.py:616 | 45,253 (exact) | 8.4 MB | ACTIVE, but written only while `paper_trades.json` has OPEN trades (at most once per ~15s dispatch pass, market hours) — newest row 2026-09-22 09:32; a gap is expected while 0 trades are open |
| analysis_cache | `AnalysisCache` db_manager.py:469 | 227 | 3.3 MB | ACTIVE, DB-backed cache |
| master_ticker_table | `MasterTicker` db_manager.py:256 | 2,467 | 1.2 MB | ACTIVE, directory (not a collection trigger) |
| intraday_candles | `IntradayCandle` db_manager.py:79 | 2,850 | 904 kB | ACTIVE, post-close chart replay |
| company_connections | `CompanyConnection` db_manager.py:683 | 1,559 | 704 kB | ACTIVE |
| nse_instruments | `NSEInstrument` db_manager.py:236 | 2,464 | 448 kB | STATIC/manual — sole writer is the manual root script `load_nse_instruments.py` (idempotent upsert via `insert(...).on_conflict_do_update`, lines 13/19/41-48; not scheduled, no callers, re-runnable); earlier seeding by archived `import_nse_stocks.py` |
| trade_snapshots | `TradeSnapshot` db_manager.py:545 | 27 | 424 kB | ACTIVE (bot.py:844) |
| trade_journal | `TradeJournalEntry` db_manager.py:309 | 26 (exact; the earlier 22 was a stale `reltuples`, never current) — newest row 2026-09-11 | 320 kB | ACTIVE — SOURCE OF TRUTH for trades |
| paper_trades | `PaperTrade` db_manager.py:522 | 4 (exact; ids 591, 594, 597, 598 — earlier 8 was a stale estimate) | 312 kB | ACTIVE as a partial order-fill log — **NOT the source of truth**: `paper_trades.json` (26 records, 0 OPEN) is the operational source of truth for paper positions; the only reader of this table is the EOD Telegram summary |
| shareholding_patterns | none — raw SQL, market_intelligence.py:197 | 897 | 296 kB | ACTIVE, last write 2026-09-27 (today) |
| external_slug_map | `ExternalSlugMap` db_manager.py:746 | 585 | 296 kB | ACTIVE (tijori_collector.py:258) |
| peer_comparisons | none — raw SQL, market_intelligence.py:529 | 66 (exact) | 264 kB | FROZEN — last write 2026-09-12 (`_PEER_RATIOS_RETIRED=True`) |
| disruption_events | `DisruptionEvent` db_manager.py:132 | 22 | 176 kB | ACTIVE (supply_chain_collector.py:309) |
| config_settings | `ConfigSetting` db_manager.py:651 | 220 | 152 kB | ACTIVE — SOURCE OF TRUTH for runtime config |
| commodity_snapshots | `CommoditySnapshot` db_manager.py:111 | 7 | 112 kB | ACTIVE (supply_chain_collector.py:255) |
| auth_sessions | `AuthSession` db_manager.py:498 | 19 | 112 kB | ACTIVE — SOURCE OF TRUTH for "logged in" |
| cost_notifications | none — raw SQL, cost_notifications.py:278 (self-creates table) | 1 | 96 kB | STALLED — last write 2026-07-31; the cost pipeline ran on 2026-08-24 and 2026-09-27 but left no notification row (cause UNVERIFIED — failures are only logged as warnings) |
| stocks | `Stock` db_manager.py:201 | 67 | 96 kB | ACTIVE — SOURCE OF TRUTH for watchlist universe |
| candle_training_metadata | `CandleTrainingMetadata` db_manager.py:662 | 88 (exact; all `event_type='training'`, `model_version='both'`, 2026-03-31 → 2026-09-25; the earlier 43 was a stale estimate — the ML section's 88 is correct) | 80 kB | ACTIVE (db_manager.py:1923-1971), F&O retrain only |
| idempotency_keys | `IdempotencyKey` db_manager.py:771 | 0 | 80 kB | **MONEY-PATH GUARD IS INERT** — ORM `content_type` column is missing from the live table, so every claim INSERT fails and falls OPEN; 0 rows is the SYMPTOM, not "pruned clean" — see `idempotency_keys` section |
| users | `User` auth_manager.py:24 | 1 | 64 kB | ACTIVE — identity table for the live Google sign-in → cookie-session flow (`google_auth.py`, UNTRACKED file, creates/links rows); JWT decorator guards only 5 routes — see Drift |
| watchlist_notes | `WatchlistNote` db_manager.py:486 | 0 | 48 kB | ACTIVE (empty now; feature works) |
| cost_audit_log | none — raw SQL, cost_updater.py:393 (self-creates table) | 0 | 48 kB | **STRUCTURALLY ALWAYS EMPTY** — first run skips (no old value); every later run crashes on float − str in `_log_audit_trail` and rolls back (cost_updater.py:141-146, 334-346; inferred from code, consistent with 0 rows after 3 runs). It attempts an insert for every update, not only on a change — 0 rows does NOT mean "no change detected" |
| theses | none — raw SQL | 1 | 48 kB | RELIC — 1 row (ASIANPAINT), last write 2026-03-30; no INSERT path anywhere; read only by `/api/thesis/<s>/performance` (app.py:5653, thesis_analyzer.py:41,181; one UPDATE at thesis_analyzer.py:159) |
| refresh_tokens | **none — no ORM, zero code references anywhere** | 0 | 40 kB | **DEAD** |
| candles | `Candle` db_manager.py:56 | 0 | 32 kB | LEGACY/EMPTY — superseded by fyers_candles; `get_candles()` kept for old consumers |
| fyers_candles_2027 / _2028 | (partitions) | 0 | 32 kB ea | future partitions, pre-created |
| predictions | **none — no ORM, no INSERT found; "predictions" in code = in-memory var, not this table** | 0 | 24 kB | **DEAD** (table exists, nothing writes it) |
| stock_theses | `StockThesis` db_manager.py:438 | 0 | 24 kB | ACTIVE — the LIVE store: both `/api/thesis` (stock_thesis.py:18-114) and `/api/my-thesis` (thesis_manager.py:110-125,158-170,202) read/write it; currently 0 rows (nobody has saved a thesis) |
| thesis_analysis | none — raw SQL, thesis_analyzer.py:113 | 0 | 16 kB | Model absent; writer exists but table currently empty |
| trade_log | `TradeLogEntry` db_manager.py:403 | 0 | 16 kB | WIRED but BROKEN by schema drift: `_persist_trade_log_entry` (bot.py:121-138) `session.add(TLE(...)); commit()` is called at bot.py:1591, 1761, 1850 — every INSERT (and the boot `_load_trade_log` SELECT) fails with UndefinedColumn because the live table predates the ORM model; failures are swallowed at DEBUG. In-memory list is what's actually served, and it is lost on every restart |

### Money-path & auth tables — full detail

#### `trade_journal` — SOURCE OF TRUTH for all trades (actual + paper)
| Field | Detail |
|---|---|
| Where | `db_manager.py:309-399` (`TradeJournalEntry`) |
| Purpose | Unified pre/post-trade record, replaces old `trade_journal.json` as source of truth |
| Writers | `app.py:3442`, `app.py:3609` (manual/API trade creation); `trade_journal.py:190-249` `_save()` — writes DB first, **then** mirrors to `trade_journal.json` only after DB commit succeeds (trade_journal.py:250-260) |
| Readers | `trade_journal.py` (in-memory `_journal` list is loaded from DB at boot then kept in sync); `app.py` trade/journal endpoints |
| Columns | id, trade_id (unique), status (OPEN/CLOSED), symbol, side, quantity, trigger, **model_source** (nullable — added after cash-XGBoost; NULL means pre-dates model attribution, db_manager.py:320-323), is_paper, entry_time, entry_price, exit_time, exit_price, exit_reason, signal, confidence, stop_loss, projected_exit, peak_pnl, actual_profit_pct, breakeven_price, pre_trade_json, post_trade_json, created_at, updated_at, **user_id (uuid, live DB only — no ORM field, no code writer found)** |
| Indexes | PK id; unique `trade_id` (`uk_trade_id`/`ix_trade_journal_trade_id`); `idx_journal_symbol_status`, `idx_journal_is_paper`, `ix_trade_journal_model_source`, `idx_trade_journal_user_id` |
| Deletion | Never deleted by symbol_purge (symbol_purge.py:63 `KEEP_TABLES` — financial history is never deleted by a UI action) |
| Blast radius | Any dashboard trade view, P&L, model-attribution reporting |
| Status | ACTIVE |

#### `paper_trades` — partial order-fill log (NOT the source of truth for paper positions)
| Field | Detail |
|---|---|
| Where | `db_manager.py:522-540` (`PaperTrade`) |
| Writers | `bot.py:1549-1550` inside `_paper_trade()` (bot.py:1473), which per CLAUDE.md operational rule #2 also writes `paper_trades.json` — **never exercise this write path against live data for testing** |
| Readers | **Only the EOD Telegram summary** (`scheduler.py:1059-1084`, the sole reader of the `PaperTrade` model). Positions, exits, the duplicate-entry guard, `record_pnl`, auto-close and `symbol_purge` all read **`paper_trades.json`** via `PaperTradeTracker` (`paper_trader.py:37-104`). |
| Source of truth (CORRECTED, VERIFIED 2026-09-28) | The operational source of truth for paper positions is **`paper_trades.json`** (26 records, 0 OPEN). The DB table is a partial order-fill log — **4 rows vs 26 JSON trades** — so the EOD summary (its only reader) under-reports. |
| Columns | id, symbol, side, quantity, price, segment (CASH/FNO/COMMODITY), product, order_type, status, paper_order_id, model_source, charges, remark, created_at |
| Indexes | PK id; `ix_paper_trades_symbol`, `ix_paper_trades_model_source` |
| Deletion | Kept by symbol_purge (financial history) |
| Status | ACTIVE as a write-only-ish fill log (4 rows; `pg_stat_user_tables` shows it was never analyzed, so `reltuples` said 8) |

#### `trade_snapshots` — full context at trade time (chart replay)
`db_manager.py:545-611`. Writer: `bot.py:844`. 27 rows. Holds candles/indicators/news/reasoning as
JSON text blobs keyed by `paper_order_id`. Kept by symbol_purge. ACTIVE.

#### `pnl_snapshots` — unrealised P&L time series
`db_manager.py:616-646`. Writer: `scheduler.py:1023` (`session.add(snapshot)`; the `PnLSnapshot(` is
constructed at ~1014) inside `_task_record_pnl`. It is written at most once per ~15s dispatch pass
(the "every 5s" docstring is bounded by the 15s scheduler tick), only during market hours, and **only
while `paper_trades.json` has OPEN trades** (currently 0), so the newest row is 2026-09-22 09:32 and a
gap in the P&L chart is expected, not a failure. 45,253 rows exact (2026-09-28; the first pass's
43,511 was a `reltuples` estimate). Live DB has a **`user_id uuid` column with no ORM
field** (drift — see below). ACTIVE.

#### `idempotency_keys` — duplicate-order guard
| Field | Detail |
|---|---|
| Where | `db_manager.py:771-807` (`IdempotencyKey`); claim/complete/fail logic `db_manager.py:1569-1791` |
| What/Why | One row per client `Idempotency-Key` scoped to an endpoint; blocks a retried buy/sell from placing a second order. Insert-uniqueness on (key,scope) is the concurrency primitive |
| Failure behaviour | INSERT path fails OPEN (unreachable table = revert to pre-feature behaviour); every path AFTER a duplicate is proven fails CLOSED (see db_manager.py:1581-1589). **This fail-OPEN path is what is firing today** — see "Live state" below. |
| **Live state — GUARD IS INERT (money path; VERIFIED FROM CODE + LIVE SCHEMA + library source, 2026-09-28; not by executing a request)** | The ORM `IdempotencyKey.content_type` column (db_manager.py:798, committed in HEAD) is **absent from the live table** (`information_schema` diff; re-checked 2026-09-28 22:06: still 10 live columns, no `content_type`, 0 rows). The add-column script `migrate_idempotency.py` (commit 096e523, 2026-08-06) is not called by anything and was evidently never run. SQLAlchemy 2.0.49 renders every default-less nullable column as an explicit NULL in ORM INSERTs (`mapper._insert_cols_as_none`, sqlalchemy/orm/persistence.py:367-379), so `claim_idempotency_key`'s INSERT (db_manager.py:1608-1614) raises `UndefinedColumn`, which is caught by the generic `except Exception` (db_manager.py:1626-1631) and returns `IDEM_CLAIMED` (fail OPEN). **Result: the idempotency guard on `/api/buy` etc. is currently INERT — every claim fails on the missing column and falls open, so retried orders are not de-duplicated.** 0 rows is the symptom, not "pruned clean". Fix = run `migrate_idempotency.py` (needs user approval). |
| Pruning | `prune_idempotency_keys(retention_hours=48)` db_manager.py:1774 (prunes an always-empty table today) |
| Status | **INERT — the guard does not de-duplicate anything** (0 rows because every claim INSERT fails on the missing `content_type` column, NOT because pruning cleaned it) |

#### `auth_sessions` — SOURCE OF TRUTH for "logged in"
| Field | Detail |
|---|---|
| Where | `db_manager.py:498-517` (`AuthSession`); all logic in `auth_session.py` |
| What/Why | One row per browser/device session; cookie carries only a random ID, table stores its SHA-256 (`sid_hash`) so a DB read never yields a usable credential. Two independent clocks on one row: `expires_at` (account layer, default 30d) and `pin_verified_at`+`idle`/`absolute` (PIN layer, default 12h abs / 30min idle) |
| Schema evolution | `auth_session.ensure_schema()` (auth_session.py:92-118) added `pin_verified_at` at runtime via `ALTER TABLE` outside any ORM migration — backfilled existing rows from `created_at` once, then never touches NULL again (NULL is a real state) |
| Writers | `auth_session.create()/promote()/_touch()/revoke()` |
| Readers | `auth_session.load()`, cached in-process for `CACHE_SECONDS=30` |
| Gates | `app._require_session()` (app.py:230) — the **real** gate for the whole app (all `/api/*`, all GETs, SSE); allowlist is `_PUBLIC_PATHS` (app.py:221-222) |
| Status | ACTIVE, primary auth mechanism |

#### `users` / JWT auth (`auth_manager.py`) — marginal, parallel system
| Field | Detail |
|---|---|
| Where | `auth_manager.py:24-76` (`User` model, separate `Base` import from `db_manager`) |
| What/Why | Email/password + Google-OAuth signup with JWT bearer tokens (`generate_jwt`/`verify_jwt`, `require_auth` decorator) |
| Routes gated by it | `@require_auth` decorates **exactly 5 routes**: `/dashboard`, `/setup`, `/api/auth/verify`, `/api/auth/profile`, `/api/auth/set-api-key` (app.py:1076-1187) — signup/login are NOT decorated, and it does **not** gate the rest of the app |
| Live use of `users` | **`users` is the identity table for the live Google sign-in → cookie-session flow**: `google_auth.py` (UNTRACKED file) `_find_or_create_user` queries/creates `auth_manager.User` rows (google_auth.py:173-201) and passes `users.id` into `auth_session.create(user_id, ...)` (google_auth.py:229-230; `auth_sessions.user_id` is `integer`). It also sends a Telegram message "Signed in with Google: ..." on every sign-in (google_auth.py:242-245). |
| Contradiction | The JWT decorator is a second, largely-disconnected auth layer from `auth_session.py`. `users` has exactly 1 row (LAST VERIFIED 2026-09-27) — the table is live (Google sign-in creates and links rows), but the JWT layer is not the system's real gate. `/api/auth/demo` (app.py:1207) is explicitly disabled by default because it "hands out a valid JWT to any caller ... which also defeats @require_auth on every protected route" |
| password_hash | SHA-256+salt via `hashlib` (auth_manager.py:44-51) — **not** bcrypt/scrypt; distinct from the PIN hashing CLAUDE.md/memory references for the lock-screen (scrypt PIN work is planned separately) |
| Status | ACTIVE — `users` is live (Google sign-in); the JWT layer (`@require_auth`, 5 routes) is marginal / likely legacy from an earlier multi-tenant plan |

#### `refresh_tokens` — DEAD
`id uuid`, `user_id uuid`, `token_hash`, `expires_at`, `revoked`, etc. **Zero references anywhere
in tracked, non-archived Python** (`git grep` for `refresh_tokens`/`RefreshToken` returns nothing
outside the schema itself) and 0 rows. No ORM model. This is inert schema, likely a remnant of the
same on-hold multi-tenancy/JWT-refresh design as the stray uuid `user_id` columns on
`trade_journal`/`pnl_snapshots`. Confirm before ever building on it — it may be a placeholder for
Phase 1/2 of the multi-tenancy plan (memory: `multi-tenancy-phase-plan.md`, Phase 0 done, 1-2 on
hold).

#### `config_settings` — SOURCE OF TRUTH for runtime config
| Field | Detail |
|---|---|
| Where | `db_manager.py:651-659` (`ConfigSetting`); helpers `get_config`/`get_configs`/`get_configs_prefix`/`set_config` db_manager.py:1444-1526 |
| Read pattern | Memoized 30s per-key cache (`_config_cache`, `_CONFIG_CACHE_TTL=30.0`, thread-lock protected); `set_config` invalidates immediately and fires `change_feed.notify("config", key=key)` so open dashboards see the change without waiting out the TTL |
| Columns | id, key (unique), value (text — caller casts), description, updated_at |
| Rule | Never call `get_config` in a loop — use `get_configs()`/`get_configs_prefix()` (CLAUDE.md standard #8, matches code comment at db_manager.py:1465-1467) |
| Status | ACTIVE, 220 keys |

### Reference / watchlist tables

#### `stocks` — SOURCE OF TRUTH for the active watchlist universe
`db_manager.py:201-233`. Replaces old hardcoded `STOCK_DIRECTORY`/`SECTOR_MAP`/`COMPETITORS`/
`COMMODITY_MAP`/`SYMBOL_NAMES` dicts. 67 rows (matches CLAUDE.md's stated "67 stocks in database,
10 in config, 57 added dynamically"). Helpers: `get_all_stocks`, `get_stock`, `get_sector_map`,
`get_competitors`, `get_commodity_map`, `get_symbol_names` (db_manager.py:1286-1343). Seeded once
via `seed_stocks()` (db_manager.py:1795-1916, no-ops if any row exists). Driven off `is_active`
flag; deletion via `symbol_purge.py` when a stock leaves the watchlist (full cascade — see Drift/
Deletion section below). ACTIVE.

#### `master_ticker_table` — provider-identifier directory, NOT a collection trigger
`db_manager.py:256-304`. Maps `nse_ticker` → FYERS/Tijori identifiers. Explicitly documented
(db_manager.py:265-267) as separate from `stocks` (the active scheduler/Tijori/research universe)
— adding a row here fetches nothing. Writer: `build_master_ticker_table.py:202/236`. Read by
`fyers_fill_1min_gap.py`, `fyers_historical_backfill.py`, `fyers_market_data_provider.py`,
`fyers_ws_client.py`. ACTIVE.

#### `nse_instruments` — STATIC search/autocomplete directory
`db_manager.py:236-253`. **Writer = the manual root script `load_nse_instruments.py`** (tracked;
idempotent upsert via `insert(...).on_conflict_do_update`, load_nse_instruments.py:13,19,41-48;
re-runnable; not scheduled, no callers). (The earlier claim "no writer exists in live code" was
wrong.) Populated historically by `archive/migration_scripts/import_nse_stocks.py`.
Docstring confirms this is deliberate: "search/autocomplete only ... adding a row here does not
add it to any active tracking loop." Treat as static reference data unless `load_nse_instruments.py`
is re-run by hand.

### Candle / price data

#### `fyers_candles` (partitioned parent, 32 yearly partitions `fyers_candles_1997`…`fyers_candles_2028`)
No ORM model — read via raw `text()` SQL in three `CandleDatabase` methods:
`get_fyers_candles_as_5min`, `get_fyers_1min`, `get_fyers_daily` (db_manager.py:954-1132). PRIMARY
market-data store today. Schema origin: `db/fyers_candles_schema.sql` (marked in its own header as
"NOT YET EXECUTED ... proposal", but the live DB has all 32 partitions built from it, so it *was*
executed — the file header is now stale/aspirational, a doc-vs-reality mismatch). Columns: id
(bigserial), symbol, exchange (default NSE), provider (default FYERS), source_type
(historical/websocket), resolution ('5S'..'240','D','1W','1M'), ts (timestamptz, candle open),
open/high/low/close (double), volume/open_interest (bigint, nullable), created_at. PK
`(id, ts)` (composite — required by Postgres for a partitioned table's PK to include the
partition key). Unique `(symbol, provider, resolution, ts)`. CHECK constraint enforces OHLC
sanity. **Never full-scan** — bound every query by `ts`/`symbol`/`resolution` (COMMON_RULES.md,
also documented in-code at db_manager.py:986-988). Known historical bug, now fixed: '5S' and '1'
resolution tiers overlap (2026-07-13 to 2026-08-14), which double-counted volume until
`get_fyers_candles_as_5min` added tier-precedence logic (db_manager.py:914-926, 1028-1043). Largest
partition: `fyers_candles_2026` at 19.0M rows / 6.28 GB (LAST VERIFIED 2026-09-27; confirmed 2026-09-28: 19,039,264 rows / 6282 MB). **Totals (corrected):** the 32 partitions sum to **~22 GB** (≈ the entire database — `pg_database_size` is also 22 GB) and **~70.8M rows by planner estimate** (sum of partition `reltuples`; an exact full count is forbidden by the bounded-read rule) — NOT "~28 GB / ~61.9M". **No `fyers_candles` rows exist for Monday 2026-09-28** (bounded probes on RELIANCE, TCS, INFY, HDFCBANK, SBIN; RELIANCE's last 5S bar is 2026-09-25 15:29:55; latest trading data in the DB is Fri 2026-09-25) — cause UNVERIFIED (market holiday vs collection outage); if an outage, it is also why the 2026-09-28 22:06 GBC retrain "succeeded" (see ML section).

#### `candles` — LEGACY, now empty
`db_manager.py:56-76` (`Candle`). 0 rows (LAST VERIFIED). `get_candles()` (db_manager.py:1134-1175)
kept "unchanged for consumers that still legitimately read the legacy table" but there is nothing
left to read. `db_cli.py` (`sync`/`prune`/`clear`/`export` commands) still targets this table —
those CLI commands are effectively no-ops against current data.

#### `stock_prices` — LEGACY, last write 2026-05-29
No ORM model; raw SQL throughout (`fetch_google_prices.py:106`, `price_fetcher.py:129`,
`app.py:5466` `fetch_stock_prices()`). 101,502 rows (exact, 2026-09-28; the first pass's 104,532 was a `reltuples` estimate) / 80 MB — the second-largest non-fyers table.
`bot.py:692-707` and `app.py:3952-4092` both have explicit comments that this table "stopped
receiving data" / is "disabled below, not deleted" with call sites noting what still assumes it's
empty. `backtester.py:105`, `research_engine.py:116`, `market_intelligence.py:576-597` still read
it for 5-year weekly backtests — so it is read-legacy, not fully dead. Kept out of symbol_purge's
delete set at the table level? **No** — it IS in `PURGE_TABLES` (symbol_purge.py) and gets rows
deleted when a symbol leaves the watchlist, despite no longer being written.

#### `intraday_candles` — post-close chart replay
`db_manager.py:79-106`. 2,850 rows, last `trading_date` 2026-09-09. ACTIVE, populated once per
trading day after close for entry/exit visualisation.

### News / commodity / company-external tables
All ACTIVE, all append-only or upsert-on-key:
- `news_articles` (`NewsArticle`, db_manager.py:157) — writer `news_sentiment.py:67`; dedup key `(symbol, title_hash)`, never re-fetched once stored.
- `global_news` (`GlobalNews`, db_manager.py:180) — writer `world_news_collector.py:219`; unique `title_hash`.
- `commodity_snapshots` (`CommoditySnapshot`, db_manager.py:111) / `disruption_events` (`DisruptionEvent`, db_manager.py:132) — writer `supply_chain_collector.py:255/309`; both keep a `prev_*` column pair to diff against the last refresh.
- `company_connections` (`CompanyConnection`, db_manager.py:683) / `company_external_data` (`CompanyExternalData`, db_manager.py:720) / `external_slug_map` (`ExternalSlugMap`, db_manager.py:746) — all written by `tijori_collector.py` (lines 258, 498, 712). `company_external_data` is explicitly append-only (docstring: "every scrape adds a new snapshot"); a partial unique index `uq_ext_symbol_type_day` (added by `migrate_tijori_daily_snapshot.py`) caps it to one non-`collection_attempt` row per (symbol,data_type,day) while leaving history and attempt-audit rows untouched.
- `shareholding_patterns` — no ORM; raw SQL writer `market_intelligence.py:197`, unique on `(symbol, quarter_date)`. Last write 2026-09-27 (today) — actively current.
- `peer_comparisons` — no ORM; raw SQL writer `market_intelligence.py:529`, unique `symbol` (one row per symbol, overwritten each refresh — not append-only, unlike `company_external_data`). Last write 2026-09-12.

### Cost-tracking tables (self-managing, no ORM)
- `cost_audit_log` — `cost_updater.py` creates its own table (`_create_table`-style function at cost_updater.py:380-417). **CORRECTED: it is structurally always empty, not "empty because no change was detected".** The first run skips the row (no old value); every later run computes `new_val - old_val` with `old_val` being the stored JSON *string* (`float(existing.value)` fails on the JSON blob, cost_updater.py:141-146), raising `TypeError` in `_log_audit_trail` (cost_updater.py:334-346), and the whole insert is rolled back ("Could not log audit trail"). It attempts an insert for every update (not only for changes). `SELECT count(*) FROM cost_audit_log` = 0 (INFERENCE from code, consistent with 0 rows after 3 pipeline runs).
- `cost_notifications` — same pattern, `cost_notifications.py:267-297` self-creates table; 1 row, created 2026-07-31 22:20 — and **no row since**, although the pipeline wrote config rows on 2026-08-24 and 2026-09-27 (only caller: scheduler → `costs.update_cost_rates`, `costs.py:187-199`). `_log_dashboard_notification` has been failing or the notification step is not reached (cause UNVERIFIED; failures are only logged as warnings).
Both bypass the ORM entirely; `CLAUDE.md`'s "Config over constants" standard doesn't apply to them since they're logs, not settings.

### Thesis tables — three different mechanisms, mostly disconnected
**CORRECTED (VERIFIED 2026-09-28):** `stock_theses` is the LIVE store for BOTH thesis APIs; `theses` is a relic. The first pass had this inverted.
- `stock_theses` — HAS an ORM model (`StockThesis`, db_manager.py:438-464, "replaces stock_thesis.json + .theses.json"). **It is the live target of BOTH `/api/thesis` (`stock_thesis.py:18-114`) and `/api/my-thesis` (`thesis_manager.py:110-125,158-170,202`)** — both modules read/write `StockThesis`. Currently **0 rows** (no thesis has been saved via either API). The section on the intelligence collectors (thesis subsystems) gives the same, correct account.
- `theses` — no ORM; raw SQL (`app.py:5653`, `thesis_analyzer.py:41,181`, one UPDATE at `thesis_analyzer.py:159`). 1 row (ASIANPAINT, entry 2250.39, target 3500, qty 16, 2025-09-30), last update 2026-03-30. **A relic**: nothing but `thesis_analyzer.py` and `app.py:5653` touches it, it is read only by `/api/thesis/<s>/performance`, and there is no INSERT path anywhere. `thesis_manager.py` does NOT use `theses` (the earlier claim of "DB-first, `.theses.json` fallback over `theses`" was wrong — it uses `stock_theses` with the JSON fallback).
- `thesis_analysis` — no ORM; raw SQL writer `thesis_analyzer.py:113` (`INSERT INTO thesis_analysis`), FK to `theses.id`. 0 rows currently.
Three thesis-shaped tables (`theses`, `thesis_analysis`, `stock_theses`) for what CLAUDE.md's current-state summary implies should be one feature — flag for follow-up (the only live one is `stock_theses`).

### `predictions` and `trade_log` — schema exists, nothing populates them
- `predictions` (id, symbol, signal, confidence, timestamp, data jsonb) — no ORM model, no `INSERT INTO predictions` found anywhere in tracked code; every "predictions" hit in grep is an in-memory Python variable/list (auto_analyzer.py, bot.py), not this table. 0 rows. **DEAD.**
- `trade_log` — has both an ORM model (`TradeLogEntry`, db_manager.py:403-419) and a loader (`bot.py:104-124` `_load_trade_log()`, reads via `TradeLogEntry` at boot). **CORRECTED: the persistence path IS wired but broken.** `bot.py:121-138` `_persist_trade_log_entry` does `session.add(TLE(...)); commit()` and is called at bot.py:1591, 1761 and 1850 right after each `_trade_log.append(entry)` — the earlier claim "no `session.add(TradeLogEntry(...))` found; writes go to the in-memory list only" was wrong. **Why it stays at 0 rows — schema drift:** live `trade_log` columns = id, symbol, **action**, quantity, price, **timestamp**; ORM `TradeLogEntry` = side, order_id, order_status, remark, breakeven_price, est_charges, trade_id, created_at (8 ORM columns missing, 2 live-only). So **every INSERT (and the boot `_load_trade_log` SELECT) fails with `UndefinedColumn` and is swallowed at DEBUG** (bot.py:137-138, 118-119) because the live table predates the ORM model. Consequence: the in-memory `_trade_log` is what is served, and it is lost on every restart.

### Legacy JSON files vs DB (source-of-truth check)
| Data | DB table (rows, 2026-09-27) | JSON file (mtime) | Source of truth |
|---|---|---|---|
| Trade journal | `trade_journal` (26 exact; earlier 22 was a stale estimate) | `trade_journal.json` (2026-09-22) | **DB** — `trade_journal.py:_save()` commits to DB first, mirrors to JSON only after DB success (trade_journal.py:250-260) |
| Paper trades | `paper_trades` (4 exact; earlier 8 was a stale estimate) | `paper_trades.json` (2026-09-22; 26 records, 0 OPEN) | **JSON — `paper_trades.json` is the operational source of truth** (CORRECTED): positions, exits, duplicate guard, `record_pnl`, auto-close and `symbol_purge` all read it via `PaperTradeTracker` (paper_trader.py:37-104). The DB table is a partial order-fill log (4 rows vs 26 JSON trades) read only by the EOD Telegram summary (scheduler.py:1059-1084). Dual-write pattern per CLAUDE.md op-rule #2 (four stores total: both JSON files + both DB tables) — **never exercise this write path for testing (op-rule #2)** |
| Watchlist notes | `watchlist_notes` (0) | `watchlist_notes.json` (2 bytes, effectively empty) | DB (`WatchlistNote` model); JSON is stale/unused (both empty) |
| Personal theses | `stock_theses` (0; live store) / `theses` (1; relic) | `.theses.json` (276 bytes, 2026-03-30) | **`stock_theses`** — `thesis_manager.py` (and `stock_thesis.py`) read/write it DB-first with JSON fallback; `theses` is a relic read only by `/api/thesis/<s>/performance` (see Thesis section) |

### Drift & contradictions (verified this pass)
1. **Two parallel auth systems.** `auth_session.py` (cookie + `auth_sessions` table) is the real
   gate for the entire app (`app._require_session`, app.py:230). `auth_manager.py`'s JWT
   `@require_auth` decorator gates only 5 routes (`/dashboard`, `/setup`, `/api/auth/verify`,
   `/api/auth/profile`, `/api/auth/set-api-key`; signup/login are not decorated), and `users` has 1
   row — but `users` is live: the Google sign-in flow (`google_auth.py`, untracked) creates/links
   `users` rows and passes `users.id` into `auth_session.create` (and sends a Telegram message on every
   sign-in). Any future work should confirm which system a given endpoint actually sits behind
   before assuming JWT protects it.
2. **Undeclared uuid columns.** `trade_journal.user_id`, `pnl_snapshots.user_id` (both `uuid`,
   nullable) and the entire `refresh_tokens` table exist live but have **no ORM field and no
   `ALTER TABLE`/migration found in tracked code** — they were added directly against the DB,
   outside any committed migration. `refresh_tokens` has zero code references at all (DEAD).
   Likely artifacts of the on-hold multi-tenancy plan (memory: Phase 0 done, 1-2 on hold) —
   confirm intent before dropping or building on them.
2a. **Complete ORM-vs-live-DB drift list (VERIFIED 2026-09-28 — only 4 tables differ):**
   `trade_journal` (+`user_id` uuid, DB-only), `pnl_snapshots` (+`user_id` uuid, DB-only),
   **`trade_log`** (8 ORM columns missing from the live table: side, order_id, order_status, remark,
   breakeven_price, est_charges, trade_id, created_at; 2 live-only: action, timestamp) and
   **`idempotency_keys`** (ORM `content_type` missing in DB). `refresh_tokens.user_id` is uuid too
   (no ORM). `auth_sessions.user_id` and `idempotency_keys.user_id` are `integer` (ORM-declared).
3. **`db/fyers_candles_schema.sql` says "NOT YET EXECUTED"** but the live DB has all 32
   partitions matching it exactly — the file's header comment is stale documentation, not current
   fact.
4. **Three thesis tables** (`theses`, `thesis_analysis`, `stock_theses`): `stock_theses` (ORM model,
   documented as replacing the others) IS the live store for both `/api/thesis` and `/api/my-thesis`
   but holds 0 rows; `theses` (no ORM) is a relic with 1 row, read only by
   `/api/thesis/<s>/performance`, with no INSERT path.
5. **`predictions` is dead; `trade_log` is wired but broken.** `predictions` has no writer at all (no
   ORM, no INSERT). `trade_log` HAS a writer (`bot.py:121-138`, called at 1591/1761/1850) but every
   INSERT fails on schema drift (live `action`/`timestamp` vs ORM `side`/`order_id`/… /`created_at`)
   and is swallowed at DEBUG, so actual state is served from an in-memory list that is lost on restart.
5a. **`idempotency_keys` schema drift makes a money-path guard inert.** The ORM `content_type`
   column is missing from the live table (`migrate_idempotency.py` never run), so
   `claim_idempotency_key`'s INSERT raises `UndefinedColumn` and falls OPEN to `IDEM_CLAIMED`.
5b. **`paper_trades` DB (4 rows) diverges from `paper_trades.json` (26 records, the operational source
   of truth)**, so the EOD Telegram summary — the DB table's only reader — under-reports.
6. **`nse_instruments` has no scheduled writer** — static reference data whose only writer is the
   manual root script `load_nse_instruments.py` (idempotent upsert; not scheduled, no callers), plus
   the archived import script.
7. **`stock_prices` is in `symbol_purge.PURGE_TABLES`** (rows deleted on watchlist removal) despite
   no longer being written by the collection pipeline — purge logic still assumes it's live.

### Deletion / lifecycle mechanics
- **`symbol_purge.py`** (root) is the only structured deletion path: removing a symbol from the
  watchlist deletes matching rows from `PURGE_TABLES` (stocks, stock_prices, fyers_candles→all
  partitions, candles, intraday_candles, predictions, news_articles, shareholding_patterns,
  peer_comparisons, company_external_data, external_slug_map, company_connections,
  thesis_analysis, watchlist_notes) plus symbol-keyed `analysis_cache` keys and symbol-named model
  files. `KEEP_TABLES` (trade_journal, paper_trades, trade_log, trade_snapshots, theses,
  stock_theses, master_ticker_table, nse_instruments, commodity_snapshots) are explicitly never
  touched. Refuses if the symbol has an OPEN paper position. Any table with a symbol column not in
  either list is reported as `unclassified` rather than silently skipped.
- **`prune_idempotency_keys(retention_hours=48)`** — db_manager.py:1774.
- **`prune_old_candles(symbol, keep_days=365)`** — db_manager.py:1235, targets the now-empty legacy `candles` table.
- No automatic pruning found for `fyers_candles`, `news_articles`, `global_news`,
  `company_external_data` (append-only, unbounded growth — matches CLAUDE.md standard #2's
  concern about append-only tables needing bounded reads, not necessarily pruning).

### Cross-cutting facts (for the maps)

- **DB tables written**: fyers_candles(+partitions), stock_prices, candles, intraday_candles,
  company_external_data, global_news, news_articles, pnl_snapshots, analysis_cache,
  master_ticker_table, company_connections, trade_snapshots, trade_journal, paper_trades,
  shareholding_patterns, external_slug_map, peer_comparisons, disruption_events, config_settings,
  commodity_snapshots, auth_sessions, cost_notifications, stocks, candle_training_metadata,
  idempotency_keys, users, watchlist_notes(indirectly), cost_audit_log, theses, thesis_analysis.
- **DB tables read but effectively static/dead**: nse_instruments (static), refresh_tokens (dead),
  predictions (dead), trade_log (wired but every INSERT fails on schema drift — served from memory
  instead), stock_theses (live target of both thesis APIs, 0 rows), idempotency_keys (guard INERT — 0
  rows because every claim INSERT fails), cost_audit_log (structurally always empty), theses (relic).
- **Every timed/triggered DB write found this pass**: pnl_snapshots at most once per ~15s dispatch
  pass during market hours and only while `paper_trades.json` has OPEN trades
  (scheduler.py:1023; newest row 2026-09-22); candle_training_metadata on each collection/XGBoost-retrain event
  (db_manager.py:1923-1971); config cache TTL 30s (db_manager.py:1430); auth session cache 30s /
  touch throttle 60s (auth_session.py:57-58).
- **Config keys touching this layer**: `auth.idle_minutes` (30), `auth.absolute_hours` (12),
  `auth.account_days` (30) — all seeded/read via `auth_session.seed_config()`/`get_config`.
- **Fail-open vs fail-closed**: `claim_idempotency_key` — INSERT-unreachable fails OPEN, everything
  after a proven duplicate fails CLOSED (db_manager.py:1581-1589). **The fail-OPEN branch is live
  today**: the missing `content_type` column makes every claim INSERT raise, caught by the generic
  `except Exception` (db_manager.py:1626-1631) → `IDEM_CLAIMED`, so the guard on `/api/buy` etc. is INERT. `auth_session.ensure_schema()`
  swallows all exceptions (never raises) — a failed `ALTER TABLE` at startup is silent.
- **Dead/legacy code surfaced**: `refresh_tokens` table (dead), `predictions` table (dead),
  `trade_log` table (persist path wired but every INSERT fails on schema drift; real data in-memory),
  `theses` table (relic), `nse_instruments` (static; manual `load_nse_instruments.py` only),
  `db/fyers_candles_schema.sql` header stale vs live state, JWT auth system (`auth_manager.py`)
  marginal vs the real session gate.
- **Open unknowns**: whether `theses` / `thesis_analysis` (the relic pair) were meant to converge into
  `stock_theses` (the live store) — UNKNOWN, not determinable from code alone, would need the user's
  intent. Whether the missing `fyers_candles` rows for Mon 2026-09-28 are a market holiday or a
  collection outage — UNVERIFIED. Why `cost_notifications` has no row since 2026-07-31 — UNVERIFIED. Origin of the undeclared uuid `user_id` columns and
  `refresh_tokens` (which migration/manual DDL added them) — UNKNOWN, no commit or script found in
  this pass; EXTERNAL VERIFICATION REQUIRED (ask the user, or check DB-side migration history if
  one exists outside git).

## Configuration, Environment Variables, File Stores & Dependencies

Covers: the `config_settings` DB table (runtime-tunable knobs, read via `get_config`/memoized
helpers in `db_manager.py` and exposed through `/api/config`), environment variables read from
`.env` via `os.getenv`/`os.environ` across the codebase, file-based JSON/log/state stores in the
repo root (some gitignored "local runtime data", some checked in), and `requirements.txt` pinned
dependencies including the documented `fyers-apiv3` no-deps install conflict. Repo root:
`/Users/parthsharma/Desktop/Grow`. All DB values below are LAST VERIFIED: 2026-09-27 via
`SELECT key,value,description,updated_at FROM config_settings ORDER BY key` (220 rows).

### The config API and helper layer — VERIFIED FROM CODE

| Piece | Where | Behaviour |
|---|---|---|
| `get_config(key, default, db)` | `db_manager.py:1444` | 1 query, memoized `_config_cache` dict, TTL `_CONFIG_CACHE_TTL=30.0s` (`db_manager.py:1430`). Returns `default` if row absent or value `None`. |
| `get_configs(keys, db)` | `db_manager.py:1465` | Batch read via `WHERE key IN (...)`, ONE query for N keys — populates the same memo. Used by `news_sentiment._news_settings()` (news_sentiment.py:359) and `cash_backtester.py` (see prefix helper below). |
| `get_configs_prefix(prefix, db)` | `db_manager.py:1486` | Batch read via `LIKE 'prefix%'`, ONE query. Used for `auth.provider.` (app.py:1014), `scheduler_interval_` (scheduler.py:1217, app.py:8021), `prediction.weight.` (cash_backtester.py:96), `tijori.last_collected.` (tijori_collector.py:1168) — the standard pattern this codebase uses to avoid N+1 config reads inside per-item loops. |
| `set_config(key, value, description, db)` | `db_manager.py:1498` | Upsert, invalidates that key's cache entry immediately (so a Settings-tab edit is live at once), then best-effort `change_feed.notify("config", key=key)` to push to open dashboards (never raises). |
| `invalidate_config_cache(key=None)` | `db_manager.py:1435` | Drop one key or clear the whole memo. |
| `GET /api/config` | `app.py:2018` (`list_config`) | Requires a `pin_ok` session (not in `_PUBLIC_PATHS`, so not public). One query, filters out `_CONFIG_HIDDEN_PREFIXES` / `_CONFIG_DEAD_KEYS` rows, masks `_CONFIG_SENSITIVE_KEYS` values as `••••••••`, marks `_CONFIG_READONLY_KEYS`. |
| `POST /api/config` | `app.py:2053` (`update_config`) | Rejects hidden-prefix/readonly (403), rejects dead keys (403 "unused — nothing reads it"), rejects unknown keys (404 — a row must already exist), no-ops if a sensitive field is submitted back as the mask string, and on `cost.*` edits calls `costs.reload_rates()` since `costs.py` caches rates at import. |
| UI gating sets (app.py:1987-2015) | `_CONFIG_HIDDEN_PREFIXES = ("tijori.last_collected.", "earnings.last_qrev.", "tijori.onboarded.")`; `_CONFIG_READONLY_KEYS = {"tijori.backfill_status","fno.used_capital","portfolio_reviewed"}`; `_CONFIG_SENSITIVE_KEYS = {"telegram_bot_token"}`; `_CONFIG_DEAD_KEYS` = 13 lowercase `cost.*` JSON-blob twins (see Cost group). | `earnings.last_qrev.` is hidden by prefix but **no row with that prefix exists in the current 220** — dead code guard for a feature not present in this snapshot (UNKNOWN — NOT DETERMINABLE FROM CODE whether it existed before or is planned). |

**CONTRADICTION FOUND:** `_CONFIG_SENSITIVE_KEYS` only contains `telegram_bot_token`. `telegram_chat_id` (app.py:7224,7236) and `auth.allowed_emails` (auth_session.py:133, holds the user's Google-sign-in email) are returned in the clear by `GET /api/config` — not masked, not readonly-hidden (that endpoint itself needs a `pin_ok` session — it is not public — so the exposure is to a PIN-verified session only). Everything else in this file redacts both per this task's instructions; the live app does not.

### `auth.*` — session/lock and landing-page config (8 keys) — VERIFIED FROM CODE+DB

| Key | Value (LAST VERIFIED 2026-09-27) | Description | Seeded default | Reader(s) | Orphaned? | Editable in UI? |
|---|---|---|---|---|---|---|
| auth.absolute_hours | 12 | Lock after N hours regardless of activity | `auth_session.py:126` DEFAULT_ABSOLUTE_HOURS | `auth_session.py:85` `_cfg_int` | No | Yes |
| auth.account_days | 30 | Stay signed in (skip landing) N days after sign-in | `auth_session.py:128` DEFAULT_ACCOUNT_DAYS | `auth_session.py:89` | No | Yes |
| auth.allowed_emails | (secret, not recorded) | Emails allowed to sign in with Google, comma-sep; empty=nobody | `auth_session.py:133` (seeded `""`) | `google_auth.py:167` `_allowed_emails()`, enforced at `google_auth.py:183-184` (`SignInRefused` if email not in list) — **`google_auth.py` is untracked by git** (see Cross-cutting facts), so `git grep` misses this; only found via a plain `/usr/bin/grep` pass | No | Yes |
| auth.idle_minutes | 30 | Lock after N idle minutes | `auth_session.py:124` DEFAULT_IDLE_MINUTES | `auth_session.py:81` | No | Yes |
| auth.landing_enabled | false | Serve landing page at `/` for visitors without a session | `auth_session.py:139` (`"false"`) | `app.py:987` | No | Yes |
| auth.provider.apple | false | Landing page: "Continue with Apple" live | `auth_session.py:143` | `app.py:1020` (`on("auth.provider.apple")`), batch-read via `get_configs_prefix("auth.provider.")` app.py:1014 | No | Yes |
| auth.provider.email | false | Landing page: email+password sign-in/up live | `auth_session.py:145` | `app.py:1021` | No | Yes |
| auth.provider.google | false | Landing page: "Continue with Google" live | `auth_session.py:141` | `app.py:1019` (also needs `google_auth.configured()`) — **governs only the landing-page button** (`/api/auth/providers`); the OAuth flow itself (`/api/auth/google/start`, `app.py:1032`) checks only `google_auth.configured()`, never this key, so the flow is LIVE even with this key `false` | No | Yes |

### `cash_auto_trade_enabled` / `cash_autotrade_enabled` — VERIFIED FROM CODE+DB

| Key | Value | Description | Reader(s) | Orphaned? | Editable? |
|---|---|---|---|---|---|
| cash_auto_trade_enabled | true | Master switch, cash-equity auto-trade | `scheduler.py:802`, `bot.py` gate, `telegram_commander.py:674,698,715,1138`, toggled by `app.py:6619-6621` and `telegram_commander.py:700`, read in `index.html:17685` (mutation-notify allow-list) | No | Yes |
| cash_autotrade_enabled | false | (no description) | **none found** — `app.py:2003` comment: "typo twin of cash_auto_trade_enabled with no readers" | **Yes — dead** | Hidden (`_CONFIG_DEAD_KEYS`, app.py:2008) |

### `close_trade.max_price_divergence_pct` — VERIFIED FROM CODE+DB
Value 20 · "Reject a close if price moved more than this % from the quote" · seeded `app.py:904` · read `app.py:1296` in the close-trade endpoint's price-sanity guard · not orphaned · editable.

### `cost.*` — brokerage/tax rate table (29 rows) — VERIFIED FROM CODE+DB
Two parallel families exist under this prefix and **only the UPPERCASE family is live**:

**Live family — read by `costs.py:_load_rates()` (costs.py:45-55), 11 keys, default from `costs.py:_DEFAULTS` (costs.py:26-38), seeded by `costs.py:seed_cost_rates()`:**

| Key | Value | Default (code) |
|---|---|---|
| cost.BROKERAGE_PER_ORDER | 20.0 | 20.0 |
| cost.BROKERAGE_INTRADAY_PCT | 0.05 | 0.05 |
| cost.STT_DELIVERY_PCT | 0.1 | 0.1 |
| cost.STT_INTRADAY_SELL_PCT | 0.025 | 0.025 |
| cost.EXCHANGE_TXN_NSE_PCT | 0.00345 | 0.00345 |
| cost.EXCHANGE_TXN_BSE_PCT | 0.00375 | 0.00375 |
| cost.SEBI_FEE_PCT | 0.0001 | 0.0001 |
| cost.GST_PCT | 18.0 | 18.0 |
| cost.STAMP_DUTY_DELIVERY_PCT | 0.015 | 0.015 |
| cost.STAMP_DUTY_INTRADAY_PCT | 0.003 | 0.003 |
| cost.DP_CHARGES | 15.93 | 15.93 |

All 11 editable, not orphaned, not readonly/hidden. `costs.reload_rates()` is invoked by `app.py:2088-2093` on any `cost.*` POST because `costs.py` caches rates in a module-level `_rate_cache` at first use.

**Dead family — 18 lowercase JSON-blob keys, whose values come from `cost_scraper.py:GROWW_CHARGES_CANONICAL` (cost_scraper.py:34-64) via the scraper's `scrape()` (cost_scraper.py:465) and are written wholesale to the DB by `cost_updater.update_costs()` (cost_updater.py:213), called by `costs.update_cost_rates()` (costs.py:125-186) — which is what the `cost_scraper` scheduler task runs (scheduler.py:559-564, registered :1348) — on `scheduler_interval_cost_scraper` cadence (3,888,000s ≈ 45 days). Chain: scheduler `cost_scraper` → `costs.update_cost_rates` → `cost_scraper.scrape` (values) → `cost_updater.update_costs` (DB write). (`cost_scraper.py:505-517` is a READ of the old `cost.%` rows for comparison, not the write; the `app.py:2000` comment also names `cost_updater.py`.) None are read by `costs.py` or anywhere else in `*.py`/`index.html` — VERIFIED via `git grep` for each literal key, zero readers outside `cost_scraper.py`/`cost_updater.py`/`cost_notifications.py` (which only reference them in log/notification text, not as config lookups).**

| Key | Value | Hidden via `_CONFIG_DEAD_KEYS`? |
|---|---|---|
| cost.brokerage_flat_per_order | 20.0 | Yes |
| cost.brokerage_pct_per_order | 0.1 | Yes |
| cost.brokerage_min_per_order | 5.0 | **No — shows as live-editable in Settings, does nothing** |
| cost.dp_charge_delivery_depository | 3.5 | **No** |
| cost.dp_charge_delivery_groww | 16.5 | **No** |
| cost.dp_charge_intraday | 0.0 | **No** |
| cost.exchange_charge_bse_pct | 0.00375 | Yes |
| cost.exchange_charge_nse_pct | 0.00297 | Yes |
| cost.gst_rate | 0.18 | Yes |
| cost.sebi_fee_pct | 0.0001 | Yes |
| cost.stamp_duty_pct_delivery_buy | 0.015 | Yes |
| cost.stamp_duty_pct_intraday_buy | 0.003 | Yes |
| cost.stt_commodity_sell | 0.01 | Yes |
| cost.STT... (uppercase, live, listed above) | — | n/a |
| cost.stt_fno_sell | 0.05 | Yes |
| cost.stt_option_premium | 0.15 | Yes |
| cost.stt_pct_delivery_buy | 0.1 | **No** |
| cost.stt_pct_delivery_sell | 0.1 | Yes |
| cost.stt_pct_intraday_sell | 0.025 | Yes |

**FINDING (new, not previously documented in code comments):** `_CONFIG_DEAD_KEYS` (app.py:2007-2015) hides 13 of the 18 orphaned lowercase twins, but **5 are missing from that set** — `cost.brokerage_min_per_order`, `cost.dp_charge_delivery_depository`, `cost.dp_charge_delivery_groww`, `cost.dp_charge_intraday`, `cost.stt_pct_delivery_buy`. These 5 appear as normal, live, editable rows in the Settings UI (`GET /api/config`) and accept edits via `POST /api/config`, but no code path ever reads them back — editing one silently does nothing, exactly the failure mode CLAUDE.md engineering standard and the `_CONFIG_DEAD_KEYS` comment block describe, just incompletely covered.

### `fno_auto_trade_enabled` + `fno.*` + `mcx.lot.*` — F&O paper trading (24 keys) — VERIFIED FROM CODE+DB

| Key | Value | Reader(s) | Orphaned? | Editable? |
|---|---|---|---|---|
| fno_auto_trade_enabled | false | Master switch, `scheduler.py:648` gate; seeded `app.py:897`; UI `index.html:5568,5580,17685` | No | Yes |
| fno.capital | 10000 | `fno_trader.py:315` `get_available_capital()`; **written by `fno_trader.py:269,295`** (synced from Groww margin every `scheduler_interval_fno_capital_sync`=600s) — a manual Settings edit is overwritten on the next sync | No | Yes (but sync wins) |
| fno.used_capital | 0 | `fno_trader.py:325,337`; app.py:3717-3718 sync | No | **Readonly** (`_CONFIG_READONLY_KEYS`) |
| fno.lot.NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY / SENSEX / HDFCBANK (6 keys, JSON lot-size blobs) | see dump | `auto_metadata.py:520` `get_fno_lot_config()` — dynamic key `f"fno.lot.{instrument}"`, checked before `mcx.lot.` | No | Yes (JSON edit) |
| mcx.lot.CRUDEOILM / GOLDM / NATGASMINI / NATURALGAS / SILVERM (5 keys) | see dump | same `get_fno_lot_config()`, dynamic `f"mcx.lot.{instrument}"` | No | Yes |
| fno.stt.option_sell_pct, fno.stt.futures_sell_pct, fno.exchange.nse_pct, fno.exchange.bse_pct, fno.exchange.mcx_pct, fno.sebi_pct, fno.gst_pct, fno.stamp_duty_pct, fno.brokerage_per_order, fno.brokerage_pct_cap (10 keys) | see dump | **Dynamic-key read** — `fno_trader.py:186-195` calls `get_fno_cost_rate(name, default)` (`auto_metadata.py:534`), which does `get_config(f"fno.{name}")`; the literal string never appears in `fno_trader.py`, so a naive grep for the key text misses the call site. Seeded `auto_metadata.py:500-510`. | No (confirmed live, not orphaned, despite not matching a literal-string grep) | Yes |

### `fyers.*` — rate limiter + WebSocket config (8 DB keys + 1 code-only key) — VERIFIED FROM CODE+DB

| Key | Value | Reader | Orphaned? | Editable? |
|---|---|---|---|---|
| fyers.rate_per_sec | 2.5 | `fyers_client.py:111` `_acquire_token()` token-bucket rate; `_cfg()` tries DB → env `FYERS_RATE_PER_SEC` → literal `_DEFAULT_RATE=2.5` | No | Yes — **CLAUDE.md op-rule 9 subject**: literal fallback `_DEFAULT_RATE` was previously 5.0 (300/min, over the 200/min cap), now fixed to 2.5 (150/min) |
| fyers.burst | 5 | `fyers_client.py:112` | No | Yes |
| fyers.ws_enabled | false | `fyers_ws_client.py:138,564` gate — **seeded default was `"true"` (app.py:920) but live DB value is `false`**, i.e. manually disabled after seeding; CLAUDE.md/COMMON_RULES precedent example ("fyers_ws_client.py exists but ws_enabled=false") | No | Yes |
| fyers.ws_freshness_seconds | 2 | `fyers_ws_client.py:145,199` — tick older than this is STALE, never used, never falls back to REST | No | Yes |
| fyers.ws_reconnect_retry | 10 | `fyers_ws_client.py:477` | No | Yes |
| fyers.ws_backoff_max_seconds | 300 | `fyers_ws_client.py:500` | No | Yes |
| fyers.ws_stall_seconds | 60 | `fyers_ws_client.py:398` — 0 disables the watchdog | No | Yes |
| fyers.ws_watchlist_poll_seconds | 60 | seeded app.py:926 — **no reader anywhere** (`git grep --untracked watchlist_poll` returns only the seed) | **Yes — ORPHANED, seed-only key** (not in `_CONFIG_DEAD_KEYS`, so it shows in Settings as live-editable) | Yes |
| fyers.quote_ttl_seconds | **no DB row — not in the 220** | `fyers_client.py:104-105` `quote_ttl()`; `_cfg()` DB→env `FYERS_QUOTE_TTL_SECONDS`→literal `_DEFAULT_QUOTE_TTL=2.0` (fyers_client.py:48) | Code reads a key that was never seeded — always falls through to env/literal | N/A — not a DB row, so absent from Settings UI entirely |

### `idempotency.*` — order-endpoint replay protection (2 keys) — VERIFIED FROM CODE+DB
| Key | Value | Reader | Seeded |
|---|---|---|---|
| idempotency.require_key | 0 | `app.py:627` (`idempotency_required()`) gates whether order endpoints demand an `Idempotency-Key` header; `scheduler.py` prune task reads retention only | `app.py:906`, also re-seeded defensively by `migrate_idempotency.py:65-71` |
| idempotency.retention_hours | 48 | `scheduler.py:677` (`scheduler_interval_prune_idempotency` task, prunes used keys older than this) | `app.py:908`, `migrate_idempotency.py:73-78` |

### `intel.request_delay_seconds` — VERIFIED FROM CODE+DB
Value 5 · politeness delay between Screener.in shareholding-scrape page fetches · reader `market_intelligence.py:899` `_intel_cfg()` · default 5.0 in code · not orphaned · editable.

### `lock.colour.1/2/3` — VERIFIED FROM CODE+DB
Values `#1f2b3a` (navy) / `#4a4f36` (olive) / `#5c2230` (wine) · seeded `app.py:899-901` · **read AND written directly by the frontend** (`index.html:5660,5699,5761,5764`) as the color-picker behind the CLAUDE.md-protected lock-screen intro backdrop (the "navy/olive/wine, cycling per load" colours named in the protected section) · not orphaned · editable · **this is the one config group directly wired into the protected lock-screen feature — changing these 3 values changes protected UI behaviour and falls under that CLAUDE.md approval rule.**

### `model.gbc_cash_enabled` / `model.xgb_cash_enabled` — VERIFIED FROM CODE+DB
| Key | Value | Reader |
|---|---|---|
| model.gbc_cash_enabled | false | `bot.py:2094,2111` `_on()` — gates whether the cash GradientBoosting model is allowed to paper-trade |
| model.xgb_cash_enabled | true | `bot.py:2095` `_on(..., XGB_LIVE_TRADING)` — gates the cash XGBoost model |
No seed call found for either in this pass (UNKNOWN where first written — likely a one-off DB insert, same pattern as `trade.*` below).

### `news.*` — sentiment source toggles + cache TTL (7 keys) — VERIFIED FROM CODE+DB
All 7 (`news.cache_ttl_seconds`=600, `news.source.google/newsapi/et_rss/moneycontrol/extra_rss/x_posts`=true) seeded `app.py:912-919`, read as ONE batch via `news_sentiment.py:337-365` `_news_settings()` (uses `get_configs()`, re-batched at most every 30s in a local cache — avoids per-request DB hit and avoids a config-read loop). Not orphaned. Editable.

### `paper_trading` / `paper_trade_amount_limit` / `paper.cap.*` / `paper.min_confidence` — VERIFIED FROM CODE+DB
| Key | Value | Reader | Notes |
|---|---|---|---|
| paper_trading | true | `bot.py:1286-1319` (**fail-closed on exception**: a read error → PAPER, "Fail closed" comment + code at bot.py:1276-1294 — the safe direction since paper can't lose real money. **BUT a MISSING row defaults to LIVE**: `get_config("paper_trading", "false")` at bot.py:1286, also app.py:5853, 6552, 6631, and no code seeds `paper_trading` — only toggles at app.py:6554 and telegram_commander.py:1175), `paper_trader.py:30`, `app.py:5853,6552`, `telegram_commander.py` (10+ sites), `index.html:17685` | Global paper/live switch |
| paper_trade_amount_limit | 50000.00 | `bot.py:1326-1330` `get_paper_trade_amount_limit()`; 0=unlimited; `app.py:6564,6597` | Account-wide cap across ALL open paper positions |
| paper.cap.gradientboosting | 50000 | `bot.py:1351` `_MODEL_CAP_KEYS` dict → `_apply_paper_trade_amount_limit` | Per-model cap |
| paper.cap.xgboost | 50000 | `bot.py:1352`; `telegram_commander.py:1020` | Per-model cap, "applies only when XGB live trading is on" per its own description |
| paper.min_confidence | 0.50 | `bot.py:2218`; `telegram_commander.py:508,676,716` | Shared threshold for both cash models |
Seeds: `paper.cap.*` and `paper.min_confidence` are seeded at `app.py:836-850`; **`paper_trading` has no seed anywhere** (the `paper_trade_amount_limit` seed location was not confirmed). None orphaned. All editable.

### `portfolio_reviewed` — VERIFIED FROM CODE+DB
Value true · safety gate: cash auto-trade scheduler task (`scheduler.py:811-812`) checks `bot.is_portfolio_reviewed()` and auto-marks it reviewed in paper mode; `bot.py:2487-2581` (`_load_portfolio_reviewed`/`mark_portfolio_reviewed`/`is_portfolio_reviewed`, in-process bool cached after first DB read — **not re-checked per call after first load, so an external DB flip to `false` would not be seen until process restart** — UNKNOWN whether this is intentional); `app.py:5256,5265` manual review endpoints · **Readonly** in Settings (`_CONFIG_READONLY_KEYS`) — the app manages it itself.

### `prediction.weight.ml/trend/news/context` — VERIFIED FROM CODE+DB
Values 0.40/0.15/0.20/0.25 (sum to 1.0) · seeded `app.py:819-822` · read individually in `bot.py:1107-1110` (4 separate `get_config` calls — not batched, minor inefficiency but only 4 keys and only in the prediction path, not a hot loop) and via `get_configs_prefix("prediction.weight.")` in `cash_backtester.py:96` (batched) · also `telegram_commander.py:811` (news weight only, for a Telegram-displayed number) · not orphaned · editable.

### `scheduler_interval_*` — 31 task-cadence overrides — VERIFIED FROM CODE+DB
Keys: `auto_analysis`(300) `auto_close_trades`(300) `auto_metadata`(604800=7d) `build_daily_snapshots`(900) `cache_refresh`(3600) `cash_auto_trade`(5) `collect_5min_candles`(300) `cost_scraper`(3888000=45d) `deep_analysis`(1800) `fno_auto_trade`(5) `fno_capital_sync`(600) `fyers_daily_topup`(3600) `fyers_token_refresh`(3600) `geopolitical`(1800) `global_indices`(900) `market_intelligence`(86400) `ml_retrain`(86400) `news_prefetch`(600) `paper_eod_summary`(1800) `prune_idempotency`(3600) `record_pnl`(5) `research_engine`(14400) `retrain_xgb_daily`(86400) `self_healing`(3600) `supply_chain`(900) `telegram_summary`(1800) `tijori_refresh`(21600) `token_refresh`(3600) `update_watchlist_prices`(3600) `world_news`(900) `xgb_cash_retrain`(86400) — 31 tasks (DB has entries for the ones ever changed from their compiled default; others run on compiled defaults with no DB row). All read in ONE query per dispatch pass by `scheduler.py:1202-1220` `_load_interval_overrides()` → `get_configs_prefix("scheduler_interval_")`, applied per-task by `_resolve_interval()` (scheduler.py:1223+, dynamic key `f"scheduler_interval_{task_name}"`, no I/O). **Documented real N+1 fix** (scheduler.py:1206-1210 comment): per-task reads were ~29 distinct keys × every 15s dispatch ≈ 83,000 queries/day; now 1 query per dispatch. Also re-exposed via `app.py:8018-8021` (likely a status/introspection endpoint). Not orphaned. Editable per-key (each is its own `config_settings` row, not hidden/readonly).

### `telegram_*` — bot alerts (5 keys) — VERIFIED FROM CODE+DB
| Key | Value | Reader | Sensitive |
|---|---|---|---|
| telegram_bot_token | (secret, not recorded) | `app.py:7223,7234`; `telegram_alerts.py:28`; `telegram_commander.py:51` | Yes — masked in UI (`_CONFIG_SENSITIVE_KEYS`) |
| telegram_chat_id | (secret, not recorded) | `app.py:7224,7236`; `telegram_alerts.py:29`; `telegram_commander.py:52` | **Not masked by the app** (see contradiction above) — redacted here per this task's own rules |
| telegram_enabled | true | `app.py:7222`; `cost_notifications.py:180`; `scheduler.py:1041,1133`; `telegram_alerts.py:30` | No |
| telegram_cost_notifications | true | `cost_notifications.py:181` | No |
(no 5th distinct telegram_* row beyond these 4 in the dump — corrected count) All seeded/settable via the Telegram-setup endpoint (`app.py:7222-7238`), not the generic `_seed_config`-style block. Not orphaned. Editable (token/chat_id via the dedicated setup form, not raw `/api/config` per the mask no-op rule).

### `tijori.*` — supply-chain/fundamentals scraper (16 static keys + 2 dynamic-prefix families) — VERIFIED FROM CODE+DB
Static keys (`tijori.enabled`=true, `base_url`, `request_delay_seconds`=6, `timeout_seconds`=15, `refresh_interval_days`=7, `max_symbols_per_run`=10, `max_slug_resolutions_per_run`=15, `block_below_coverage_pct`=95, `local_index_ttl_seconds`=3600, `max_partner_snapshots_per_run`=12, `partner_retry_days`=14, `max_partner_discovery_per_run`=15, `onboard_partner_limit`=20, `user_agent`) all seeded in `tijori_collector.py:40-53` `_CONFIG_DEFAULTS` and read through its own `_cfg()` helper (tijori_collector.py:61-69, same DB→literal-default pattern, no env fallback). `tijori.backfill_status` (readonly; written by `tijori_backfill.py:27,50,60`, read `app.py:2876`). `tijori.last_partner_refresh` (date string, `scheduler.py:605,617`, dedupes the daily partner-discovery run to once/day). None orphaned.

Dynamic families (hidden from Settings UI via `_CONFIG_HIDDEN_PREFIXES`):
- `tijori.last_collected.<SYMBOL>` (66 rows as of the 2026-09-27 verification; grows with collection — 63 in the original dump) — write `tijori_collector.py:584` per-symbol on successful collection; read back **batched** via `get_configs_prefix("tijori.last_collected.")` (tijori_collector.py:1166-1168) then looked up per symbol from the in-memory map (tijori_collector.py:1173) — correct N+1-avoiding pattern.
- `tijori.onboarded.<SYMBOL>` (3 rows: ABB... no — JSWSTEEL, MOTILALOFS, TCS) — write-only: `tijori_collector.py:1123`. **VERIFIED ORPHANED — no reader anywhere in `*.py`** (confirmed by exhaustive `grep -rn "tijori.onboarded"`, only the writer at :1123 exists). Genuinely dead per-symbol state, distinct from `last_collected` which IS read back.

### `trade.*` — exit-freeze and breakeven config (3 keys) — VERIFIED FROM CODE+DB
| Key | Value | Reader | Seed |
|---|---|---|---|
| trade.max_breakeven_pct | 0.60 | `bot.py:2275` `_max_be = float(_gc("trade.max_breakeven_pct") or 0.60)`; `telegram_commander.py:509` | **No `set_config`/seed call found anywhere in `*.py`** — row exists in DB only; code default 0.60 used if the row is ever missing |
| trade.no_auto_exit_after | 15:15 | `trailing_stop.py:57,87` `_exit_freeze_config()` — cutoff time after which automated exits are frozen (manual closes exempt, `is_manual_exit()`) | Same — no seed call found; default `_DEFAULT_CUTOFF="15:15"` (trailing_stop.py:44) |
| trade.no_auto_exit_enabled | true | `trailing_stop.py:54` | Same — no seed found; **fails closed to `enabled=True`** (freeze stays on) if config read fails, per the function's own docstring: "a config failure must not decide whether money can be protected" |
Blast radius: these three directly gate whether the automated trailing-stop/exit logic is allowed to close a position late in the trading day — a money-path control. UNKNOWN how the 3 rows first entered the DB (no seed code found); likely a manual SQL insert during development.

## Part 2 — Environment variables

Searched every tracked `*.py` (`git ls-files '*.py'`, 146 files) **plus 2 files git does not track** —
`google_auth.py` and `generate_book_pdf.py` — which a plain `git grep` silently skips (see
Cross-cutting facts). `archive/` (47 `.py` files, legacy/backup scripts) checked separately and
excluded from the "active reader" claims below. `.env` has 25 variable NAMES (values never read):
`ALLOWED_ORIGINS, APP_DEVICE_TOKEN, APP_PIN_HASH, DB_URL, FLASK_HOST, FLASK_PORT, FYER_ACCESS_TOKEN,
FYER_APP_ID, FYER_PIN, FYER_REFRESH_TOKEN, FYER_Redirect_URL, FYER_SECRET_ID, GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, GROWW_ACCESS_TOKEN, GROWW_API_KEY, GROWW_API_SECRET, MAX_POSITIONS,
MAX_TRADE_QUANTITY, MAX_TRADE_VALUE, NEWS_API_KEY, STOP_LOSS_PCT, TARGET_PCT, WATCHLIST,
XGB_LIVE_TRADING` (note the mixed-case `FYER_Redirect_URL` — must match exactly, case-sensitive).

### Variables present in `.env` and read by code — VERIFIED FROM CODE

| Name | Where read | Default (code) | Controls | Sensitivity |
|---|---|---|---|---|
| DB_URL | `config.py:56` (built from DB_USER/PASS/HOST/PORT/NAME if absent); also read directly in `app.py` (6 call sites: 157,1557,3886,4314,5516,5644), `bot.py:683`, `db_manager.py` (via config), `fyers_backfill_all_watchlist.py:28`, `fyers_fill_1min_gap.py:31`, `fyers_historical_backfill.py:151`, `market_intelligence.py:24`, `peer_analyzer.py:24`, `price_fetcher.py:17`, `self_healing.py:143,234`, `symbol_purge.py:143,196`, `telegram_commander.py:234`, `thesis_analyzer.py:15`, `fetch_google_prices.py:21` | `postgresql://postgres:postgres@localhost:5432/grow_trading_bot` (config.py:51-56) | Postgres connection string, single source used everywhere | Secret (DB creds embedded) |
| GROWW_ACCESS_TOKEN | `config.py:9` (module const); re-read live in `app.py:1375`, `bot.py:148`, `build_master_ticker_table.py:49`, `check_groww_market_data.py:31`, `fetch_full_history.py:46`, `fii_tracker.py:21,71`, `fno_trader.py:354`, `get_token.py` (via API key/secret only), `load_nse_instruments.py:23`, `price_fetcher.py:16`, `refresh_token_cli.py:15`, `token_refresher.py:118`, `trailing_stop.py:184` | `""` | Groww broker session token | Secret — **also WRITTEN at runtime**: `token_refresher.py:46` sets `os.environ`, `:56` (`_update_env_file`, token_refresher.py:82-107) regex-rewrites the `GROWW_ACCESS_TOKEN=` line in the actual `.env` file on disk |
| GROWW_API_KEY | `config.py:7`, `get_token.py:18`, `token_refresher.py:26` | `""` | Groww API key for token exchange | Secret |
| GROWW_API_SECRET | `config.py:8`, `get_token.py:19`, `token_refresher.py:27` | `""` | Groww API secret | Secret |
| FYER_APP_ID | `fyers_auth.py:34` | `None` (raises `RuntimeError` if unset, fyers_auth.py:44,69,242) | FYERS app id for OAuth | Identifier |
| FYER_SECRET_ID | `fyers_auth.py:35` | `None` (raises if unset with APP_ID) | FYERS app secret | Secret |
| FYER_Redirect_URL | `fyers_auth.py:36` | `http://127.0.0.1:8000/fyers_callback` | FYERS OAuth redirect URI | Non-secret |
| FYER_ACCESS_TOKEN | `fyers_auth.py:157,233` | `None` (raises if unset — "run the login flow first") | FYERS session token | Secret — **also WRITTEN**: `fyers_auth.py:139,205` (`_update_env_file`) persists it into `.env`, plus `os.environ` (:141,206) |
| FYER_REFRESH_TOKEN | `fyers_auth.py:193` | `None` | FYERS refresh token (~15-day validity per fyers_auth.py:174) | Secret — WRITTEN at `fyers_auth.py:140` (`.env`) + `:142` (`os.environ`) |
| FYER_PIN | `fyers_auth.py:194` | `None` (unattended refresh logs an error and gives up if unset, fyers_auth.py:199) | FYERS PIN for unattended token refresh | Secret |
| GOOGLE_CLIENT_ID | `google_auth.py:58` (**untracked file — missed by `git grep`**) | `""` | Google OAuth client id for "Continue with Google" | Identifier |
| GOOGLE_CLIENT_SECRET | `google_auth.py:62` (**untracked file**) | `""` | Google OAuth client secret | Secret |
| APP_PIN_HASH | `config.py:47` | `""` | **The live PIN check**: `/api/unlock` compares `sha256(pin) != APP_PIN_HASH` (app.py:330-344) — unsalted SHA-256 with a plain `!=` compare (memory `auth-work-deferred.md`: scrypt PIN storage is planned/"C", not yet built) | Secret |
| APP_DEVICE_TOKEN | `config.py:48` | `""` | **Legacy but not vestigial**: the `X-Device-Token` check it once fed is gone — the app.py:296-300 comment says `APP_DEVICE_TOKEN`/`_device_token_is_valid()` are "no longer consulted"; the mutation guard now checks `X-Requested-With` (checked server-side at app.py:466-471, *sent* by `api()` in index.html:5865-5867; CLAUDE.md op-rule 6 still describes the old `X-Device-Token` header). It must still be non-empty or `/api/unlock` returns 500 (app.py:332) | Secret |
| ALLOWED_ORIGINS | `app.py:266` | `",".join(_DEFAULT_ORIGINS)` (code-defined list) | CORS allow-list | Non-secret |
| FLASK_HOST | `config.py:42` | `127.0.0.1` | Flask bind host | Non-secret |
| FLASK_PORT | `config.py:43` | `5000` (app actually runs on 8000 per `start-all.sh`/CLAUDE.md — **the .env-visible default here (5000) does not match the operational port (8000)**; UNKNOWN — likely `.env` itself sets FLASK_PORT=8000, not verified since values aren't read) | Flask bind port | Non-secret |
| NEWS_API_KEY | `config.py:59` | `""` | NewsAPI.org key for `news.source.newsapi` | Secret |
| MAX_POSITIONS | `config.py:39` | 5 | Max concurrent positions | Non-secret |
| MAX_TRADE_QUANTITY | `config.py:16` | 1000 | Per-trade quantity ceiling (comment: "no hard quantity limit" intent) | Non-secret |
| MAX_TRADE_VALUE | `config.py:17` | 999999999 | Per-trade value ceiling (effectively unlimited per comment) | Non-secret |
| STOP_LOSS_PCT | `config.py:37` | `min(2.0, MAX_CASH_SL_PCT)` | Default cash stop-loss % | Non-secret |
| TARGET_PCT | `config.py:38` | 4.0 | Default cash target % | Non-secret |
| WATCHLIST | `config.py:25`, `price_fetcher.py:158` | code-defined seed list | Initial watchlist symbols (CLAUDE.md: 10 in config, 57 added dynamically → DB, not this env var, is the live source of truth) | Non-secret |
| XGB_LIVE_TRADING | `bot.py:601` | false | Live **runtime fallback** for `model.xgb_cash_enabled`: `bot.py:2095` `_on("model.xgb_cash_enabled", XGB_LIVE_TRADING)` uses it whenever the DB row is missing/empty (not a seed) — currently inert because the row = true | Non-secret |

### Variables read by code but ABSENT from `.env` (fall back to code default) — VERIFIED FROM CODE

| Name | Where read | Default used | Risk |
|---|---|---|---|
| **JWT_SECRET** | `auth_manager.py:18`, used to sign/verify JWTs at `auth_manager.py:89,95` | **hardcoded literal fallback string baked into the source** (value not repeated here — secret; visible at `auth_manager.py:18`) | **MEDIUM/LOW — downgraded from HIGH (see the last two sentences of this cell).** `auth_manager.py` is actively imported by `app.py:54-57` and its `@require_auth`/`generate_jwt` are live on several routes (app.py:1077,1087,1108,1132-1133,1164,1174,1187,1246) alongside the newer cookie-session system in `auth_session.py`. With no `JWT_SECRET` in `.env`, every JWT is signed with the fallback literal that is sitting in plain sight in tracked source, so a token is forgeable by anyone with repo read access. **However, a forged token is only useful to someone who already holds a live session:** `_require_session` (app.py:221-252) runs first on every request; `/dashboard` and `/setup` need an account session cookie, and `/api/auth/verify|profile|set-api-key` need a `pin_ok` session; none of the `@require_auth` paths is in `_PUBLIC_PATHS`. (Section 04's "unreachable without a session" is the correct framing.) |
| ALLOW_DEMO_LOGIN | `app.py:1215` | `""` → demo login route refused unless set to `1/true/yes` | Demo/no-credential login path exists but is closed by default (comment app.py:1212: bypassing this "also defeats `@require_auth` on every protected route") |
| DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME | `config.py:51-55`, `db_manager.py:817-821` | postgres/postgres/localhost/5432/grow_trading_bot | Dead in practice since `DB_URL` is set in `.env` and takes precedence in both call sites; kept as a fallback path |
| XGB_TRAIN_DAYS, XGB_PREDICT_DAYS, LTT_YEARS | `bot.py:437,595,663` | 0→None / 10 / 5 | ML training window tuning, not currently overridden |
| CASH_BT_MAX_HOLD_BARS, CASH_BT_TRAIN_DAYS, CASH_BT_CAPITAL, CASH_BT_ENTRY_THRESHOLD | `cash_backtester.py:71,76,82,85` | 7×bars/session / 180 / 50000 / 0.15 | Backtester tuning knobs |
| FNO_TRAIN_DAYS, FNO_SIGNAL_DAYS | `fno_backtester.py:136,139` | 180 / 30 | F&O backtester tuning |
| `FYERS_RATE_PER_SEC`, `FYERS_BURST`, `FYERS_QUOTE_TTL_SECONDS`, and any other `fyers.*` key | `fyers_client.py:96` `_os.getenv(key.upper().replace(".", "_"))` — **dynamically derived name**, not a literal in source | mid-tier fallback between DB config and the hardcoded literal | Never set today (absent from `.env`); DB `config_settings` rows win first, so these are currently inert safety nets, not active overrides |
| Same pattern, WebSocket keys (`FYERS_WS_ENABLED`, `FYERS_WS_FRESHNESS_SECONDS`, etc.) | `fyers_ws_client.py:127` `os.getenv(key.replace(".", "_").upper(), default)` | per-key literal | Same — inert unless set |
| _FORCE_BACKFILL | `app.py:1784,1786`; referenced in a comment `scheduler.py:224` | unset | **Not a `.env` variable at all** — an in-process flag one code path sets on `os.environ` to signal another call within the same process; never persisted, never read from disk |
| WERKZEUG_RUN_MAIN | `app.py:8147` | n/a | Flask/Werkzeug's own reloader-child marker, not app config |

## Part 3 — File-based data stores and runtime files (repo root)

Log config: the real structured app log is `~/Library/Logs/ParthS/app.log` (`app.py:101`,
`RotatingFileHandler`, `_LOG_MAX_BYTES=20MB × _LOG_BACKUP_COUNT=5` → 120MB ceiling, `app.py:102-124`).
launchd's `StandardOutPath`/`StandardErrorPath` for the `com.parthsharma.parths.flask.plist` service
point to a SEPARATE file, `~/Library/Logs/ParthS/raw.log` (`launchd/com.parthsharma.parths.flask.plist:76,79`,
catches anything that bypasses Python `logging`, e.g. crashes before logging initializes). The
repo-root `server.log` is a THIRD, different target: `start-all.sh:35,289,293` redirects
`nohup .venv/bin/python3 app.py > "$FLASK_LOG" 2>&1` there when the app is started via the script
directly (not via launchd) — VERIFIED FROM CODE which mechanism writes which file; UNKNOWN (not
determined in this pass) which of launchd vs `start-all.sh` is the currently-active start path, so
it is unclear which of `raw.log` / `server.log` is presently live — check `lsof` on the running
PID's fd 1/2 if this matters.

### JSON state files — VERIFIED FROM CODE

| Path | Purpose | Writer(s) | Reader(s) | Source of truth? | Gitignored? |
|---|---|---|---|---|---|
| `paper_trades.json` | Open/closed paper positions | `paper_trader.py:40,74-104` (`PaperTradeTracker`, advisory-lock read-merge-write via `paper_trades.json.lock`, `open(lock_path,'w')` at :74, re-reads disk copy before merging at :79-80 to avoid clobbering concurrent writers), `close_trades.py:64` (manual script) | `analyze_losses.py:11`, `close_trades.py:7`, `change_feed.py:42` (dashboard push-notify path), `paper_trade_reconciliation.py:9`, `trailing_stop.py:231,692` | **One of FOUR stores** written per paper trade alongside `trade_journal.json` + the DB `paper_trades`/`trade_journal` tables (CLAUDE.md op-rule 2) — not a pure mirror, a parallel write target | Yes (`paper_trades.json`, `.bak*`, `*.json.lock`) |
| `paper_trades.json.lock` | Advisory lock for the read-merge-write above | `paper_trader.py:74` | same | Ephemeral coordination file, always empty on disk | Yes (`*.json.lock`) |
| `trade_journal.json` | Full trade history/journal | `trade_journal.py:96` (`JOURNAL_FILE`) | `change_feed.py:43` | Same 4-store pattern as above | Yes |
| `watchlist_notes.json` | User notes per watchlist symbol | `app.py:4225-4260` `_save_watchlist_note()` | `app.py` `_load_notes()`/`_get_watchlist_note()`; `symbol_purge.py:280` (removes a symbol's note on purge) | **Mirror/fallback** — `_load_notes()` tries the DB `WatchlistNote` table FIRST (app.py:4229-4235) and only falls back to this file if the DB query fails/returns nothing; saves go to both (DB primary, JSON "also save as backup", app.py comment) | Yes |
| `manual_holdings.json` | User-declared manually-held positions, excluded from auto-trading | `trade_origin_manager.py:26-52` `register_manual_holding()` — plain read-modify-write, **no lock file**, unlike `paper_trades.json` | `trade_origin_manager.py:56-64` `get_manual_holdings()`/`is_manual_holding()`; `app.py:6687-6735` (list/capital endpoints) | **Sole source of truth** — no DB table involved | Yes |
| `trade_origins.json` | Presumably tracks which trades were system- vs manually-originated | `trade_origin_manager.py:24,99` (`TRADE_ORIGINS_FILE`) | `trade_origin_manager.py:84-112` | **Does not currently exist on disk** (VERIFIED — `ls` fails) — write path defined but apparently never triggered, or was deleted; **NOT in `.gitignore`** — if this write path ever fires it produces an untracked file with no ignore rule, same gap class as the two below | **No — gap** |
| `real_trading_config.json` | Snapshot written when "real trading" (non-paper) is enabled: capital splits, protected/manual symbols | `app.py:6741-6751` (`enable_real_trading`-style endpoint) | Not read back by any grep hit in this pass — **write-only in the code searched; UNKNOWN if any other path reads it** | Looks like an audit/snapshot record, not consulted for a live decision (unverified) | Yes |
| `daily_snapshots.json` | End-of-day portfolio snapshots | `app.py:6045-6146` `build_daily_snapshots()`, `scheduler.py:1147-1160` `_task_build_daily_snapshots()` on `scheduler_interval_build_daily_snapshots`=900s (only runs after 4PM per scheduler.py:1344 comment, `initial_delay=86`) | `app.py:6441,6798` (also `build_daily_snapshots_with_candles()` app.py:6166) | UNKNOWN — not cross-checked against a DB snapshots table in this pass | Yes |
| `training_progress.json` (+`.lock`) | Cross-process ML-training progress for the Data Coverage panel's ETA | `training_progress.py` (full module, ~150 lines) — **atomic (tempfile+fsync+os.replace) AND `fcntl`-locked read-modify-write** (`_locked()` context manager); the module docstring documents a real bug this fixed: two concurrent trainers both reading `done=11` and one clobbering the other, observed live as the progress counter going BACKWARDS (13→11) | `/api/data-health`-style endpoint (per docstring; not traced to exact line in this pass) | Sole source of truth, deliberately file-based BECAUSE training can run in more than one process (scheduler thread vs. a standalone terminal script) and an in-memory counter would be invisible across processes | Yes |
| `.theses.json` | Stock investment theses | `thesis_manager.py:16` (`THESES_FILE`) | `thesis_manager.py`, `thesis_analyzer.py` (not traced further) | UNKNOWN vs DB `stock_thesis`-style table (file `stock_thesis.py` exists — possible DB/file duplication not verified in this pass) | Yes |
| `paper_trades.json.backup`, `paper_trades.json.pre-test-backup`, `paper_trades.json.bak-20260804-211242`, `paper_trades.json.bak-20260804-234241` | One-off manual backups, presumably taken before a risky test/change | UNKNOWN (no code writer found — look like manual `cp` snapshots, e.g. CLAUDE.md op-rule 2's "restoring one file does not undo it" guidance) | n/a | Historical snapshots | **Partly covered by `.gitignore`**: `.gitignore:21` (`paper_trades.json.bak*`) matches the two `.bak-20260804-*` files but NOT `.backup` / `.pre-test-backup`; **all four ARE tracked in git** (`git ls-files` confirms — the `.bak-*` pair was added in commit 8140b23 "…paper trade backups", and `.gitignore` never untracks a file that is already committed) — real trade-data snapshots committed into the repository |
| `index.html.bak`, `index.html.tmp` | Stale duplicate copies of the 946KB dashboard (524KB each, from Apr 20) | UNKNOWN (manual) | n/a | Dead weight | **No — tracked in git**, not gitignored |

### Logs, PID file, caches — VERIFIED FROM CODE

| Path | Purpose | Writer | Rotation | Gitignored? |
|---|---|---|---|---|
| `app_restart.log` | Unknown — likely a restart-script log from an earlier version of the ops tooling | **No writer found** by `git grep` for the literal name in any `*.py`/`*.sh` | n/a | Yes (`*.log`) — legacy/stale file, 144KB, not recently touched |
| `paper_trader.log` | Unknown | **No writer found** (name unreferenced) | n/a | Yes — legacy/stale, 610 bytes |
| `fyersDataSocket.log` | FYERS SDK's own internal WebSocket log (third-party `fyers-apiv3`/`fyers_logger`, not this codebase's logger) | The vendored SDK itself, not our code — referenced only in a `fyers_ws_client.py:466` comment describing a historical double-socket bug diagnosed FROM this file's growth | Vendor-controlled | Yes |
| `tijori_backfill.log` | Presumably a one-off redirected-stdout capture of `tijori_backfill.py` | **No writer found** in code (no hardcoded path) — consistent with a manual `python3 tijori_backfill.py > tijori_backfill.log` invocation rather than app-managed logging | n/a | Yes |
| `nohup.out` | Empty (0 bytes), leftover from an ad-hoc `nohup ... &` not using `$FLASK_LOG` | Shell redirection, not app code | n/a | Yes |
| `.groww-pids` | PID file for the Flask/Next.js/graphify processes `start-all.sh` starts | `start-all.sh:379` (heredoc: `FLASK_PID=`,`NEXTJS_PID=`,`GRAPHIFY_PID=`) | Removed on clean stop (`start-all.sh:170,436`) | **Does not currently exist** (CLAUDE.md's own documented incident: a stale copy of this exact file caused `--stop` to kill the wrong PID and report false success) |
| `chart_cache/` | Per-trade cached OHLC candle JSON for the trade-detail chart | `trade_chart_manager.py:24-25,237-258` `cache_trade_candles()` → `chart_cache/{trade_id}.json` | Cleared wholesale by `clear_trade_cache()` (trade_chart_manager.py:289-295, `shutil.rmtree`+recreate); individual files pruned per-symbol by `symbol_purge.py:86` glob `chart_cache/{s}.*` | Directory currently empty on disk; not gitignored by name but effectively empty so nothing tracked |
| `models/*.joblib` (`git ls-files models` = 55 flat files: per-symbol cash GBC models + `xgb_backtester.joblib`) | Trained model artifacts | Various retrain scripts (`bot.py:90`, `retrain_xgb.py`, `retrain_all_models.py`) | **These flat files ARE tracked in git** (`git ls-files models` = 55) — **but 54 of them are deleted in the working tree** (uncommitted, per `git status`); only `models/xgb_backtester.joblib` is still on disk (modified), so the deletions are pending a commit | Not gitignored, and checked in — binary ML artifacts in version control |
| `models/gbc_cash/`, `models/xgb_cash/`, `models/backtest_cache/` (subdirectories, ~60-70 files each) | Newer per-model-type artifact layout | `cash_backtester.py:266`, `fno_backtester.py:942`, `scheduler.py:429`, `xgb_predictor.py:169` — **all 5 `joblib.dump()` call sites in the codebase use the atomic tempfile-then-`os.replace()` pattern** (CLAUDE.md op-rule 4), confirmed by reading each site: `bot.py:90`, `cash_backtester.py:266`, `xgb_predictor.py:169` (var `tmp`), `fno_backtester.py:942` (var `tmp_path`), `scheduler.py:429` (var `_tmp`); **outside that set**: `retrain_xgb.py:89-95` does `pickle.dump` straight to `/tmp/xgb_models/*.pkl` — non-atomic, but nothing reads that path | **Untracked** by git (not gitignored either — just never `git add`ed) — inconsistent with the flat `models/*.joblib` files above being committed | Untracked, not ignored |

**FINDING:** six tracked files are real trade- or dashboard-data artifacts sitting in git history despite the project's `.gitignore` clearly intending to keep `paper_trades.json`-family and runtime data out of version control: `paper_trades.json.backup`, `paper_trades.json.pre-test-backup`, `paper_trades.json.bak-20260804-211242`, `paper_trades.json.bak-20260804-234241` (4 files of trade data), `index.html.bak`/`index.html.tmp` (stale dashboard copies). The `.gitignore` glob `paper_trades.json.bak*` only matches names starting `...bak`, not `...backup` or `...pre-test-backup` — and the two `.bak-20260804-*` files it DOES match are tracked anyway (a `.gitignore` entry never untracks a file already committed). Total: 6 tracked backup files, 4 of them containing trade data.

## Part 4 — `requirements.txt` dependencies

Installed versions below are read from `.venv/lib/python*/site-packages/*.dist-info` (a listing, not
`pip install` — LAST VERIFIED 2026-09-27) since `requirements.txt` pins almost nothing itself.

### Declared and used — VERIFIED FROM CODE

| Package | Pin in `requirements.txt` | Installed | Imported by (`git grep`, count) | Used? |
|---|---|---|---|---|
| growwapi | none | 1.5.0 | 11 files (`GrowwAPI` client) | Yes — core broker SDK |
| flask | none | 3.1.3 | `app.py` (Flask app itself) | Yes |
| flask-cors | none | 6.0.2 | `app.py:51,269` `CORS(app, origins=ALLOWED_ORIGINS)` | Yes |
| python-dotenv | none | 1.2.2 | 18 files, `load_dotenv()` | Yes |
| numpy | none | 2.4.4 | 12 files | Yes |
| pandas | none | 2.3.3 | 8 files | Yes |
| scikit-learn | none | 1.8.0 (import name `sklearn`) | 1 file (`predictor.py`, GradientBoosting model) | Yes |
| feedparser | none | 6.0.12 | 2 files (RSS news sources) | Yes |
| textblob | none | 0.20.0 | 2 files (sentiment) | Yes |
| requests | none | 2.34.2 | 14+ files | Yes — also the reason `fyers-apiv3==3.1.17`'s own pin (`requests==2.31.0`) can't be a normal requirements line (see below) |
| psycopg2-binary | none | 2.9.12 | 18 files (raw `psycopg2.connect`, alongside SQLAlchemy) | Yes |
| sqlalchemy | none | 2.0.49 | 17 files, core ORM (`db_manager.py`) | Yes |
| **alembic** | none | 1.18.4 | **0 files** — no import, no `alembic.ini`, no `migrations/`/`versions/` directory found anywhere in the repo | **No — installed and declared, but unused. Genuinely dead dependency**, distinct from the app's own code-level dead keys/features |
| PyJWT | none | 2.12.1 (import name `jwt`) | `auth_manager.py` only | Yes — see JWT_SECRET risk in Part 2 |
| google-auth | none | 2.58.0 (import name `google.auth`/`google.oauth2`) | `google_auth.py:150-151` — **lazy imports inside a function**, so a naive head-of-file import scan misses them; **`google_auth.py` is untracked by git**, so `git grep` misses this entirely too (double blind spot) | Yes |
| werkzeug | none | 3.1.8 | 0 direct imports; used transitively via Flask | Yes |
| yfinance | none | 1.3.0 | 3 files (`commodity_tracker.py`, `fno_trader.py`, `fetch_google_prices.py`) | Yes |
| websocket-client | `==1.6.1` | 1.6.1 | Not imported directly by this codebase's own `*.py` — it is a **runtime dependency of the vendored `fyers-apiv3` SDK's `data_ws.py`** (per the `requirements.txt` header comment), pinned here explicitly because `fyers-apiv3` is installed with `--no-deps` (below) and would otherwise have no working WebSocket transport | Yes (indirectly, load-bearing) |
| aws-lambda-powertools | `>=3.0` | 3.34.0 | Same story — dependency of `fyers_logger` inside the SDK; pinned `>=3.0` specifically so it needs only `jmespath`+`typing-extensions`, avoiding the `boto3`/`botocore` chain the SDK's own pinned `1.25.5` would otherwise drag in | Yes (indirectly) |
| setuptools | `<81` | 68.0.0 | Needed because the SDK's `data_ws.py` does `import pkg_resources`, removed from `setuptools>=81` | Yes (indirectly) |
| fyers-apiv3 | **not a requirements.txt line at all** — installed by `start-all.sh` as `pip install -q --no-deps fyers-apiv3==3.1.17` (per the file's own extensive comment, `requirements.txt:19-30`) | 3.1.17 | `fyers_ws_client.py` (`from fyers_apiv3.FyersWebsocket import data_ws`), `fyers_auth.py` | Yes — kept out of the normal pin list because it hard-pins `requests==2.31.0`/`aiohttp==3.9.3`, which conflicts with `growwapi`'s `requests>=2.32.3`/`aiohttp>=3.11.18`; `--no-deps` sidesteps the unsatisfiable resolution. `pip check` will always report 2 unsatisfied `fyers-apiv3` pins as a result — documented as expected. |

### Directly imported in code but MISSING from `requirements.txt` — VERIFIED FROM CODE

A fresh `pip install -r requirements.txt` into an empty venv would not list any of these directly;
all but `xgboost` would still install because a declared package depends on them.

| Package | Installed | Imported by | Why it currently works anyway |
|---|---|---|---|
| **xgboost** | 3.4.1 | `fno_backtester.py:838`, `retrain_all_models.py:50`, `retrain_xgb.py:22`, `scheduler.py:330`, `xgb_predictor.py:53` (`from xgboost import XGBClassifier`) | **Nothing else here depends on it** — this is the only real fresh-install gap; a from-scratch environment install would leave every XGB-model code path broken with `ModuleNotFoundError` at first call, not at install time |
| beautifulsoup4 (`bs4`) | 4.14.3 | `auto_metadata.py`, `cost_scraper.py`, `costs.py`, `tijori_collector.py` (scraping; `cost_updater.py` has no bs4 import) | Transitively installed as a `yfinance` dependency (`yfinance-1.3.0` METADATA: `Requires-Dist: beautifulsoup4>=4.11.1`) |
| joblib | 1.5.3 | 6 files (all the model save/load call sites in Part 3) | Transitively installed as a `scikit-learn` dependency |
| pytz | 2026.1.post1 | 11 files (IST timezone handling throughout) | Transitively installed as a `pandas`/`yfinance` dependency |
| itsdangerous | 2.2.0 | `google_auth.py` (token/nonce signing) | Transitively installed as a `flask` dependency |

**FINDING:** `requirements.txt` is missing 5 directly-imported packages (`python-dateutil` was
dropped from the list: no code imports it — `news_sentiment.py:312` only mentions it in a comment and
the code uses `email.utils`). Only `xgboost` is a real fresh-install gap: nothing declared depends on
it. The other four ride on declared packages — `beautifulsoup4` on `yfinance`, `joblib` on
`scikit-learn`, `pytz` on `pandas`/`yfinance`, `itsdangerous` on `flask` — which works today but is not
a stable guarantee across version bumps.

### Cross-cutting facts (for the maps)

- **External services + endpoints**: FYERS REST + WebSocket (`fyers_client.py`, `fyers_ws_client.py`, token endpoints in `fyers_auth.py`); Groww broker API via `growwapi` (`config.py`, `bot.py`, `fno_trader.py`); Google OAuth (`accounts.google.com` token/tokeninfo endpoints, `google_auth.py:150-151`, `google.oauth2.id_token`); Telegram Bot API (`telegram_alerts.py`, `telegram_commander.py`); Tijori Finance scraping (`tijori.base_url=https://www.tijorifinance.com`); Groww's public pricing pages (`cost_scraper.py`, `https://groww.in/pricing/...`); Screener.in shareholding scrape (`market_intelligence.py`); NewsAPI, Google News RSS, Economic Times RSS, Moneycontrol RSS, X/Twitter (`news_sentiment.py`, gated by `news.source.*`); yfinance (Yahoo Finance).
- **Env vars read** (name — where — default — sensitivity): see Part 2 tables in full; highest-risk ones: `JWT_SECRET` (auth_manager.py:18 — hardcoded literal fallback — **secret, missing from `.env`; forgeable fallback, but only useful to someone who already holds a live session — downgraded from HIGH**), `DB_URL` (config.py:56 — postgres/postgres@localhost fallback — secret), `GROWW_ACCESS_TOKEN`/`FYER_ACCESS_TOKEN`/`FYER_REFRESH_TOKEN` (secret, also written back to `.env` at runtime by `token_refresher.py`/`fyers_auth.py`), `GOOGLE_CLIENT_SECRET`, `NEWS_API_KEY`, `APP_PIN_HASH`, `APP_DEVICE_TOKEN` (all secret).
- **config_settings keys read** (220 rows, ~17 prefix groups): see Part 1 in full. Batch-read helpers (`get_configs`, `get_configs_prefix`) exist specifically to avoid the N+1 pattern CLAUDE.md standard #1 warns about, and `scheduler.py:1202-1220` documents a real historical fix (83,000 queries/day → 1 query/dispatch).
- **DB tables read/written by this section's code**: `config_settings` (`db_manager.py` `ConfigSetting` model — read/written by every `get_config`/`set_config` call cited above); `WatchlistNote` (app.py:4229, primary store for watchlist notes, JSON file is the fallback).
- **Every timed/triggered execution touching config or files**: all 31 `scheduler_interval_*`-named tasks (Part 1 table) dispatched from one batch-read per pass; `cost_scraper` task rewrites the 18 dead `cost.*` lowercase keys every 45 days for no effect; `tijori_refresh`/`market_intelligence`/`supply_chain` tasks write the `tijori.last_collected.*`/`tijori.onboarded.*` dynamic keys and `chart_cache`/`models` artifacts.
- **Rate limits & quotas**: FYERS 10 req/s / 200/min (Standard) enforced via `fyers.rate_per_sec`+`fyers.burst` config (CLAUDE.md op-rule 9); Tijori scrape politeness via `tijori.request_delay_seconds`/`intel.request_delay_seconds` (not a hard external quota, self-imposed).
- **Cost drivers**: `cost_scraper` task network calls every 45 days; `tijori_collector` HTTP scrape volume bounded by `tijori.max_*_per_run` keys; FYERS/Groww API call volume bounded by the rate-limiter config.
- **Data flows**: `.env`/`config_settings` → `get_config`/`_cfg()` helpers → in-process behaviour; broker token refresh: FYERS/Groww API → `os.environ` (immediate) → `.env` file (persisted, regex rewrite) → next process start reads the new value; ML training → `joblib.dump` (atomic tmp+`os.replace`) → `models/*.joblib` → `xgb_predictor.py`/`bot.py` load path; paper trade → `paper_trader.py`/`trailing_stop.py` → `paper_trades.json` (locked read-merge-write) + `trade_journal.json` + DB `paper_trades`/`trade_journal` tables, four writes per trade, not one.
- **Failure modes — fail-open**: `paper_trading` **row missing** → `get_config("paper_trading", "false")` defaults to **LIVE** (bot.py:1286; app.py:5853, 6552, 6631; no code seeds the row — it currently exists and = true); `costs.py`/`tijori_collector.py`/`fyers_client.py`/`fyers_ws_client.py` all fall back to hardcoded literals on any DB error rather than raising.
- **Failure modes — fail-closed**: `paper_trading` read **exception** → **PAPER** (bot.py:1276-1294, code comment "Fail closed"); `trade.no_auto_exit_enabled` unreadable → **freeze stays ON** (trailing_stop.py, explicit docstring reasoning); `_config_cache` miss just re-queries, never silently returns stale-forever data.
- **Dead / legacy / retired**: `cash_autotrade_enabled` (typo twin, no readers); 18 lowercase `cost.*` JSON keys (only 13 hidden by `_CONFIG_DEAD_KEYS`, 5 leak into the Settings UI as live-looking but inert); `tijori.onboarded.*` (write-only, never read back — unlike `tijori.last_collected.*`); `fyers.ws_watchlist_poll_seconds` (seed-only, no reader anywhere); `alembic` package (installed, declared, never used); `app_restart.log`/`paper_trader.log` (no current writer found); `index.html.bak`/`.tmp` (stale, tracked in git).
- **Contradictions found**: (1) `_CONFIG_SENSITIVE_KEYS` masks only `telegram_bot_token`, not `telegram_chat_id`/`auth.allowed_emails`, both of which this doc treats as sensitive per its own instructions. (2) `_CONFIG_DEAD_KEYS` comment claims to hide "these lowercase JSON-valued twins" but misses 5 of 18. (3) `fyers.ws_enabled` seed default is `"true"` (app.py:920) but the live row is `false` — manually flipped post-seed. (4) `.gitignore`'s `paper_trades.json.bak*`/`trade_journal.json.bak*` globs don't match `.backup`/`.pre-test-backup` suffixes, and those files, the two `paper_trades.json.bak-20260804-*` files the glob DOES match (tracked anyway, commit 8140b23), and `index.html.bak`/`.tmp` are all tracked in git (6 tracked backup files, 4 with trade data). (5) `requirements.txt` is missing 5 directly-imported packages (only `xgboost` is a real fresh-install gap; `beautifulsoup4` rides on `yfinance`, `joblib` on `scikit-learn`, `pytz` on `pandas`/`yfinance`, `itsdangerous` on `flask`; `python-dateutil` is not imported by code at all). (6) `google_auth.py` and `generate_book_pdf.py` are untracked by git — every `git grep`-based finding elsewhere in this doc (and likely in other agents' sections) silently excludes them.
- **Open unknowns**: which of `raw.log` (launchd) vs `server.log` (`start-all.sh` nohup) is the currently-live stdout/stderr target; reader of `real_trading_config.json` and `daily_snapshots.json` beyond their writers; whether `.theses.json` duplicates a `stock_thesis.py`-backed DB table; origin of the 3 ungoverned `trade.*` DB rows (no seed call found in any `*.py`); exact reader of `auth.allowed_emails` beyond `google_auth.py:167,183-184` for any additional enforcement points; `APP_DEVICE_TOKEN` (config.py:48) — RESOLVED, no longer unknown: it is a legacy token no longer consulted by the mutation guard (which now checks `X-Requested-With`, app.py:466-471), but it must still be non-empty or `/api/unlock` returns 500 (app.py:332).

## Frontend — Dashboard, Landing Page, Legacy Pages, Next.js, iOS App

Overview: The system exposes one production surface — the vanilla-JS dashboard `index.html` (18,343 lines), served by Flask (`app.py`) behind a PIN-lock/session gate — plus a public marketing page `landing.html`, two apparently-legacy auth pages (`login.html`, `setup.html`), a `frontend/` Next.js scaffold that Flask does not serve (started on :3000 by default by `start-all.sh` unless `--dashboard-only`), and a native iOS wrapper app (`ios/ParthS`, Swift/WKWebView) that loads the same dashboard. PWA surface is minimal (root `manifest.json`, no service worker found). This document covers structure, every feature/panel, the `api()` wrapper, loaders, timers, the protected lock-screen intro, XSS audit points, and the frontend→endpoint table.

### Page structure — `index.html`

| Area | Where | Notes |
|---|---|---|
| `<head>` pre-paint script | index.html:21-57 | Picks lock backdrop colour (navy/olive/wine, `lock_palette`/`lock_col_n` in localStorage) and card colour (`lock_shot_n`, black `#111014`/off-white `#f4f2ee` alternating), paints `document.documentElement.style.backgroundColor` before first paint (iOS samples status-bar strip at first paint only). Sets `window.__lockColour`, `window.__lockShot`. |
| PWA meta | index.html:11-20,58-60 | `apple-mobile-web-app-capable`, status-bar style, `theme-color`, apple-touch-icon, `manifest.json` link. |
| `TAB_DESCRIPTIONS` | index.html:4824-4838 | 13 tabs: predictions, research, analysis, thesis, news, rawmat, intraday, journal, fno-backtest, paper, pnl-chart, alerts, settings. Used as `.title`/`aria-label` for the tab strip (index.html:4840-4855). |
| Mobile bottom tab bar | index.html:4857-4949+ | Builds on top of the same 13 `.tab` DOM elements (not a replacement). `MOBILE_PRIMARY_TABS` = predictions/analysis/journal/research get icons + short labels; rest collapse into a "More" sheet (`#mobile-more-sheet`, role=dialog). CSS-scoped to <=768px. Logout button moved here on mobile. |
| Data Coverage panel | index.html:2127 (CSS), 2976 (markup "Data Coverage" chip), 8760-8784 (JS) | `toggleDataHealthPanel()` shows `#data-health-panel`; while open, polls `loadDataHealth` every 5s via `_startHealthPoll(5000)` (`_dataHealthFastPoll`), stopped on close. **Verified: closes on outside tap** — `document.addEventListener('pointerdown', ...)` at index.html:8779-8784 closes the panel unless the tap is inside it or on `#data-health-chip` (which toggles it itself). Uses `pointerdown` not `click` because iOS Safari doesn't fire `click` on non-interactive areas. |

### `api()` wrapper — index.html:5832-5922
Single fetch wrapper for all `/api/*` calls.
- Method sniffing: GET/HEAD/OPTIONS = read; everything else = write (index.html:5833-5834).
- **Session gate**: while `_sessionState !== 'unlocked'`, writes `await _whenUnlocked()` then recurse; GETs are parked and de-duped by path in `_parkedGets` Map (so 3 pollers ticking before PIN entry become 1 request) — index.html:5844-5857.
- Writes get header `X-Requested-With: XMLHttpRequest` (index.html:5865-5867) — server (`_block_cross_origin_mutations`, header check at app.py:466-471 — this replaced the old static `X-Device-Token` check that CLAUDE.md operational rule 6 still names) refuses non-GET without it; CSRF defense relies on this + SameSite=Lax since a cross-origin page can't add custom headers without a blocked preflight. Session itself is an HttpOnly cookie the browser attaches automatically — JS never touches the credential.
- Response handling: parses JSON only if `content-type` includes `application/json`; else wraps raw text/HTML (e.g. a Flask error page) into `{error: ...}` — index.html:5872-5882.
- Non-2xx: throws `Error` with `.status` set from the HTTP code (index.html:5889-5908). **401 handling**: reveals `#pin-lock`, calls `_setLocked()` — the page's own way of noticing its session died without a dedicated push channel (index.html:5897-5904).
- Non-JSON 2xx also throws (index.html:5909-5913).
- Catch: toasts `'Error: ' + e.message` for every failure EXCEPT status 401 (401 is answered by showing the lock screen, not a toast) — index.html:5915-5921.
- **Session gate primitives** (index.html:4386-4403): `_sessionState` ∈ {unknown, locked, unlocked}; `_whenUnlocked()` returns a pending Promise queued in `_unlockWaiters` until `_setUnlocked()` resolves them all; `_setLocked()` just flips state. Declared very early (before `api`/`API` const exist) because `verifySessionOnBoot` IIFE (index.html:4406-4441) runs during parse: it does `fetch(location.origin + '/api/session')` (not the `API` const — temporal dead zone) and shows/hides `#pin-lock` based on `{authenticated}`; on fetch failure it fails **locked** (shows PIN screen) — fail-closed.
- Idempotency key helpers alongside `api()`: `newIdempotencyKey()` (crypto.randomUUID, index.html:5995-6001), `getOrderKey(intent)`/`clearOrderKey(intent)` (index.html:6017-6033) — persist a per-intent key in localStorage (`idem:<intent>`) for 10 min (`ORDER_KEY_TTL_MS`) so a retry of the same order reuses the same key (server-side dedupe is authoritative; this is the client half). `orderFailureIsAmbiguous(e)` (index.html:6054-6057) — true unless status is a clean 4xx, because order routes call the broker before validating in some paths, so even a "bad request" 400 can follow a real placement attempt; key is only cleared on a 2xx.

### Loaders standard (index.html:5924-6126)
| Fn | Where | Purpose |
|---|---|---|
| `inlineLoader(text)` | 5926-5928 | mini 3-dot orb spinner string for small regions |
| `skeleton(kind, n)` | 5934-5965 | kinds: stats/cards/table/list/chart/default(text) — shaped placeholders mirroring real layout |
| `panelOrb(text, sub)` | 5967-5978 | canvas-animated "thinking orb" (`startOrb`) for multi-second waits; random flavour from `ORB_STATES` |
| `withLoader(target, work, opts)` | 6095-6126 | `{tier, n, text, sub, delay=300}`; nothing shown until `delay` ms elapse (no flash on fast loads); on success clears timer; on error, if the loader had already taken over (or container was empty) shows a retry block (`location.reload()`), else restores prior content — never destroys existing content on a transient error. |
| `withBusy(btn, key, work)` | 6071-6093 | index.html:6059-6069 doc-comment. Double-fire guard keyed by string (not DOM node — re-renders replace the button), disables + relabels button "Working…", `toast('Already working on that…')` on re-entry. UX guard only; server Idempotency-Key is the real duplicate-order defense. Used at 6870, 6891, 8684 (FYERS token paste), 12359, 12397, 13717, 13788 — order/action buttons. |

### Change feed / live price stream (EventSource)
| Name | Where | Detail |
|---|---|---|
| Price stream | index.html:17472 (`_priceSSE = new EventSource(API + '/api/stream/prices')`), reconnect `setTimeout(startPriceStream, 30000)` at 17486 | Live price ticks. |
| Change feed | index.html:17622-17669 (`_feed = new EventSource(API + '/api/events')`) | Backed by `change_feed.py` per comment. Server sends `retry: 3000` so EventSource self-reconnects; comment notes iOS closes the socket when Safari is backgrounded and it needs the session cookie (credentialed request). Re-opened explicitly after PIN unlock if `_feed.readyState === 2` (CLOSED) — see `pinKey()` success path index.html:4342-4345. |

### Portfolio analysis trigger — VERIFIED: exactly 3 call sites for `GET /api/portfolio-analysis`
1. **Auto, once, 30s after boot** — index.html:11987-12001, inside the boot IIFE, `setTimeout(..., 30000)` — comment: "gives scheduler time to populate candles + analysis"; silent (catches errors, only logs, no user-facing error UI); on success calls `renderPASummary`/`renderPAStocks` directly and toasts "Portfolio analysis complete". **No setInterval — confirmed one-shot.**
2. **Manual** — `runPortfolioAnalysis()` (index.html:10652-10669), bound to `id="pa-run-btn"` `onclick` (index.html:3158). Uses `panelOrb` loading state, disables button while running.
3. **Thesis validation** — `validateThesisAgainstAI(symbol)` (index.html:11614-11686), called from `saveThesis`-type flow after `await validateThesisAgainstAI(symbol)` at 11597 (thesis save awaits it before re-rendering). It calls `/api/portfolio-analysis` (11621) to find the stock's AI signal if it's a current holding/position; falls back to `/api/predict/<symbol>` (11637) if not held. Result cached in `localStorage['thesis_ai_' + symbol]`.

### Watchlist add/remove
- **Add**: `addToWatchlist()` index.html:6990+, button at 3180 (`.btn-icon`, onclick).
- **Remove — press-and-hold** (index.html:7038-7118): delegated `pointerdown`/`pointerup`/`pointercancel` listeners on `document` (not per-button — survives re-renders from `loadWatchlist()`). Hold duration 300ms for `.wl-remove` buttons, 600ms for `.close-all-hold` (deliberately longer — closes ALL open positions). Uses `setPointerCapture` so finger drift during the hold doesn't break it; explicitly has **no** `pointerleave` handler (documented regression: capture-phase pointerleave on document fired for the inner label span and cancelled every hold). Keyboard parity via held Enter/Space (`e.repeat` guarded). Fires `removeFromWatchlist(symbol)` (index.html:7123+) which purges all DB rows for the symbol server-side (`symbol_purge.py` per comment) after a confirm-style toast of what will be deleted.
### LOCK SCREEN intro — PROTECTED (CLAUDE.md: never remove/hide/disable/shorten)
Full flow verified against code (matches CLAUDE.md's description exactly):

| Piece | Where | Detail |
|---|---|---|
| Pre-paint colour pick | index.html:21-57 (`<head>` script) | Runs synchronously before first paint (not in `runLockIntro`) — iOS samples the status-bar-strip colour from the document background at first paint only and never re-samples. Backdrop palette from `localStorage['lock_palette']` (validated 3-entry hex array) else `FALLBACK=['#1f2b3a','#4a4f36','#5c2230']` (navy/olive/wine); index stepped via `lock_col_n`. Card ("shot") colour alternates `#111014`/`#f4f2ee` via `lock_shot_n % 2`. Sets `window.__lockColour`, `window.__lockShot`, and paints `documentElement.style.backgroundColor = shot` (root takes the CARD colour since the card ends full-screen and stays behind PIN entry). |
| `.pin-shot` | index.html:347-365 (CSS), 3075 (markup: plain `<div class="pin-shot">`) | **Invariant 1**: plain div with background-color, never an `<img>`. History: it was once an `<img>` of an SVG data URI that iOS WebKit refused to load → grey box → was "fixed" by `display:none`, silently deleting the feature. A coloured block cannot fail to load. |
| `_lockColour()` / `_lockShotColour()` | index.html:4456-4487 | Reuse `window.__lockColour`/`__lockShot` set in `<head>` — **never re-step the alternation** (would desync intro colour from what's already painted on `<html>`). Fallback path reads localStorage synchronously (never awaits a fetch — would flash wrong colour or delay intro); `refreshLockPaletteCache()` refreshes the cache **after** unlock, in the background. |
| `_lockIntroTimers` | index.html:4527 | One shared array (not per-run) — `runLockIntro()` first line (4530) does `_lockIntroTimers.splice(0).forEach(clearTimeout)`. Prevents an in-flight run's timers firing into a restarted run (re-lock within ~4s of opening) — documented regression: card appearing early / keypad revealed mid-animation. |
| `runLockIntro()` | index.html:4529-4648 | **Invariant 5**: every run snaps to hidden state first via `.no-anim` class + forced reflow (`void lock.offsetWidth`) before removing shot-in/shot-full — else a re-lock replay plays the previous card's transitions in reverse. Splits wordmark text into per-char `<span class="ch">` (kerning fixes at CSS nth-child(4)/(5) tied specifically to "OHLCV" — re-measure if the name changes, per CSS comment index.html:389-399). Timers via local `at(ms, fn)` helper pushing into shared list: `at(2150, add 'shot-in')`, `at(2550, add 'shot-full' + landInk())`, `at(3750, finish)`. **Invariant 6**: 2550ms + 1.2s `.pin-shot` transform transition = 3750ms `finish()` — coupled, comment warns to change both together. |
| `finish()` / `jump()` | index.html:4593-4610 | **Invariant 4**: `finish()` is the ONLY place that reveals controls (removes `staging`, adds `shot-in`+`shot-full`, applies ink+ground colours) — anything that prevents `finish()` running locks the user out of PIN entry. `jump()` = reduced-motion/instant path: adds `no-anim`, calls `finish()` immediately, forces reflow, removes `no-anim`. |
| Reduced motion | index.html:4617-4621, CSS 428-432 | `matchMedia('(prefers-reduced-motion: reduce)')` → disables char animation, calls `jump()` (which still routes through `finish()`), returns early — skips the 2150/2550/3750 timer chain entirely. |
| No skip-on-tap | index.html:4643-4648 | Deliberate: staged controls are `pointer-events:none` (CSS 421-424) rather than letting a tap cut the intro short — "the sequence is under three seconds and touching the screen to watch it should not destroy it." |
| Ink flip | `landInk()` 4576, `landGround()` 4582-4585 | Ink (`.on-dark` class, driving text/icon colour) flips on the SAME beat as the zoom (2550ms), matched-duration transition, so wordmark recolours *while* card expands. Backdrop (`.pin-canvas`) repaints only in `landGround()` at `finish()` (3750ms) — repainting it mid-zoom was tried and rejected (visible seam around the still-small card). |
| PIN keypad | `pinKey(n)` index.html:4303-4360 | 4-digit buffer `_pinBuf`; on 4th digit, `POST /api/unlock {pin}` (via raw `fetch`, not `api()` — runs before `api`/`API` exist). Success: reveals dashboard, calls `_setUnlocked()`, restarts change feed if `readyState===2`, releases root colour (`_lockPaintRoot('')`), refreshes lock-palette cache. Failure: dots flash `.wrong`, buffer cleared; if server returned 429, starts lockout countdown. |
| Lockout countdown | `_pinStartTimeout(secs)` index.html:4279-4301 | Absolute end-time (`Date.now()+secs*1000`) survives a throttled background tab; `setInterval` ticks every 1s updating `.pin-subtitle` text "Too many attempts. Try again in M:SS"; adds `.pin-timeout` class (CSS 420: dims + `pointer-events:none` on `.pin-pad`). Server (not client) is the authority — a reload just re-asks and gets remaining time back. |
| Re-lock replay | index.html:18327-18338 | Comment confirms a logout re-shows `#pin-lock` and re-invokes `runLockIntro()` (only adds classes; the invariant-3/5 resets handle replay correctly). |

### Charts (Chart.js v3.9.1, CDN `cdn.jsdelivr.net`, index.html:2919)
No custom charting engine — every chart is a `new Chart(canvas, {...})` instance. Custom-canvas-only exceptions: `startOrb` (boot/panel "thinking orb" animation, plain 2D canvas, not Chart.js).

| Chart | Where created | Canvas id | Feeds from |
|---|---|---|---|
| Per-stock prediction/price chart | index.html:8090 (`new Chart`), period selector `renderChartPeriodSelector` 7911, opened via `setChartPeriod`/`analyzeWatchlistStock` | `chart-${stock.symbol}` (6975) | `/api/prices/{symbol}` |
| Portfolio-analysis per-holding chart | index.html:11263 | `pa-chart-${s.symbol}` (10742) | `loadPAChart` → `/api/prices/{symbol}` |
| Cash backtest cumulative-drawdown chart | `_btcdChart` (12466 decl, 12849 instantiation) | `btcd-chart` (12818) | `/api/cash/backtest/run` |
| F&O backtest chart | `_fbtChart` (12466 decl, 13212 instantiation) | `fbt-chart` (3806) | `/api/fno/backtest/run` / `/multi` |
| P&L-over-time chart | `pnlChartInstance` (18097) | `pnl-chart-canvas` (3915) | `/api/pnl-stats` (`loadDashboardStats`) |
| Symbol intraday chart w/ live updates | `viewSymbolChart`(16060)/`displaySimplifiedSymbolChart`(16936)/`fetchTodaysCandlesAndShowChart`(16219, 15s abort-timeout) | n/a (canvas built dynamically) | `/api/1min-candles`, `/api/5min-candles`, `/api/trade-candles`; live-refreshed via `window._chartUpdateInterval = setInterval(updateChartWithLivePrice, 2000)` (16096) while the chart is open, cleared before a new one starts |

### Timers — full inventory (52 in index.html; source: `docs/function_inventory.json` static scan of `setInterval`/`setTimeout`, VERIFIED count matches COMMON_RULES' "57 timers" total once landing.html(3)+login.html(1)+setup.html(1) are added: 52+3+1+1=57, and 403+25+8+5=441 functions — both cross-checked and correct)

**Recurring pollers (`setInterval`, or a `setTimeout` chain that reschedules itself) — these are the ones with an ongoing resource/battery/API cost:**

| Timer | Interval | Where started | Gate / pause condition | Calls |
|---|---|---|---|---|
| Lockout countdown tick | 1000ms | `_pinStartTimeout` (4300), only while `_pinTimeoutUntil` in future | self-clears at 0 | UI text only, no network |
| Watchlist add — poll for new stock | 3000ms, ≤15 tries | `addToWatchlist` (7014) | stops on found or 15 attempts | `GET /api/watchlist` |
| Backfill status poll | 30000ms | boot IIFE (7339) | none seen — runs continuously; drives backfill overlay | `refreshBackfillStatus` → `/api/tijori/backfill-status` |
| FYERS token login poll | 3000ms, gives up ~5 min | `_fyersPollForToken` (8649) | self-clears via `clearInterval` on match/timeout | `loadFyersToken` → `/api/fyers-token-status` |
| Data Coverage panel fast-poll | 5000ms (param `ms`) | `_startHealthPoll` (8749), only while panel open | cleared on panel close (8768-8771) | `loadDataHealth` → `/api/data-health` |
| Data Coverage background poll | 300000ms (5 min) | boot IIFE (11983) | none — always runs | `loadDataHealth` |
| Smart-update poller | 60000ms (+30s initial `setTimeout`) | `startSmartUpdatePoller` (11471) | none seen | `checkForUpdates` → `/api/check-updates` |
| Market-sentiment refresh | 300000ms (5 min), after 2s initial delay | `startSmartUpdatePoller` (11477) | none seen | `loadMarketSentiment` → `/api/market-sentiment` |
| Market-hours badge | 60000ms | boot IIFE (17547) | none — pure UI clock label | `updateMarketHoursBadge` (local calc, no fetch) |
| **Paper trader FAST loop** | 1000ms | boot IIFE (17565) | **checks `#paper` panel `.active` AND `!document.hidden` AND `isMarketHours()`** — genuinely pauses when tab hidden/inactive/off-hours | `refreshPaperSummaryLive` (read-only: status + live prices + re-render); it calls `api()`, which toasts every non-401 failure before the caller's silent catch (index.html:5919, 17747), so a persistent failure **toasts every second** |
| **Paper trader SLOW loop** | 5000ms | boot IIFE (17605) | **only checks `isMarketHours()` — does NOT check tab visibility/`document.hidden`** (asymmetry vs the fast loop, verified by reading both blocks) | `loadPaperTradingStatus`, which POSTs `/api/update-trailing-stops` and `/api/auto-close/check` — **this one can close positions**, per code comment at 17549-17561 explaining the two-cadence split exists specifically to keep the write-path off the 1s cadence |
| Symbol chart live price | 2000ms, only while a chart is open | `viewSymbolChart` (16096), stored on `window._chartUpdateInterval`, cleared before starting a new one | implicitly stops when a new chart replaces it; no visibility check found | `updateChartWithLivePrice` → `/api/price/{symbol}` |
| Research leaderboard poll while a batch runs | 10000ms, self-rescheduling `setTimeout` | `loadResearchLeaderboard` (13972), only re-arms if `data.batch.running && panel.active && !rs-detail` | stops once batch finishes or user navigates away/into detail | `/api/research/leaderboard` |
| Price SSE (`/api/stream/prices`) reconnect | 30000ms on error | `startPriceStream` (17486) | **VERIFIED DEAD: the only unconditional call site, `startPriceStream();` at line 17491, is commented out** (`// Start SSE on page load (optional — enable by uncommenting below)`) — this entire EventSource + reconnect chain is defined but never runs. Module-existing-≠-running case per CLAUDE.md research rule. | n/a — not started |
| Change-feed debounce | 400ms, self-rescheduling if busy | `_feedOnChange`/`_feedRefresh` (17689/17694) | reschedules only while `_feedBusy`; otherwise one-shot per change | re-renders the tab the feed said changed |

**One-shot delays (boot sequencing, UI transitions, fetch-abort timeouts — not recurring, listed for completeness, not individually detailed):** toast auto-hide (5816), `withLoader` 300ms flash-guard (6102), `fetchWithTimeout` abort (6160), settings-panel open delay (6854), hold-to-delete 300/600ms (7069), `scShowPartnerTip` (8902), `collectWorldNews` 10s refresh (9596), `refreshSupplyChain` 30s refresh (9654), `runAutoAnalysis` 500ms (11394), boot overlay: 12s "Continue anyway" escape hatch (11901), 2500ms minimum show-time (11944), 350ms fade-out (11889), 400ms hand-off to backfill overlay (11950); portfolio-analysis auto-run 30s-after-load (11987, see above); `loadResearchLeaderboard` (13972 — listed above as it self-reschedules); paper-trading-status internal retries (14498/14531/14600); `getLivePrices` abort timeouts (14954/14982, 5s each); chart-fetch abort timeouts 15s/10s (16219, 16979); paper-trades startup timeout 15s (17522); `refreshPaperSummaryLive` abort timeout 4s (17760). None of these recur on their own.

### XSS audit — untrusted text inserted via `innerHTML` without `escapeHtml()`
`escapeHtml()` is defined at index.html:6622-6625 (standard `&<>"'` map) but is **not used at any of the following sites**, all of which render fields sourced from external providers (scraped news/world-news/X posts, i.e. attacker-reachable if a feed is compromised or a source injects HTML in a headline):

| Line(s) | Function | Field(s) inserted raw | Risk |
|---|---|---|---|
| 9204 | (watchlist-news render block) | `a.title` (text), `a.url` (href), `a.source` | headline HTML injection; `href` built from external URL with **no scheme check** — a `javascript:` URL would execute on click |
| 9360 | news tab article list | `a.title`, `a.url`, `a.source` | same |
| 9412 | article render helper | `a.title`, `a.url`, `a.source` | same |
| 9424 | X/Twitter post render helper | `p.title`, `p.url`, `p.source` | same |
| 9563 | (another headline list) | `a.title`, `a.url` | same |
| 10099 | supply-chain heatmap headlines | `h.title`, `h.region` | headline injection (no href here) |

All **six lines VERIFIED present at the exact numbers CLAUDE.md/prompt cited**, current against the working tree as of this read. No `isSafeUrl`/scheme-check helper exists anywhere in index.html (`grep` for `isSafeUrl|safeUrl|javascript:|startsWith('http` = zero hits) — **every** `href="${...url}"` built from external data in this file is unguarded, not just the 6 listed lines; those 5 (9204/9360/9412/9424/9563) are the href-bearing ones among them.

**Lower-severity / self-authored text also unescaped:** index.html:11800 renders `t.comments` (the user's own personal-thesis notes) raw via innerHTML — same-origin/self-XSS risk only (the user attacking themselves), not a third-party vector, but stored notes could carry HTML if ever synced/shared.

**Contrast — deliberate, documented exception:** `notRegisteredYet()` in landing.html (~972-985) builds innerHTML with a **static, hardcoded string** (never user input) and the surrounding comment explicitly states this is why it's safe unlike `setNote()` (textContent-only for anything that can carry a server response) — i.e. the landing page's author was aware of the escaping distinction; the dashboard's news-rendering code does not apply the same discipline.

### FRONTEND → ENDPOINT table (index.html, 101 distinct endpoint+method pairs, 138 call sites — from `docs/function_inventory.json` static AST scan of every `api(...)`/`fetch(...)` call, spot-verified against source)
`{…}` = a template-literal-interpolated path segment or query string (symbol, id, etc.).

| Endpoint | Method | JS function(s):line |
|---|---|---|
| `/api/1min-candles?symbol={…}&start_time={…}&end_time={…}` | GET | fetchTodaysCandlesAndShowChart:16221 |
| `/api/5min-candles?symbol={…}&start_time={…}&end_time={…}` | GET | fetchTodaysCandlesAndShowChart:16238 |
| `/api/5min-candles?symbol={…}&trading_date={…}` | GET | viewTradesOverlay:15359 |
| `/api/auto-analysis` | GET | loadAutoAnalysis:11356 |
| `/api/auto-analysis/run` | POST | runAutoAnalysis:11392 |
| `/api/auto-close/check` | POST | loadPaperTradingStatus:14593 |
| `/api/backtest/{…}` | POST | btcRun:12918, btcCompare:12949 |
| `/api/buy` | POST | quickBuy:6872 |
| `/api/candles/refresh` | POST | analyzeWatchlistStock:8029 — **VERIFIED DEAD ENDPOINT: no matching Flask route exists** (`git grep candles/refresh` over all `.py` files = zero hits; also absent from the 187-route `docs/function_inventory.json` routes list). The call has a `.catch(e => console.debug(...))` (index.html:8033), but `api()` toasts every non-401 failure first (index.html:5919, `toast('Error: ' + e.message, 4000)`), so **each "Analyze" click shows a 4s "Error: /api/candles/refresh returned 40x…" toast** before the silent catch runs. With `static_url_path=""` (app.py:169) a POST likely gets 405 from the static rule rather than 404 (inference, not run). |
| `/api/cash-auto-trade/status` | GET | renderMasterSwitches:5563, _syncCashAutoTradeHeader:5605, loadCashAutoTradeStatus:6760, toggleCashAutoTrade:6832 |
| `/api/cash-auto-trade/toggle` | POST | setToggleCashAuto:5595, toggleCashAutoTrade:6840 |
| `/api/cash/backtest/dates/{…}?limit=120` | GET | btcdLoadDates:12629 |
| `/api/cash/backtest/run` | POST | btcdRun:12660 |
| `/api/check-updates` | GET | checkForUpdates:11406 |
| `/api/close-trade` | POST | manualCloseTrade:15035 |
| `/api/config` | GET | loadSystemConfig:5231, refreshLockPaletteCache:5657 |
| `/api/config` | POST | saveConfigKey:5328, setSaveValue:5494, setToggleBool:5514, saveLockPalette:5759 |
| `/api/data-health` | GET | loadDataHealth:8494 |
| `/api/deep-analysis/watchlist` | GET | loadWatchlistDeepAnalysis:11047 |
| `/api/deep-analysis/{…}` | GET | loadDeepAnalysis:8475, loadDeepAnalysisFull:11201 |
| `/api/events` | SSE | startChangeFeed:17651 |
| `/api/fno/affordable/{…}/{…}` | GET | fnoFindAffordable:12273 |
| `/api/fno/analyze/{…}` | GET | fnoInstrumentChanged:12205 |
| `/api/fno/auto-trade/log` | GET | fnoLoadAutoLog:13480, intradayLoadAutoLog:13898 |
| `/api/fno/auto-trade/run` | POST | fnoRunAutoTrade:13449 |
| `/api/fno/backtest/dates/{…}` | GET | fbtLoadDates:12530 |
| `/api/fno/backtest/instruments` | GET | fbtLoadInstruments:12475 |
| `/api/fno/backtest/multi` | POST | fbtRunMulti:13394 |
| `/api/fno/backtest/run` | POST | fbtRun:12984 |
| `/api/fno/best-opportunity` | GET | fnoAutoPick:12105, intradayAutoPick:13617 |
| `/api/fno/buy` | POST | fnoBuyOption:12361 |
| `/api/fno/capital` | GET | intradayLoadDashboard:12030, intradayLoadDashboard:13521, fnoSyncCapital:13466 |
| `/api/fno/expiries/{…}` | GET | _fnoAutoLoadExpiriesAndOptions:12175, fnoInstrumentChanged:12204 |
| `/api/fno/global-indices` | GET | fnoRefreshGlobal:12428 |
| `/api/fno/option-chain/{…}/{…}` | GET | fnoLoadChain:12319 |
| `/api/fno/positions` | GET | intradayLoadDashboard:12031, intradayLoadDashboard:13522 |
| `/api/fno/rules` | GET | intradayLoadDashboard:12033 |
| `/api/fno/sell` | POST | fnoSellPosition:12399 |
| `/api/fno/sync-capital` | POST | intradaySyncCapital:13880 |
| `/api/fno/trades` | GET | intradayLoadDashboard:13523 |
| `/api/fyers-token-status` | GET | loadFyersToken:8706 |
| `/api/fyers/complete-login` | POST | submitFyersCode:8686 — **not public**: it is not in `_PUBLIC_PATHS` (app.py:221), so it needs a `pin_ok` session (contrast the public `/fyers_callback`) |
| `/api/intelligence/{…}` | GET | loadMarketIntelligence:8233 |
| `/api/intelligence/{…}/collect` | POST | collectIntelligence:8462 |
| `/api/intraday/close-paper` | POST | intradayClosePosition:13797 |
| `/api/intraday/enter-paper` | POST | intradayEnterTrade:13742 |
| `/api/intraday/trades` | GET | intradayLoadDashboard:13523 |
| `/api/journal` | GET | loadJournal:10321 |
| `/api/journal/open` | GET | closeAllOpenTrades:10625 |
| `/api/journal/stats` | GET | loadJournal:10312 |
| `/api/journal/{…}/close` | POST | _closeJournalTradeRequest:10594 |
| `/api/live-prices` | POST | loadPaperTradingStatus:14511, getLivePrices:14961, refreshPaperSummaryLive:17761 |
| `/api/logout` | POST | logoutUser:18317 |
| `/api/margin` | GET | loadMargin:9233 |
| `/api/market-sentiment` | GET | loadMarketSentiment:9327, intradayRefreshMarket:13684 |
| `/api/my-thesis` | GET | loadPersonalTheses:11690 |
| `/api/my-thesis` | POST | savePersonalThesis:11581 |
| `/api/my-thesis/{…}` | DELETE | deletePersonalThesis:11876 |
| `/api/nlp/info` | GET | loadNLPStatus:17454 |
| `/api/paper-trading/settings` | POST | savePaperTradingSettings:5069 |
| `/api/paper-trading/status` | GET | handleTabActivation:4710, loadPaperTradingSettings:5014, loadPaperTradingStatus:14448/14578, loadPaperTradingToggle:15072, loadTradeSnapshots:15920, _feedRefresh:17724, refreshPaperSummaryLive:17748 |
| `/api/paper-trading/toggle` | POST | setTogglePaperMode:5588, togglePaperTrading:15102 |
| `/api/pnl-stats` | GET | loadDashboardStats:9257 |
| `/api/portfolio-analysis` | GET | runPortfolioAnalysis:10660, validateThesisAgainstAI:11621 (+ silent boot auto-call, index.html:11990, not attributed to a named function in the static scan) |
| `/api/portfolio-review` | POST | checkReviewStatus:10649 |
| `/api/predict/{…}` | GET | validateThesisAgainstAI:11637 |
| `/api/price/{…}` | GET | getLivePrices:14985, updateChartWithLivePrice:16787 |
| `/api/prices/{…}` | GET | analyzeWatchlistStock:8037, loadPAChart:11209 |
| `/api/prices/{…}?period={…}` | GET | setChartPeriod:7951 |
| `/api/raw-materials` | GET | loadRawMaterials:10202 |
| `/api/raw-materials/supply-chain` | GET | initHeatmap:9615, renderHeatmap:9685 |
| `/api/refresh-token` | POST | reconnectGroww:9285 |
| `/api/research/all` | POST | runAllResearch:13944 |
| `/api/research/leaderboard` | GET | loadResearchLeaderboard:13967 |
| `/api/research/{…}` | GET | loadResearchDetail:14213 |
| `/api/research/{…}/refresh` | POST | runSingleResearch:13933, runResearchRefresh:14423 |
| `/api/risk-parameters` | GET | loadRiskParameters:5617 |
| `/api/scan` | GET | runScan:6669 |
| `/api/scheduler/settings` | GET | loadSchedulerSettings:5106 |
| `/api/scheduler/settings` | POST | saveSchedulerSettings:5180 |
| `/api/sell` | POST | quickSell:6893 |
| `/api/stock/{…}/news-detail` | GET | loadStockNewsDetail:9441 |
| `/api/stream/prices` | SSE | startPriceStream:17472 (dead — see Timers) |
| `/api/supply-chain-intel/{…}` | GET | loadPASupplyChain:11030 |
| `/api/supply-chain/refresh` | POST | refreshSupplyChain:9651 |
| `/api/telegram/configure` | POST | saveTelegramConfig:17417, toggleTelegram:17440 |
| `/api/telegram/status` | GET | loadTelegramStatus:17396 |
| `/api/telegram/test` | POST | testTelegram:17430 |
| `/api/tijori/backfill-status` | GET | refreshBackfillStatus:7277 |
| `/api/trade-candles?symbol={…}&entry_time={…}&exit_time={…}` | GET | displaySimplifiedSymbolChart:16981 |
| `/api/trade-snapshots/candles/{…}/{…}` | GET | viewTradesOverlay:15368, loadTradeSnapshots:15958 |
| `/api/trade-snapshots/{…}` | GET | viewTradeSnapshot:17382 |
| `/api/update-trailing-stops` | POST | loadPaperTradingStatus:14571 |
| `/api/watchlist` | GET | loadWatchlist:6916, populateNewsQuickStocks:9315, btcLoadSymbols:12599 |
| `/api/watchlist/add` | POST | addToWatchlist:7003 |
| `/api/watchlist/remove/{…}` | DELETE | removeFromWatchlist:7147 |
| `/api/watchlist/{…}/analysis` | GET | analyzeWatchlistStock:8038, loadPAFullAnalysis:11012 |
| `/api/watchlist/{…}/footprint` | GET | removeFromWatchlist:7127 |
| `/api/watchlist/{…}/note` | POST | saveWatchlistNote:8215 |
| `/api/world-news/collect` | POST | collectWorldNews:9594 |
| `/api/world-news?{…}` | GET | loadWorldNews:9508 |
| `/api/unlock` | POST | `pinKey` (4317) — raw `fetch`, not `api()` (runs before `api`/`API` exist); not in static scan's function-endpoint table for that reason |
| `/api/session` | GET | `verifySessionOnBoot` IIFE (4421), boot loader (11915) — both raw `fetch`, same reason |

Not all 138 raw call sites are attributed above (a handful, like the boot-time portfolio-analysis auto-call and the two pre-`api()` bootstrap fetches, run inside anonymous IIFEs the static scanner doesn't name — added as explicit notes instead of dropped).

---

### landing.html — public marketing/lead-capture page
Served at `/` **only** when `config_settings['auth.landing_enabled'] = 'true'` (app.py:987, default off; live value `false`, VERIFIED CONFIG 2026-09-27; read via `get_config`, checked per-request, no caching noted at this call site); otherwise `/` serves the dashboard directly (`_dashboard_page()`, app.py:988) exactly as before. When enabled, a request with a **live** session cookie is redirected to `/app` (app.py:989-990); a request with a **dead** cookie gets the landing page AND has that cookie cleared (app.py:992-993). **Also published as a separate GitHub Pages repo outside this one** (per task brief — not independently verified from this repo, since that repo isn't present here; UNKNOWN — NOT DETERMINABLE FROM THIS CODEBASE whether the two copies are kept in sync).
- `<meta name="robots" content="noindex">` — deliberately kept out of search until ready (comment at top of file).
- Shares the PIN screen's palette system: `--accent` CSS var is one of navy/olive/wine (same triple as `_lockColour()`), though landing.html's own JS does not appear to read the dashboard's `localStorage` cycle — UNKNOWN whether it's synced or independently randomized (not traced further, out of time budget for this pass).
- **Flying bird animation** (`.sky-bird`, SVG, index.html-style `prefers-reduced-motion` guard at line 543 disables it): purely decorative, `pointer-events:none`, sized proportionally (2.64vw) so it stays visible on phones (per commit `3155dd5 Raise the landing bird's minimum size so phones can see it`).
- **Custom cursor**: `initCursor()` (~745), gated to `(hover: hover) and (pointer: fine)` media query so touch devices never get it; sticky-on class, tracks mouse with smoothing, glows near interactive elements.
- **Glass header/footer**: CSS-only (not traced in detail — visual chrome, no logic).
- **Lead-capture sign-in/sign-up forms**: `#sign-in-form`/`#sign-up-form` (568-620) are fake — `handleSignIn`/`handleSignUp` (~975-990) call `e.preventDefault()`, validate only that fields are non-empty, and call `notRegisteredYet(noteId)` which **sends nothing to any server** (comment at ~950: "nothing typed here is sent anywhere or stored") and instead reveals a static `<a href="/deck.pdf" download>` link (deck.pdf is in the static allow-list, app.py:191). The `innerHTML` used to render that link is explicitly safe per the code's own comment because the string is 100%-static, never user input — contrasted deliberately against `setNote()`, which is textContent-only because it can carry a server-derived auth-error message.
- **Google/Apple provider buttons**: real, not fake. `loadProviders()` (~876) does `GET /api/auth/providers` (public route, app.py:1004-1022, reads `config_settings` prefix `auth.provider.*` plus `google_auth.configured()` for Google specifically — i.e. Google needs BOTH the DB toggle AND working `.env` OAuth credentials for the **button** to show as live — the flow itself is not gated by the toggle, see below) and disables/relabels ("… opens soon") each button accordingly. `handleGoogleSignIn()`/`handleAppleSignIn()` just `window.location.assign('/api/auth/google/start')` / `/api/auth/apple/start` when live — real server-side OAuth handoff (`google_auth.py`), landing on `/` with a session cookie afterward. **Apple's button (landing.html:946) points at `/api/auth/apple/start`, which has no route** (VERIFIED: none in app.py; only `/api/auth/google/start` and `/api/auth/google/callback` exist) — clicking it while `PROVIDERS.apple` were true would fail. Currently moot: live `auth.provider.apple=false` (VERIFIED 2026-09-27), so the button is disabled, and `auth.landing_enabled=false`. **Google: button hidden, flow LIVE** — live `auth.provider.google=false` keeps the button disabled ("opens soon"), but `/api/auth/google/start` and `/api/auth/google/callback` are both in `_PUBLIC_PATHS` (app.py:221) and `google_start()` (app.py:1032) checks only `google_auth.configured()`, never `auth.provider.google`; anyone who visits `/api/auth/google/start` directly can start the OAuth flow, and the only remaining restriction is `auth.allowed_emails` (enforced in `google_auth.py`, raising `SignInRefused`).
- Auth-error surfacing: `?auth_error=<code>` query param (set by app.py's Google callback redirects) is mapped through a static `AUTH_ERRORS` dict to a short user-facing message, then stripped from the URL via `history.replaceState`.
- Footer clock: IST-only (`Asia/Kolkata`), independent of visitor's timezone.

### login.html, setup.html — VERIFIED LEGACY / non-functional prototypes, NOT wired to any backend
- **Still served**: `GET /login` → `send_file("login.html")` (app.py:1070-1073, no auth guard); `GET /setup` → `send_file("setup.html")` behind `@require_auth` (app.py:1086-1090, `auth_manager.require_auth`, JWT-based — a **different** auth system from the PIN/session-cookie one the dashboard uses); `GET /dashboard` also exists, `@require_auth`, redirects to `/setup` if the JWT user has no `groww_api_key` else serves `index.html` again (app.py:1076-1083).
- **VERIFIED NOT USED from the live UI**: the only references to `/login` inside index.html (lines 3024/3033/3043/3048) are **inside a commented-out block** (`/* ... */`, index.html:3019-3050, explicit comment "DISABLED: Allow dashboard to display without authentication"). No live link anywhere points a user at `/login` or `/setup`.
- **VERIFIED NON-FUNCTIONAL**: neither login.html nor setup.html contains a single `fetch(` or form `action=` call (`grep` for both = zero hits in both files). Their `<script>` blocks (login.html:643, setup.html:634) just: `handleGoogleSignIn()` sets `localStorage['user_email']`/`['logged_in']='true'` and redirects to `setup.html`; setup.html's API-key form stores the typed key/secret **only in `localStorage`** and redirects to `index.html`; `handleSkip()` sets `localStorage['setup_skipped']` and redirects. None of this ever calls `/api/auth/signup`, `/api/auth/login`, or any other of app.py's real JWT auth routes (`api_signup` etc., app.py:1095+). They are self-contained GSAP-animated mockups from an earlier design pass.
- **Dead client-side leftover in index.html**: outside the disabled block, index.html:3056-3067 still actively monkey-patches `window.fetch` to attach `Authorization: Bearer <token>` from `localStorage['auth_token']`/`window.JWT_TOKEN` if present — harmless in practice today since nothing in the current flow ever sets `auth_token` (the code that used to set it is the disabled block above), but it is live, unconditional, wrapping every fetch the page makes, including the PIN-unlock and session-check calls that run before it. **CONTRADICTION worth flagging**: real, working JWT auth infrastructure exists server-side (`auth_manager.py:203 require_auth`, `/api/auth/signup` etc.) and is exercised by nothing in the current UI — it is orphaned back-end code kept alive by three unused routes and a stub of client-side wiring.
- **Status: LEGACY.** Superseded by the PIN-lock + `auth_session.py` HttpOnly-cookie system that gates the real dashboard. Matches the user's own memory note ("Multi-tenancy phase plan — Phase 0 done, Phases 1-2 on hold").

### frontend/ — Next.js + next-auth scaffold — VERIFIED LEGACY / not integrated (added after the earlier React removal — not a contradiction)
- **Tracked in git**: 25 files (`git ls-files frontend/`) — `app/login/page.tsx`, `app/setup/page.tsx`, `app/api/auth/[...nextauth]/route.ts`, `lib/auth.ts` (NextAuth config using `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` env vars — **a third, independent Google-OAuth implementation**, alongside app.py's own `google_auth.py` and landing.html's provider buttons — none of these three appear to share code or state).
- **Not a contradiction (resolved)**: `cda8263 "Remove React frontend completely - serve static index.html only"` (2026-04-17) deleted a *different*, Vite-based React build (`frontend/dist`, `frontend/index.html`, `frontend/node_modules`); the current Next.js files were added afterwards by `73c29b3` (2026-04-30), 13 days later (`git show --stat cda8263`).
- **Staleness**: `frontend/package.json`, `frontend/app/`, and the `.next/` build directory all last modified **2026-04-19** — over 5 months before today (2026-09-27) and well before the recent lock-screen/OHLCV-rebrand commits. `.next/` holds full build/dev artifacts (`cache`, `server`, `static`, `trace`, `types` and 4 manifest files; ~47 MB) — not just two manifest files.
- **`app.py` still references it**: `ALLOWED_ORIGINS` (app.py:258-266) defaults include `http://localhost:3000` / `http://127.0.0.1:3000` "# Next.js frontend in frontend/" — CORS is pre-configured for it, but nothing in app.py serves its build output or proxies to a port-3000 process, but `start-all.sh` starts it by default (`START_FRONTEND=true`, start-all.sh:42): a plain `./start-all.sh` installs its deps and starts Next.js on :3000; only `--dashboard-only` (the restart command CLAUDE.md prescribes) skips it. It talks to Flask cross-origin, subject to the same `X-Requested-With`/session-cookie rules as any other origin.
- `setup/page.tsx` calls `fetch("/api/setup")` — a **relative** path that would hit the Next.js server itself, not Flask on :8000; no such Next.js API route exists in the 25 tracked files (only `[...nextauth]/route.ts`) — this call would 404 if ever run.
- **Status: LEGACY / dead weight.** Contradicts the user's own memory rule "Keep dashboard vanilla — index.html stays plain HTML/JS; never propose React or a build step." Build artifacts exist (`.next/`, ~47 MB) and `start-all.sh` starts it by default unless `--dashboard-only`; no evidence found that it is deployed or used in production.

### ios/ParthS — Swift/WKWebView wrapper app
4 Swift files, 327 lines total. Loads the **same** dashboard (`index.html`) unmodified — "keep the dashboard vanilla" is explicitly the design rationale in the code's own comments (DashboardWebView.swift header comment).

| File | Role |
|---|---|
| `ParthSApp.swift` | `@main` entry, `WindowGroup { ContentView() }` — trivial. |
| `ContentView.swift` | Composes `DashboardWebView` (always mounted, never destroyed) + `BiometricGateView` overlay. **Deliberately does not conditionally render the WebView** — an earlier version did, which destroyed/recreated the `WKWebView` (and its `sessionStorage`, which the Swift comment treats as the dashboard's session store — STALE: the session is now the HttpOnly cookie managed by `auth_session.py`, and index.html mentions `sessionStorage` only in a comment at :4613) every re-lock; keeping it alive and only covering it with the Face ID gate is what makes the PIN survive a Face-ID re-check. Re-locks (`biometricsPassed = false`) on `scenePhase == .background`. |
| `BiometricGateView.swift` | Second, OS-level gate **in addition to**, not instead of, the dashboard's own PIN (comment: Face ID answers "is this Parth's device", the PIN "does this session hold the API secret"). Uses `LAContext.canEvaluatePolicy(.deviceOwnerAuthentication)` — Face ID **or device passcode**, not biometrics-only. Falls through silently to the dashboard's own PIN screen if no biometrics/passcode configured at all (`status = .unavailable` → `onUnlocked()` immediately) rather than blocking entry. Requires `NSFaceIDUsageDescription` in Info.plist or iOS kills the app on first LocalAuthentication call (documented in project.yml comment). |
| `DashboardWebView.swift` | `WKWebView` wrapper. **URL**: Simulator → `http://localhost:8000` (shares Mac's network stack, Tailscale MagicDNS doesn't resolve in-Simulator); real device → `https://parths-macbook-air.tailfba767.ts.net` (Tailscale Serve reverse-proxies to `127.0.0.1:8000`, terminates real TLS — Flask itself stays bound to loopback only, never exposed on local Wi-Fi). `webView.scrollView.contentInsetAdjustmentBehavior = .never` and `.ignoresSafeArea()` on the SwiftUI wrapper — VERIFIED settings named in the task brief. Implements `WKUIDelegate` for `alert`/`confirm`/`prompt` JS dialogs: **without this the app's 13 `confirm()` calls [index.html has 13 `confirm(` calls; the "14" comes from the DashboardWebView.swift:106 comment] (Buy/Sell/Close-All/F&O orders/Logout) silently no-op and return `false`** — documented as a real regression that was found and fixed (comment: "in the app every one of those actions did nothing at all... failed closed, never executing unconfirmed"). Confirm's safe default on any dialog-presentation failure is `false` (don't act) — fail-closed on money paths, consistent with CLAUDE.md operational rule 8. |

- **Xcode project**: `ios/ParthS/ParthS.xcodeproj` exists and is tracked (the iOS project DOES exist; 4 Swift files, 327 lines).
- **project.yml** (xcodegen source of truth — "editing Info.plist by hand does not survive `xcodegen generate`", explicit warning in comments): iOS 17.0 deployment target, iPhone-only (`TARGETED_DEVICE_FAMILY: "1"`), bundle id `com.parthsharma.ParthS`, `DEVELOPMENT_TEAM` blank (needs manual Xcode team selection before it can be signed/run on-device), `UILaunchScreen: {}` (plain system launch screen — needed or the app runs letterboxed), `NSAppTransportSecurity.NSAllowsLocalNetworking: true` (Simulator-only purpose — permits loopback for `http://localhost:8000`; grants nothing for the public internet, no blanket ATS exception exists since the device build is real HTTPS via Tailscale Serve).
- **Info.plist**: generated, byte-matches project.yml's `info.properties` block (verified by reading both) — `NSFaceIDUsageDescription`, `NSAppTransportSecurity/NSAllowsLocalNetworking`, `UILaunchScreen`.
- No settings screen, no configurability beyond the compiled-in URL constant (one user, one Mac, per design comment).

### PWA bits
- **`manifest.json`** (repo root, whitelisted static file): `name`/`short_name` = **"Parth S."**, `display: standalone`, `start_url`/`scope: "/"`, `background_color: #e9e7e2`, `theme_color: #1e1d20`, icons `icon-192.png`/`icon-512.png` (both exist on disk, `purpose: any`). **CONTRADICTION/stale branding**: index.html's on-page wordmark was rebranded "Parth S." → "OHLCV" (commit `1688e4f`), but **manifest.json's `name`/`short_name` and index.html's own `<meta name="apple-mobile-web-app-title" content="Parth S." />` (index.html:19) were not updated** — the home-screen icon label and PWA install name still say "Parth S." while the app itself says "OHLCV". VERIFIED by reading both files directly.
- **iOS install meta** (index.html:17-20): `apple-mobile-web-app-capable=yes` (this — not manifest.json's `display:standalone`, which iOS ignores per the code's own comment — is what actually removes Safari chrome), `apple-mobile-web-app-status-bar-style=black-translucent`, `theme-color=#1e1d20`.
- **Icons on disk**: `apple-touch-icon.png`, `icon-192.png`, `icon-512.png` all present and whitelisted in app.py's `_PUBLIC_STATIC_FILES`. `favicon.ico` is **also whitelisted but does not exist on disk** (`ls` confirms absent) and nothing in index.html/landing.html references it (`rel="icon"` instead points at `icon-192.png`) — harmless dead allow-list entry, requests would 404 from missing-file, not from the security block.
- **Service worker: VERIFIED NONE EXISTS.** No `sw.js`/`*service-worker*` file found repo-wide (excluding `node_modules`/`graphify-out`), no `navigator.serviceWorker` call anywhere in index.html or landing.html. No offline caching — the app is installable (via the meta tags) but has zero offline capability; every load hits the network.
- **Static-file exposure history** (app.py:172-203, directly explains why index.html/login.html/setup.html are called "self-contained" in a code comment there): `static_folder="."` previously made **every** repo file fetchable over HTTP — the comment records that `GET /.env` once returned 200 with the live `GROWW_API_KEY` in the body, same for `/app.py` and `/paper_trades.json`, and this got materially worse once Tailscale made the box reachable off-localhost. Fixed via an **allow-list** (`_PUBLIC_STATIC_FILES` + `_block_project_file_exposure` before_request hook, app.py:185-203) rather than a deny-list, specifically because a deny-list "silently fails open for every file nobody thought to add to it" — ties directly into CLAUDE.md operational rule 8 (guards must fail closed).

### Cross-cutting facts (for the maps)

**External services called from the frontend (all via the Flask backend, never directly from JS):** none — index.html never calls a third-party API directly; all data comes through `/api/*`. Landing.html's Google-sign-in button navigates to a Flask route (`/api/auth/google/start`) which itself talks to Google. Chart.js is loaded from `cdn.jsdelivr.net` (script tag, index.html:2919); GSAP from `cdnjs.cloudflare.com` (login.html only, legacy).

**Env vars referenced (frontend-adjacent, read server-side):** `ALLOWED_ORIGINS` (app.py:266, default includes `localhost:3000` for the legacy Next.js app) · `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (frontend/lib/auth.ts, NextAuth — separate from whatever `google_auth.py` reads for the Flask-side Google login, not verified here — out of scope for this pass, flagged as UNKNOWN whether they're the same credentials).

**config_settings keys read (frontend-serving logic):** `auth.landing_enabled` (app.py:987, default off, gates whether `/` serves landing.html vs the dashboard) · `auth.provider.google`, `auth.provider.apple`, `auth.provider.email` (app.py:1014, read via `get_configs_prefix("auth.provider.")`, drive `/api/auth/providers`).

**DB tables:** none read/written directly by any frontend file — everything goes through `/api/*` (see 13_backend/routes doc for what those touch); `config_settings` is read by the two config keys above via `app.py`.

**Every timed/triggered execution — WHEN → WHAT (dashboard, index.html):** see the full Timers table above; the two load-bearing recurring writers are the paper-trader SLOW loop (5s, market-hours-gated, POSTs to `/api/update-trailing-stops` + `/api/auto-close/check`, can close real/paper positions) and the auto-close/trailing-stop chain it drives — everything else is a read or a UI-only tick.

**Rate limits / quotas visible from the frontend side:** none enforced client-side beyond the idempotency-key TTL (10 min) and the busy-guard (`withBusy`) — both UX-only; server-side FYERS rate limiting (CLAUDE.md op-rule 9) is invisible to the JS beyond a request occasionally failing.

**Cost drivers:** the paper-trader FAST (1s) + SLOW (5s) loops during market hours are the highest-frequency client-driven load on the backend/broker; Data-Coverage fast-poll (5s while panel open) and the 5-min background poll are comparatively cheap; the symbol-chart live-price interval (2s) only runs while a chart modal is open.

**Data flows:** external news/world-news/X-post providers → backend scrape/store → `/api/world-news`, `/api/stock/{…}/news-detail`, `/api/raw-materials/supply-chain` → index.html news/heatmap renderers → **raw innerHTML, unescaped** (see XSS audit) → rendered DOM. Broker (FYERS/Groww) live prices → `/api/live-prices`, `/api/price/{…}` → paper-trader loops / chart live-update → DOM, never persisted client-side beyond `localStorage` idempotency keys and lock-screen palette state.

**Failure modes:**
- Fail-**closed** (safe): `verifySessionOnBoot` on fetch failure → shows PIN lock (index.html:4435-4440); iOS `BiometricGateView`/`WKUIDelegate` confirm-dialog default → `false` (don't place/close trade) on any presentation failure; `_block_project_file_exposure` allow-list → 404 on anything not explicitly listed.
- Fail-**noisy** (not silent): `/api/candles/refresh` has no route and is permanently broken, but `api()` toasts the error on every "Analyze" click before the caller's `.catch(console.debug)` runs; the paper-trader FAST loop's per-tick errors also toast (via `api()`), so a persistent failure toasts every second.
- Fail-**silent** (risk): XSS sinks fail silently by definition (no error, just unsanitized render).

**Dead / legacy / retired code found in this pass:**
1. `startPriceStream()` (`/api/stream/prices` SSE) — fully implemented with 30s reconnect, but its only unconditional call site is commented out. Dead.
2. `login.html` / `setup.html` / `/login` /`/setup` /`/dashboard` routes / `auth_manager.require_auth` JWT system — real server-side code, zero live client wiring; the only index.html reference to `/login` is inside a disabled comment block.
3. `frontend/` Next.js + next-auth app — tracked in git (added 2026-04-30, after the separate Vite React build was removed on 2026-04-17), untouched for 5+ months, not served by Flask (but started on :3000 by default by `start-all.sh` unless `--dashboard-only`), a third independent Google-OAuth implementation.
4. The `window.fetch` JWT-Authorization monkey-patch (index.html:3056-3067) — live code with no live producer of the token it looks for.
5. `/api/candles/refresh` call with no matching route (see endpoint table; each "Analyze" click toasts an error).
6. `favicon.ico` allow-listed in app.py but absent from disk and unreferenced.
7. `manifest.json` name/short_name and the apple-mobile-web-app-title meta tag still say "Parth S." after the in-app rebrand to "OHLCV".

**Contradictions between code, config, comments or docs:**
- (Resolved) `frontend/` is git-tracked despite the earlier commit titled "Remove React frontend completely" — that commit removed a different Vite React build; the Next.js app was added 13 days later.
- Real JWT multi-tenant auth (`auth_manager.py`, `/api/auth/signup` et al.) exists server-side but is orphaned — no page drives it.
- Landing page's Apple sign-in button has client-side wiring (`handleAppleSignIn`) and a provider flag (`auth.provider.apple`) but **no `/api/auth/apple/start` route exists** in app.py — it would fail if ever enabled; live `auth.provider.apple=false` (VERIFIED 2026-09-27), so the button is disabled.
- Landing page's Google button is hidden/disabled (live `auth.provider.google=false`) but `/api/auth/google/start` is public and gated only by `google_auth.configured()`, so the OAuth flow itself is live.
- Paper-trader FAST loop checks tab-visibility + `document.hidden`; the SLOW loop (the one with write/close-position power) does not — asymmetric pause behavior, verified by direct code comparison, not stated as a bug anywhere in comments.

**Open unknowns (not determinable from this file set / out of this pass's scope):**
- Whether `google_auth.py` (Flask) and `frontend/lib/auth.ts` (NextAuth) reference the same Google OAuth client credentials or two separate ones.
- Whether the separately-published GitHub Pages copy of landing.html is kept in sync with this repo's copy, or has diverged.
- (Resolved) Live values verified 2026-09-27: `auth.provider.apple=false`, `auth.provider.google=false`, `auth.landing_enabled=false`.
- (Resolved) `frontend/` history: the "Remove React frontend completely" commit (`cda8263`, 2026-04-17) removed a different Vite build; the Next.js files were added by `73c29b3` (2026-04-30).

## External Services, Costs, Rate Limits & Legacy Register

Overview: this section inventories every external HTTP/SDK dependency in the repo (broker APIs,
OAuth, news scraping, Telegram, cost scraping), maps billable resources and their scheduler cadence,
and registers legacy/archive/one-off code. Repo root has 98 top-level `*.py` files; `archive/` (42
entries) and `archive/dead_code/` (17 files) are legacy and covered separately below. Evidence
standard per COMMON_RULES.md; DB config values confirmed via prior read-only dumps in
`scratchpad/brain/cfg_rows.txt` (LAST VERIFIED 2026-09-27, per that file's own capture time).

### 1. EXTERNAL SERVICE REGISTER

#### FYERS (broker — market data)
| Field | Detail |
|---|---|
| Provider / product | FYERS Data API v3 (read-only market data) |
| Purpose | Live/historical quotes, candles — VERIFIED FROM CODE: `fyers_client.py:1-8` docstring: "Thin FYERS Data API v3 wrapper — read-only market-data endpoints only. No order-placement methods exist in this module by design" |
| Modules | `fyers_client.py` (REST, `DATA_BASE="https://api-t1.fyers.in/data"` line 18), `fyers_auth.py` (`FYERS_BASE="https://api-t1.fyers.in/api/v3"` line 32; token endpoints `fyers_auth.py:75,100`), `fyers_ws_client.py` (SDK `fyers_apiv3.FyersWebsocket.data_ws`, imported `fyers_ws_client.py:459`), `build_master_ticker_table.py:76` (`FYERS_NSE_CM_URL`, master symbol list, host `public.fyers.in`) |
| Credentials (env NAMES only) | `FYER_APP_ID`, `FYER_SECRET_ID`, `FYER_ACCESS_TOKEN`, `FYER_REFRESH_TOKEN`, `FYER_Redirect_URL`, `FYER_PIN` — VERIFIED FROM CONFIG: `.env` var names, `fyers_auth.py:34-36,141-142,193-194` |
| Request types | GET (quotes/candles), POST (token exchange/refresh) |
| Data sent | app id, hashed app-id:secret-id (SHA256, `fyers_auth.py:70`), access token, symbols, PIN (server-side only, for refresh) |
| Data received | quote/candle JSON |
| Rate limits (stated in repo) | VERIFIED FROM CODE `fyers_client.py:50` (Standard-tier text starts at that line): "FYERS's own documented Standard-tier cap is 10/sec, 200/min (Prime: 600/min). Exceeding the per-minute limit more than 3 times in a day gets the ACCOUNT BLOCKED FOR THE REST OF THAT DAY." Also VERIFIED FROM CONFIG `config_settings`: `fyers.rate_per_sec=2.5`, `fyers.burst=5` (cfg_rows.txt:60-61, description: "Keep under ~3.3/sec (200/min) to avoid 429 rate-limit blocks") |
| Quota/pricing | Standard tier free (per CLAUDE.md operational rules); Prime tier mentioned (600/min) but price not stated in repo — EXTERNAL VERIFICATION REQUIRED |
| Failure implications | 429 → HTML page parsed as JSON fails ("Expecting value: line 1 column 1", `fyers_client.py:24-26` comment); cooldown/backoff implemented, token-bucket cache, per code comments `fyers_client.py:20-40` |
| ACTIVE? | REST (`fyers_client.py`) — ACTIVE (used for quotes/candles per config comment `fyers.ws_enabled=false ... Portfolio Analysis uses the REST path`, cfg_rows.txt:63). WebSocket (`fyers_ws_client.py`) — VERIFIED FROM CONFIG DISABLED: `fyers.ws_enabled=false` (cfg_rows.txt:63, "Master switch for the FYERS live WebSocket. Disabled: Portfolio Analysis uses the REST path and nothing else consumes the feed.") |

#### Groww (broker API — SDK) — the live ORDER-EXECUTION broker
| Field | Detail |
|---|---|
| Provider / product | `growwapi` Python SDK (`GrowwAPI` class) |
| Purpose | VERIFIED FROM CODE: this is the broker that actually places orders — `bot.py:1743,1832` (`groww.place_order(**order_params)`, cash trades) and `fno_trader.py:1678,1753` (F&O orders), plus the paper-guarded GTT stop-loss order at `bot.py:1868-1897` (`groww.create_smart_order(smart_order_type="GTT")`, call at :1897). Also used for quotes/LTP/historical candles as primary/fallback: `bot.py:213` (`get_historical_candle_data`), `fno_trader.py:566,746,1437,1770,1907,1964` (`get_historical_candle_data`, `get_quote`, `get_ltp`). The "Groww → FYERS migration" mentioned in `fyers_client.py:1-8` is **market-data only** — FYERS supplies read-only quotes/candles, Groww remains the order-placement broker. `fii_tracker.py:19,69` also uses GrowwAPI for FII/DII-related data. |
| Modules | `bot.py:145` (`_get_groww()`), `fno_trader.py:353` (`_get_groww()`), `trailing_stop.py:182` (post-trade candle reconstruction only, not live orders), `fii_tracker.py:19,69`, `price_fetcher.py`, `get_token.py`, `token_refresher.py`, `fetch_full_history.py`, `build_master_ticker_table.py`, `load_nse_instruments.py` |
| Credentials (env NAMES only) | `GROWW_ACCESS_TOKEN`, `GROWW_API_KEY`, `GROWW_API_SECRET` — VERIFIED FROM CONFIG: `.env` names, `get_token.py:18-19`, `price_fetcher.py:16`, `token_refresher.py:26-27,46` |
| Request types | GET (quote/LTP/historical candles), POST (place_order) |
| Data sent | access token, trading_symbol, exchange, segment, product, order params (qty, side, price, order_type) |
| Data received | order response (order id/status), quote/candle JSON |
| Rate limits stated in repo | NONE FOUND — `git grep` for Groww + rate-limit terms returned no hits. UNLIKE FYERS, there is no token-bucket limiter module for Groww visible in this pass — EXTERNAL VERIFICATION REQUIRED for Groww's own API limits, and worth flagging as a gap (FYERS has `fyers_client.py`'s elaborate limiter; no equivalent module found for Groww in this pass) |
| Quota/pricing | not stated in repo — EXTERNAL VERIFICATION REQUIRED |
| Failure implications | `token_refresher.py` exists specifically to auto-refresh `GROWW_ACCESS_TOKEN` (updates `os.environ`, `config` module, `.env` file, and resets cached clients — `token_refresher.py:21,45-73`), implying expiry is a known operational risk |
| ACTIVE? | YES — this is the live trading broker for both cash (`bot.py`) and F&O (`fno_trader.py`). CLAUDE.md's money-safety rules (never exercise a write path against live trading records) apply directly to the `groww.place_order` call sites and the `groww.create_smart_order` GTT stop-loss site (bot.py:1897). |

#### yfinance (Yahoo Finance, unofficial, no API key)
| Field | Detail |
|---|---|
| Purpose | Fallback data source for instruments Groww/FYERS don't cover well |
| Modules | `commodity_tracker.py:56` (commodity futures for supply-chain heatmap, e.g. `CL=F`, `GC=F`), `fno_trader.py:580` (MCX commodity fallback when Groww candles fail), `fno_trader.py:2005` (`_fetch_intl_indices` — "Groww doesn't cover them", international indices), `supply_chain_collector.py` (commodity prices, runs every 15 min in a daemon thread per its own docstring, started `app.py:8186-8187` with `interval_seconds=900`) |
| Credentials | none (unofficial public Yahoo Finance scrape via the `yfinance` pip package) |
| Rate limits | none stated in repo; yfinance is well known to throttle/block on abuse — EXTERNAL VERIFICATION REQUIRED |
| ACTIVE? | YES for `supply_chain_collector.py` (started at app boot) and as fallback paths in `fno_trader.py`/`commodity_tracker.py` |
| Note | `fetch_google_prices.py` (root, uses `yfinance`) is NOT imported by any other tracked file — standalone/manual script, see Legacy Register |

#### Telegram Bot API
| Field | Detail |
|---|---|
| Provider / product | Telegram Bot API (`api.telegram.org`) |
| Purpose | Outbound alerts (`telegram_alerts.py`) + interactive command bot via long polling (`telegram_commander.py`) |
| Modules | `telegram_alerts.py:59,78,88` (send/getMe), `telegram_commander.py:78,90,373,1370` (`_BASE_URL="https://api.telegram.org/bot{token}/{method}"` line 34; `requests.get(url, params=params, timeout=35)` at 1370 = long-poll `getUpdates`), also called from `bot.py`, `scheduler.py:1058`, `daily_summary.py:374`, `app.py:7245,8132`, `google_auth.py:242`, `cost_notifications.py:196` |
| Credentials | stored in DB `config_settings`, NOT `.env` — VERIFIED FROM CODE `telegram_alerts.py:24-31`: `get_config("telegram_bot_token")`, `get_config("telegram_chat_id")`, `get_config("telegram_enabled")`. VERIFIED FROM CONFIG (cfg_rows.txt:129-132): `telegram_bot_token`=(secret, not recorded), `telegram_chat_id`=(secret, not recorded), `telegram_enabled`=true, `telegram_cost_notifications`=true |
| ACTIVE? | YES — `telegram_enabled=true` (cfg_rows.txt:132); commander started at app startup under `if __name__=="__main__"` block, `app.py:8191-8195` (`from telegram_commander import start_commander; start_commander()`) |
| Rate limits | none stated in repo — EXTERNAL VERIFICATION REQUIRED (Telegram's own limits apply) |
| Failure implications | alerts silently skipped if not configured/enabled (`telegram_alerts.py:38-45` guard pattern) |

#### Google OAuth (Sign in with Google)
| Field | Detail |
|---|---|
| Provider | Google OAuth2 / OpenID Connect |
| Purpose | Landing-page "Sign in with Google" — VERIFIED FROM CODE docstring `google_auth.py:1-30` |
| Hosts | `AUTH_URL="https://accounts.google.com/o/oauth2/v2/auth"` (`google_auth.py:45`), `TOKEN_URL="https://oauth2.googleapis.com/token"` (line 46) |
| Credentials | `.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (`google_auth.py:58,62`) |
| Endpoints wired | `app.py:1031` `/api/auth/google/start`, `app.py:1043` `/api/auth/google/callback`, both public (`app.py:222`) |
| Gate | The landing-page BUTTON is gated by `auth.provider.google` config AND `google_auth.configured()` (`app.py:1019`) — live `auth.provider.google=false`, so the button is hidden/disabled. The OAuth FLOW is not gated by the toggle: `google_start()` (`app.py:1032`) checks only `google_auth.configured()` and both routes are public, so anyone can start OAuth by visiting `/api/auth/google/start`; only `auth.allowed_emails` limits who gets a session |
| ACTIVE? | YES — VERIFIED FROM CONFIG: `auth.allowed_emails=parttthh@gmail.com` (cfg_rows.txt:3, "Empty = nobody") — only the account owner's own email is allowed |
| Failure implications | errors redirect to `/?auth_error=<code>`, no detail leaked (`google_auth.py:29-31`) |

#### NewsAPI
| Field | Detail |
|---|---|
| Provider | newsapi.org |
| Purpose | News sentiment source, one of several |
| Module | `news_sentiment.py:419-436` (`apiKey: NEWS_API_KEY`, imported from `config` at line 25) |
| Credential | `.env`: `NEWS_API_KEY` |
| Gate | `config_settings.news.source.newsapi` toggle (cfg_rows.txt:86; value shown "(secret, not recorded)" by prior agent's redaction — value itself may just be true/false but was conservatively redacted) |
| ACTIVE? | Gated on both the config toggle and `NEWS_API_KEY` being set (`news_sentiment.py:419: if not NEWS_API_KEY: ...`) — toggle value not independently re-verified this session |
| Rate limits | none stated in repo — EXTERNAL VERIFICATION REQUIRED (NewsAPI free tier is 100 req/day, dev-only, per public docs — NOT found in this repo, so flagged as external) |

#### RSS / scraped news sources (no API key)
VERIFIED FROM CODE — all free, unauthenticated RSS/HTML fetches with a spoofed `User-Agent`:
- Google News RSS (`news_sentiment.py`, `world_news_collector.py`) — `news.google.com`
- Economic Times RSS — `economictimes.indiatimes.com` (gated `news.source.et_rss=true`, cfg_rows.txt:82)
- Moneycontrol — `www.moneycontrol.com` (gated `news.source.moneycontrol=true`, cfg_rows.txt:84)
- Reuters, Bloomberg, MarketWatch, CNBC, feedburner feeds — `world_news_collector.py` (gated `news.source.extra_rss=true`, cfg_rows.txt:83)
- "X/Twitter" source (`news.source.x_posts=true`, cfg_rows.txt:87) is **NOT the X/Twitter API** — VERIFIED FROM CODE `news_sentiment.py:584-645`: it queries Google News RSS with `site:x.com`/`site:twitter.com` search terms, no Twitter credentials anywhere in repo
- screener.in — used by `fundamental_analysis.py:107-249`, `research_engine.py:231-234`, `auto_metadata.py:97-213`, `market_intelligence.py:90-414` (13 literal-URL hits) — fundamentals scraping

#### Tijori Finance (fundamentals/supply-chain scrape)
| Field | Detail |
|---|---|
| Provider | tijorifinance.com (public site, no API key) |
| Purpose | VERIFIED FROM CODE `tijori_collector.py:1-19`: scrapes supplier/customer/competitor connections → `company_connections` table; ratios/peers/forensics → `company_external_data` snapshots (append-only) |
| Base URL / config | `tijori.base_url=https://www.tijorifinance.com` default (`tijori_collector.py:41`), all delays/limits config-driven (`_CONFIG_DEFAULTS`, lines 39-56): `tijori.request_delay_seconds` (code default 2, `tijori_collector.py:41`; **LIVE DB value = 6**), `tijori.timeout_seconds=15`, `tijori.max_symbols_per_run=10`, `tijori.max_partner_snapshots_per_run=12`, `tijori.max_partner_discovery_per_run=15` (comment: "rotates oldest-attempt-first ... without a ~500-request daily cost") |
| Scheduler cadence | VERIFIED FROM CODE `scheduler.py:1384`: `tijori_refresh` every 21600s (6h); `scheduler.py:1387`: `tijori_daily_partners` every 1800s (30 min) but gated to once/day by `tijori.last_partner_refresh` date check (`scheduler.py:604-607`) |
| ACTIVE? | YES — `tijori.enabled=true` default; scheduler tasks registered unconditionally |

#### Groww pricing pages (cost scraper — NOT the broker API)
| Field | Detail |
|---|---|
| Provider | groww.in public pricing pages (no auth, different from Groww broker SDK above) |
| Purpose | VERIFIED FROM CODE `cost_scraper.py:1-18`: scrapes brokerage/STT/exchange/SEBI/GST/stamp-duty rates from `groww.in/pricing/stocks`, `.../pricing/futures-and-options`, `.../calculators/brokerage-calculator`; canonical fallback rates hardcoded `cost_scraper.py:34-40` (marked "Updated: Check pricing pages for latest", dated Jan 2026) |
| Consumer | `costs.py` — the actual trading-cost calculator, loads rates from `config_settings` (`cost.*` keys) with hardcoded defaults as fallback (`costs.py:25-53`): brokerage ₹20/order or 0.05% intraday, STT 0.1%/0.025%, exchange NSE 0.00345% / BSE 0.00375%, SEBI ₹10/crore, GST 18%, stamp duty 0.015%/0.003%, DP ₹15.93/scrip |
| Scheduler cadence | VERIFIED FROM CODE `scheduler.py:1348`: `cost_scraper` task every 3,888,000s (45 days), random initial delay 0-170s |
| Fallback path | on primary workflow failure, `costs.py:229-236` falls back to a simpler scrape of `https://groww.in/charges` with regex extraction |
| ACTIVE? | YES, per scheduler registration |

#### FYERS instrument master CSV/JSON (public, no auth)
| Field | Detail |
|---|---|
| Host | `public.fyers.in` — VERIFIED FROM DOC `docs/FYERS_MIGRATION_MASTER_REPORT.md:~278`: `https://public.fyers.in/sym_details/{SEGMENT}.csv`, all 7 segments, no auth required, "all public, no auth required" (doc's own `[HTTP TEST]` tag) |
| Module | `build_master_ticker_table.py:76` (`FYERS_NSE_CM_URL`) |
| ACTIVE? | Manual/one-off table-build script — `build_master_ticker_table` has no importers among tracked files (see Legacy Register) — likely run by hand, not on a live path |

### 2. SYSTEM COST MAP

| Provider | Service | What we use | Where | Frequency/quantity | Pricing model | Known price | Fixed/variable | Cost drivers | How to reduce |
|---|---|---|---|---|---|---|---|---|---|
| FYERS | Data API v3 | Read-only quotes/candles | `fyers_client.py` | VERIFIED FROM CONFIG: limiter capped at `fyers.rate_per_sec=2.5`, `fyers.burst=5` (≤150/min actual ceiling, under the 200/min Standard cap). VERIFIED FROM CODE `fyers_client.py:267-306`: quotes are batched (≤50 symbols/call) and served from a 2s-TTL cache shared across the four 5-second scheduler tasks that would otherwise all fetch the same symbols (`record_pnl`, `cash_auto_trade`, `fno_auto_trade`, `auto_close_trades` — named in `fyers_client.py:24-28` comment) | Standard tier free; Prime paid, price not in repo | N/A (Standard is free) | N/A — no per-call charge stated; the "cost" is rate-limit risk, not money | Watchlist size (67 active symbols, VERIFIED FROM DATABASE `SELECT count(*) FROM stocks WHERE is_active` = 67, LAST VERIFIED 2026-09-27) drives `ceil(67/50)=2` batched calls per full-watchlist quote refresh — INFERENCE: with 2s cache TTL this bounds real network calls regardless of how many of the 5s tasks ask | cache TTL already collapses duplicate callers; further reduction would mean raising TTL or reducing scheduler task overlap |
| Groww | Trading SDK | Order placement (cash + F&O, plus the paper-guarded GTT stop-loss order at `bot.py:1897`) + quotes/candles fallback | `bot.py`, `fno_trader.py` | UNKNOWN — no rate limiter module found for Groww (see register above); order-frequency is trade-frequency, not scan-frequency | Not stated in repo | EXTERNAL VERIFICATION REQUIRED | Likely brokerage-based, not API-call-based (see `costs.py` rates below) | Number of live trades | N/A — this is the execution path, not a scan |
| Groww | Brokerage/STT/exchange/SEBI/GST/stamp-duty | Per-trade transaction costs | `costs.py:25-53` | Per trade | VERIFIED FROM CODE, `costs.py` defaults (FY 2025-26, DB-overridable via `cost.*` config keys): Brokerage ₹20/order flat (delivery) or lesser of ₹20/0.05% (intraday); STT 0.1% (delivery buy+sell) / 0.025% (intraday sell); Exchange txn NSE 0.00345% / BSE 0.00375%; SEBI ₹10/crore; GST 18% (on brokerage+exchange+SEBI); Stamp duty 0.015% (delivery buy) / 0.003% (intraday buy); DP charges ₹15.93/scrip (delivery sell only) | Variable, per trade | Trade frequency and size | Fewer/larger trades amortize the flat ₹20 and DP charge |
| Groww | Public pricing-page scrape | Keep `costs.py` rates current | `cost_scraper.py` | VERIFIED FROM CODE `scheduler.py:1348`: every 3,888,000s (45 days), random 0-170s initial delay | Free (public page, no auth) | N/A | Fixed (one scrape per 45 days) | N/A | N/A |
| Tijori Finance | HTML scrape | Supply-chain/fundamentals | `tijori_collector.py` | VERIFIED FROM CODE `scheduler.py:1384,1387`: `tijori_refresh` every 21,600s (6h, ≤10 symbols/run per `tijori.max_symbols_per_run`); `tijori_daily_partners` checked every 1800s but gated to once/day (`tijori.max_partner_discovery_per_run=15`, comment notes "without a ~500-request daily cost" — VERIFIED FROM CODE `tijori_collector.py:51`) | Free (public site, no auth) | N/A | Fixed by config caps | Politeness delay `tijori.request_delay_seconds` (live 6; code default 2) self-imposed | Already rate-capped by config |
| Google | OAuth2 sign-in | Auth | `google_auth.py` | Per sign-in attempt (rare — single allowed email) | Free (standard OAuth) | Free | N/A | N/A | N/A |
| NewsAPI | News sentiment | One news source of several | `news_sentiment.py:419-436` | UNKNOWN call frequency this session — gated by `news.source.newsapi` config + `NEWS_API_KEY` env | Free tier commonly 100 req/day per NewsAPI's own public terms — NOT stated in this repo, so EXTERNAL VERIFICATION REQUIRED | EXTERNAL VERIFICATION REQUIRED | Unknown | Unknown |
| RSS feeds (Google News, ET, Moneycontrol, Reuters, Bloomberg, MarketWatch, CNBC) | Free scrape | News sentiment | `news_sentiment.py`, `world_news_collector.py` | Config-gated per source (`news.source.*`, cfg_rows.txt:82-87), cached 600s (`news.cache_ttl_seconds=600`) | Free | Free | N/A | N/A | N/A |
| Telegram | Bot API | Alerts + interactive commander | `telegram_alerts.py`, `telegram_commander.py` | Alerts on trade/summary events; commander long-polls `getUpdates` continuously (35s long-poll, `telegram_commander.py:1370`); `scheduler_interval_telegram_summary=1800` (30 min, cfg_rows.txt:123) | Free | Free | N/A | N/A | N/A |
| yfinance | Unofficial Yahoo Finance | Commodity/intl-index fallback | `supply_chain_collector.py` (every 900s per its docstring + `app.py:8187`), `fno_trader.py`, `commodity_tracker.py` | Free, unofficial | Free | N/A | Risk of being blocked by Yahoo, not billed | N/A |
| PostgreSQL | Local DB | `grow_trading_bot` | Local Mac, not managed/cloud | N/A | Free (self-hosted) | Free | Disk growth (see below) | Storage growth on `fyers_candles` | Partition pruning already in place (32 yearly partitions) |
| GitHub | Git hosting | Source control | `origin = https://github.com/parth-xd/Grow.git` (VERIFIED FROM CODE: `git remote -v`) | N/A | Unknown if public/private repo, unknown plan | EXTERNAL VERIFICATION REQUIRED | Unknown | Repo/LFS size if private+paid tier | N/A |
| Apple/macOS | Local hosting via launchd | Runs `app.py` as a LaunchAgent | `launchd/com.parthsharma.parths.flask.plist` — VERIFIED FROM CODE: `ProgramArguments` runs `.venv/bin/python3 app.py` from `/Users/parthsharma/Desktop/Grow`, `RunAtLoad=true`, `KeepAlive` restarts on crash (not on intentional stop — plist comment explains `stop-all.sh` must use `launchctl bootout`, not a raw `kill`, or launchd treats the kill as a crash and relaunches) | N/A | Free (local Mac, no cloud/VM) | Free | N/A | N/A | N/A |
| Domain | none found | — | `git grep` for `ohlcvlabs`/`.studio`/`ts.net` found no real hits (only false-positive matches on `costs.net_profit(...)`) | — | — | — | — | — | — |

**Storage growth (VERIFIED FROM DATABASE, read-only, LAST VERIFIED 2026-09-27):**
- `grow_trading_bot` total DB size: **22 GB** (`pg_database_size`)
- `fyers_candles` (32 yearly partitions): **22 GB**, ~**70.8M rows** (`sum(reltuples)` across partitions via `pg_inherits`) — i.e. essentially the entire DB footprint is this one append-only table. **Contradiction/update**: CLAUDE.md's operational rule 7 (not the "Current State" section) says "~60M rows" — now measured at ~70.8M; CLAUDE.md's "Current State" section (dated 2026-07-31) says "13 tables", now 35 logical tables (34 plain + `fyers_candles`) + 32 partitions = 67 relations (`pg_class` public: 66 `relkind r` + 1 partitioned parent; `information_schema` BASE TABLE = 67; no other user schemas) — both are stale snapshots, not current facts.
- Other tables are small by comparison: `stock_prices` 80MB/104.5K rows, `global_news` 59MB/73.5K rows, `news_articles` 37MB/43K rows, `trade_journal` 320KB/22 rows.
- `.git` directory: 151MB.

**FYERS cost-per-operation (INFERENCE, bounded by the rate limiter rather than computed from raw scan math):** watchlist = 67 active symbols (VERIFIED FROM DATABASE), batch cap 50/call → a full-watchlist quote refresh needs `ceil(67/50) = 2` calls. Four 5-second scheduler tasks could each want a refresh (48/min × 4 = worst case), but the 2-second quote cache (`_DEFAULT_QUOTE_TTL = 2.0`, `fyers_client.py:48`) collapses same-symbol requests inside that window, and the token-bucket limiter additionally caps sustained throughput at 2.5 req/sec (150/min) regardless of demand. Exact realized calls/day were not measured this session (would require live log inspection, out of scope for a read-only pass) — flagged as **UNKNOWN — NOT DETERMINABLE FROM CODE ALONE**, only its upper bound is.

### 3. REPO HOUSEKEEPING / LEGACY REGISTER

**`archive/` (42 entries, top-level) — one line each:**
| File | What it was | Still referenced? |
|---|---|---|
| `ARCHITECTURE.md`, `DATABASE_QUICKSTART.md`, `DATABASE_SETUP.md`, `ERROR_CORRECTION.md`, `EXPANDED_UNIVERSE_README.md`, `EXPANSION_COMPLETE.md`, `HOW_TO_START.md`, `IMPLEMENTATION_SUMMARY.md`, `README.md` | Superseded docs (early-project setup/architecture notes) | No `git grep` hits from live code |
| `_temp_scrape2/3/4.py`, `_temp_scrape_test.py`, `_test_groww_live.py` | One-off scraping experiments | Not imported anywhere (VERIFIED: `git grep` for each name outside archive found nothing) |
| `acknowledge_error.py`, `cleanup_strategy.py` | Manual maintenance/one-off scripts | Not referenced |
| `demo_tomorrow_signals.py` | Demo script | Not referenced |
| `fetch_real_candles.py`, `fetch_real_prices.py`, `real_market_prices.py` | Superseded by `fyers_client.py`/`price_fetcher.py` | Not referenced |
| `fno_backtester_old.py`, `fno_backtester_v3_backup.py`, `fno_backtester_v4_backup.py` | Prior versions of the live root `fno_backtester.py` | VERIFIED: no references from tracked non-archive `.py` files |
| `generate_5year_data.py`, `generate_5year_optimized.py`, `generate_index_data.py`, `regenerate_data.py`, `resume_generation.py` | Synthetic/backfill data generation, one-off | Not referenced; `5year_generation.log`, `synthetic_gen.log`, `import_progress.log` are their leftover logs |
| `migration_scripts/` (subdir: `aggregate_to_daily.py`, `backfill_candles.py`, `import_nse_stocks.py`, `migrate_schema.py`, `migrate_trades_to_db.py`) | One-off DB migration scripts (referenced by `docs/DATABASE_SCHEMA.md:260` as historical record) | Not re-run; historical record only |
| `setup_price_schema.sql` | One-off schema setup | Superseded |
| `test_automation.py`, `test_bt.py`, `test_fii.py`, `test_groww_api.py`, `test_watchlist.py`, `test_xgb.py` | Ad-hoc test/debug scripts, pass status UNKNOWN (not run per COMMON_RULES) | Not referenced |
| `flask_startup.log` | Leftover log | N/A |
| `docs/` (13 files: `ARCHITECTURE_AUDIT.md`, `AUDIT_SUMMARY.md`, `CLEANUP_REPORT.md`, `CODEBASE_AUDIT.md`, `CODEBASE_AUDIT_DETAILED.md`, `DATABASE_ARCHITECTURE_DIAGRAM.md`, `DATABASE_AUDIT_EXECUTIVE.md`, `DATABASE_AUDIT_FLOW.md`, `DEBUG_OPEN_TRADES.md`, `PAPER_TRADING_README.md`, `TRAILING_STOP_AUDIT.md`, `TRAILING_STOP_IMPLEMENTATION.md`, `TRAILING_STOP_VERIFIED_WORKING.md`) | Historical audits, superseded by live `docs/*.md` | Historical only |
| `dead_code/` (17 files: `_check_coverage.py`, `_check_intervals.py`, `_check_today.py`, `_test_bt_api.py`, `check_candles_simple.py`, `check_data_recency.py`, `check_db.py`, `check_db_dates.py`, `check_db_status.py`, `check_missing_candles.py`, `check_prices.py`, `check_token.py`, `debug_confidence.py`, `test_5min_api.py`, `test_daily_candles.py`, `test_symbol_availability.py`, `test_today_data.py`) | Ad-hoc diagnostic scripts, explicitly marked dead | Not referenced |

**Root-level `*.py` NOT imported by any other tracked file (98 total root scripts; 38 have zero importers among tracked, non-archive `.py` files — VERIFIED via `git grep` for `import X`/`from X import` patterns across tracked files):**
`analyze_losses, app*, build_master_ticker_table, check_groww_market_data, check_raw_fetch, close_trades, collect_index_candles, confidence_analysis, db_cli, execute_high_confidence_trades, fetch_full_history, fetch_google_prices, find_high_confidence_trades, find_quick_trades, fyers_backfill_all_watchlist, fyers_fill_1min_gap, generate_book_pdf, get_real_prices, get_token, groww_market_data_provider, list_active_symbols, live_trade_executor, load_nse_instruments, migrate_auth, migrate_idempotency, migrate_tijori_daily_snapshot, peer_analyzer, real_market_trading, refresh_token_cli, retrain_all_models, retrain_xgb, sanity_check, simulate_profit, test_cash_backtest_leak, test_xgb_price_batching, threshold_analysis, tijori_backfill, verify_api`
(*`app.py` is the entry point by design, not meant to be imported — not "dead".*) These are manual/CLI tools (backfill, migration, diagnostics, one-off analysis) run by hand, not on the scheduler/live path. Two are notable: `retrain_xgb.py`/`retrain_all_models.py` are **separate from** the scheduler's own inline `_task_retrain_xgb_daily` (`scheduler.py:324`, registered `scheduler.py:1380` at 86400s/24h) — the root scripts are manual-retrain tools, not what runs daily. `check_raw_fetch.py` is CLAUDE.md's own cited guard script (`python check_raw_fetch.py` — "exit 1 if any raw mutating fetch() exists") but is itself standalone (run manually/CI, not imported).

**Root `test_*.py` (2 files, pass status UNKNOWN — not run per COMMON_RULES):** `test_cash_backtest_leak.py`, `test_xgb_price_batching.py` — both zero-importer, presumably run manually with pytest/python.

**`tools/`:** `build_function_inventory.py` (generates `docs/FUNCTION_INVENTORY.md`/`function_inventory.json`, per COMMON_RULES explicitly NOT run this session) and `js_inventory.mjs` (JS-side equivalent, presumably for `index.html`, not inspected further — frontend is another agent's scope).

**`book/`:** 9 of a presumably 12-part markdown book (`Part_01,02,03,06,08,09,10,11,12` present; **04, 05, 07 missing** — gap, not verified why). `generate_book_pdf.py` (root, zero importers) presumably renders these to PDF; appears to be a personal writing project about the system, not app functionality.

**`"Smm course/"`:** 4 PDF files (`SMM Concepts Part 1-4`), non-code, unrelated to the trading app — personal course material stored in-repo.

**`graphify-out/`:** knowledge-graph output directory (HTML + JSON + cache + `GRAPH_REPORT.md`) — VERIFIED FROM CLAUDE.md: "2,035 nodes, 114 communities" (as of 2026-07-31, not re-verified this session — would require running graphify, explicitly forbidden). Per git status, many `graphify-out/cache/*.json` files are modified/deleted in the working tree — consistent with a recent graphify run in this session's git history (uncommitted).

**`chart_cache/`:** exists, currently 0 bytes / empty — a runtime cache directory, not source.

**`docs/*.md` (24 files in `docs/`, dates from `ls -la`):** Notable staleness found:
- `docs/DATABASE_SCHEMA.md` (Aug 1, "Live row counts as of 01 Aug 2026") — STALE: live relation count is now **67** (35 logical tables + 32 `fyers_candles` partitions, via `pg_class`/`information_schema`, LAST VERIFIED 2026-09-27) vs whatever snapshot the doc captured ~2 months ago; CLAUDE.md's own "13 tables" claim (dated 2026-07-31) is also stale by the same measurement.
- `docs/FYERS_MIGRATION_MASTER_REPORT.md` (Aug 15) — spot-checked §10 "FYERS Rate Limits" against `fyers_client.py` and CLAUDE.md: **consistent** (10/sec, 200/min Standard, 600/min Prime, 100,000/day; 3-strikes-per-day block rule) — NOT stale on this point. Also documents (§ following 10) that FYERS's documented 50-symbol quote-batch limit is unenforced in practice (tested up to 500) but explicitly warns "do not design against the undocumented 500 behavior."
- `docs/FUNCTION_INVENTORY.md` (965KB, generated 2026-09-27 10:04 IST, same-day) — freshest doc in the tree, used as this whole research pass's starting map per COMMON_RULES.
- Other docs (`ARCHITECTURE.md`, `CHANGELOG.md`, `COST_*` docs, `FYERS_VS_GROWW_MARKET_DATA.md`, `GRAPHIFY_STATUS.md`, etc., Jul-Aug dates) were not individually spot-checked beyond the above two — treat as claims to verify, not facts, per COMMON_RULES.

**`frontend/` (briefly — another agent covers UI in depth):** a git-tracked (25 files) **Next.js** app exists at `frontend/` with its own `package.json`/`node_modules`/`.next` build dir (~47 MB of build artifacts), started by default by a plain `./start-all.sh` (`START_FRONTEND=true`, start-all.sh:42; skipped only with `--dashboard-only`) and also startable via `./start-all.sh --frontend-only`. This coexists with the vanilla `index.html` dashboard that the user's memory explicitly protects ("Keep dashboard vanilla ... never propose React or a build step"). Whether `frontend/` is an active parallel UI, an abandoned experiment, or supersedes `index.html` was **not determined this session** — flagged as a question for the UI-focused section/agent, and worth surfacing to the user given the explicit vanilla-JS memory rule. History (verified): the earlier commit `cda8263` "Remove React frontend completely" (2026-04-17) removed a different Vite build; these Next.js files were added by `73c29b3` (2026-04-30) — not a contradiction.

**`launchd/com.parthsharma.parths.flask.plist`:** exists and is the real production launcher (see Cost Map row above) — runs `app.py` directly (bypassing `start.sh`'s broken exit-code detection, per the plist's own comment), `RunAtLoad=true`, `KeepAlive` restarts on any non-`launchctl bootout` exit.

**iOS project:** EXISTS — `ios/ParthS/ParthS.xcodeproj` is tracked (depth 3, beyond the depth-2 search that originally missed it): 4 Swift files, 327 lines, xcodegen `project.yml`; see the iOS section of 13_frontend for detail.

### Cross-cutting facts (for the maps)

- **External services + endpoints**: FYERS Data API v3 (`api-t1.fyers.in`, `fyers_client.py`/`fyers_auth.py`) — ACTIVE, read-only; FYERS instrument master (`public.fyers.in`) — manual/one-off; Groww SDK (`growwapi`, no fixed host, wraps their API) — ACTIVE, live order execution + fallback quotes; Telegram Bot API (`api.telegram.org`) — ACTIVE, alerts + long-poll commander; Google OAuth2 (`accounts.google.com`, `oauth2.googleapis.com`) — ACTIVE, gated to one allowed email; NewsAPI (`newsapi.org`) — gated by config+env, activity not independently confirmed; Google News/ET/Moneycontrol/Reuters/Bloomberg/MarketWatch/CNBC RSS — ACTIVE, free, config-gated per source; Tijori Finance (`tijorifinance.com`) — ACTIVE scrape, config-throttled; Groww pricing pages (`groww.in/pricing/*`, `groww.in/charges`) — ACTIVE scrape every 45 days; yfinance/Yahoo Finance (unofficial) — ACTIVE fallback for commodities/intl indices.
- **Env vars read** (name, where, sensitivity): `FYER_APP_ID`/`FYER_SECRET_ID`/`FYER_ACCESS_TOKEN`/`FYER_REFRESH_TOKEN`/`FYER_Redirect_URL`/`FYER_PIN` (`fyers_auth.py`, secret); `GROWW_ACCESS_TOKEN`/`GROWW_API_KEY`/`GROWW_API_SECRET` (`price_fetcher.py`/`get_token.py`/`token_refresher.py`, secret); `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (`google_auth.py`, secret); `NEWS_API_KEY` (`config.py`→`news_sentiment.py`, secret); `DB_URL` (`price_fetcher.py` and many others, sensitive — connection string); `APP_DEVICE_TOKEN`, `APP_PIN_HASH` (auth, secret); `ALLOWED_ORIGINS`, `FLASK_HOST`, `FLASK_PORT`, `MAX_POSITIONS`, `MAX_TRADE_QUANTITY`, `MAX_TRADE_VALUE`, `STOP_LOSS_PCT`, `TARGET_PCT`, `WATCHLIST`, `XGB_LIVE_TRADING` (operational, non-secret).
- **config_settings keys read** (key, default, where): `fyers.rate_per_sec=2.5`, `fyers.burst=5`, `fyers.ws_enabled=false`, `fyers.ws_freshness_seconds=2`, `fyers.ws_stall_seconds=60`, `fyers.ws_reconnect_retry=10`, `fyers.ws_backoff_max_seconds=300`, `fyers.ws_watchlist_poll_seconds=60` (`fyers_client.py`/`fyers_ws_client.py`); `telegram_bot_token`/`telegram_chat_id`/`telegram_enabled=true`/`telegram_cost_notifications=true` (`telegram_alerts.py`); `news.source.{google,newsapi,et_rss,moneycontrol,extra_rss,x_posts}` (mostly `true`), `news.cache_ttl_seconds=600` (`news_sentiment.py`); `tijori.*` (enabled=true, base_url, request_delay_seconds=6 (live; code default 2), timeout_seconds=15, refresh_interval_days=7, max_symbols_per_run=10, max_partner_snapshots_per_run=12, max_partner_discovery_per_run=15, onboard_partner_limit=20, user_agent) (`tijori_collector.py`); `auth.allowed_emails=parttthh@gmail.com`, `auth.provider.google` (`google_auth.py`/`app.py`); `cost.*` (BROKERAGE/STT/EXCHANGE/SEBI/GST/STAMP_DUTY/DP keys, defaults in `costs.py:25-36`); `scheduler_interval_telegram_summary=1800` and other `scheduler_interval_*` keys (config-overridable per CLAUDE.md standard #8).
- **DB tables read/written by this section's modules**: `stocks` (67 active, read by watchlist logic), `company_connections`/`company_external_data` (written by `tijori_collector.py`, append-only), `config_settings` (read everywhere via `get_config`), `trade_journal` (written by `bot.py`/`fno_trader.py` order paths), `fyers_candles` (32 partitions, ~70.8M rows, ~22GB — the dominant storage cost), `stock_prices`, `global_news`, `news_articles`.
- **Timed/triggered executions** (WHEN → WHAT): every 5s × 4 tasks → FYERS quote refresh (record_pnl, cash_auto_trade, fno_auto_trade, auto_close_trades); every 2s → FYERS quote cache TTL expiry; every 900s (15 min) → `supply_chain_collector` yfinance/Google-News pass; every 1800s (30 min) → `tijori_daily_partners` check (gated to once/day) + `telegram_summary`; every 21,600s (6h) → `tijori_refresh`; every 86,400s (24h) → `retrain_xgb_daily` (scheduler-inline, not the root script); every 3,888,000s (45 days) → `cost_scraper` (Groww pricing pages); continuous long-poll (35s cycles) → Telegram commander `getUpdates`.
- **Rate limits & quotas**: FYERS — 10/sec, 200/min (Standard) / 600/min (Prime), 100,000/day, 3-strikes-per-day account block (`docs/FYERS_MIGRATION_MASTER_REPORT.md` §10, corroborated in `fyers_client.py` comments and CLAUDE.md); local limiter set conservatively to 2.5/sec (150/min). Groww — no limiter found in repo, EXTERNAL VERIFICATION REQUIRED. NewsAPI — EXTERNAL VERIFICATION REQUIRED. Tijori/Groww-pricing/RSS — no hard external limit known, self-throttled via config delays.
- **Cost drivers**: `fyers_candles` storage growth (22GB/70.8M rows, dominates DB size) is the single largest and only clearly "growing" resource found; everything else in this repo is free-tier API usage with no stated ₹/$ pricing.
- **Data flows**: FYERS/Groww quotes → in-memory cache/limiter → live P&L calc + order decisions (bot.py/fno_trader.py) → `trade_journal` DB + JSON files. Tijori/screener.in/Google-News-RSS/NewsAPI → sentiment/fundamentals scoring → `company_external_data`/`global_news`/`news_articles` tables → dashboard + Telegram alerts. Groww pricing pages/`groww.in/charges` → `costs.py` `cost.*` config rows → every P&L calculation in the app.
- **Failure modes**: FYERS 429 → cooldown + backoff, cache-only reads (fail toward stale-but-safe, per `fyers_client.py` comments — CLAUDE.md standard #8 "guards fail closed" is the general principle but this module's own comments frame it as availability-preserving, not explicitly audited against that standard in this pass). Telegram/NewsAPI/RSS sources — guarded, silently skipped if unconfigured (`telegram_alerts.py:38-45` pattern). Groww — no rate-limit failure handling found in this pass; **flag for money-safety review**: if Groww also enforces a block-on-abuse policy like FYERS, there is no visible local limiter protecting against it.
- **Dead/legacy/retired code**: `archive/` (42 top-level + 17 `dead_code/` + 13 `docs/` + 5 `migration_scripts/`) is fully retired, zero live references confirmed via `git grep`. 38 of 98 root `*.py` files have zero importers among tracked files — manual/CLI tools, not necessarily "dead" but not on any live/scheduled path. `book/` + `generate_book_pdf.py` + `"Smm course/"` are non-app personal-project content stored in-repo.
- **Contradictions found**: (1) CLAUDE.md "Current State" "13 tables" (2026-07-31) vs 35 logical tables + 32 partitions = 67 relations now — stale. (2) CLAUDE.md operational rule 7's "~60M rows" for `fyers_candles` vs measured ~70.8M rows now — stale, growing as expected but the number should be treated as a snapshot, not current. (3) `frontend/` (Next.js) exists and is git-tracked alongside a memory rule that says the dashboard must stay vanilla HTML/JS — partly resolved: it is started by default by `start-all.sh` unless `--dashboard-only`, and was added after (not in conflict with) the earlier React removal; still not clear if `frontend/` is live/intended or an abandoned parallel effort. (4) FYERS has an elaborate, well-documented rate limiter (`fyers_client.py`); no equivalent was found for Groww despite Groww being the actual order-execution broker — a potential blind spot, not confirmed as a real gap without EXTERNAL VERIFICATION of Groww's own rate-limit policy.
- **Open unknowns**: Groww API's own rate limits and pricing (EXTERNAL VERIFICATION REQUIRED); NewsAPI's actual free-tier quota (EXTERNAL VERIFICATION REQUIRED) and whether `news.source.newsapi` is currently toggled on (value redacted as secret in the config dump this session relied on); GitHub repo visibility/plan (EXTERNAL VERIFICATION REQUIRED); whether `frontend/` (Next.js) is actively served in production or experimental only; exact realized FYERS/Groww calls-per-day (would require live log inspection, out of scope for read-only static analysis).

## Technical Debt, Performance & Dangerous Areas

Audit of `/Users/parthsharma/Desktop/Grow` against CLAUDE.md's 8 Engineering Standards and 9
Operational Rules, focused on hot paths: `scheduler.py`, `bot.py`, `app.py` dashboard-polled
endpoints, `research_engine.py`, `deep_analysis.py`, `trade_journal.py`, `fno_trader.py`,
`fno_backtester.py`. All findings VERIFIED FROM CODE unless marked otherwise. LAST VERIFIED:
2026-09-27. Cross-references sections 06/07/09/11 rather than repeating their work; re-verifies
anything repeated.

---

## 1. KNOWN TECHNICAL DEBT — audited against the 8 Engineering Standards

### Standard 1 — No N+1 queries

| # | Finding | Where | Severity | Evidence |
|---|---|---|---|---|
| 1 | `/api/live-prices` (POST, called every 5s by scheduler's `record_pnl` via loopback HTTP — scheduler.py:955, `_task_record_pnl`) loops over the submitted `symbols` list and calls `_get_latest_symbol_price(symbol)` **once per symbol, sequentially**, each of which tries `paper_trader.get_live_price(symbol)` → `bot.fetch_live_price(symbol)` → `FYERSMarketDataProvider().get_ltp(symbol)` — **one external FYERS network call per symbol**, no batching, despite a working batch method (`get_ltp_batch`, used elsewhere at bot.py:1961) existing in the same provider class. No cap on list length either. | `app.py:7524-7548` (loop `for symbol in symbols:` at 7536), `app.py:7461-7472` (`_get_latest_symbol_price`), `fyers_market_data_provider.py:96-98` (`get_ltp`) vs `:104-111` (`get_ltp_batch`, unused here) | **HIGH** (hot loop, 5s cadence, market hours) | VERIFIED FROM CODE |
| 2 | `/api/live-prices-stream` SSE generator loops `for sym in symbols[:20]:` every 10s inside an infinite `while True`, calling `bot.fetch_live_price(sym)` per symbol sequentially — same single-symbol-only path, same unused batch method available. | `app.py:7330-7357` | **HIGH** (dashboard-facing SSE, every open tab) | VERIFIED FROM CODE |
| 3 | `_task_auto_close_trades` (scheduler, live interval 300s — see contradiction in §9) loops `for symbol in open_symbols:` calling `get_live_price(symbol)` once per open position, sequentially, same single-symbol path. | `scheduler.py:860-866` | MEDIUM (background, bounded by open-position count — currently ≤8 rows in `paper_trades` per §11) | VERIFIED FROM CODE |
| 4 | Fix pattern already exists and is used correctly elsewhere: `tijori_collector._load_snapshots_bulk(session, symbols, data_types=(...))` — the one call site (`tijori_collector.py:1419-1421`) passes `data_types` explicitly with an in-code comment citing exactly this class of bug ("without this filter we materialise every historical snapshot row"). CLAUDE.md's own cited example (`get_supply_chain_intel`, 151→3 queries) is this code — confirmed CURRENTLY CLEAN, not regressed. | `tijori_collector.py:1331,1419` | — (clean) | VERIFIED FROM CODE |
| 5 | `to_fyers_symbol()` — called once per symbol inside **every** quote fetch, including inside the "batched" `get_ltp_batch()` (`fy_map = {s: to_fyers_symbol(s) for s in symbols}`, fyers_market_data_provider.py:106) — does its own fresh `session.query(MasterTicker).filter_by(...).first()` per symbol, uncached, by explicit design (comment: table is small, correctness over caching). So even the "fixed" batch path is N DB queries + 1 batched external call, not fully N+1-free. | `fyers_market_data_provider.py:36-55` | LOW (documented tradeoff, `master_ticker_table` only 2,467 rows per §11) | VERIFIED FROM CODE, INFERENCE on impact |
| 6 | Two `for ... in ...:` loops that *look* like N+1 on cursory grep are **false positives** (confirmed by reading): `app.py:1680` (`for s in stocks:` after a single `get_all_stocks()` call — pure Python dict-building, `s.get_competitors()` is a `json.loads` of an already-loaded column, exactly the false-positive case the codebase-health skill calls out) and `app.py:3928` (formatting loop after one raw-SQL query). Per-symbol model retrain loops (`scheduler.py:496,541` — `bot.train_model`/`train_xgb_model` per symbol) are **not** N+1: each iteration is a genuine standalone ML fit, not a batchable query. | `app.py:1680`, `app.py:3928`, `scheduler.py:496,541` | — (non-issues) | VERIFIED FROM CODE |

### Standard 2 — Bound every read that can grow

- `?limit=` params found in `app.py` are correctly clamped: `app.py:1482` `min(int(request.args.get("limit", 50)), 200)`, `app.py:3814` `min(..., 250)` — matches CLAUDE.md's own reference pattern. **Clean** (VERIFIED — only 2 such params exist in app.py; no unclamped `?limit=`/`?days=` found).
- **Already-flagged, re-verified**: `fno_backtester.run_fno_backtest`/`run_multi_backtest` call `_fetch_candles_from_db(instrument_key)` with no `days` → unbounded full-history read of `fyers_candles` (~5s/~770MB per symbol per the code's own comment) — see section 07 for full detail. Confirmed still present. **HIGH** (user-triggered via `/api/fno-backtest/run`, `/multi`).
- `trade_journal.py:119` — `session.query(TradeJournalEntry).order_by(...).all()`, no LIMIT, loaded once at boot into the in-memory `_journal` list. Currently harmless (22 rows, §11) but latent: nothing bounds this if the table grows into the thousands. LOW/INFERENCE.
- No unbounded `.all()` found on `stock_prices`/`global_news`/`news_articles`/`company_external_data` in the files audited this pass (`bot.py`, `app.py`, `research_engine.py`, `deep_analysis.py`, `trade_journal.py`) beyond the fno_backtester case above.

### Standard 3 — Parallelize independent I/O

- **Clean reference patterns confirmed**: `research_engine.py:1681` (`ThreadPoolExecutor(max_workers=6)` + `as_completed`, matches CLAUDE.md's own cited idiom), `deep_analysis.py:817-819` (`ThreadPoolExecutor(max_workers=3)` + `as_completed(timeout=120)` for multi-symbol batch generation), `fno_trader.py:2029` (`ThreadPoolExecutor(max_workers=4)` for international indices, 20s per-ticker timeout) — all correctly parallel.
- `generate_deep_analysis(symbol)` itself (`deep_analysis.py:464` onward) does **not** make network calls — every data source (`commodity_tracker`, geopolitical context, global news) is a local DB read, so the scheduler's sequential 6-symbol pre-warm loop (`scheduler.py:758`, `_task_deep_analysis`) is not a network-sequential-I/O violation; each iteration is DB-local and fast. Re-classified out of the "sequential I/O" bucket after reading the function body — flagged as a candidate by grep, ruled out on inspection.
- The three live-price loops in Standard-1 findings #1-3 are simultaneously Standard-3 violations: N sequential blocking network calls where none depends on another's result, with a working batch alternative unused.
- No `ThreadPoolExecutor(max_workers=1)` (timeout-guard-not-parallelism antipattern) found in the audited files.

### Standard 4 — Optimistic UI

Not independently re-audited this pass (out of file scope — `index.html` frontend patterns belong to section 13); section 09 notes one confirmed optimistic-UI implementation (`app.py:5191`, `/api/portfolio-analysis` background refresh with instant cached serve).

### Standard 5 — Loading states

Not independently re-audited this pass — frontend-scope, belongs to section 13.

### Standard 6 — Labelled controls

Not independently re-audited this pass — frontend-scope, belongs to section 13.

### Standard 7 — Missing data must be visible

**Finding — retrain failure RATE is invisible; only staleness is checked.** `/api/data-health`
(`app.py:2419-2427`, docstring: "Exists so silent data gaps surface on their own") checks ML model
health by **file mtime staleness** only: `_model_stats()` globs `models/gbc_cash/*.joblib` /
`models/xgb_cash/*.joblib`, computes an age, and flags "stale" only if the newest file is >48h old
(`app.py` §data_health, "Stale = older than 48h; the retrain task runs every 24h, so anything past
two cycles means retraining is not happening"). It does **not** read the retrain task's own
trained/failed counts. Cross-referencing the app log (see Performance Map, GBC retrain row) shows
the scheduled `ml_retrain` task logged **"0 trained, 66-73 failed"** on the large majority of runs
from at least 2026-08-21 through 2026-09-25 (MEASURED), with only occasional partial success (e.g.
48/73, or today 2026-09-27's 48/67) — meaning at least one symbol's file gets refreshed often enough
to keep the *staleness* check green while the *success rate* for most symbols has been near-zero for
over a month. This is a real invisible-gap under the same standard `/api/data-health` exists to
enforce, just on a task's success rate rather than a dataset's coverage. Partially mitigated in
practice by `model.gbc_cash_enabled=false` LIVE (§06) — the broken model isn't currently used for
live cash predictions — but the failure is undetectable from the dashboard either way. **MEDIUM**
(mitigated by the model being disabled, but the underlying gap-detection logic doesn't know that).
- Compounding: the per-symbol failure reason is logged at `logger.debug` (`scheduler.py:503-506`,
  `:549-551`), which never reaches the INFO-level `app.log` — so even reading the log file (as this
  audit did) cannot show *why* 66+ symbols fail per run, only that they do. Root-causing this would
  require raising the DEBUG log level or reproducing manually. UNKNOWN — NOT DETERMINABLE FROM
  LOGS AT CURRENT LEVEL.

### Standard 8 — Config over constants

Re-verified, not re-litigated (see section 07 for full detail): `fno_trader.py` hardcodes the
trailing-stop drawdown trigger (15%, line 2305), the option liquidity gate (`open_interest < 10000`,
line 2499), and declares `avoid_expiry_day`/`mcx_close_hour`/`mcx_close_min` in
`_AUTO_TRADE_CONFIG` that are **never read anywhere** (dead flags presented to the user as active
via `/api/risk-parameters`). `_AUTO_TRADE_CONFIG` itself is runtime-mutable via an endpoint but
**in-memory only** — not persisted to `config_settings`, reverts on restart. The FYERS rate-limiter
literal fallback (Standard-8-relevant since it's a hardcoded safety constant) was checked and is
**currently correct**: `fyers_client.py:71-72` `_DEFAULT_RATE=2.5`/`_DEFAULT_BURST=5` (150/min +
burst, under the 200/min Standard cap) exactly matches the LIVE `config_settings` values
(`fyers.rate_per_sec=2.5`, `fyers.burst=5`, VERIFIED FROM DATABASE 2026-09-27) — the historical
mismatch CLAUDE.md op-rule 9 describes (fallback 5.0/sec vs DB 2.5/sec) is **resolved**, fallback and
live config now agree.

---

## 2. PERFORMANCE MAP

| Workflow | Runtime | Basis | API calls / concurrency | Notes |
|---|---|---|---|---|
| World news collection (`_task_world_news`, every 900s) | **32-124s** typical, one MEASURED outlier at **937.8s** (2026-09-24 12:31) | MEASURED — `app.log` lines e.g. "World news collected... 71.8s" (2026-09-27 09:23), "...937.8s" (2026-09-24 12:31) | RSS + Google News fetches | Per-task lock prevents overlap (§09) even when a run overshoots its own 900s interval; a 937.8s run just delays the next tick, doesn't corrupt state |
| Self-healing (`self_healing.run_all`, every 3600s) | Typically **0-30s**, occasional long runs: **995.2s, 913.0s, 460.0s** MEASURED | MEASURED — `app.log`, "self-heal run: ... (Ns)" | FYERS backfill calls when a real repair is needed | Long runs correspond to genuine backfill/top-up work (healer 2/3), not a bug — matches the cooldown-gated design in §09 |
| Cash GBC retrain (`_task_ml_retrain`, daily, ~25min staggered per §09) | Compute-bound, per-symbol `bot.train_model` | MEASURED completion timestamps only (no per-symbol duration in INFO log) | 0 network calls (local compute) | **Success rate near-zero most days** — see Standard-7 finding above; "0 trained, 66-73 failed" MEASURED repeatedly 2026-08-21→2026-09-25 |
| Cash XGB retrain (`_task_xgb_cash_retrain`, daily, ~10.3min per §09) | MEASURED — "Cash XGB retrain complete: 65-66 trained, 1 failed (of 66-67)" consistently | MEASURED | local compute | Healthy — nearly all symbols succeed every run, unlike GBC sibling |
| F&O XGB retrain (`_task_retrain_xgb_daily`, daily, ~31min per §09) | 30-40 min per code comment (fno_backtester.py) | comment/doc-cited (ESTIMATED, not seen in this pass's log grep) | local compute, `n_estimators=150` × 2 models (long/short) over all `BACKTEST_INSTRUMENTS` | See Dangerous Areas §3 for an unguarded-lock race with the live signal path's own retrain-on-miss |
| F&O manual backtest (`/api/fno-backtest/run`) | UNKNOWN/unbounded — no `days` cap, full-history resample | code comment cites "~5s/~770MB peak for a liquid name" per *symbol* for the analogous unbounded case in `db_manager.py` (MEASURED there, not re-measured for this specific caller) | 1 unbounded `fyers_candles` read | On-demand only, not scheduled — worst case borne by whoever clicks it |
| `/api/live-prices` (record_pnl, every 5s market-open) | UNKNOWN wall time — scales linearly with symbol count × 1 FYERS call each, no batching | INFERENCE from code path (Standard-1 finding #1) | N sequential external calls, N = symbols requested | Candidate bottleneck if watchlist/open-position count grows; currently small enough to not have surfaced as an incident |
| `/api/data-health` | Not re-measured this pass; CLAUDE.md itself documents a prior fix (190s→0.7s) for this exact endpoint (op-rule 7) | doc-cited, ESTIMATED still valid absent contrary evidence | batched counts, per its own docstring "must stay cheap enough to poll" | — |
| Watchlist scan (GBC + XGB blend) | UNKNOWN — not measured this pass; `bot.py:634-657`/`1201-1271` parallelize per-symbol prediction via `ThreadPoolExecutor` (pool size not confirmed in this file's excerpt) | INFERENCE (parallel pattern present) | 1 batch price fetch + N parallel model-inference calls | Out of this pass's read depth for a precise pool size — flag for follow-up |
| Auto-trade cycle (cash, every 5s) / (F&O, every 5s, currently gated off) | UNKNOWN — not measured; `fno_trader.auto_trade_fno()` internals covered qualitatively in §07 | — | capital sync + exit check + entry scan per cycle | F&O currently gated off live (`fno_auto_trade_enabled=false`, §07) so this cycle is presently a no-op on the scheduler path |
| Trailing-stop / TP-SL monitor (`_task_auto_close_trades`) | Coded interval 5s, **LIVE override 300s** (§09 contradiction) | VERIFIED FROM DATABASE | 1 sequential FYERS call per open symbol (Standard-1 finding #3) | Currently small position count keeps this cheap despite being sequential |

---

## 3. DANGEROUS AREAS

### Paper/live gate
Covered fully in §06/§07: `bot.is_paper_mode()` fails toward PAPER when the read raises an exception
(`bot.py:1276-1294`, "Fail closed" — fail-closed on exception); only exact `{false,0,no,off}` select LIVE. **LIVE VALUE (VERIFIED FROM DATABASE
2026-09-27): `paper_trading=true`** — system is in paper mode. Invariant: never weaken the
asymmetric string match, since that's the entire fail-safe. **Caveat — a MISSING `paper_trading` row defaults to LIVE**: `get_config("paper_trading", "false")` (bot.py:1286; also app.py:5853, 6552, 6631), and no code seeds the row (only toggles: app.py:6554, telegram_commander.py:1175) — so a fresh DB or restored backup without the row would run LIVE. The row currently exists (= true).

### Lock-screen intro (PROTECTED, per project CLAUDE.md)
Not touched, not re-audited beyond confirming the CLAUDE.md protection block exists and instructs
never to alter `.pin-shot`/timer/colour-pick invariants without explicit approval. Out of this
research task's file scope (`index.html`); flagged here only to record that the protection rule
exists and was respected (no edits made, per COMMON_RULES read-only mandate anyway).

### FYERS rate limiter
`fyers_client.py:56-201`. Token bucket (`_acquire_token`, `_bucket_lock`-protected refill),
exponential-backoff cooldown on 429 (`_note_429`, doubling 5s→300s cap, **locked** — the
CLAUDE.md-documented unlocked-race bug is fixed, reusing `_bucket_lock`). **Literal fallback
verified current and safe** (2.5/sec, burst 5 → 155/min effective ceiling, under the 200/min
Standard-tier cap) and **matches live DB config exactly** (VERIFIED FROM DATABASE 2026-09-27) — no
drift between fallback and live config today. Invariant: any future change to `fyers.rate_per_sec`/
`fyers.burst` must keep `rate*60+burst` under 200/min (600/min Prime) — exceeding it 3× in a day
gets FYERS to block the account for the rest of that day (CLAUDE.md op-rule 9), a much harsher
penalty than ordinary throttling.

### Symbol purge (`symbol_purge.py`)
Per §11: explicit `PURGE_TABLES` vs `KEEP_TABLES` split (financial history — `trade_journal`,
`paper_trades`, `trade_snapshots`, theses — is never deleted by this path); refuses if the symbol
has an open paper position; any table with a symbol column not in either list is reported
`unclassified` rather than silently skipped (fails toward visibility, not silent data loss). One
drift noted in §11: `stock_prices` is still in `PURGE_TABLES` despite no longer being written by the
collection pipeline (last write 2026-05-29) — purge logic hasn't been updated to reflect that the
table is now read-legacy-only; not dangerous (only means purge deletes rows from a table nothing
repopulates), but worth reconciling.

### Scheduler task overlap
Per §09: `_task_locks` (`threading.Lock`, `blocking=False`) skip a tick if the previous run of the
same task is still executing — verified this prevents same-task overlap. The 3 daily retrains are
explicitly staggered by measured runtime + margin (T+150/1800/3000, §09) specifically because two
~30min jobs once started 10s apart (CLAUDE.md op-rule 5's cited incident). **Cross-task** overlap is
a separate, narrower concern — see the XGB model-save race below, which is a race between two
*different* tasks/call-paths writing the *same file*, not a same-task overlap (which the lock
already prevents).

### Model save atomicity — every `joblib.dump` site checked
All 5 sites use the correct temp-file + `os.replace()` pattern (atomic rename):
`bot.py:88-91` (cash GBC), `xgb_predictor.py:166-170` (cash XGB), `cash_backtester.py:264-267`
(backtest cache), `fno_backtester.py:940-949` (`_get_xgb_models()` lazy load-or-train path),
`scheduler.py:428-436` (`_task_retrain_xgb_daily`, the scheduled F&O retrain). Each has an in-code
comment citing the exact incident this fixes (e.g. fno_backtester.py: "a training run was killed 16
minutes in on 2026-08-25").

**NEW FINDING — the two F&O XGB save sites are not mutually exclusive with each other.**
`fno_backtester.py` defines `_xgb_lock = threading.Lock()` (fno_backtester.py:588) specifically
because two concurrent `_get_xgb_models()` callers (e.g. two backtests started at once) used to both
train and both `joblib.dump()` to the same path, corrupting it — documented in-code as a fixed bug
(fno_backtester.py:572-587: "the second caller now waits and takes the first caller's result").
However, `_task_retrain_xgb_daily` (`scheduler.py:324-450`, the independently-scheduled daily
retrain) implements its **own** duplicate training-and-save logic — it does not call
`_get_xgb_models()` and does **not** acquire `fno_backtester._xgb_lock` before writing
`fno_backtester._xgb_models` (scheduler.py:398, unguarded assignment) or before its own
`joblib.dump`+`os.replace` (scheduler.py:428-436). Both save sites additionally build their temp
filename as `f"{_XGB_MODEL_PATH}.tmp.{os.getpid()}"` (fno_backtester.py:941, scheduler.py:428) — and
since both run as threads inside the **same process** (scheduler's `ThreadPoolExecutor`, §09),
`os.getpid()` is identical for both, so a genuine overlap between the scheduled retrain and a
live-path cold-start retrain (e.g. right after a restart, before the disk cache is populated, when
`_get_xgb_models()` still hits its "train fresh" branch from the 5s F&O signal path) would produce
**two threads writing to the literal same temp path** — the exact "interleaved dump" failure mode
the `_xgb_lock` comment claims is fixed, just not fixed across this second, independent code path.
Likelihood is LOW in steady state (the in-code comment notes the disk cache normally loads in
milliseconds, so the live path's own retrain branch is "almost never reached"), but the invariant
("only one writer to `models/xgb_backtester.joblib` at a time") is not actually enforced end-to-end.
**MEDIUM** severity, INFERENCE-based on control flow (not observed in logs this pass).

### Raw mutating fetch() guard (`check_raw_fetch.py`)
Read the script (pure text/regex over `index.html`, no side effects, no network, no DB — safe to
execute per COMMON_RULES) and ran it read-only: **`python3 check_raw_fetch.py` → "OK — no raw
mutating fetch() calls in index.html"** (MEASURED, run 2026-09-27). Currently clean — the 4-times-
recurring bug CLAUDE.md op-rule 6 describes is not present in the current `index.html`.

### `/autotrade` Telegram bypass (cross-reference, verified in §09)
`telegram_commander._cmd_autotrade` (telegram_commander.py:1046) calls `bot.auto_trade()` directly,
with no `cash_auto_trade_enabled` check — unlike the scheduler's own `_task_cash_auto_trade`, which
does gate on it. A user pressing "Run Auto-Trade" in Telegram runs a real/paper trading cycle
regardless of that master toggle. Not re-verified against `bot.auto_trade()`'s own internal gates in
this pass (bot.py trading internals were outside this section's primary file list) — flagged as an
open item, same as §09 left it.

---

## 4. CONTRADICTIONS

| # | Claim | Reality | Evidence |
|---|---|---|---|
| 1 | CLAUDE.md "Current State (As of 2026-07-31)": "Graphify: Knowledge graph tracking 2,035 nodes, 114 communities" | `graphify-out/GRAPH_REPORT.md` (last **committed** version, dated 2026-08-06) already reports **3,795 nodes · 12,506 edges · 162 communities** — and the working tree has this file additionally modified (uncommitted) per git status at session start, so the true current count is even further from CLAUDE.md's figure. | VERIFIED FROM CODE (`graphify-out/GRAPH_REPORT.md:8`), `git log -1` commit date 2026-08-06 |
| 2 | CLAUDE.md "Current State": "67 stocks in database" | `SELECT count(*) FROM stocks` → **67** — matches exactly. | VERIFIED FROM DATABASE 2026-09-27 (not a contradiction — confirms this specific claim still holds) |
| 3 | `scheduler.py:1331` comment: "Check every 5s for TP/SL hits" (`_task_auto_close_trades`) | LIVE `config_settings.scheduler_interval_auto_close_trades=300` overrides it to every 5 minutes (re-confirms §09's finding; independently re-checked this pass in the context of the sequential-price-fetch finding above, which inherits this same 300s cadence). | VERIFIED FROM DATABASE 2026-09-27 (§09 original finding) |
| 4 | `fno_backtester.py` in-code comment implies the cross-caller XGB-save race is "fixed" ("the second caller now waits and takes the first caller's result") | The fix (`_xgb_lock`) only covers `_get_xgb_models()`'s own callers; `scheduler._task_retrain_xgb_daily` duplicates the training+save logic independently and never touches that lock — see Dangerous Areas §3 above. | VERIFIED FROM CODE (fno_backtester.py:572-588 vs scheduler.py:324-450) |
| 5 | `/api/data-health`'s own docstring: "Exists so silent data gaps surface on their own instead of being noticed by chance" | The ML-model check inside it only detects staleness (no file update in 48h), not the retrain task's actual per-run success rate — which has been near-zero for the GBC cash model on most days across a month of MEASURED log lines, invisibly to this same endpoint. | VERIFIED FROM CODE (app.py `_model_stats`) + MEASURED (`app.log` "ML retrain complete: 0 trained, N failed", repeated 2026-08-21→2026-09-25) |
| 6 | CLAUDE.md op-rule 9's own historical account: fallback rate was "50% over" the cap, contradicting a DB row that said "keep under ~3.3/sec" | Both are now reconciled: literal fallback (2.5/sec) and live DB value (2.5/sec) agree, and the DB description text literally says "Keep under ~3.3/sec (200/min) to avoid 429 rate-limit blocks" — consistent with the code. Not a live contradiction; recorded here to confirm the fix described in CLAUDE.md actually landed. | VERIFIED FROM CODE + VERIFIED FROM DATABASE 2026-09-27 |

---

### Cross-cutting facts (for the maps)

- **External services + endpoints**: FYERS quotes (`fyers_client.get_quotes`, chunked ≤50/call, 2s
  TTL cache) — hit once per symbol per call from every sequential live-price loop found above
  (Standard-1 #1-3), not batched despite `get_ltp_batch` existing; RSS/Google News (world_news, MEASURED
  32-937.8s per run); Screener.in/Tijori scraping (rate-limited, out of this section's remeasurement).
- **Config_settings keys read in this scope**: `fyers.rate_per_sec`/`fyers.burst` (both **2.5**/**5**
  LIVE, VERIFIED FROM DATABASE, matches literal fallback — no drift); `scheduler_interval_auto_close_trades`
  (**300**, overrides coded 5s default — re-confirmed); `model.gbc_cash_enabled` (**false** LIVE per §06 —
  mitigates but does not fix the invisible GBC-retrain-failure gap found in Standard 7).
- **DB tables read in this scope**: `stocks` (67 rows, re-confirmed), `trade_journal` (22 rows,
  unbounded `.all()` at trade_journal.py:119, currently harmless at this size), `master_ticker_table`
  (2,467 rows, queried once per symbol per quote fetch via `to_fyers_symbol`, uncached by design).
- **Every timed/triggered execution relevant here**: `record_pnl` (5s, market-open) → `/api/live-prices`
  → N sequential FYERS calls; `auto_close_trades` (300s LIVE) → N sequential FYERS calls; `ml_retrain`
  (daily, ~25min) → near-zero success rate MEASURED for over a month; `xgb_cash_retrain` (daily,
  ~10.3min) → healthy; `retrain_xgb_daily` (F&O, daily, ~31min) → correct atomic save, but shares an
  unguarded file path with the live signal path's own rare retrain-on-miss branch.
  - **Rate limits & quotas**: FYERS 10 req/s, 200/min Standard, 600/min Prime, 100k/day (CLAUDE.md
  op-rule 9) — local limiter's fallback and live config both correctly under this (155/min effective);
  the N-sequential-FYERS-call patterns found here (Standard-1 #1-3) each individually pass through
  `fyers_client._request()`'s token bucket, so they're throttled, not unlimited — but they still cost
  N round-trips (latency, not correctness) where 1 batched call would do, and at large-enough N could
  contend with other scheduler tasks for the same shared token bucket.
- **Cost drivers**: 3 daily ML retrains (compute, not network); world_news collection (32-937.8s per
  15-min cycle, MEASURED); repeated single-symbol FYERS quote calls from 3 separate live-price code
  paths instead of 1 shared batched call.
- **Data flows**: open positions/watchlist symbols → sequential single-symbol FYERS LTP calls (3
  separate call sites, Standard-1) → PnLSnapshot / dashboard price display / TP-SL exit checks.
- **Failure modes**: `is_paper_mode()` fails toward PAPER on exception (safe; fail-closed) but a missing `paper_trading` row defaults to LIVE (`get_config("paper_trading", "false")`, bot.py:1286); FYERS rate limiter cooldown is
  locked and correct; `_task_retrain_xgb_daily` failure mode on save exception logs a clear ERROR
  ("models live in memory only and will be lost on restart") — fails loud, not silent, on that
  specific path; GBC cash retrain's per-symbol failures are swallowed to DEBUG-level logging, making
  root cause undeterminable from the standard INFO log — this is the audit's main "invisible failure"
  finding.
- **Dead/legacy code found this pass**: `_AUTO_TRADE_CONFIG["avoid_expiry_day"]` /
  `["mcx_close_hour"/"mcx_close_min"]` (fno_trader.py, declared, never read, still shown to the user
  as active via `/api/risk-parameters` — re-confirms §07).
- **Contradictions found this pass**: see full table above (6 items); items 1 and 5 are new findings
  from this section, items 2/3/6 are independent re-verifications of prior sections' findings (all
  held up), item 4 is a new nuance on an existing (§07-adjacent) finding.
- **Open unknowns**: exact pool size for the watchlist-scan `ThreadPoolExecutor` in `bot.py`
  (`futures = {pool.submit(...)}` at bot.py:650/1260 — the `pool` object's `max_workers` was not
  traced to its definition in this pass); precise wall-clock timing for the F&O manual backtest
  endpoints and the watchlist scan (no log lines found this pass; would need code instrumentation or
  a live-run trace, out of scope for read-only static+log audit); the DEBUG-level root cause of the
  GBC cash retrain's near-total failure rate (requires either raising the log level or manual
  reproduction — both out of scope for this read-only pass).
## Change Protocol — keeping this document alive

SYSTEM_BRAIN.md is a **living document**. It is only useful while it is accurate. A stale entry is worse than
a missing one, because it will be believed.

### BEFORE changing any code
1. **Read the relevant sections here** — the component entry, its "Used by", its "When", and the
   *Change Impact / Blast Radius* entry.
2. **Identify consumers**: use the *Where Is It Used* index, then confirm with
   `git grep -n "<name>"` and `docs/function_inventory.json` (static analysis misses dynamic dispatch —
   see its header).
3. **Identify timing**: which scheduler task / timer / endpoint / thread runs it, how often, and under which
   gates (*When Does It Run* map).
4. **Identify cost & rate-limit implications**: especially anything that changes FYERS request volume
   (the account is blocked for the day after 3 per-minute breaches — see *Rate Limit & Quota Map*).
5. **Identify security implications**: does it change who can reach what, what is logged, or what is sent
   to a third party?
6. **Check the protected areas** in CLAUDE.md (lock-screen intro, paper/live gate, rate limiter,
   deletion protocol) and the *Dangerous Areas* list.

### AFTER changing code
1. Re-read the changed code (not your memory of it).
2. Update **every** affected section — the component entry, *Who Uses What*, *Where Is It Used*,
   *When Does It Run*, *Data Flow*, *Source of Truth*, *Database* (if schema/writers changed),
   *API Endpoints*, *Config & Env*, *Cost Map*, *Rate Limits*, *Performance*, *Failure & Fallback*,
   *Feature status*, *Change Impact*, and *Current System State* if live state changed.
3. Update labels: a claim you re-checked becomes `VERIFIED FROM CODE (file:line)`; bump
   `LAST VERIFIED` dates on live values you re-queried.
4. Do **not** just append a changelog line. The body must stay correct.
5. If `docs/FUNCTION_INVENTORY.md` is now stale (functions added/removed/moved), tell the user it can be
   regenerated with `.venv/bin/python tools/build_function_inventory.py` (it rewrites files in docs/).

## Documentation Integrity — what the labels mean

| Label | Meaning |
|---|---|
| **VERIFIED FROM CODE** | Read in the source; cited as `file:line`. Line numbers drift — re-grep by name if a line doesn't match. |
| **VERIFIED FROM CONFIG** | Read from `config_settings`, `.env` (variable *names* only), or a config file. |
| **VERIFIED FROM DATABASE** | Read with a read-only `SELECT`; live values carry `LAST VERIFIED: YYYY-MM-DD`. |
| **MEASURED** | A real measurement exists (cited code comment, doc, or log line). |
| **INFERENCE** | Reasoned from verified facts; not directly observed. Treat as a hypothesis. |
| **UNKNOWN — NOT DETERMINABLE FROM CODE** | The repository does not establish it. Do not fill it in by guessing. |
| **EXTERNAL VERIFICATION REQUIRED** | Depends on a third party (pricing, quotas, tiers) not stated in the repo. |

Rules that produced these labels (from CLAUDE.md "Research Rule"):
- A module existing ≠ it running — check config enablement, startup, and callers.
- A docstring or comment is intent, not behaviour.
- A log line is a snapshot, not a status; a file's modified-date is not a status.
- When corrected, re-verify every related claim.

**Secrets:** this document never contains secret values — only variable/key *names*.
If you find a value here that looks like a secret, remove it immediately and tell the user.
## Appendix A — Complete Database Schema (generated from the live database)

**VERIFIED FROM DATABASE** — read-only queries against `information_schema` / `pg_catalog`. LAST VERIFIED: 2026-09-27. Row counts are planner estimates (`pg_class.reltuples`), not exact counts; `-1` means the table has never been analysed. The 32 yearly partitions of `fyers_candles` share its columns and are listed once at the end. Purpose, writers and readers for each table are in the **Database** section; this appendix is the exact column inventory.

| Table | Est. rows | Total size | Columns |
|---|---|---|---|
| `analysis_cache` | 227 | 3336 kB | 5 |
| `auth_sessions` | 19 | 112 kB | 11 |
| `candle_training_metadata` | 43 | 80 kB | 10 |
| `candles` | -1 | 32 kB | 10 |
| `commodity_snapshots` | 7 | 112 kB | 11 |
| `company_connections` | 1559 | 704 kB | 12 |
| `company_external_data` | 31575 | 68 MB | 6 |
| `config_settings` | 220 | 152 kB | 5 |
| `cost_audit_log` | -1 | 48 kB | 10 |
| `cost_notifications` | -1 | 96 kB | 6 |
| `disruption_events` | 22 | 176 kB | 13 |
| `external_slug_map` | 585 | 296 kB | 10 |
| `fyers_candles` | -1 | 0 bytes | 14 |
| `global_news` | 73563 | 59 MB | 13 |
| `idempotency_keys` | -1 | 80 kB | 10 |
| `intraday_candles` | 2850 | 904 kB | 12 |
| `master_ticker_table` | 2467 | 1200 kB | 19 |
| `news_articles` | 43058 | 37 MB | 11 |
| `nse_instruments` | 2464 | 448 kB | 5 |
| `paper_trades` | 8 | 312 kB | 14 |
| `peer_comparisons` | 67 | 264 kB | 4 |
| `pnl_snapshots` | 43511 | 8416 kB | 11 |
| `predictions` | -1 | 24 kB | 6 |
| `refresh_tokens` | -1 | 40 kB | 8 |
| `shareholding_patterns` | 897 | 296 kB | 13 |
| `stock_prices` | 104532 | 80 MB | 9 |
| `stock_theses` | -1 | 24 kB | 10 |
| `stocks` | 67 | 96 kB | 13 |
| `theses` | -1 | 48 kB | 10 |
| `thesis_analysis` | -1 | 16 kB | 12 |
| `trade_journal` | 22 | 320 kB | 26 |
| `trade_log` | -1 | 16 kB | 6 |
| `trade_snapshots` | -1 | 424 kB | 17 |
| `users` | -1 | 64 kB | 12 |
| `watchlist_notes` | -1 | 48 kB | 4 |

### `analysis_cache`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('analysis_cache_id_seq'::regclass) |
| 2 | `cache_key` | character varying(100) | NO | — |
| 3 | `cache_type` | character varying(30) | NO | — |
| 4 | `data_json` | text | NO | — |
| 5 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `analysis_cache_pkey: CREATE UNIQUE INDEX analysis_cache_pkey ON public.analysis_cache USING btree (id)`
- `idx_cache_type: CREATE INDEX idx_cache_type ON public.analysis_cache USING btree (cache_type)`
- `ix_analysis_cache_cache_key: CREATE UNIQUE INDEX ix_analysis_cache_cache_key ON public.analysis_cache USING btree (cache_key)`

### `auth_sessions`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('auth_sessions_id_seq'::regclass) |
| 2 | `sid_hash` | character varying(64) | NO | — |
| 3 | `user_id` | integer | NO | — |
| 4 | `created_at` | timestamp without time zone | NO | — |
| 5 | `last_seen_at` | timestamp without time zone | NO | — |
| 6 | `expires_at` | timestamp without time zone | NO | — |
| 7 | `revoked_at` | timestamp without time zone | YES | — |
| 8 | `sudo_until` | timestamp without time zone | YES | — |
| 9 | `ip` | character varying(64) | YES | — |
| 10 | `user_agent` | character varying(300) | YES | — |
| 11 | `pin_verified_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `auth_sessions_pkey: CREATE UNIQUE INDEX auth_sessions_pkey ON public.auth_sessions USING btree (id)`
- `ix_auth_sessions_sid_hash: CREATE UNIQUE INDEX ix_auth_sessions_sid_hash ON public.auth_sessions USING btree (sid_hash)`
- `ix_auth_sessions_user_id: CREATE INDEX ix_auth_sessions_user_id ON public.auth_sessions USING btree (user_id)`

### `candle_training_metadata`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('candle_training_metadata_id_seq'::regclass) |
| 2 | `event_type` | character varying(50) | NO | — |
| 3 | `timestamp` | timestamp without time zone | NO | — |
| 4 | `total_candles` | integer | YES | — |
| 5 | `instruments_count` | integer | YES | — |
| 6 | `training_samples` | integer | YES | — |
| 7 | `model_version` | character varying(50) | YES | — |
| 8 | `win_rate_long` | double precision | YES | — |
| 9 | `win_rate_short` | double precision | YES | — |
| 10 | `notes` | text | YES | — |

Indexes / constraints:
- `candle_training_metadata_pkey: CREATE UNIQUE INDEX candle_training_metadata_pkey ON public.candle_training_metadata USING btree (id)`
- `ix_candle_training_metadata_timestamp: CREATE INDEX ix_candle_training_metadata_timestamp ON public.candle_training_metadata USING btree ("timestamp")`

### `candles`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('candles_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `timestamp` | timestamp without time zone | NO | — |
| 4 | `open` | double precision | NO | — |
| 5 | `high` | double precision | NO | — |
| 6 | `low` | double precision | NO | — |
| 7 | `close` | double precision | NO | — |
| 8 | `volume` | double precision | NO | — |
| 9 | `created_at` | timestamp without time zone | YES | — |
| 10 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `candles_pkey: CREATE UNIQUE INDEX candles_pkey ON public.candles USING btree (id)`
- `idx_symbol_timestamp: CREATE UNIQUE INDEX idx_symbol_timestamp ON public.candles USING btree (symbol, "timestamp")`
- `ix_candles_symbol: CREATE INDEX ix_candles_symbol ON public.candles USING btree (symbol)`
- `ix_candles_timestamp: CREATE INDEX ix_candles_timestamp ON public.candles USING btree ("timestamp")`

### `commodity_snapshots`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('commodity_snapshots_id_seq'::regclass) |
| 2 | `commodity` | character varying(50) | NO | — |
| 3 | `ticker` | character varying(20) | NO | — |
| 4 | `current_price` | double precision | YES | — |
| 5 | `price_change_1m` | double precision | YES | — |
| 6 | `price_change_3m` | double precision | YES | — |
| 7 | `trend` | character varying(10) | YES | — |
| 8 | `updated_at` | timestamp without time zone | YES | — |
| 9 | `prev_price` | double precision | YES | — |
| 10 | `price_change_since_last` | double precision | YES | — |
| 11 | `prev_trend` | character varying(10) | YES | — |

Indexes / constraints:
- `commodity_snapshots_pkey: CREATE UNIQUE INDEX commodity_snapshots_pkey ON public.commodity_snapshots USING btree (id)`
- `idx_commodity_snap: CREATE UNIQUE INDEX idx_commodity_snap ON public.commodity_snapshots USING btree (commodity)`
- `ix_commodity_snapshots_commodity: CREATE INDEX ix_commodity_snapshots_commodity ON public.commodity_snapshots USING btree (commodity)`

### `company_connections`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('company_connections_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `relation_type` | character varying(20) | NO | — |
| 4 | `related_name` | character varying(200) | NO | — |
| 5 | `related_symbol` | character varying(20) | YES | — |
| 6 | `related_slug` | character varying(200) | YES | — |
| 7 | `source` | character varying(50) | YES | — |
| 8 | `first_seen` | timestamp without time zone | YES | — |
| 9 | `last_seen` | timestamp without time zone | YES | — |
| 10 | `is_active` | boolean | YES | — |
| 11 | `created_at` | timestamp without time zone | YES | — |
| 12 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `company_connections_pkey: CREATE UNIQUE INDEX company_connections_pkey ON public.company_connections USING btree (id)`
- `idx_conn_symbol_type_name: CREATE UNIQUE INDEX idx_conn_symbol_type_name ON public.company_connections USING btree (symbol, relation_type, related_name)`
- `ix_company_connections_related_symbol: CREATE INDEX ix_company_connections_related_symbol ON public.company_connections USING btree (related_symbol)`
- `ix_company_connections_symbol: CREATE INDEX ix_company_connections_symbol ON public.company_connections USING btree (symbol)`

### `company_external_data`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('company_external_data_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `data_type` | character varying(50) | NO | — |
| 4 | `source` | character varying(50) | YES | — |
| 5 | `payload_json` | text | NO | — |
| 6 | `scraped_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `company_external_data_pkey: CREATE UNIQUE INDEX company_external_data_pkey ON public.company_external_data USING btree (id)`
- `idx_ext_symbol_type_time: CREATE INDEX idx_ext_symbol_type_time ON public.company_external_data USING btree (symbol, data_type, scraped_at)`
- `ix_company_external_data_scraped_at: CREATE INDEX ix_company_external_data_scraped_at ON public.company_external_data USING btree (scraped_at)`
- `ix_company_external_data_symbol: CREATE INDEX ix_company_external_data_symbol ON public.company_external_data USING btree (symbol)`
- `uq_ext_symbol_type_day: CREATE UNIQUE INDEX uq_ext_symbol_type_day ON public.company_external_data USING btree (symbol, data_type, ((scraped_at)::date)) WHERE ((data_type)::text <> 'collection_attempt'::text)`

### `config_settings`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('config_settings_id_seq'::regclass) |
| 2 | `key` | character varying(100) | NO | — |
| 3 | `value` | text | NO | — |
| 4 | `description` | character varying(200) | YES | — |
| 5 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `config_settings_pkey: CREATE UNIQUE INDEX config_settings_pkey ON public.config_settings USING btree (id)`
- `ix_config_settings_key: CREATE UNIQUE INDEX ix_config_settings_key ON public.config_settings USING btree (key)`

### `cost_audit_log`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('cost_audit_log_id_seq'::regclass) |
| 2 | `scrape_date` | timestamp without time zone | NO | now() |
| 3 | `cost_type` | character varying(100) | NO | — |
| 4 | `old_value` | double precision | YES | — |
| 5 | `new_value` | double precision | YES | — |
| 6 | `changed` | boolean | YES | false |
| 7 | `percent_change` | double precision | YES | — |
| 8 | `source_url` | character varying(500) | YES | — |
| 9 | `notes` | text | YES | — |
| 10 | `created_at` | timestamp without time zone | YES | now() |

Indexes / constraints:
- `cost_audit_log_pkey: CREATE UNIQUE INDEX cost_audit_log_pkey ON public.cost_audit_log USING btree (id)`
- `cost_audit_unique: CREATE UNIQUE INDEX cost_audit_unique ON public.cost_audit_log USING btree (scrape_date, cost_type)`
- `idx_cost_audit_changed: CREATE INDEX idx_cost_audit_changed ON public.cost_audit_log USING btree (changed)`
- `idx_cost_audit_date: CREATE INDEX idx_cost_audit_date ON public.cost_audit_log USING btree (scrape_date)`
- `idx_cost_audit_type: CREATE INDEX idx_cost_audit_type ON public.cost_audit_log USING btree (cost_type)`

### `cost_notifications`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('cost_notifications_id_seq'::regclass) |
| 2 | `type` | character varying(50) | NO | — |
| 3 | `message` | character varying(1000) | NO | — |
| 4 | `data` | text | YES | — |
| 5 | `is_read` | boolean | YES | false |
| 6 | `created_at` | timestamp without time zone | YES | now() |

Indexes / constraints:
- `cost_notif_unique: CREATE UNIQUE INDEX cost_notif_unique ON public.cost_notifications USING btree (type, created_at)`
- `cost_notifications_pkey: CREATE UNIQUE INDEX cost_notifications_pkey ON public.cost_notifications USING btree (id)`
- `idx_cost_notif_date: CREATE INDEX idx_cost_notif_date ON public.cost_notifications USING btree (created_at DESC)`
- `idx_cost_notif_read: CREATE INDEX idx_cost_notif_read ON public.cost_notifications USING btree (is_read)`
- `idx_cost_notif_type: CREATE INDEX idx_cost_notif_type ON public.cost_notifications USING btree (type)`

### `disruption_events`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('disruption_events_id_seq'::regclass) |
| 2 | `commodity` | character varying(50) | NO | — |
| 3 | `region` | character varying(100) | NO | — |
| 4 | `iso_a3` | character varying(3) | YES | — |
| 5 | `iso_n3` | character varying(3) | YES | — |
| 6 | `severity` | character varying(20) | YES | — |
| 7 | `description` | character varying(500) | YES | — |
| 8 | `news_count` | integer | YES | — |
| 9 | `avg_sentiment` | double precision | YES | — |
| 10 | `sample_headlines` | character varying(2000) | YES | — |
| 11 | `updated_at` | timestamp without time zone | YES | — |
| 12 | `prev_severity` | character varying(20) | YES | — |
| 13 | `prev_description` | character varying(500) | YES | — |

Indexes / constraints:
- `disruption_events_pkey: CREATE UNIQUE INDEX disruption_events_pkey ON public.disruption_events USING btree (id)`
- `idx_disruption: CREATE UNIQUE INDEX idx_disruption ON public.disruption_events USING btree (commodity, region)`
- `ix_disruption_events_commodity: CREATE INDEX ix_disruption_events_commodity ON public.disruption_events USING btree (commodity)`

### `external_slug_map`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('external_slug_map_id_seq'::regclass) |
| 2 | `source` | character varying(50) | NO | — |
| 3 | `company_name` | character varying(200) | NO | — |
| 4 | `symbol` | character varying(20) | YES | — |
| 5 | `slug` | character varying(200) | YES | — |
| 6 | `external_id` | character varying(50) | YES | — |
| 7 | `resolution_status` | character varying(20) | YES | — |
| 8 | `verified_at` | timestamp without time zone | YES | — |
| 9 | `created_at` | timestamp without time zone | YES | — |
| 10 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `external_slug_map_pkey: CREATE UNIQUE INDEX external_slug_map_pkey ON public.external_slug_map USING btree (id)`
- `idx_slugmap_source_name: CREATE UNIQUE INDEX idx_slugmap_source_name ON public.external_slug_map USING btree (source, company_name)`
- `ix_external_slug_map_symbol: CREATE INDEX ix_external_slug_map_symbol ON public.external_slug_map USING btree (symbol)`

### `fyers_candles`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | bigint | NO | nextval('fyers_candles_id_seq'::regclass) |
| 2 | `symbol` | character varying(40) | NO | — |
| 3 | `exchange` | character varying(10) | NO | 'NSE'::character varying |
| 4 | `provider` | character varying(20) | NO | 'FYERS'::character varying |
| 5 | `source_type` | character varying(20) | NO | — |
| 6 | `resolution` | character varying(10) | NO | — |
| 7 | `ts` | timestamp with time zone | NO | — |
| 8 | `open` | double precision | NO | — |
| 9 | `high` | double precision | NO | — |
| 10 | `low` | double precision | NO | — |
| 11 | `close` | double precision | NO | — |
| 12 | `volume` | bigint | YES | — |
| 13 | `open_interest` | bigint | YES | — |
| 14 | `created_at` | timestamp with time zone | NO | now() |

Indexes / constraints:
- `fyers_candles_pkey: CREATE UNIQUE INDEX fyers_candles_pkey ON ONLY public.fyers_candles USING btree (id, ts)`
- `idx_fyers_candles_lookup: CREATE INDEX idx_fyers_candles_lookup ON ONLY public.fyers_candles USING btree (symbol, resolution, ts)`
- `idx_fyers_candles_source: CREATE INDEX idx_fyers_candles_source ON ONLY public.fyers_candles USING btree (provider, source_type)`
- `uq_fyers_candles: CREATE UNIQUE INDEX uq_fyers_candles ON ONLY public.fyers_candles USING btree (symbol, provider, resolution, ts)`

### `global_news`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('global_news_id_seq'::regclass) |
| 2 | `title_hash` | character varying(64) | NO | — |
| 3 | `title` | character varying(500) | NO | — |
| 4 | `source` | character varying(100) | YES | — |
| 5 | `url` | character varying(1000) | YES | — |
| 6 | `published` | character varying(60) | YES | — |
| 7 | `published_at` | timestamp without time zone | YES | — |
| 8 | `category` | character varying(50) | YES | — |
| 9 | `tags` | text | YES | — |
| 10 | `sentiment_score` | double precision | YES | 0 |
| 11 | `sentiment` | character varying(10) | YES | 'NEUTRAL'::character varying |
| 12 | `summary` | character varying(500) | YES | — |
| 13 | `fetched_at` | timestamp without time zone | YES | now() |

Indexes / constraints:
- `global_news_pkey: CREATE UNIQUE INDEX global_news_pkey ON public.global_news USING btree (id)`
- `global_news_title_hash_key: CREATE UNIQUE INDEX global_news_title_hash_key ON public.global_news USING btree (title_hash)`
- `idx_global_news_category: CREATE INDEX idx_global_news_category ON public.global_news USING btree (category)`
- `idx_global_news_published: CREATE INDEX idx_global_news_published ON public.global_news USING btree (published_at)`

### `idempotency_keys`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('idempotency_keys_id_seq'::regclass) |
| 2 | `key` | character varying(255) | NO | — |
| 3 | `scope` | character varying(100) | NO | — |
| 4 | `user_id` | integer | YES | — |
| 5 | `state` | character varying(20) | NO | — |
| 6 | `request_fingerprint` | character varying(64) | YES | — |
| 7 | `response_json` | text | YES | — |
| 8 | `status_code` | integer | YES | — |
| 9 | `created_at` | timestamp without time zone | YES | — |
| 10 | `completed_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `idempotency_keys_pkey: CREATE UNIQUE INDEX idempotency_keys_pkey ON public.idempotency_keys USING btree (id)`
- `idx_idem_created: CREATE INDEX idx_idem_created ON public.idempotency_keys USING btree (created_at)`
- `idx_idem_key_scope: CREATE UNIQUE INDEX idx_idem_key_scope ON public.idempotency_keys USING btree (key, scope)`
- `ix_idempotency_keys_user_id: CREATE INDEX ix_idempotency_keys_user_id ON public.idempotency_keys USING btree (user_id)`

### `intraday_candles`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('intraday_candles_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `trading_date` | character varying(10) | NO | — |
| 4 | `time` | character varying(8) | NO | — |
| 5 | `open` | double precision | NO | — |
| 6 | `high` | double precision | NO | — |
| 7 | `low` | double precision | NO | — |
| 8 | `close` | double precision | NO | — |
| 9 | `volume` | integer | YES | — |
| 10 | `interval` | character varying(10) | YES | — |
| 11 | `created_at` | timestamp without time zone | YES | — |
| 12 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `idx_intraday_symbol_date: CREATE INDEX idx_intraday_symbol_date ON public.intraday_candles USING btree (symbol, trading_date)`
- `idx_intraday_symbol_date_time: CREATE INDEX idx_intraday_symbol_date_time ON public.intraday_candles USING btree (symbol, trading_date, "time")`
- `intraday_candles_pkey: CREATE UNIQUE INDEX intraday_candles_pkey ON public.intraday_candles USING btree (id)`
- `ix_intraday_candles_symbol: CREATE INDEX ix_intraday_candles_symbol ON public.intraday_candles USING btree (symbol)`
- `ix_intraday_candles_trading_date: CREATE INDEX ix_intraday_candles_trading_date ON public.intraday_candles USING btree (trading_date)`

### `master_ticker_table`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `nse_ticker` | character varying(20) | NO | — |
| 2 | `company_name` | character varying(200) | YES | — |
| 3 | `isin` | character varying(20) | YES | — |
| 4 | `exchange` | character varying(10) | YES | — |
| 5 | `segment` | character varying(10) | YES | — |
| 6 | `instrument_type` | character varying(10) | YES | — |
| 7 | `fyers_historical_symbol` | character varying(40) | YES | — |
| 8 | `fyers_websocket_symbol` | character varying(40) | YES | — |
| 9 | `fyers_token` | character varying(30) | YES | — |
| 10 | `fyers_isin` | character varying(20) | YES | — |
| 11 | `fyers_resolution_status` | character varying(20) | YES | — |
| 12 | `fyers_unresolved_reason` | text | YES | — |
| 13 | `tijori_ticker` | character varying(200) | YES | — |
| 14 | `tijori_resolution_status` | character varying(20) | YES | — |
| 15 | `tijori_unresolved_reason` | text | YES | — |
| 16 | `is_active` | boolean | YES | — |
| 17 | `first_seen_at` | timestamp without time zone | YES | — |
| 18 | `last_seen_at` | timestamp without time zone | YES | — |
| 19 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `ix_master_ticker_table_isin: CREATE INDEX ix_master_ticker_table_isin ON public.master_ticker_table USING btree (isin)`
- `master_ticker_table_pkey: CREATE UNIQUE INDEX master_ticker_table_pkey ON public.master_ticker_table USING btree (nse_ticker)`

### `news_articles`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('news_articles_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `title_hash` | character varying(64) | NO | — |
| 4 | `title` | character varying(500) | NO | — |
| 5 | `source` | character varying(100) | YES | — |
| 6 | `url` | character varying(1000) | YES | — |
| 7 | `published` | character varying(60) | YES | — |
| 8 | `published_at` | timestamp without time zone | YES | — |
| 9 | `sentiment_score` | double precision | YES | 0 |
| 10 | `sentiment` | character varying(10) | YES | 'NEUTRAL'::character varying |
| 11 | `fetched_at` | timestamp without time zone | YES | now() |

Indexes / constraints:
- `idx_news_published_at: CREATE INDEX idx_news_published_at ON public.news_articles USING btree (published_at)`
- `idx_news_symbol_hash: CREATE INDEX idx_news_symbol_hash ON public.news_articles USING btree (symbol, title_hash)`
- `idx_news_symbol_hash_uniq: CREATE UNIQUE INDEX idx_news_symbol_hash_uniq ON public.news_articles USING btree (symbol, title_hash)`
- `news_articles_pkey: CREATE UNIQUE INDEX news_articles_pkey ON public.news_articles USING btree (id)`

### `nse_instruments`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `symbol` | character varying(20) | NO | — |
| 2 | `name` | character varying(200) | NO | — |
| 3 | `isin` | character varying(20) | YES | — |
| 4 | `series` | character varying(10) | YES | — |
| 5 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `ix_nse_instruments_name: CREATE INDEX ix_nse_instruments_name ON public.nse_instruments USING btree (name)`
- `nse_instruments_pkey: CREATE UNIQUE INDEX nse_instruments_pkey ON public.nse_instruments USING btree (symbol)`

### `paper_trades`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('paper_trades_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `side` | character varying(4) | NO | — |
| 4 | `quantity` | integer | NO | — |
| 5 | `price` | double precision | NO | — |
| 6 | `segment` | character varying(20) | YES | — |
| 7 | `product` | character varying(10) | YES | — |
| 8 | `order_type` | character varying(20) | YES | — |
| 9 | `status` | character varying(20) | YES | — |
| 10 | `paper_order_id` | character varying(50) | YES | — |
| 11 | `charges` | double precision | YES | — |
| 12 | `remark` | text | YES | — |
| 13 | `created_at` | timestamp without time zone | YES | — |
| 14 | `model_source` | character varying(20) | YES | — |

Indexes / constraints:
- `ix_paper_trades_model_source: CREATE INDEX ix_paper_trades_model_source ON public.paper_trades USING btree (model_source)`
- `ix_paper_trades_symbol: CREATE INDEX ix_paper_trades_symbol ON public.paper_trades USING btree (symbol)`
- `paper_trades_pkey: CREATE UNIQUE INDEX paper_trades_pkey ON public.paper_trades USING btree (id)`

### `peer_comparisons`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('peer_comparisons_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `data_json` | jsonb | NO | — |
| 4 | `collected_at` | timestamp without time zone | YES | now() |

Indexes / constraints:
- `peer_comparisons_pkey: CREATE UNIQUE INDEX peer_comparisons_pkey ON public.peer_comparisons USING btree (id)`
- `peer_comparisons_symbol_key: CREATE UNIQUE INDEX peer_comparisons_symbol_key ON public.peer_comparisons USING btree (symbol)`

### `pnl_snapshots`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('pnl_snapshots_id_seq'::regclass) |
| 2 | `timestamp` | timestamp without time zone | NO | — |
| 3 | `total_pnl` | double precision | NO | — |
| 4 | `total_pnl_pct` | double precision | NO | — |
| 5 | `trades_count` | integer | YES | — |
| 6 | `peak_pnl` | double precision | YES | — |
| 7 | `peak_pnl_pct` | double precision | YES | — |
| 8 | `profit_trades` | integer | YES | — |
| 9 | `loss_trades` | integer | YES | — |
| 10 | `created_at` | timestamp without time zone | YES | — |
| 11 | `user_id` | uuid | YES | — |

Indexes / constraints:
- `idx_pnl_snapshots_user_id: CREATE INDEX idx_pnl_snapshots_user_id ON public.pnl_snapshots USING btree (user_id)`
- `idx_pnl_timestamp: CREATE INDEX idx_pnl_timestamp ON public.pnl_snapshots USING btree ("timestamp")`
- `ix_pnl_snapshots_timestamp: CREATE INDEX ix_pnl_snapshots_timestamp ON public.pnl_snapshots USING btree ("timestamp")`
- `pnl_snapshots_pkey: CREATE UNIQUE INDEX pnl_snapshots_pkey ON public.pnl_snapshots USING btree (id)`

### `predictions`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('predictions_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `signal` | character varying(20) | YES | — |
| 4 | `confidence` | double precision | YES | — |
| 5 | `timestamp` | timestamp without time zone | YES | CURRENT_TIMESTAMP |
| 6 | `data` | jsonb | YES | — |

Indexes / constraints:
- `idx_predictions_symbol: CREATE INDEX idx_predictions_symbol ON public.predictions USING btree (symbol)`
- `predictions_pkey: CREATE UNIQUE INDEX predictions_pkey ON public.predictions USING btree (id)`

### `refresh_tokens`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | uuid | NO | gen_random_uuid() |
| 2 | `user_id` | uuid | NO | — |
| 3 | `token_hash` | character varying(255) | NO | — |
| 4 | `expires_at` | timestamp without time zone | NO | — |
| 5 | `revoked` | boolean | YES | false |
| 6 | `revoked_at` | timestamp without time zone | YES | — |
| 7 | `created_at` | timestamp without time zone | YES | CURRENT_TIMESTAMP |
| 8 | `last_used_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `idx_refresh_tokens_expires: CREATE INDEX idx_refresh_tokens_expires ON public.refresh_tokens USING btree (expires_at)`
- `idx_refresh_tokens_revoked: CREATE INDEX idx_refresh_tokens_revoked ON public.refresh_tokens USING btree (revoked)`
- `idx_refresh_tokens_user_id: CREATE INDEX idx_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id)`
- `refresh_tokens_pkey: CREATE UNIQUE INDEX refresh_tokens_pkey ON public.refresh_tokens USING btree (id)`
- `refresh_tokens_token_hash_key: CREATE UNIQUE INDEX refresh_tokens_token_hash_key ON public.refresh_tokens USING btree (token_hash)`

### `shareholding_patterns`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('shareholding_patterns_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `quarter_date` | date | NO | — |
| 4 | `quarter_label` | character varying(20) | YES | — |
| 5 | `promoters` | double precision | YES | — |
| 6 | `fiis` | double precision | YES | — |
| 7 | `diis` | double precision | YES | — |
| 8 | `government` | double precision | YES | — |
| 9 | `public_pct` | double precision | YES | — |
| 10 | `others` | double precision | YES | — |
| 11 | `num_shareholders` | integer | YES | — |
| 12 | `created_at` | timestamp without time zone | YES | now() |
| 13 | `updated_at` | timestamp without time zone | YES | now() |

Indexes / constraints:
- `idx_shp_symbol: CREATE INDEX idx_shp_symbol ON public.shareholding_patterns USING btree (symbol)`
- `shareholding_patterns_pkey: CREATE UNIQUE INDEX shareholding_patterns_pkey ON public.shareholding_patterns USING btree (id)`
- `shareholding_patterns_symbol_quarter_date_key: CREATE UNIQUE INDEX shareholding_patterns_symbol_quarter_date_key ON public.shareholding_patterns USING btree (symbol, quarter_date)`

### `stock_prices`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('stock_prices_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `date` | date | NO | — |
| 4 | `open` | double precision | YES | — |
| 5 | `high` | double precision | YES | — |
| 6 | `low` | double precision | YES | — |
| 7 | `close` | double precision | YES | — |
| 8 | `volume` | bigint | YES | — |
| 9 | `timestamp` | timestamp without time zone | YES | CURRENT_TIMESTAMP |

Indexes / constraints:
- `idx_stock_prices_date: CREATE INDEX idx_stock_prices_date ON public.stock_prices USING btree (date)`
- `idx_stock_prices_symbol: CREATE INDEX idx_stock_prices_symbol ON public.stock_prices USING btree (symbol)`
- `idx_stock_prices_symbol_date: CREATE INDEX idx_stock_prices_symbol_date ON public.stock_prices USING btree (symbol, date)`
- `stock_prices_pkey: CREATE UNIQUE INDEX stock_prices_pkey ON public.stock_prices USING btree (id)`
- `stock_prices_symbol_date_key: CREATE UNIQUE INDEX stock_prices_symbol_date_key ON public.stock_prices USING btree (symbol, date)`

### `stock_theses`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('stock_theses_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `thesis_text` | text | YES | — |
| 4 | `target_price` | double precision | YES | — |
| 5 | `entry_price` | double precision | YES | — |
| 6 | `quantity` | integer | YES | — |
| 7 | `timeframe` | character varying(50) | YES | — |
| 8 | `comments` | text | YES | — |
| 9 | `created_at` | timestamp without time zone | YES | — |
| 10 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `ix_stock_theses_symbol: CREATE UNIQUE INDEX ix_stock_theses_symbol ON public.stock_theses USING btree (symbol)`
- `stock_theses_pkey: CREATE UNIQUE INDEX stock_theses_pkey ON public.stock_theses USING btree (id)`

### `stocks`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('stocks_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `company_name` | character varying(200) | NO | — |
| 4 | `sector` | character varying(50) | YES | — |
| 5 | `sector_display` | character varying(100) | YES | — |
| 6 | `competitors_json` | text | YES | — |
| 7 | `commodity` | character varying(50) | YES | — |
| 8 | `commodity_ticker` | character varying(20) | YES | — |
| 9 | `commodity_relationship` | character varying(10) | YES | — |
| 10 | `commodity_weight` | double precision | YES | — |
| 11 | `is_active` | boolean | YES | — |
| 12 | `created_at` | timestamp without time zone | YES | — |
| 13 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `ix_stocks_symbol: CREATE UNIQUE INDEX ix_stocks_symbol ON public.stocks USING btree (symbol)`
- `stocks_pkey: CREATE UNIQUE INDEX stocks_pkey ON public.stocks USING btree (id)`

### `theses`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('theses_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `entry_price` | double precision | YES | — |
| 4 | `target_price` | double precision | YES | — |
| 5 | `quantity` | double precision | YES | — |
| 6 | `comments` | text | YES | — |
| 7 | `timestamp` | timestamp without time zone | YES | CURRENT_TIMESTAMP |
| 8 | `created_date` | date | YES | CURRENT_DATE |
| 9 | `current_price` | double precision | YES | — |
| 10 | `last_updated` | timestamp without time zone | YES | CURRENT_TIMESTAMP |

Indexes / constraints:
- `theses_pkey: CREATE UNIQUE INDEX theses_pkey ON public.theses USING btree (id)`
- `theses_symbol_key: CREATE UNIQUE INDEX theses_symbol_key ON public.theses USING btree (symbol)`

### `thesis_analysis`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('thesis_analysis_id_seq'::regclass) |
| 2 | `thesis_id` | integer | YES | — |
| 3 | `symbol` | character varying(20) | YES | — |
| 4 | `entry_date` | date | YES | — |
| 5 | `entry_price` | double precision | YES | — |
| 6 | `target_price` | double precision | YES | — |
| 7 | `current_price` | double precision | YES | — |
| 8 | `days_held` | integer | YES | — |
| 9 | `current_return_pct` | double precision | YES | — |
| 10 | `max_price` | double precision | YES | — |
| 11 | `min_price` | double precision | YES | — |
| 12 | `last_updated` | timestamp without time zone | YES | CURRENT_TIMESTAMP |

Indexes / constraints:
- `idx_thesis_analysis_symbol: CREATE INDEX idx_thesis_analysis_symbol ON public.thesis_analysis USING btree (symbol)`
- `thesis_analysis_pkey: CREATE UNIQUE INDEX thesis_analysis_pkey ON public.thesis_analysis USING btree (id)`

Foreign keys:
- `thesis_analysis_thesis_id_fkey: thesis_id -> theses.id`

### `trade_journal`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('trade_journal_id_seq'::regclass) |
| 2 | `trade_id` | character varying(50) | NO | — |
| 3 | `status` | character varying(10) | NO | — |
| 4 | `symbol` | character varying(20) | NO | — |
| 5 | `side` | character varying(4) | NO | — |
| 6 | `quantity` | integer | NO | — |
| 7 | `trigger` | character varying(20) | YES | — |
| 8 | `entry_time` | timestamp without time zone | NO | — |
| 9 | `entry_price` | double precision | NO | — |
| 10 | `exit_time` | timestamp without time zone | YES | — |
| 11 | `exit_price` | double precision | YES | — |
| 12 | `pre_trade_json` | text | YES | — |
| 13 | `post_trade_json` | text | YES | — |
| 14 | `created_at` | timestamp without time zone | YES | — |
| 15 | `updated_at` | timestamp without time zone | YES | — |
| 16 | `is_paper` | boolean | YES | true |
| 17 | `exit_reason` | character varying(100) | YES | — |
| 18 | `signal` | character varying(20) | YES | — |
| 19 | `confidence` | double precision | YES | — |
| 20 | `stop_loss` | double precision | YES | — |
| 21 | `projected_exit` | double precision | YES | — |
| 22 | `peak_pnl` | double precision | YES | — |
| 23 | `actual_profit_pct` | double precision | YES | — |
| 24 | `breakeven_price` | double precision | YES | — |
| 25 | `user_id` | uuid | YES | — |
| 26 | `model_source` | character varying(20) | YES | — |

Indexes / constraints:
- `idx_journal_symbol_status: CREATE INDEX idx_journal_symbol_status ON public.trade_journal USING btree (symbol, status)`
- `idx_trade_journal_user_id: CREATE INDEX idx_trade_journal_user_id ON public.trade_journal USING btree (user_id)`
- `ix_trade_journal_model_source: CREATE INDEX ix_trade_journal_model_source ON public.trade_journal USING btree (model_source)`
- `ix_trade_journal_symbol: CREATE INDEX ix_trade_journal_symbol ON public.trade_journal USING btree (symbol)`
- `ix_trade_journal_trade_id: CREATE UNIQUE INDEX ix_trade_journal_trade_id ON public.trade_journal USING btree (trade_id)`
- `trade_journal_pkey: CREATE UNIQUE INDEX trade_journal_pkey ON public.trade_journal USING btree (id)`
- `uk_trade_id: CREATE UNIQUE INDEX uk_trade_id ON public.trade_journal USING btree (trade_id)`

### `trade_log`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('trade_log_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | YES | — |
| 3 | `action` | character varying(10) | YES | — |
| 4 | `quantity` | double precision | YES | — |
| 5 | `price` | double precision | YES | — |
| 6 | `timestamp` | timestamp without time zone | YES | CURRENT_TIMESTAMP |

Indexes / constraints:
- `idx_trade_log_symbol: CREATE INDEX idx_trade_log_symbol ON public.trade_log USING btree (symbol)`
- `trade_log_pkey: CREATE UNIQUE INDEX trade_log_pkey ON public.trade_log USING btree (id)`

### `trade_snapshots`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('trade_snapshots_id_seq'::regclass) |
| 2 | `paper_order_id` | character varying(50) | YES | — |
| 3 | `symbol` | character varying(20) | NO | — |
| 4 | `side` | character varying(4) | NO | — |
| 5 | `price` | double precision | NO | — |
| 6 | `quantity` | integer | YES | — |
| 7 | `segment` | character varying(20) | YES | — |
| 8 | `candles_json` | text | YES | — |
| 9 | `indicators_json` | text | YES | — |
| 10 | `news_json` | text | YES | — |
| 11 | `reasoning` | text | YES | — |
| 12 | `signal` | character varying(10) | YES | — |
| 13 | `confidence` | double precision | YES | — |
| 14 | `combined_score` | double precision | YES | — |
| 15 | `sources_json` | text | YES | — |
| 16 | `market_context_json` | text | YES | — |
| 17 | `created_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `idx_snapshot_symbol_created: CREATE INDEX idx_snapshot_symbol_created ON public.trade_snapshots USING btree (symbol, created_at)`
- `ix_trade_snapshots_paper_order_id: CREATE INDEX ix_trade_snapshots_paper_order_id ON public.trade_snapshots USING btree (paper_order_id)`
- `ix_trade_snapshots_symbol: CREATE INDEX ix_trade_snapshots_symbol ON public.trade_snapshots USING btree (symbol)`
- `trade_snapshots_pkey: CREATE UNIQUE INDEX trade_snapshots_pkey ON public.trade_snapshots USING btree (id)`

### `users`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('users_id_seq'::regclass) |
| 2 | `email` | character varying(255) | NO | — |
| 3 | `username` | character varying(100) | YES | — |
| 4 | `password_hash` | character varying(255) | YES | — |
| 5 | `groww_api_key` | character varying(500) | YES | — |
| 6 | `groww_api_secret` | character varying(500) | YES | — |
| 7 | `google_id` | character varying(255) | YES | — |
| 8 | `google_email` | character varying(255) | YES | — |
| 9 | `is_active` | boolean | YES | — |
| 10 | `created_at` | timestamp without time zone | YES | — |
| 11 | `updated_at` | timestamp without time zone | YES | — |
| 12 | `last_login` | timestamp without time zone | YES | — |

Indexes / constraints:
- `ix_users_email: CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email)`
- `users_google_id_key: CREATE UNIQUE INDEX users_google_id_key ON public.users USING btree (google_id)`
- `users_pkey: CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)`

### `watchlist_notes`

| # | Column | Type | Nullable | Default |
|---|---|---|---|---|
| 1 | `id` | integer | NO | nextval('watchlist_notes_id_seq'::regclass) |
| 2 | `symbol` | character varying(20) | NO | — |
| 3 | `note` | text | YES | — |
| 4 | `updated_at` | timestamp without time zone | YES | — |

Indexes / constraints:
- `ix_watchlist_notes_symbol: CREATE UNIQUE INDEX ix_watchlist_notes_symbol ON public.watchlist_notes USING btree (symbol)`
- `watchlist_notes_pkey: CREATE UNIQUE INDEX watchlist_notes_pkey ON public.watchlist_notes USING btree (id)`

### `fyers_candles` partitions

| Partition | Range | Est. rows | Size |
|---|---|---|---|
| `fyers_candles_1997` | FOR VALUES FROM ('1997-01-01 00:00:00+05:30') TO ('1998-01-01 00:00:00+05:30') | 4696 | 1568 kB |
| `fyers_candles_1998` | FOR VALUES FROM ('1998-01-01 00:00:00+05:30') TO ('1999-01-01 00:00:00+05:30') | 10625 | 3424 kB |
| `fyers_candles_1999` | FOR VALUES FROM ('1999-01-01 00:00:00+05:30') TO ('2000-01-01 00:00:00+05:30') | 11329 | 3736 kB |
| `fyers_candles_2000` | FOR VALUES FROM ('2000-01-01 00:00:00+05:30') TO ('2001-01-01 00:00:00+05:30') | 11218 | 3688 kB |
| `fyers_candles_2001` | FOR VALUES FROM ('2001-01-01 00:00:00+05:30') TO ('2002-01-01 00:00:00+05:30') | 11099 | 3736 kB |
| `fyers_candles_2002` | FOR VALUES FROM ('2002-01-01 00:00:00+05:30') TO ('2003-01-01 00:00:00+05:30') | 11681 | 3928 kB |
| `fyers_candles_2003` | FOR VALUES FROM ('2003-01-01 00:00:00+05:30') TO ('2004-01-01 00:00:00+05:30') | 12578 | 4120 kB |
| `fyers_candles_2004` | FOR VALUES FROM ('2004-01-01 00:00:00+05:30') TO ('2005-01-01 00:00:00+05:30') | 13654 | 4224 kB |
| `fyers_candles_2005` | FOR VALUES FROM ('2005-01-01 00:00:00+05:30') TO ('2006-01-01 00:00:00+05:30') | 14080 | 4328 kB |
| `fyers_candles_2006` | FOR VALUES FROM ('2006-01-01 00:00:00+05:30') TO ('2007-01-01 00:00:00+05:30') | 14336 | 4464 kB |
| `fyers_candles_2007` | FOR VALUES FROM ('2007-01-01 00:00:00+05:30') TO ('2008-01-01 00:00:00+05:30') | 14243 | 4512 kB |
| `fyers_candles_2008` | FOR VALUES FROM ('2008-01-01 00:00:00+05:30') TO ('2009-01-01 00:00:00+05:30') | 13678 | 4584 kB |
| `fyers_candles_2009` | FOR VALUES FROM ('2009-01-01 00:00:00+05:30') TO ('2010-01-01 00:00:00+05:30') | 14688 | 4576 kB |
| `fyers_candles_2010` | FOR VALUES FROM ('2010-01-01 00:00:00+05:30') TO ('2011-01-01 00:00:00+05:30') | 15660 | 4864 kB |
| `fyers_candles_2011` | FOR VALUES FROM ('2011-01-01 00:00:00+05:30') TO ('2012-01-01 00:00:00+05:30') | 14820 | 4840 kB |
| `fyers_candles_2012` | FOR VALUES FROM ('2012-01-01 00:00:00+05:30') TO ('2013-01-01 00:00:00+05:30') | 15304 | 4984 kB |
| `fyers_candles_2013` | FOR VALUES FROM ('2013-01-01 00:00:00+05:30') TO ('2014-01-01 00:00:00+05:30') | 15000 | 4984 kB |
| `fyers_candles_2014` | FOR VALUES FROM ('2014-01-01 00:00:00+05:30') TO ('2015-01-01 00:00:00+05:30') | 14640 | 4864 kB |
| `fyers_candles_2015` | FOR VALUES FROM ('2015-01-01 00:00:00+05:30') TO ('2016-01-01 00:00:00+05:30') | 15097 | 4992 kB |
| `fyers_candles_2016` | FOR VALUES FROM ('2016-01-01 00:00:00+05:30') TO ('2017-01-01 00:00:00+05:30') | 16289 | 5072 kB |
| `fyers_candles_2017` | FOR VALUES FROM ('2017-01-01 00:00:00+05:30') TO ('2018-01-01 00:00:00+05:30') | 2924383 | 939 MB |
| `fyers_candles_2018` | FOR VALUES FROM ('2018-01-01 00:00:00+05:30') TO ('2019-01-01 00:00:00+05:30') | 6105918 | 1876 MB |
| `fyers_candles_2019` | FOR VALUES FROM ('2019-01-01 00:00:00+05:30') TO ('2020-01-01 00:00:00+05:30') | 5741211 | 1877 MB |
| `fyers_candles_2020` | FOR VALUES FROM ('2020-01-01 00:00:00+05:30') TO ('2021-01-01 00:00:00+05:30') | 6014089 | 1936 MB |
| `fyers_candles_2021` | FOR VALUES FROM ('2021-01-01 00:00:00+05:30') TO ('2022-01-01 00:00:00+05:30') | 6103560 | 1933 MB |
| `fyers_candles_2022` | FOR VALUES FROM ('2022-01-01 00:00:00+05:30') TO ('2023-01-01 00:00:00+05:30') | 6042526 | 1944 MB |
| `fyers_candles_2023` | FOR VALUES FROM ('2023-01-01 00:00:00+05:30') TO ('2024-01-01 00:00:00+05:30') | 6087259 | 1928 MB |
| `fyers_candles_2024` | FOR VALUES FROM ('2024-01-01 00:00:00+05:30') TO ('2025-01-01 00:00:00+05:30') | 6219928 | 1941 MB |
| `fyers_candles_2025` | FOR VALUES FROM ('2025-01-01 00:00:00+05:30') TO ('2026-01-01 00:00:00+05:30') | 6284428 | 1963 MB |
| `fyers_candles_2026` | FOR VALUES FROM ('2026-01-01 00:00:00+05:30') TO ('2027-01-01 00:00:00+05:30') | 19039264 | 6282 MB |
| `fyers_candles_2027` | FOR VALUES FROM ('2027-01-01 00:00:00+05:30') TO ('2028-01-01 00:00:00+05:30') | -1 | 32 kB |
| `fyers_candles_2028` | FOR VALUES FROM ('2028-01-01 00:00:00+05:30') TO ('2029-01-01 00:00:00+05:30') | -1 | 32 kB |
