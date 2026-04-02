"""
Market Context Analyzer — gathers broader market intelligence for smarter trades.

Combines:
  1. Market-wide trend (Nifty 50 / Sensex direction)
  2. Sector relative strength (is the stock's sector outperforming?)
  3. Multi-timeframe confirmation (daily + weekly alignment)
  4. Volatility regime detection (high-vol vs low-vol environment)
  5. Market breadth signals
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config import DEFAULT_EXCHANGE, DEFAULT_SEGMENT, CANDLE_INTERVAL_MINUTES

logger = logging.getLogger(__name__)

# ── Sector mapping — loaded from DB, with fallback ──────────────────────────

_FALLBACK_SECTOR_MAP = {
    "HDFCBANK": "BANKING", "ICICIBANK": "BANKING", "SBIN": "BANKING",
    "KOTAKBANK": "BANKING", "AXISBANK": "BANKING", "BAJFINANCE": "BANKING",
    "INDUSINDBK": "BANKING", "BANKBARODA": "BANKING", "PNB": "BANKING",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "TECHM": "IT", "LTI": "IT", "MPHASIS": "IT",
    "RELIANCE": "ENERGY", "ONGC": "ENERGY", "BPCL": "ENERGY",
    "IOC": "ENERGY", "NTPC": "ENERGY", "POWERGRID": "ENERGY",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG",
    "MARUTI": "AUTO", "TATAMOTORS": "AUTO", "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO", "EICHERMOT": "AUTO", "HEROMOTOCO": "AUTO",
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA", "APOLLOHOSP": "PHARMA",
    "TATASTEEL": "METALS", "HINDALCO": "METALS", "JSWSTEEL": "METALS",
    "VEDL": "METALS", "COALINDIA": "METALS",
    "LT": "INFRA", "BHARTIARTL": "TELECOM", "ASIANPAINT": "CONSUMER",
    "ULTRACEMCO": "CEMENT", "GRASIM": "CEMENT",
}

_sector_map_cache = None


def _get_sector_map():
    """Get sector map from DB, with in-memory cache and fallback."""
    global _sector_map_cache
    if _sector_map_cache is not None:
        return _sector_map_cache
    try:
        from db_manager import get_sector_map
        m = get_sector_map()
        if m:
            _sector_map_cache = m
            return m
    except Exception:
        pass
    return _FALLBACK_SECTOR_MAP

# Nifty sector indices (trading symbols on NSE)
SECTOR_INDEX_SYMBOLS = {
    "BANKING": "NIFTY BANK",
    "IT": "NIFTY IT",
    "FMCG": "NIFTY FMCG",
    "PHARMA": "NIFTY PHARMA",
    "AUTO": "NIFTY AUTO",
    "METALS": "NIFTY METAL",
    "ENERGY": "NIFTY ENERGY",
}

MARKET_INDEX = "NIFTY 50"

# DB symbol mapping (Groww API symbols ≠ index display names)
_DB_SYMBOL_MAP = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
}


def _fetch_candle_data_from_db(symbol, days=7):
    """Fetch candle data directly from the DB (fast, no API call)."""
    try:
        from db_manager import CandleDatabase
        from sqlalchemy import text
        db_sym = _DB_SYMBOL_MAP.get(symbol, symbol)
        db = CandleDatabase()
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT timestamp, open, high, low, close, volume "
                "FROM candles WHERE symbol=:sym ORDER BY timestamp DESC LIMIT :lim"
            ), {"sym": db_sym, "lim": days * 75}).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.sort_values("timestamp").reset_index(drop=True)
    except Exception as e:
        logger.debug("DB candle fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()


def _fetch_candle_data(groww_api, symbol, days, interval_min):
    """Fetch candle data, returns DataFrame or empty. Falls back to daily candles if API rejects interval."""
    try:
        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        resp = groww_api.get_historical_candle_data(
            trading_symbol=symbol,
            exchange=DEFAULT_EXCHANGE,
            segment=DEFAULT_SEGMENT,
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=interval_min,
        )
        candles = resp.get("candles", [])
        if not candles and interval_min < 1440:
            # Fallback: try daily candles if intraday was rejected
            resp = groww_api.get_historical_candle_data(
                trading_symbol=symbol,
                exchange=DEFAULT_EXCHANGE,
                segment=DEFAULT_SEGMENT,
                start_time=start_time,
                end_time=end_time,
                interval_in_minutes=1440,
            )
            candles = resp.get("candles", [])
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        return df.sort_values("datetime").reset_index(drop=True)
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", symbol, e)
        return pd.DataFrame()


def _compute_trend_score(close: pd.Series) -> float:
    """
    Score from -1 (strong downtrend) to +1 (strong uptrend).
    Combines SMA slope + price position relative to MAs.
    """
    if len(close) < 20:
        return 0.0

    sma_10 = close.rolling(10).mean()
    sma_20 = close.rolling(20).mean()
    price = close.iloc[-1]
    s10 = sma_10.iloc[-1]
    s20 = sma_20.iloc[-1]

    # Position score: price above both MAs = bullish
    pos_score = 0.0
    if price > s10:
        pos_score += 0.25
    if price > s20:
        pos_score += 0.25
    if price < s10:
        pos_score -= 0.25
    if price < s20:
        pos_score -= 0.25

    # Direction score: are MAs sloping up?
    if s10 > sma_10.iloc[-5]:
        pos_score += 0.25
    else:
        pos_score -= 0.25
    if s10 > s20:
        pos_score += 0.25
    else:
        pos_score -= 0.25

    return max(-1.0, min(1.0, pos_score))


# ── Public API ───────────────────────────────────────────────────────────────

def analyze_market_context(groww_api, symbol: str) -> dict:
    """
    Build a comprehensive market context for a symbol.
    Returns a dict with scores and signals the predictor can use.
    """
    result = {
        "symbol": symbol,
        "market_trend": 0.0,       # -1 to +1
        "market_signal": "NEUTRAL",
        "sector": _get_sector_map().get(symbol, "UNKNOWN"),
        "sector_trend": 0.0,
        "sector_signal": "NEUTRAL",
        "multi_tf_aligned": False,
        "volatility_regime": "NORMAL",  # LOW / NORMAL / HIGH
        "context_score": 0.0,      # -1 to +1 overall
    }

    # 1. Market-wide trend (Nifty 50) — DB first, API fallback
    try:
        nifty = _fetch_candle_data_from_db(MARKET_INDEX, days=7)
        if nifty.empty:
            nifty = _fetch_candle_data(groww_api, MARKET_INDEX, days=7, interval_min=CANDLE_INTERVAL_MINUTES)
        if not nifty.empty and len(nifty) > 20:
            result["market_trend"] = _compute_trend_score(nifty["close"])
            if result["market_trend"] > 0.3:
                result["market_signal"] = "BULLISH"
            elif result["market_trend"] < -0.3:
                result["market_signal"] = "BEARISH"
    except Exception as e:
        logger.warning("Market trend analysis failed: %s", e)

    # 2. Sector relative strength — DB first, API fallback
    sector = _get_sector_map().get(symbol, "")
    sector_idx = SECTOR_INDEX_SYMBOLS.get(sector)
    if sector_idx:
        try:
            sec_data = _fetch_candle_data_from_db(sector_idx, days=7)
            if sec_data.empty:
                sec_data = _fetch_candle_data(groww_api, sector_idx, days=7, interval_min=CANDLE_INTERVAL_MINUTES)
            if not sec_data.empty and len(sec_data) > 20:
                result["sector_trend"] = _compute_trend_score(sec_data["close"])
                if result["sector_trend"] > 0.3:
                    result["sector_signal"] = "BULLISH"
                elif result["sector_trend"] < -0.3:
                    result["sector_signal"] = "BEARISH"
        except Exception as e:
            logger.warning("Sector analysis failed for %s: %s", sector_idx, e)

    # 3. Multi-timeframe confirmation — DB for intraday, API for daily
    try:
        daily = _fetch_candle_data(groww_api, symbol, days=60, interval_min=1440)  # daily candles
        intra = _fetch_candle_data_from_db(symbol, days=5)
        if intra.empty:
            intra = _fetch_candle_data(groww_api, symbol, days=5, interval_min=CANDLE_INTERVAL_MINUTES)

        if not daily.empty and len(daily) > 20 and not intra.empty and len(intra) > 20:
            daily_trend = _compute_trend_score(daily["close"])
            intra_trend = _compute_trend_score(intra["close"])
            # Aligned = both timeframes agree on direction
            result["multi_tf_aligned"] = (daily_trend > 0 and intra_trend > 0) or \
                                          (daily_trend < 0 and intra_trend < 0)
    except Exception as e:
        logger.warning("Multi-TF analysis failed for %s: %s", symbol, e)

    # 4. Volatility regime — DB first
    try:
        stock = _fetch_candle_data_from_db(symbol, days=7)
        if stock.empty:
            stock = _fetch_candle_data(groww_api, symbol, days=7, interval_min=CANDLE_INTERVAL_MINUTES)
        if not stock.empty and len(stock) > 20:
            returns = stock["close"].pct_change().dropna()
            current_vol = returns.tail(5).std() * np.sqrt(252)
            avg_vol = returns.std() * np.sqrt(252)
            if avg_vol > 0:
                vol_ratio = current_vol / avg_vol
                if vol_ratio > 1.5:
                    result["volatility_regime"] = "HIGH"
                elif vol_ratio < 0.6:
                    result["volatility_regime"] = "LOW"
    except Exception as e:
        logger.warning("Volatility analysis failed for %s: %s", symbol, e)

    # 5. Composite context score
    mkt_weight = 0.3
    sec_weight = 0.3
    tf_weight = 0.2
    vol_weight = 0.2

    ctx = mkt_weight * result["market_trend"] + sec_weight * result["sector_trend"]

    # Multi-TF bonus: if aligned, amplify the signal
    if result["multi_tf_aligned"]:
        ctx += tf_weight * np.sign(result["market_trend"] + result["sector_trend"])
    else:
        ctx -= tf_weight * 0.5  # penalty for mixed signals

    # Volatility adjustment: dampen signals in high-vol regime (more uncertainty)
    if result["volatility_regime"] == "HIGH":
        ctx *= 0.7
    elif result["volatility_regime"] == "LOW":
        ctx *= 1.1  # low vol trending = reliable

    result["context_score"] = round(max(-1.0, min(1.0, ctx)), 4)

    return result
