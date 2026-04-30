# COMPREHENSIVE CODEBASE AUDIT REPORT
## Groww AI Trading Bot System

---

## EXECUTIVE SUMMARY

**Total Python Files:** 87
**Total Flask Endpoints:** 90+
**Core Production Files:** 24
**Test/Debug Files:** 16
**Orphaned/CLI Tools:** ~30
**Truly Dead Code:** ~17

---

## 1. MAIN ENTRY POINTS & IMPORTS

### Primary Entry Points:
- **app.py** - Flask API server (4200+ lines)
  - Imports 23 core modules directly at startup
  - Serves all REST endpoints
  - Initializes database, scheduler, token refresh
  
- **scheduler.py** - Background task runner
  - Manages all scheduled data collection
  - Starts token refresh, candle collection, auto-trading cycles
  
- **trade_journal.py** - Trade tracking database

### Core Modules Imported by app.py:
1. **bot.py** - Main trading logic (predictions, execution)
2. **fno_trader.py** - Futures & Options trading
3. **db_manager.py** - PostgreSQL database ORM
4. **config.py** - Environment configuration
5. **news_sentiment.py** - News sentiment analysis
6. **stock_thesis.py** - Personal stock theses
7. **auto_analyzer.py** - Automated analysis engine
8. **fundamental_analysis.py** - Financial metrics
9. **stock_search.py** - Stock search/autocomplete
10. **trade_chart_manager.py** - Trade charting
11. **thesis_manager.py** - Investment thesis management
12. **token_refresher.py** - Groww API token refresh
13. **auto_metadata.py** - Stock metadata from Screener.in
14. **deep_analysis.py** - Contextual analysis
15. **research_engine.py** - Unified research algorithm
16. **market_intelligence.py** - Institutional trends
17. **commodity_tracker.py** - Commodity price tracking
18. **supply_chain_collector.py** - Geopolitical disruption tracking
19. **world_news_collector.py** - Global macro news
20. **enhanced_nlp.py** - FinBERT sentiment scoring
21. **fno_backtester.py** - F&O backtest engine
22. **thesis_analyzer.py** - Thesis performance analysis
23. **price_fetcher.py** - Historical price fetching

---

## 2. FILE CATEGORIZATION

### CORE SYSTEM (24 files - Production Critical)
✓ app.py
✓ config.py
✓ scheduler.py
✓ db_manager.py
✓ bot.py
✓ fno_trader.py
✓ trade_journal.py
✓ costs.py
✓ predictor.py
✓ token_refresher.py
✓ auto_analyzer.py
✓ fundamental_analysis.py
✓ stock_search.py
✓ auto_metadata.py
✓ deep_analysis.py
✓ research_engine.py
✓ market_intelligence.py
✓ commodity_tracker.py
✓ supply_chain_collector.py
✓ world_news_collector.py
✓ news_sentiment.py
✓ enhanced_nlp.py
✓ trade_chart_manager.py
✓ thesis_manager.py

**Status:** CRITICAL - Never remove these

### DATA COLLECTION (9 files)
- collect_index_candles.py
- fetch_google_prices.py
- fetch_full_history.py
- price_fetcher.py
- import_nse_stocks.py
- aggregate_to_daily.py
- backfill_candles.py
- world_news_collector.py (also in Core)
- supply_chain_collector.py (also in Core)

**Status:** Optional but useful for data management

### TRADING EXECUTION (5 files)
- paper_trader.py - Paper trading strategy
- live_trade_executor.py - Real-time execution
- real_market_trading.py - Real money trading
- trailing_stop.py - Trailing stop management
- trade_origin_manager.py - Manual vs auto trade segregation

**Status:** CRITICAL for trading

### ANALYSIS TOOLS (8 files)
- backtester.py - Strategy backtesting
- fno_backtester.py - F&O backtest engine
- confidence_analysis.py - Trade confidence metrics
- threshold_analysis.py - Threshold discovery
- simulate_profit.py - Profit simulation
- find_high_confidence_trades.py - Trade finder
- find_quick_trades.py - Quick trade scanner
- peer_analyzer.py - Competitor analysis

