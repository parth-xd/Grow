"""
F&O Strategy Backtester v3 — Real-Time Entry Detection
========================================================
Scans 15-min candles through a full trading day like a live trader:
  - Uses prior days for indicator baseline
  - Walks candle-by-candle, runs technicals at each bar
  - Enters when signals align (no fixed midpoint split)
  - Sets Entry / SL / TP from technicals + ATR
  - Predicts trajectory from entry, compares to actual
  - Chart: full day price + predicted vs actual from entry

Supports BOTH indices (NIFTY, BANKNIFTY, etc.) AND equities.
"""

import logging
import random
import math
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST INSTRUMENT UNIVERSE (Indices + Equities)
# ═══════════════════════════════════════════════════════════════════════════════

BACKTEST_INSTRUMENTS = {
    # ── Indices ──
    "NIFTY":      {"lot_size": 75,   "exchange": "NSE", "type": "index", "underlying": "NIFTY",      "label": "NIFTY 50"},
    "BANKNIFTY":  {"lot_size": 15,   "exchange": "NSE", "type": "index", "underlying": "BANKNIFTY",  "label": "BANK NIFTY"},
    "FINNIFTY":   {"lot_size": 25,   "exchange": "NSE", "type": "index", "underlying": "FINNIFTY",   "label": "FIN NIFTY"},
    "SENSEX":     {"lot_size": 10,   "exchange": "BSE", "type": "index", "underlying": "SENSEX",     "label": "SENSEX"},
    "MIDCPNIFTY": {"lot_size": 50,   "exchange": "NSE", "type": "index", "underlying": "MIDCPNIFTY", "label": "MIDCAP NIFTY"},
    # ── Equities ──
    "RELIANCE":   {"lot_size": 250,  "exchange": "NSE", "type": "stock", "underlying": "RELIANCE",   "label": "Reliance Industries"},
    "TCS":        {"lot_size": 175,  "exchange": "NSE", "type": "stock", "underlying": "TCS",        "label": "TCS"},
    "INFY":       {"lot_size": 300,  "exchange": "NSE", "type": "stock", "underlying": "INFY",       "label": "Infosys"},
    "HDFCBANK":   {"lot_size": 550,  "exchange": "NSE", "type": "stock", "underlying": "HDFCBANK",   "label": "HDFC Bank"},
    "ICICIBANK":  {"lot_size": 700,  "exchange": "NSE", "type": "stock", "underlying": "ICICIBANK",  "label": "ICICI Bank"},
    "SBIN":       {"lot_size": 750,  "exchange": "NSE", "type": "stock", "underlying": "SBIN",       "label": "SBI"},
    "BAJFINANCE": {"lot_size": 125,  "exchange": "NSE", "type": "stock", "underlying": "BAJFINANCE", "label": "Bajaj Finance"},
    "TATASTEEL":  {"lot_size": 500,  "exchange": "NSE", "type": "stock", "underlying": "TATASTEEL",  "label": "Tata Steel"},
    "ITC":        {"lot_size": 1600, "exchange": "NSE", "type": "stock", "underlying": "ITC",        "label": "ITC"},
    "AXISBANK":   {"lot_size": 600,  "exchange": "NSE", "type": "stock", "underlying": "AXISBANK",   "label": "Axis Bank"},
    "KOTAKBANK":  {"lot_size": 400,  "exchange": "NSE", "type": "stock", "underlying": "KOTAKBANK",  "label": "Kotak Mahindra Bank"},
    "HINDUNILVR": {"lot_size": 300,  "exchange": "NSE", "type": "stock", "underlying": "HINDUNILVR", "label": "Hindustan Unilever"},
    "LT":         {"lot_size": 150,  "exchange": "NSE", "type": "stock", "underlying": "LT",         "label": "Larsen & Toubro"},
    "WIPRO":      {"lot_size": 1500, "exchange": "NSE", "type": "stock", "underlying": "WIPRO",      "label": "Wipro"},
    "MARUTI":     {"lot_size": 100,  "exchange": "NSE", "type": "stock", "underlying": "MARUTI",     "label": "Maruti Suzuki"},
}


