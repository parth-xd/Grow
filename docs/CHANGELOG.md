# 📋 CHANGELOG - Groww Trading System

## Version 2.3 (2026-08-01) - Supply-Chain Intelligence, Performance & Accessibility

### ✅ New Features

#### Company Supply-Chain Intelligence (Tijori)
- New `tijori_collector.py` collects suppliers, customers, competitors, ratios,
  price returns, forensic checks, peer tables, and market share per company
- Three new tables: `company_connections`, `company_external_data` (append-only
  snapshots), `external_slug_map` (verified name→slug cache)
- `get_supply_chain_intel()` returns resolved partners with their **own**
  financials (PE/ROE/ROCE/market cap), 6-month returns, and forensic red-flag
  counts, plus a network **health score** and a plain-English **impact narrative**
- Fully config-driven via `tijori.*` keys — refresh interval, request delay,
  timeouts, per-run caps, enable flag. Nothing hardcoded.
- Earnings-aware: `_detect_new_quarter` marks a symbol stale when fresh
  quarterly revenue appears, so new numbers flow in within hours

#### Supply Chain visible in all three analysis surfaces
- **Watchlist → View Analysis** now embeds the full supply-chain block directly
- **Portfolio Analysis** lazy-loads it when a holding is expanded
- **Deep Analysis** renders both the narrative section and the detail block
- Hovering a supplier/customer shows a **performance snapshot tooltip**: full
  return ladder (1d/1m/6m/1y/3y/5y), financials, and forensic pass/flag counts.
  Partners with no inlined data are fetched lazily on first hover.

#### Loading states
- Boot loader covers the dashboard from first paint until the backend answers,
  retrying while `app.py` starts, with a "Continue anyway" escape hatch
- Analysis sections lock behind the orb loader while a genuine backfill runs;
  routine background refreshes never block the UI
- Lock threshold is config-driven (`tijori.block_below_coverage_pct`, default 95)

### ⚡ Performance

- **`get_config` memoized** (30s TTL, write-through invalidation on `set_config`).
  Added `get_configs()` and `get_configs_prefix()` for batched reads. 500 cached
  reads now take ~1ms instead of 500 round-trips.
- **Supply-chain reads batched** via `_load_snapshots_bulk`: `7 + 3P` queries
  → **3** (151 → 3 for a company with 48 resolved partners)
- **Watchlist analysis providers parallelized** — six independent providers now
  fan out across a thread pool instead of running serially
- **News sentiment parallelized** — six sources fetched concurrently instead of
  8 sequential HTTP round-trips (each up to a 10s timeout)
- **`_persist_articles`** preloads existing title hashes in one query instead of
  a SELECT per article
- **Price-action look-backs** collapsed from 5 queries to 1 (`UNION ALL`)

### 🧭 Accessibility & UX

- Nav tabs are now keyboard-operable (`role="tab"`, `tabindex`, Enter/Space) with
  descriptive tooltips and accessible names explaining what each section does
- Icon-only controls labelled (PIN delete, empty keypad cell hidden from AT)
- Optimistic UI: removing a watchlist stock and toggling cash auto-trade update
  immediately and roll back if the server rejects the change

### 📚 Read limits

- `GET /api/prices/<symbol>` accepts `?days=N` / `?limit=N` (max 5000)
- Journal loader bounded to the newest 2000 rows (`_JOURNAL_MAX_ROWS`)

---

## Version 2.2 (2026-07-03) - Data Pipeline & Metadata Refresh

### ✅ New/Updated Features

#### Commodity & Supply Chain Pipeline
- Canonical commodity price fetcher now lives in `commodity_tracker.py`
- NaN/Infinity-safe price validation for all commodity snapshots
- Supply-chain collector now builds disruption watchlists dynamically from commodity metadata
- Live disruption severity is stored in PostgreSQL via `CommoditySnapshot` and `DisruptionEvent`

#### Stock Metadata Refresh
- `auto_metadata.py` now scrapes Screener.in for company names, sectors, and peer lists
- Commodity links are inferred from sector and company description text
- F&O config seeding is centralized through `seed_fno_config()`