**Status:** Optional - for research only

### TELEGRAM INTEGRATION (2 files)
- telegram_alerts.py - Alert sending
- telegram_commander.py - Command handling

**Status:** Optional - can be disabled

### INFRASTRUCTURE (6 files)
- token_refresher.py - Token management
- verify_api.py - API validation
- sanity_check.py - System health check
- db_cli.py - Database CLI
- migrate_schema.py - Database migrations
- migrate_trades_to_db.py - Data migration

**Status:** Utilities - keep but rarely run

### TEST/DEBUG (17 files - CANDIDATES FOR REMOVAL)
⚠️ _check_coverage.py
⚠️ _check_intervals.py
⚠️ _check_today.py
⚠️ _test_bt_api.py
⚠️ test_5min_api.py
⚠️ test_daily_candles.py
⚠️ test_symbol_availability.py
⚠️ test_today_data.py
⚠️ check_db.py
⚠️ check_db_dates.py
⚠️ check_db_status.py
⚠️ check_missing_candles.py
⚠️ check_candles_simple.py
⚠️ check_data_recency.py
⚠️ check_prices.py
⚠️ check_token.py
⚠️ debug_confidence.py

**Status:** SAFE TO REMOVE - these are debugging/validation scripts

### LEGACY/DUPLICATES (2 files)
- market_context.py - Possibly superseded by market_intelligence.py
- portfolio_analyzer.py - May be redundant with bot.py analysis

**Status:** Review before removing

### STANDALONE CLI TOOLS (5 files)
- list_active_symbols.py
- get_token.py
- get_real_prices.py
- refresh_token_cli.py
- run_collector.py

**Status:** Optional - useful utilities

### TRAINING/RETRAINING (2 files)
- retrain_xgb.py
- retrain_all_models.py

**Status:** Optional - for model updates

### ADDITIONAL ANALYSIS (5 files)
- analyze_losses.py
- execute_high_confidence_trades.py
- stock_thesis.py
- thesis_analyzer.py
- fii_tracker.py

**Status:** Analysis tools - optional

---

## 3. FLASK API ENDPOINTS (90 endpoints)

### Core Trading (15 endpoints)
- POST /api/buy - Place buy order
- POST /api/sell - Place sell order
- POST /api/auto-trade - Execute auto-trade cycle
- POST /api/monitor-trailing-stops - Update trailing stops
- POST /api/close-trade - Manual trade closure
- GET /api/holdings - Current holdings
- GET /api/positions - Open positions
- GET /api/orders - Order history
- GET /api/margin - Margin availability
- GET /api/costs/<symbol> - Cost estimation
- POST /api/net-profit - P&L calculation
- GET /api/trade-log - Trading history
- POST /api/auto-close/check - Automated management

### Prediction & Signals (5 endpoints)
- GET /api/predict/<symbol> - ML prediction
- GET /api/scan - Scan watchlist
- POST /api/train/<symbol> - Train model
- GET /api/signals/tomorrow - F&O signals

### Portfolio Management (8 endpoints)
- GET /api/portfolio-analysis - Full portfolio analysis
- POST /api/portfolio-review - Mark reviewed
- GET /api/portfolio-review-status - Review status
- GET /api/check-updates - Portfolio changes
- GET /api/journal - All trades
- GET /api/journal/stats - Trade statistics
- GET /api/journal/open - Open trades
- GET /api/journal/closed - Closed trades

### Watchlist Management (8 endpoints)
- GET /api/watchlist - All watchlist stocks
- POST /api/watchlist/add - Add to watchlist
- POST /api/watchlist/sync-holdings - Sync from Groww
- DELETE /api/watchlist/remove/<symbol> - Remove from watchlist
- GET /api/watchlist/<symbol>/analysis - Investment analysis
- POST /api/watchlist/<symbol>/note - Save notes
- GET /api/live-price/<symbol> - Current price
- GET /api/quote/<symbol> - Stock quote

