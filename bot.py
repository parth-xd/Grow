"""
Trading Bot — Connects AI predictions to Groww API order execution.
Fetches historical data, runs predictions, and places/manages trades.
"""

import time
import os
import logging
import pandas as pd
from datetime import datetime, timedelta

from config import (
    GROWW_ACCESS_TOKEN, DEFAULT_EXCHANGE, DEFAULT_SEGMENT, DEFAULT_PRODUCT,
    DEFAULT_VALIDITY, MAX_TRADE_QUANTITY, MAX_TRADE_VALUE, WATCHLIST,
    STOP_LOSS_PCT, TARGET_PCT, MAX_POSITIONS, PREDICTION_LOOKBACK_DAYS,
    CANDLE_INTERVAL_MINUTES, CONFIDENCE_THRESHOLD, DB_URL,
)
from predictor import PricePredictor

# Try to import database module (optional)
try:
    from db_manager import get_db
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    get_db = None

import costs
import news_sentiment
import market_context
import trade_journal

logger = logging.getLogger(__name__)

# ── Database & Groww SDK wrapper ───────────────────────────────────────────

_groww = None
_groww_token_cache = None  # Track token changes for auto-refresh
_db = None
_predictors = {}   # symbol -> PricePredictor
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


def _load_predictor(symbol):
    """Try to load a persisted ML model from disk."""
    import joblib
    path = os.path.join(_MODELS_DIR, f"{symbol}.joblib")
    if os.path.exists(path):
        try:
            _predictors[symbol] = joblib.load(path)
            logger.debug(f"Loaded persisted model for {symbol}")
            return True
        except Exception as e:
            logger.debug(f"Failed to load model for {symbol}: {e}")
    return False


def _save_predictor(symbol):
    """Persist an ML model to disk."""
    import joblib
    os.makedirs(_MODELS_DIR, exist_ok=True)
    path = os.path.join(_MODELS_DIR, f"{symbol}.joblib")
    try:
        joblib.dump(_predictors[symbol], path)
        logger.debug(f"Saved model for {symbol}")
    except Exception as e:
        logger.debug(f"Failed to save model for {symbol}: {e}")
_trade_log = []    # in-memory trade history (also persisted to DB)
_trade_log_loaded = False


def _load_trade_log():
    """Load trade log from DB on first access."""
    global _trade_log, _trade_log_loaded
    if _trade_log_loaded:
        return
    _trade_log_loaded = True
    try:
        from db_manager import get_db as _get_db_mgr, TradeLogEntry as TLE
        db_inst = _get_db_mgr()
        with db_inst.Session() as session:
            rows = session.query(TLE).order_by(TLE.created_at).all()
            if rows:
                _trade_log = [r.to_dict() for r in rows]
    except Exception:
        pass


def _persist_trade_log_entry(entry):
    """Persist a single trade log entry to DB."""
    try:
        from db_manager import get_db as _get_db_mgr, TradeLogEntry as TLE
        db_inst = _get_db_mgr()
        with db_inst.Session() as session:
            row = TLE(
                symbol=entry.get("symbol", ""),
                side=entry.get("side", ""),
                quantity=entry.get("quantity", 0),
                price=entry.get("price", 0),
                order_id=entry.get("order_id"),
                order_status=entry.get("status"),
                trade_id=entry.get("trade_id"),
            )
            session.add(row)
            session.commit()
    except Exception as e:
        logger.debug("DB persist trade log failed (non-fatal): %s", e)


def _get_groww():
    global _groww, _groww_token_cache
    
    from growwapi import GrowwAPI
    
    # Always read fresh token from environment (handles auto-refresh)
    current_token = os.getenv("GROWW_ACCESS_TOKEN") or GROWW_ACCESS_TOKEN
    
    if not current_token:
        raise RuntimeError("GROWW_ACCESS_TOKEN is not set. Configure it in .env")
    
    # Recreate client if token has changed (handles token refresh)
    if _groww is None or _groww_token_cache != current_token:
        _groww = GrowwAPI(current_token)
        _groww_token_cache = current_token
        logger.info("Created new GrowwAPI instance: %s", type(_groww).__name__)
    
    logger.info("Returning groww instance: %s (is None: %s)", type(_groww).__name__ if _groww else "None", _groww is None)
    return _groww


def _get_db():
    """Get database instance (or None if not available)."""
    global _db
    if not _DB_AVAILABLE:
        return None
    if _db is None and get_db:
        try:
            _db = get_db(DB_URL)
        except Exception as e:
            logger.warning(f"Could not initialize database: {e}")
            return None
    return _db


# ── Data fetching with database ──────────────────────────────────────────────

def sync_candles_from_api(symbol, days=None, interval=None):
    """
    Fetch new candles from API only since last stored candle (if DB available).
    If database not available, fetches full lookback period from API.
    
    Returns:
        Integer: number of new candles synced (0 if DB not available)
    """
    days = days or PREDICTION_LOOKBACK_DAYS
    interval = interval or CANDLE_INTERVAL_MINUTES
    
    db = _get_db()
    if db is None:
        logger.debug(f"↷ {symbol}: Database not available, skipping sync")
        return 0
    
    latest_ts = db.get_latest_timestamp(symbol)
    
    # Determine start time: either from last candle or full lookback
    if latest_ts:
        start_time = latest_ts + timedelta(minutes=interval)
    else:
        start_time = datetime.utcnow() - timedelta(days=days)
    
    end_time = datetime.utcnow()
    
    # Always sync if there's a gap > 1 day (handles stale data gracefully)
    gap_seconds = (end_time - start_time).total_seconds()
    if gap_seconds < 86400:  # Less than 1 day gap - skip to avoid excessive API calls
        logger.debug(f"↷ {symbol}: No new data to sync (gap only {gap_seconds/3600:.1f} hours)")
        return 0
    
    groww = _get_groww()
    try:
        resp = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange=DEFAULT_EXCHANGE,
            segment=DEFAULT_SEGMENT,
            start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            interval_in_minutes=interval,
        )
        
        candles = resp.get("candles", [])
        if candles:
            # Convert API response format to database format
            candles_formatted = [
                {
                    "timestamp": int(c[0]),  # Unix timestamp
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                }
                for c in candles
            ]
            db.insert_candles(symbol, candles_formatted)
            logger.info(f"✓ Synced {len(candles)} new candles for {symbol}")
            return len(candles)
        else:
            logger.debug(f"↷ {symbol}: No new candles from API")
            return 0
    except Exception as e:
        logger.error(f"✗ Failed to sync {symbol}: {e}")
        return 0


