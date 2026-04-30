# Database Architecture Diagram - Visual Overview

## COMPLETE DATA FLOW MAP

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            TRADING SYSTEM DATABASE                          │
└─────────────────────────────────────────────────────────────────────────────┘

╔═══════════════════════════════════════════════════════════════════════════════╗
║                       1️⃣  PRICE & CANDLE FLOW                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

    EXTERNAL SOURCES
    ════════════════════════════════════════════════════════════════════════════

    Groww API                              Yahoo Finance
         │                                      │
         ├─ Historical daily candles            └─ 3-month commodity prices
         ├─ 5-min intraday candles             (weekly data)
         └─ Latest close prices


    BACKGROUND JOBS (SCHEDULER)
    ════════════════════════════════════════════════════════════════════════════

    _task_collect_5min_candles()    [Every 300 seconds]
         └─→ INSERT intraday_candles (5-min bars)

    _task_sync_historical_candles()  [Every 3600 seconds]
         └─→ INSERT candles (daily OHLCV)

    _task_update_watchlist_prices()  [Every 3600 seconds]
         └─→ UPDATE stock_prices (latest close)


    DATABASE TABLES
    ════════════════════════════════════════════════════════════════════════════

    ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────┐
    │   candles            │    │ intraday_candles     │    │  stock_prices    │
    │                      │    │                      │    │                  │
    │ symbol       (IDX)   │    │ symbol         (IDX) │    │ symbol     (IDX) │
    │ timestamp    (IDX)   │    │ trading_date   (IDX) │    │ price            │
    │ open, high, low      │    │ time           (IDX) │    │ prev_close       │
    │ close, volume        │    │ open, high, low      │    │ change_pct       │
    │ (5K+ rows)           │    │ close, volume        │    │ updated_at       │
    │                      │    │ interval: "1min"     │    │ (100-200 rows)   │
    │ Updated: EOD         │    │ (100K+ rows)         │    │                  │
    │ Size: ~10 MB         │    │ Updated: Every 5min  │    │ Updated: 1 hr    │
    │                      │    │ Size: ~50 MB         │    │ Size: ~1 MB      │
    └──────────────────────┘    └──────────────────────┘    └──────────────────┘
             ▲                           ▲                           ▲
             │                           │                           │
             └───────────────────────────┴───────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
              FRONTEND:                      BOT ANALYSIS:
              index.html                     bot.py
              • Price charts                 • train_model()
              • Watchlist                    • get_technical_indicators()
              • Trade entry prices           • ML decision making


╔═══════════════════════════════════════════════════════════════════════════════╗
║                       2️⃣  TRADE EXECUTION FLOW                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

    USER/BOT ACTION                            SCHEDULER JOBS
    ═════════════════════════════════════     ════════════════════════════════

    POST /api/buy                             _task_cash_auto_trade()
    POST /api/sell                            [Every 300 seconds]
    POST /api/journal/{id}/close              └─ Run trade decision logic
            │                                 └─ Execute new trades
            │
            ├─→ bot.execute_trade()           _task_auto_close_trades()
            │                                 [Every 30 seconds]
            │                                 └─ Check TP/SL hits
            │                                 └─ Auto-exit if needed
            │
            ├─ Capture trade context at T0    _task_record_pnl()
            │ (candles, indicators, news)     [Every 5 seconds]
            │                                 └─ Calculate unrealised P&L
            ▼


    DATABASE WRITES
    ════════════════════════════════════════════════════════════════════════════

    ┌────────────────────────┐  ┌──────────────────┐  ┌─────────────────────┐
    │  trade_journal         │  │  trade_snapshots │  │  trade_log          │
    │  (Master Trades)       │  │  (Trade Context) │  │  (Order Audit)      │
    │                        │  │                  │  │                     │
    │ trade_id (UNIQUE, IDX) │  │ paper_order_id   │  │ symbol              │
    │ status: OPEN/CLOSED    │  │ symbol           │  │ side: BUY/SELL      │
    │ symbol (IDX)           │  │ price, quantity  │  │ quantity            │
    │ side: BUY/SELL         │  │ candles_json     │  │ price               │
    │ quantity               │  │ indicators_json  │  │ order_id            │
    │ is_paper: TRUE/FALSE   │  │ news_json        │  │ order_status        │
    │                        │  │ reasoning        │  │ trade_id (links to) │
    │ entry_time, entry_price│  │ signal, confidence │  │ created_at        │
    │ exit_time, exit_price  │  │ combined_score   │  │ (Audit only)        │
    │ exit_reason            │  │ market_context_json│  │                    │
    │                        │  │ created_at       │  │ (One per order)     │
    │ signal, confidence     │  │ (One per trade)  │  │                     │
    │ pre_trade_json         │  │                  │  │ Size: ~100 rows     │
    │ post_trade_json        │  │ Size: ~56 rows   │  │ Indexed: By symbol  │
    │                        │  │                  │  │ Updated: On order   │
    │ (56 trades - all closed) │  │ Indexed:        │  │                    │
    │ 83.93% win rate        │  │  symbol+created  │  │                     │
    │ Net P&L: ₹35K / 195.6% │  │ Updated: On entry│  │                     │
    │                        │  │ Size: ~2 KB/trade│  │                     │
    │ Size: ~100 KB          │  │                  │  │                     │
    │ Updated: On trade      │  └──────────────────┘  └─────────────────────┘
    │ Indexed: symbol, status│
    └────────────────────────┘


    ┌─────────────────────────────────────────────────────────────────────────┐
    │                        pnl_snapshots                                     │
    │                    (P&L History - Very Large)                           │
    │                                                                         │
    │ timestamp (IDX)      - When snapshot taken                             │
    │ total_pnl, total_pnl_pct - Current unrealised P&L                      │
    │ peak_pnl, peak_pnl_pct   - Best P&L in session                         │
    │ trades_count, profit_trades, loss_trades                               │
    │                                                                         │
    │ (One entry every 5 seconds = 43,200 per trading day)                  │
    │ (100K+ rows = ~200 days of data currently)                            │
    │ Indexed: timestamp (range queries)                                      │
    │ Updated: Every 5 seconds during market hours                           │
    │ Size: ~50-100 MB (GROWS FAST - archive strategy needed)                │
    │                                                                         │
    │ ⚠️ ARCHIVAL NEEDED: Consider moving data > 90 days to cold storage     │
    └─────────────────────────────────────────────────────────────────────────┘


