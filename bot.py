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
# Cash GradientBoosting models live in their own directory, alongside
# models/xgb_cash/ (cash XGBoost) and models/xgb_backtester.joblib (F&O).
# Previously these sat loose in models/, which made "count the cash GBC
# models" a matter of globbing models/*.joblib and remembering to exclude
# the F&O artifact — fragile, and the source of an earlier miscount.
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models", "gbc_cash")
# Where they used to live. Read-only fallback so a model saved before the
# move still loads; nothing is written here any more.
_LEGACY_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")


def _load_predictor(symbol):
    """
    Try to load a persisted ML model from disk.

    Checks the current directory first, then the pre-move location, so a
    model that was never migrated still loads instead of silently
    triggering a retrain.
    """
    import joblib
    for base in (_MODELS_DIR, _LEGACY_MODELS_DIR):
        path = os.path.join(base, f"{symbol}.joblib")
        if os.path.exists(path):
            try:
                _predictors[symbol] = joblib.load(path)
                logger.debug(f"Loaded persisted model for {symbol} from {base}")
                return True
            except Exception as e:
                logger.debug(f"Failed to load model for {symbol} from {base}: {e}")
    return False


def _save_predictor(symbol):
    """
    Persist an ML model to disk, atomically.

    Temp-file + os.replace so an interrupted write can never leave a
    truncated .joblib behind — a corrupt model loads as garbage, whereas a
    missing one correctly triggers a retrain. Same reasoning as
    xgb_predictor.save_model().
    """
    import joblib
    import tempfile
    os.makedirs(_MODELS_DIR, exist_ok=True)
    path = os.path.join(_MODELS_DIR, f"{symbol}.joblib")
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=_MODELS_DIR, prefix=f".{symbol}_", suffix=".joblib")
        os.close(fd)
        joblib.dump(_predictors[symbol], tmp)
        os.replace(tmp, path)
        logger.debug(f"Saved model for {symbol}")
    except Exception as e:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
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

    Source: fyers_candles, read through CandleDatabase.get_fyers_candles_as_5min(),
    which resamples FYERS 5-second/1-minute data into 5-minute bars with naive-IST
    timestamps — the same cadence and timestamp representation the legacy Groww
    `candles` table provided, so feature engineering, labels and trained models
    are unaffected. See docs/FYERS_CANDLE_MIGRATION_PLAN.md.

    Returns:
        DataFrame with columns: timestamp, datetime, open, high, low, close, volume
    """
    days = days or PREDICTION_LOOKBACK_DAYS
    interval = interval or CANDLE_INTERVAL_MINUTES

    db = _get_db()

    if db:
        # Keep today's FYERS data current before reading it. Replaces the old
        # Groww sync_candles_from_api() call, which topped up the legacy table
        # this function no longer reads. Throttled and best-effort — without
        # it, the "today" branch below would happily serve stale bars and never
        # fall through to the live-API fallback.
        try:
            import fyers_historical_backfill
            fyers_historical_backfill.ensure_recent(symbol)
        except Exception as e:
            logger.debug(f"↷ {symbol}: FYERS freshness top-up skipped: {e}")

        # PRIORITY: Get today's data first (market still open, get latest 5-min candles)
        today = datetime.now().date()
        today_start = int(datetime.combine(today, datetime.min.time()).timestamp())
        today_df = db.get_fyers_candles_as_5min(symbol, days=1)  # Get today only

        if not today_df.empty and len(today_df) > 2:
            # We have enough today data, use it
            logger.debug(f"↷ {symbol}: Using {len(today_df)} candles from TODAY (prioritized over historical)")
            return today_df

        # FALLBACK: Use full lookback if today data is insufficient
        df = db.get_fyers_candles_as_5min(symbol, days=days)

        if not df.empty:
            logger.debug(f"↷ {symbol}: Fetched {len(df)} candles from DB (last: {df['datetime'].iloc[-1]})")
            return df
    
    # No Groww fallback. This previously dropped to Groww's live
    # get_historical_candle_data when the DB had nothing — which would mean
    # silently pricing the ML pipeline off the provider we've removed as a
    # market-data source. fyers_candles plus ensure_recent() above is now
    # the only path; an empty frame here means the symbol genuinely has no
    # FYERS data yet (not backfilled), which callers already handle by
    # returning a HOLD/no-data result rather than trading on nothing.
    logger.warning(
        "↷ %s: no fyers_candles data available — symbol may not be backfilled yet", symbol
    )
    return pd.DataFrame()


def fetch_live_price(symbol):
    """
    Fetch the last traded price for a symbol. FYERS only — no Groww fallback.

    Groww is deliberately not consulted here even on failure. A silent
    fallback would mean the system sometimes prices off a provider we've
    decided not to use for market data, with no way to tell from the
    outside which one produced a given number. Raising instead makes a
    FYERS outage visible rather than papered over — callers that must
    tolerate it (display endpoints) already wrap this in try/except, and
    the ones that must NOT trade on a bad price (place_buy/place_sell)
    already refuse to proceed when price <= 0.

    Every one of this function's ~30 callers — paper-trade entry/exit
    pricing, auto_trade sizing, portfolio display, telegram commands —
    migrates via this one function, no per-call-site changes.
    """
    from fyers_market_data_provider import FYERSMarketDataProvider
    return float(FYERSMarketDataProvider().get_ltp(symbol))


def fetch_quote(symbol):
    """
    Fetch full quote for a symbol. FYERS only — no Groww fallback.

    FYERS's raw shape nests everything under d[0]["v"] with its own key
    names (lp/open_price/prev_close_price/...). Rather than push that shape
    onto every caller, this normalises to the Groww-era key names those
    callers already read — `ltp`, `open`, `high`, `low`, `prev_close`,
    `volume` — so peer_analyzer, fundamental_analysis and the
    /api/quote/<symbol> frontend consumer keep working unchanged.

    FYERS also gives us fields Groww never did; they're added alongside
    rather than discarded:
        change, change_pct, bid, ask, spread, quote_time, fy_symbol

    Two Groww fields have NO FYERS equivalent and are therefore absent:
        avg_traded_volume, upper_circuit, lower_circuit
    fundamental_analysis.py used avg_traded_volume for volume-spike
    detection; it now degrades to "no spike detected" rather than silently
    computing a wrong ratio. See _fyers_quote_missing_fields below.
    """
    from fyers_market_data_provider import FYERSMarketDataProvider
    raw = FYERSMarketDataProvider().get_quote(symbol)
    v = raw.get("v", {}) or {}
    return {
        # ── Groww-compatible keys (existing consumers read these) ──
        "ltp": v.get("lp", 0),
        "open": v.get("open_price", 0),
        "high": v.get("high_price", 0),
        "low": v.get("low_price", 0),
        "prev_close": v.get("prev_close_price", 0),
        "volume": v.get("volume", 0),
        # ── FYERS extras, genuinely useful, absent from Groww ──
        "change": v.get("ch", 0),
        "change_pct": v.get("chp", 0),
        "bid": v.get("bid", 0),
        "ask": v.get("ask", 0),
        "spread": v.get("spread", 0),
        "quote_time": v.get("tt"),
        "fy_symbol": raw.get("n"),
        # ── Provenance, so a consumer can tell where this came from ──
        "provider": "FYERS",
    }


# Groww quote fields with no FYERS equivalent. Kept as an explicit list so
# a consumer that needs one of these fails loudly against a named gap
# rather than silently reading a 0 that looks like real data.
_FYERS_QUOTE_MISSING_FIELDS = ("avg_traded_volume", "upper_circuit", "lower_circuit")


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


# ── Cash XGBoost: an independent second model ────────────────────────────────
# Everything below is additive. The GradientBoosting path above is untouched:
# separate predictor cache, separate model directory, separate train/predict
# entry points. Both models see the same features and the same cost-aware
# labels (predictor.build_features / predictor.create_labels), so a
# GBC-vs-XGB comparison isolates the algorithm rather than the strategy.
#
# Data: 5-MINUTE FYERS bars, naive-IST. Both paths below emit 5-minute bars
# built from the same underlying ticks, but they read different tiers on
# purpose:
#
#   training  -> resampled from the '1' tier ONLY. One homogeneous source
#                across the whole history, exactly reproducible, no tier
#                boundary partway through the training window.
#   inference -> get_fyers_candles_as_5min(), which also reads '5S'. The '1'
#                tier is backfilled end-of-day and runs ~2 trading sessions
#                behind (measured: '1' ends 2026-08-14, '5S' ends 2026-08-18,
#                uniformly across all 68-69 symbols), so a 1-minute-only read
#                would serve live signals off bars several days stale.
#
# Splitting them is safe because the two are bit-identical wherever they
# overlap - verified over 92,345 bars of RELIANCE: zero difference in OHLC
# AND volume. The property that matters (train and serve see the same BAR
# WIDTH) still holds; only which tier fills the newest bars differs.
#
# Why 5-minute rather than the native 1-minute this used to train on:
# create_labels(forward_periods=5) is a 5-BAR horizon, i.e. 5 minutes on
# 1-minute bars - a window in which price almost never clears the cost-aware
# breakeven threshold. Measured over 5 liquid names, that left a median of
# 165 usable BUY/SELL examples in 91k rows (0.18%). At 5-minute bars the same
# 5 periods become 25 minutes, and the median rises to 1,303 examples (1.41%)
# on full history - ~8x the training signal.

_xgb_predictors = {}   # symbol -> XGBPricePredictor

# How much history to train on. 0 / unset = FULL history (the default):
# ~843k 1-minute rows per symbol from 2017-07-03, resampling to ~168.8k
# 5-minute bars. Measured at ~8.5s and ~1.4GB peak RSS per symbol, so a
# 73-symbol retrain is ~10.3 minutes.
XGB_TRAIN_DAYS = int(os.getenv("XGB_TRAIN_DAYS", "0")) or None

# open/high/low/close/volume aggregation for 1-minute -> 5-minute.
_XGB_RESAMPLE = {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}


def fetch_5min_for_training(symbol, days=None):
    """
    5-minute bars resampled from the NATIVE 1-minute tier only.

    Deliberately does not go through get_fyers_candles_as_5min(): that reader
    unions '5S' and '1', and for training we want a single uniform source over
    the full history rather than one that switches tier for the most recent
    ~25 trading days. Nothing is written back - fyers_candles keeps storing
    1-minute rows exactly as before; the 5-minute bars exist only in memory.

    FYERS only - an empty frame means the symbol genuinely has no 1-minute
    data, never a silent fall back to another provider or resolution.
    """
    db = _get_db()
    if db is None:
        logger.warning("↷ %s: database unavailable for training fetch", symbol)
        return pd.DataFrame()

    one = db.get_fyers_1min(symbol, days=days if days is not None else XGB_TRAIN_DAYS)
    if one.empty:
        return pd.DataFrame()

    out = (
        one.set_index("datetime")
           .resample("5min")
           .agg(_XGB_RESAMPLE)
           .dropna(subset=["open"])       # never invent a bar for an empty bucket
           .reset_index()
    )
    if out.empty:
        return pd.DataFrame()
    out["timestamp"] = out["datetime"].astype("int64") // 10**9
    return out[["timestamp", "datetime", "open", "high", "low", "close", "volume"]]


def fetch_5min_for_inference(symbol, days=None):
    """
    5-minute bars for live prediction, including the '5S' tier so the newest
    session is present. See the note above on why this differs from the
    training reader.
    """
    db = _get_db()
    if db is None:
        logger.warning("↷ %s: database unavailable for inference fetch", symbol)
        return pd.DataFrame()
    return db.get_fyers_candles_as_5min(
        symbol, days=days if days is not None else XGB_PREDICT_DAYS
    )


def train_xgb_model(symbol, days=None):
    """
    Train the cash XGBoost model for one symbol on 5-minute bars resampled
    from native 1-minute data. Does not touch the GradientBoosting model or
    its artifacts.
    """
    import xgb_predictor

    df = fetch_5min_for_training(symbol, days=days)
    if df.empty:
        return {"success": False, "symbol": symbol,
                "message": f"No 1-minute FYERS data to resample for {symbol}"}

    predictor = xgb_predictor.XGBPricePredictor()
    result = predictor.train(df)
    if result.get("success"):
        _xgb_predictors[symbol] = predictor
        xgb_predictor.save_model(symbol, predictor)
        result["rows"] = len(df)
        result["range"] = f"{df['datetime'].iloc[0]} to {df['datetime'].iloc[-1]}"
    result["symbol"] = symbol
    result["model_source"] = xgb_predictor.MODEL_SOURCE_XGB
    return result


def _get_xgb_predictor(symbol, allow_train=True):
    """
    Load-or-train the cash XGB model for a symbol; None if unavailable.

    Mirrors the GradientBoosting path in get_prediction(), which loads a
    persisted model and trains one on demand if absent — so a newly added
    stock gets an XGB model automatically on first use rather than staying
    permanently signal-less until someone runs a manual batch job.
    """
    import xgb_predictor
    if symbol in _xgb_predictors:
        return _xgb_predictors[symbol]

    p = xgb_predictor.load_model(symbol)
    if p is not None:
        _xgb_predictors[symbol] = p
        return p

    if not allow_train:
        return None

    result = train_xgb_model(symbol)
    if result.get("success"):
        return _xgb_predictors.get(symbol)
    logger.debug("XGB train-on-demand failed for %s: %s", symbol, result.get("message"))
    return None


def get_prediction_xgb(symbol):
    """
    Cash XGBoost signal for a symbol — the independent sibling of
    get_prediction(). Same BUY/SELL/HOLD vocabulary and the same
    confidence semantics, so downstream consumers need no special-casing;
    only `model_source` distinguishes it.

    Returns HOLD with a reason (never raises) when the model or its data is
    unavailable, matching get_prediction()'s failure convention.

    Runs through get_prediction() rather than returning the raw model output,
    so XGBoost receives the SAME four-source weighted consensus as
    GradientBoosting — news sentiment, market context, 5-year trend and the
    cost gate, at the same DB-configured weights. Previously this returned
    predictor.predict() directly, which meant XGBoost decided on technicals
    alone (Source 1, 40% of the blend) while GradientBoosting used all four.
    That difference, not the algorithm, would have dominated any comparison
    between them.
    """
    import xgb_predictor

    predictor = _get_xgb_predictor(symbol)
    if predictor is None:
        return {"symbol": symbol, "signal": "HOLD", "confidence": 0,
                "reason": "XGB model not trained for this symbol",
                "model_source": xgb_predictor.MODEL_SOURCE_XGB}

    df = fetch_5min_for_inference(symbol, days=XGB_PREDICT_DAYS)
    if df.empty:
        return {"symbol": symbol, "signal": "HOLD", "confidence": 0,
                "reason": "No 5-minute FYERS data",
                "model_source": xgb_predictor.MODEL_SOURCE_XGB}

    return get_prediction(
        symbol,
        ml_predictor=predictor,
        ml_df=df,
        model_source=xgb_predictor.MODEL_SOURCE_XGB,
    )


# Inference needs only enough bars for the longest rolling window in
# build_features (sma_50 etc.) plus headroom — not the whole training span.
XGB_PREDICT_DAYS = int(os.getenv("XGB_PREDICT_DAYS", "10"))

# Whether cash XGBoost signals may place trades. Default OFF: the models
# train and can be inspected via get_prediction_xgb() / scan_watchlist_xgb(),
# but auto_trade ignores them until a GBC-vs-XGB backtest exists. Flip with
# XGB_LIVE_TRADING=true once that comparison is available.
XGB_LIVE_TRADING = os.getenv("XGB_LIVE_TRADING", "false").strip().lower() in ("1", "true", "yes")


def scan_watchlist_xgb():
    """
    Cash XGBoost predictions for the whole watchlist — the independent
    sibling of scan_watchlist().

    Kept as a separate function rather than folded into scan_watchlist() so
    the existing GradientBoosting summary (Total Scanned / Buy / Sell / Hold)
    and every current consumer of scan_watchlist() keep seeing exactly what
    they saw before. Parallelised the same way, for the same reason.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    symbols = get_active_watchlist()
    if not symbols:
        return []

    out = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(get_prediction_xgb, s): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                out[sym] = fut.result()
            except Exception as e:
                logger.warning("XGB prediction failed for %s: %s", sym, e)
    return [out[s] for s in symbols if s in out]


