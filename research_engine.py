"""
Unified Research Engine — One algorithm, every stock.

A single, consistent, multi-dimensional scoring framework applied
identically to every tracked stock.  The *same* algorithm produces
*different* results because the underlying data is different.

Dimensions scored (each 0–100):
  1. TECHNICAL STRUCTURE  — trend regime, momentum, mean-reversion, volume profile
  2. FUNDAMENTAL QUALITY  — earnings, balance sheet, capital efficiency, valuation
  3. INSTITUTIONAL FLOW   — FII/DII/promoter quarterly trends, delivery %
  4. SENTIMENT MOMENTUM   — news flow trend, sector rotation, commodity alignment
  5. RISK PROFILE         — volatility, drawdown, leverage, liquidity

Composite:
  ALPHA SCORE  — regime-adaptive weighted blend of all five dimensions
  CONVICTION   — statistical confidence in the composite view
  REGIME       — TRENDING_UP / DOWN / RANGE / BREAKOUT / BREAKDOWN

The output is a *Research Report* — not a simple BUY/SELL signal, but
a full institutional-grade breakdown any analyst could act on.
"""

import logging
import math
import re
import time
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta, date
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# ─────────────────────────────────────────────────────────────────────────────
# 0.  DATA LAYER — collect raw inputs from DB / Screener / API
# ─────────────────────────────────────────────────────────────────────────────

def _get_db_session():
    try:
        from db_manager import get_db
        from config import DB_URL
        return get_db(DB_URL).Session()
    except Exception:
        return None


def _safe_float(text):
    if text is None:
        return None
    cleaned = re.sub(r"[₹,%\s\xa0]", "", str(text).replace(",", "").replace("&nbsp;", ""))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _clamp(val, lo=0.0, hi=100.0):
    return max(lo, min(hi, val))


