# Graph Report - /tmp/gfocus  (2026-08-01)

## Corpus Check
- Corpus is ~12,710 words - fits in a single context window. You may not need a graph.

## Summary
- 235 nodes · 564 edges · 33 communities detected
- Extraction: 57% EXTRACTED · 43% INFERRED · 0% AMBIGUOUS · INFERRED: 242 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Supply Chain & External Data|Supply Chain & External Data]]
- [[_COMMUNITY_DB Core & Config|DB Core & Config]]
- [[_COMMUNITY_Analysis Cache & Lookups|Analysis Cache & Lookups]]
- [[_COMMUNITY_News & Commodity Models|News & Commodity Models]]
- [[_COMMUNITY_Scheduler Core|Scheduler Core]]
- [[_COMMUNITY_Scheduler Trading Tasks|Scheduler Trading Tasks]]
- [[_COMMUNITY_P&L & ML Retrain Tasks|P&L & ML Retrain Tasks]]
- [[_COMMUNITY_Candle Storage & Intelligence|Candle Storage & Intelligence]]
- [[_COMMUNITY_Candle Queries|Candle Queries]]
- [[_COMMUNITY_Paper Trading & Token Refresh|Paper Trading & Token Refresh]]
- [[_COMMUNITY_Stock Metadata Maps|Stock Metadata Maps]]
- [[_COMMUNITY_Stock Master Table|Stock Master Table]]
- [[_COMMUNITY_Training Event Logs|Training Event Logs]]
- [[_COMMUNITY_Support Group 13|Support Group 13]]
- [[_COMMUNITY_Support Group 14|Support Group 14]]
- [[_COMMUNITY_Support Group 15|Support Group 15]]
- [[_COMMUNITY_Earnings-Aware Refresh|Earnings-Aware Refresh]]
- [[_COMMUNITY_Support Group 17|Support Group 17]]
- [[_COMMUNITY_Support Group 18|Support Group 18]]
- [[_COMMUNITY_Support Group 19|Support Group 19]]
- [[_COMMUNITY_Support Group 20|Support Group 20]]
- [[_COMMUNITY_Support Group 21|Support Group 21]]
- [[_COMMUNITY_Support Group 22|Support Group 22]]
- [[_COMMUNITY_Support Group 23|Support Group 23]]
- [[_COMMUNITY_Support Group 24|Support Group 24]]
- [[_COMMUNITY_Support Group 25|Support Group 25]]
- [[_COMMUNITY_Support Group 26|Support Group 26]]
- [[_COMMUNITY_Support Group 27|Support Group 27]]
- [[_COMMUNITY_Support Group 28|Support Group 28]]
- [[_COMMUNITY_Support Group 29|Support Group 29]]
- [[_COMMUNITY_Support Group 30|Support Group 30]]
- [[_COMMUNITY_Support Group 31|Support Group 31]]
- [[_COMMUNITY_Support Group 32|Support Group 32]]