# Lookback for analyze_long_term_trend(). fyers_candles daily reaches back to
# 1997, so this MUST be bounded — the function reports a "5-year" trend and
# derives it from prices[0] vs prices[-1].
LTT_YEARS = int(os.getenv("LTT_YEARS", "5"))


def analyze_long_term_trend(symbol, as_of=None):
    """
    Analyze 5-year historical price trend from database.
    Returns metrics about long-term price behavior.

    as_of: optional date/datetime ceiling for point-in-time replay. Every
    metric below is derived from list POSITIONS (prices[0], prices[-1],
    prices[-250:]), so leaving the query unbounded would make a backtest of a
    past date read "the trend as of today" — the strongest possible look-ahead
    in a 15%-weighted source. None keeps the original live behaviour.
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
        
        # Fetch 5-year daily price history from fyers_candles.
        #
        # Was `SELECT ... FROM stock_prices`. That table stopped receiving data
        # on 2026-05-29 when _task_update_watchlist_prices was disabled during
        # the FYERS migration — the task's own docstring flags this exact
        # consequence and defers the repoint, which is what this is. The signal
        # feeds get_prediction()'s trend source at prediction.weight.trend=0.15,
        # so every live and paper decision was reading prices ~85 days old.
        #
        # WINDOW: explicitly bounded to LTT_YEARS. stock_prices happened to hold
        # 2020-01-02 onward (~6.4y); fyers_candles daily goes back to 1997, so an
        # unbounded query would silently turn "5-Year trend +82%" into a 29-year
        # figure and shift every downstream score. The bound also keeps the read
        # from growing without limit (CLAUDE.md standard 2).
        #
        # Shape is preserved exactly: (date, close, high, low, volume) ascending,
        # date as a real date — ts is TIMESTAMPTZ here, so it is converted to IST
        # and cast, matching what stock_prices.date returned. Callers below index
        # by position (prices[0], prices[-1], prices[-250:]), so ordering matters.
        _ceiling = as_of if as_of is not None else datetime.now()
        cursor.execute("""
            SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date AS date,
                   close, high, low, volume
            FROM fyers_candles
            WHERE symbol = %s
              AND resolution = 'D'
              AND ts <= %s
              AND ts >= %s
            ORDER BY ts ASC
        """, (symbol, _ceiling, _ceiling - timedelta(days=365 * LTT_YEARS)))
        
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
    session = None
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
        logger.info("Trade snapshot saved for %s %s @ %.2f", side, symbol, price)
    except Exception as e:
        logger.warning("Trade snapshot capture failed for %s: %s", symbol, e)
        # Clear the aborted transaction — this runs on long-lived scheduler
        # threads that reuse the same scoped session for every later trade.
        if session is not None:
            try:
                session.rollback()
            except Exception:
                logger.debug("Snapshot rollback failed", exc_info=True)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.debug("Snapshot session close failed", exc_info=True)


def fetch_intraday_candles_for_today(symbol):
    """
    Fetch today's fresh intraday candles from IntradayCandle table.
    Returns a pandas DataFrame with OHLCV columns, or None if no data available.
    
    These are real-time 1-minute candles from the trading session (09:15-15:30).
    """
    session = None
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
        session = None  # already returned to the pool; skip the finally

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
    finally:
        # Only set if the query raised before the close above.
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.debug("Intraday candle session close failed", exc_info=True)


def get_prediction(symbol, intraday_candles=None, ml_predictor=None, ml_df=None,
                   model_source=None):
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
        ml_predictor: Optional predictor supplying Source 1. Defaults to this
                      symbol's GradientBoosting model, so the existing call
                      signature and behaviour are unchanged.
        ml_df:        Optional DataFrame for that predictor. Needed because the
                      cash XGBoost model runs on native 1-minute candles while
                      GradientBoosting runs on 5-minute.
        model_source: Tag carried onto the result and, from there, onto the
                      trade record ('GradientBoosting' | 'XGBoost').

    Final signal is a weighted consensus of all sources.

    WHY ml_predictor exists: the ML model is only Source 1 of four, worth 40%
    of combined_score. Trend (15%), news (20%) and market context (25%) are
    blended here, NOT inside the model — predictor.build_features() is purely
    OHLCV. get_prediction_xgb() previously returned the raw model output, so
    XGBoost was deciding on 40%-equivalent information while GradientBoosting
    got all four sources. That made the two incomparable. Both now run through
    this one function, so they differ only in the estimator.
    """
    _using_default_model = ml_predictor is None
    if _using_default_model and symbol not in _predictors:
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
    if ml_df is not None:
        # Caller supplied the ML model's own data (e.g. native 1-minute
        # candles for the cash XGBoost model).
        df = ml_df
    elif intraday_candles is not None and not intraday_candles.empty and len(intraday_candles) > 2:
        df = intraday_candles
        logger.debug(f"↷ {symbol}: Using {len(df)} fresh intraday candles for prediction")
    else:
        df = fetch_historical(symbol)
        if intraday_candles is not None:
            logger.debug(f"↷ {symbol}: Intraday candles insufficient ({len(intraday_candles) if intraday_candles is not None else 0}), falling back to historical data")

    if df.empty:
        return {"symbol": symbol, "signal": "HOLD", "confidence": 0, "reason": "No data",
                "model_source": model_source or "GradientBoosting"}

    # ── Source 1: ML / Technical Analysis ────────────────────────────────
    ml_prediction = (ml_predictor or _predictors[symbol]).predict(df)

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
        # Size the displayed breakeven from the SAME pot auto_trade() will size
        # the real order from. These two had drifted apart: this one read the
        # F&O virtual capital while the trader used the cash pot, so the
        # dashboard quoted a breakeven the actual order would never have had
        # (TITAN: 1.15% shown vs 0.36% traded). Same model_source, same budget,
        # same number.
        trade_budget = get_model_trade_budget(model_source or "GradientBoosting")
        if trade_budget <= 0:
            trade_budget = MAX_TRADE_VALUE
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
        # Which ML model supplied Source 1. Flows through place_buy ->
        # _paper_trade -> record_entry onto the trade record.
        "model_source": model_source or "GradientBoosting",
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