╔═══════════════════════════════════════════════════════════════════════════════╗
║                    3️⃣  INTELLIGENCE & NEWS FLOW                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

    EXTERNAL SOURCES (Always Free)
    ════════════════════════════════════════════════════════════════════════════

    Company-Specific News      Global/Macro News       Sentiment Analysis
    (search.google.com)        (RSS Feeds)             (ML model)
           │                         │                       │
           ├─ Stock news headlines   ├─ RBI announcements    └─ NLP scoring
           ├─ Sentiment scores       ├─ Fed decisions          -1.0 to +1.0
           └─ Article sources        ├─ Sector updates
                                     ├─ FII/DII flows
                                     └─ Market news


    SCHEDULER JOBS
    ════════════════════════════════════════════════════════════════════════════

    _task_news_prefetch()          [Every 600 seconds]
    └─ Fetch company news           (10 min)
    └─ Dedup by title_hash          └─→ news_articles
    └─ Update cache
                                    _task_world_news()        [Every 900 seconds]
                                    └─ Fetch RSS feeds         (15 min)
                                    └─ Parse + score sentiment └─→ global_news
                                    └─ Categorize by topic

    _task_deep_analysis()          [Every 1800 seconds]
    └─ Run analysis for watchlist   (30 min)
    └─ Combine all data sources     └─→ analysis_cache
    └─ Cache result


    DATABASE TABLES
    ════════════════════════════════════════════════════════════════════════════

    ┌──────────────────────┐  ┌──────────────────────┐  ┌─────────────────────┐
    │  news_articles       │  │  global_news         │  │  analysis_cache     │
    │  (Company News)      │  │  (Macro/Sector News) │  │  (Computed Results) │
    │                      │  │                      │  │                     │
    │ symbol (IDX)         │  │ category (IDX)       │  │ cache_key (UNIQUE)  │
    │ title                │  │ title                │  │ cache_type          │
    │ title_hash (DEDUP)   │  │ title_hash (DEDUP)   │  │ data_json           │
    │ source, url          │  │ source, url          │  │ updated_at          │
    │ published_at         │  │ published_at         │  │                     │
    │ sentiment_score      │  │ sentiment_score      │  │ Types:              │
    │ sentiment            │  │ sentiment            │  │ • news              │
    │ fetched_at           │  │ tags (JSON array)    │  │ • fundamentals      │
    │                      │  │ summary              │  │ • auto_analysis     │
    │ (2K-5K per stock)    │  │ fetched_at           │  │ • geopolitical      │
    │ Total: ~50K articles │  │                      │  │                     │
    │                      │  │ (100K+ articles)     │  │ (100-500 entries)   │
    │ Indexed: symbol+hash │  │ Total: ~36K/year     │  │ Indexed: cache_type │
    │ Updated: Every 10min │  │ Indexed: hash        │  │ Updated: On-demand  │
    │ Size: ~50 MB         │  │ Updated: Every 15min │  │ Size: ~5-10 MB      │
    │                      │  │ Size: ~100-200 MB    │  │                     │
    └──────────────────────┘  └──────────────────────┘  └─────────────────────┘
             ▲                           ▲                         ▲
             │                           │                         │
             └───────────────────────────┴───────────────────────┤
                                                                 │
                        ┌─────────────────────────────────────────┘
                        │
                   FRONTEND:
                   • News feed
                   • Auto-analysis tab
                   • Market intelligence
                   • P&L analysis