def fetch_historical(symbol, days=None, interval=None):
    """
    Fetch historical candle data from database (if available) or directly from API.
    Prioritizes TODAY's live market data over historical data.
    Falls back to daily candles if 5-min data is unavailable.
    
    Returns:
        DataFrame with columns: timestamp, datetime, open, high, low, close, volume
    """
    days = days or PREDICTION_LOOKBACK_DAYS
    interval = interval or CANDLE_INTERVAL_MINUTES
    
    db = _get_db()
    
    if db:
        # Database available: try to sync and fetch from DB
        sync_candles_from_api(symbol, days, interval)
        
        # PRIORITY: Get today's data first (market still open, get latest 5-min candles)
        today = datetime.now().date()
        today_start = int(datetime.combine(today, datetime.min.time()).timestamp())
        today_df = db.get_candles(symbol, days=1, interval_minutes=interval)  # Get today only
        
        if not today_df.empty and len(today_df) > 2:
            # We have enough today data, use it
            logger.debug(f"↷ {symbol}: Using {len(today_df)} candles from TODAY (prioritized over historical)")
            return today_df
        
        # FALLBACK: Use full lookback if today data is insufficient
        df = db.get_candles(symbol, days=days, interval_minutes=interval)
        
        if not df.empty:
            logger.debug(f"↷ {symbol}: Fetched {len(df)} candles from DB (last: {df['datetime'].iloc[-1]})")
            return df
    
    # Fallback: fetch directly from API (old method)
    logger.debug(f"↷ {symbol}: Fetching directly from API (DB unavailable)")
    groww = _get_groww()
    
    end_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    start_time = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        resp = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange=DEFAULT_EXCHANGE,
            segment=DEFAULT_SEGMENT,
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=interval,
        )
        
        candles = resp.get("candles", [])
        if not candles:
            return pd.DataFrame()
        
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df = df.sort_values("datetime").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
        
    except Exception as e:
        error_str = str(e).lower()
        # If 5-min data is unavailable for this duration, fall back to daily candles
        if "invalid interval" in error_str or "large interval" in error_str:
            logger.debug(f"↷ {symbol}: 5-min data unavailable, falling back to daily candles")
            try:
                resp = groww.get_historical_candle_data(
                    trading_symbol=symbol,
                    exchange=DEFAULT_EXCHANGE,
                    segment=DEFAULT_SEGMENT,
                    start_time=start_time,
                    end_time=end_time,
                    interval_in_minutes=1440,  # Daily
                )
                
                candles = resp.get("candles", [])
                if not candles:
                    return pd.DataFrame()
                
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
                df = df.sort_values("datetime").reset_index(drop=True)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                logger.debug(f"↷ {symbol}: Fetched {len(df)} daily candles from API")
                return df
            except Exception as e2:
                logger.error(f"✗ Failed to fetch daily candles for {symbol}: {e2}")
                return pd.DataFrame()
        else:
            logger.error(f"✗ Failed to fetch historical data for {symbol}: {e}")
            return pd.DataFrame()


def fetch_live_price(symbol):
    """Fetch the last traded price for a symbol."""
    groww = _get_groww()
    resp = groww.get_ltp(
        segment=DEFAULT_SEGMENT,
        exchange_trading_symbols=f"{DEFAULT_EXCHANGE}_{symbol}",
    )
    key = f"{DEFAULT_EXCHANGE}_{symbol}"
    return float(resp.get(key, 0))


def fetch_quote(symbol):
    """Fetch full quote for a symbol."""
    groww = _get_groww()
    return groww.get_quote(
        exchange=DEFAULT_EXCHANGE,
        segment=DEFAULT_SEGMENT,
        trading_symbol=symbol,
    )


# ── AI prediction ────────────────────────────────────────────────────────────

def train_model(symbol):
    """Train (or retrain) the AI model for a symbol and persist to disk."""
    df = fetch_historical(symbol)
    if df.empty:
        return {"success": False, "message": f"No historical data for {symbol}"}

    predictor = PricePredictor()
    result = predictor.train(df)
    if result["success"]:
        _predictors[symbol] = predictor
        _save_predictor(symbol)
    result["symbol"] = symbol
    return result