## God Nodes (most connected - your core abstractions)
1. `CandleDatabase` - 47 edges
2. `Candle` - 40 edges
3. `PnLSnapshot` - 40 edges
4. `PaperTrade` - 38 edges
5. `CompanyConnection` - 28 edges
6. `CompanyExternalData` - 28 edges
7. `ExternalSlugMap` - 27 edges
8. `get_db()` - 27 edges
9. `collect_for_symbol()` - 13 edges
10. `resolve_slug()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `resolve_slug()` --calls--> `ExternalSlugMap`  [INFERRED]
  /tmp/gfocus/tijori_collector.py → /tmp/gfocus/db_manager.py
- `_store_snapshots()` --calls--> `CompanyExternalData`  [INFERRED]
  /tmp/gfocus/tijori_collector.py → /tmp/gfocus/db_manager.py
- `collect_stale_symbols()` --calls--> `get_all_stocks()`  [INFERRED]
  /tmp/gfocus/tijori_collector.py → /tmp/gfocus/db_manager.py
- `_task_tijori_refresh()` --calls--> `collect_stale_symbols()`  [INFERRED]
  /tmp/gfocus/scheduler.py → /tmp/gfocus/tijori_collector.py
- `get_supply_chain_intel()` --calls--> `get_db()`  [INFERRED]
  /tmp/gfocus/tijori_collector.py → /tmp/gfocus/db_manager.py

## Communities

### Community 0 - "Supply Chain & External Data"
Cohesion: 0.1
Nodes (42): CompanyConnection, CompanyExternalData, ExternalSlugMap, Supplier/customer relationships between companies, scraped from external     sou, Snapshots of externally-sourced company data (ratios, peers, forensics,     retu, Verified mapping of company name/symbol → external source page slug.     Avoids, _compute_health(), _diff_forensics() (+34 more)

### Community 1 - "DB Core & Config"
Cohesion: 0.19
Nodes (22): get_config(), get_db(), get_stock(), Get a config value from DB (memoized for _CONFIG_CACHE_TTL seconds)., Set a config value in DB., Create tables if they don't exist., Get or create global database instance., Get a single stock by symbol. (+14 more)

### Community 2 - "Analysis Cache & Lookups"
Cohesion: 0.11
Nodes (18): AnalysisCache, get_cached(), get_competitors(), get_configs(), get_configs_prefix(), get_stock_name(), get_watchlist_note(), invalidate_config_cache() (+10 more)

### Community 3 - "News & Commodity Models"
Cohesion: 0.18
Nodes (11): Base, CommoditySnapshot, ConfigSetting, DisruptionEvent, GlobalNews, NewsArticle, Live disruption events scored from news sentiment., Persisted news article — never re-fetched once stored. (+3 more)

### Community 4 - "Scheduler Core"
Cohesion: 0.2
Nodes (10): Master Scheduler — thread-pool daemon coordinating all background tasks.  Tasks, Send comprehensive daily summary via Telegram (once at ~15:30 IST)., Register a periodic task.  initial_delay = seconds after scheduler     start bef, Pre-fetch news sentiment for watchlist stocks to warm cache., Collect world/macro/sector news from RSS feeds and Google News., _register(), start_scheduler(), _task_news_prefetch() (+2 more)

### Community 5 - "Scheduler Trading Tasks"
Cohesion: 0.18
Nodes (10): Candle, ORM model for OHLCV candle data., Main scheduler loop — dispatches due tasks to thread pool., Run F&O automated trading cycle — entry/exit signals + order execution., Pre-generate deep contextual analysis for watchlist stocks (cached)., Run supply chain commodity data collector., _scheduler_loop(), _task_deep_analysis() (+2 more)

### Community 6 - "P&L & ML Retrain Tasks"
Cohesion: 0.2
Nodes (10): PnLSnapshot, Record unrealised P&L at regular intervals (every 5 seconds during market)., Retrain ML models for all watchlist stocks., Auto-refresh stock metadata: company names, sectors, peers, commodities from Scr, Automatically close trades when they hit target price or stop loss., Record unrealised P&L snapshot every 5 seconds during market hours., _task_auto_close_trades(), _task_auto_metadata() (+2 more)

### Community 7 - "Candle Storage & Intelligence"
Cohesion: 0.22
Nodes (9): CandleDatabase, Database manager for candle storage and retrieval., Insert candles into database.                  Args:             symbol: Stock s, Collect latest 5-minute candles for all trading instruments from Groww API., Collect institutional holdings, peer comparisons for all watchlist stocks., Run the unified research algorithm on all tracked stocks., _task_collect_5min_candles(), _task_market_intelligence() (+1 more)

### Community 8 - "Candle Queries"
Cohesion: 0.11
Nodes (5): Retrieve candles from database using raw SQL for speed.                  Args:, Get the most recent candle timestamp for a symbol.                  Returns:, Identify missing candle dates to determine what needs to be synced from API., Delete candles older than keep_days for a symbol (optional cleanup)., Get database statistics.

### Community 9 - "Paper Trading & Token Refresh"
Cohesion: 0.25
Nodes (9): PaperTrade, Simulated trades for paper trading mode., Register all tasks and start the scheduler daemon thread.     Call this once fro, Check if Groww token is still valid, refresh if expired., Send end-of-day paper trading summary via Telegram., Generate and send paper trade EOD summary with reasoning., _send_paper_eod_summary(), _task_paper_eod_summary() (+1 more)

### Community 10 - "Stock Metadata Maps"
Cohesion: 0.25
Nodes (8): get_all_stocks(), get_commodity_map(), get_sector_map(), get_symbol_names(), Get all active stocks from DB., Build SECTOR_MAP dict from DB: {symbol: sector}., Build COMMODITY_MAP dict from DB for stocks with commodity dependency., Build SYMBOL_NAMES dict from DB: {symbol: company_name}.

### Community 11 - "Stock Master Table"
Cohesion: 0.29
Nodes (4): Populate Stock table with known stocks if empty. Safe to call repeatedly., Master stock table. Replaces all hardcoded dicts:     STOCK_DIRECTORY, SYMBOL_NA, seed_stocks(), Stock

### Community 12 - "Training Event Logs"
Cohesion: 0.29
Nodes (6): CandleTrainingMetadata, log_candle_collection_event(), log_xgb_training_event(), Log completion of hourly candle collection task., Log completion of daily XGBoost retraining., Track data collection and XGBoost model training events.

### Community 13 - "Support Group 13"
Cohesion: 0.5
Nodes (4): Persistent watchlist notes — why a stock is being tracked., Save/update watchlist note., save_watchlist_note(), WatchlistNote

### Community 14 - "Support Group 14"
Cohesion: 0.5
Nodes (3): Unified trade journal — all trades (actual + paper) with full pre/post analysis., Convert ORM object to dictionary matching JSON format., TradeJournalEntry

### Community 15 - "Support Group 15"
Cohesion: 0.5
Nodes (4): Sync ALL historical candles end-of-day (after 3:30 PM IST).     - Skips during m, Aggregate ALL 5-minute candles into daily OHLCV prices for watchlist display., _task_aggregate_candles_to_daily(), _task_sync_historical_candles()

### Community 16 - "Earnings-Aware Refresh"
Cohesion: 0.5
Nodes (4): _detect_new_quarter(), Earnings-aware refresh: when the latest quarterly revenue changes vs     what we, Refresh fundamentals cache for ALL dashboard stocks (hourly).      Each symbol o, _task_cache_refresh()

### Community 17 - "Support Group 17"
Cohesion: 0.67
Nodes (2): Persistent trade log — every order placed., TradeLogEntry

### Community 18 - "Support Group 18"
Cohesion: 0.67
Nodes (2): Complete trade context — candles, indicators, news — for chart replay., TradeSnapshot

### Community 19 - "Support Group 19"
Cohesion: 0.67
Nodes (2): IntradayCandle, Intraday 1-minute or 5-minute candles for daily chart replay.     Used for visua

### Community 20 - "Support Group 20"
Cohesion: 0.67
Nodes (2): Unified thesis table — personal outlook + investment projection., StockThesis

### Community 21 - "Support Group 21"
Cohesion: 1.0
Nodes (1): Initialize database connection.

### Community 22 - "Support Group 22"
Cohesion: 1.0
Nodes (2): Run cash equity auto-trade (paper or real based on DB config)., _task_cash_auto_trade()

### Community 23 - "Support Group 23"
Cohesion: 1.0
Nodes (2): Collect and store geopolitical news for commodities., _task_geopolitical_collect()

### Community 24 - "Support Group 24"
Cohesion: 1.0
Nodes (2): Sync F&O capital from actual Groww account balance., _task_fno_capital_sync()

### Community 25 - "Support Group 25"
Cohesion: 1.0
Nodes (2): Check and update trading cost rates from live sources., _task_cost_rate_update()

### Community 26 - "Support Group 26"
Cohesion: 1.0
Nodes (2): Build comprehensive end-of-day trading snapshots with REAL market data (1-min ca, _task_build_daily_snapshots()

### Community 27 - "Support Group 27"
Cohesion: 1.0
Nodes (2): Run watchlist auto-analysis (predictions for all watchlist stocks)., _task_auto_analysis()

### Community 28 - "Support Group 28"
Cohesion: 1.0
Nodes (2): Retrain XGBoost F&O models with all available candle data (runs daily post-marke, _task_retrain_xgb_daily()

### Community 29 - "Support Group 29"
Cohesion: 1.0
Nodes (2): Run a single task with its own lock (prevents self-overlap)., _run_task_safe()

### Community 30 - "Support Group 30"
Cohesion: 1.0
Nodes (2): Fetch and store latest close prices for all watchlist stocks in database.      R, _task_update_watchlist_prices()

### Community 31 - "Support Group 31"
Cohesion: 1.0
Nodes (2): Fetch global indices data for F&O decision-making., _task_global_indices()

### Community 32 - "Support Group 32"
Cohesion: 1.0
Nodes (2): Refresh Tijori supply-chain & fundamentals data for stale symbols., _task_tijori_refresh()

## Knowledge Gaps
- **50 isolated node(s):** `PostgreSQL database manager — unified ORM for all persistent data. Models: Candl`, `ORM model for OHLCV candle data.`, `Intraday 1-minute or 5-minute candles for daily chart replay.     Used for visua`, `Live commodity price + trend snapshot, updated by background collector.`, `Live disruption events scored from news sentiment.` (+45 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Support Group 21`** (2 nodes): `.__init__()`, `Initialize database connection.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 22`** (2 nodes): `Run cash equity auto-trade (paper or real based on DB config).`, `_task_cash_auto_trade()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 23`** (2 nodes): `Collect and store geopolitical news for commodities.`, `_task_geopolitical_collect()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 24`** (2 nodes): `Sync F&O capital from actual Groww account balance.`, `_task_fno_capital_sync()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 25`** (2 nodes): `Check and update trading cost rates from live sources.`, `_task_cost_rate_update()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 26`** (2 nodes): `Build comprehensive end-of-day trading snapshots with REAL market data (1-min ca`, `_task_build_daily_snapshots()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 27`** (2 nodes): `Run watchlist auto-analysis (predictions for all watchlist stocks).`, `_task_auto_analysis()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 28`** (2 nodes): `Retrain XGBoost F&O models with all available candle data (runs daily post-marke`, `_task_retrain_xgb_daily()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 29`** (2 nodes): `Run a single task with its own lock (prevents self-overlap).`, `_run_task_safe()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 30`** (2 nodes): `Fetch and store latest close prices for all watchlist stocks in database.      R`, `_task_update_watchlist_prices()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 31`** (2 nodes): `Fetch global indices data for F&O decision-making.`, `_task_global_indices()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Support Group 32`** (2 nodes): `Refresh Tijori supply-chain & fundamentals data for stale symbols.`, `_task_tijori_refresh()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CandleDatabase` connect `Candle Storage & Intelligence` to `DB Core & Config`, `Analysis Cache & Lookups`, `Scheduler Core`, `Scheduler Trading Tasks`, `P&L & ML Retrain Tasks`, `Candle Queries`, `Paper Trading & Token Refresh`, `Support Group 15`, `Earnings-Aware Refresh`, `Support Group 21`, `Support Group 22`, `Support Group 23`, `Support Group 24`, `Support Group 25`, `Support Group 26`, `Support Group 27`, `Support Group 28`, `Support Group 29`, `Support Group 30`, `Support Group 31`, `Support Group 32`?**
  _High betweenness centrality (0.216) - this node is a cross-community bridge._
