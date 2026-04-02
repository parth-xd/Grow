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
import random
import math
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Max trading days to hold a position
MAX_HOLD_DAYS = 7
MAX_HOLD_CANDLES = MAX_HOLD_DAYS * 7  # 7 candles per trading day (1hr)

# Minimum candles needed for technical indicators
MIN_BASELINE_CANDLES = 40


# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUMENT UNIVERSE — All stocks in the database
# ═══════════════════════════════════════════════════════════════════════════════

BACKTEST_INSTRUMENTS = {
    "ASIANPAINT":  {"lot_size": 300,   "label": "Asian Paints"},
    "BHARTIARTL":  {"lot_size": 950,   "label": "Bharti Airtel"},
    "GEMAROMA":    {"lot_size": 1000,  "label": "Gema Aroma"},
    "HDFCBANK":    {"lot_size": 550,   "label": "HDFC Bank"},
    "ICICIBANK":   {"lot_size": 700,   "label": "ICICI Bank"},
    "INFY":        {"lot_size": 300,   "label": "Infosys"},
    "ITC":         {"lot_size": 1600,  "label": "ITC"},
    "LT":          {"lot_size": 150,   "label": "Larsen & Toubro"},
    "MOTILALOFS":  {"lot_size": 400,   "label": "Motilal Oswal"},
    "ONGC":        {"lot_size": 3850,  "label": "ONGC"},
    "PIDILITIND":  {"lot_size": 250,   "label": "Pidilite Industries"},
    "RELIANCE":    {"lot_size": 250,   "label": "Reliance Industries"},
    "SBIN":        {"lot_size": 750,   "label": "SBI"},
    "SUZLON":      {"lot_size": 10000, "label": "Suzlon Energy"},
    "TCS":         {"lot_size": 175,   "label": "TCS"},
    "WIPRO":       {"lot_size": 1500,  "label": "Wipro"},
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE CANDLE FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_candles_from_db(symbol):
    """Fetch all 1-hour candles for a symbol from the candles table."""
    try:
        from db_manager import CandleDatabase, Candle
        db = CandleDatabase()
        session = db.Session()
        try:
            rows = (
                session.query(Candle)
                .filter(Candle.symbol == symbol)
                .order_by(Candle.timestamp)
                .all()
            )
            candles = []
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
            return candles
        finally:
            session.close()
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
    Simulate 7-signal analysis using technicals + synthetic scores.
    Non-technical signals use very light tech correlation so they
    don't amplify direction bias.
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

    noise_factor = tech_result["score"] * 0.15
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
# ENTRY SCANNING — walks candle-by-candle across all data
# ═══════════════════════════════════════════════════════════════════════════════

def _scan_for_entry(candles, start_idx=None):
    """
    Walk through candles from start_idx looking for entry signal.
    Skips first MIN_BASELINE_CANDLES candles (needed for indicators).
    Returns (entry_idx, tech, analysis) or (None, None, None).
    """
    if start_idx is None:
        start_idx = MIN_BASELINE_CANDLES

    # Don't scan the last few candles — need room for a trade
    max_idx = len(candles) - 7  # at least 1 day of candles after entry

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
    Uses daily ATR (sum of hourly ranges per day) for wider levels.
    """
    ranges = [c["high"] - c["low"] for c in prior_candles[-50:] if c["high"] > c["low"]]
    hourly_atr = sum(ranges) / len(ranges) if ranges else entry_price * 0.005
    # Daily ATR ≈ hourly ATR * sqrt(7) ... or more practically ~3x hourly
    daily_atr = hourly_atr * 3.0

    support = tech.get("support")
    resistance = tech.get("resistance")

    if direction == "BULLISH":
        base_sl = entry_price - daily_atr * 1.8
        if support and support < entry_price and support > entry_price - daily_atr * 4:
            base_sl = max(base_sl, support - hourly_atr * 0.5)
        sl = round(base_sl, 2)

        risk = entry_price - sl
        base_tp = entry_price + risk * 2.5
        if resistance and resistance > entry_price and resistance < entry_price + daily_atr * 6:
            base_tp = min(base_tp, max(resistance, entry_price + risk * 1.5))
        tp = round(base_tp, 2)

    elif direction == "BEARISH":
        base_sl = entry_price + daily_atr * 1.8
        if resistance and resistance > entry_price and resistance < entry_price + daily_atr * 4:
            base_sl = min(base_sl, resistance + hourly_atr * 0.5)
        sl = round(base_sl, 2)

        risk = sl - entry_price
        base_tp = entry_price - risk * 2.5
        if support and support < entry_price and support > entry_price - daily_atr * 6:
            base_tp = max(base_tp, min(support, entry_price - risk * 1.5))
        tp = round(base_tp, 2)
    else:
        sl = round(entry_price - daily_atr * 1.5, 2)
        tp = round(entry_price + daily_atr * 1.5, 2)

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
    """Simulate a realistic ATM option premium."""
    if spot_price > 5000:
        base_premium = random.uniform(80, 200)
    elif spot_price > 1000:
        base_premium = random.uniform(40, 120)
    elif spot_price > 100:
        base_premium = random.uniform(10, 50)
    else:
        base_premium = random.uniform(2, 15)
    return round(base_premium, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-DAY TRADE SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

def _simulate_swing_trade(candles, entry_idx, entry_premium, direction, lot_size, trade_levels):
    """
    Simulate a swing trade across multiple days using 1-hour candles.
    Exits on: spot SL/TP, trailing stop, max hold (7 days), or signal reversal.
    Uses delta-based premium changes.
    """
    entry_spot = candles[entry_idx]["close"]
    entry_date = candles[entry_idx]["date"]
    spot_sl = trade_levels["stop_loss"]
    spot_tp = trade_levels["take_profit"]

    # ATM delta with per-trade noise
    delta = random.uniform(0.42, 0.52)
    # Theta per candle: ~0.3% per 1hr candle for swing (higher than intraday)
    theta_per_candle = entry_premium * 0.003

    def _calc_premium(spot_price, candles_elapsed):
        spot_move = spot_price - entry_spot
        if direction == "BULLISH":
            prem_delta = spot_move * delta
        else:
            prem_delta = -spot_move * delta
        theta_decay = theta_per_candle * candles_elapsed
        noise = random.uniform(-0.3, 0.3)
        return max(0.05, round(entry_premium + prem_delta - theta_decay + noise, 2))

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
    """Generate predicted price trajectory from entry point."""
    ranges = [c["high"] - c["low"] for c in prior_candles[-30:] if c["high"] > c["low"]]
    avg_range = sum(ranges) / len(ranges) if ranges else entry_price * 0.003

    dir_mult = 1.0 if direction == "BULLISH" else (-1.0 if direction == "BEARISH" else 0.0)
    drift = dir_mult * confidence * avg_range * 0.20

    prices = [entry_price]
    for i in range(1, num_candles):
        noise = random.gauss(0, avg_range * 0.06)
        momentum = 1 + 0.03 * (i / num_candles)
        prices.append(round(prices[-1] + drift * momentum + noise, 2))
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
        instrument_key = random.choice(list(BACKTEST_INSTRUMENTS.keys()))

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
        # Random start point after baseline
        valid_range = len(candles) - MIN_BASELINE_CANDLES - 14
        if valid_range > 0:
            scan_start = MIN_BASELINE_CANDLES + random.randint(0, valid_range)

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
