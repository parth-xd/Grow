"""
Master Scheduler — thread-pool daemon coordinating all background tasks.

Tasks run concurrently via a thread pool (max 4 workers) so slow tasks
(deep analysis, research) never block fast critical ones (candle collection,
auto-trade).  Each task has its own lock to prevent self-overlap.
"""

import logging
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)

# ── Task definitions ─────────────────────────────────────────────────────────

_tasks = []
_task_locks = {}          # per-task locks to prevent self-overlap
_pool = None              # thread pool (created on first start)
MAX_WORKERS = 4           # concurrent task limit


def _register(name, fn, interval_seconds, initial_delay=0):
    """Register a periodic task.  initial_delay = seconds after scheduler
    start before the first run (used to stagger startup bursts)."""
    _tasks.append({
        "name": name,
        "fn": fn,
        "interval": interval_seconds,
        "initial_delay": initial_delay,
        "last_run": 0,
        "_started": False,   # tracks whether initial_delay has elapsed
    })
    _task_locks[name] = threading.Lock()


def _task_auto_analysis():
    """Run watchlist auto-analysis (predictions for all watchlist stocks)."""
    import auto_analyzer
    auto_analyzer.auto_analyze_watchlist()


def _task_news_prefetch():
    """Pre-fetch news sentiment for watchlist stocks to warm cache."""
    from config import WATCHLIST
    import news_sentiment
    for symbol in WATCHLIST:
        try:
            news_sentiment.get_news_sentiment(symbol)
        except Exception as e:
            logger.debug("News prefetch failed for %s: %s", symbol, e)


def _task_supply_chain():
    """Run supply chain commodity data collector."""
    try:
        from supply_chain_collector import collect_once
        collect_once()
    except Exception as e:
        logger.warning("Supply chain collection failed: %s", e)


def _task_cache_refresh():
    """Refresh analysis caches (fundamentals, etc.)."""
    from config import WATCHLIST
    import fundamental_analysis as fa
    for symbol in WATCHLIST:
        try:
            fa.get_fundamental_analysis(None, symbol)
        except Exception as e:
            logger.debug("Cache refresh failed for %s: %s", symbol, e)


def _task_update_watchlist_prices():
    """Fetch and store latest close prices for all watchlist stocks in database."""
    try:
        from config import WATCHLIST
        from datetime import datetime
        import psycopg2
        from dotenv import load_dotenv
        import os
        
        load_dotenv()
        db_url = os.getenv("DB_URL")
        if not db_url:
            logger.debug("Database not configured for watchlist price updates")
            return
        
        # Get live prices from bot
        try:
            import bot
            conn = psycopg2.connect(db_url, connect_timeout=3)
            cursor = conn.cursor()
            
            today = datetime.now().date()
            updated_count = 0
            failed_count = 0
            
            for symbol in WATCHLIST:
                try:
                    # Fetch latest live price from Groww API
                    ltp = bot.fetch_live_price(symbol)
                    if ltp and ltp > 0:
                        # Insert latest price into stock_prices table
                        # Using UPSERT to avoid duplicates if already recorded today
                        cursor.execute("""
                            INSERT INTO stock_prices (symbol, date, close)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (symbol, date) DO UPDATE
                            SET close = EXCLUDED.close
                        """, (symbol, today, ltp))
                        updated_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.debug("Failed to update price for %s: %s", symbol, e)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            if updated_count > 0:
                logger.info("✓ Updated watchlist prices: %d stocks (failed: %d)", updated_count, failed_count)
        except ImportError:
            logger.debug("Bot module not available for price updates")
    except Exception as e:
        logger.warning("Watchlist price update failed: %s", e)