def get_active_watchlist():
    """
    The symbols actually being tracked, from the database.

    config.WATCHLIST is a static 10-symbol seed list from before the
    watchlist became dynamic. Reading it directly meant scan_watchlist()
    (and therefore the Total Scanned / Buy / Sell / Hold summary) covered
    10 stocks while the dashboard showed 67 — the analysis silently ignored
    everything the user had added. Falls back to the static list only if the
    DB is unreachable, so behaviour degrades rather than returning nothing.
    """
    try:
        from db_manager import get_all_stocks
        symbols = [s.symbol for s in get_all_stocks() if s.symbol]
        if symbols:
            return symbols
    except Exception as e:
        logger.warning("Could not load watchlist from DB, using config fallback: %s", e)
    return list(WATCHLIST)


def _predict_one(symbol):
    """One symbol's prediction, with the same fallback shape as before."""
    try:
        return get_prediction(symbol)
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
        return {
            "symbol": symbol,
            "signal": "HOLD",
            "confidence": 0,
            "reason": f"Error: {e}",
            "indicators": {"price": round(fallback_price, 2)},
        }


def scan_watchlist():
    """
    Run predictions for every symbol in the watchlist.

    Parallelised because each symbol's prediction is independent I/O (FYERS
    quote, news sentiment, market context, DB reads) and the watchlist is now
    the real ~70-symbol list rather than the old hardcoded 10. Serially that
    measured ~4.5s/symbol = ~325s, which overran the 300s scheduler interval
    for this task; at 6 workers it comfortably fits. max_workers=6 matches
    the existing idiom in research_engine.py.

    Results are re-ordered to match the input list so the output is
    deterministic regardless of completion order — downstream code (and the
    dashboard table) shouldn't reshuffle between runs.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    symbols = get_active_watchlist()
    if not symbols:
        return []

    out = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_predict_one, s): s for s in symbols}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                out[sym] = fut.result()
            except Exception as e:
                logger.warning("Prediction worker crashed for %s: %s", sym, e)
                out[sym] = {
                    "symbol": sym, "signal": "HOLD", "confidence": 0,
                    "reason": f"Error: {e}", "indicators": {"price": 0},
                }
    return [out[s] for s in symbols if s in out]


# ── Paper Trading ────────────────────────────────────────────────────────────

def is_paper_mode():
    """Check if paper trading mode is active.

    SAFETY: this gate decides simulated vs REAL money.  If we cannot read the
    setting we must assume paper mode — the alternative is that a transient DB
    error silently converts practice trades into live exchange orders.  Fail
    closed, and make the failure loud rather than silent.
    """
    try:
        from db_manager import get_config
        raw = get_config("paper_trading", "false")
        return _paper_flag_means_live(raw) is False
    except Exception:
        logger.error(
            "SAFETY: could not read paper_trading config — assuming PAPER mode "
            "and blocking live orders until the setting is readable again",
            exc_info=True,
        )
        return True


# Only these spellings turn real money on.  Everything else — "true", "1",
# "yes", a stray trailing space, an empty string, a typo — means PAPER.
#
# This asymmetry is deliberate.  The old check was `value.lower() == "true"`,
# which meant *any* value that was not exactly "true" selected live trading:
# "true " with one trailing space, "1", "yes", "True\n" all placed real orders
# while the operator believed they were practising.  A safety gate must fail in
# the direction that cannot lose money, so the burden of proof is on "live".
_LIVE_TRADING_VALUES = frozenset({"false", "0", "no", "off"})


def _paper_flag_means_live(raw):
    """True only when the stored paper_trading value clearly disables paper mode."""
    if raw is None:
        return False
    normalized = str(raw).strip().lower()
    if normalized in _LIVE_TRADING_VALUES:
        return True
    if normalized not in ("true", "1", "yes", "on"):
        # Unrecognized value: stay in paper mode, but say so — a typo here is
        # otherwise invisible until someone notices orders they did not expect.
        logger.warning(
            "paper_trading has unrecognized value %r — treating as PAPER mode. "
            "Use 'true' or 'false'.",
            raw,
        )
    return False


def get_paper_trade_amount_limit():
    """Max total capital the paper trader can deploy across all open positions. Zero = unlimited."""
    try:
        from db_manager import get_config
        raw = get_config("paper_trade_amount_limit", "0")
        return max(float(raw or 0), 0.0)
    except Exception:
        return 0.0


# Per-model capital caps (cash paper trading only — F&O is untouched and
# keeps using fno.capital / fno.used_capital as before).
#
# auto_trade() runs GradientBoosting and, when XGB_LIVE_TRADING is on, cash
# XGBoost as two independent signal sources, and every resulting trade already
# carries `model_source` through place_buy -> _paper_trade -> record_entry.
# That tag is what makes a per-model budget possible: each model gets its own
# pot, sized and enforced against only its own open positions, so one model
# cannot starve the other.
#
# The pre-existing global `paper_trade_amount_limit` is deliberately KEPT as an
# overall ceiling across both models — it is the account-level risk limit and
# removing it would be a silent widening of risk. A trade must satisfy BOTH its
# model's cap and the global cap.
_MODEL_CAP_KEYS = {
    "GradientBoosting": "paper.cap.gradientboosting",
    "XGBoost": "paper.cap.xgboost",
}
_MODEL_CAP_DEFAULT = 50000.0


def get_model_trade_cap(model_source=None):
    """
    Total capital this model may have deployed across its open positions.

    Zero = unlimited (same convention as paper_trade_amount_limit). An unknown
    or missing model_source falls back to the global limit, so any caller that
    predates per-model caps behaves exactly as it did before.
    """
    key = _MODEL_CAP_KEYS.get(model_source or "")
    if not key:
        return get_paper_trade_amount_limit()
    try:
        from db_manager import get_config
        raw = get_config(key, None)
        if raw is None or str(raw).strip() == "":
            return _MODEL_CAP_DEFAULT
        return max(float(raw), 0.0)
    except Exception:
        return _MODEL_CAP_DEFAULT


def get_current_deployed_capital(model_source=None):
    """
    Sum of (entry_price * quantity) for OPEN paper trades.

    model_source=None keeps the original behaviour (every open position, used
    by the global cap and by /api/paper-trading). Passing a model name narrows
    it to that model's own positions, which is what the per-model cap needs.
    """
    try:
        from paper_trader import PaperTradeTracker
        tracker = PaperTradeTracker()
        open_trades = tracker.get_open_positions()
        if model_source:
            open_trades = [
                t for t in open_trades
                if (t.get('model_source') or 'GradientBoosting') == model_source
            ]
        total = sum(
            float(t.get('entry_price', 0)) * int(t.get('quantity', 0))
            for t in open_trades
        )
        return total
    except Exception as e:
        logger.warning("Failed to calculate deployed capital: %s", e)
        return 0.0


def get_model_trade_budget(model_source=None):
    """
    Headroom left in this model's pot — what a NEW trade may be sized against.

    This is what auto_trade() sizes from. It previously sized from
    fno_trader.get_available_capital(), i.e. the F&O virtual pot (fno.capital,
    ₹10,000), even for cash equity. Because fixed charges (~₹20 brokerage +
    ~₹16 DP) do not scale with position size, a ₹10,000 position needs ~0.85%
    just to break even — above the 0.60% trade.max_breakeven_pct gate — so
    EVERY cash candidate was rejected before the model's opinion mattered.
    Measured 2026-08-26: TITAN/DIVISLAB/HINDUNILVR all skipped at 0.85%, all
    clearing at 0.35% once sized from the ₹50,000 cash pot.

    Never returns more than the GLOBAL headroom either, so the account-level
    ceiling still binds when both models hold positions.
    """
    cap = get_model_trade_cap(model_source)
    if cap <= 0:
        cap = float('inf')            # 0 = unlimited, same convention as global
    model_room = cap - get_current_deployed_capital(model_source)

    global_cap = get_paper_trade_amount_limit()
    global_room = (float('inf') if global_cap <= 0
                   else global_cap - get_current_deployed_capital())

    room = min(model_room, global_room)
    return max(room, 0.0)


def _check_capital_cap_allows_trade(new_trade_value, model_source=None):
    """
    Return True if adding a trade worth `new_trade_value` stays within BOTH
    this model's cap and the global cap. Returns True (allow) when:
      • paper mode is off
      • no cap is set (limit == 0) — per-cap, independently
      • deployed + new_trade_value <= cap

    model_source is optional so existing callers keep their exact behaviour;
    passing it adds the per-model check on top of the global one.
    """
    if not is_paper_mode():
        return True

    checks = [("global", get_paper_trade_amount_limit(), get_current_deployed_capital())]
    if model_source:
        checks.append((model_source,
                       get_model_trade_cap(model_source),
                       get_current_deployed_capital(model_source)))

    for label, cap, deployed in checks:
        if cap <= 0:
            continue  # unlimited
        if deployed + new_trade_value > cap:
            logger.info(
                "⛔ Capital cap breach (%s): deployed ₹%.0f + new ₹%.0f = ₹%.0f > cap ₹%.0f — SKIPPING trade",
                label, deployed, new_trade_value, deployed + new_trade_value, cap,
            )
            return False

    return True


def _apply_paper_trade_amount_limit(trade_budget):
    """Legacy helper — kept for backward compatibility but no longer caps per-trade.
    Capital enforcement is now done via _check_capital_cap_allows_trade()."""
    return trade_budget


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
    
    # Which model produced this signal. Read off the prediction dict, which
    # get_prediction_xgb() tags as 'XGBoost'; get_prediction() (the
    # GradientBoosting path) doesn't tag itself, so absence means GBC.
    model_source = (prediction or {}).get('model_source') or 'GradientBoosting'

    # Record trade with trailing stop initialization
    trade = tracker.record_entry(
        symbol=symbol,
        signal=side,
        confidence=prediction.get('confidence', 0) if prediction else 0,
        entry_price=price,
        quantity=quantity,
        prediction=prediction_data,
        exit_reason="new_prediction" if prediction else "manual",
        model_source=model_source,
    )
    
    # Calculate charges
    charges = 0
    try:
        charge_info = costs.calculate_costs(price, quantity, sell_price=price,
                                            product=product, exchange=DEFAULT_EXCHANGE)
        charges = round(charge_info.total, 2)
    except Exception:
        pass

    session = None
    try:
        db = get_db()
        session = db.Session()
        from db_manager import PaperTrade
        session.add(PaperTrade(
            symbol=symbol, side=side, quantity=quantity, price=price,
            segment=segment, product=product, paper_order_id=trade['id'],
            model_source=model_source,
            charges=charges, remark=reason[:500] if reason else None,
        ))
        session.commit()
    except Exception as e:
        logger.warning("Paper trade DB write failed: %s", e)
        # Roll back so the scoped session isn't left in an aborted transaction.
        # This runs on long-lived scheduler threads, and scoped_session hands the
        # same Session back to every later call on that thread — without the
        # rollback, one failed commit would break every subsequent paper trade.
        if session is not None:
            try:
                session.rollback()
            except Exception:
                logger.debug("Paper trade rollback failed", exc_info=True)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.debug("Paper trade session close failed", exc_info=True)

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
            # Pass attribution EXPLICITLY. safe_prediction is a hand-built dict
            # that does not carry model_source, so create_pre_trade_report fell
            # through to its "GradientBoosting" default and recorded the wrong
            # model — MARUTI-B-20260819102622101215 was an XGBoost signal
            # (correct in paper_trades.json and the paper_trades table) but
            # logged as GradientBoosting in trade_journal. A missing value must
            # not become a confident wrong answer.
            model_source=model_source,
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

    # SAFETY: type-check on every path — a caller-supplied quantity (e.g. from
    # POST /api/buy) must not escape as a string or Infinity.  Model-driven
    # orders (GradientBoosting / XGBoost) carry a model_source and are sized
    # from the capital/budget gates, so they take no per-trade share cap.
    # Manual orders (prediction is None) keep MAX_TRADE_QUANTITY as the
    # last-resort guard against a runaway quantity.
    # OverflowError is in the tuple because JSON genuinely carries Infinity:
    # json.loads('{"quantity": Infinity}') succeeds, and int(inf) raises
    # OverflowError — not ValueError — so it would otherwise escape as a 500.
    try:
        quantity = int(quantity)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"quantity must be a finite number, got {quantity!r}")
    if (prediction or {}).get("model_source"):
        quantity = max(1, quantity)
    else:
        quantity = max(1, min(quantity, MAX_TRADE_QUANTITY))

    # SAFETY: a zero/negative price means the LTP lookup failed (fetch_live_price
    # returns 0.0 when the symbol is missing from the response).  Placing a market
    # order on that basis, and the divide-by-zero it causes in the cost helpers
    # afterwards, both have to be prevented before any order reaches the exchange.
    if price is None or price <= 0:
        raise ValueError(
            f"refusing to place BUY for {symbol}: no valid price available (got {price!r})"
        )

    if price * quantity > MAX_TRADE_VALUE:
        raise ValueError(
            f"refusing to place BUY for {symbol}: order value "
            f"₹{price * quantity:,.2f} exceeds MAX_TRADE_VALUE ₹{MAX_TRADE_VALUE:,.2f}"
        )

    # Paper trading intercept
    if is_paper_mode():
        # ── Capital cap gate: reject trade if it would exceed deployed capital limit ──
        new_trade_value = price * quantity
        if not _check_capital_cap_allows_trade(new_trade_value):
            return {
                "time": datetime.now().isoformat(),
                "symbol": symbol,
                "side": "BUY",
                "quantity": quantity,
                "price": price,
                "status": "SKIPPED",
                "remark": "Capital cap exceeded — trade not placed",
                "paper": True,
            }
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
            model_source=(prediction or {}).get("model_source") or "GradientBoosting",
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

    # SAFETY: type-check on every path — see the matching note in place_buy.
    # Model-driven SELLs exit exactly what the position holds (no share cap);
    # manual orders keep MAX_TRADE_QUANTITY as the last-resort guard.
    # OverflowError is in the tuple because JSON genuinely carries Infinity:
    # json.loads('{"quantity": Infinity}') succeeds, and int(inf) raises
    # OverflowError — not ValueError — so it would otherwise escape as a 500.
    try:
        quantity = int(quantity)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"quantity must be a finite number, got {quantity!r}")
    if (prediction or {}).get("model_source"):
        quantity = max(1, quantity)
    else:
        quantity = max(1, min(quantity, MAX_TRADE_QUANTITY))

    if price is None or price <= 0:
        raise ValueError(
            f"refusing to place SELL for {symbol}: no valid price available (got {price!r})"
        )

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
    # Paper mode must never touch the exchange. auto_trade() calls this right
    # after place_buy(), but OUTSIDE place_buy's paper intercept — so without
    # this guard a simulated paper buy still created a REAL GTT sell order on
    # the exchange. Guarding here rather than at the call site protects every
    # caller, including any added later.
    if is_paper_mode():
        logger.info("[PAPER] GTT stop-loss simulated for %s @ %.2f (qty %s) — no exchange order",
                    symbol, trigger_price, quantity)
        return {
            "paper": True,
            "simulated": True,
            "symbol": symbol,
            "trigger_price": trigger_price,
            "quantity": quantity,
            "remark": "Paper mode — GTT stop-loss not sent to exchange",
        }

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

    # One batched quote request for every open position, instead of one
    # fetch_live_price() per trade inside the loop below.
    #
    # Behaviour-preserving: get_ltp_batch() resolves symbols with the same
    # to_fyers_symbol() and reads through the same _get_quotes_cached() layer
    # that fetch_live_price() uses, so prices and cache semantics are
    # identical. It omits symbols it could not quote rather than raising,
    # which lands on the same `if not current_price: continue` branch the
    # per-symbol failure path already used.
    #
    # Bounded by MAX_POSITIONS (5), and deduped because several open trades
    # can share a symbol — previously that meant N separate calls for the
    # same price.
    batch_prices = {}
    try:
        from fyers_market_data_provider import FYERSMarketDataProvider
        _syms = list({t['symbol'] for t in open_trades})
        batch_prices = FYERSMarketDataProvider().get_ltp_batch(_syms) or {}
    except Exception as e:
        # Fall through to the per-symbol path below — never let a batch
        # failure stop stop-loss monitoring.
        logger.debug(f"Batch LTP fetch failed, falling back per-symbol: {e}")

    # Monitor each open trade
    for trade in open_trades:
        symbol = trade['symbol']
        trade_id = trade['id']

        try:
            # Get current live price (batched above; per-symbol only if the
            # batch missed this symbol, preserving the original behaviour)
            current_price = batch_prices.get(symbol)
            if not current_price:
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

def auto_trade(skip_new_entries=False):
    """
    Full cycle: scan watchlist → place trades based on AI signals.
    Also monitors and updates trailing stops on open positions.
    Returns a summary of actions taken.

    SAFETY: Will not run until the user has reviewed their portfolio analysis.

    skip_new_entries: run ONLY the open-position management half (trailing
        stops) and skip the new-entry watchlist scan. Used during FYERS boot
        warm-up (see fyers_boot_warmup.py).

        This split matters because the two halves have opposite risk
        profiles. `monitor_and_update_trailing_stops()` protects money
        already at risk and must never pause. `scan_watchlist()` is a
        ~73-symbol fan-out over FYERS and is the single largest source of
        the restart request burst — this task runs far more often than
        auto_analysis, so pausing auto_analysis alone would not have
        stopped it. Bundling them would have forced a choice between
        pausing stop-loss monitoring and not fixing the burst.
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
    # Runs unconditionally, including during boot warm-up: this is what
    # guards positions that already have money in them.
    trailing_stop_summary = monitor_and_update_trailing_stops()

    if skip_new_entries:
        # Existing positions stay fully managed above; only the bulk scan
        # for NEW entries is deferred. Same early-return shape as the
        # PORTFOLIO_NOT_REVIEWED guard.
        return {
            "timestamp": datetime.now().isoformat(),
            "actions": [],
            "predictions": [],
            "trailing_stop_summary": trailing_stop_summary,
            "skipped_reason": "boot_warmup_active",
            "message": "New-entry scan deferred while FYERS boot warm-up runs. "
                       "Trailing stops on open positions were still checked.",
        }

    actions = []
    predictions = scan_watchlist()

    # Append the independent cash XGBoost signals. GBC predictions come
    # first, so when both models signal the same symbol the existing
    # open_symbols guard below lets GBC take the position and skips XGB —
    # no double entry, and the incumbent model keeps precedence. Each
    # prediction carries its own model_source, which flows through
    # place_buy -> _paper_trade -> record_entry onto the trade record.
    #
    # Gated by XGB_LIVE_TRADING (default off): the models are trained and
    # evaluated but do not place trades until their backtest is available,
    # per the "evaluation-only until compared against GBC" requirement.
    if XGB_LIVE_TRADING:
        try:
            predictions = predictions + scan_watchlist_xgb()
        except Exception as e:
            logger.warning("XGB scan failed, continuing with GradientBoosting only: %s", e)

    # Check current positions.
    # SAFETY: open_symbols is the ONLY thing enforcing both the no-duplicate-entry
    # rule and MAX_POSITIONS below.  Treating a failed lookup as "no open
    # positions" makes both guards vanish and lets the trader re-buy every
    # signalled symbol on every cycle.  Unknown positions != no positions —
    # abort the cycle instead.
    try:
        groww = _get_groww()
        positions_resp = groww.get_positions_for_user(segment=DEFAULT_SEGMENT)
        current_positions = positions_resp.get("positions", [])
    except Exception as e:
        logger.error(
            "SAFETY: could not fetch current positions (%s) — aborting auto-trade "
            "cycle rather than trading blind with the duplicate/limit guards off", e
        )
        return {
            "timestamp": datetime.now().isoformat(),
            "actions": [],
            "predictions": predictions,
            "error": "position_lookup_failed",
            "reason": str(e),
        }

    open_symbols = {p["trading_symbol"] for p in current_positions if p.get("quantity", 0) > 0}

    # UNION the broker's positions with open PAPER positions.
    #
    # Broker positions alone are the wrong answer in paper mode: no real order
    # is ever placed, so the broker reports nothing, `symbol not in
    # open_symbols` is true on every cycle, and the trader re-enters the same
    # symbol forever. Measured on 2026-05-13: 385 separate LT entries in one
    # day, 2 shares each, Rs 31,266 in charges against Rs 7,024 for the same
    # 800 shares bought once — Rs 24,242 (77.5%) burned purely on
    # fragmentation, for an identical end position.
    #
    # Union rather than replace, so live mode keeps the broker as the
    # authority (it is the only source that knows about positions opened
    # outside this bot) while paper positions are also honoured. In live mode
    # this additionally covers the window between placing an order and the
    # position appearing in the broker's response — the auto-trade task runs
    # every 5 seconds, which is faster than fills are reflected.
    #
    # Failure here must not silently drop the guard, so a lookup error is
    # treated the same way a broker lookup error is: abort the cycle.
    try:
        from paper_trader import PaperTradeTracker
        _open_paper = {
            t.get("symbol") for t in PaperTradeTracker().trades
            if t.get("symbol") and str(t.get("status", "")).upper() == "OPEN"
        }
        open_symbols |= _open_paper
        if _open_paper:
            logger.debug("Duplicate-entry guard also holding %d open paper position(s)", len(_open_paper))
    except Exception as e:
        logger.error(
            "SAFETY: could not read open paper positions (%s) — aborting auto-trade "
            "cycle rather than trading with the duplicate-entry guard half-blind", e
        )
        return {
            "timestamp": datetime.now().isoformat(),
            "actions": [],
            "predictions": predictions,
            "error": "paper_position_lookup_failed",
            "reason": str(e),
        }

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

                # Cost-aware gate: predicted confidence must outweigh breakeven cost.
                #
                # Sized from THIS MODEL'S cash pot. It previously read
                # fno_trader.get_available_capital() — the F&O virtual capital
                # (fno.capital, ₹10,000) — for cash equity trades, which made
                # every candidate fail the breakeven gate below. See
                # get_model_trade_budget() for the measurement.
                #
                # F&O sizing is deliberately NOT touched: fno_trader keeps its
                # own capital accounting exactly as before.
                pred_model = pred.get("model_source") or "GradientBoosting"
                trade_budget = get_model_trade_budget(pred_model)
                if trade_budget <= 0:
                    actions.append({
                        "symbol": symbol, "action": "SKIP",
                        "reason": (f"{pred_model} capital pot exhausted "
                                   f"(cap ₹{get_model_trade_cap(pred_model):,.0f}, "
                                   f"deployed ₹{get_current_deployed_capital(pred_model):,.0f})"),
                    })
                    continue
                # Evaluate the economics of the order WE WILL ACTUALLY PLACE.
                #
                # This previously sized qty from the full budget (50000/3950 = 12)
                # and computed breakeven at that size — but place_buy() clamps to
                # MAX_TRADE_QUANTITY (10) before sending. So the gate approved a
                # trade on economics the order never got. Measured on the closed
                # SIEMENS trade: 2 shares, +0.845% gross, breakeven 1.030%,
                # NET -14.50 on a move the model called correctly.
                qty = int(trade_budget / price) if price > 0 else 1
                qty = max(1, qty)     # budget-sized, no per-trade share cap

                cost_info = costs.min_profitable_move(price, qty, product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)
                breakeven_pct = cost_info["min_move_pct"]

                # ── MINIMUM VIABLE POSITION ──────────────────────────────────
                # Fixed charges (brokerage ~Rs40, DP ~Rs16) do not scale with
                # size, so a small position needs a disproportionate move just
                # to break even: Rs7,900 needs 1.02%, Rs39,500 needs 0.38% —
                # the same move, five times the net result. Rather than pick a
                # rupee floor, this caps the BREAKEVEN ITSELF, which is the
                # quantity that actually matters and stays correct across any
                # price. Configurable via trade.max_breakeven_pct.
                try:
                    from db_manager import get_config as _gc
                    _max_be = float(_gc("trade.max_breakeven_pct") or 0.60)
                except Exception:
                    _max_be = 0.60
                if _max_be > 0 and breakeven_pct > _max_be:
                    actions.append({
                        "symbol": symbol, "action": "SKIP",
                        "reason": (f"Position too small: {qty} sh (Rs{price*qty:,.0f}) needs "
                                   f"{breakeven_pct:.2f}% to break even, above the "
                                   f"{_max_be:.2f}% limit."),
                    })
                    logger.info("Min-position gate: %s skipped — %d sh needs %.2f%% breakeven (limit %.2f%%)",
                                symbol, qty, breakeven_pct, _max_be)
                    continue

                # Require confidence * target to exceed at least the breakeven %
                expected_return_pct = confidence * TARGET_PCT
                if expected_return_pct < breakeven_pct:
                    actions.append({
                        "symbol": symbol, "action": "SKIP",
                        "reason": f"Cost-gated: expected {expected_return_pct:.2f}% < breakeven {breakeven_pct:.2f}%",
                    })
                    continue

                # ── Capital cap gate: skip if adding this trade exceeds a cap ──
                # Checks this model's own pot AND the account-wide ceiling.
                new_trade_value = price * qty
                if not _check_capital_cap_allows_trade(new_trade_value, pred_model):
                    actions.append({
                        "symbol": symbol, "action": "SKIP",
                        "reason": (f"Capital cap exceeded: {pred_model} deployed "
                                   f"₹{get_current_deployed_capital(pred_model):,.0f} + ₹{new_trade_value:,.0f} "
                                   f"> cap ₹{get_model_trade_cap(pred_model):,.0f} "
                                   f"(global deployed ₹{get_current_deployed_capital():,.0f} "
                                   f"/ ₹{get_paper_trade_amount_limit():,.0f})"),
                    })
                    continue

                journal_report = None
                if not is_paper_mode():
                    # Real trades still create the journal entry before order placement.
                    journal_report = trade_journal.create_pre_trade_report(
                        symbol=symbol, side="BUY", quantity=qty,
                        entry_price=price, prediction=pred, trigger="auto",
                        model_source=(pred or {}).get("model_source") or "GradientBoosting",
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
                # QUANTITY: broker first, then OPEN PAPER positions.
                #
                # current_positions is the BROKER's list, which is empty in
                # paper mode — so `pos` was always None and qty fell through to
                # MAX_TRADE_QUANTITY (10). Measured 2026-08-18: SIEMENS was
                # held 2 shares long and sold 10, five times over, because the
                # fallback constant was standing in for a real position size.
                # Same blind spot the duplicate-entry guard had: broker state
                # that paper mode never populates.
                pos = next((p for p in current_positions if p["trading_symbol"] == symbol), None)
                _paper_open = []
                if not pos:
                    try:
                        from paper_trader import PaperTradeTracker
                        _paper_open = [
                            t for t in PaperTradeTracker().get_open_positions(symbol) or []
                            if str(t.get("signal", t.get("side", ""))).upper() == "BUY"
                        ]
                    except Exception as e:
                        logger.error("SAFETY: could not read open paper position for %s (%s) "
                                     "— skipping SELL rather than guessing a quantity", symbol, e)
                        actions.append({"symbol": symbol, "action": "SKIP",
                                        "reason": "paper_position_lookup_failed"})
                        continue

                if pos:
                    qty = pos["quantity"]
                elif _paper_open:
                    qty = sum(int(t.get("quantity") or 0) for t in _paper_open)
                else:
                    # Nothing actually held. Selling here would open a NEW
                    # short rather than exit anything — the exact loop that
                    # accumulated 5 SIEMENS positions. Refuse instead.
                    logger.warning("SELL signal for %s but no open long found — skipping "
                                   "(a sell with nothing held would open a short, not an exit)", symbol)
                    open_symbols.discard(symbol)
                    actions.append({"symbol": symbol, "action": "SKIP", "reason": "no_open_long_to_close"})
                    continue

                if qty <= 0:
                    open_symbols.discard(symbol)
                    actions.append({"symbol": symbol, "action": "SKIP", "reason": "zero_quantity"})
                    continue

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

                # CLOSE the paper position this SELL was meant to exit.
                #
                # THE core defect: _paper_trade() calls tracker.record_entry()
                # for every side, and record_entry hardcodes status='OPEN'
                # (paper_trader.py:136). So a SELL created a NEW open row
                # instead of closing the BUY — and because open_symbols is
                # rebuilt from the tracker each cycle, that new row put the
                # symbol straight back into the guard and the SELL fired again
                # next cycle. Self-reinforcing: every sell guaranteed the next.
                #
                # open_symbols.discard() below only clears the in-memory set
                # for the REST OF THIS CYCLE; it does nothing to the file the
                # next cycle reads from. Closing the row is what actually ends
                # the loop.
                if _paper_open:
                    try:
                        from paper_trader import PaperTradeTracker
                        _tracker = PaperTradeTracker()
                        for _t in _paper_open:
                            _tracker.close_trade(_t["id"], exit_price=sell_price,
                                                 exit_reason="signal_reversed")
                        logger.info("Closed %d open paper position(s) for %s on SELL",
                                    len(_paper_open), symbol)
                    except Exception as e:
                        # Loud: an unclosed row means the symbol re-enters the
                        # guard next cycle and the loop restarts.
                        logger.error("SELL for %s did not close its paper position(s) (%s) "
                                     "— duplicate-entry loop may recur", symbol, e)

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