#### Trading Persistence & Trailing Stops
- `bot.py` now persists trade logs to PostgreSQL and reloads them on startup
- ML models are cached to `models/*.joblib`
- `paper_trader.py` now tracks cost coverage, trailing stops, and syncs closures to the trade journal

#### API Surface Updates
- Added/updated auth routes: `/api/auth/signup`, `/api/auth/login`, `/api/auth/demo`, `/api/auth/set-api-key`
- Added paper-trading routes: `/api/intraday/enter-paper`, `/api/intraday/close-paper`, `/api/intraday/auto-trade-run-paper`
- Added market/control routes: `/api/monitor-trailing-stops`, `/api/scheduler/settings`, `/api/fno/global-indices`

#### Schema & Documentation
- Database now includes intraday candle storage, commodity snapshots, disruption events, and config settings
- Core architecture docs refreshed to match the current backend surface

---

## Version 2.1 (2026-06-22) - Settings & Journal Fixes

### ✅ New Features

#### Scheduler Settings Management
- **Endpoints Added:**
  - `GET /api/scheduler/settings` - Retrieve all task intervals with descriptions
  - `POST /api/scheduler/settings` - Update task intervals (persisted to config_settings table)
- **Frontend UI:**
  - Settings panel integrated into header menu (⚙️ button)
  - Dynamic form inputs for each scheduler task
  - Form validation (minimum 1 second interval)
  - Toast notifications for success/error feedback
  - Live preview of saved settings
- **Tasks Configurable:**
  - cash_auto_trade (BUY/SELL signal generation)
  - auto_close_trades (trailing stop management)
  - fno_auto_trade (futures/options trading)
  - collect_5min_candles (candle data sync)
  - auto_analysis (portfolio analysis)
  - And 3 more...

#### Intraday Paper Trading
- **Endpoints Added:**
  - `/api/intraday/enter-paper` - Enter intraday paper trade with real price validation
  - `/api/intraday/close-paper` - Close intraday paper trade
  - `/api/intraday/auto-trade-run-paper` - Scan watchlist in paper mode
- **Features:**
  - Real market price validation (rejects if market data unavailable)
  - Capital cap checking before execution
  - Trailing stop system for cost coverage
  - Full trade logging to TradeJournalEntry

### 🐛 Bug Fixes

#### Frontend Fixes (index.html)
1. **Intraday Auto-Log Error (Line 6674)**
   - **Fixed:** Wrong API endpoint path `/api/fno/auto-trade-log` → `/api/fno/auto-trade/log`
   - **Issue:** Endpoint returned HTML error page (404) instead of JSON
   - **Solution:** Corrected path and added error fallback UI
   - **Test:** Auto-log now displays trade history or "No auto-trade log yet" message

2. **Trade Journal Undefined Properties**
   - **Fixed:** Multiple properties accessed without null checks:
     - `post.exit_price` → fallback to `'--'`
     - `post.move_pct` → fallback to `0`
     - `post.move_vs_expected` → fallback to `'N/A'`
     - `post.gross_pnl` → wrapped in conditional check
     - `post.total_charges` → wrapped in conditional check
     - `entry.trade_id` → fallback to empty string
     - `entryTime` → fallback to `'--'`
   - **Impact:** Trade journal now displays without rendering errors
   - **Test:** All trade journal entries load without console errors

#### Backend Fixes (app.py)
1. **TradeJournalEntry Serialization**
   - Fixed `.to_dict()` method to properly handle JSON parsing
   - Added null-checks for optional fields
   - Pre-trade and post-trade JSON documents properly deserialized

### 📊 Signal Generation (5-second intervals)

**Pipeline:**
```
[Scheduler 5s] → [Get Watchlist]
  ↓
[Per Symbol]
  ├─ Fetch live 5-min candle (Groww API)
  ├─ XGBoost prediction (365-day trained model)
  ├─ ML signal + confidence score
  ├─ News sentiment + article count
  ├─ Market context (Nifty, sector, multi-TF)
  └─ Combined signal (ML:30%, News:40%, Market:30%)
  ↓
[Filter by Confidence] (40%+ paper, 65%+ real)
  ↓
[Execute Trade] (if capital available)
  └─ Log to TradeJournalEntry
```

**Status:** ✅ Working - trades generated every 5 seconds during market hours

### 📝 Configuration Changes