def _task_collect_5min_candles():
    """Collect latest 5-minute candles for all trading instruments from Groww API.
    
    NOTE: Groww only provides 5-min intraday data for ~13 liquid symbols:
    TCS, INFY, RELIANCE, SBIN, WIPRO, HDFCBANK, ICICIBANK, ITC, LT, BHARTIARTL, ASIANPAINT, SUZLON, GEMAROMA
    
    Other symbols only have daily candles (collected separately).
    """
    from db_manager import CandleDatabase, Candle, log_candle_collection_event
    from datetime import datetime, timedelta
    from sqlalchemy import text
    import time

    db = CandleDatabase()

    try:
        from fno_trader import _get_groww
    except Exception as e:
        logger.warning("Failed to import Groww API: %s", e)
        return

    now = datetime.now()
    
    # For TODAY's data: start from market open (9:15 AM) or last 2 hours, whichever includes more
    # This ensures we collect all intraday candles from today's market session
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    two_hours_ago = now - timedelta(hours=2)
    
    # Use whichever is more recent (market open or last 2 hours)
    start_time = max(market_open, two_hours_ago) if now.hour >= 9 else two_hours_ago
    start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_time = now.strftime("%Y-%m-%d %H:%M:%S")

    collected_count = 0
    failed_count = 0

    # Symbols that Groww actively provides 5-min intraday data for
    # (These are the only ones that consistently return candles in real-time)
    ACTIVE_5MIN_SYMBOLS = [
        "TCS", "INFY", "RELIANCE", "SBIN", "WIPRO", "HDFCBANK", "ICICIBANK", 
        "ITC", "LT", "BHARTIARTL", "ASIANPAINT", "SUZLON", "GEMAROMA"
    ]
    
    # Always try indices for market context
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    symbols = ACTIVE_5MIN_SYMBOLS + indices

    # Upsert SQL — skip existing, insert new (ON CONFLICT DO NOTHING is fast)
    upsert_sql = text(
        "INSERT INTO candles (symbol, timestamp, open, high, low, close, volume) "
        "VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume) "
        "ON CONFLICT (symbol, timestamp) DO NOTHING"
    )

    for idx, symbol in enumerate(symbols):
        # Create fresh Groww API client for each symbol to avoid connection issues
        try:
            groww = _get_groww()
            if not groww:
                failed_count += 1
                continue
        except Exception as e:
            logger.debug("Failed to get Groww API for %s: %s", symbol, e)
            failed_count += 1
            continue

        # Add small delay between calls to avoid rate limiting
        if idx > 0:
            time.sleep(0.3)

        try:
            resp = groww.get_historical_candle_data(
                trading_symbol=symbol, exchange="NSE", segment="CASH",
                start_time=start_time_str, end_time=end_time, interval_in_minutes=5,
            )
            candles = resp.get("candles", []) if resp else []
            if not candles:
                continue

            # Batch all candles for this symbol in one transaction
            batch = []
            for c in candles:
                ts = c.get("timestamp")
                if not ts:
                    continue
                batch.append({
                    "symbol": symbol, "timestamp": ts,
                    "open": float(c.get("open", 0)), "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)), "close": float(c.get("close", 0)),
                    "volume": int(c.get("volume", 0)),
                })

            if batch:
                with db.engine.begin() as conn:
                    conn.execute(upsert_sql, batch)
                collected_count += len(batch)

        except Exception as e:
            failed_count += 1
            logger.debug("Failed to collect candles for %s: %s", symbol, e)

    if collected_count > 0:
        logger.info("📊 Collected %d candles (%d symbols, %d failed)",
                     collected_count, len(symbols), failed_count)
        try:
            log_candle_collection_event(collected_count, 0)
        except Exception:
            pass


def _task_retrain_xgb_daily():
    """Retrain XGBoost F&O models with all available candle data (runs daily post-market)."""
    from fno_backtester import _generate_xgb_training_data, FEATURE_NAMES
    from datetime import datetime
    
    try:
        import xgboost as xgb
    except ImportError:
        logger.warning("XGBoost not available for retraining")
        return
    
    try:
        logger.info("🧠 Starting daily XGBoost retraining...")
        
        # Generate training data from all candles in DB
        X, y_long, y_short = _generate_xgb_training_data()
        
        if len(X) < 100:
            logger.warning("Insufficient training data for XGBoost retraining: %d samples", len(X))
            return
        
        X = np.array(X, dtype=np.float32)
        y_long = np.array(y_long)
        y_short = np.array(y_short)
        
        lp = int(y_long.sum())
        sp = int(y_short.sum())
        logger.info("XGB retraining: %d samples — long wins %d (%.0f%%), short wins %d (%.0f%%)",
                    len(X), lp, lp / len(X) * 100, sp, sp / len(X) * 100)
        
        # Guard against degenerate labels
        if lp < 5 or sp < 5:
            logger.warning("Too few positive labels (long=%d, short=%d) — skipping retrain", lp, sp)
            return
        
        params = dict(
            n_estimators=150,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=1.0,
            reg_lambda=2.0,
            min_child_weight=5,
            random_state=42,
            eval_metric='logloss',
        )
        
        # Train long model
        long_model = xgb.XGBClassifier(
            scale_pos_weight=max(1.0, (len(y_long) - lp) / max(1, lp)),
            **params,
        )
        long_model.fit(X, y_long)
        
        # Train short model
        short_model = xgb.XGBClassifier(
            scale_pos_weight=max(1.0, (len(y_short) - sp) / max(1, sp)),
            **params,
        )
        short_model.fit(X, y_short)
        
        # Update global cache
        import fno_backtester
        fno_backtester._xgb_models = {"long": long_model, "short": short_model}
        fno_backtester._xgb_model_timestamp = datetime.now()
        
        # Calculate win rates for logging
        long_win_rate = (lp / len(y_long) * 100) if len(y_long) > 0 else 0
        short_win_rate = (sp / len(y_short) * 100) if len(y_short) > 0 else 0
        
        logger.info("✅ XGBoost models retrained successfully at %s", datetime.now().isoformat())
        logger.info("   Long model: %d wins / %d trades (%.1f%% win rate)", lp, len(y_long), long_win_rate)
        logger.info("   Short model: %d wins / %d trades (%.1f%% win rate)", sp, len(y_short), short_win_rate)
        
        # Log feature importances
        for tag, mdl in [("LONG", long_model), ("SHORT", short_model)]:
            imp = mdl.feature_importances_
            top5 = sorted(zip(FEATURE_NAMES, imp), key=lambda x: -x[1])[:5]
            logger.info("XGB %s top features: %s", tag, ", ".join(f"{n}={v:.3f}" for n, v in top5))
        
        # Log training event to metadata table
        try:
            from db_manager import log_xgb_training_event
            log_xgb_training_event(len(X), long_win_rate, short_win_rate)
        except Exception as e:
            logger.debug("Failed to log training metadata: %s", e)
        
    except Exception as e:
        logger.error("XGBoost retraining failed: %s", e)