### News & Sentiment (6 endpoints)
- GET /api/news/<symbol> - News for stock
- GET /api/market-sentiment - Overall sentiment
- GET /api/world-news - Global news
- POST /api/world-news/collect - Collect news
- GET /api/stock/<symbol>/news-detail - Detailed news

### F&O (Futures & Options) (25 endpoints)
- GET /api/fno/dashboard - Full F&O dashboard
- GET /api/fno/instruments - Available instruments
- GET /api/fno/expiries/<instrument> - Expiry dates
- GET /api/fno/option-chain/<instrument>/<expiry> - Option chain
- GET /api/fno/affordable/<instrument>/<expiry> - Affordable options
- GET /api/fno/analyze/<instrument> - F&O direction
- GET /api/fno/best-opportunity - Best opportunity scan
- POST /api/fno/buy - Buy options
- POST /api/fno/sell - Sell options
- GET /api/fno/positions - F&O positions
- GET /api/fno/margin - F&O margins
- GET /api/fno/trades - F&O trade log
- GET /api/fno/capital - Capital status
- POST /api/fno/costs - Cost calculation
- GET /api/fno/rules - Trading rules
- GET /api/fno/technicals/<instrument> - Technical indicators
- GET /api/fno/oi/<instrument> - OI analysis
- GET /api/fno/global-indices - Global indices
- POST /api/fno/auto-trade/run - Run auto-trade
- GET /api/fno/auto-trade/log - Auto-trade log
- GET /api/fno/auto-trade/config - Config management
- POST /api/fno/backtest/run - Run backtest
- GET /api/fno/backtest/dates/<instrument> - Available dates
- POST /api/fno/backtest/multi - Multi-day backtest
- GET /api/fno/backtest/instruments - Instrument list

### Research & Analysis (10 endpoints)
- GET /api/research/<symbol> - Full research report
- POST /api/research/<symbol>/refresh - Refresh report
- GET /api/research/leaderboard - Stock leaderboard
- POST /api/research/all - Run all research
- GET /api/deep-analysis/<symbol> - Deep analysis
- POST /api/deep-analysis/portfolio - Portfolio analysis
- GET /api/deep-analysis/watchlist - Watchlist analysis
- GET /api/intelligence/<symbol> - Market intelligence
- POST /api/intelligence/<symbol>/collect - Collect intelligence
- POST /api/intelligence/collect-all - Collect all

### Metadata & Configuration (4 endpoints)
- POST /api/metadata/refresh - Refresh metadata
- POST /api/metadata/<symbol>/refresh - Refresh single
- GET /api/metadata/status - Metadata status
- POST /api/supply-chain/refresh - Supply chain refresh

### Token & System (5 endpoints)
- POST /api/token/refresh - Refresh Groww token
- GET /api/token/status - Token validity
- POST /api/refresh-token - Alternative refresh
- GET /api/search-stocks - Stock search
- GET /api/search - Stock autocomplete

### Theses (8 endpoints)
- GET /api/thesis/<symbol> - Get stock thesis
- GET /api/thesis - All theses
- POST /api/thesis - Save thesis
- DELETE /api/thesis/<symbol> - Delete thesis
- GET /api/my-thesis - Personal theses
- GET /api/my-thesis/<symbol> - Personal thesis
- POST /api/my-thesis - Create thesis
- DELETE /api/my-thesis/<symbol> - Delete personal thesis
- GET /api/my-thesis/<symbol>/projection - Profit projection

### Paper Trading (5 endpoints)
- GET /api/paper-trading/status - Paper mode status
- POST /api/paper-trading/toggle - Toggle paper mode
- GET /api/paper-trading/closed-trades - Closed trades
- POST /api/update-trailing-stops - Update stops
- POST /api/paper-trading/build-daily-snapshots - Build snapshots