def _load_price_history(symbol, days=365):
    """Load OHLCV from DB candles table.  Returns DataFrame or empty."""
    session = _get_db_session()
    if not session:
        return pd.DataFrame()
    try:
        from db_manager import Candle
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = (
            session.query(Candle)
            .filter(Candle.symbol == symbol, Candle.timestamp >= cutoff)
            .order_by(Candle.timestamp)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        data = [{
            "timestamp": r.timestamp, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close, "volume": r.volume,
        } for r in rows]
        df = pd.DataFrame(data)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        logger.warning("Price history load failed for %s: %s", symbol, e)
        return pd.DataFrame()
    finally:
        session.close()


def _load_weekly_prices(symbol, years=5):
    """Load 5-year weekly prices from stock_prices table."""
    try:
        import psycopg2
        from config import DB_URL
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT date, open, high, low, close, volume FROM stock_prices "
            "WHERE symbol = %s ORDER BY date ASC", (symbol,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        logger.debug("Weekly prices load failed for %s: %s", symbol, e)
        return pd.DataFrame()


def _load_shareholding(symbol):
    """Load quarterly shareholding from DB."""
    try:
        import psycopg2
        from config import DB_URL
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT quarter_date, promoters, fiis, diis, government, public_pct, others, num_shareholders "
            "FROM shareholding_patterns WHERE symbol = %s ORDER BY quarter_date ASC", (symbol,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {"quarter_date": r[0], "promoters": r[1], "fiis": r[2], "diis": r[3],
             "government": r[4], "public": r[5], "others": r[6], "num_shareholders": r[7]}
            for r in rows
        ]
    except Exception:
        return []


def _load_recent_news(symbol, days=14):
    """Load recent news articles for this symbol from DB."""
    session = _get_db_session()
    if not session:
        return []
    try:
        from db_manager import NewsArticle
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = (
            session.query(NewsArticle)
            .filter(NewsArticle.symbol == symbol, NewsArticle.published_at >= cutoff)
            .order_by(NewsArticle.published_at.desc())
            .limit(50)
            .all()
        )
        return [{"title": r.title, "sentiment_score": r.sentiment_score or 0,
                 "sentiment": r.sentiment or "NEUTRAL", "published_at": r.published_at,
                 "source": r.source or ""} for r in rows]
    except Exception:
        return []
    finally:
        session.close()


def _load_commodity_data(symbol):
    """Load commodity linkage and latest snapshot."""
    session = _get_db_session()
    if not session:
        return None
    try:
        from db_manager import Stock, CommoditySnapshot
        stock = session.query(Stock).filter_by(symbol=symbol).first()
        if not stock or not stock.commodity:
            return None
        snap = session.query(CommoditySnapshot).filter_by(commodity=stock.commodity).first()
        return {
            "commodity": stock.commodity,
            "ticker": stock.commodity_ticker,
            "relationship": stock.commodity_relationship or "direct",
            "weight": float(stock.commodity_weight or 0.2),
            "price_change_1m": float(snap.price_change_1m or 0) if snap else 0,
            "price_change_3m": float(snap.price_change_3m or 0) if snap else 0,
            "trend": snap.trend if snap else "UNKNOWN",
        }
    except Exception:
        return None
    finally:
        session.close()


def _scrape_screener_ratios(symbol):
    """Quick scrape — key ratios + annual P&L from Screener.in."""
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code == 404:
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            return {}

        html = resp.text
        data = {}

        patterns = {
            "market_cap": r"Market Cap[^₹]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
            "pe_ratio": r"Stock P/E[^0-9]*([\d.]+)",
            "pb_ratio": r"Price to book value[^0-9]*([\d.]+)",
            "dividend_yield": r"Dividend Yield[^0-9]*([\d.]+)\s*%",
            "roce": r"ROCE[^0-9]*([\d.]+)\s*%",
            "roe": r"ROE[^0-9]*([\d.]+)\s*%",
            "debt_to_equity": r"Debt to equity[^0-9]*([\d.]+)",
            "interest_coverage": r"Interest Coverage[^0-9]*([\d.]+)",
            "promoter_holding": r"Promoter holding[^0-9]*([\d.]+)\s*%",
            "current_price": r"Current Price[^₹]*₹\s*([\d,]+(?:\.\d+)?)",
            "book_value": r"Book Value[^₹]*₹\s*([\d,]+(?:\.\d+)?)",
            "high_low": r"High / Low[^₹]*₹?\s*([\d,]+)\s*/\s*₹?\s*([\d,]+)",
            "face_value": r"Face Value[^₹]*₹\s*([\d.]+)",
            "industry_pe": r"Industry PE[^0-9]*([\d.]+)",
            "peg_ratio": r"PEG Ratio[^0-9]*([\d.]+)",
        }

        for key, pattern in patterns.items():
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                if key == "high_low":
                    data["52w_high"] = _safe_float(m.group(1))
                    data["52w_low"] = _safe_float(m.group(2))
                else:
                    data[key] = _safe_float(m.group(1))

        # Annual P&L rows — revenue / net_profit / eps / opm trends
        pl_idx = html.find('id="profit-loss"')
        if pl_idx != -1:
            section = html[pl_idx:pl_idx + 25000]
            table_m = re.search(r'<table[^>]*>(.*?)</table>', section, re.DOTALL)
            if table_m:
                table_html = table_m.group(1)
                tbody = re.search(r'</thead>\s*(.*)', table_html, re.DOTALL)
                if tbody:
                    rows_html = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.DOTALL)
                    key_map = {"sales": "revenue", "revenue": "revenue",
                               "net profit": "net_profit", "eps in rs": "eps",
                               "opm": "opm_pct",
                               "operating profit": "operating_profit"}
                    for row in rows_html:
                        label_m = re.search(r'class="text"[^>]*>\s*(?:<[^>]*>)*\s*([^<]+)', row)
                        if not label_m:
                            continue
                        raw_label = label_m.group(1).replace("&nbsp;", "").strip().lower()
                        k = None
                        for kk, vv in key_map.items():
                            if kk in raw_label:
                                k = vv
                                break
                        if not k:
                            continue
                        cells = re.findall(r'<td[^>]*>\s*([\d,.-]+)\s*</td>', row)
                        data[f"{k}_trend"] = [_safe_float(c) for c in cells]

        # Cash flow
        cf_idx = html.find('id="cash-flow"')
        if cf_idx != -1:
            section = html[cf_idx:cf_idx + 10000]
            # Operating cash flow latest
            ocf_match = re.search(
                r'Cash from Operating Activity.*?<td[^>]*>\s*([\d,.-]+)\s*</td>',
                section, re.DOTALL | re.IGNORECASE
            )
            if ocf_match:
                data["operating_cash_flow"] = _safe_float(ocf_match.group(1))
            # Capex (negative in investing)
            inv_rows = re.findall(r'<td[^>]*>\s*([\d,.-]+)\s*</td>', section)
            # Free cash flow row
            fcf_match = re.search(r'Free cash flow.*?<td[^>]*>\s*([\d,.-]+)\s*</td>',
                                  section, re.DOTALL | re.IGNORECASE)
            if fcf_match:
                data["free_cash_flow"] = _safe_float(fcf_match.group(1))

        # Balance sheet — debt, equity
        bs_idx = html.find('id="balance-sheet"')
        if bs_idx != -1:
            section = html[bs_idx:bs_idx + 15000]
            # Total equity
            eq_m = re.search(r'Equity Capital.*?<td[^>]*>\s*([\d,.-]+)\s*</td>',
                             section, re.DOTALL | re.IGNORECASE)
            if eq_m:
                data["equity_capital"] = _safe_float(eq_m.group(1))
            # Total borrowings
            borr_m = re.search(r'Borrowings.*?<td[^>]*>\s*([\d,.-]+)\s*</td>',
                               section, re.DOTALL | re.IGNORECASE)
            if borr_m:
                data["borrowings"] = _safe_float(borr_m.group(1))

        return data

    except Exception as e:
        logger.warning("Screener scrape failed for %s: %s", symbol, e)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 1.  TECHNICAL STRUCTURE SCORING (0-100)
# ─────────────────────────────────────────────────────────────────────────────

def _score_technical(df):
    """
    Multi-factor technical score from OHLCV data.

    Sub-factors (equal weight):
      A. Trend Strength        — ADX + multi-MA alignment
      B. Momentum              — ROC, RSI zone, MACD histogram
      C. Mean Reversion        — Bollinger %B, distance from VWAP
      D. Volume Profile        — OBV trend, relative volume, accumulation/distribution
      E. Breakout Proximity    — distance to 52w high/resistance, volatility squeeze
    """
    result = {"score": 50, "factors": {}, "regime": "UNKNOWN", "signals": []}

    if df.empty or len(df) < 50:
        result["factors"] = {"note": "Insufficient price data"}
        return result

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    open_ = df["open"]

    # ── A. Trend Strength ────────────────────────────────────────────────
    # ADX (Average Directional Index) — measures trend strength regardless of direction
    def _adx(h, l, c, period=14):
        plus_dm = h.diff()
        minus_dm = -l.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=period).mean()
        plus_di = 100 * (plus_dm.ewm(span=period).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.ewm(span=period).mean() / atr.replace(0, np.nan))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.ewm(span=period).mean()
        return adx, plus_di, minus_di

    adx, plus_di, minus_di = _adx(high, low, close)
    adx_val = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 20

    # Multi-MA alignment — how many EMAs are stacked correctly
    emas = {}
    for p in [10, 21, 50, 100, 200]:
        if len(close) >= p:
            emas[p] = float(close.ewm(span=p).mean().iloc[-1])

    current_price = float(close.iloc[-1])
    ma_alignment = 0  # -5 to +5
    sorted_emas = sorted(emas.values(), reverse=True)
    if sorted_emas == list(emas.values()):
        # Perfect bull stacking: price > ema10 > ema21 > ema50 > ema100 > ema200
        pass
    for p, v in emas.items():
        if current_price > v:
            ma_alignment += 1
        else:
            ma_alignment -= 1

    # Trend strength sub-score (0-100)
    trend_sub = 50
    if adx_val > 25:  # trending
        trend_direction = 1 if plus_di.iloc[-1] > minus_di.iloc[-1] else -1
        trend_sub = 50 + trend_direction * min((adx_val - 25) * 2, 30)
    # MA alignment bonus
    trend_sub += ma_alignment * 4
    trend_sub = _clamp(trend_sub)

    # ── B. Momentum ──────────────────────────────────────────────────────
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50

    # MACD histogram slope (last 5 bars)
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9).mean()
    hist = macd_line - macd_signal
    hist_slope = float(hist.iloc[-1] - hist.iloc[-5]) if len(hist) >= 5 else 0

    # Rate of Change (20-day)
    roc_20 = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0

    momentum_sub = 50
    # RSI contribution: 30-70 is neutral, outside is directional
    if rsi_val > 70:
        momentum_sub += min((rsi_val - 70) * 1.5, 20)
    elif rsi_val < 30:
        momentum_sub -= min((30 - rsi_val) * 1.5, 20)
    else:
        momentum_sub += (rsi_val - 50) * 0.5  # mild directional bias

    # MACD histogram: positive & rising = bullish, negative & falling = bearish
    if hist.iloc[-1] > 0 and hist_slope > 0:
        momentum_sub += 10
    elif hist.iloc[-1] < 0 and hist_slope < 0:
        momentum_sub -= 10

    # ROC 20
    momentum_sub += _clamp(roc_20 * 2, -15, 15)
    momentum_sub = _clamp(momentum_sub)

    # ── C. Mean Reversion ────────────────────────────────────────────────
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    bb_pct = float((close.iloc[-1] - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1]).item()) if (bb_upper.iloc[-1] - bb_lower.iloc[-1]) > 0 else 0.5

    # Z-score: how many std devs from 20-day mean
    z_score = float((close.iloc[-1] - sma20.iloc[-1]) / std20.iloc[-1]) if std20.iloc[-1] > 0 else 0

    # Mean reversion score: centered at 50, deviates based on position
    mean_rev_sub = 50
    if abs(z_score) > 2:
        # Extremely stretched — mean reversion likely
        mean_rev_sub = 50 - z_score * 10  # overbought → lower score
    else:
        mean_rev_sub = 50 - z_score * 5
    mean_rev_sub = _clamp(mean_rev_sub)

    # ── D. Volume Profile ────────────────────────────────────────────────
    vol_sma20 = volume.rolling(20).mean()
    rel_vol = float(volume.iloc[-1] / vol_sma20.iloc[-1]) if vol_sma20.iloc[-1] > 0 else 1

    # On-Balance Volume trend
    obv = pd.Series(0.0, index=close.index)
    obv_dir = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (obv_dir * volume).cumsum()
    obv_sma = obv.rolling(20).mean()
    obv_above = float(obv.iloc[-1] > obv_sma.iloc[-1])

    # Accumulation/Distribution — Chaikin Money Flow (20-day)
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfm = mfm.fillna(0)
    mfv = mfm * volume
    cmf = float(mfv.rolling(20).sum().iloc[-1] / volume.rolling(20).sum().iloc[-1]) if volume.rolling(20).sum().iloc[-1] > 0 else 0

    volume_sub = 50
    # Rising OBV with price = accumulation
    if obv_above and close.iloc[-1] > sma20.iloc[-1]:
        volume_sub += 15
    elif not obv_above and close.iloc[-1] < sma20.iloc[-1]:
        volume_sub -= 15

    # CMF: positive = buying pressure, negative = selling
    volume_sub += _clamp(cmf * 40, -15, 15)

    # Relative volume spike with upward price = bullish
    if rel_vol > 1.5 and close.iloc[-1] > close.iloc[-2]:
        volume_sub += 10
    elif rel_vol > 1.5 and close.iloc[-1] < close.iloc[-2]:
        volume_sub -= 10

    volume_sub = _clamp(volume_sub)

    # ── E. Breakout Proximity ────────────────────────────────────────────
    high_52w = float(high.rolling(min(252, len(high))).max().iloc[-1])
    low_52w = float(low.rolling(min(252, len(low))).min().iloc[-1])
    range_52w = high_52w - low_52w if high_52w > low_52w else 1

    pct_from_high = (high_52w - current_price) / current_price * 100
    pct_from_low = (current_price - low_52w) / current_price * 100

    # Bollinger bandwidth squeeze — low bandwidth → potential breakout
    bb_width = float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / sma20.iloc[-1] * 100) if sma20.iloc[-1] > 0 else 5
    bb_width_avg = float(((bb_upper - bb_lower) / sma20 * 100).rolling(100).mean().iloc[-1]) if len(close) >= 100 else bb_width
    squeeze = bb_width < bb_width_avg * 0.7  # width is 30% below average

    breakout_sub = 50
    if pct_from_high < 3:
        breakout_sub += 20  # near 52w high — breakout territory
        result["signals"].append("Within 3% of 52-week high")
    elif pct_from_high < 10:
        breakout_sub += 10
    if squeeze:
        breakout_sub += 10
        result["signals"].append("Volatility squeeze detected — breakout imminent")
    if pct_from_low < 5:
        breakout_sub -= 15  # near 52w low
        result["signals"].append("Near 52-week low — capitulation zone")

    breakout_sub = _clamp(breakout_sub)

    # ── REGIME CLASSIFICATION ────────────────────────────────────────────
    if adx_val > 25 and plus_di.iloc[-1] > minus_di.iloc[-1]:
        regime = "TRENDING_UP"
    elif adx_val > 25 and minus_di.iloc[-1] > plus_di.iloc[-1]:
        regime = "TRENDING_DOWN"
    elif squeeze:
        if ma_alignment > 0:
            regime = "BREAKOUT_IMMINENT"
        else:
            regime = "BREAKDOWN_IMMINENT"
    else:
        regime = "RANGE_BOUND"

    # ── COMPOSITE TECHNICAL SCORE ────────────────────────────────────────
    composite = (
        trend_sub * 0.25 +
        momentum_sub * 0.25 +
        mean_rev_sub * 0.15 +
        volume_sub * 0.20 +
        breakout_sub * 0.15
    )

    result["score"] = round(_clamp(composite), 1)
    result["regime"] = regime
    result["factors"] = {
        "trend_strength": round(trend_sub, 1),
        "momentum": round(momentum_sub, 1),
        "mean_reversion": round(mean_rev_sub, 1),
        "volume_profile": round(volume_sub, 1),
        "breakout_proximity": round(breakout_sub, 1),
        "adx": round(adx_val, 1),
        "rsi": round(rsi_val, 1),
        "macd_histogram": round(float(hist.iloc[-1]), 4),
        "z_score": round(z_score, 2),
        "relative_volume": round(rel_vol, 2),
        "cmf": round(cmf, 4),
        "pct_from_52w_high": round(pct_from_high, 1),
        "bb_squeeze": squeeze,
    }

    # Signals
    if rsi_val > 70:
        result["signals"].append(f"RSI overbought ({rsi_val:.0f})")
    elif rsi_val < 30:
        result["signals"].append(f"RSI oversold ({rsi_val:.0f})")
    if ma_alignment >= 4:
        result["signals"].append("Strong MA bull alignment")
    elif ma_alignment <= -4:
        result["signals"].append("Strong MA bear alignment")
    if cmf > 0.15:
        result["signals"].append("Heavy accumulation (CMF)")
    elif cmf < -0.15:
        result["signals"].append("Heavy distribution (CMF)")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2.  FUNDAMENTAL QUALITY SCORING (0-100)
