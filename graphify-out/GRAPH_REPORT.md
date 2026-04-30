# Graph Report - /Users/parthsharma/Desktop/Grow  (2026-04-30)

## Corpus Check
- 82 files · ~192,752 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1858 nodes · 7096 edges · 71 communities detected
- Extraction: 34% EXTRACTED · 66% INFERRED · 0% AMBIGUOUS · INFERRED: 4664 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]

## God Nodes (most connected - your core abstractions)
1. `PaperTradeTracker` - 388 edges
2. `IntradayCandle` - 372 edges
3. `Stock` - 355 edges
4. `TradeSnapshot` - 345 edges
5. `CommoditySnapshot` - 339 edges
6. `PnLSnapshot` - 339 edges
7. `TradeJournalEntry` - 334 edges
8. `DisruptionEvent` - 315 edges
9. `User` - 313 edges
10. `ThesisAnalyzer` - 308 edges

## Surprising Connections (you probably didn't know these)
- `Candle` --uses--> `Display database statistics.`  [INFERRED]
  /Users/parthsharma/Desktop/Grow/db_manager.py → /Users/parthsharma/Desktop/Grow/db_cli.py
- `Candle` --uses--> `Sync a specific symbol from API.`  [INFERRED]
  /Users/parthsharma/Desktop/Grow/db_manager.py → /Users/parthsharma/Desktop/Grow/db_cli.py
- `Candle` --uses--> `Sync all watchlist symbols.`  [INFERRED]
  /Users/parthsharma/Desktop/Grow/db_manager.py → /Users/parthsharma/Desktop/Grow/db_cli.py
- `Candle` --uses--> `Delete old candles for a symbol.`  [INFERRED]
  /Users/parthsharma/Desktop/Grow/db_manager.py → /Users/parthsharma/Desktop/Grow/db_cli.py