def _task_ml_retrain():
    """Retrain ML models for all watchlist stocks."""
    from config import WATCHLIST
    import bot
    for symbol in WATCHLIST:
        try:
            bot.train_model(symbol)
        except Exception as e:
            logger.debug("ML retrain failed for %s: %s", symbol, e)


def _task_cost_rate_update():
    """Check and update trading cost rates from live sources."""
    try:
        from costs import update_cost_rates
        update_cost_rates()
    except Exception as e:
        logger.warning("Cost rate update failed: %s", e)


def _task_geopolitical_collect():
    """Collect and store geopolitical news for commodities."""
    try:
        from commodity_tracker import collect_geopolitical_news
        collect_geopolitical_news()
    except Exception as e:
        logger.warning("Geopolitical news collection failed: %s", e)


def _task_fno_auto_trade():
    """Run F&O automated trading cycle — entry/exit signals + order execution."""
    try:
        import fno_trader
        result = fno_trader.auto_trade_fno()
        actions = result.get("actions", []) if result else []
        if actions:
            logger.info("F&O auto-trade: %d action(s) executed", len(actions))
        else:
            reason = result.get("skipped_reason", "no action") if result else "failed"
            logger.debug("F&O auto-trade: %s", reason)
    except Exception as e:
        logger.warning("F&O auto-trade failed: %s", e)


def _task_fno_capital_sync():
    """Sync F&O capital from actual Groww account balance."""
    try:
        import fno_trader
        synced = fno_trader.sync_capital_from_groww()
        if synced is not None:
            logger.debug("F&O capital synced: ₹%.2f", synced)
    except Exception as e:
        logger.warning("F&O capital sync failed: %s", e)


def _task_global_indices():
    """Fetch global indices data for F&O decision-making."""
    try:
        import fno_trader
        indices = fno_trader.fetch_global_indices()
        logger.debug("Global indices refreshed: %d indices", len(indices))
    except Exception as e:
        logger.warning("Global indices fetch failed: %s", e)


def _task_token_refresh():
    """Check if Groww token is still valid, refresh if expired."""
    try:
        from token_refresher import check_and_refresh
        check_and_refresh()
    except Exception as e:
        logger.warning("Token refresh check failed: %s", e)


def _task_world_news():
    """Collect world/macro/sector news from RSS feeds and Google News."""
    try:
        from world_news_collector import collect_world_news
        collect_world_news()
    except Exception as e:
        logger.warning("World news collection failed: %s", e)


def _task_deep_analysis():
    """Pre-generate deep contextual analysis for watchlist stocks (cached)."""
    try:
        from deep_analysis import generate_deep_analysis
        from config import WATCHLIST
        # Analyze top watchlist stocks to pre-warm cache
        for symbol in list(WATCHLIST)[:6]:
            try:
                generate_deep_analysis(symbol)
            except Exception as e:
                logger.debug("Deep analysis pre-gen failed for %s: %s", symbol, e)
    except Exception as e:
        logger.warning("Deep analysis task failed: %s", e)