### Prices & Charts (6 endpoints)
- POST /api/prices/fetch - Fetch prices
- GET /api/prices/<symbol> - Get prices
- POST /api/candles/refresh - Refresh candles
- GET /api/thesis/<symbol>/performance - Thesis performance
- GET /api/trade-snapshots - Snapshot list
- GET /api/trade-snapshots/<id> - Snapshot detail

### Additional (8 endpoints)
- GET / - Main HTML
- GET /api/raw-materials - Commodity overview
- GET /api/raw-materials/supply-chain - Supply chain data
- POST /api/cash-auto-trade/toggle - Toggle cash auto-trade
- GET /api/cash-auto-trade/status - Auto-trade status
- POST /api/manual-holdings/register - Register manual holding
- GET /api/manual-holdings/list - List manual holdings
- POST /api/real-trading/enable - Enable real trading
- GET /api/pnl-history - P&L history
- GET /api/pnl-stats - P&L stats

---

## 4. FRONTEND API INTEGRATION

### APIs Called from index.html (6 directly):
- /api/fno/backtest/instruments
- /api/fno/backtest/dates/{instrument}
- /api/fno/backtest/run
- /api/fno/backtest/multi
- /api/live-prices
- /api/update-trailing-stops
- /api/close-trade
- /api/price/{symbol}
- /api/trade-snapshots/candles/{symbol}/{date}
- /api/1min-candles
- /api/5min-candles
- /api/trade-candles

### Endpoints NOT Called from Current Frontend:
The vast majority of endpoints (80+) are NOT called from the current HTML. This suggests:
1. Frontend is minimal/incomplete (only F&O backtester + paper trading)
2. Many endpoints are for future features
3. APIs were built speculatively without corresponding UI

---

## 5. UNUSED FUNCTIONS ANALYSIS

### High-Priority Dead Code:
The following files appear to be debugging/validation scripts with no production use:

**Test Files (Safe to Delete):**
- _check_coverage.py - Candle count validation
- _check_intervals.py - Interval verification
- _check_today.py - Today's data check
- _test_bt_api.py - API test
- check_db.py - Database connection test
- check_db_dates.py - Date range validation
- check_db_status.py - DB status check
- check_missing_candles.py - Missing data detection
- check_candles_simple.py - Candle validation
- check_data_recency.py - Data freshness check
- check_prices.py - Price validation
- check_token.py - Token validity
- debug_confidence.py - Confidence debugging
- test_5min_api.py - API test
- test_daily_candles.py - Candle test
- test_symbol_availability.py - Symbol test
- test_today_data.py - Data test

**Utility/Migration Files (Can Remove After Use):**
- import_nse_stocks.py - One-time stock import
- migrate_schema.py - Schema migration
- migrate_trades_to_db.py - Trade migration
- backfill_candles.py - Historical backfill
- aggregate_to_daily.py - Daily aggregation
- fetch_google_prices.py - Alternative price source
- fetch_full_history.py - Historical fetch
- verify_expanded_universe.py - Universe verification

---

## 6. IMPORT DEPENDENCY ANALYSIS

### Most Critical Dependencies:
1. **db_manager.py** - Used by 8+ files
2. **config.py** - Used by 5+ files
3. **bot.py** - Central trading logic
4. **costs.py** - Cost calculations
5. **news_sentiment.py** - Sentiment analysis

### Circular Dependencies:
- None detected (good!)

### Dead Imports:
- Several test files import from db_manager but don't use results

---

## 7. RECOMMENDATIONS

### PHASE 1: IMMEDIATE CLEANUP (Safe, No Risk)
**Remove these 17 test/debug files:**
```
_check_coverage.py
_check_intervals.py
_check_today.py
_test_bt_api.py
check_db.py
check_db_dates.py
check_db_status.py
check_missing_candles.py
check_candles_simple.py
check_data_recency.py
check_prices.py
check_token.py
debug_confidence.py
test_5min_api.py
test_daily_candles.py
test_symbol_availability.py
test_today_data.py
```
**Impact:** -186 KB, zero production impact