# ═══════════════════════════════════════════════════════════════════════════════
# INTRADAY DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_intraday_candles(instrument_key, days=15):
    """
    Fetch 15-minute candle data.
    Uses fno_trader's cached function when the instrument exists there,
    otherwise calls the Groww API directly for equities.
    """
    inst = BACKTEST_INSTRUMENTS.get(instrument_key)
    if not inst:
        return []

    # Try fno_trader's cached function first
    try:
        from fno_trader import _fetch_historical_candles, ALL_FNO_INSTRUMENTS
        if instrument_key in ALL_FNO_INSTRUMENTS:
            return _fetch_historical_candles(instrument_key, days=days, interval="15minute")
    except Exception:
        pass

    # Check cache for equities
    cache_key = f"bt_15m:{instrument_key}:{days}"
    try:
        from db_manager import get_cached
        cached = get_cached(cache_key, ttl_seconds=3600)
        if cached:
            return cached
    except Exception:
        pass

    # Direct Groww API call for equities not in fno_trader
    try:
        from fno_trader import _get_groww
        groww = _get_groww()
        now = datetime.now()
        start = now - timedelta(days=days)

        data = groww.get_historical_candle_data(
            trading_symbol=inst["underlying"],
            exchange=inst["exchange"],
            segment="CASH",
            start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=now.strftime("%Y-%m-%d %H:%M:%S"),
            interval_in_minutes=15,
        )

        if data and data.get("candles"):
            candles = []
            for c in data["candles"]:
                if isinstance(c, (list, tuple)) and len(c) >= 5:
                    ts = c[0] / 1000 if c[0] > 1e12 else c[0]
                    candles.append({
                        "timestamp": ts,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5]) if len(c) > 5 else 0,
                    })
            candles.sort(key=lambda x: x["timestamp"])

            try:
                from db_manager import set_cached
                set_cached(cache_key, candles, cache_type="bt_15m")
            except Exception:
                pass

            return candles
    except Exception as e:
        logger.error("Failed to fetch 15m candles for %s: %s", instrument_key, e)

    return []


def _group_candles_by_date(candles):
    """Group 15-min candles by trading date, adding time labels."""
    by_date = {}
    for c in candles:
        ts = c["timestamp"]
        dt = datetime.fromtimestamp(ts)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M")
        if date_str not in by_date:
            by_date[date_str] = []
        by_date[date_str].append({**c, "date": date_str, "time": time_str})
    for date_str in by_date:
        by_date[date_str].sort(key=lambda x: x["timestamp"])
    return by_date


def _generate_predicted_trajectory(entry_price, direction, confidence, num_candles, prior_candles):
    """
    Generate predicted price trajectory from entry point.
    Uses the recent candles' volatility to calibrate magnitude.
    """
    ranges = [c["high"] - c["low"] for c in prior_candles[-20:] if c["high"] > c["low"]]
    avg_range = sum(ranges) / len(ranges) if ranges else entry_price * 0.001

    dir_mult = 1.0 if direction == "BULLISH" else (-1.0 if direction == "BEARISH" else 0.0)
    drift = dir_mult * confidence * avg_range * 0.25

    prices = [entry_price]
    for i in range(1, num_candles):
        noise = random.gauss(0, avg_range * 0.08)
        momentum = 1 + 0.05 * (i / num_candles)
        prices.append(round(prices[-1] + drift * momentum + noise, 2))
    return prices