def _task_sync_historical_candles():
    """
    Sync ALL historical candles end-of-day (after 3:30 PM IST).
    - Skips during market hours (9:15 AM - 3:30 PM IST)
    - Runs ONCE daily before close (late afternoon safe window)
    - Does full backfill: fetches any missing dates since last stored candle
    - Feeds data to daily aggregation
    """
    try:
        from db_manager import get_db, get_all_stocks
        from config import DEFAULT_EXCHANGE, DB_URL
        from datetime import datetime, timedelta
        from fno_trader import _is_market_open
        import psycopg2
        import bot
        
        # Only sync if market is closed OR very close to close (3:25 PM+)
        now = datetime.utcnow()
        ist_now = now + timedelta(hours=5, minutes=30)  # IST = UTC + 5:30
        ist_hour = ist_now.hour
        ist_minute = ist_now.minute
        ist_time_minutes = ist_hour * 60 + ist_minute
        
        market_close_time = 15 * 60 + 30  # 3:30 PM = 15:30
        
        # Skip during market hours (9:15 AM to 3:30 PM IST, weekdays only)
        if ist_now.weekday() < 5:  # Monday-Friday
            if ist_time_minutes < market_close_time:
                logger.debug("Market still open, skipping candle sync")
                return
        
        db = get_db()
        if not db:
            logger.debug("Database not available for candle sync")
            return
        
        stocks = get_all_stocks(db)
        if not stocks:
            logger.debug("No stocks found in database")
            return
        
        synced_count = 0
        failed_count = 0
        symbols = [s.symbol for s in stocks if s.is_active]
        
        logger.info("📊 End-of-day candle backfill starting for %d stocks...", len(symbols))
        
        # Aggressive backfill: fetch last 365 days worth of data for any symbol with gaps
        for symbol in symbols:
            try:
                # Check if symbol has any candles
                conn = psycopg2.connect(DB_URL)
                cursor = conn.cursor()
                cursor.execute("SELECT MAX(timestamp) FROM candles WHERE symbol = %s", (symbol,))
                latest = cursor.fetchone()[0]
                cursor.close()
                conn.close()
                
                # Sync from API (will fetch only missing data)
                new_candles = bot.sync_candles_from_api(symbol, days=365)
                if new_candles > 0:
                    synced_count += new_candles
                    logger.debug(f"  ✓ {symbol}: {new_candles} new candles")
            except Exception as e:
                failed_count += 1
                logger.debug("Failed to sync %s: %s", symbol, e)
        
        logger.info("✅ End-of-day sync complete: %d candles synced (%d failed)", synced_count, failed_count)
        
        # Auto-trigger daily aggregation after sync
        logger.info("🔄 Triggering daily price aggregation...")
        _task_aggregate_candles_to_daily()
    
    except Exception as e:
        logger.warning("Historical candle sync task failed: %s", e)


def _task_aggregate_candles_to_daily():
    """
    Aggregate ALL 5-minute candles into daily OHLCV prices for watchlist display.
    Called after end-of-day sync to ensure all data is fresh.
    """
    try:
        from db_manager import get_db, get_all_stocks
        from config import DB_URL
        import psycopg2
        from datetime import datetime, timedelta
        
        db = get_db()
        if not db:
            logger.debug("Database not available for aggregation")
            return
        
        stocks = get_all_stocks(db)
        if not stocks:
            logger.debug("No stocks found")
            return
        
        symbols = [s.symbol for s in stocks if s.is_active]
        
        # Aggregate ALL candles to daily prices (full backfill for any gaps)
        aggregated = 0
        
        for symbol in symbols:
            # Fresh connection for each symbol
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            
            try:
                # Get all unique dates with candles, aggregate each
                cursor.execute("""
                    SELECT 
                        DATE(timestamp) as trade_date,
                        MIN(open) as open_price,
                        MAX(high) as high_price,
                        MIN(low) as low_price,
                        (array_agg(close ORDER BY timestamp DESC))[1] as close_price,
                        SUM(CAST(volume AS BIGINT)) as total_volume
                    FROM candles
                    WHERE symbol = %s
                    GROUP BY DATE(timestamp)
                    ORDER BY DATE(timestamp)
                """, (symbol,))
                
                rows = cursor.fetchall()
                if not rows:
                    cursor.close()
                    conn.close()
                    continue
                
                # Insert/update all dates (upsert)
                insert_count = 0
                for row in rows:
                    trade_date, open_p, high_p, low_p, close_p, vol = row
                    insert_query = """
                        INSERT INTO stock_prices (symbol, date, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol, date) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume
                    """
                    cursor.execute(insert_query, (
                        symbol,
                        trade_date,
                        float(open_p) if open_p else None,
                        float(high_p) if high_p else None,
                        float(low_p) if low_p else None,
                        float(close_p) if close_p else None,
                        int(vol) if vol else 0,
                    ))
                    insert_count += 1
                
                conn.commit()
                aggregated += insert_count
                logger.debug(f"  ✓ {symbol}: aggregated {insert_count} daily prices")
            
            except Exception as e:
                logger.debug("Failed to aggregate %s: %s", symbol, e)
            
            finally:
                cursor.close()
                conn.close()
        
        if aggregated > 0:
            logger.info("✅ Aggregated %d daily prices for watchlist", aggregated)
    
    except Exception as e:
        logger.warning("Candle aggregation task failed: %s", e)


