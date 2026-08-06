# 📊 UNIFIED TRADING DATABASE SCHEMA

## Overview
Everything is now stored in PostgreSQL. No more reading from JSON files for trading data.

---

## Primary Table: `trade_journal`
**Purpose:** Single source of truth for ALL trades (paper + actual)

### Columns:
```
id                  INTEGER          PRIMARY KEY
trade_id            VARCHAR(50)      UNIQUE, NOT NULL  (e.g., "INFY-B-20260402125739")
status              VARCHAR(10)      OPEN / CLOSED
symbol              VARCHAR(20)      Stock symbol (INFY, TCS, LT, etc.)
side                VARCHAR(4)       BUY / SELL
quantity            INTEGER          Number of shares
trigger             VARCHAR(20)      auto / manual
is_paper            BOOLEAN          TRUE = paper trade, FALSE = actual trade

-- ENTRY DETAILS
entry_time          DATETIME         When trade was entered
entry_price         FLOAT            Entry price per share

-- EXIT DETAILS  
exit_time           DATETIME         When trade was exited (NULL if OPEN)
exit_price          FLOAT            Exit price per share (NULL if OPEN)
exit_reason         VARCHAR(100)     TARGET_HIT, STOP_LOSS, MANUAL, etc.

-- PAPER TRADING METRICS
signal              VARCHAR(20)      BUY / SELL (from ML model)
confidence          FLOAT            ML confidence 0-1
stop_loss           FLOAT            Stop loss price
projected_exit      FLOAT            Target price
peak_pnl            FLOAT            Best P&L during trade life
actual_profit_pct   FLOAT            Final P&L percentage
breakeven_price     FLOAT            Price to break even

-- ANALYSIS (JSON)
pre_trade_json      TEXT             Full pre-trade analysis & reasoning
post_trade_json     TEXT             Post-trade analysis & results

-- TIMESTAMPS
created_at          DATETIME         When record created
updated_at          DATETIME         When record last updated
```

### Indexes:
- `idx_trade_journal_trade_id` - Fast lookup by trade_id
- `idx_trade_journal_symbol_status` - Filter by symbol and status
- `idx_trade_journal_is_paper` - Filter paper vs actual trades

### Current Data (56 trades):
- Paper trades: 56 (all trades are currently marked as `is_paper=TRUE`)
- Actual trades: 0
- Status: 56 CLOSED, 0 OPEN
- Symbols: INFY (27 trades), TCS (27 trades), LT (2 trades)
- P&L: 47 winners, 0 losers, 83.93% win rate, ₹35,326.85 net profit

---

## Supporting Tables (Already Existing)

### `paper_trades` (Legacy - Kept for compatibility)
- Contains same data but with different structure
- Gradually migrate code to use `trade_journal` exclusively

### `trade_log`
- Records every order placed
- Links to `trade_journal` via `trade_id`

### `trade_snapshots` 
- Historical price data at trade time
- Used for chart replay

### `intraday_candles`
- Stores 1-minute / 5-minute intraday candles for trade replay
- Used by paper-trade closures and chart overlays

### `commodity_snapshots`
- Latest commodity price, trend, and previous-refresh comparison
- Updated by the supply-chain collector

### `disruption_events`
- Live disruption scoring for commodity regions
- Persists news count, sentiment, severity, and headline samples

### `stocks`
- Master stock table with sector, peers, and commodity linkage columns
- Holds the normalized source of truth for metadata refreshes

### `config_settings`
- Persistent config store for scheduler intervals, paper trading, and F&O settings
- Replaces ad-hoc file-based toggles for operational configuration
- Read through `db_manager.get_config()`, which memoizes for 30s; writes via
  `set_config()` invalidate that key immediately. Use `get_configs()` /
  `get_configs_prefix()` to read many keys in one query instead of looping.

---

## Supply-Chain Intelligence Tables (Tijori)

Populated by `tijori_collector.py`. Read through
`tijori_collector.get_supply_chain_intel(symbol)`, which serves the supply-chain
block in watchlist analysis, portfolio analysis, and deep analysis.

### `company_connections`
- Supplier / customer / competitor relationships between companies
- Columns: `symbol`, `relation_type` (supplier|customer|competitor),
  `related_name`, `related_symbol` (NSE symbol once resolved), `first_seen`,
  `last_seen`, `is_active`, `updated_at`
- **Append-and-deactivate**, never deleted — a partner dropping off the source
  page sets `is_active=False`, which surfaces as a "connection removed" signal
- Unique index `idx_conn_symbol_type_name` on (symbol, relation_type, related_name)

### `company_external_data`
- **Append-only** point-in-time snapshots, one row per scrape per data block
- Columns: `symbol`, `data_type`, `source`, `payload_json`, `scraped_at`
- `data_type` is one of: `company_info`, `ratios`, `peers`, `returns`,
  `forensics`, `market_share`, `corporate_actions`
- Append-only by design so ratios/forensics can be diffed across scrapes to
  detect what changed since last quarter
- Index `idx_ext_symbol_type_time` on (symbol, data_type, scraped_at)

### `external_slug_map`
- Caches verified company-name → source-URL-slug resolutions
- Columns: `company_name`, `slug`, `symbol`, `resolution_status`
- Prevents re-guessing slugs on every collection pass

---

## API ENDPOINTS - NOW DATABASE DRIVEN

