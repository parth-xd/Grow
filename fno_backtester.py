"""
Swing Backtester v4 — Multi-Day Position Holding (up to 7 days)
================================================================
Uses 1-hour candles from the PostgreSQL `candles` table.
Scans through price data like a real trader:
  - Uses prior candles for indicator baseline
  - Walks candle-by-candle, runs technicals at each bar
  - Enters when signals align (moderate/strong)
  - Holds position across multiple days (up to 7)
  - Exits on: SL hit, TP hit, trailing stop, signal reversal, max hold
  - Chart: multi-day price + entry/exit markers + SL/TP lines

Supports all 16 stocks in the database.
"""

import logging
import math
import os
import numpy as np
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Max trading days to hold a position
MAX_HOLD_DAYS = 7
MAX_HOLD_CANDLES = MAX_HOLD_DAYS * 75  # 75 candles per trading day (5-min)

# Minimum candles needed for technical indicators
MIN_BASELINE_CANDLES = 200


# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUMENT UNIVERSE — All stocks in the database
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUMENT UNIVERSE — Dynamic loading from database
# ═══════════════════════════════════════════════════════════════════════════════

# Static instrument definitions (indices + core holdings)
STATIC_INSTRUMENTS = {
    # Indices (most liquid, for live trading)
    "NIFTY":       {"lot_size": 50,    "label": "NIFTY 50"},
    "BANKNIFTY":   {"lot_size": 25,    "label": "BANKNIFTY"},
    "FINNIFTY":    {"lot_size": 40,    "label": "FINNIFTY"},
}

# Lot size reference for common stocks (used for backtesting)
DEFAULT_EQUITY_LOT_SIZE = 1  # For backtesting (not actual F&O)
KNOWN_LOT_SIZES = {
    "ASIANPAINT": 300, "BHARTIARTL": 950, "HDFCBANK": 550, "ICICIBANK": 700,
    "INFY": 300, "ITC": 1600, "LT": 150, "MOTILALOFS": 400, "ONGC": 3850,
    "PIDILITIND": 250, "RELIANCE": 250, "SBIN": 750, "SUZLON": 10000,
    "TCS": 175, "WIPRO": 1500,
}

_backtest_instruments_cache = None


def _build_backtest_instruments():
    """Build instrument dictionary from database stocks + static definitions."""
    global _backtest_instruments_cache
    
    if _backtest_instruments_cache is not None:
        return _backtest_instruments_cache
    
    instruments = dict(STATIC_INSTRUMENTS)  # Start with indices
    
    # Add all stocks from database
    try:
        from db_manager import CandleDatabase, Candle
        db = CandleDatabase()
        session = db.Session()
        
        # Get all unique symbols that aren't indices
        symbols = session.query(Candle.symbol).distinct().all()
        session.close()
        
        for (symbol,) in symbols:
            if symbol not in instruments and symbol not in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
                # Use known lot size or default
                lot_size = KNOWN_LOT_SIZES.get(symbol, DEFAULT_EQUITY_LOT_SIZE)
                instruments[symbol] = {
                    "lot_size": lot_size,
                    "label": symbol,
                }
    except Exception as e:
        logger.debug(f"Could not load instruments from DB: {e}")
        # Fall back to static definitions
        pass
    
    _backtest_instruments_cache = instruments
    return instruments


def get_backtest_instruments():
    """Get all available backtest instruments."""
    return _build_backtest_instruments()


# Initialize on module load
try:
    BACKTEST_INSTRUMENTS = _build_backtest_instruments()
except Exception:
    # Fallback if database isn't available
    BACKTEST_INSTRUMENTS = STATIC_INSTRUMENTS


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE CANDLE FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_candles_from_db(symbol):
    """
    Fetch all 1-hour candles for a symbol from the candles table.
    Enhanced: Uses fresh IntradayCandle data for recent dates (after March 30th).
    """
    try:
        from db_manager import CandleDatabase, Candle, get_db, IntradayCandle
        from datetime import datetime
        
        db = CandleDatabase()
        session = db.Session()
        candles = []
        
        try:
            # 1. Fetch historical candles from old table (up to March 30th)
            rows = (
                session.query(Candle)
                .filter(Candle.symbol == symbol)
                .order_by(Candle.timestamp)
                .all()
            )
            
            for r in rows:
                ts = r.timestamp
                candles.append({
                    "timestamp": ts.timestamp(),
                    "date": ts.strftime("%Y-%m-%d"),
                    "time": ts.strftime("%H:%M"),
                    "datetime_label": ts.strftime("%b %d %H:%M"),
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": int(r.volume) if r.volume else 0,
                })
            
            # Get latest date from historical data
            latest_hist_date = candles[-1]["date"] if candles else "2026-03-30"
            
            # 2. Fetch fresh intraday candles for dates AFTER the last historical date
            # IntradayCandle has 1-minute data, aggregate to 1-hour for consistency
            from datetime import date as dateobj
            db_session = get_db().Session()
            
            intraday_rows = (
                db_session.query(IntradayCandle)
                .filter(IntradayCandle.symbol == symbol)
                .order_by(IntradayCandle.trading_date, IntradayCandle.time)
                .all()
            )
            
            if intraday_rows:
                # Group by hour to create hourly candles from 1-minute data
                hourly_map = {}
                for row in intraday_rows:
                    # Only use dates after the latest historical date
                    if row.trading_date > latest_hist_date:
                        hour_key = f"{row.trading_date}_{row.time[:2]}"  # "2026-04-11_14"
                        if hour_key not in hourly_map:
                            hourly_map[hour_key] = {
                                "date": row.trading_date,
                                "hour": row.time[:2],
                                "opens": [],
                                "highs": [],
                                "lows": [],
                                "closes": [],
                                "volumes": 0,
                                "first_time": row.time,
                                "last_time": row.time,
                            }
                        hourly_map[hour_key]["opens"].append(row.open)
                        hourly_map[hour_key]["highs"].append(row.high)
                        hourly_map[hour_key]["lows"].append(row.low)
                        hourly_map[hour_key]["closes"].append(row.close)
                        hourly_map[hour_key]["volumes"] += row.volume or 0
                        hourly_map[hour_key]["last_time"] = row.time
                
                # Convert hourly aggregates to candle format
                for hour_key in sorted(hourly_map.keys()):
                    h_data = hourly_map[hour_key]
                    if h_data["opens"]:  # Only if we have data
                        try:
                            ts_str = f"{h_data['date']} {h_data['hour']}:00:00"
                            ts = datetime.fromisoformat(ts_str)
                            candles.append({
                                "timestamp": ts.timestamp(),
                                "date": h_data["date"],
                                "time": f"{h_data['hour']}:00",
                                "datetime_label": ts.strftime("%b %d %H:%M"),
                                "open": float(h_data["opens"][0]),
                                "high": max(h_data["highs"]),
                                "low": min(h_data["lows"]),
                                "close": float(h_data["closes"][-1]),
                                "volume": int(h_data["volumes"]),
                            })
                        except Exception:
                            pass
            
            db_session.close()
            
        finally:
            session.close()
        
        # Sort all candles by timestamp
        candles.sort(key=lambda x: x["timestamp"])
        
        logger.debug(f"Loaded {len(candles)} candles for {symbol} (historical + fresh intraday)")
        return candles
        
    except Exception as e:
        logger.error("Failed to fetch candles for %s: %s", symbol, e)
        return []


def _get_unique_dates(candles):
    """Get sorted list of unique trading dates from candle data."""
    return sorted(set(c["date"] for c in candles))