def _task_market_intelligence():

    """Collect institutional holdings, peer comparisons for all watchlist stocks."""
    try:
        import market_intelligence as mi
        mi.collect_all_watchlist()
    except Exception as e:
        logger.warning("Market intelligence task failed: %s", e)


def _task_auto_metadata():
    """Auto-refresh stock metadata: company names, sectors, peers, commodities from Screener.in."""
    try:
        import auto_metadata as am
        am.refresh_all_metadata()
    except Exception as e:
        logger.warning("Auto-metadata refresh failed: %s", e)


def _task_research_engine():
    """Run the unified research algorithm on all tracked stocks."""
    try:
        import research_engine as re_eng
        re_eng.generate_research_all()
    except Exception as e:
        logger.warning("Research engine batch failed: %s", e)


def _task_cash_auto_trade():
    """Run cash equity auto-trade (paper or real based on DB config)."""
    try:
        from db_manager import get_config
        # Check if cash auto-trade is enabled (disabled by default)
        if get_config("cash_auto_trade_enabled", "false").lower() != "true":
            return
        import bot
        # Check market hours
        from fno_trader import _is_market_open
        market_open, _ = _is_market_open()
        if not market_open:
            return
        # Ensure portfolio is reviewed (auto-set for paper mode)
        if bot.is_paper_mode() and not bot.is_portfolio_reviewed():
            bot.mark_portfolio_reviewed()
        result = bot.auto_trade()
        actions = result.get("actions", []) if result else []
        trades = [a for a in actions if a.get("action") in ("BUY", "SELL")]
        if trades:
            logger.info("Cash auto-trade: %d trade(s) executed", len(trades))
    except Exception as e:
        logger.warning("Cash auto-trade failed: %s", e)


def _task_auto_close_trades():
    """Automatically close trades when they hit target price or stop loss."""
    try:
        from fno_trader import _is_market_open
        import json
        import os
        from paper_trader import get_live_price
        from trailing_stop import check_and_close_trades_on_loss
        
        # Check market hours (only during trading)
        market_open, _ = _is_market_open()
        if not market_open:
            return
        
        trades_json_path = os.path.join(PROJECT_ROOT, 'paper_trades.json')
        if not os.path.exists(trades_json_path):
            return
        
        try:
            with open(trades_json_path, 'r') as f:
                trades = json.load(f)
        except:
            return
        
        # Get unique symbols from OPEN trades
        open_trades = [t for t in trades if t.get('status') == 'OPEN']
        if not open_trades:
            return
        
        open_symbols = list(set(t['symbol'] for t in open_trades))
        
        # Fetch live prices for all OPEN trade symbols
        live_prices = {}
        for symbol in open_symbols:
            try:
                price = get_live_price(symbol)
                if price:
                    live_prices[symbol] = price
            except Exception as e:
                logger.debug(f"Error fetching price for {symbol}: {e}")
        
        if not live_prices:
            return
        
        # Check and close trades
        closed_trades = check_and_close_trades_on_loss(
            paper_trades_file='paper_trades.json',
            live_prices=live_prices
        )
        
        if closed_trades:
            logger.info(f"Auto-closed {len(closed_trades)} trades: {[t['symbol'] + ' ' + t['reason'] for t in closed_trades]}")
    
    except Exception as e:
        logger.warning(f"Auto-close trades failed: {e}")