- **Why does `get_db()` connect `DB Core & Config` to `Supply Chain & External Data`, `Analysis Cache & Lookups`, `P&L & ML Retrain Tasks`, `Candle Storage & Intelligence`, `Paper Trading & Token Refresh`, `Stock Metadata Maps`, `Stock Master Table`, `Training Event Logs`, `Support Group 13`, `Support Group 15`, `Earnings-Aware Refresh`?**
  _High betweenness centrality (0.165) - this node is a cross-community bridge._
- **Why does `Candle` connect `Scheduler Trading Tasks` to `Analysis Cache & Lookups`, `News & Commodity Models`, `Scheduler Core`, `P&L & ML Retrain Tasks`, `Candle Storage & Intelligence`, `Paper Trading & Token Refresh`, `Support Group 15`, `Earnings-Aware Refresh`, `Support Group 22`, `Support Group 23`, `Support Group 24`, `Support Group 25`, `Support Group 26`, `Support Group 27`, `Support Group 28`, `Support Group 29`, `Support Group 30`, `Support Group 31`, `Support Group 32`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Are the 36 inferred relationships involving `CandleDatabase` (e.g. with `Master Scheduler — thread-pool daemon coordinating all background tasks.  Tasks` and `Register a periodic task.  initial_delay = seconds after scheduler     start bef`) actually correct?**
  _`CandleDatabase` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `Candle` (e.g. with `Master Scheduler — thread-pool daemon coordinating all background tasks.  Tasks` and `Register a periodic task.  initial_delay = seconds after scheduler     start bef`) actually correct?**
  _`Candle` has 35 INFERRED edges - model-reasoned connections that need verification._
- **Are the 36 inferred relationships involving `PnLSnapshot` (e.g. with `Master Scheduler — thread-pool daemon coordinating all background tasks.  Tasks` and `Register a periodic task.  initial_delay = seconds after scheduler     start bef`) actually correct?**
  _`PnLSnapshot` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `PaperTrade` (e.g. with `Master Scheduler — thread-pool daemon coordinating all background tasks.  Tasks` and `Register a periodic task.  initial_delay = seconds after scheduler     start bef`) actually correct?**
  _`PaperTrade` has 35 INFERRED edges - model-reasoned connections that need verification._