### PHASE 2: ARCHIVE MIGRATIONS (Keep but Archive)
**Move these one-time utilities to /archive:**
```
import_nse_stocks.py
migrate_schema.py
migrate_trades_to_db.py
backfill_candles.py
aggregate_to_daily.py
```
**Impact:** Cleaner main directory, can restore if needed

### PHASE 3: REVIEW DUPLICATES
**Audit these potential duplicates:**
- `market_context.py` vs `market_intelligence.py` - Consolidate?
- `portfolio_analyzer.py` vs `bot.py` analysis - Consolidate?
- Multiple "fetch" functions - Centralize price fetching

### PHASE 4: EXPAND FRONTEND
**Current frontend is minimal - add UI for:**
- Portfolio analysis (/api/portfolio-analysis - not called)
- Deep analysis (/api/deep-analysis - not called)
- Market intelligence (/api/intelligence - not called)
- Thesis management (/api/thesis - not called)
- Fundamental analysis (/api/fundamentals - not called)
- Trade journal (/api/journal - not called)
- Real market trading controls (/api/real-trading - not called)

---

## 8. FILE STATISTICS

| Category | Count | Size | Action |
|----------|-------|------|--------|
| Core Production | 24 | ~500 KB | KEEP |
| Data Collection | 9 | ~80 KB | KEEP |
| Trading | 5 | ~150 KB | KEEP |
| Analysis | 8 | ~120 KB | KEEP |
| Infrastructure | 6 | ~50 KB | KEEP |
| Telegram | 2 | ~80 KB | OPTIONAL |
| CLI Tools | 5 | ~40 KB | OPTIONAL |
| Training | 2 | ~30 KB | OPTIONAL |
| Test/Debug | 17 | ~150 KB | **DELETE** |
| Legacy | 2 | ~50 KB | REVIEW |
| **TOTAL** | **87** | **~1.25 MB** | |

---

## 9. SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│                      index.html                         │
│            (Minimal UI - F&O Backtester Only)           │
└────────────────────────┬────────────────────────────────┘
                         │
                    ↓ 12 API calls ↓
                         │
┌─────────────────────────────────────────────────────────┐
│                      app.py (Flask)                     │
│                 90+ REST Endpoints                      │
└────────────┬──────────────┬──────────────┬──────────────┘
             │              │              │
             ↓              ↓              ↓
      ┌──────────────┐  ┌──────────┐  ┌──────────────┐
      │   bot.py     │  │fno_trader│  │db_manager.py │
      │  (Trading)   │  │(F&O)     │  │  (DB ORM)    │
      └──────────────┘  └──────────┘  └──────────────┘
             │                            │
             ├─→ predictor.py             ├─→ PostgreSQL
             ├─→ costs.py                 └─→ Sessions
             ├─→ trailing_stop.py
             └─→ market_context.py
                     │
      ┌──────────────┼──────────────┐
      ↓              ↓              ↓
  news_sentiment  commodity_   research_
  .py            tracker.py     engine.py
      │              │              │
      ↓              ↓              ↓
  enhanced_nlp   supply_chain   deep_analysis
  .py           .py             .py
```

---

## 10. FINAL SUMMARY

**Your system is well-structured with:**
- ✓ Clear separation of concerns
- ✓ No circular dependencies
- ✓ Comprehensive API surface (90+ endpoints)
- ✓ Strong core module foundation

**Issues to address:**
- ⚠️ Significant dead code (17 test files)
- ⚠️ Frontend severely outdated/incomplete (only 12 of 90 endpoints used)
- ⚠️ Many APIs implemented without corresponding UI
- ⚠️ Possible duplicate functionality (market_context vs market_intelligence)

**Immediate actions:**
1. Delete 17 test files → clean codebase
2. Archive migration scripts → organized workspace
3. Update frontend → fully utilize backend API
4. Consolidate duplicates → reduce maintenance burden