def _task_record_pnl():
    """Record unrealised P&L snapshot every 5 seconds during market hours."""
    try:
        import json
        import os
        from db_manager import get_db, PnLSnapshot
        
        # TEST: Temporarily disabled market hours check to test P&L recording
        # from fno_trader import _is_market_open
        # market_open, _ = _is_market_open()
        # if not market_open:
        #     return
        
        trades_json_path = os.path.join(PROJECT_ROOT, 'paper_trades.json')
        if not os.path.exists(trades_json_path):
            return
        
        try:
            with open(trades_json_path, 'r') as f:
                trades = json.load(f)
        except Exception as load_error:
            logger.debug(f"Failed to load trades JSON: {load_error}")
            return
        
        # Calculate P&L from open trades
        open_trades = [t for t in trades if t.get('status') == 'OPEN']
        if not open_trades:
            return
        
        # Get live prices for all symbols
        live_prices = {}
        try:
            import requests
            from config import FLASK_HOST, FLASK_PORT
            
            # Build API URL (use environment variable if available, otherwise construct from Flask host/port)
            api_url = os.getenv('API_URL') or f'http://localhost:{FLASK_PORT}/api/live-prices'
            
            symbols = list(set([t['symbol'] for t in open_trades]))
            response = requests.post(
                api_url,
                json={'symbols': symbols},
                timeout=5
            )
            if response.status_code == 200:
                live_prices = response.json().get('prices', {})
                logger.debug(f"[PnL] Got live prices for {len(live_prices)} symbols")
            else:
                logger.debug(f"[PnL] Live prices API returned {response.status_code}")
        except Exception as price_error:
            logger.debug(f"[PnL] Failed to fetch live prices: {price_error}")
        
        total_pnl = 0.0
        total_pnl_pct = 0.0
        profit_count = 0
        loss_count = 0
        peak_pnl = 0.0
        
        for trade in open_trades:
            symbol = trade.get('symbol')
            entry_price = trade.get('entry_price', 0)
            current_price = live_prices.get(symbol)
            
            if current_price and entry_price:
                # Calculate P&L
                if trade.get('signal') == 'BUY':
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                else:  # SELL
                    pnl_pct = ((entry_price - current_price) / entry_price) * 100
                
                quantity = trade.get('quantity', 1)
                pnl_amount = (pnl_pct / 100) * (entry_price * quantity)
                
                total_pnl += pnl_amount
                total_pnl_pct += pnl_pct
                
                # Track peak P&L for each trade
                trade_peak = trade.get('peak_pnl', pnl_pct)
                if pnl_pct > trade_peak:
                    trade_peak = pnl_pct
                
                peak_pnl = max(peak_pnl, trade_peak)
                
                if pnl_pct > 0:
                    profit_count += 1
                elif pnl_pct < 0:
                    loss_count += 1
        
        # Average P&L percentage
        avg_pnl_pct = total_pnl_pct / len(open_trades) if open_trades else 0
        
        logger.debug(f"[PnL] Recording: total_pnl=₹{total_pnl:.2f}, avg_pct={avg_pnl_pct:.2f}%, profit={profit_count}, loss={loss_count}")
        
        # Store in database
        db = get_db()
        if db:
            session = db.Session()
            try:
                snapshot = PnLSnapshot(
                    total_pnl=round(total_pnl, 2),
                    total_pnl_pct=round(avg_pnl_pct, 2),
                    trades_count=len(open_trades),
                    peak_pnl=round(peak_pnl, 2),
                    peak_pnl_pct=round(peak_pnl, 2),
                    profit_trades=profit_count,
                    loss_trades=loss_count,
                )
                session.add(snapshot)
                session.commit()
                logger.debug(f"[PnL] ✓ Snapshot saved successfully")
            except Exception as save_error:
                logger.debug(f"[PnL] Failed to save snapshot: {save_error}")
            except Exception as save_error:
                logger.debug(f"Failed to save P&L snapshot: {save_error}")
            finally:
                session.close()
    
    except Exception as e:
        logger.debug(f"Record P&L task failed: {e}")


def _task_paper_eod_summary():
    """Send end-of-day paper trading summary via Telegram."""
    try:
        from db_manager import get_config
        if get_config("telegram_enabled", "false").lower() != "true":
            return
        if get_config("paper_trading", "false").lower() != "true":
            return
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        # Only send between 15:30-16:00 IST
        if not (now_ist.hour == 15 and 30 <= now_ist.minute <= 59):
            return
        _send_paper_eod_summary()
    except Exception as e:
        logger.warning("Paper EOD summary failed: %s", e)