**scheduler.py**
- `_task_cash_auto_trade`: Changed from 300s → 5s interval
- `_task_auto_close_trades`: Changed from 300s → 5s interval  
- `_task_fno_auto_trade`: Changed from 300s → 5s interval
- New task: `_task_retrain_xgb_daily` for daily model updates
- New task: `_task_sync_capital_from_groww` for real-time balance

**app.py**
- Added `/api/scheduler/settings` endpoints
- Enhanced error handling for missing market data
- Capital validation before trade execution
- Proper JSON response formatting

**index.html**
- Header menu: Added ⚙️ Settings button
- Settings panel: Full scheduler UI
- Trade journal: Comprehensive null-checks
- Intraday section: Proper API path and fallback UI

### 📈 Database Updates

**Existing Tables:**
- `trade_journal` - TradeJournalEntry ORM model
- `config_settings` - Now used for scheduler settings persistence

**New Settings Added:**
- All 8+ scheduler task intervals now configurable and persistent
- Settings survive app restarts

### 🎯 Testing & Verification

✅ **Tested:**
1. Settings API returns correct JSON with task descriptions
2. Settings save to PostgreSQL and persist across restarts
3. UI properly displays all interval values
4. Form validation prevents invalid values
5. Auto-log displays without JSON parsing errors
6. Trade journal loads without undefined property errors
7. 5-second signal generation confirmed in logs

### 📚 Documentation Updates

- **IMPLEMENTATION_SUMMARY.md** - Added recent changes section
- **ARCHITECTURE.md** - Added comprehensive REST API endpoints documentation
- **DATABASE_SCHEMA.md** - Updated last modified date and recent changes
- **CODEBASE_ANALYSIS.json** - Generated comprehensive file-by-file analysis

### 🚀 Known Issues Fixed

- ✅ Intraday JSON parsing error (SyntaxError)
- ✅ Trade journal rendering errors (undefined properties)
- ✅ Settings not persisting (now using PostgreSQL)
- ✅ No way to change scheduler intervals without code edit

### ⚠️ Remaining Items

- Multi-user filtering validation (some endpoints may need user_id checks)
- Real-time scheduler reloading (currently requires app restart after settings change)
- Settings UI polish (backend complete, frontend mostly done)
- Rate limiting (not yet implemented)
- Demo user endpoint marked for production removal

### 📊 System Status

| Component | Status | Notes |
|-----------|--------|-------|
| Flask Backend | ✅ Working | 100+ REST endpoints |
| Scheduler | ✅ Working | 20+ tasks, 4-worker pool |
| Signal Generation | ✅ Working | 5-second intervals |
| Trade Journal | ✅ Working | PostgreSQL ORM, full analysis |
| Paper Trading | ✅ Working | Trailing stops, real prices |
| Settings Panel | ✅ Working | Menu integrated, API functional |
| Groww API Integration | ✅ Live | Real-time quotes, orders, holdings |

---

## Version 2.0 (2026-04-24) - Database & Journal Rewrite

### Major Changes
- Migrated all trading data from JSON files to PostgreSQL
- Implemented ORM (SQLAlchemy) for all database operations
- Complete trade journal rewrite with pre/post analysis
- Removed in-memory data structures, all persistent to DB
- 56 trades successfully migrated

### Features Added
- Trade journal with full pre-trade & post-trade analysis
- ML accuracy tracking
- Win rate calculations
- P&L tracking and statistics
- Paper trading simulation
- Trailing stop management

---

## Version 1.0 (Initial Release)

### Core Features
- Flask REST API backend
- Real-time trading dashboard
- ML-based signal generation (XGBoost)
- Groww API integration
- Paper trading simulation
- Portfolio analysis
- Market intelligence
- News sentiment analysis
- Multi-timeframe technical analysis
- Backtesting engine
- Telegram alerts

---

## Contributing

When making changes:
1. Update CHANGELOG.md with detailed changes
2. Update relevant .md documentation files
3. Test changes thoroughly
4. Verify database migrations if needed
5. Update version number and date

---

## Support

- Check TROUBLESHOOTING.md for common issues
- Review ARCHITECTURE.md for system design
- See DATABASE_SCHEMA.md for data model details
- Examine CODEBASE_ANALYSIS.json for comprehensive file breakdown