def analyze_long_term_trend(symbol):
    """
    Analyze 5-year historical price trend from database.
    Returns metrics about long-term price behavior.
    """
    try:
        import psycopg2
        from dotenv import load_dotenv
        import os
        load_dotenv()
        
        db_url = os.getenv("DB_URL")
        if not db_url:
            return None
        
        conn = psycopg2.connect(db_url, connect_timeout=3)
        cursor = conn.cursor()
        
        # Fetch 5-year price history
        cursor.execute("""
            SELECT date, close, high, low, volume 
            FROM stock_prices 
            WHERE symbol = %s 
            ORDER BY date ASC
        """, (symbol,))
        
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not rows or len(rows) < 100:
            return None
        
        # Convert to price list
        prices = [row[1] for row in rows]
        dates = [row[0] for row in rows]
        
        # Calculate trend metrics
        start_price = prices[0]
        end_price = prices[-1]
        max_price = max(prices)
        min_price = min(prices)
        avg_price = sum(prices) / len(prices)
        
        # Calculate volatility (std dev of daily returns)
        daily_returns = []
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i-1]) / prices[i-1] * 100
            daily_returns.append(ret)
        
        volatility = (sum(x**2 for x in daily_returns) / len(daily_returns)) ** 0.5
        
        # Calculate trend direction (5-year slope)
        trend_direction = (end_price - start_price) / start_price * 100
        
        # Identify if stock is near support/resistance
        q1_price = max(prices[:len(prices)//4])  # 1st quarter high
        q4_price = max(prices[3*len(prices)//4:])  # Last quarter high
        support = min(prices[-250:]) if len(prices) > 250 else min_price  # 1-year support
        resistance = max(prices[-250:]) if len(prices) > 250 else max_price  # 1-year resistance
        
        distance_from_support = ((end_price - support) / support * 100) if support > 0 else 0
        distance_from_resistance = ((end_price - resistance) / resistance * 100) if resistance > 0 else 0
        
        return {
            "total_candles": len(prices),
            "date_range": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
            "start_price": start_price,
            "end_price": end_price,
            "trend_pct": round(trend_direction, 2),
            "min_price": min_price,
            "max_price": max_price,
            "avg_price": round(avg_price, 2),
            "volatility": round(volatility, 2),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "distance_from_support_pct": round(distance_from_support, 2),
            "distance_from_resistance_pct": round(distance_from_resistance, 2),
        }
    except Exception as e:
        logger.warning(f"Could not analyze long-term trend for {symbol}: {e}")
        return None


# ── Trade Snapshot Capture ───────────────────────────────────────────────────

def _capture_trade_snapshot(symbol, side, price, quantity, segment, paper_order_id,
                            prediction=None, reason=""):
    """Save full trade context (candles, indicators, news, reasoning) for chart replay."""
    import json as _json
    try:
        from db_manager import get_db, TradeSnapshot

        # 1. Candle data (last 60 days)
        candles_data = None
        try:
            df = fetch_historical(symbol)
            if not df.empty:
                # Last 60 rows of OHLCV
                recent = df.tail(60)
                candles_data = []
                for _, row in recent.iterrows():
                    candles_data.append({
                        "t": row.get("timestamp", row.get("datetime", "")),
                        "o": round(float(row["open"]), 2),
                        "h": round(float(row["high"]), 2),
                        "l": round(float(row["low"]), 2),
                        "c": round(float(row["close"]), 2),
                        "v": int(row.get("volume", 0)),
                    })
        except Exception as e:
            logger.debug("Snapshot candle fetch failed for %s: %s", symbol, e)

        # 2. Indicators + sources from prediction
        indicators_data = None
        sources_data = None
        signal = side
        confidence = 0
        combined_score = 0
        market_ctx = None

        if prediction:
            indicators_data = prediction.get("indicators")
            sources_data = prediction.get("sources")
            signal = prediction.get("signal", side)
            confidence = prediction.get("confidence", 0)
            combined_score = prediction.get("combined_score", 0)
            ctx = (prediction.get("sources") or {}).get("market_context")
            if ctx:
                market_ctx = ctx

        # 3. News at trade time
        news_data = None
        try:
            news = news_sentiment.get_news_sentiment(symbol)
            if news and news.articles:
                news_data = [{
                    "title": a.title,
                    "sentiment": round(a.sentiment_score, 4),
                    "source": a.source,
                    "date": str(a.published or ""),
                } for a in news.articles[:10]]
        except Exception:
            pass

        # 4. Save to DB
        db = get_db()
        session = db.Session()
        snap = TradeSnapshot(
            paper_order_id=paper_order_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            segment=segment,
            candles_json=_json.dumps(candles_data, default=str) if candles_data else None,
            indicators_json=_json.dumps(indicators_data, default=str) if indicators_data else None,
            news_json=_json.dumps(news_data, default=str) if news_data else None,
            reasoning=reason[:1000] if reason else None,
            signal=signal,
            confidence=confidence,
            combined_score=combined_score,
            sources_json=_json.dumps(sources_data, default=str) if sources_data else None,
            market_context_json=_json.dumps(market_ctx, default=str) if market_ctx else None,
        )
        session.add(snap)
        session.commit()
        session.close()
        logger.info("Trade snapshot saved for %s %s @ %.2f", side, symbol, price)
    except Exception as e:
        logger.warning("Trade snapshot capture failed for %s: %s", symbol, e)


def fetch_intraday_candles_for_today(symbol):
    """
    Fetch today's fresh intraday candles from IntradayCandle table.
    Returns a pandas DataFrame with OHLCV columns, or None if no data available.
    
    These are real-time 1-minute candles from the trading session (09:15-15:30).
    """
    try:
        from datetime import datetime
        from db_manager import get_db, IntradayCandle
        import pandas as pd
        
        db = get_db()
        if not db or not db.Session:
            return None
        
        session = db.Session()
        today_str = datetime.now().date().isoformat()  # "2026-04-11"
        
        # Query today's candles for this symbol
        candles = session.query(IntradayCandle).filter(
            IntradayCandle.symbol == symbol,
            IntradayCandle.trading_date == today_str,
            IntradayCandle.interval == "1min"  # Fetch 1-min candles for precision
        ).order_by(IntradayCandle.time).all()
        
        session.close()
        
        if not candles or len(candles) < 2:
            # Not enough data for analysis
            return None
        
        # Convert to DataFrame format compatible with ML model
        data = []
        for candle in candles:
            data.append({
                "datetime": f"{candle.trading_date} {candle.time}",
                "timestamp": int(datetime.fromisoformat(f"{candle.trading_date}T{candle.time}").timestamp()),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            })
        
        df = pd.DataFrame(data)
        logger.debug(f"↷ {symbol}: Fetched {len(df)} fresh intraday candles for today")
        return df
        
    except Exception as e:
        logger.debug(f"Could not fetch intraday candles for {symbol}: {e}")
        return None


def get_prediction(symbol, intraday_candles=None):
    """
    Get a combined prediction using ALL available knowledge:
      1. ML model (technical indicators from historical data or fresh intraday candles)
      2. News sentiment (financial headlines from multiple sources)
      3. Market context (Nifty trend, sector strength, multi-TF, volatility)
      4. Trading costs (only signal profitable trades)

    Args:
        symbol: Stock symbol
        intraday_candles: Optional DataFrame of fresh intraday candles (for portfolio analysis)
                         If provided, will be prioritized over historical data

    Final signal is a weighted consensus of all sources.
    """
    if symbol not in _predictors:
        # Try loading persisted model first
        if not _load_predictor(symbol):
            train_result = train_model(symbol)
            if not train_result.get("success"):
                return {
                    "symbol": symbol,
                    "signal": "HOLD",
                    "confidence": 0,
                    "reason": train_result.get("message", "Training failed"),
                }

    # ── Prioritize fresh intraday candles if available (portfolio analysis) ──
    if intraday_candles is not None and not intraday_candles.empty and len(intraday_candles) > 2:
        df = intraday_candles
        logger.debug(f"↷ {symbol}: Using {len(df)} fresh intraday candles for prediction")
    else:
        df = fetch_historical(symbol)
        if intraday_candles is not None:
            logger.debug(f"↷ {symbol}: Intraday candles insufficient ({len(intraday_candles) if intraday_candles is not None else 0}), falling back to historical data")
    
    if df.empty:
        return {"symbol": symbol, "signal": "HOLD", "confidence": 0, "reason": "No data"}

    # ── Source 1: ML / Technical Analysis ────────────────────────────────
    ml_prediction = _predictors[symbol].predict(df)

    ml_signal = ml_prediction["signal"]
    ml_confidence = ml_prediction.get("confidence", 0)
    # Convert signal to numeric score: BUY=+1, SELL=-1, HOLD=0
    ml_score = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0}.get(ml_signal, 0.0) * ml_confidence

    # ── Source 1b: Long-term Trend Analysis (5-year history) ──────────────
    long_term_trend = analyze_long_term_trend(symbol)
    long_term_score = 0.0
    if long_term_trend:
        trend_pct = long_term_trend["trend_pct"]
        support_dist = long_term_trend["distance_from_support_pct"]
        resistance_dist = long_term_trend["distance_from_resistance_pct"]
        
        # Factors:
        # 1. Long-term uptrend is bullish
        if trend_pct > 20:
            long_term_score += 0.3
        elif trend_pct < -20:
            long_term_score -= 0.3
        
        # 2. Price near support is less risky (slightly bullish)
        if 0 < support_dist < 5:
            long_term_score += 0.15
        
        # 3. Price near resistance might reverse (slightly bearish)
        if -5 < resistance_dist < 0:
            long_term_score -= 0.15

    # ── Source 2: News Sentiment ────────────────────────────────────────
    try:
        news = news_sentiment.get_news_sentiment(symbol)
        news_score = news.avg_score  # -1 to +1
        news_conf = news.confidence
        news_data = news.to_dict()
    except Exception as e:
        logger.warning("News sentiment failed for %s: %s", symbol, e)
        news_score = 0.0
        news_conf = 0.0
        news_data = None

    # ── Source 3: Market Context ────────────────────────────────────────
    try:
        groww = _get_groww()
        ctx = market_context.analyze_market_context(groww, symbol)
        ctx_score = ctx["context_score"]  # -1 to +1
    except Exception as e:
        logger.warning("Market context failed for %s: %s", symbol, e)
        ctx = {"market_signal": "NEUTRAL", "sector_signal": "NEUTRAL",
               "multi_tf_aligned": False, "volatility_regime": "NORMAL", "context_score": 0}
        ctx_score = 0.0

    # ── Source 4: Cost Analysis ─────────────────────────────────────────
    # Override price with live Groww LTP (DB candle may be stale after market close)
    try:
        live_price = fetch_live_price(symbol)
        if live_price and live_price > 0:
            price = live_price
            ml_prediction.setdefault("indicators", {})["price"] = round(live_price, 2)
        else:
            price = ml_prediction.get("indicators", {}).get("price") or float(df["close"].iloc[-1])
    except Exception:
        price = ml_prediction.get("indicators", {}).get("price") or float(df["close"].iloc[-1])

    try:
        # Use available capital if in trader mode, otherwise use high default limit
        try:
            from fno_trader import get_available_capital as get_trader_capital
            available = get_trader_capital()
            trade_budget = available if available > 0 else MAX_TRADE_VALUE
        except:
            trade_budget = MAX_TRADE_VALUE
        trade_budget = _apply_paper_trade_amount_limit(trade_budget)
        qty = int(trade_budget / price) if price > 0 else 1
        cost_info = costs.min_profitable_move(price, qty, product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)
        cost_data = {
            "breakeven_price": cost_info["breakeven_sell_price"],
            "breakeven_pct": cost_info["min_move_pct"],
            "total_charges": cost_info["costs"]["total"],
            "charges_pct": cost_info["costs"]["total_pct"],
        }
    except Exception:
        cost_data = None

    # ── Weighted Consensus ──────────────────────────────────────────────
    # Weights loaded from DB (tunable without code changes)
    try:
        from db_manager import get_config
        W_ML = float(get_config("prediction.weight.ml", default="0.40"))
        W_TREND = float(get_config("prediction.weight.trend", default="0.15"))
        W_NEWS = float(get_config("prediction.weight.news", default="0.20"))
        W_CTX = float(get_config("prediction.weight.context", default="0.25"))
    except Exception:
        W_ML, W_TREND, W_NEWS, W_CTX = 0.40, 0.15, 0.20, 0.25

    combined_score = (W_ML * ml_score) + (W_TREND * long_term_score) + (W_NEWS * news_score) + (W_CTX * ctx_score)

    # Combined confidence: weighted average of individual confidences
    combined_confidence = (W_ML * ml_confidence) + (W_TREND * min(abs(long_term_score), 1.0)) + (W_NEWS * news_conf) + (W_CTX * abs(ctx_score))
    combined_confidence = min(combined_confidence, 1.0)

    # Determine final signal
    if combined_score > 0.15:
        final_signal = "BUY"
    elif combined_score < -0.15:
        final_signal = "SELL"
    else:
        final_signal = "HOLD"

    # Volatility dampening: reduce confidence in high-vol regime
    if ctx.get("volatility_regime") == "HIGH":
        combined_confidence *= 0.8

    # Multi-timeframe bonus: boost confidence when timeframes agree
    if ctx.get("multi_tf_aligned") and final_signal != "HOLD":
        combined_confidence = min(combined_confidence * 1.15, 1.0)

    # Build detailed reason
    reason_parts = []
    if ml_prediction.get("reason"):
        reason_parts.append(ml_prediction["reason"])
    if long_term_trend:
        trend = long_term_trend["trend_pct"]
        if abs(trend) >= 20:
            direction = "↑↑ Strong uptrend" if trend > 0 else "↓↓ Strong downtrend"
            reason_parts.append(f"5-Year: {direction} ({trend:+.1f}%)")
        else:
            reason_parts.append(f"5-Year trend: {trend:+.1f}%")
        
        # Add support/resistance context
        support_dist = long_term_trend["distance_from_support_pct"]
        if support_dist < 5:
            reason_parts.append(f"Near 1Y support ({support_dist:.1f}%)")
    
    if news_data and news_data.get("signal") != "NEUTRAL":
        reason_parts.append(f"News: {news_data['signal']} ({news_data['total_articles']} articles)")
    if ctx.get("market_signal") != "NEUTRAL":
        reason_parts.append(f"Market: {ctx['market_signal']}")
    if ctx.get("sector") != "UNKNOWN" and ctx.get("sector_signal") != "NEUTRAL":
        reason_parts.append(f"{ctx['sector']}: {ctx['sector_signal']}")
    if ctx.get("multi_tf_aligned"):
        reason_parts.append("Multi-TF aligned")
    if ctx.get("volatility_regime") != "NORMAL":
        reason_parts.append(f"Volatility: {ctx['volatility_regime']}")

    prediction = {
        "symbol": symbol,
        "signal": final_signal,
        "confidence": round(combined_confidence, 4),
        "combined_score": round(combined_score, 4),
        "indicators": ml_prediction.get("indicators", {}),
        "reason": "; ".join(reason_parts) if reason_parts else "Consensus hold",
        "costs": cost_data,
        # 5-Year trend analysis
        "long_term_trend": long_term_trend,
        # Source breakdown for transparency
        "sources": {
            "ml": {"signal": ml_signal, "confidence": round(ml_confidence, 4), "score": round(ml_score, 4)},
            "news": news_data,
            "market_context": ctx,
            "long_term": {"score": round(long_term_score, 4)},
        },
    }
    return prediction


def scan_watchlist():
    """Run predictions for every symbol in the watchlist."""
    results = []
    for symbol in WATCHLIST:
        try:
            pred = get_prediction(symbol)
            results.append(pred)
        except Exception as e:
            logger.warning("Prediction failed for %s: %s", symbol, e)
            # Still try to get a valid price for display
            fallback_price = 0
            try:
                fallback_price = fetch_live_price(symbol) or 0
            except Exception:
                pass
            if not fallback_price:
                try:
                    _df = fetch_historical(symbol)
                    if not _df.empty:
                        fallback_price = float(_df["close"].iloc[-1])
                except Exception:
                    pass
            results.append({
                "symbol": symbol,
                "signal": "HOLD",
                "confidence": 0,
                "reason": f"Error: {e}",
                "indicators": {"price": round(fallback_price, 2)},
            })
    return results


# ── Paper Trading ────────────────────────────────────────────────────────────

def is_paper_mode():
    """Check if paper trading mode is active."""
    try:
        from db_manager import get_config
        return get_config("paper_trading", "false").lower() == "true"
    except Exception:
        return False


def get_paper_trade_amount_limit():
    """Optional rupee cap for each auto paper trade. Zero keeps current sizing."""
    try:
        from db_manager import get_config
        raw = get_config("paper_trade_amount_limit", "0")
        return max(float(raw or 0), 0.0)
    except Exception:
        return 0.0


def _apply_paper_trade_amount_limit(trade_budget):
    """Clamp auto paper-trade sizing without affecting real-trade behavior."""
    if not is_paper_mode():
        return trade_budget

    amount_limit = get_paper_trade_amount_limit()
    if amount_limit <= 0:
        return trade_budget

    if trade_budget <= 0:
        return amount_limit

    return min(trade_budget, amount_limit)


def _paper_trade(symbol, side, quantity, price, segment="CASH", product="CNC", reason="", prediction=None):
    """
    Record a simulated paper trade using the unified paper_trader system.
    Integrates with paper_trader.py for trailing stop management.
    ALSO syncs to trade_journal for complete trade history.
    """
    from paper_trader import PaperTradeTracker
    import trade_journal
    
    # Initialize paper trader
    tracker = PaperTradeTracker()
    
    # Get prediction info for pre-trade reasoning
    prediction_data = None
    if prediction:
        prediction_data = {
            'ml': prediction.get('sources', {}).get('ml', {}),
            'news': prediction.get('sources', {}).get('news', {}),
            'market_context': prediction.get('sources', {}).get('market_context', {}),
            'combined_score': prediction.get('combined_score'),
            'reason': prediction.get('reason', ''),
        }
    
    # Record trade with trailing stop initialization
    trade = tracker.record_entry(
        symbol=symbol,
        signal=side,
        confidence=prediction.get('confidence', 0) if prediction else 0,
        entry_price=price,
        quantity=quantity,
        prediction=prediction_data,
        exit_reason="new_prediction" if prediction else "manual"
    )
    
    # Calculate charges
    charges = 0
    try:
        charge_info = costs.calculate_costs(price, quantity, sell_price=price,
                                            product=product, exchange=DEFAULT_EXCHANGE)
        charges = round(charge_info.total, 2)
    except Exception:
        pass

    try:
        db = get_db()
        session = db.Session()
        from db_manager import PaperTrade
        session.add(PaperTrade(
            symbol=symbol, side=side, quantity=quantity, price=price,
            segment=segment, product=product, paper_order_id=trade['id'],
            charges=charges, remark=reason[:500] if reason else None,
        ))
        session.commit()
        session.close()
    except Exception as e:
        logger.warning("Paper trade DB write failed: %s", e)

    entry = {
        "time": datetime.now().isoformat(),
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "order_id": trade['id'],
        "trade_id": trade['id'],  # Link to paper_trader
        "status": "PAPER_FILLED",
        "remark": "Paper trade — not executed on exchange",
        "est_charges": charges,
        "paper": True,
        "cost_coverage_price": trade['cost_coverage_price'],
        "trailing_stop": None,  # Will be set when costs covered
    }
    _trade_log.append(entry)
    _persist_trade_log_entry(entry)

    # 🔥 NEW: SYNC TO TRADE JOURNAL — so new paper trades appear in the journal!
    try:
        # Build a safe prediction structure for the journal
        safe_prediction = {
            "sources": {
                "ml": prediction.get('sources', {}).get('ml', {}) if prediction else {},
                "news": prediction.get('sources', {}).get('news', {}) if prediction else {},
                "market_context": prediction.get('sources', {}).get('market_context', {}) if prediction else {},
            },
            "costs": prediction.get('costs', {}) if prediction else {},
            "indicators": prediction.get('indicators', {}) if prediction else {},
            "confidence": prediction.get('confidence', 0) if prediction else 0,
            "combined_score": prediction.get('combined_score', 0) if prediction else 0,
            "reason": prediction.get('reason', 'Paper trade') if prediction else 'Paper trade',
        }
        
        journal_entry = trade_journal.create_pre_trade_report(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=price,
            prediction=safe_prediction,
            trigger="auto",
            is_paper=True,
            trade_id=trade["id"],
            entry_time=trade.get("entry_time"),
        )
        logger.info(f"✓ Synced paper trade {trade['id']} to trade journal as {journal_entry.get('trade_id')}")
    except Exception as e:
        logger.warning(f"Failed to sync paper trade to journal: {e}")

    # Telegram alert for paper trade
    try:
        import telegram_alerts
        if telegram_alerts.is_enabled():
            telegram_alerts.alert_trade_executed(symbol, side, quantity, price,
                                                 order_id=trade['id'], charges=charges,
                                                 paper=True, reason=reason)
    except Exception:
        pass

    # Capture full trade snapshot for chart replay
    try:
        _capture_trade_snapshot(symbol, side, price, quantity, segment,
                                paper_order_id=trade['id'], prediction=prediction,
                                reason=reason)
    except Exception:
        pass

    return entry


# ── Order execution ──────────────────────────────────────────────────────────

def place_buy(symbol, quantity=None, price=None, reason="", prediction=None):
    """Place a BUY order via Groww API (or paper trade if paper mode active)."""
    if price is None:
        price = fetch_live_price(symbol)
    if quantity is None:
        # Calculate quantity based on available capital
        # For paper trading: use 10% of capital per trade to allow multiple concurrent positions
        try:
            from fno_trader import get_available_capital as get_trader_capital
            available = get_trader_capital()
            if available > 0:
                # In F&O trading: use 10% of available capital per trade
                trade_budget = available * 0.10
            else:
                # Fall back to higher limit if no F&O capital
                trade_budget = MAX_TRADE_VALUE * 0.05  # Use 5% of max to keep it reasonable
        except:
            # Paper trading mode: allocate reasonable per-trade budget
            trade_budget = MAX_TRADE_VALUE * 0.05  # 5% of max value = ~₹50M per trade

        trade_budget = _apply_paper_trade_amount_limit(trade_budget)
        
        quantity = int(trade_budget / price) if price > 0 else 1
        # Cap at MAX_TRADE_QUANTITY (1000 shares) per trade
        quantity = min(quantity, MAX_TRADE_QUANTITY)
    
    quantity = max(1, quantity)

    # Paper trading intercept
    if is_paper_mode():
        return _paper_trade(symbol, "BUY", quantity, price, reason=reason, prediction=prediction)

    groww = _get_groww()
    quantity = max(1, quantity)

    order_params = dict(
        trading_symbol=symbol,
        quantity=quantity,
        validity=DEFAULT_VALIDITY,
        exchange=DEFAULT_EXCHANGE,
        segment=DEFAULT_SEGMENT,
        product=DEFAULT_PRODUCT,
        order_type="MARKET",
        transaction_type="BUY",
    )

    resp = groww.place_order(**order_params)

    # Calculate round-trip cost estimate
    cost_info = costs.min_profitable_move(price, quantity, product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)

    entry = {
        "time": datetime.now().isoformat(),
        "symbol": symbol,
        "side": "BUY",
        "quantity": quantity,
        "price": price,
        "order_id": resp.get("groww_order_id"),
        "status": resp.get("order_status"),
        "remark": resp.get("remark"),
        "breakeven_price": cost_info["breakeven_sell_price"],
        "est_charges": cost_info["costs"]["total"],
    }
    _trade_log.append(entry)
    _persist_trade_log_entry(entry)

    # Create pre-trade journal report if prediction context is available
    prediction = entry.get("_prediction")
    if prediction:
        jr = trade_journal.create_pre_trade_report(
            symbol=symbol, side="BUY", quantity=quantity,
            entry_price=price, prediction=prediction, trigger="auto",
        )
        entry["trade_id"] = jr["trade_id"]

    # Telegram alert for real trade
    try:
        import telegram_alerts
        if telegram_alerts.is_enabled():
            telegram_alerts.alert_trade_executed(symbol, "BUY", quantity, price,
                                                 order_id=entry.get("order_id"),
                                                 charges=entry.get("est_charges", 0))
    except Exception:
        pass

    return entry


def place_sell(symbol, quantity=None, price=None, reason="", prediction=None):
    """Place a SELL order via Groww API (or paper trade if paper mode active)."""
    if price is None:
        price = fetch_live_price(symbol)
    if quantity is None:
        # Default to MAX_TRADE_QUANTITY, but could be overridden
        # For consistency with place_buy, use similar capital-based calculation
        quantity = MAX_TRADE_QUANTITY
    
    quantity = max(1, quantity)

    # Paper trading intercept
    if is_paper_mode():
        return _paper_trade(symbol, "SELL", quantity, price, reason=reason, prediction=prediction)

    groww = _get_groww()

    order_params = dict(
        trading_symbol=symbol,
        quantity=quantity,
        validity=DEFAULT_VALIDITY,
        exchange=DEFAULT_EXCHANGE,
        segment=DEFAULT_SEGMENT,
        product=DEFAULT_PRODUCT,
        order_type="MARKET",
        transaction_type="SELL",
    )

    resp = groww.place_order(**order_params)

    # Estimate charges for this sell
    sell_costs = costs.calculate_costs(price, quantity, sell_price=price,
                                       product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)

    entry = {
        "time": datetime.now().isoformat(),
        "symbol": symbol,
        "side": "SELL",
        "quantity": quantity,
        "price": price,
        "order_id": resp.get("groww_order_id"),
        "status": resp.get("order_status"),
        "remark": resp.get("remark"),
        "est_charges": round(sell_costs.total, 2),
    }
    _trade_log.append(entry)
    _persist_trade_log_entry(entry)

    # Close matching open journal entry (if any)
    open_reports = trade_journal.get_open_reports()
    for jr in open_reports:
        if jr["symbol"] == symbol and jr["side"] == "BUY":
            trade_journal.close_trade_report(
                trade_id=jr["trade_id"], exit_price=price,
                exit_reason="signal_reversed",
            )
            entry["closed_trade_id"] = jr["trade_id"]
            break

    return entry


# ── Smart order helpers (GTT stop-loss / target) ────────────────────────────

def place_gtt_stop_loss(symbol, trigger_price, quantity, order_price=None):
    """Create a GTT stop-loss order."""
    groww = _get_groww()
    ref_id = f"sl-{symbol[:8]}-{int(time.time())}"[:20]

    order_dict = {
        "order_type": "SL_M" if order_price is None else "SL",
        "transaction_type": "SELL",
    }
    if order_price is not None:
        order_dict["price"] = str(order_price)

    return groww.create_smart_order(
        smart_order_type="GTT",
        reference_id=ref_id,
        segment=DEFAULT_SEGMENT,
        trading_symbol=symbol,
        quantity=quantity,
        product_type=DEFAULT_PRODUCT,
        exchange=DEFAULT_EXCHANGE,
        duration=DEFAULT_VALIDITY,
        trigger_price=str(trigger_price),
        trigger_direction="DOWN",
        order=order_dict,
    )


# ── Trailing Stop Monitor ───────────────────────────────────────────────────

def monitor_and_update_trailing_stops():
    """
    Monitor all open trades and update their trailing stops.
    Should be called periodically (e.g., every 1-5 minutes) to check current prices.
    Returns a summary of actions taken.
    """
    from paper_trader import PaperTradeTracker
    
    tracker = PaperTradeTracker()
    open_trades = tracker.get_open_positions()
    
    if not open_trades:
        return {"monitored": 0, "closed": 0, "updated": 0}
    
    summary = {"monitored": len(open_trades), "closed": 0, "updated": 0, "events": []}
    
    # Monitor each open trade
    for trade in open_trades:
        symbol = trade['symbol']
        trade_id = trade['id']
        
        try:
            # Get current live price
            current_price = fetch_live_price(symbol)
            if not current_price:
                logger.debug(f"Could not fetch price for {symbol}")
                continue
            
            # Update trailing stop
            result = tracker.update_trailing_stop(trade_id, current_price)
            
            if result == 'closed':
                summary["closed"] += 1
                summary["events"].append({
                    "action": "CLOSED",
                    "symbol": symbol,
                    "price": current_price,
                    "reason": "trailing_stop_hit"
                })
                
                # Telegram alert for closed trade
                try:
                    import telegram_alerts
                    if telegram_alerts.is_enabled():
                        telegram_alerts.alert_trade_closed(symbol, trade['signal'], 
                                                          current_price, trade_id)
                except Exception:
                    pass
            
            elif result == 'costs_covered':
                summary["events"].append({
                    "action": "COSTS_COVERED",
                    "symbol": symbol,
                    "price": current_price,
                    "trailing_stop": current_price
                })
            
            elif result == 'trailing_updated':
                summary["updated"] += 1
            
        except Exception as e:
            logger.error(f"Error monitoring trade {trade_id}: {e}")
    
    return summary


# ── Auto-trade logic ────────────────────────────────────────────────────────

def auto_trade():
    """
    Full cycle: scan watchlist → place trades based on AI signals.
    Also monitors and updates trailing stops on open positions.
    Returns a summary of actions taken.

    SAFETY: Will not run until the user has reviewed their portfolio analysis.
    """
    if not _portfolio_reviewed:
        return {
            "timestamp": datetime.now().isoformat(),
            "actions": [],
            "predictions": [],
            "error": "PORTFOLIO_NOT_REVIEWED",
            "message": "You must review your portfolio analysis before auto-trading. "
                       "Go to the Portfolio Analysis tab, run the analysis, and click 'I've Reviewed — Unlock Trading'.",
        }

    # ── STEP 1: Monitor and update trailing stops on open positions ──
    trailing_stop_summary = monitor_and_update_trailing_stops()

    actions = []
    predictions = scan_watchlist()

    # Check current positions
    try:
        groww = _get_groww()
        positions_resp = groww.get_positions_for_user(segment=DEFAULT_SEGMENT)
        current_positions = positions_resp.get("positions", [])
    except Exception:
        current_positions = []

    open_symbols = {p["trading_symbol"] for p in current_positions if p.get("quantity", 0) > 0}

    for pred in predictions:
        symbol = pred["symbol"]
        signal = pred["signal"]
        confidence = pred.get("confidence", 0)

        # Skip low-confidence signals (lower threshold in paper mode to get more trades)
        min_conf = 0.40 if is_paper_mode() else CONFIDENCE_THRESHOLD
        if confidence < min_conf:
            actions.append({"symbol": symbol, "action": "SKIP", "reason": f"Low confidence ({confidence})"})
            continue

        if signal == "BUY" and symbol not in open_symbols and len(open_symbols) < MAX_POSITIONS:
            try:
                price = fetch_live_price(symbol)

                # Cost-aware gate: predicted confidence must outweigh breakeven cost
                # Use available capital if in trader mode, otherwise use high default limit
                try:
                    from fno_trader import get_available_capital as get_trader_capital
                    available = get_trader_capital()
                    trade_budget = available if available > 0 else MAX_TRADE_VALUE
                except:
                    trade_budget = MAX_TRADE_VALUE
                trade_budget = _apply_paper_trade_amount_limit(trade_budget)
                qty = int(trade_budget / price) if price > 0 else 1
                cost_info = costs.min_profitable_move(price, qty, product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)
                breakeven_pct = cost_info["min_move_pct"]
                # Require confidence * target to exceed at least the breakeven %
                expected_return_pct = confidence * TARGET_PCT
                if expected_return_pct < breakeven_pct:
                    actions.append({
                        "symbol": symbol, "action": "SKIP",
                        "reason": f"Cost-gated: expected {expected_return_pct:.2f}% < breakeven {breakeven_pct:.2f}%",
                    })
                    continue

                journal_report = None
                if not is_paper_mode():
                    # Real trades still create the journal entry before order placement.
                    journal_report = trade_journal.create_pre_trade_report(
                        symbol=symbol, side="BUY", quantity=qty,
                        entry_price=price, prediction=pred, trigger="auto",
                    )

                # Pass the calculated quantity to place_buy to ensure consistent qty
                trade = place_buy(symbol, quantity=qty, price=price,
                                  reason=pred.get("reason", ""),
                                  prediction=pred)

                # Set stop-loss GTT
                sl_price = round(price * (1 - STOP_LOSS_PCT / 100), 2)
                try:
                    place_gtt_stop_loss(symbol, sl_price, trade["quantity"])
                except Exception as e:
                    logger.warning("GTT SL failed for %s: %s", symbol, e)

                open_symbols.add(symbol)
                trade_trade_id = trade.get("trade_id") or trade.get("order_id")
                if journal_report is not None:
                    trade["trade_id"] = journal_report["trade_id"]
                    trade_trade_id = journal_report["trade_id"]
                actions.append({"symbol": symbol, "action": "BUY", "trade": trade, "trade_id": trade_trade_id})
            except Exception as e:
                actions.append({"symbol": symbol, "action": "ERROR", "reason": str(e)})

        elif signal == "SELL" and symbol in open_symbols:
            try:
                pos = next((p for p in current_positions if p["trading_symbol"] == symbol), None)
                qty = pos["quantity"] if pos else MAX_TRADE_QUANTITY
                sell_price = fetch_live_price(symbol)

                # Close the matching open journal entry with post-trade analysis
                open_reports = trade_journal.get_open_reports()
                closed_trade_id = None
                for jr in open_reports:
                    if jr["symbol"] == symbol and jr["side"] == "BUY":
                        trade_journal.close_trade_report(
                            trade_id=jr["trade_id"], exit_price=sell_price,
                            exit_reason="signal_reversed",
                            current_indicators=pred.get("indicators"),
                        )
                        closed_trade_id = jr["trade_id"]
                        break

                trade = place_sell(symbol, quantity=qty, price=sell_price,
                                   reason=pred.get("reason", ""),
                                   prediction=pred)
                open_symbols.discard(symbol)
                action_entry = {"symbol": symbol, "action": "SELL", "trade": trade}
                if closed_trade_id:
                    action_entry["closed_trade_id"] = closed_trade_id
                actions.append(action_entry)
            except Exception as e:
                actions.append({"symbol": symbol, "action": "ERROR", "reason": str(e)})
        else:
            actions.append({"symbol": symbol, "action": "HOLD", "signal": signal, "confidence": confidence})

    return {"timestamp": datetime.now().isoformat(), "actions": actions, "predictions": predictions}


# ── Portfolio helpers ────────────────────────────────────────────────────────

def get_holdings():
    groww = _get_groww()
    return groww.get_holdings_for_user()


def get_positions():
    groww = _get_groww()
    return groww.get_positions_for_user()


def get_order_list():
    groww = _get_groww()
    return groww.get_order_list()


def get_margin():
    groww = _get_groww()
    return groww.get_available_margin_details()


def get_trade_log():
    _load_trade_log()
    return list(_trade_log)


# ── Portfolio Analysis (read-only) ───────────────────────────────────────────

_portfolio_reviewed = False  # Safety gate: must review before auto-trading


def _load_portfolio_reviewed():
    """Load portfolio_reviewed flag from DB."""
    global _portfolio_reviewed
    try:
        from db_manager import get_config
        val = get_config("portfolio_reviewed")
        if val == "true":
            _portfolio_reviewed = True
    except Exception:
        pass


def analyze_portfolio():
    """
    Run full AI analysis on every holding/position in the Groww portfolio.
    No trades are placed — purely read-only.
    Gracefully handles errors by returning empty analysis.
    
    Enhanced with fresh intraday candles for accurate daily predictions.
    """
    try:
        import portfolio_analyzer
        groww = _get_groww()
        logger.info("analyze_portfolio got groww: %s (is None: %s)", type(groww).__name__ if groww else "None", groww is None)
        
        if groww is None:
            logger.warning("Groww API not available for portfolio analysis")
            return {
                "error": "Groww API not available",
                "holdings": [],
                "positions": [],
                "portfolio": [],
                "summary": {}
            }
        
        # Create a wrapper function that fetches intraday candles for each symbol
        def get_prediction_with_fresh_candles(symbol):
            """Get prediction using fresh intraday candles if available."""
            intraday_df = fetch_intraday_candles_for_today(symbol)
            return get_prediction(symbol, intraday_candles=intraday_df)
        
        logger.info("Passing groww to portfolio_analyzer: %s", type(groww).__name__)
        result = portfolio_analyzer.analyze_portfolio(groww, get_prediction_with_fresh_candles, fetch_live_price)
        
        if result is None:
            logger.warning("Portfolio analysis returned None")
            return {
                "error": "Portfolio analysis returned no data",
                "holdings": [],
                "positions": [],
                "portfolio": [],
                "summary": {}
            }
        
        return result
        
    except ImportError as ie:
        logger.error(f"Portfolio analyzer import failed: {ie}")
        return {
            "error": "Portfolio analyzer module not found",
            "holdings": [],
            "positions": [],
            "portfolio": [],
            "summary": {}
        }
    except Exception as e:
        logger.error(f"Portfolio analysis error: {e}", exc_info=True)
        return {
            "error": "Portfolio analysis failed",
            "message": str(e),
            "holdings": [],
            "positions": [],
            "portfolio": [],
            "summary": {}
        }


def mark_portfolio_reviewed():
    """Mark that the user has reviewed the portfolio analysis."""
    global _portfolio_reviewed
    _portfolio_reviewed = True
    try:
        from db_manager import set_config
        set_config("portfolio_reviewed", "true")
    except Exception:
        pass
    return {"reviewed": True, "message": "Portfolio reviewed. Auto-trade is now unlocked."}


def is_portfolio_reviewed():
    _load_portfolio_reviewed()
    return _portfolio_reviewed