def _send_paper_eod_summary():
    """Generate and send paper trade EOD summary with reasoning."""
    import telegram_alerts
    from db_manager import get_db, PaperTrade
    from datetime import timezone, timedelta

    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()

    try:
        db = get_db()
        with db.Session() as session:
            from sqlalchemy import func
            trades = session.query(PaperTrade).filter(
                func.date(PaperTrade.created_at) >= today
            ).order_by(PaperTrade.created_at).all()

            if not trades:
                telegram_alerts.send_message(
                    "<b>Paper Trading EOD</b>\n"
                    f"{today.strftime('%d %b %Y')}\n\n"
                    "No paper trades today. Market conditions did not meet thresholds."
                )
                return

            total_buy_value = 0
            total_charges = 0
            lines = [
                f"<b>Paper Trading EOD Summary</b>",
                f"{today.strftime('%d %b %Y')}",
                f"━━━━━━━━━━━━━━━━━━",
                f"Trades: {len(trades)}",
                "",
            ]
            for t in trades:
                emoji = "BUY" if t.side == "BUY" else "SELL"
                val = t.price * t.quantity
                total_charges += t.charges or 0
                if t.side == "BUY":
                    total_buy_value += val
                lines.append(
                    f"{emoji} <b>{t.symbol}</b> x{t.quantity} @ ₹{t.price:.2f} "
                    f"(₹{val:,.0f}) | Charges: ₹{t.charges:.2f}"
                )

            lines.append(f"\nTotal deployed: ₹{total_buy_value:,.0f}")
            lines.append(f"Total charges: ₹{total_charges:.2f}")

            # Capital recommendation
            if total_buy_value > 0:
                # Add buffer for margin + charges
                recommended = int(total_buy_value * 1.3 + total_charges * 2)
                lines.append(f"\n<b>Recommended capital: ₹{recommended:,}</b>")
                lines.append("(based on today's trades + 30% buffer + charges)")

            telegram_alerts.send_message("\n".join(lines))
    except Exception as e:
        logger.warning("Paper EOD summary generation failed: %s", e)


def _task_telegram_daily_summary():
    """Send comprehensive daily summary via Telegram (once at ~15:30 IST)."""
    try:
        from db_manager import get_config
        if get_config("telegram_enabled", "false").lower() != "true":
            return
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        # Only send between 15:30-16:00 IST (right after market close)
        if not (now_ist.hour == 15 and 30 <= now_ist.minute <= 59):
            return
        from daily_summary import send_daily_summary
        send_daily_summary()
    except Exception as e:
        logger.warning("Telegram daily summary failed: %s", e)


def _task_build_daily_snapshots():
    """Build comprehensive end-of-day trading snapshots with REAL market data (1-min candles) after 4 PM."""
    try:
        from datetime import timezone, timedelta
        from config import PROJECT_ROOT
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        
        # Only build snapshots between 4:05 PM - 4:30 PM IST (once per day)
        if not (now_ist.hour == 16 and 5 <= now_ist.minute <= 30):
            return
        
        # Check if already built today (prevent re-running)
        import json
        snapshots_path = os.path.join(PROJECT_ROOT, 'daily_snapshots.json')
        if os.path.exists(snapshots_path):
            try:
                with open(snapshots_path, 'r') as f:
                    snapshots = json.load(f)
                # Check if snapshots are from today
                if snapshots and isinstance(snapshots, dict):
                    first_snapshot = next(iter(snapshots.values()), {})
                    snapshot_date = first_snapshot.get('date')
                    today_str = now_ist.date().strftime("%Y-%m-%d")
                    if snapshot_date == today_str:
                        logger.debug("Daily snapshots already built for today")
                        return
            except:
                pass
        
        logger.info("📊 Building daily trading snapshots with REAL market data (1-min candles)...")
        
        # Call the build endpoint which will attach real market candles
        import requests
        try:
            # Build API URL from environment or construct from Flask config
            from config import FLASK_PORT
            api_url = os.getenv('API_URL') or f'http://localhost:{FLASK_PORT}/api/paper-trading/build-daily-snapshots-with-candles'
            
            response = requests.post(api_url, timeout=180)
            if response.status_code == 200:
                result = response.json()
                count = result.get('snapshots_count', 0)
                candles_count = result.get('candles_fetched', 0)
                logger.info(f"✓ Daily snapshots built: {count} symbols with {candles_count} 5-minute candles")
            else:
                logger.warning(f"Snapshot build failed: HTTP {response.status_code}")
        except Exception as e:
            logger.warning(f"Failed to build daily snapshots: {e}")
    
    except Exception as e:
        logger.warning("Daily snapshot task failed: %s", e)


# ── Scheduler engine ─────────────────────────────────────────────────────────

def _run_task_safe(task):
    """Run a single task with its own lock (prevents self-overlap)."""
    lock = _task_locks.get(task["name"])
    if lock and not lock.acquire(blocking=False):
        logger.debug("Skipping '%s' — still running from previous cycle", task["name"])
        return
    try:
        logger.debug("Scheduler running: %s", task["name"])
        task["fn"]()
        task["last_run"] = time.time()
    except Exception as e:
        logger.error("Scheduler task '%s' failed: %s", task["name"], e)
    finally:
        if lock:
            lock.release()