def _scan_for_entry(day_candles, prior_candles, min_candle=2, max_candle_pct=0.75):
    """
    Walk through the day candle-by-candle, re-run technicals at each bar.
    Return the first candle index where a strong enough signal appears.

    We skip the first 2 candles (opening volatility) and stop at 75%
    of the day (need room to trade after entry).

    Returns (entry_idx, tech, analysis) or (None, None, None) if no signal.
    """
    max_candle = int(len(day_candles) * max_candle_pct)
    best_entry = None
    best_score = 0
    best_tech = None
    best_analysis = None

    for idx in range(min_candle, max_candle):
        # Build rolling window: prior days + today up to this candle
        window = prior_candles + day_candles[:idx + 1]
        closes = [c["close"] for c in window]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        volumes = [c.get("volume", 0) for c in window]
        current_price = day_candles[idx]["close"]

        if len(closes) < 40:
            continue

        tech = _analyze_technicals_pure(closes, highs, lows, volumes, current_price)

        # Price change from open to this candle
        open_price = day_candles[0]["open"]
        change_pct = ((current_price - open_price) / open_price) * 100 if open_price else 0

        analysis = _simulate_analysis(tech, change_pct)

        # Need at least moderate strength to enter
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

        # If strong signal, take it immediately (don't wait for better)
        if analysis["strength"] == "strong" and score > 0.25:
            return idx, tech, analysis

    return best_entry, best_tech, best_analysis


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATOR FUNCTIONS (pure — no API calls)
# Duplicated from fno_trader to run on arbitrary historical slices
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
# PURE TECHNICAL ANALYSIS (no API calls)
# ═══════════════════════════════════════════════════════════════════════════════