### Journal Endpoints (Query `trade_journal` directly)
```
GET  /api/journal                          → All 56 trades
GET  /api/journal?type=paper               → Paper trades only
GET  /api/journal?type=actual              → Actual trades only
GET  /api/journal/stats                    → Aggregate statistics
GET  /api/journal/open                     → Open trades only
GET  /api/journal/closed                   → Closed trades only
GET  /api/journal/{trade_id}               → Single trade details
POST /api/journal/{trade_id}/close         → Close a trade
```

### Paper Trading Endpoints (Query `trade_journal` with `is_paper=TRUE`)
```
GET  /api/paper-trading/status             → Paper trades summary
GET  /api/paper-trading/closed-trades      → Closed paper trades
```

---

## Migration Completed

### From JSON Files → PostgreSQL

#### 1. **trade_journal.json** → `trade_journal` table
- 56 trades loaded
- Fields mapped: trade_id, symbol, side, quantity, entry/exit data
- Pre-trade analysis stored as JSON

#### 2. **paper_trades.json** → `trade_journal` table (enrichment)
- Merged with journal data
- Added fields: signal, confidence, stop_loss, projected_exit, peak_pnl, actual_profit_pct

#### 3. **Schema Update**
- Added 9 new columns to `trade_journal` table
- All columns indexed for fast queries
- Maintains historical integrity

---

## Usage Example

### Get All Trades with Paper Trading Metrics
```python
from db_manager import get_db, TradeJournalEntry

db = get_db()
with db.Session() as session:
    trades = session.query(TradeJournalEntry)\
        .filter(TradeJournalEntry.is_paper == True)\
        .order_by(TradeJournalEntry.created_at.desc())\
        .all()
    
    for t in trades:
        print(f"{t.symbol} {t.side} {t.quantity} @ ₹{t.entry_price}")
        if t.status == "CLOSED":
            print(f"  Exit: ₹{t.exit_price} ({t.actual_profit_pct}%)")
```

### Calculate Statistics
```python
from sqlalchemy import func

closed = session.query(TradeJournalEntry)\
    .filter(TradeJournalEntry.status == "CLOSED")\
    .all()

win_rate = len([t for t in closed if t.actual_profit_pct > 0]) / len(closed) * 100
total_pnl = sum(t.actual_profit_pct for t in closed)

print(f"Win Rate: {win_rate}%")
print(f"Total P&L: {total_pnl}%")
```

---

## Database Structure Summary

Live row counts as of 01 Aug 2026 (`pg_stat_user_tables`):

```
PostgreSQL Database
├── stock_prices             107,936   ← largest; daily OHLCV, 5Y per symbol
├── global_news               52,508
├── news_articles             18,348
├── company_connections        1,469   ← suppliers / customers / competitors
├── shareholding_patterns        864
├── company_external_data        728   ← append-only Tijori snapshots
├── analysis_cache               157
├── config_settings              140
├── external_slug_map            138
├── peer_comparisons              66
├── disruption_events             22
├── commodity_snapshots            7
└── trade_journal / candles / predictions / … (currently empty)
```

### Read-size discipline

`stock_prices`, `global_news`, and `news_articles` are large enough that
unbounded reads matter. Endpoints touching them take limits:

| Endpoint | Bound |
|---|---|
| `GET /api/prices/<symbol>` | `?days=N` or `?limit=N` (max 5000); full history by default |
| `GET /api/world-news` | `limit` clamped to 200, `days` clamped to 30 |
| `GET /api/journal` (and the 7 endpoints sharing its loader) | newest `_JOURNAL_MAX_ROWS` (2000) |
| `GET /api/pnl-history` | `minutes` cutoff + `limit` |

---

## Benefits of This Structure

✅ **Single Source of Truth** - All trades in one table  
✅ **No JSON File Dependency** - APIs read directly from DB  
✅ **Rich Metadata** - 20+ fields per trade (entry, exit, metrics, analysis)  
✅ **Fast Queries** - Indexed by trade_id, symbol, status  
✅ **Historical Integrity** - created_at, updated_at tracking  
✅ **Flexible Filtering** - Query by status, symbol, paper/actual, date range  
✅ **Scalable** - Easy to add new trades without JSON file size issues  

---

## Migration Scripts Used

1. `migrate_schema.py` - Added new columns to existing table
2. `migrate_trades_to_db.py` - Loaded 56 trades from JSON files

Both scripts now in codebase for future reference.

---

## Last Updated
**Date:** 01 August 2026
**Status:** ✅ All trades migrated, PostgreSQL ORM in use, APIs database-driven
**Added since 03 Jul:** Tijori supply-chain tables (`company_connections`,
`company_external_data`, `external_slug_map`), a 30s memo cache on
`get_config`, batched snapshot reads, and read limits on the large tables.
**Recent Changes (2026-07-03):**
  - Added commodity snapshot and disruption-event persistence
  - Added intraday candle storage for trade replay
  - Expanded `stocks` metadata to include peer and commodity linkage details
  - Scheduler and paper-trading settings now persist in `config_settings`
  - Paper-trade closures sync back into the trade journal
**Recent Changes (2026-06-22):**
  - Fixed TradeJournalEntry.to_dict() serialization for JSON responses
  - Added proper null-checks for optional fields in responses
  - Fixed trade journal UI undefined property errors
  - Added support for pre_trade and post_trade JSON analysis documents
  - Settings endpoints now persist to config_settings table
**Performance:** <100ms response time for all journal endpoints  
**Data Integrity:** Perfect sync between ORM and database