def _scheduler_loop():
    """Main scheduler loop — dispatches due tasks to thread pool."""
    global _pool
    _pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="sched")
    logger.info("Master scheduler started with %d tasks (pool=%d workers)", len(_tasks), MAX_WORKERS)

    # Wait for server to stabilize
    time.sleep(5)
    start_time = time.time()

    while True:
        # Check if paused via Telegram /stop command
        try:
            from telegram_commander import is_scheduler_paused
            if is_scheduler_paused():
                time.sleep(10)
                continue
        except Exception:
            pass

        now = time.time()
        elapsed = now - start_time
        for task in _tasks:
            # Honour initial_delay: skip until enough time has passed since start
            if not task["_started"]:
                if elapsed < task["initial_delay"]:
                    continue
                task["_started"] = True
                task["last_run"] = 0  # ensure it fires immediately once delay elapses

            if now - task["last_run"] >= task["interval"]:
                # Submit to pool — non-blocking; lock prevents self-overlap
                _pool.submit(_run_task_safe, task)
                task["last_run"] = now  # mark scheduled (even if lock skips it)
        # Sleep 15s between checks (faster reaction to due tasks)
        time.sleep(15)


def start_scheduler():
    """
    Register all tasks and start the scheduler daemon thread.
    Call this once from app.py on startup.
    """
    # Register tasks — staggered initial_delay to avoid API rate-limit storm
    # Tier 1: Instant (0s) — lightweight / critical for dashboard
    _register("token_refresh",   _task_token_refresh, 3600, initial_delay=0)
    _register("cache_refresh",    _task_cache_refresh,  3600, initial_delay=0)
    _register("update_watchlist_prices", _task_update_watchlist_prices, 3600, initial_delay=10)

    # Tier 2: 5s — market data needed for predictions
    _register("collect_5min_candles", _task_collect_5min_candles, 300, initial_delay=5)
    _register("sync_historical_candles", _task_sync_historical_candles, 3600, initial_delay=12)  # End-of-day sync (after 3:30 PM IST)
    _register("record_pnl", _task_record_pnl, 5, initial_delay=8)  # Record P&L every 5 seconds

    # Tier 3: 15s — analysis that feeds the dashboard
    _register("auto_analysis",    _task_auto_analysis,  300, initial_delay=15)
    _register("news_prefetch",    _task_news_prefetch,   600, initial_delay=20)

    # Tier 4: 30s — trading tasks (need candles + predictions ready)
    _register("fno_auto_trade",   _task_fno_auto_trade,  300, initial_delay=30)
    _register("cash_auto_trade",      _task_cash_auto_trade,  300, initial_delay=35)
    _register("auto_close_trades", _task_auto_close_trades, 30, initial_delay=36)  # Check every 30s for TP/SL hits
    _register("fno_capital_sync", _task_fno_capital_sync, 600, initial_delay=40)

    # Tier 5: 60s — secondary data feeds
    _register("global_indices",   _task_global_indices,  900, initial_delay=60)
    _register("world_news",      _task_world_news,    900, initial_delay=65)
    _register("geopolitical",     _task_geopolitical_collect, 1800, initial_delay=70)
    _register("supply_chain",     _task_supply_chain,    900, initial_delay=75)
    _register("telegram_summary",    _task_telegram_daily_summary, 1800, initial_delay=80)
    _register("paper_eod_summary",    _task_paper_eod_summary, 1800, initial_delay=85)
    _register("build_daily_snapshots", _task_build_daily_snapshots, 900, initial_delay=86)  # Check every 15 minutes after 4 PM
    _register("cost_rate_update", _task_cost_rate_update, 259200, initial_delay=90)

    # Tier 6: 120s — heavy compute / rare tasks
    _register("deep_analysis",   _task_deep_analysis, 1800, initial_delay=120)
    _register("market_intelligence", _task_market_intelligence, 21600, initial_delay=130)
    _register("research_engine",     _task_research_engine, 14400, initial_delay=140)
    _register("ml_retrain",       _task_ml_retrain,    86400, initial_delay=150)
    _register("retrain_xgb_daily", _task_retrain_xgb_daily, 86400, initial_delay=160)
    _register("auto_metadata",       _task_auto_metadata, 604800, initial_delay=170)

    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="master-scheduler")
    thread.start()
    logger.info("✓ Master scheduler running in background (%d tasks)", len(_tasks))
    return thread