- `Candle` --uses--> `Delete ALL candles for a symbol (dangerous!).`  [INFERRED]
  /Users/parthsharma/Desktop/Grow/db_manager.py → /Users/parthsharma/Desktop/Grow/db_cli.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (377): Flask API server — serves the dashboard and exposes REST endpoints for the AI tr, Monitor and update trailing stops on open trades., Monitor and update trailing stops on open trades., Manually trigger a Groww token refresh., Serve the main trading dashboard., Get cost breakdown for a round-trip trade on a symbol., Manually trigger a Groww token refresh., Serve the main trading dashboard. (+369 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (219): add_to_watchlist(), api_close_trade(), api_demo(), api_google_oauth(), api_login(), api_profile(), api_refresh_token(), api_set_api_key() (+211 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (178): api_daily_summary(), api_send_daily_summary(), index(), collect_index_candles(), Collect historical hourly candle data for indices (NIFTY, BANKNIFTY, FINNIFTY) a, Fetch index candles from Groww and store in database., format_telegram_summary(), generate_daily_summary() (+170 more)

### Community 3 - "Community 3"
Cohesion: 0.03
Nodes (124): cost_estimate(), margin(), monitor_trailing_stops(), portfolio_review_status(), predict(), telegram_test(), trade_log(), train() (+116 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (120): fno_auto_trade_config(), fno_auto_trade_log(), fno_capital(), fno_global_indices(), fno_margin(), search_stocks(), search_stocks_api(), auto_analyze_watchlist() (+112 more)

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (122): auto_trade(), get_auto_analysis(), portfolio_review(), research_leaderboard(), toggle_cash_auto_trade(), toggle_paper_trading(), get_latest_analysis(), Get the most recent auto-analysis results. (+114 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (119): _do_watchlist_analysis(), quote(), raw_materials(), research_stock(), research_stock_refresh(), stock_news_detail(), collect_geopolitical_news(), _fallback_result() (+111 more)

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (66): fundamentals(), market_intelligence(), Get fundamental analysis for a stock (financials, competitors, etc.), _analyze_financials(), _fetch_competitor_prices(), _get_competitors(), get_fundamental_analysis(), _get_groww_quote_fundamentals() (+58 more)

### Community 8 - "Community 8"
Cohesion: 0.04
Nodes (58): metadata_status(), discover_peers(), get_fno_cost_rate(), infer_commodity_links(), _invalidate_caches(), auto_metadata.py — Automated stock metadata discovery and refresh.  Replaces ALL, Auto-discover peers from Screener.in industry pages.     Multi-level fallback: I, Scrape a Screener.in /market/... page for company links. (+50 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (47): options_build_strategy(), options_greeks(), options_iv(), options_strategy_list(), analyze_option_chain(), bs_call_price(), bs_put_price(), _build_bear_put() (+39 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (44): check_updates(), deep_analysis_portfolio(), deep_analysis_stock(), deep_analysis_watchlist(), _pa_refresh_background(), portfolio_analysis(), _build_commodity_narrative(), _build_fundamental_narrative() (+36 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (38): backtest_strategies(), compare_strategies_endpoint(), fno_backtest_multi(), run_backtest_endpoint(), _benchmark(), _bollinger(), _cache_result(), compare_strategies() (+30 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (31): world_news(), GlobalNews, World & macro news — RBI, Fed, global events, sector moves, etc., _task_world_news(), _auto_tag(), _classify(), collect_world_news(), _fetch_all_rss() (+23 more)

### Community 13 - "Community 13"
Cohesion: 0.08
Nodes (29): check_trailing_stop_exits(), enable_real_trading(), list_manual_holdings(), calculate_available_capital_for_auto_trading(), can_system_close_trade(), get_manual_holdings(), get_protected_symbols(), get_trade_origin() (+21 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (22): build_features(), compute_atr(), compute_bollinger(), compute_fibonacci_levels(), compute_macd(), compute_rsi(), compute_stochastic(), compute_support_resistance() (+14 more)

### Community 15 - "Community 15"
Cohesion: 0.14
Nodes (18): _task_supply_chain(), _auto_queries(), _build_disruption_watch(), collect_once(), _collector_loop(), _fetch_commodity_price(), _get_disruption_watch(), Supply Chain Data Collector — background job that: 1. Fetches live commodity pri (+10 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (15): nlp_info(), nlp_score(), batch_score(), _enhanced_keyword_score(), finbert_score(), get_model_info(), Enhanced NLP Sentiment — FinBERT transformer model with keyword fallback.  Tries, Enhanced keyword-based sentiment scoring.      Improvements over basic keyword m (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.35
Nodes (14): _as_float(), _as_int(), build_canonical_trade_views(), _build_tracker_post_trade(), _is_potential_tracker_match(), load_tracker_trades(), _merge_non_null(), _normalize_status() (+6 more)

### Community 18 - "Community 18"
Cohesion: 0.24
Nodes (11): fetch_chunked(), _get_db_symbols(), _get_existing_timestamps(), _get_groww(), _insert_candles(), main(), Fetch comprehensive historical candle data from Groww V1 API.  Fetches DAILY can, Fetch candles in chunks respecting API limits. (+3 more)

### Community 19 - "Community 19"
Cohesion: 0.23
Nodes (11): fetch_and_store_all_stocks(), fetch_historical_prices(), get_groww_client(), get_segment(), Price data fetcher — Download 5 years of historical OHLCV data from Groww API an, Fetch and store prices for multiple stocks.          Args:         symbols: List, Get authenticated Groww API client., Get the CASH segment constant from GrowwAPI. (+3 more)

### Community 20 - "Community 20"
Cohesion: 0.39
Nodes (7): extract_imports(), get_all_py_files(), get_local_module_imports(), main(), Get all Python files in workspace., Extract all imports from a Python file., Get imports of local modules (other Python files in this workspace).

### Community 21 - "Community 21"
Cohesion: 0.47
Nodes (5): categorize_file(), extract_flask_endpoints(), main(), Extract all Flask endpoints from app.py., Categorize a file by its purpose.

### Community 22 - "Community 22"
Cohesion: 0.4
Nodes (4): fetch_google_prices(), Fetch historical prices from Google Finance via yfinance.          Args:, Store prices in PostgreSQL., store_prices_in_db()

### Community 23 - "Community 23"
Cohesion: 0.5
Nodes (3): migrate(), Database migration: Create users table for multi-tenant authentication. Run this, Create users table if it doesn't exist.

### Community 24 - "Community 24"
Cohesion: 0.5
Nodes (0): 

### Community 25 - "Community 25"
Cohesion: 0.67
Nodes (1): Load existing trades from file

### Community 26 - "Community 26"
Cohesion: 0.67
Nodes (0): 

### Community 27 - "Community 27"
Cohesion: 0.67
Nodes (0): 

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Get all theses with their current performance.

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Thesis analyzer — Link personal theses with historical price data to show perfor

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): Update current price for a symbol from latest data.

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Convert ORM object to dictionary matching JSON format.

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (0): 

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (0): 

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (1): Total cost as a % of buy value.

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Minimum price move % needed to break even after all costs.

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): How much premium must rise to break even.

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (1): Get all open trades, optionally filtered by symbol

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (1): Get the current live price for a symbol from Groww API

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (1): AUTOMATED LOSS POSITION MANAGEMENT          Handles loss positions intelligently

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): Check if paper trading is enabled in the database config

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Track paper trades with entry, exit targets, and actual results

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Load existing trades from file

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Record a new trade entry with trailing stop setup.                  Args:

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Close a trade with actual exit price.                  Args:             trade_i

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Update trailing stop for an open trade based on current price.         Simple lo

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Get all open trades, optionally filtered by symbol

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Get the current live price for a symbol from Groww API

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Get fundamental analysis for a stock (financials, competitors, etc.)

## Knowledge Gaps
- **302 isolated node(s):** `AI Price Prediction Engine Uses technical indicators + ML to predict price movem`, `Stochastic Oscillator (%K and %D) — SMM Part 4: Oscillators.`, `Detect candlestick patterns from SMM Part 1:     Hammer, Inverted Hammer, Bullis`, `Fibonacci Retracement levels — SMM Part 2.     Returns distance from current pri`, `Dynamic Support & Resistance — SMM Part 2.     Uses rolling pivot-based levels.` (+297 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 28`** (2 nodes): `Get all theses with their current performance.`, `.get_all_theses_with_performance()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (2 nodes): `Thesis analyzer — Link personal theses with historical price data to show perfor`, `thesis_analyzer.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (2 nodes): `Update current price for a symbol from latest data.`, `.update_current_price()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (2 nodes): `Convert ORM object to dictionary matching JSON format.`, `.to_dict()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (2 nodes): `RootLayout()`, `layout.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (2 nodes): `Providers()`, `providers.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (2 nodes): `SmoothScroll()`, `smooth-scroll.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (2 nodes): `LoginPage()`, `page.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (2 nodes): `InstagramLink()`, `instagram-link.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (2 nodes): `utils.ts`, `cn()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `analyze_losses.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `verify_api.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `simulate_profit.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `config.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `threshold_analysis.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `run_collector.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `live_trade_executor.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `close_trades.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `confidence_analysis.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `Total cost as a % of buy value.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `Minimum price move % needed to break even after all costs.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `How much premium must rise to break even.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `get_real_prices.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `list_active_symbols.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `next.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `next-env.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `tailwind.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `route.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `button.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `auth.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `Get all open trades, optionally filtered by symbol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `Get the current live price for a symbol from Groww API`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `AUTOMATED LOSS POSITION MANAGEMENT          Handles loss positions intelligently`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `Check if paper trading is enabled in the database config`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `Track paper trades with entry, exit targets, and actual results`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Load existing trades from file`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Record a new trade entry with trailing stop setup.                  Args:`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Close a trade with actual exit price.                  Args:             trade_i`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Update trailing stop for an open trade based on current price.         Simple lo`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Get all open trades, optionally filtered by symbol`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Get the current live price for a symbol from Groww API`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Get fundamental analysis for a stock (financials, competitors, etc.)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PaperTradeTracker` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 5`, `Community 25`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Why does `IntradayCandle` connect `Community 0` to `Community 8`, `Community 1`, `Community 2`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Why does `Stock` connect `Community 0` to `Community 4`, `Community 5`, `Community 6`, `Community 8`, `Community 10`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 378 inferred relationships involving `PaperTradeTracker` (e.g. with `Telegram Commander — interactive bot that listens for commands via polling.  Giv` and `Check if scheduler is paused via Telegram command.`) actually correct?**
  _`PaperTradeTracker` has 378 INFERRED edges - model-reasoned connections that need verification._
- **Are the 368 inferred relationships involving `IntradayCandle` (e.g. with `Swing Backtester v4 — Multi-Day Position Holding (up to 7 days) ================` and `Build instrument dictionary from database stocks + static definitions.`) actually correct?**
  _`IntradayCandle` has 368 INFERRED edges - model-reasoned connections that need verification._
- **Are the 348 inferred relationships involving `Stock` (e.g. with `Unified Research Engine — One algorithm, every stock.  A single, consistent, mul` and `Load OHLCV from DB candles table.  Returns DataFrame or empty.`) actually correct?**
  _`Stock` has 348 INFERRED edges - model-reasoned connections that need verification._
- **Are the 341 inferred relationships involving `TradeSnapshot` (e.g. with `Trading Bot — Connects AI predictions to Groww API order execution. Fetches hist` and `Try to load a persisted ML model from disk.`) actually correct?**
  _`TradeSnapshot` has 341 INFERRED edges - model-reasoned connections that need verification._