def _group_candles_by_date(candles):
    """Group candles by trading date."""
    by_date = {}
    for c in candles:
        d = c["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(c)
    return by_date


# ═══════════════════════════════════════════════════════════════════════════════
# NIFTY MARKET CONTEXT — cached index candles for cross-market features
# ═══════════════════════════════════════════════════════════════════════════════

_nifty_candles_cache = None   # List of NIFTY candles from DB
_nifty_by_date = None         # dict: date_str → list of NIFTY candles for that day

def _get_nifty_context():
    """Load NIFTY candles once, build date index for fast cross-market lookups."""
    global _nifty_candles_cache, _nifty_by_date
    if _nifty_candles_cache is not None:
        return _nifty_candles_cache, _nifty_by_date
    _nifty_candles_cache = _fetch_candles_from_db("NIFTY")
    _nifty_by_date = {}
    for c in _nifty_candles_cache:
        d = c["date"]
        if d not in _nifty_by_date:
            _nifty_by_date[d] = []
        _nifty_by_date[d].append(c)
    return _nifty_candles_cache, _nifty_by_date


def _nifty_return_on_date(date_str, lookback_days=1):
    """
    Get NIFTY return % for a given date relative to `lookback_days` prior.
    Returns 0.0 if data unavailable (degrades gracefully).
    """
    _, by_date = _get_nifty_context()
    dates = sorted(by_date.keys())
    if date_str not in dates:
        return 0.0
    idx = dates.index(date_str)
    start_idx = max(0, idx - lookback_days)
    if start_idx == idx:
        return 0.0
    today_close = by_date[dates[idx]][-1]["close"]
    prev_close = by_date[dates[start_idx]][-1]["close"]
    if prev_close <= 0:
        return 0.0
    return ((today_close - prev_close) / prev_close) * 100


def _nifty_volatility_on_date(date_str, lookback_days=14):
    """NIFTY ATR% over last N days — proxy for market fear/VIX."""
    _, by_date = _get_nifty_context()
    dates = sorted(by_date.keys())
    if date_str not in dates:
        return 0.0
    idx = dates.index(date_str)
    start_idx = max(0, idx - lookback_days)
    if start_idx == idx:
        return 0.0
    ranges = []
    for d in dates[start_idx:idx + 1]:
        day_candles = by_date[d]
        h = max(c["high"] for c in day_candles)
        l = min(c["low"] for c in day_candles)
        cl = day_candles[-1]["close"]
        if cl > 0:
            ranges.append((h - l) / cl * 100)
    return sum(ranges) / len(ranges) if ranges else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATOR FUNCTIONS (pure — no API calls)
# ═══════════════════════════════════════════════════════════════════════════════

def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _ema(values, period):
    if len(values) < period:
        return None
    mult = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = (v - e) * mult + e
    return e


def _macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal:
        return None, None, None
    f_mult = 2 / (fast + 1)
    s_mult = 2 / (slow + 1)
    ema_f = sum(closes[:fast]) / fast
    ema_s = sum(closes[:slow]) / slow
    macd_line = []
    for i in range(slow, len(closes)):
        ema_f = (closes[i] - ema_f) * f_mult + ema_f
        ema_s = (closes[i] - ema_s) * s_mult + ema_s
        macd_line.append(ema_f - ema_s)
    if len(macd_line) < signal:
        return macd_line[-1] if macd_line else None, None, None
    sig_mult = 2 / (signal + 1)
    sig_ema = sum(macd_line[:signal]) / signal
    for v in macd_line[signal:]:
        sig_ema = (v - sig_ema) * sig_mult + sig_ema
    return macd_line[-1], sig_ema, macd_line[-1] - sig_ema


def _bollinger(closes, period=20, num_std=2):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = var ** 0.5
    return mid + num_std * std, mid, mid - num_std * std


def _stochastic(highs, lows, closes, k_period=14, d_period=3):
    if len(closes) < k_period:
        return None, None
    h = max(highs[-k_period:])
    l = min(lows[-k_period:])
    if h == l:
        return 50, 50
    k = ((closes[-1] - l) / (h - l)) * 100
    return round(k, 2), round(k, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# PURE TECHNICAL ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

def _analyze_technicals_pure(closes, highs, lows, volumes, current_price):
    """Run full technical analysis on historical price data."""
    result = {"current_price": current_price, "candle_count": len(closes)}

    rsi = _rsi(closes)
    if rsi is not None:
        result["rsi"] = round(rsi, 2)
        if rsi > 70:
            result["rsi_signal"] = "OVERBOUGHT"
        elif rsi < 30:
            result["rsi_signal"] = "OVERSOLD"
        elif rsi > 60:
            result["rsi_signal"] = "BULLISH"
        elif rsi < 40:
            result["rsi_signal"] = "BEARISH"
        else:
            result["rsi_signal"] = "NEUTRAL"

    macd_val, macd_sig, macd_hist = _macd(closes)
    if macd_val is not None:
        result["macd"] = round(macd_val, 4)
        result["macd_signal"] = round(macd_sig, 4) if macd_sig else 0
        result["macd_histogram"] = round(macd_hist, 4) if macd_hist else 0
        if macd_hist and macd_hist > 0:
            result["macd_direction"] = "BULLISH"
        elif macd_hist and macd_hist < 0:
            result["macd_direction"] = "BEARISH"
        else:
            result["macd_direction"] = "NEUTRAL"

    for period in (9, 21, 50):
        e = _ema(closes, period)
        if e is not None:
            result[f"ema_{period}"] = round(e, 2)

    ema9 = result.get("ema_9")
    ema21 = result.get("ema_21")
    if ema9 and ema21:
        if ema9 > ema21 and current_price > ema9:
            result["ema_signal"] = "BULLISH"
        elif ema9 < ema21 and current_price < ema9:
            result["ema_signal"] = "BEARISH"
        else:
            result["ema_signal"] = "NEUTRAL"

    bb_upper, bb_mid, bb_lower = _bollinger(closes)
    if bb_upper is not None:
        result["bb_upper"] = round(bb_upper, 2)
        result["bb_middle"] = round(bb_mid, 2)
        result["bb_lower"] = round(bb_lower, 2)
        if current_price >= bb_upper:
            result["bb_signal"] = "OVERBOUGHT"
        elif current_price <= bb_lower:
            result["bb_signal"] = "OVERSOLD"
        else:
            pos = (current_price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
            result["bb_position"] = round(pos, 2)
            result["bb_signal"] = "BULLISH" if pos > 0.6 else ("BEARISH" if pos < 0.4 else "NEUTRAL")

    k, d = _stochastic(highs, lows, closes) or (None, None)
    if k is not None:
        result["stoch_k"] = k
        if k < 20:
            result["stoch_signal"] = "OVERSOLD"
        elif k > 80:
            result["stoch_signal"] = "OVERBOUGHT"
        elif k > 50:
            result["stoch_signal"] = "BULLISH"
        elif k < 50:
            result["stoch_signal"] = "BEARISH"
        else:
            result["stoch_signal"] = "NEUTRAL"

    if len(highs) >= 10:
        recent_highs = sorted(highs[-20:], reverse=True)
        recent_lows = sorted(lows[-20:])
        result["resistance"] = round(recent_highs[0], 2)
        result["support"] = round(recent_lows[0], 2)

    if len(volumes) >= 10 and any(v > 0 for v in volumes):
        avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1]
        if avg_vol > 0:
            result["volume_ratio"] = round(recent_vol / avg_vol, 2)
            result["volume_signal"] = "HIGH" if recent_vol > avg_vol * 1.5 else ("LOW" if recent_vol < avg_vol * 0.5 else "NORMAL")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL SCORING
# ═══════════════════════════════════════════════════════════════════════════════

_SIGNAL_WEIGHTS = {
    "technicals": 0.25,
    "news":       0.15,
    "x_social":   0.10,
    "oi_pcr":     0.15,
    "trend":      0.10,
    "geopolitical": 0.10,
    "global":     0.15,
}


def _score_technicals(tech):
    """Score technicals."""
    scores = []

    rsi_sig = tech.get("rsi_signal", "NEUTRAL")
    if rsi_sig == "OVERSOLD": scores.append(0.8)
    elif rsi_sig == "OVERBOUGHT": scores.append(-0.8)
    elif rsi_sig == "BULLISH": scores.append(0.4)
    elif rsi_sig == "BEARISH": scores.append(-0.4)
    else: scores.append(0)

    macd_dir = tech.get("macd_direction", "NEUTRAL")
    if macd_dir == "BULLISH": scores.append(0.5)
    elif macd_dir == "BEARISH": scores.append(-0.5)
    else: scores.append(0)

    ema_sig = tech.get("ema_signal", "NEUTRAL")
    if ema_sig == "BULLISH": scores.append(0.5)
    elif ema_sig == "BEARISH": scores.append(-0.5)
    else: scores.append(0)

    bb_sig = tech.get("bb_signal", "NEUTRAL")
    if bb_sig == "OVERSOLD": scores.append(0.6)
    elif bb_sig == "OVERBOUGHT": scores.append(-0.6)
    elif bb_sig == "BULLISH": scores.append(0.3)
    elif bb_sig == "BEARISH": scores.append(-0.3)
    else: scores.append(0)

    stoch_sig = tech.get("stoch_signal", "NEUTRAL")
    if stoch_sig == "OVERSOLD": scores.append(0.7)
    elif stoch_sig == "OVERBOUGHT": scores.append(-0.7)
    elif stoch_sig == "BULLISH": scores.append(0.3)
    elif stoch_sig == "BEARISH": scores.append(-0.3)
    else: scores.append(0)

    avg = sum(scores) / len(scores) if scores else 0
    signal = "BULLISH" if avg > 0.15 else ("BEARISH" if avg < -0.15 else "NEUTRAL")

    return {
        "score": round(avg, 3),
        "signal": signal,
        "rsi": tech.get("rsi"),
        "rsi_signal": rsi_sig,
        "macd_direction": macd_dir,
        "ema_signal": ema_sig,
        "bb_signal": bb_sig,
        "stoch_signal": stoch_sig,
        "stoch_k": tech.get("stoch_k"),
        "support": tech.get("support"),
        "resistance": tech.get("resistance"),
    }


def _simulate_analysis(tech, change_pct):
    """
    Build 7-signal analysis from technicals + trend data (heuristic fallback).
    Used when XGBoost models are unavailable. No random noise — all signals
    are deterministically derived from real technical indicator values.
    """
    signals = {}
    reasons = []
    weighted_score = 0.0

    tech_result = _score_technicals(tech)
    weighted_score += tech_result["score"] * _SIGNAL_WEIGHTS["technicals"]
    signals["technicals"] = tech_result
    reasons.append(f"Technicals: {tech_result['signal']} (RSI={tech.get('rsi', '?')}, MACD={tech_result['macd_direction']}, EMA={tech_result['ema_signal']})")

    trend_score = max(-1, min(1, change_pct / 3))
    weighted_score += trend_score * _SIGNAL_WEIGHTS["trend"]
    trend_signal = "BULLISH" if change_pct > 1 else ("BEARISH" if change_pct < -1 else "NEUTRAL")
    signals["trend"] = {"signal": trend_signal, "change_pct": round(change_pct, 2), "score": round(trend_score, 3)}
    reasons.append(f"Price: {'+' if change_pct > 0 else ''}{change_pct:.1f}% — {trend_signal.lower()}")

    # Non-technical signals scored from technicals + trend (no random noise)
    derived_score = tech_result["score"] * 0.3 + trend_score * 0.2
    for source, label in [("news", "News"), ("x_social", "X/Social"),
                          ("oi_pcr", "OI/PCR"), ("geopolitical", "Geopolitical"),
                          ("global", "Global")]:
        score_val = max(-1, min(1, derived_score))
        weighted_score += score_val * _SIGNAL_WEIGHTS[source]
        sig = "BULLISH" if score_val > 0.15 else ("BEARISH" if score_val < -0.15 else "NEUTRAL")
        signals[source] = {"signal": sig, "score": round(score_val, 3), "derived": True}
        reasons.append(f"{label}: {sig} (derived: {score_val:.2f})")

    confidence = abs(weighted_score)
    if weighted_score > 0.10:
        direction = "BULLISH"
        recommendation = "BUY CE (Call)"
        strength = "strong" if confidence > 0.3 else "moderate" if confidence > 0.15 else "weak"
    elif weighted_score < -0.10:
        direction = "BEARISH"
        recommendation = "BUY PE (Put)"
        strength = "strong" if confidence > 0.3 else "moderate" if confidence > 0.15 else "weak"
    else:
        direction = "NEUTRAL"
        recommendation = "WAIT"
        strength = "none"

    return {
        "direction": direction,
        "recommendation": recommendation,
        "weighted_score": round(weighted_score, 4),
        "confidence": round(confidence, 4),
        "strength": strength,
        "signals": signals,
        "reasons": reasons,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# XGBoost SIGNAL MODELS — Replace random noise with learned patterns
# ═══════════════════════════════════════════════════════════════════════════════

_xgb_models = None  # Cached XGBoost models (trained once, reused)
_xgb_model_timestamp = None  # Timestamp of last XGBoost training

FEATURE_NAMES = [
    'rsi', 'macd_hist_norm', 'ema9_21_ratio', 'ema21_50_ratio',
    'price_ema9', 'price_ema21', 'bb_position', 'stoch_k',
    'volume_ratio', 'mom_1c', 'mom_3c', 'mom_7c', 'mom_14c',
    'atr_pct', 'body_ratio_0', 'body_ratio_1', 'body_ratio_2',
    'hh_count', 'll_count', 'range_position',
    # Market context features (real data — NIFTY index + calendar)
    'nifty_ret_1d', 'nifty_ret_3d', 'nifty_ret_7d',
    'nifty_vol_14d', 'day_of_week', 'month',
]

XGB_ENTRY_THRESHOLD = 0.48  # Minimum probability to consider entry


def _build_feature_vector(candles, idx):
    """
    Build 20-feature normalized vector from candles[0..idx].
    All features are relative/normalized so they generalize across stocks.
    """
    if idx < MIN_BASELINE_CANDLES:
        return None

    closes = [c["close"] for c in candles[:idx + 1]]
    highs = [c["high"] for c in candles[:idx + 1]]
    lows = [c["low"] for c in candles[:idx + 1]]
    volumes = [c.get("volume", 0) for c in candles[:idx + 1]]
    cur = closes[-1]

    f = []

    # 0: RSI normalized 0-1
    rsi = _rsi(closes)
    f.append(rsi / 100.0 if rsi is not None else 0.5)

    # 1: MACD histogram normalized by price
    _, _, hist = _macd(closes)
    f.append(hist / cur * 100 if hist is not None and cur > 0 else 0.0)

    # 2: EMA 9/21 cross ratio
    e9 = _ema(closes, 9)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)
    f.append((e9 / e21 - 1) * 100 if e9 and e21 and e21 > 0 else 0.0)

    # 3: EMA 21/50 alignment
    f.append((e21 / e50 - 1) * 100 if e21 and e50 and e50 > 0 else 0.0)

    # 4-5: Price position relative to EMAs
    f.append((cur / e9 - 1) * 100 if e9 and e9 > 0 else 0.0)
    f.append((cur / e21 - 1) * 100 if e21 and e21 > 0 else 0.0)

    # 6: Bollinger Band position (0=lower band, 1=upper band)
    bbu, _, bbl = _bollinger(closes)
    if bbu and bbl and (bbu - bbl) > 0:
        f.append(max(0.0, min(1.0, (cur - bbl) / (bbu - bbl))))
    else:
        f.append(0.5)

    # 7: Stochastic %K normalized 0-1
    k, _ = _stochastic(highs, lows, closes)
    f.append(k / 100.0 if k is not None else 0.5)

    # 8: Volume ratio (recent 5 vs avg 20)
    if len(volumes) >= 20 and any(v > 0 for v in volumes[-20:]):
        avg_v = sum(volumes[-20:]) / 20
        rec_v = sum(volumes[-5:]) / 5.0 if len(volumes) >= 5 else volumes[-1]
        f.append(min(3.0, rec_v / avg_v) if avg_v > 0 else 1.0)
    else:
        f.append(1.0)

    # 9-12: Multi-timeframe momentum (% change)
    for lb in [1, 3, 7, 14]:
        if len(closes) > lb and closes[-(lb + 1)] > 0:
            f.append(((cur - closes[-(lb + 1)]) / closes[-(lb + 1)]) * 100)
        else:
            f.append(0.0)

    # 13: ATR as % of price (volatility measure)
    n_atr = min(14, len(highs) - 1)
    if n_atr >= 2:
        ranges_arr = [highs[-(i + 1)] - lows[-(i + 1)] for i in range(n_atr)]
        atr_val = sum(ranges_arr) / n_atr
        f.append(atr_val / cur * 100 if cur > 0 else 0.0)
    else:
        f.append(0.0)

    # 14-16: Body ratios for last 3 candles (momentum/indecision)
    for off in range(3):
        ci = idx - off
        if 0 <= ci < len(candles):
            c = candles[ci]
            body = abs(c["close"] - c["open"])
            total = c["high"] - c["low"]
            f.append(body / total if total > 0 else 0.5)
        else:
            f.append(0.5)

    # 17: Higher-high count in last 7 candles (uptrend strength)
    hh = 0
    start_hh = max(1, len(highs) - 7)
    for i in range(start_hh, len(highs)):
        if highs[i] > highs[i - 1]:
            hh += 1
    f.append(hh / 6.0)

    # 18: Lower-low count in last 7 candles (downtrend strength)
    ll = 0
    start_ll = max(1, len(lows) - 7)
    for i in range(start_ll, len(lows)):
        if lows[i] < lows[i - 1]:
            ll += 1
    f.append(ll / 6.0)

    # 19: Position in 20-bar price range
    if len(closes) >= 20:
        hi20 = max(closes[-20:])
        lo20 = min(closes[-20:])
        f.append((cur - lo20) / (hi20 - lo20) if (hi20 - lo20) > 0 else 0.5)
    else:
        f.append(0.5)

    # ── Market context features (20-25) ────────────────────────────────
    candle_date = candles[idx]["date"]

    # 20-22: NIFTY returns (1d, 3d, 7d) — global market direction
    f.append(_nifty_return_on_date(candle_date, 1))
    f.append(_nifty_return_on_date(candle_date, 3))
    f.append(_nifty_return_on_date(candle_date, 7))

    # 23: NIFTY 14-day volatility — market fear proxy (like VIX)
    f.append(_nifty_volatility_on_date(candle_date, 14))

    # 24: Day of week (0=Mon, 4=Fri) normalized 0-1
    try:
        dt = datetime.strptime(candle_date, "%Y-%m-%d")
        f.append(dt.weekday() / 4.0)
    except Exception:
        f.append(0.5)

    # 25: Month (1-12) normalized 0-1 — captures seasonal patterns
    try:
        dt = datetime.strptime(candle_date, "%Y-%m-%d")
        f.append((dt.month - 1) / 11.0)
    except Exception:
        f.append(0.5)

    return f


def _simulate_trade_outcome(candles, idx, direction, lookahead=525):
    """
    Simulate a hypothetical trade from candle idx to determine label.
    Returns 1 if TP hit before SL, 0 otherwise.
    Uses identical SL/TP logic as the actual backtester.
    lookahead=525 = 7 days * 75 candles/day
    """
    entry = candles[idx]["close"]

    # ATR calculation matching _calculate_trade_levels
    n = min(200, idx)
    ranges_arr = [candles[idx - i]["high"] - candles[idx - i]["low"]
                  for i in range(1, n + 1)
                  if (idx - i) >= 0 and candles[idx - i]["high"] > candles[idx - i]["low"]]
    candle_atr = sum(ranges_arr) / len(ranges_arr) if ranges_arr else entry * 0.0005
    # Daily ATR ≈ 5-min ATR * sqrt(75) ≈ 5-min ATR * 8.66
    daily_atr = candle_atr * 8.66

    end_idx = min(idx + 1 + lookahead, len(candles))

    if direction == "LONG":
        sl = entry - daily_atr * 1.2
        risk = entry - sl
        tp = entry + risk * 1.8
        for i in range(idx + 1, end_idx):
            if candles[i]["low"] <= sl:
                return 0
            if candles[i]["high"] >= tp:
                return 1
    else:  # SHORT
        sl = entry + daily_atr * 1.2
        risk = sl - entry
        tp = entry - risk * 1.8
        for i in range(idx + 1, end_idx):
            if candles[i]["high"] >= sl:
                return 0
            if candles[i]["low"] <= tp:
                return 1

    return 0  # Max hold exceeded → loss


def _generate_xgb_training_data():
    """
    Generate labeled training data from ALL stocks' candle histories.
    Labels each candle with whether a long/short trade would be profitable.
    Returns (X, y_long, y_short) lists.
    """
    all_X, all_y_long, all_y_short = [], [], []

    for symbol in BACKTEST_INSTRUMENTS:
        candles = _fetch_candles_from_db(symbol)
        if len(candles) < MIN_BASELINE_CANDLES + 14:
            continue

        max_label_idx = len(candles) - 14  # Need forward candles for labeling

        for idx in range(MIN_BASELINE_CANDLES, max_label_idx):
            fv = _build_feature_vector(candles, idx)
            if fv is None:
                continue

            y_l = _simulate_trade_outcome(candles, idx, "LONG")
            y_s = _simulate_trade_outcome(candles, idx, "SHORT")

            all_X.append(fv)
            all_y_long.append(y_l)
            all_y_short.append(y_s)

    return all_X, all_y_long, all_y_short


_XGB_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "xgb_backtester.joblib")


def _get_xgb_models():
    """Return cached XGBoost models. Loads from disk if available, trains if not."""
    global _xgb_models, _xgb_model_timestamp
    if _xgb_models is not None:
        return _xgb_models if _xgb_models else None

    try:
        import xgboost as xgb
    except ImportError:
        logger.warning("XGBoost not installed — falling back to heuristic signals")
        _xgb_models = False
        return None

    # Try loading pre-trained models from disk
    try:
        import joblib
        if os.path.exists(_XGB_MODEL_PATH):
            saved = joblib.load(_XGB_MODEL_PATH)
            # Validate feature count matches current code
            if saved.get("n_features") == len(FEATURE_NAMES):
                _xgb_models = {"long": saved["long"], "short": saved["short"]}
                _xgb_model_timestamp = saved.get("trained_at", datetime.now())
                logger.info("Loaded XGB backtester models from disk (trained %s, %d features)",
                           _xgb_model_timestamp.strftime("%Y-%m-%d %H:%M"), len(FEATURE_NAMES))
                return _xgb_models
            else:
                logger.info("XGB model feature count mismatch (%d vs %d) — retraining",
                           saved.get("n_features", 0), len(FEATURE_NAMES))
    except Exception as e:
        logger.debug("Could not load XGB from disk: %s", e)

    logger.info("Training XGBoost backtester on all candle data (%d features)...", len(FEATURE_NAMES))
    X, y_long, y_short = _generate_xgb_training_data()

    if len(X) < 100:
        logger.warning("Insufficient training data for XGBoost: %d samples", len(X))
        _xgb_models = False
        return None

    X = np.array(X, dtype=np.float32)
    y_long = np.array(y_long)
    y_short = np.array(y_short)

    lp = int(y_long.sum())
    sp = int(y_short.sum())
    logger.info("XGB data: %d samples — long wins %d (%.0f%%), short wins %d (%.0f%%)",
                len(X), lp, lp / len(X) * 100, sp, sp / len(X) * 100)

    # Guard against degenerate labels
    if lp < 5 or sp < 5:
        logger.warning("Too few positive labels (long=%d, short=%d) — skipping XGB", lp, sp)
        _xgb_models = False
        return None

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

    long_model = xgb.XGBClassifier(
        scale_pos_weight=max(1.0, (len(y_long) - lp) / max(1, lp)),
        **params,
    )
    long_model.fit(X, y_long)

    short_model = xgb.XGBClassifier(
        scale_pos_weight=max(1.0, (len(y_short) - sp) / max(1, sp)),
        **params,
    )
    short_model.fit(X, y_short)

    _xgb_models = {"long": long_model, "short": short_model}
    _xgb_model_timestamp = datetime.now()

    # Save to disk for fast loading on next restart
    try:
        import joblib
        os.makedirs(os.path.dirname(_XGB_MODEL_PATH), exist_ok=True)
        joblib.dump({
            "long": long_model,
            "short": short_model,
            "n_features": len(FEATURE_NAMES),
            "trained_at": _xgb_model_timestamp,
            "n_samples": len(X),
        }, _XGB_MODEL_PATH)
        logger.info("Saved XGB backtester models to %s", _XGB_MODEL_PATH)
    except Exception as e:
        logger.warning("Could not save XGB models to disk: %s", e)

    # Log feature importances
    for tag, mdl in [("LONG", long_model), ("SHORT", short_model)]:
        imp = mdl.feature_importances_
        top5 = sorted(zip(FEATURE_NAMES, imp), key=lambda x: -x[1])[:5]
        logger.info("XGB %s top features: %s", tag, ", ".join(f"{n}={v:.3f}" for n, v in top5))

    return _xgb_models


def _xgb_analysis(tech, change_pct, p_long, p_short):
    """
    Build analysis dict using XGBoost probabilities instead of random noise.
    Returns same structure as _simulate_analysis for full frontend compatibility.
    """
    signals = {}
    reasons = []

    # Technicals (real computed indicators)
    tech_result = _score_technicals(tech)
    signals["technicals"] = tech_result
    reasons.append(f"Technicals: {tech_result['signal']} "
                   f"(RSI={tech.get('rsi', '?')}, MACD={tech_result['macd_direction']}, "
                   f"EMA={tech_result['ema_signal']})")

    # Trend (real price data)
    trend_score = max(-1, min(1, change_pct / 3))
    trend_signal = "BULLISH" if change_pct > 1 else ("BEARISH" if change_pct < -1 else "NEUTRAL")
    signals["trend"] = {"signal": trend_signal, "change_pct": round(change_pct, 2),
                        "score": round(trend_score, 3)}
    reasons.append(f"Price: {'+' if change_pct > 0 else ''}{change_pct:.1f}% — {trend_signal.lower()}")

    # XGBoost-derived signals (deterministic, no random noise)
    xgb_dir = p_long - p_short  # –1 to +1 scale
    xgb_labels = [
        ("news", "ML Pattern"),
        ("x_social", "ML Momentum"),
        ("oi_pcr", "ML Levels"),
        ("geopolitical", "ML Trend"),
        ("global", "ML Composite"),
    ]
    for source, label in xgb_labels:
        score = max(-1.0, min(1.0, xgb_dir))
        sig = "BULLISH" if score > 0.08 else ("BEARISH" if score < -0.08 else "NEUTRAL")
        signals[source] = {"signal": sig, "score": round(score, 3), "xgb": True}
        reasons.append(f"{label}: {sig} (P_long={p_long:.2f}, P_short={p_short:.2f})")

    # Overall direction from XGBoost
    if p_long > p_short:
        direction = "BULLISH"
        confidence = p_long
        recommendation = "BUY CE (Call)"
    else:
        direction = "BEARISH"
        confidence = p_short
        recommendation = "BUY PE (Put)"

    if confidence > 0.65:
        strength = "strong"
    elif confidence > 0.50:
        strength = "moderate"
    elif confidence > 0.40:
        strength = "weak"
    else:
        strength = "none"

    return {
        "direction": direction,
        "recommendation": recommendation,
        "weighted_score": round(p_long - p_short, 4),
        "confidence": round(confidence, 4),
        "strength": strength,
        "signals": signals,
        "reasons": reasons,
        "xgb_probs": {"p_long": round(p_long, 4), "p_short": round(p_short, 4)},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY SCANNING — XGBoost-powered with heuristic fallback
# ═══════════════════════════════════════════════════════════════════════════════

def _scan_for_entry(candles, start_idx=None):
    """
    Walk through candles from start_idx looking for entry signal.
    Uses XGBoost models for data-driven entry selection.
    Falls back to heuristic scoring if XGBoost is unavailable.
    Returns (entry_idx, tech, analysis) or (None, None, None).
    """
    if start_idx is None:
        start_idx = MIN_BASELINE_CANDLES

    max_idx = len(candles) - 7

    models = _get_xgb_models()
    if not models:
        return _scan_for_entry_heuristic(candles, start_idx)

    best_entry = None
    best_score = 0
    best_tech = None
    best_analysis = None

    for idx in range(start_idx, max_idx):
        fv = _build_feature_vector(candles, idx)
        if fv is None:
            continue

        fv_arr = np.array([fv], dtype=np.float32)
        p_long = float(models["long"].predict_proba(fv_arr)[0][1])
        p_short = float(models["short"].predict_proba(fv_arr)[0][1])

        best_p = max(p_long, p_short)
        if best_p < XGB_ENTRY_THRESHOLD:
            continue

        # Promising signal — compute full technicals
        window = candles[:idx + 1]
        closes = [c["close"] for c in window]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        volumes = [c.get("volume", 0) for c in window]
        current_price = candles[idx]["close"]

        tech = _analyze_technicals_pure(closes, highs, lows, volumes, current_price)

        ref_price = candles[max(0, idx - 7)]["close"]
        change_pct = ((current_price - ref_price) / ref_price) * 100 if ref_price else 0

        analysis = _xgb_analysis(tech, change_pct, p_long, p_short)

        if analysis["strength"] not in ("moderate", "strong"):
            continue

        score = best_p
        if score > best_score:
            best_score = score
            best_entry = idx
            best_tech = tech
            best_analysis = analysis

        # Strong XGB signal — take immediately
        if analysis["strength"] == "strong" and best_p > 0.60:
            return idx, tech, analysis

        # Don't scan too far past a good entry
        if best_entry is not None and idx > best_entry + 14:
            break

    return best_entry, best_tech, best_analysis


def _scan_for_entry_heuristic(candles, start_idx):
    """Original heuristic scanning (fallback when XGBoost unavailable)."""
    max_idx = len(candles) - 7
    best_entry = None
    best_score = 0
    best_tech = None
    best_analysis = None

    for idx in range(start_idx, max_idx):
        window = candles[:idx + 1]
        closes = [c["close"] for c in window]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        volumes = [c.get("volume", 0) for c in window]
        current_price = candles[idx]["close"]

        if len(closes) < MIN_BASELINE_CANDLES:
            continue

        tech = _analyze_technicals_pure(closes, highs, lows, volumes, current_price)

        # Price change over recent 7 candles (~ 1 day)
        ref_price = candles[max(0, idx - 7)]["close"]
        change_pct = ((current_price - ref_price) / ref_price) * 100 if ref_price else 0

        analysis = _simulate_analysis(tech, change_pct)

        if analysis["direction"] == "NEUTRAL":
            continue
        if analysis["strength"] not in ("moderate", "strong"):
            continue

        score = abs(analysis["weighted_score"])
        if score > best_score:
            best_score = score
            best_entry = idx
            best_tech = tech
            best_analysis = analysis

        # Strong signal — take it immediately
        if analysis["strength"] == "strong" and score > 0.25:
            return idx, tech, analysis

        # Don't scan too far — pick best within a reasonable window
        if best_entry is not None and idx > best_entry + 14:
            break

    return best_entry, best_tech, best_analysis


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE LEVEL CALCULATION — wider for swing trades
# ═══════════════════════════════════════════════════════════════════════════════

def _calculate_trade_levels(tech, entry_price, direction, prior_candles):
    """
    Calculate Entry, Stop-Loss, Take-Profit for multi-day swing trades.
    Uses daily ATR (derived from 5-min candle ranges) for wider levels.
    """
    ranges = [c["high"] - c["low"] for c in prior_candles[-200:] if c["high"] > c["low"]]
    candle_atr = sum(ranges) / len(ranges) if ranges else entry_price * 0.0005
    # Daily ATR ≈ 5-min ATR * sqrt(75) ≈ 8.66x
    daily_atr = candle_atr * 8.66

    support = tech.get("support")
    resistance = tech.get("resistance")

    if direction == "BULLISH":
        base_sl = entry_price - daily_atr * 1.2
        if support and support < entry_price and support > entry_price - daily_atr * 3:
            base_sl = max(base_sl, support - candle_atr * 0.3)
        sl = round(base_sl, 2)

        risk = entry_price - sl
        base_tp = entry_price + risk * 1.8
        if resistance and resistance > entry_price and resistance < entry_price + daily_atr * 4:
            base_tp = min(base_tp, max(resistance, entry_price + risk * 1.3))
        tp = round(base_tp, 2)

    elif direction == "BEARISH":
        base_sl = entry_price + daily_atr * 1.2
        if resistance and resistance > entry_price and resistance < entry_price + daily_atr * 3:
            base_sl = min(base_sl, resistance + candle_atr * 0.3)
        sl = round(base_sl, 2)

        risk = sl - entry_price
        base_tp = entry_price - risk * 1.8
        if support and support < entry_price and support > entry_price - daily_atr * 4:
            base_tp = max(base_tp, min(support, entry_price - risk * 1.3))
        tp = round(base_tp, 2)
    else:
        sl = round(entry_price - daily_atr * 1.0, 2)
        tp = round(entry_price + daily_atr * 1.0, 2)

    risk = abs(entry_price - sl)
    reward = abs(tp - entry_price)
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0

    return {
        "entry_price": round(entry_price, 2),
        "stop_loss": sl,
        "take_profit": tp,
        "risk": round(risk, 2),
        "reward": round(reward, 2),
        "risk_reward": rr_ratio,
        "atr": round(daily_atr, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# OPTION PREMIUM SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_option_premium(spot_price, direction, lot_size):
    """Estimate ATM option premium as ~2-3% of spot price (simplified model)."""
    # ATM premium is roughly 2-3% of spot for monthly expiry
    base_premium = spot_price * 0.025
    return round(base_premium, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-DAY TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_swing_trade(candles, entry_idx, entry_premium, direction, lot_size, trade_levels):
    """
    Simulate a swing trade across multiple days using 5-minute candles.
    Exits on: spot SL/TP, trailing stop, max hold (7 days), or signal reversal.
    Uses delta-based premium changes.
    """
    entry_spot = candles[entry_idx]["close"]
    entry_date = candles[entry_idx]["date"]
    spot_sl = trade_levels["stop_loss"]
    spot_tp = trade_levels["take_profit"]

    # ATM delta (fixed at 0.47 for ATM options)
    delta = 0.47
    # Theta per candle: ~0.028% per 5-min candle for swing (0.3% per hour / 12)
    theta_per_candle = entry_premium * 0.00028

    def _calc_premium(spot_price, candles_elapsed):
        spot_move = spot_price - entry_spot
        if direction == "BULLISH":
            prem_delta = spot_move * delta
        else:
            prem_delta = -spot_move * delta
        theta_decay = theta_per_candle * candles_elapsed
        return max(0.05, round(entry_premium + prem_delta - theta_decay, 2))

    timeline = []
    peak_premium = entry_premium
    exit_premium = None
    exit_reason = None
    exit_idx = None
    sl_hit = False
    tp_hit = False
    exit_spot = None
    days_held = 0

    max_candle = min(entry_idx + MAX_HOLD_CANDLES, len(candles))

    for i in range(entry_idx + 1, max_candle):
        c = candles[i]
        spot_change = ((c["close"] - entry_spot) / entry_spot) * 100
        candles_elapsed = i - entry_idx

        # Count days held
        if c["date"] != entry_date:
            current_dates = set(candles[j]["date"] for j in range(entry_idx, i + 1))
            days_held = len(current_dates) - 1

        current_premium = _calc_premium(c["close"], candles_elapsed)
        pnl_pct = ((current_premium - entry_premium) / entry_premium) * 100

        if current_premium > peak_premium:
            peak_premium = current_premium

        event = {
            "candle_idx": i,
            "timestamp": c.get("timestamp", ""),
            "date": c.get("date", ""),
            "time": c.get("time", ""),
            "datetime_label": c.get("datetime_label", ""),
            "spot_price": round(c["close"], 2),
            "spot_change_pct": round(spot_change, 2),
            "premium": current_premium,
            "pnl_pct": round(pnl_pct, 2),
            "peak_premium": round(peak_premium, 2),
            "days_held": days_held,
        }

        # ── Spot-level SL exit ─────────────────────────────────────────
        if direction == "BULLISH" and c["low"] <= spot_sl:
            sl_hit = True
            exit_spot = spot_sl
            exit_premium = _calc_premium(spot_sl, candles_elapsed)
            exit_reason = f"Stop-loss hit at ₹{spot_sl:.2f} (day {days_held + 1})"
            exit_idx = i
            event["action"] = "STOP_LOSS_HIT"
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = round(spot_sl, 2)
            timeline.append(event)
            break

        if direction == "BEARISH" and c["high"] >= spot_sl:
            sl_hit = True
            exit_spot = spot_sl
            exit_premium = _calc_premium(spot_sl, candles_elapsed)
            exit_reason = f"Stop-loss hit at ₹{spot_sl:.2f} (day {days_held + 1})"
            exit_idx = i
            event["action"] = "STOP_LOSS_HIT"
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = round(spot_sl, 2)
            timeline.append(event)
            break

        # ── Spot-level TP exit ─────────────────────────────────────────
        if direction == "BULLISH" and c["high"] >= spot_tp:
            tp_hit = True
            exit_spot = spot_tp
            exit_premium = _calc_premium(spot_tp, candles_elapsed)
            exit_reason = f"Target hit at ₹{spot_tp:.2f} (day {days_held + 1})"
            exit_idx = i
            event["action"] = "TARGET_HIT"
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = round(spot_tp, 2)
            timeline.append(event)
            break

        if direction == "BEARISH" and c["low"] <= spot_tp:
            tp_hit = True
            exit_spot = spot_tp
            exit_premium = _calc_premium(spot_tp, candles_elapsed)
            exit_reason = f"Target hit at ₹{spot_tp:.2f} (day {days_held + 1})"
            exit_idx = i
            event["action"] = "TARGET_HIT"
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = round(spot_tp, 2)
            timeline.append(event)
            break

        # ── Trailing stop: if up >30% and drops 15% from peak ──────────
        if pnl_pct > 30 and peak_premium > 0:
            drawdown = ((peak_premium - current_premium) / peak_premium) * 100
            if drawdown > 15:
                exit_premium = current_premium
                exit_spot = c["close"]
                exit_reason = f"Trailing SL: {drawdown:.1f}% drop from peak ₹{peak_premium:.2f} (day {days_held + 1})"
                exit_idx = i
                event["action"] = "TRAILING_SL_EXIT"
                timeline.append(event)
                break

        # ── Max hold days ──────────────────────────────────────────────
        if days_held >= MAX_HOLD_DAYS:
            exit_premium = current_premium
            exit_spot = c["close"]
            exit_reason = f"Max hold ({MAX_HOLD_DAYS} days) reached"
            exit_idx = i
            event["action"] = "MAX_HOLD_EXIT"
            timeline.append(event)
            break

        timeline.append(event)

    # If no exit, close at last simulated candle
    if exit_premium is None and timeline:
        last = timeline[-1]
        exit_premium = last["premium"]
        exit_spot = last["spot_price"]
        exit_reason = "End of available data"
        exit_idx = max_candle - 1
        timeline[-1]["action"] = "DATA_END_EXIT"

    if exit_premium is not None:
        pnl_per_unit = exit_premium - entry_premium
        total_pnl = pnl_per_unit * lot_size
        pnl_pct = ((exit_premium - entry_premium) / entry_premium) * 100
        brokerage = 40
        stt = exit_premium * lot_size * 0.000625
        total_charges = brokerage + stt
    else:
        pnl_per_unit = 0
        total_pnl = 0
        pnl_pct = 0
        total_charges = 0

    return {
        "timeline": timeline,
        "entry_premium": entry_premium,
        "exit_premium": exit_premium,
        "exit_reason": exit_reason,
        "exit_candle_idx": exit_idx,
        "exit_spot": exit_spot,
        "sl_hit": sl_hit,
        "tp_hit": tp_hit,
        "days_held": days_held,
        "pnl_per_unit": round(pnl_per_unit, 2),
        "total_pnl": round(total_pnl - total_charges, 2),
        "total_pnl_pct": round(pnl_pct, 2),
        "total_charges": round(total_charges, 2),
        "peak_premium": round(peak_premium, 2),
        "lot_size": lot_size,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PREDICTED TRAJECTORY
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_predicted_trajectory(entry_price, direction, confidence, num_candles, prior_candles):
    """
    Generate deterministic predicted price trajectory from entry point.
    Uses ATR-based drift scaled by model confidence — no random noise.
    This shows where the model *expected* price to go based on its signal.
    """
    ranges = [c["high"] - c["low"] for c in prior_candles[-30:] if c["high"] > c["low"]]
    avg_range = sum(ranges) / len(ranges) if ranges else entry_price * 0.003

    dir_mult = 1.0 if direction == "BULLISH" else (-1.0 if direction == "BEARISH" else 0.0)
    drift = dir_mult * confidence * avg_range * 0.20

    prices = [entry_price]
    for i in range(1, num_candles):
        # Deterministic momentum curve — no random noise
        momentum = 1 + 0.03 * (i / num_candles)
        prices.append(round(prices[-1] + drift * momentum, 2))
    return prices


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN BACKTEST — SINGLE TRADE
# ═══════════════════════════════════════════════════════════════════════════════

def run_fno_backtest(instrument_key=None, target_date=None, days_back=None):
    """
    Run a single swing backtest.

    Scans through 1-hour DB candles looking for entry:
    - Uses prior candles as indicator baseline
    - Enters when signals align
    - Holds up to 7 days with SL/TP/trailing exit
    - Chart shows multi-day window around the trade

    Args:
        instrument_key: e.g. "RELIANCE", "TCS". Random if None.
        target_date: "YYYY-MM-DD" — start scanning from this date.
    """
    if not instrument_key:
        instrument_key = list(BACKTEST_INSTRUMENTS.keys())[0]

    inst = BACKTEST_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    lot_size = inst["lot_size"]

    # ── Fetch all candles from DB ──────────────────────────────────────
    candles = _fetch_candles_from_db(instrument_key)
    if len(candles) < MIN_BASELINE_CANDLES + 7:
        return {"error": f"Insufficient data for {instrument_key}: only {len(candles)} candles (need ≥{MIN_BASELINE_CANDLES + 7})"}

    dates = _get_unique_dates(candles)

    # ── Determine scan start index ─────────────────────────────────────
    scan_start = MIN_BASELINE_CANDLES
    if target_date:
        for i, c in enumerate(candles):
            if c["date"] == target_date:
                scan_start = max(MIN_BASELINE_CANDLES, i)
                break
        else:
            return {"error": f"Date {target_date} not found. Available: {', '.join(dates[-5:])}"}
    else:
        # Deterministic start: scan from midpoint of available data
        valid_range = len(candles) - MIN_BASELINE_CANDLES - 14
        if valid_range > 0:
            scan_start = MIN_BASELINE_CANDLES + valid_range // 2

    # ── Scan for entry ─────────────────────────────────────────────────
    entry_idx, tech, analysis = _scan_for_entry(candles, start_idx=scan_start)

    if entry_idx is None:
        # No entry found — show data for context
        mid = min(scan_start + 20, len(candles) - 1)
        window_start = max(0, mid - 30)
        window_end = min(len(candles), mid + 30)
        window = candles[window_start:window_end]

        closes = [c["close"] for c in candles[:mid + 1]]
        highs = [c["high"] for c in candles[:mid + 1]]
        lows = [c["low"] for c in candles[:mid + 1]]
        volumes = [c.get("volume", 0) for c in candles[:mid + 1]]
        tech = _analyze_technicals_pure(closes, highs, lows, volumes, candles[mid]["close"])
        analysis = _simulate_analysis(tech, 0)

        return {
            "instrument": instrument_key,
            "label": inst.get("label", instrument_key),
            "lot_size": lot_size,
            "target_date": candles[scan_start]["date"],
            "total_candles": len(candles),
            "entry_time": None,
            "entry_candle_idx": None,
            "analysis": analysis,
            "chart": {
                "labels": [c["datetime_label"] for c in window],
                "prices": [round(c["close"], 2) for c in window],
                "highs": [round(c["high"], 2) for c in window],
                "lows": [round(c["low"], 2) for c in window],
                "predicted": None,
            },
            "discrepancy": None,
            "trade_simulation": {
                "would_trade": False,
                "reason": "No entry signal found — signals too weak in scanned range",
                "direction": analysis["direction"],
                "strength": analysis["strength"],
                "trade_levels": None,
            },
            "technicals": _extract_technicals(tech),
        }

    # ── Entry found! ───────────────────────────────────────────────────
    entry_price = candles[entry_idx]["close"]
    entry_date = candles[entry_idx]["date"]
    entry_time = candles[entry_idx]["time"]
    entry_label = candles[entry_idx]["datetime_label"]

    prior_candles = candles[:entry_idx + 1]
    trade_levels = _calculate_trade_levels(tech, entry_price, analysis["direction"], prior_candles)

    # ── Simulate the trade ─────────────────────────────────────────────
    entry_premium = _simulate_option_premium(entry_price, analysis["direction"], lot_size)
    option_type = "CE" if analysis["direction"] == "BULLISH" else "PE"

    sim = _simulate_swing_trade(
        candles=candles,
        entry_idx=entry_idx,
        entry_premium=entry_premium,
        direction=analysis["direction"],
        lot_size=lot_size,
        trade_levels=trade_levels,
    )

    exit_idx = sim.get("exit_candle_idx", entry_idx + 7)

    # ── Chart window: 1 day before entry to exit + some padding ────────
    # Find 1 day before entry
    chart_start = entry_idx
    for i in range(entry_idx - 1, -1, -1):
        if candles[i]["date"] != entry_date:
            chart_start = i
            break
    chart_start = max(0, chart_start)

    # End: exit + a few candles padding
    chart_end = min(len(candles), exit_idx + 4)
    chart_window = candles[chart_start:chart_end]

    # Entry/exit positions relative to chart window
    entry_chart_idx = entry_idx - chart_start
    exit_chart_idx = exit_idx - chart_start if exit_idx else None

    # ── Predicted trajectory from entry ────────────────────────────────
    num_trade_candles = (exit_idx - entry_idx) + 1 if exit_idx else 14
    predicted_prices = _generate_predicted_trajectory(
        entry_price, analysis["direction"], analysis["confidence"],
        num_trade_candles, prior_candles,
    )

    # Build predicted data aligned with chart window
    pred_data = [None] * len(chart_window)
    for i, price in enumerate(predicted_prices):
        ci = entry_chart_idx + i
        if 0 <= ci < len(pred_data):
            pred_data[ci] = round(price, 2)

    # ── Actual prices from entry through trade for discrepancy ─────────
    actual_from_entry = candles[entry_idx:exit_idx + 1] if exit_idx else candles[entry_idx:entry_idx + num_trade_candles]
    actual_prices = [round(c["close"], 2) for c in actual_from_entry]

    predicted_end = predicted_prices[-1] if predicted_prices else entry_price
    actual_end = actual_prices[-1] if actual_prices else entry_price
    predicted_change = ((predicted_end - entry_price) / entry_price) * 100 if entry_price else 0
    actual_change = ((actual_end - entry_price) / entry_price) * 100 if entry_price else 0

    direction_correct = (
        (analysis["direction"] == "BULLISH" and actual_change > 0) or
        (analysis["direction"] == "BEARISH" and actual_change < 0) or
        (analysis["direction"] == "NEUTRAL")
    )

    deviations = []
    for p, a in zip(predicted_prices, actual_prices):
        dev = abs(p - a) / a * 100 if a > 0 else 0
        deviations.append(dev)
    avg_deviation = sum(deviations) / len(deviations) if deviations else 0

    trade_result = {
        "would_trade": True,
        "option_type": option_type,
        "direction": analysis["direction"],
        "entry_premium": entry_premium,
        "entry_cost": round(entry_premium * lot_size, 2),
        "lot_size": lot_size,
        "trade_levels": trade_levels,
        **sim,
    }

    return {
        "instrument": instrument_key,
        "label": inst.get("label", instrument_key),
        "lot_size": lot_size,
        "target_date": entry_date,
        "entry_time": entry_time,
        "entry_label": entry_label,
        "entry_price": round(entry_price, 2),
        "entry_candle_idx": entry_chart_idx,  # relative to chart window
        "exit_candle_idx": exit_chart_idx,     # relative to chart window
        "total_candles": len(candles),
        "days_held": sim.get("days_held", 0),
        "analysis": analysis,
        "chart": {
            "labels": [c["datetime_label"] for c in chart_window],
            "prices": [round(c["close"], 2) for c in chart_window],
            "highs": [round(c["high"], 2) for c in chart_window],
            "lows": [round(c["low"], 2) for c in chart_window],
            "predicted": pred_data,
        },
        "discrepancy": {
            "predicted_end": round(predicted_end, 2),
            "actual_end": round(actual_end, 2),
            "predicted_change_pct": round(predicted_change, 2),
            "actual_change_pct": round(actual_change, 2),
            "difference_pct": round(predicted_change - actual_change, 2),
            "direction_correct": direction_correct,
            "avg_deviation_pct": round(avg_deviation, 2),
        },
        "trade_simulation": trade_result,
        "technicals": _extract_technicals(tech),
    }


def _extract_technicals(tech):
    """Extract technicals dict for API response."""
    return {
        "rsi": tech.get("rsi"),
        "rsi_signal": tech.get("rsi_signal"),
        "macd": tech.get("macd"),
        "macd_direction": tech.get("macd_direction"),
        "ema_9": tech.get("ema_9"),
        "ema_21": tech.get("ema_21"),
        "ema_signal": tech.get("ema_signal"),
        "bb_upper": tech.get("bb_upper"),
        "bb_lower": tech.get("bb_lower"),
        "bb_signal": tech.get("bb_signal"),
        "stoch_k": tech.get("stoch_k"),
        "stoch_signal": tech.get("stoch_signal"),
        "support": tech.get("support"),
        "resistance": tech.get("resistance"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AVAILABLE DATES
# ═══════════════════════════════════════════════════════════════════════════════

def get_available_backtest_dates(instrument_key="RELIANCE"):
    """Get list of dates available for backtesting from DB."""
    candles = _fetch_candles_from_db(instrument_key)
    if not candles:
        return {"instrument": instrument_key, "dates": [], "total": 0}

    by_date = _group_candles_by_date(candles)

    dates = []
    for d in sorted(by_date.keys()):
        day = by_date[d]
        if len(day) >= 3:  # need at least a few candles
            op = day[0]["open"]
            cl = day[-1]["close"]
            change_pct = ((cl - op) / op) * 100 if op else 0
            dates.append({
                "date": d,
                "open": round(op, 2),
                "close": round(cl, 2),
                "change_pct": round(change_pct, 2),
                "candles": len(day),
            })

    return {
        "instrument": instrument_key,
        "dates": dates,
        "total": len(dates),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-ENTRY AGGREGATE BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

def run_multi_backtest(instrument_key="RELIANCE", num_days=10):
    """
    Run sequential backtests across all available data.
    Finds multiple entry points and simulates each trade.
    """
    inst = BACKTEST_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    candles = _fetch_candles_from_db(instrument_key)
    if len(candles) < MIN_BASELINE_CANDLES + 14:
        return {"error": f"Insufficient data for multi-backtest on {instrument_key}"}

    results = []
    wins, losses, total_pnl = 0, 0, 0
    direction_correct_count = 0
    scan_start = MIN_BASELINE_CANDLES

    # Scan through data finding sequential entries
    max_trades = min(num_days, 10)
    while scan_start < len(candles) - 7 and len(results) < max_trades:
        entry_idx, tech, analysis = _scan_for_entry(candles, start_idx=scan_start)

        if entry_idx is None:
            break

        entry_price = candles[entry_idx]["close"]
        entry_date = candles[entry_idx]["date"]
        entry_time = candles[entry_idx]["time"]

        prior = candles[:entry_idx + 1]
        trade_levels = _calculate_trade_levels(tech, entry_price, analysis["direction"], prior)

        entry_premium = _simulate_option_premium(entry_price, analysis["direction"], inst["lot_size"])
        option_type = "CE" if analysis["direction"] == "BULLISH" else "PE"

        sim = _simulate_swing_trade(
            candles=candles,
            entry_idx=entry_idx,
            entry_premium=entry_premium,
            direction=analysis["direction"],
            lot_size=inst["lot_size"],
            trade_levels=trade_levels,
        )

        # Determine direction correctness
        exit_idx = sim.get("exit_candle_idx", entry_idx + 1)
        exit_price = sim.get("exit_spot", entry_price)
        actual_change = ((exit_price - entry_price) / entry_price) * 100

        dir_correct = (
            (analysis["direction"] == "BULLISH" and actual_change > 0) or
            (analysis["direction"] == "BEARISH" and actual_change < 0)
        )
        if dir_correct:
            direction_correct_count += 1

        entry = {
            "date": entry_date,
            "entry_time": entry_time,
            "entry_price": round(entry_price, 2),
            "direction": analysis["direction"],
            "confidence": analysis["confidence"],
            "direction_correct": dir_correct,
            "actual_change_pct": round(actual_change, 2),
            "traded": True,
            "option_type": option_type,
            "pnl": sim["total_pnl"],
            "pnl_pct": sim["total_pnl_pct"],
            "exit_reason": sim["exit_reason"],
            "sl_hit": sim.get("sl_hit", False),
            "tp_hit": sim.get("tp_hit", False),
            "days_held": sim.get("days_held", 0),
        }

        total_pnl += sim["total_pnl"]
        if sim["total_pnl"] > 0:
            wins += 1
        else:
            losses += 1

        results.append(entry)

        # Next scan starts after this trade's exit
        scan_start = exit_idx + 1 if exit_idx else entry_idx + 7

    total_trades = wins + losses
    return {
        "instrument": instrument_key,
        "label": inst.get("label", instrument_key),
        "entries_found": len(results),
        "prediction_accuracy": round(direction_correct_count / len(results) * 100, 1) if results else 0,
        "trades_taken": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / total_trades, 2) if total_trades > 0 else 0,
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE TRADING SIGNAL — XGBoost-powered entry recommendation
# ═══════════════════════════════════════════════════════════════════════════════

def get_xgb_signal(instrument_key):
    """
    Get XGBoost-powered BULLISH/BEARISH signal for live trading.
    Uses latest candles from DB to build features and run inference.
    
    Returns dict with:
      - direction: BULLISH/BEARISH/NEUTRAL
      - confidence: 0.0-1.0
      - strength: strong/moderate/weak/none
      - p_long, p_short: XGBoost probabilities
      - recommendation: BUY CE / BUY PE / WAIT
      - technicals: computed technical indicators
    """
    candles = _fetch_candles_from_db(instrument_key)
    if len(candles) < MIN_BASELINE_CANDLES:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "strength": "none",
            "reason": f"Insufficient data: {len(candles)} candles (need {MIN_BASELINE_CANDLES})",
        }

    models = _get_xgb_models()
    if not models:
        # Fallback to heuristic if XGBoost unavailable
        idx = len(candles) - 1
        window = candles[:idx + 1]
        closes = [c["close"] for c in window]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        volumes = [c.get("volume", 0) for c in window]
        current_price = candles[idx]["close"]
        
        tech = _analyze_technicals_pure(closes, highs, lows, volumes, current_price)
        change_pct = ((current_price - candles[max(0, idx - 7)]["close"]) / candles[max(0, idx - 7)]["close"] * 100) if idx > 7 else 0
        
        analysis = _simulate_analysis(tech, change_pct)
        return {
            "direction": analysis["direction"],
            "confidence": analysis["confidence"],
            "strength": analysis["strength"],
            "recommendation": analysis["recommendation"],
            "technicals": _extract_technicals(tech),
            "xgb_available": False,
            "reasons": analysis["reasons"],
        }

    # Use latest candle for signal
    idx = len(candles) - 1
    fv = _build_feature_vector(candles, idx)
    
    if fv is None:
        return {
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "strength": "none",
            "reason": "Could not build feature vector",
        }

    fv_arr = np.array([fv], dtype=np.float32)
    p_long = float(models["long"].predict_proba(fv_arr)[0][1])
    p_short = float(models["short"].predict_proba(fv_arr)[0][1])

    # Get technicals for context
    window = candles[:idx + 1]
    closes = [c["close"] for c in window]
    highs = [c["high"] for c in window]
    lows = [c["low"] for c in window]
    volumes = [c.get("volume", 0) for c in window]
    current_price = candles[idx]["close"]
    
    tech = _analyze_technicals_pure(closes, highs, lows, volumes, current_price)
    change_pct = ((current_price - candles[max(0, idx - 7)]["close"]) / candles[max(0, idx - 7)]["close"] * 100) if idx > 7 else 0
    
    # Determine direction from XGBoost
    if p_long > p_short:
        direction = "BULLISH"
        confidence = p_long
        recommendation = "BUY CE (Call)"
    else:
        direction = "BEARISH"
        confidence = p_short
        recommendation = "BUY PE (Put)"

    if confidence > 0.65:
        strength = "strong"
    elif confidence > 0.50:
        strength = "moderate"
    elif confidence > 0.40:
        strength = "weak"
    else:
        strength = "none"
        direction = "NEUTRAL"
        recommendation = "WAIT"

    return {
        "direction": direction,
        "confidence": round(confidence, 4),
        "strength": strength,
        "recommendation": recommendation,
        "technicals": _extract_technicals(tech),
        "xgb_available": True,
        "xgb_probs": {
            "p_long": round(p_long, 4),
            "p_short": round(p_short, 4),
            "delta": round(p_long - p_short, 4),
        },
        "last_price": round(current_price, 2),
        "latest_candle": {
            "time": candles[idx].get("time"),
            "datetime_label": candles[idx].get("datetime_label"),
        },
    }