# ─────────────────────────────────────────────────────────────────────────────

def _score_fundamental(screener_data):
    """
    Multi-factor fundamental quality score.

    Sub-factors:
      A. Earnings Quality     — growth consistency, acceleration, margin stability
      B. Balance Sheet        — Altman Z-score proxy, debt/equity, interest coverage
      C. Capital Efficiency   — ROCE, ROE, asset turnover proxy
      D. Growth Trajectory    — revenue CAGR, profit CAGR, EPS trend
      E. Valuation            — PE vs industry, PEG, price-to-book, FCF yield
    """
    result = {"score": 50, "factors": {}, "signals": [], "grade": "C"}

    if not screener_data:
        result["factors"] = {"note": "No fundamental data available"}
        return result

    # ── A. Earnings Quality ──────────────────────────────────────────────
    earnings_sub = 50
    net_profit_trend = screener_data.get("net_profit_trend", [])
    opm_trend = screener_data.get("opm_pct_trend", [])
    revenue_trend = screener_data.get("revenue_trend", [])

    if net_profit_trend and len(net_profit_trend) >= 3:
        # Consistency: how many years did profit grow YoY?
        valid = [x for x in net_profit_trend if x is not None]
        if len(valid) >= 3:
            growing = sum(1 for i in range(1, len(valid)) if valid[i] > valid[i - 1])
            consistency = growing / (len(valid) - 1)
            earnings_sub += (consistency - 0.5) * 30  # 0.5 baseline → +0 to +15

            # Acceleration: is latest growth accelerating?
            if len(valid) >= 3:
                g1 = (valid[-1] - valid[-2]) / abs(valid[-2]) if valid[-2] != 0 else 0
                g2 = (valid[-2] - valid[-3]) / abs(valid[-3]) if valid[-3] != 0 else 0
                if g1 > g2 and g1 > 0:
                    earnings_sub += 8
                    result["signals"].append("Profit growth accelerating")
                elif g1 < 0:
                    earnings_sub -= 8
    # Negative profit is a penalty
    if net_profit_trend and net_profit_trend[-1] is not None and net_profit_trend[-1] < 0:
        earnings_sub -= 20
        result["signals"].append("Company is loss-making")

    # OPM stability
    if opm_trend and len(opm_trend) >= 3:
        valid_opm = [x for x in opm_trend if x is not None]
        if valid_opm:
            opm_std = np.std(valid_opm)
            opm_mean = np.mean(valid_opm)
            if opm_std < 3 and opm_mean > 15:
                earnings_sub += 8  # stable high margins
                result["signals"].append(f"Stable high margins (OPM ~{opm_mean:.0f}%)")
            elif opm_mean < 8:
                earnings_sub -= 5

    earnings_sub = _clamp(earnings_sub)

    # ── B. Balance Sheet ─────────────────────────────────────────────────
    balance_sub = 60  # default: assume decent unless proven otherwise
    de = screener_data.get("debt_to_equity")
    icr = screener_data.get("interest_coverage")

    if de is not None:
        if de < 0.3:
            balance_sub += 15
            result["signals"].append(f"Low debt (D/E: {de:.1f})")
        elif de < 1.0:
            balance_sub += 5
        elif de > 2.0:
            balance_sub -= 15
            result["signals"].append(f"High leverage (D/E: {de:.1f})")
        elif de > 1.5:
            balance_sub -= 8

    if icr is not None:
        if icr > 5:
            balance_sub += 10
        elif icr < 2:
            balance_sub -= 15
            result["signals"].append(f"Low interest coverage ({icr:.1f}x)")

    # FCF positive is a strong signal
    fcf = screener_data.get("free_cash_flow")
    if fcf is not None:
        if fcf > 0:
            balance_sub += 8
        else:
            balance_sub -= 10
            result["signals"].append("Negative free cash flow")

    balance_sub = _clamp(balance_sub)

    # ── C. Capital Efficiency ────────────────────────────────────────────
    efficiency_sub = 50
    roce = screener_data.get("roce")
    roe = screener_data.get("roe")

    if roce is not None:
        if roce > 20:
            efficiency_sub += 20
            result["signals"].append(f"Excellent ROCE ({roce:.0f}%)")
        elif roce > 15:
            efficiency_sub += 12
        elif roce > 10:
            efficiency_sub += 5
        elif roce < 5:
            efficiency_sub -= 15

    if roe is not None:
        if roe > 20:
            efficiency_sub += 12
        elif roe > 15:
            efficiency_sub += 6
        elif roe < 5:
            efficiency_sub -= 10

    efficiency_sub = _clamp(efficiency_sub)

    # ── D. Growth Trajectory ─────────────────────────────────────────────
    growth_sub = 50
    rev = screener_data.get("revenue_trend", [])
    valid_rev = [x for x in rev if x is not None]
    eps_trend = screener_data.get("eps_trend", [])
    valid_eps = [x for x in (eps_trend or []) if x is not None]

    # Revenue CAGR (over available years)
    if len(valid_rev) >= 3:
        start_rev = valid_rev[0]
        end_rev = valid_rev[-1]
        n_years = len(valid_rev) - 1
        if start_rev > 0 and end_rev > 0:
            cagr = (end_rev / start_rev) ** (1 / n_years) - 1
            cagr_pct = cagr * 100
            if cagr_pct > 20:
                growth_sub += 20
                result["signals"].append(f"Revenue CAGR {cagr_pct:.0f}%")
            elif cagr_pct > 10:
                growth_sub += 10
            elif cagr_pct < 0:
                growth_sub -= 15
                result["signals"].append(f"Revenue declining (CAGR {cagr_pct:.0f}%)")

    # EPS trend
    if len(valid_eps) >= 3:
        growing_eps = sum(1 for i in range(1, len(valid_eps)) if valid_eps[i] > valid_eps[i - 1])
        growth_sub += (growing_eps / (len(valid_eps) - 1) - 0.5) * 20

    growth_sub = _clamp(growth_sub)

    # ── E. Valuation ─────────────────────────────────────────────────────
    valuation_sub = 50
    pe = screener_data.get("pe_ratio")
    industry_pe = screener_data.get("industry_pe")
    pb = screener_data.get("pb_ratio")
    peg = screener_data.get("peg_ratio")
    dy = screener_data.get("dividend_yield")
    mcap = screener_data.get("market_cap")

    if pe is not None:
        if industry_pe and industry_pe > 0:
            pe_discount = (industry_pe - pe) / industry_pe * 100
            if pe_discount > 20:
                valuation_sub += 15
                result["signals"].append(f"Undervalued vs industry (PE {pe:.0f} vs {industry_pe:.0f})")
            elif pe_discount < -30:
                valuation_sub -= 12
                result["signals"].append(f"Expensive vs industry (PE {pe:.0f} vs {industry_pe:.0f})")
        if pe < 15:
            valuation_sub += 8
        elif pe > 50:
            valuation_sub -= 12
        elif pe > 30:
            valuation_sub -= 5

    if peg is not None:
        if peg < 1:
            valuation_sub += 12
            result["signals"].append(f"PEG < 1 — growth at reasonable price")
        elif peg > 3:
            valuation_sub -= 8

    if dy is not None and dy > 2:
        valuation_sub += 5
        result["signals"].append(f"Dividend yield {dy:.1f}%")

    # FCF yield: FCF / Market Cap
    if fcf is not None and mcap is not None and mcap > 0:
        fcf_yield = fcf / mcap * 100
        if fcf_yield > 5:
            valuation_sub += 10
            result["signals"].append(f"High FCF yield ({fcf_yield:.1f}%)")
        elif fcf_yield < 0:
            valuation_sub -= 5

    valuation_sub = _clamp(valuation_sub)

    # ── COMPOSITE FUNDAMENTAL SCORE ──────────────────────────────────────
    composite = (
        earnings_sub * 0.25 +
        balance_sub * 0.20 +
        efficiency_sub * 0.20 +
        growth_sub * 0.20 +
        valuation_sub * 0.15
    )

    # Grade
    if composite >= 80:
        grade = "A+"
    elif composite >= 70:
        grade = "A"
    elif composite >= 60:
        grade = "B+"
    elif composite >= 50:
        grade = "B"
    elif composite >= 40:
        grade = "C"
    elif composite >= 30:
        grade = "D"
    else:
        grade = "F"

    result["score"] = round(_clamp(composite), 1)
    result["grade"] = grade
    result["factors"] = {
        "earnings_quality": round(earnings_sub, 1),
        "balance_sheet": round(balance_sub, 1),
        "capital_efficiency": round(efficiency_sub, 1),
        "growth_trajectory": round(growth_sub, 1),
        "valuation": round(valuation_sub, 1),
        "pe_ratio": pe,
        "roe": roe,
        "roce": roce,
        "debt_to_equity": de,
        "peg_ratio": peg,
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3.  INSTITUTIONAL FLOW SCORING (0-100)
# ─────────────────────────────────────────────────────────────────────────────

def _score_institutional(shareholding_data):
    """
    Score institutional conviction from quarterly shareholding trends.

    Sub-factors:
      A. FII Trend       — increasing FII% = smart money entering
      B. DII Trend       — increasing DII% = domestic conviction
      C. Promoter Signal — pledging declining or holding stable/increasing
      D. Retail Squeeze  — falling retail% means institutions accumulating
    """
    result = {"score": 50, "factors": {}, "signals": []}

    if not shareholding_data or len(shareholding_data) < 2:
        result["factors"] = {"note": "Insufficient shareholding data (need 2+ quarters)"}
        return result

    # Take last 4 quarters (or as many as available)
    recent = shareholding_data[-4:]
    latest = recent[-1]
    prev = recent[-2] if len(recent) >= 2 else recent[0]
    oldest = recent[0]

    # ── A. FII Trend ─────────────────────────────────────────────────────
    fii_sub = 50
    fii_latest = latest.get("fiis")
    fii_prev = prev.get("fiis")
    fii_oldest = oldest.get("fiis")

    if fii_latest is not None and fii_prev is not None:
        fii_qoq = fii_latest - fii_prev
        if fii_qoq > 1:
            fii_sub += 20
            result["signals"].append(f"FII increasing (+{fii_qoq:.1f}% QoQ)")
        elif fii_qoq > 0.3:
            fii_sub += 10
        elif fii_qoq < -1:
            fii_sub -= 20
            result["signals"].append(f"FII decreasing ({fii_qoq:.1f}% QoQ)")
        elif fii_qoq < -0.3:
            fii_sub -= 10

    # Long-term FII trend (oldest to latest)
    if fii_latest is not None and fii_oldest is not None:
        fii_long = fii_latest - fii_oldest
        if fii_long > 2:
            fii_sub += 10
        elif fii_long < -2:
            fii_sub -= 10

    fii_sub = _clamp(fii_sub)

    # ── B. DII Trend ─────────────────────────────────────────────────────
    dii_sub = 50
    dii_latest = latest.get("diis")
    dii_prev = prev.get("diis")

    if dii_latest is not None and dii_prev is not None:
        dii_qoq = dii_latest - dii_prev
        if dii_qoq > 1:
            dii_sub += 15
            result["signals"].append(f"DII accumulating (+{dii_qoq:.1f}% QoQ)")
        elif dii_qoq > 0.3:
            dii_sub += 8
        elif dii_qoq < -1:
            dii_sub -= 12
        elif dii_qoq < -0.3:
            dii_sub -= 6

    dii_sub = _clamp(dii_sub)

    # ── C. Promoter Signal ───────────────────────────────────────────────
    promoter_sub = 55  # slight positive baseline
    prom_latest = latest.get("promoters")
    prom_prev = prev.get("promoters")
    prom_oldest = oldest.get("promoters")

    if prom_latest is not None:
        if prom_latest > 60:
            promoter_sub += 10  # high promoter holding = skin in the game
        elif prom_latest < 30:
            promoter_sub -= 10  # very low promoter — governance risk

        if prom_prev is not None:
            prom_change = prom_latest - prom_prev
            if prom_change < -2:
                promoter_sub -= 15
                result["signals"].append(f"Promoter reducing stake ({prom_change:.1f}%)")
            elif prom_change > 0.5:
                promoter_sub += 10
                result["signals"].append(f"Promoter increasing stake (+{prom_change:.1f}%)")

    promoter_sub = _clamp(promoter_sub)

    # ── D. Retail Squeeze ────────────────────────────────────────────────
    retail_sub = 50
    pub_latest = latest.get("public")
    pub_prev = prev.get("public")

    if pub_latest is not None and pub_prev is not None:
        pub_change = pub_latest - pub_prev
        if pub_change < -1:
            retail_sub += 12  # retail exiting → institutions accumulating
            result["signals"].append("Retail exiting — institutional accumulation likely")
        elif pub_change > 2:
            retail_sub -= 10  # retail piling in — potential distribution
            result["signals"].append("Retail piling in — potential smart money distribution")

    retail_sub = _clamp(retail_sub)

    # ── COMPOSITE ────────────────────────────────────────────────────────
    composite = (
        fii_sub * 0.35 +
        dii_sub * 0.25 +
        promoter_sub * 0.25 +
        retail_sub * 0.15
    )

    result["score"] = round(_clamp(composite), 1)
    result["factors"] = {
        "fii_trend": round(fii_sub, 1),
        "dii_trend": round(dii_sub, 1),
        "promoter_signal": round(promoter_sub, 1),
        "retail_squeeze": round(retail_sub, 1),
        "fii_pct": fii_latest,
        "dii_pct": dii_latest,
        "promoter_pct": prom_latest,
        "public_pct": pub_latest,
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4.  SENTIMENT & NARRATIVE SCORING (0-100)
# ─────────────────────────────────────────────────────────────────────────────

def _score_sentiment(news_articles, commodity_data, sector):
    """
    Score the narrative environment around a stock.

    Sub-factors:
      A. News Flow         — recent sentiment trend (improving/deteriorating)
      B. News Volume       — high article count = high attention
      C. Commodity Alignment — tailwind or headwind from commodity movement
      D. Sector Momentum   — is the stock's sector in rotation favor?
    """
    result = {"score": 50, "factors": {}, "signals": []}

    # ── A. News Flow ─────────────────────────────────────────────────────
    news_sub = 50
    if news_articles:
        scores = [a["sentiment_score"] for a in news_articles if a.get("sentiment_score")]
        if scores:
            avg_sentiment = np.mean(scores)
            # Recent vs older (first half vs second half)
            mid = len(scores) // 2
            if mid > 0:
                recent_avg = np.mean(scores[:mid])  # articles sorted desc
                older_avg = np.mean(scores[mid:])
                trend = recent_avg - older_avg
                if trend > 0.1:
                    news_sub += 12
                    result["signals"].append("News sentiment improving")
                elif trend < -0.1:
                    news_sub -= 12
                    result["signals"].append("News sentiment deteriorating")

            # Absolute level
            news_sub += avg_sentiment * 25  # -1 to +1 → -25 to +25

            bullish = sum(1 for s in scores if s > 0.1)
            bearish = sum(1 for s in scores if s < -0.1)
            if bullish > bearish * 2:
                news_sub += 8
            elif bearish > bullish * 2:
                news_sub -= 8

    news_sub = _clamp(news_sub)

    # ── B. News Volume ───────────────────────────────────────────────────
    vol_sub = 50
    n_articles = len(news_articles) if news_articles else 0
    if n_articles > 20:
        vol_sub += 10  # high attention
        result["signals"].append(f"High news volume ({n_articles} articles)")
    elif n_articles < 3:
        vol_sub -= 5  # under-the-radar
    vol_sub = _clamp(vol_sub)

    # ── C. Commodity Alignment ───────────────────────────────────────────
    commodity_sub = 50
    if commodity_data:
        change_3m = commodity_data.get("price_change_3m", 0)
        rel = commodity_data.get("relationship", "direct")
        weight = commodity_data.get("weight", 0.2)

        # Direct: commodity up = good for stock. Inverse: commodity up = bad
        effective_change = change_3m if rel == "direct" else -change_3m

        # Weighted impact
        impact = effective_change * weight
        commodity_sub += _clamp(impact * 2, -25, 25)

        trend = commodity_data.get("trend", "UNKNOWN")
        commodity_name = commodity_data.get("commodity", "commodity")
        if abs(impact) > 3:
            direction = "tailwind" if impact > 0 else "headwind"
            result["signals"].append(
                f"{commodity_name} {direction} ({change_3m:+.1f}% 3M, {rel}, {weight:.0%} weight)"
            )

    commodity_sub = _clamp(commodity_sub)

    # ── D. Sector Momentum (from global news) ────────────────────────────
    sector_sub = 50
    try:
        import psycopg2
        from config import DB_URL
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur = conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cur.execute(
            "SELECT sentiment FROM global_news WHERE category IN ('sector', 'market') "
            "AND created_at >= %s AND tags LIKE %s",
            (cutoff, f"%{(sector or '').lower()}%")
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if rows:
            sector_sentiments = [r[0] for r in rows if r[0] is not None]
            if sector_sentiments:
                avg = np.mean(sector_sentiments)
                sector_sub += avg * 20
    except Exception:
        pass
    sector_sub = _clamp(sector_sub)

    # ── COMPOSITE ────────────────────────────────────────────────────────
    composite = (
        news_sub * 0.35 +
        vol_sub * 0.10 +
        commodity_sub * 0.30 +
        sector_sub * 0.25
    )

    result["score"] = round(_clamp(composite), 1)
    result["factors"] = {
        "news_flow": round(news_sub, 1),
        "news_volume": round(vol_sub, 1),
        "commodity_alignment": round(commodity_sub, 1),
        "sector_momentum": round(sector_sub, 1),
        "article_count": n_articles,
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5.  RISK PROFILE SCORING (0-100, higher = SAFER)
# ─────────────────────────────────────────────────────────────────────────────

def _score_risk(df, screener_data, weekly_df=None):
    """
    Risk assessment — higher score = lower risk = safer.

    Sub-factors:
      A. Volatility       — ATR%, annualized vol
      B. Drawdown Risk    — current drawdown from peak, max historical drawdown
      C. Liquidity        — average daily volume, volume consistency
      D. Leverage Risk    — debt/equity, interest coverage
      E. Earnings Risk    — profit variability, loss-making quarters
    """
    result = {"score": 50, "factors": {}, "signals": []}

    # ── A. Volatility ────────────────────────────────────────────────────
    vol_sub = 50
    if not df.empty and len(df) >= 20:
        close = df["close"]
        returns = close.pct_change().dropna()
        if len(returns) >= 20:
            daily_vol = float(returns.std())
            annual_vol = daily_vol * np.sqrt(252)

            if annual_vol < 0.20:
                vol_sub = 80  # low vol = low risk
            elif annual_vol < 0.30:
                vol_sub = 65
            elif annual_vol < 0.45:
                vol_sub = 45
            else:
                vol_sub = 25
                result["signals"].append(f"High volatility ({annual_vol:.0%} annualized)")

        # ATR% (14-day ATR / price)
        high = df["high"]
        low = df["low"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        atr_pct = atr / float(close.iloc[-1]) * 100 if close.iloc[-1] > 0 else 0
        if atr_pct > 4:
            vol_sub -= 10
        elif atr_pct < 1.5:
            vol_sub += 5

    vol_sub = _clamp(vol_sub)

    # ── B. Drawdown Risk ─────────────────────────────────────────────────
    dd_sub = 60
    if not df.empty and len(df) >= 50:
        close = df["close"]
        peak = close.cummax()
        drawdown = (close - peak) / peak
        current_dd = float(drawdown.iloc[-1])
        max_dd = float(drawdown.min())

        if current_dd < -0.20:
            dd_sub -= 20
            result["signals"].append(f"In deep drawdown ({current_dd:.0%} from peak)")
        elif current_dd < -0.10:
            dd_sub -= 10

        if max_dd < -0.50:
            dd_sub -= 10  # has had >50% crashes historically
            result["signals"].append(f"History of deep crashes ({max_dd:.0%} max drawdown)")
        elif max_dd > -0.20:
            dd_sub += 10  # never crashed badly

    # 5-year drawdown analysis
    if weekly_df is not None and not weekly_df.empty and len(weekly_df) >= 50:
        close_w = weekly_df["close"]
        peak_w = close_w.cummax()
        dd_w = (close_w - peak_w) / peak_w
        max_dd_5y = float(dd_w.min())
        if max_dd_5y < -0.50:
            dd_sub -= 5
        elif max_dd_5y > -0.25:
            dd_sub += 5

    dd_sub = _clamp(dd_sub)

    # ── C. Liquidity ─────────────────────────────────────────────────────
    liq_sub = 50
    if not df.empty and len(df) >= 20:
        volume = df["volume"]
        avg_vol = float(volume.rolling(20).mean().iloc[-1])
        close_val = float(df["close"].iloc[-1])
        avg_turnover = avg_vol * close_val  # rough daily turnover in ₹

        if avg_turnover > 100_000_000:  # > 10 Cr daily
            liq_sub = 85
        elif avg_turnover > 10_000_000:  # > 1 Cr
            liq_sub = 65
        elif avg_turnover > 1_000_000:  # > 10L
            liq_sub = 45
        else:
            liq_sub = 25
            result["signals"].append("Low liquidity — slippage risk")

        # Volume consistency (low std = reliable liquidity)
        vol_cv = float(volume.std() / volume.mean()) if volume.mean() > 0 else 1
        if vol_cv < 0.5:
            liq_sub += 5
        elif vol_cv > 1.5:
            liq_sub -= 5

    liq_sub = _clamp(liq_sub)

    # ── D. Leverage Risk ─────────────────────────────────────────────────
    leverage_sub = 60
    if screener_data:
        de = screener_data.get("debt_to_equity")
        icr = screener_data.get("interest_coverage")

        if de is not None:
            if de < 0.1:
                leverage_sub = 85
            elif de < 0.5:
                leverage_sub = 70
            elif de < 1.5:
                leverage_sub = 55
            elif de < 3:
                leverage_sub = 35
                result["signals"].append(f"High leverage risk (D/E: {de:.1f})")
            else:
                leverage_sub = 20
                result["signals"].append(f"Dangerous leverage (D/E: {de:.1f})")

        if icr is not None and icr < 1.5:
            leverage_sub -= 15
            result["signals"].append(f"Cannot cover interest payments (ICR: {icr:.1f}x)")

    leverage_sub = _clamp(leverage_sub)

    # ── E. Earnings Risk ─────────────────────────────────────────────────
    earnings_risk_sub = 55
    if screener_data:
        np_trend = screener_data.get("net_profit_trend", [])
        valid = [x for x in np_trend if x is not None]
        if valid:
            # Count loss-making years
            losses = sum(1 for x in valid if x < 0)
            if losses == 0:
                earnings_risk_sub = 75
            elif losses <= 1:
                earnings_risk_sub = 60
            else:
                earnings_risk_sub = 30
                result["signals"].append(f"Multiple loss-making years ({losses})")

            # Profit variability (coefficient of variation)
            if len(valid) >= 3:
                cv = np.std(valid) / (abs(np.mean(valid)) + 1e-6)
                if cv > 1:
                    earnings_risk_sub -= 10
                elif cv < 0.3:
                    earnings_risk_sub += 10

    earnings_risk_sub = _clamp(earnings_risk_sub)

    # ── COMPOSITE ────────────────────────────────────────────────────────
    composite = (
        vol_sub * 0.25 +
        dd_sub * 0.20 +
        liq_sub * 0.20 +
        leverage_sub * 0.20 +
        earnings_risk_sub * 0.15
    )

    result["score"] = round(_clamp(composite), 1)
    result["factors"] = {
        "volatility": round(vol_sub, 1),
        "drawdown": round(dd_sub, 1),
        "liquidity": round(liq_sub, 1),
        "leverage": round(leverage_sub, 1),
        "earnings_risk": round(earnings_risk_sub, 1),
    }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 6.  COMPOSITE ALPHA SCORE + CONVICTION + CATALYST DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _compute_alpha_score(tech, fundamental, institutional, sentiment, risk, regime):
    """
    Regime-adaptive composite score.

    In trending markets → weight technical & momentum more
    In range-bound      → weight fundamentals & valuation more
    In breakout zones   → weight volume & institutional more
    """
    # Base weights
    w = {"technical": 0.25, "fundamental": 0.25, "institutional": 0.15,
         "sentiment": 0.15, "risk": 0.20}

    # Regime adaptation
    if regime in ("TRENDING_UP", "TRENDING_DOWN"):
        w["technical"] = 0.35
        w["fundamental"] = 0.20
        w["sentiment"] = 0.15
        w["institutional"] = 0.10
        w["risk"] = 0.20

    elif regime == "RANGE_BOUND":
        w["technical"] = 0.15
        w["fundamental"] = 0.35
        w["sentiment"] = 0.10
        w["institutional"] = 0.20
        w["risk"] = 0.20

    elif regime in ("BREAKOUT_IMMINENT", "BREAKDOWN_IMMINENT"):
        w["technical"] = 0.30
        w["fundamental"] = 0.15
        w["sentiment"] = 0.15
        w["institutional"] = 0.25
        w["risk"] = 0.15

    alpha = (
        tech["score"] * w["technical"] +
        fundamental["score"] * w["fundamental"] +
        institutional["score"] * w["institutional"] +
        sentiment["score"] * w["sentiment"] +
        risk["score"] * w["risk"]
    )

    # Conviction: how aligned are the dimensions?
    scores = [tech["score"], fundamental["score"], institutional["score"],
              sentiment["score"], risk["score"]]
    mean_s = np.mean(scores)
    std_s = np.std(scores)

    # Low std = high conviction (all dimensions agree), high std = mixed signals
    conviction = _clamp(100 - std_s * 3, 0, 100)

    # Bonus: if all 5 signals are above 60 → strong conviction
    all_above_60 = all(s >= 60 for s in scores)
    all_below_40 = all(s <= 40 for s in scores)
    if all_above_60:
        conviction = min(conviction + 15, 100)
    elif all_below_40:
        conviction = min(conviction + 15, 100)  # high conviction bearish

    return round(alpha, 1), round(conviction, 1), w


def _detect_catalysts(tech, fundamental, institutional, sentiment, commodity_data, screener_data):
    """Identify actionable catalysts from the research data."""
    catalysts = []

    # Technical catalysts
    if tech.get("regime") == "BREAKOUT_IMMINENT":
        catalysts.append({
            "type": "TECHNICAL", "catalyst": "Volatility squeeze — breakout imminent",
            "impact": "HIGH", "timeframe": "1-2 weeks"
        })
    if tech.get("factors", {}).get("rsi", 50) < 30:
        catalysts.append({
            "type": "TECHNICAL", "catalyst": "RSI oversold — reversal setup",
            "impact": "MEDIUM", "timeframe": "Days"
        })

    # Fundamental catalysts
    for sig in fundamental.get("signals", []):
        if "accelerating" in sig.lower():
            catalysts.append({
                "type": "FUNDAMENTAL", "catalyst": sig,
                "impact": "HIGH", "timeframe": "Quarters"
            })
        if "undervalued" in sig.lower() or "PEG < 1" in sig:
            catalysts.append({
                "type": "FUNDAMENTAL", "catalyst": sig,
                "impact": "MEDIUM", "timeframe": "Months"
            })

    # Institutional catalysts
    for sig in institutional.get("signals", []):
        if "FII increasing" in sig:
            catalysts.append({
                "type": "INSTITUTIONAL", "catalyst": sig,
                "impact": "HIGH", "timeframe": "Quarters"
            })
        if "Promoter increasing" in sig:
            catalysts.append({
                "type": "INSTITUTIONAL", "catalyst": sig,
                "impact": "HIGH", "timeframe": "Months"
            })

    # Commodity catalysts
    if commodity_data:
        change_3m = abs(commodity_data.get("price_change_3m", 0))
        if change_3m > 10:
            rel = commodity_data.get("relationship", "direct")
            name = commodity_data.get("commodity", "commodity")
            direction = commodity_data.get("trend", "UNKNOWN")
            catalysts.append({
                "type": "COMMODITY", "catalyst": f"{name} {direction} ({change_3m:.0f}% in 3M) — {rel} exposure",
                "impact": "HIGH", "timeframe": "Weeks-Months"
            })

    return catalysts


def _generate_verdict(alpha, conviction, regime, tech, fundamental, risk):
    """Generate a human-readable research verdict."""
    # Overall stance
    if alpha >= 70:
        stance = "STRONG_BUY"
        stance_label = "Strong Buy"
    elif alpha >= 60:
        stance = "BUY"
        stance_label = "Buy"
    elif alpha >= 50:
        stance = "ACCUMULATE"
        stance_label = "Accumulate"
    elif alpha >= 40:
        stance = "HOLD"
        stance_label = "Hold"
    elif alpha >= 30:
        stance = "REDUCE"
        stance_label = "Reduce"
    else:
        stance = "SELL"
        stance_label = "Sell"

    # Confidence qualifier
    if conviction >= 75:
        confidence = "HIGH"
    elif conviction >= 50:
        confidence = "MODERATE"
    else:
        confidence = "LOW"

    # Risk qualifier
    risk_score = risk.get("score", 50)
    if risk_score >= 70:
        risk_label = "LOW_RISK"
    elif risk_score >= 45:
        risk_label = "MODERATE_RISK"
    else:
        risk_label = "HIGH_RISK"

    return {
        "stance": stance,
        "stance_label": stance_label,
        "confidence": confidence,
        "conviction": conviction,
        "risk_label": risk_label,
        "regime": regime,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7.  RISK-REWARD ESTIMATION
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_risk_reward(df, screener_data):
    """Estimate upside/downside targets and risk:reward ratio."""
    rr = {"upside_pct": None, "downside_pct": None, "risk_reward": None,
          "support": None, "resistance": None}

    if df.empty or len(df) < 50:
        return rr

    close = df["close"]
    high = df["high"]
    low = df["low"]
    current = float(close.iloc[-1])

    # Support: max of (recent swing low, Fib 0.618 of last rally, 200-EMA)
    supports = []
    low_20 = float(low.rolling(20).min().iloc[-1])
    supports.append(low_20)

    if len(close) >= 200:
        ema200 = float(close.ewm(span=200).mean().iloc[-1])
        supports.append(ema200)

    # Fibonacci support: 0.618 retracement of last 50-bar range
    r_high = float(high.iloc[-50:].max())
    r_low = float(low.iloc[-50:].min())
    fib_618 = r_high - (r_high - r_low) * 0.618
    supports.append(fib_618)

    support = max(s for s in supports if s < current) if [s for s in supports if s < current] else r_low

    # Resistance: min of (52-week high, Fib 1.618 extension, recent swing high)
    resistances = []
    high_lookback = min(252, len(high))
    high_52w = float(high.iloc[-high_lookback:].max())
    resistances.append(high_52w)

    high_20 = float(high.rolling(20).max().iloc[-1])
    resistances.append(high_20)

    resistance = min(r for r in resistances if r > current) if [r for r in resistances if r > current] else high_52w

    upside_pct = (resistance - current) / current * 100
    downside_pct = (current - support) / current * 100
    risk_reward = upside_pct / downside_pct if downside_pct > 0 else 0

    rr["support"] = round(support, 2)
    rr["resistance"] = round(resistance, 2)
    rr["upside_pct"] = round(upside_pct, 1)
    rr["downside_pct"] = round(downside_pct, 1)
    rr["risk_reward"] = round(risk_reward, 2)

    return rr


# ─────────────────────────────────────────────────────────────────────────────
# 8.  LONG-TERM STRUCTURAL ANALYSIS (5-year weekly data)
# ─────────────────────────────────────────────────────────────────────────────

def _analyze_long_term(weekly_df):
    """Analyze 5-year structural trends from weekly data."""
    result = {"available": False}
    if weekly_df.empty or len(weekly_df) < 50:
        return result

    close = weekly_df["close"]
    result["available"] = True

    # 5-year return
    start_price = float(close.iloc[0])
    end_price = float(close.iloc[-1])
    if start_price > 0:
        result["return_5y_pct"] = round((end_price / start_price - 1) * 100, 1)
        result["cagr_5y"] = round(((end_price / start_price) ** (1 / max(len(close) / 52, 1)) - 1) * 100, 1)

    # Max drawdown over entire period
    peak = close.cummax()
    dd = (close - peak) / peak
    result["max_drawdown_pct"] = round(float(dd.min()) * 100, 1)

    # Trend: 52-week SMA slope
    if len(close) >= 52:
        sma52 = close.rolling(52).mean()
        slope = float((sma52.iloc[-1] - sma52.iloc[-13]) / sma52.iloc[-13]) * 100 if sma52.iloc[-13] > 0 else 0
        result["weekly_trend_slope"] = round(slope, 1)
        if slope > 5:
            result["structural_trend"] = "STRONG_UPTREND"
        elif slope > 0:
            result["structural_trend"] = "MILD_UPTREND"
        elif slope > -5:
            result["structural_trend"] = "MILD_DOWNTREND"
        else:
            result["structural_trend"] = "STRONG_DOWNTREND"
    else:
        result["structural_trend"] = "UNKNOWN"

    # Volatility (annualized from weekly returns)
    returns = close.pct_change().dropna()
    if len(returns) >= 20:
        result["annual_volatility_pct"] = round(float(returns.std()) * np.sqrt(52) * 100, 1)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# █  MAIN PUBLIC API — generate_research()
# ─────────────────────────────────────────────────────────────────────────────

def generate_research(symbol):
    """
    Generate a complete research report for a single stock.
    This is THE unified algorithm — same steps, same scoring, every stock.

    Returns a dict with:
      - alpha_score (0-100)
      - conviction (0-100)
      - verdict (STRONG_BUY → SELL)
      - five dimension scores + factors + signals
      - catalysts
      - risk_reward
      - long_term
      - generated_at
    """
    t0 = time.time()
    logger.info("🔬 Research: generating report for %s", symbol)

    # ── Step 1: Collect all raw data in parallel ─────────────────────────
    price_df = pd.DataFrame()
    weekly_df = pd.DataFrame()
    shareholding = []
    news = []
    commodity = None
    screener = {}
    stock_meta = {}

    def _load_price():
        nonlocal price_df
        price_df = _load_price_history(symbol, days=365)

    def _load_weekly():
        nonlocal weekly_df
        weekly_df = _load_weekly_prices(symbol)

    def _load_sh():
        nonlocal shareholding
        shareholding = _load_shareholding(symbol)

    def _load_news():
        nonlocal news
        news = _load_recent_news(symbol, days=14)

    def _load_comm():
        nonlocal commodity
        commodity = _load_commodity_data(symbol)

    def _load_scr():
        nonlocal screener
        screener = _scrape_screener_ratios(symbol)

    def _load_meta():
        nonlocal stock_meta
        session = _get_db_session()
        if session:
            try:
                from db_manager import Stock
                s = session.query(Stock).filter_by(symbol=symbol).first()
                if s:
                    stock_meta = {
                        "company_name": s.company_name or symbol,
                        "sector": s.sector or "UNKNOWN",
                        "sector_display": s.sector_display or "",
                    }
            except Exception:
                pass
            finally:
                session.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(_load_price),
            pool.submit(_load_weekly),
            pool.submit(_load_sh),
            pool.submit(_load_news),
            pool.submit(_load_comm),
            pool.submit(_load_scr),
            pool.submit(_load_meta),
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                logger.warning("Research data load error: %s", e)

    company_name = stock_meta.get("company_name", symbol)
    sector = stock_meta.get("sector", "UNKNOWN")
    sector_display = stock_meta.get("sector_display", "")

    # ── Step 2: Score all five dimensions ────────────────────────────────
    tech = _score_technical(price_df)
    fundamental = _score_fundamental(screener)
    institutional = _score_institutional(shareholding)
    sentiment = _score_sentiment(news, commodity, sector)
    risk = _score_risk(price_df, screener, weekly_df)

    regime = tech.get("regime", "UNKNOWN")

    # ── Step 3: Composite scoring ────────────────────────────────────────
    alpha, conviction, weights = _compute_alpha_score(
        tech, fundamental, institutional, sentiment, risk, regime
    )

    # ── Step 4: Verdict ──────────────────────────────────────────────────
    verdict = _generate_verdict(alpha, conviction, regime, tech, fundamental, risk)

    # ── Step 5: Catalysts ────────────────────────────────────────────────
    catalysts = _detect_catalysts(tech, fundamental, institutional, sentiment, commodity, screener)

    # ── Step 6: Risk-reward ──────────────────────────────────────────────
    risk_reward = _estimate_risk_reward(price_df, screener)

    # ── Step 7: Long-term structure ──────────────────────────────────────
    long_term = _analyze_long_term(weekly_df)

    elapsed = time.time() - t0
    logger.info("🔬 Research: %s complete in %.1fs — Alpha: %.0f, Verdict: %s",
                symbol, elapsed, alpha, verdict["stance"])

    return {
        "symbol": symbol,
        "company_name": company_name,
        "sector": sector,
        "sector_display": sector_display,
        "alpha_score": alpha,
        "conviction": conviction,
        "verdict": verdict,
        "dimensions": {
            "technical": tech,
            "fundamental": fundamental,
            "institutional": institutional,
            "sentiment": sentiment,
            "risk": risk,
        },
        "regime": regime,
        "weights_used": weights,
        "catalysts": catalysts,
        "risk_reward": risk_reward,
        "long_term": long_term,
        "generated_at": datetime.utcnow().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# █  BATCH — run research for ALL tracked stocks
# ─────────────────────────────────────────────────────────────────────────────

def generate_research_all():
    """
    Run the research algorithm on every tracked stock.
    Returns list sorted by alpha_score descending.
    Also persists results into analysis_cache for the UI.
    """
    session = _get_db_session()
    if not session:
        return []

    try:
        from db_manager import Stock
        stocks = session.query(Stock.symbol).filter(Stock.is_active == True).all()
        symbols = [s[0] for s in stocks]
    except Exception:
        from config import WATCHLIST
        symbols = list(WATCHLIST)
    finally:
        session.close()

    logger.info("🔬 Research batch: %d stocks", len(symbols))
    results = []
    for i, sym in enumerate(symbols):
        try:
            report = generate_research(sym)
            results.append(report)
            # Persist to cache
            _cache_report(sym, report)
        except Exception as e:
            logger.warning("Research failed for %s: %s", sym, e)

        # Rate-limit Screener.in scraping
        if i < len(symbols) - 1:
            time.sleep(2)

    # Sort by alpha score descending
    results.sort(key=lambda r: r.get("alpha_score", 0), reverse=True)

    # Persist the ranked summary
    _cache_ranked_summary(results)

    logger.info("🔬 Research batch complete: %d/%d stocks", len(results), len(symbols))
    return results


def _cache_report(symbol, report):
    """Persist individual report into analysis_cache."""
    try:
        from db_manager import set_cached
        import json
        # Make it JSON-serializable
        clean = _make_serializable(report)
        set_cached(f"research_{symbol}", clean, cache_type="research")
    except Exception as e:
        logger.debug("Cache report failed for %s: %s", symbol, e)


def _cache_ranked_summary(results):
    """Persist ranked summary for the leaderboard UI."""
    try:
        from db_manager import set_cached
        summary = []
        for r in results:
            summary.append({
                "symbol": r["symbol"],
                "company_name": r.get("company_name", r["symbol"]),
                "sector": r.get("sector", ""),
                "alpha_score": r["alpha_score"],
                "conviction": r["conviction"],
                "verdict": r["verdict"],
                "regime": r["regime"],
                "dimensions": {
                    k: {"score": v.get("score", 50)}
                    for k, v in r.get("dimensions", {}).items()
                },
                "catalysts_count": len(r.get("catalysts", [])),
                "generated_at": r.get("generated_at"),
            })
        set_cached("research_leaderboard", summary, cache_type="research")
    except Exception as e:
        logger.debug("Cache leaderboard failed: %s", e)


def get_cached_report(symbol):
    """Get a previously cached research report."""
    try:
        from db_manager import get_cached
        return get_cached(f"research_{symbol}")
    except Exception:
        return None


def get_cached_leaderboard():
    """Get the cached ranked summary."""
    try:
        from db_manager import get_cached
        return get_cached("research_leaderboard")
    except Exception:
        return None


def _make_serializable(obj):
    """Recursively convert numpy/pandas types to Python native for JSON."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    else:
        return str(obj)