╔═══════════════════════════════════════════════════════════════════════════════╗
║              4️⃣  SUPPLY CHAIN & COMMODITY FLOW (Heatmap)                      ║
╚═══════════════════════════════════════════════════════════════════════════════╝

    EXTERNAL SOURCE
    ════════════════════════════════════════════════════════════════════════════

    Yahoo Finance                    Google News API
    (Commodity prices)               (Disruption headlines)
           │                                │
           ├─ Crude Oil: CL=F             ├─ "Suez blockage" → -0.7 sentiment
           ├─ Gold: GC=F                  ├─ "Sanctions" → -0.8 sentiment
           ├─ Coal: MTF=F                 └─ "Supply shortage" → -0.5
           ├─ 3-month weekly data
           └─ Calculates trends


    SCHEDULER JOB
    ════════════════════════════════════════════════════════════════════════════

    _task_supply_chain()  [Every 900 seconds]
    │                     (15 minutes)
    ├─→ For each commodity:
    │   ├─ Fetch latest price from yfinance
    │   ├─ Calculate trend (RISING/FALLING/STABLE)
    │   ├─ Store in commodity_snapshots
    │   │
    │   └─ For each disruption watch:
    │       ├─ Scan Google News for keywords
    │       ├─ Score sentiment: -1.0 (negative) to +1.0 (positive)
    │       ├─ Score severity: low|medium|high|critical
    │       │   Formula: news_count (3pts) + sentiment (3pts) + price_impact (3pts)
    │       │   Thresholds: <3=low, 3-4=medium, 5-6=high, ≥7=critical
    │       └─ Store in disruption_events


    DATABASE TABLES
    ════════════════════════════════════════════════════════════════════════════

    ┌────────────────────────┐  ┌──────────────────────────────────────────────┐
    │ commodity_snapshots    │  │  disruption_events                           │
    │ (Current Prices)       │  │  (Active Disruptions by Region)              │
    │                        │  │                                              │
    │ commodity (UNIQUE, IDX)│  │ commodity (PART OF UNIQUE IDX)               │
    │ ticker (yfinance)      │  │ region      (PART OF UNIQUE IDX)             │
    │ current_price          │  │ iso_a3, iso_n3  (Country codes)              │
    │ prev_price             │  │ severity (critical|high|medium|low)          │
    │ price_change_since_last│  │ prev_severity (for change detection)         │
    │ price_change_1m        │  │ description (dynamic from headlines)         │
    │ price_change_3m        │  │ prev_description (for change detection)      │
    │ trend: RISING|FALLING  │  │ news_count (recent articles on this)        │
    │ |STABLE                │  │ avg_sentiment (-1 to +1)                     │
    │ prev_trend             │  │ sample_headlines (JSON array, top 3)        │
    │ updated_at             │  │ updated_at (only if disruption changed)      │
    │                        │  │                                              │
    │ (8 commodities)        │  │ (20-50 disruptions per commodity region)    │
    │ • Crude Oil            │  │ • Suez Canal war                             │
    │ • Gold                 │  │ • Russia sanctions on agriculture            │
    │ • Coal                 │  │ • China drought reducing supply              │
    │ • Iron Ore / Steel     │  │ • Port strikes in Brazil                     │
    │ • Aluminium            │  │                                              │
    │ • Zinc / Base Metals   │  │ Size: ~2 KB per disruption                   │
    │ • USD/INR             │  │ Total: ~50-100 KB                             │
    │                        │  │ Indexed: commodity + region (UNIQUE)         │
    │ Size: <1 KB each       │  │ Updated: Every 900 seconds                   │
    │ Total: <10 KB          │  │ Timestamp: Only when severity changes        │
    │ Indexed: commodity     │  │                                              │
    │ (UNIQUE)               │  │                                              │
    │ Updated: Every 900s    │  │                                              │
    └────────────────────────┘  └──────────────────────────────────────────────┘
             ▲                                       ▲
             └──────────────────────┬────────────────┘
                                    │
                            FRONTEND:
                            /api/supply-chain/heatmap
                            • Commodity prices
                            • Disruption severity colors
                            • World map heatmap
                            • Risk indicators