def _analyze_technicals_pure(closes, highs, lows, volumes, current_price):
    """
    Run full technical analysis on historical price data.
    Returns the same structure as fno_trader.compute_technicals() but pure.
    """
    result = {"current_price": current_price, "candle_count": len(closes)}

    # RSI
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

    # MACD
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

    # EMAs
    for period in (9, 21, 50):
        e = _ema(closes, period)
        if e is not None:
            result[f"ema_{period}"] = round(e, 2)

    # EMA crossover
    ema9 = result.get("ema_9")
    ema21 = result.get("ema_21")
    if ema9 and ema21:
        if ema9 > ema21 and current_price > ema9:
            result["ema_signal"] = "BULLISH"
        elif ema9 < ema21 and current_price < ema9:
            result["ema_signal"] = "BEARISH"
        else:
            result["ema_signal"] = "NEUTRAL"

    # Bollinger Bands
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

    # Stochastic
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

    # Support & Resistance
    if len(highs) >= 10:
        recent_highs = sorted(highs[-20:], reverse=True)
        recent_lows = sorted(lows[-20:])
        result["resistance"] = round(recent_highs[0], 2)
        result["support"] = round(recent_lows[0], 2)

    # Volume trend
    if len(volumes) >= 10 and any(v > 0 for v in volumes):
        avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1]
        if avg_vol > 0:
            result["volume_ratio"] = round(recent_vol / avg_vol, 2)
            result["volume_signal"] = "HIGH" if recent_vol > avg_vol * 1.5 else ("LOW" if recent_vol < avg_vol * 0.5 else "NORMAL")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL SCORING (mirrors fno_trader.analyze_fno_opportunity)
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
    """Score technicals exactly as fno_trader does."""
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
    Simulate the 7-signal analysis using technicals + synthetic scores
    for non-technical signals (news, OI, etc.).

    For backtesting, we compute technicals fully. Other signals are
    simulated from the actual price movement — a realistic proxy for
    "what signals would have looked like."
    """
    signals = {}
    reasons = []
    weighted_score = 0.0

    # 1. Technicals (25%)
    tech_result = _score_technicals(tech)
    weighted_score += tech_result["score"] * _SIGNAL_WEIGHTS["technicals"]
    signals["technicals"] = tech_result
    reasons.append(f"Technicals: {tech_result['signal']} (RSI={tech.get('rsi', '?')}, MACD={tech_result['macd_direction']}, EMA={tech_result['ema_signal']})")

    # 2. Trend (10%)
    trend_score = max(-1, min(1, change_pct / 3))
    weighted_score += trend_score * _SIGNAL_WEIGHTS["trend"]
    trend_signal = "BULLISH" if change_pct > 1 else ("BEARISH" if change_pct < -1 else "NEUTRAL")
    signals["trend"] = {"signal": trend_signal, "change_pct": round(change_pct, 2), "score": round(trend_score, 3)}
    reasons.append(f"Price: {'+' if change_pct > 0 else ''}{change_pct:.1f}% — {trend_signal.lower()}")

    # 3-7. Simulated non-technical signals
    # These are unknown in backtesting — anchor near zero with light
    # correlation to technicals so they don't false-amplify direction.
    noise_factor = tech_result["score"] * 0.15  # very light correlation
    for source, label in [("news", "News"), ("x_social", "X/Social"),
                          ("oi_pcr", "OI/PCR"), ("geopolitical", "Geopolitical"),
                          ("global", "Global")]:
        sim_score = noise_factor + random.uniform(-0.25, 0.25)
        sim_score = max(-1, min(1, sim_score))
        weighted_score += sim_score * _SIGNAL_WEIGHTS[source]
        sig = "BULLISH" if sim_score > 0.15 else ("BEARISH" if sim_score < -0.15 else "NEUTRAL")
        signals[source] = {"signal": sig, "score": round(sim_score, 3), "simulated": True}
        reasons.append(f"{label}: {sig} (sim: {sim_score:.2f})")

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
# OPTION PREMIUM SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_option_premium(spot_price, direction, lot_size):
    """Simulate a realistic ATM/slightly-OTM option premium."""
    if spot_price > 50000:
        base_premium = random.uniform(80, 200)
    elif spot_price > 20000:
        base_premium = random.uniform(80, 200)
    elif spot_price > 40000:
        base_premium = random.uniform(100, 250)
    else:
        base_premium = random.uniform(50, 150)
    return round(base_premium, 2)


def _calculate_trade_levels(tech, entry_price, direction, observation):
    """
    Calculate Entry, Stop-Loss, Take-Profit, and Risk:Reward.
    Tuned for intraday 15-min candles — uses tight ATR-based levels
    with support/resistance as nudge guides (not hard targets).
    """
    # ATR from observation candle ranges
    ranges = [c["high"] - c["low"] for c in observation if c["high"] > c["low"]]
    atr = sum(ranges) / len(ranges) if ranges else entry_price * 0.003

    support = tech.get("support")
    resistance = tech.get("resistance")

    # Intraday SL: 1.2–1.8x ATR (nudge toward S/R if nearby)
    # Intraday TP: 2.0–3.0x ATR (nudge toward S/R if nearby)
    if direction == "BULLISH":
        base_sl = entry_price - atr * 1.5
        # If support is close and below entry, tighten SL to it
        if support and support < entry_price and support > entry_price - atr * 3:
            base_sl = max(base_sl, support - atr * 0.2)
        sl = round(base_sl, 2)

        risk = entry_price - sl
        base_tp = entry_price + risk * 2.2
        # If resistance is close, use it as TP guide
        if resistance and resistance > entry_price and resistance < entry_price + atr * 5:
            base_tp = min(base_tp, max(resistance, entry_price + risk * 1.5))
        tp = round(base_tp, 2)

    elif direction == "BEARISH":
        base_sl = entry_price + atr * 1.5
        if resistance and resistance > entry_price and resistance < entry_price + atr * 3:
            base_sl = min(base_sl, resistance + atr * 0.2)
        sl = round(base_sl, 2)

        risk = sl - entry_price
        base_tp = entry_price - risk * 2.2
        if support and support < entry_price and support > entry_price - atr * 5:
            base_tp = max(base_tp, min(support, entry_price - risk * 1.5))
        tp = round(base_tp, 2)
    else:
        sl = round(entry_price - atr * 1.0, 2)
        tp = round(entry_price + atr * 1.0, 2)

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
        "atr": round(atr, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# INTRADAY TRADE SIMULATION (tuned for 15-min candles)
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_intraday_trade(candles, entry_idx, entry_premium, direction, lot_size, config, trade_levels=None):
    """
    Simulate a trade through 15-min candle-by-candle price action.
    Uses delta-based absolute premium change (ATM options).
    Delta ~0.5 for ATM: 1pt spot move → ~0.5pt premium move.
    """
    sl_pct = config.get("stop_loss_pct", 50)
    target_pct = config.get("target_pct", 80)
    trailing_trigger = config.get("trailing_sl_pct", 30)

    spot_sl = trade_levels["stop_loss"] if trade_levels else None
    spot_tp = trade_levels["take_profit"] if trade_levels else None
    entry_spot = candles[entry_idx]["close"]

    # ATM delta with small noise per trade (consistent within a trade)
    delta = random.uniform(0.42, 0.52)
    # Theta per 15-min candle (very small intraday — ~₹0.5-1.5 per candle for ATM)
    theta_per_candle = entry_premium * 0.0015  # ~0.15% per candle

    def _calc_premium(spot_price, candles_elapsed):
        """Calculate premium from spot using delta-based absolute change."""
        spot_move = spot_price - entry_spot
        if direction == "BULLISH":
            prem_delta = spot_move * delta
        else:
            prem_delta = -spot_move * delta
        theta_decay = theta_per_candle * candles_elapsed
        prem = entry_premium + prem_delta - theta_decay
        # Add micro noise (bid-ask spread simulation)
        noise = random.uniform(-0.3, 0.3)
        return max(0.05, round(prem + noise, 2))

    timeline = []
    peak_premium = entry_premium
    exit_premium = None
    exit_reason = None
    exit_idx = None
    sl_hit = False
    tp_hit = False
    exit_spot = None

    for i in range(entry_idx + 1, len(candles)):
        c = candles[i]
        spot_change = ((c["close"] - entry_spot) / entry_spot) * 100
        candles_elapsed = i - entry_idx

        current_premium = _calc_premium(c["close"], candles_elapsed)
        pnl_pct = ((current_premium - entry_premium) / entry_premium) * 100

        if current_premium > peak_premium:
            peak_premium = current_premium

        event = {
            "candle_idx": i,
            "timestamp": c.get("timestamp", ""),
            "date": c.get("date", ""),
            "time": c.get("time", ""),
            "spot_price": round(c["close"], 2),
            "spot_change_pct": round(spot_change, 2),
            "premium": current_premium,
            "pnl_pct": round(pnl_pct, 2),
            "peak_premium": round(peak_premium, 2),
        }

        # ── Spot-level SL/TP exits (priority) ─────────────────────────
        if spot_sl is not None and direction == "BULLISH" and c["low"] <= spot_sl:
            event["action"] = "STOP_LOSS_HIT"
            sl_hit = True
            exit_spot = spot_sl
            exit_premium = _calc_premium(spot_sl, candles_elapsed)
            exit_reason = f"Stop-loss hit at ₹{spot_sl} (entry ₹{entry_spot})"
            exit_idx = i
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = spot_sl
            timeline.append(event)
            break

        if spot_sl is not None and direction == "BEARISH" and c["high"] >= spot_sl:
            event["action"] = "STOP_LOSS_HIT"
            sl_hit = True
            exit_spot = spot_sl
            exit_premium = _calc_premium(spot_sl, candles_elapsed)
            exit_reason = f"Stop-loss hit at ₹{spot_sl} (entry ₹{entry_spot})"
            exit_idx = i
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = spot_sl
            timeline.append(event)
            break

        if spot_tp is not None and direction == "BULLISH" and c["high"] >= spot_tp:
            event["action"] = "TARGET_HIT"
            tp_hit = True
            exit_spot = spot_tp
            exit_premium = _calc_premium(spot_tp, candles_elapsed)
            exit_reason = f"Target hit at ₹{spot_tp} (entry ₹{entry_spot})"
            exit_idx = i
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = spot_tp
            timeline.append(event)
            break

        if spot_tp is not None and direction == "BEARISH" and c["low"] <= spot_tp:
            event["action"] = "TARGET_HIT"
            tp_hit = True
            exit_spot = spot_tp
            exit_premium = _calc_premium(spot_tp, candles_elapsed)
            exit_reason = f"Target hit at ₹{spot_tp} (entry ₹{entry_spot})"
            exit_idx = i
            event["premium"] = exit_premium
            event["pnl_pct"] = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)
            event["spot_price"] = spot_tp
            timeline.append(event)
            break

        # ── Fallback premium-based exits ───────────────────────────────
        if pnl_pct <= -sl_pct:
            event["action"] = "PREMIUM_SL_EXIT"
            exit_premium = current_premium
            exit_spot = c["close"]
            exit_reason = f"Premium stop-loss at {pnl_pct:.1f}% (threshold: -{sl_pct}%)"
            exit_idx = i
            sl_hit = True
            timeline.append(event)
            break
        elif pnl_pct >= target_pct:
            event["action"] = "PREMIUM_TP_EXIT"
            exit_premium = current_premium
            exit_spot = c["close"]
            tp_hit = True
            exit_reason = f"Premium target at {pnl_pct:.1f}% (threshold: +{target_pct}%)"
            exit_idx = i
            timeline.append(event)
            break
        elif pnl_pct > trailing_trigger and peak_premium > 0:
            drawdown_from_peak = ((peak_premium - current_premium) / peak_premium) * 100
            if drawdown_from_peak > 15:
                event["action"] = "TRAILING_SL_EXIT"
                exit_premium = current_premium
                exit_spot = c["close"]
                exit_reason = f"Trailing SL: {drawdown_from_peak:.1f}% drop from peak ₹{peak_premium}"
                exit_idx = i
                timeline.append(event)
                break

        timeline.append(event)

    # If no exit triggered, close at last candle (EOD)
    if exit_premium is None and timeline:
        last = timeline[-1]
        exit_premium = last["premium"]
        exit_spot = last["spot_price"]
        exit_reason = "Position closed at end of day"
        exit_idx = len(candles) - 1
        timeline[-1]["action"] = "EOD_EXIT"

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
        "pnl_per_unit": round(pnl_per_unit, 2),
        "total_pnl": round(total_pnl - total_charges, 2),
        "total_pnl_pct": round(pnl_pct, 2),
        "total_charges": round(total_charges, 2),
        "peak_premium": round(peak_premium, 2),
        "lot_size": lot_size,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN BACKTEST — REAL-TIME ENTRY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def run_fno_backtest(instrument_key=None, target_date=None, days_back=None):
    """
    Run intraday F&O backtest using 15-minute candles.

    Scans through the full day like a real trader:
      - Uses prior days for indicator baseline
      - Walks candle-by-candle looking for entry signals
      - Enters when technicals align, sets SL/TP from ATR + S/R
      - Simulates trade through remaining candles
      - Predicts trajectory from entry, compares to actual

    Chart shows: full day actual + predicted path from entry + levels

    Args:
        instrument_key: e.g. "NIFTY", "RELIANCE". Random if None.
        target_date: "YYYY-MM-DD". Random recent day if None.

    Returns:
        Complete backtest with chart data for entry-based visualization.
    """
    if not instrument_key:
        instrument_key = random.choice(["NIFTY", "BANKNIFTY", "RELIANCE", "TCS"])

    inst = BACKTEST_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    lot_size = inst["lot_size"]

    # ── Fetch 15-minute candles ────────────────────────────────────────────
    candles = _fetch_intraday_candles(instrument_key, days=15)
    if len(candles) < 50:
        return {"error": f"Insufficient 15-min data for {instrument_key}: only {len(candles)} candles (need ≥50)"}

    by_date = _group_candles_by_date(candles)
    available_dates = sorted(by_date.keys())

    # ── Pick target date ───────────────────────────────────────────────────
    if target_date:
        if target_date not in by_date:
            return {"error": f"Date {target_date} not in 15-min data. Available: {', '.join(available_dates[-5:])}"}
    else:
        valid_dates = [d for d in available_dates if len(by_date[d]) >= 15]
        if not valid_dates:
            return {"error": "No complete trading days found in 15-min data"}
        target_date = random.choice(valid_dates[:-1]) if len(valid_dates) > 1 else valid_dates[0]

    day_candles = by_date[target_date]
    if len(day_candles) < 10:
        return {"error": f"Incomplete data for {target_date}: only {len(day_candles)} candles (need ≥10)"}

    # ── Build prior-days candle history for indicator baseline ─────────────
    prior_candles = []
    for d in available_dates:
        if d < target_date:
            prior_candles.extend(by_date[d])

    open_price = day_candles[0]["open"]
    close_price = day_candles[-1]["close"]

    # ── Scan for entry signal ──────────────────────────────────────────────
    entry_idx, tech, analysis = _scan_for_entry(day_candles, prior_candles)

    if entry_idx is None:
        # No signal found — still return full day data for chart
        # Run analysis on full day for info display
        all_candles = prior_candles + day_candles
        closes = [c["close"] for c in all_candles]
        highs = [c["high"] for c in all_candles]
        lows = [c["low"] for c in all_candles]
        volumes = [c.get("volume", 0) for c in all_candles]
        day_change = ((close_price - open_price) / open_price) * 100 if open_price else 0
        tech = _analyze_technicals_pure(closes, highs, lows, volumes, close_price)
        analysis = _simulate_analysis(tech, day_change)

        return {
            "instrument": instrument_key,
            "label": inst.get("label", instrument_key),
            "type": inst.get("type", "index"),
            "lot_size": lot_size,
            "target_date": target_date,
            "market_open": day_candles[0]["time"],
            "market_close": day_candles[-1]["time"],
            "open_price": round(open_price, 2),
            "close_price": round(close_price, 2),
            "total_candles": len(day_candles),
            "entry_time": None,
            "entry_candle_idx": None,
            "analysis": analysis,
            "chart": {
                "times": [c["time"] for c in day_candles],
                "prices": [round(c["close"], 2) for c in day_candles],
                "predicted": None,
            },
            "discrepancy": None,
            "trade_simulation": {
                "would_trade": False,
                "reason": "No entry signal found — all candles scanned, signals too weak",
                "direction": analysis["direction"],
                "strength": analysis["strength"],
                "trade_levels": None,
            },
            "technicals": _extract_technicals(tech),
        }

    # ── Entry found! ───────────────────────────────────────────────────────
    entry_price = day_candles[entry_idx]["close"]
    entry_time = day_candles[entry_idx]["time"]

    # Candles before entry (for ATR / levels calculation)
    candles_before_entry = prior_candles + day_candles[:entry_idx + 1]

    # Trade levels from technicals
    trade_levels = _calculate_trade_levels(tech, entry_price, analysis["direction"], candles_before_entry)

    # ── Generate predicted trajectory from entry ───────────────────────────
    remaining_candles = day_candles[entry_idx:]  # entry candle through EOD
    num_remaining = len(remaining_candles)

    predicted_prices = _generate_predicted_trajectory(
        entry_price, analysis["direction"], analysis["confidence"],
        num_remaining, candles_before_entry,
    )
    actual_prices_from_entry = [round(c["close"], 2) for c in remaining_candles]
    times_from_entry = [c["time"] for c in remaining_candles]

    # ── Discrepancy metrics ────────────────────────────────────────────────
    predicted_end = predicted_prices[-1]
    actual_end = actual_prices_from_entry[-1]
    predicted_change = ((predicted_end - entry_price) / entry_price) * 100 if entry_price else 0
    actual_change = ((actual_end - entry_price) / entry_price) * 100 if entry_price else 0

    direction_correct = (
        (analysis["direction"] == "BULLISH" and actual_change > 0) or
        (analysis["direction"] == "BEARISH" and actual_change < 0) or
        (analysis["direction"] == "NEUTRAL")
    )

    deviations = []
    for p, a in zip(predicted_prices, actual_prices_from_entry):
        dev = abs(p - a) / a * 100 if a > 0 else 0
        deviations.append(dev)
    avg_deviation = sum(deviations) / len(deviations) if deviations else 0

    # ── Trade simulation from entry ────────────────────────────────────────
    entry_premium = _simulate_option_premium(entry_price, analysis["direction"], lot_size)
    option_type = "CE" if analysis["direction"] == "BULLISH" else "PE"

    sim = _simulate_intraday_trade(
        candles=remaining_candles,
        entry_idx=0,
        entry_premium=entry_premium,
        direction=analysis["direction"],
        lot_size=lot_size,
        config={"stop_loss_pct": 50, "target_pct": 80, "trailing_sl_pct": 30},
        trade_levels=trade_levels,
    )

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

    # ── Build chart data ───────────────────────────────────────────────────
    return {
        "instrument": instrument_key,
        "label": inst.get("label", instrument_key),
        "type": inst.get("type", "index"),
        "lot_size": lot_size,
        "target_date": target_date,
        "market_open": day_candles[0]["time"],
        "market_close": day_candles[-1]["time"],
        "open_price": round(open_price, 2),
        "close_price": round(close_price, 2),
        "total_candles": len(day_candles),
        "entry_time": entry_time,
        "entry_price": round(entry_price, 2),
        "entry_candle_idx": entry_idx,
        "analysis": analysis,
        "chart": {
            "times": [c["time"] for c in day_candles],
            "prices": [round(c["close"], 2) for c in day_candles],
            "highs": [round(c["high"], 2) for c in day_candles],
            "lows": [round(c["low"], 2) for c in day_candles],
            "predicted": {
                "times": times_from_entry,
                "prices": [round(p, 2) for p in predicted_prices],
            },
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

def get_available_backtest_dates(instrument_key="NIFTY"):
    """Get list of dates available for 15-min intraday backtesting."""
    candles = _fetch_intraday_candles(instrument_key, days=15)
    if not candles:
        return {"instrument": instrument_key, "dates": [], "total": 0}

    by_date = _group_candles_by_date(candles)

    dates = []
    for d in sorted(by_date.keys()):
        day = by_date[d]
        if len(day) >= 10:  # only days with enough candles
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
# MULTI-DAY AGGREGATE BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

def run_multi_backtest(instrument_key="NIFTY", num_days=10):
    """Run backtests on multiple days for aggregate stats."""
    candles = _fetch_intraday_candles(instrument_key, days=20)
    if len(candles) < 50:
        return {"error": "Insufficient 15-min data for multi-day backtest"}

    by_date = _group_candles_by_date(candles)
    valid_dates = [d for d in sorted(by_date.keys()) if len(by_date[d]) >= 10]

    if len(valid_dates) < 2:
        return {"error": "Not enough complete trading days"}

    test_dates = valid_dates[:-1]  # exclude latest (may be incomplete)
    random.shuffle(test_dates)
    test_dates = test_dates[:num_days]

    results = []
    wins, losses, total_pnl = 0, 0, 0
    direction_correct_count = 0
    entries_found = 0

    for date_str in sorted(test_dates):
        bt = run_fno_backtest(instrument_key, target_date=date_str)
        if "error" in bt:
            continue

        entry = {
            "date": date_str,
            "direction": bt["analysis"]["direction"],
            "confidence": bt["analysis"]["confidence"],
        }

        disc = bt.get("discrepancy")
        if disc:
            entry["direction_correct"] = disc["direction_correct"]
            entry["predicted_change_pct"] = disc["predicted_change_pct"]
            entry["actual_change_pct"] = disc["actual_change_pct"]
            entry["avg_deviation_pct"] = disc.get("avg_deviation_pct", 0)
            if disc["direction_correct"]:
                direction_correct_count += 1
        else:
            entry["direction_correct"] = False
            entry["predicted_change_pct"] = 0
            entry["actual_change_pct"] = 0

        trade = bt.get("trade_simulation", {})
        if trade.get("would_trade"):
            entries_found += 1
            entry["traded"] = True
            entry["entry_time"] = bt.get("entry_time", "")
            entry["entry_price"] = bt.get("entry_price", 0)
            entry["option_type"] = trade["option_type"]
            entry["pnl"] = trade["total_pnl"]
            entry["pnl_pct"] = trade["total_pnl_pct"]
            entry["exit_reason"] = trade["exit_reason"]
            entry["sl_hit"] = trade.get("sl_hit", False)
            entry["tp_hit"] = trade.get("tp_hit", False)
            total_pnl += trade["total_pnl"]
            if trade["total_pnl"] > 0:
                wins += 1
            else:
                losses += 1
        else:
            entry["traded"] = False
            entry["pnl"] = 0

        results.append(entry)

    total_trades = wins + losses
    return {
        "instrument": instrument_key,
        "days_tested": len(results),
        "entries_found": entries_found,
        "prediction_accuracy": round(direction_correct_count / len(results) * 100, 1) if results else 0,
        "trades_taken": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(total_pnl / total_trades, 2) if total_trades > 0 else 0,
        "results": results,
    }