╔═══════════════════════════════════════════════════════════════════════════════╗
║                   5️⃣  STOCK REGISTRY & USER SETTINGS                          ║
╚═══════════════════════════════════════════════════════════════════════════════╝

    EXTERNAL SOURCE (Weekly)
    ════════════════════════════════════════════════════════════════════════════

    Screener.in API
    └─ Company names, sectors, competitors, commodity links


    SCHEDULER JOB
    ════════════════════════════════════════════════════════════════════════════

    _task_auto_metadata()  [Every 604,800 seconds]
    └─ Once per week
    └─ Refresh from Screener.in
    └─ Update stocks table


    DATABASE TABLES
    ════════════════════════════════════════════════════════════════════════════

    ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
    │  stocks              │  │  stock_theses        │  │  watchlist_notes     │
    │  (Master Directory)  │  │  (User Outlook)      │  │  (User Notes)        │
    │                      │  │                      │  │                      │
    │ symbol (UNIQUE, IDX) │  │ symbol (UNIQUE, IDX) │  │ symbol (UNIQUE, IDX) │
    │ company_name         │  │ thesis_text          │  │ note                 │
    │ sector               │  │ target_price         │  │ updated_at           │
    │ sector_display       │  │ entry_price          │  │                      │
    │ competitors_json     │  │ quantity             │  │ (1 per stock)        │
    │ commodity            │  │ timeframe            │  │ Manual edit only     │
    │ commodity_ticker     │  │ comments             │  │ Size: ~50 entries    │
    │ commodity_rel.       │  │ created_at           │  │                      │
    │ commodity_weight     │  │ updated_at           │  │                      │
    │ is_active            │  │                      │  │                      │
    │ created_at, updated  │  │ (20-50 theses)      │  │                      │
    │                      │  │ Manual edit only     │  │                      │
    │ (100-200 stocks)     │  │ Size: ~1 KB per      │  │                      │
    │ ~50 actively tracked │  │ Total: ~20-50 KB     │  │ Total: ~10-20 KB     │
    │ Size: ~10-20 KB      │  │                      │  │                      │
    │ Updated: Weekly      │  │                      │  │                      │
    │ Source: Screener.in  │  │                      │  │                      │
    └──────────────────────┘  └──────────────────────┘  └──────────────────────┘
             ▲
             │
         USED BY:
         • Dashboard (stock info)
         • Trade decision (commodity links)
         • Analysis (competitor comparison)


═════════════════════════════════════════════════════════════════════════════════

                            OVERALL SYSTEM HEALTH

    ┌─────────────────────────────────────────────────────────────────────────┐
    │  Database Stats                                                         │
    ├─────────────────────────────────────────────────────────────────────────┤
    │  Total Size:              ~500 MB (mostly news + candles + P&L history) │
    │  Largest Tables:          pnl_snapshots (100K rows), global_news (100K) │
    │  Query Performance:       All indexed, <20ms for main queries            │
    │  Backup Strategy:         PostgreSQL daily backups recommended           │
    │  Archive Strategy:        Move pnl_snapshots > 90 days to cold store    │
    │                                                                         │
    │  Concurrent Updates:      None (scheduler prevents self-overlap)         │
    │  Data Consistency:        ✅ All timestamps in UTC                      │
    │  Foreign Key Integrity:   ✅ trade_log → trade_journal verified         │
    │  Deduplication:           ✅ news_articles + global_news via title_hash │
    │                                                                         │
    │  ⚠️ GROWTH WARNING:                                                      │
    │  • pnl_snapshots: +15.7M rows/year                                     │
    │  • global_news: +36.5K rows/year                                        │
    │  • Archive or delete old P&L snapshots quarterly                        │
    └─────────────────────────────────────────────────────────────────────────┘

═════════════════════════════════════════════════════════════════════════════════
```

---

## DATA DEPENDENCY CHART (Which DB Reads Which)

```
                                    ┌──────────────────┐
                                    │   index.html     │
                                    │   (Frontend)     │
                                    └────────┬─────────┘
                                             │
                  ┌──────────────────────────┼──────────────────────────┐
                  │                          │                          │
                  ▼                          ▼                          ▼
        ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
        │  GET /api/       │      │  GET /api/       │      │  GET /api/       │
        │  watchlist       │      │  journal         │      │  supply-chain    │
        │                  │      │  /stats          │      │  /heatmap        │
        └────────┬─────────┘      └────────┬─────────┘      └────────┬─────────┘
                 │                         │                         │
    ┌────────────┴────────┐       ┌────────┴────────┐       ┌────────┴────────┐
    │                     │       │                 │       │                 │
    ▼                     ▼       ▼                 ▼       ▼                 ▼
stocks            stock_prices   trade_journal  pnl_snapshots  commodity_   disruption_
                                                              snapshots    events
                                 trade_log
```

---

**Database Architecture Document Complete** ✅  
**Total Tables: 12+**  
**Total Flows: 4 Major + 5 Supporting**  
**Update Frequency: Every 5 seconds to Weekly**  
