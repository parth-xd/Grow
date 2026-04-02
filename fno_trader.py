"""
F&O (Futures & Options) Trading Module

Handles:
  - Index options: NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY
  - Stock options: HDFCBANK etc.
  - MCX commodity options/futures: Crude Oil Mini, Natural Gas, Gold Mini, Silver Mini
  - Capital management within a fixed budget (₹1000 default)
  - F&O-specific cost calculation (STT, brokerage, exchange charges)
  - Option chain analysis and affordable opportunity finder
  - Order placement via Groww API (FNO / COMMODITY segments)

With ₹1000 capital, ONLY option buying is feasible (no margin for selling).
Strategy: Buy cheap OTM options on directional conviction from news/technicals.
"""

import logging
import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. INSTRUMENT KNOWLEDGE BASE
# ═══════════════════════════════════════════════════════════════════════════════

# NSE Index & Stock F&O — lot sizes (as of FY 2025-26)
# FALLBACK ONLY — primary source is DB config_settings (auto_metadata.seed_fno_config)
_FALLBACK_FNO_LOT_SIZES = {
    # Index options (NSE)
    "NIFTY":       {"lot_size": 75,  "exchange": "NSE", "segment": "FNO", "type": "index", "tick": 0.05, "weekly_expiry": "THU", "underlying": "NIFTY"},
    "BANKNIFTY":   {"lot_size": 15,  "exchange": "NSE", "segment": "FNO", "type": "index", "tick": 0.05, "weekly_expiry": "WED", "underlying": "BANKNIFTY"},
    "FINNIFTY":    {"lot_size": 25,  "exchange": "NSE", "segment": "FNO", "type": "index", "tick": 0.05, "weekly_expiry": "TUE", "underlying": "FINNIFTY"},
    "SENSEX":      {"lot_size": 10,  "exchange": "BSE", "segment": "FNO", "type": "index", "tick": 0.05, "weekly_expiry": "FRI", "underlying": "SENSEX"},
    "MIDCPNIFTY":  {"lot_size": 50,  "exchange": "NSE", "segment": "FNO", "type": "index", "tick": 0.05, "weekly_expiry": "MON", "underlying": "MIDCPNIFTY"},
    # Stock options (NSE)
    "HDFCBANK":    {"lot_size": 550, "exchange": "NSE", "segment": "FNO", "type": "stock", "tick": 0.05, "weekly_expiry": None, "underlying": "HDFCBANK"},
}

# MCX commodity contracts — mini lots preferred (lower capital requirement)
_FALLBACK_MCX_CONTRACTS = {
    "CRUDEOILM":   {"lot_size": 10,   "unit": "barrels",  "exchange": "MCX", "segment": "COMMODITY", "tick": 1.0,  "underlying": "CRUDEOIL",    "desc": "Crude Oil Mini"},
    "NATURALGAS":  {"lot_size": 1250, "unit": "MMBtu",    "exchange": "MCX", "segment": "COMMODITY", "tick": 0.10, "underlying": "NATURALGAS",  "desc": "Natural Gas"},
    "NATGASMINI":  {"lot_size": 250,  "unit": "MMBtu",    "exchange": "MCX", "segment": "COMMODITY", "tick": 0.10, "underlying": "NATURALGAS",  "desc": "Natural Gas Mini"},
    "GOLDM":       {"lot_size": 100,  "unit": "grams",    "exchange": "MCX", "segment": "COMMODITY", "tick": 1.0,  "underlying": "GOLD",        "desc": "Gold Mini"},
    "SILVERM":     {"lot_size": 5,    "unit": "kg",       "exchange": "MCX", "segment": "COMMODITY", "tick": 1.0,  "underlying": "SILVER",      "desc": "Silver Mini"},
}


def _load_fno_lot_sizes():
    """Load F&O lot sizes from DB config, falling back to hardcoded."""
    try:
        from auto_metadata import get_fno_lot_config
        result = {}
        for sym, fallback in _FALLBACK_FNO_LOT_SIZES.items():
            db_cfg = get_fno_lot_config(sym)
            if db_cfg:
                # Merge: DB overrides lot_size etc, keep segment/underlying from fallback
                merged = {**fallback, **db_cfg}
                if "segment" not in db_cfg:
                    merged["segment"] = fallback.get("segment", "FNO")
                if "underlying" not in db_cfg:
                    merged["underlying"] = fallback.get("underlying", sym)
                result[sym] = merged
            else:
                result[sym] = fallback
        return result
    except Exception:
        return _FALLBACK_FNO_LOT_SIZES


def _load_mcx_contracts():
    """Load MCX contracts from DB config, falling back to hardcoded."""
    try:
        from auto_metadata import get_fno_lot_config
        result = {}
        for sym, fallback in _FALLBACK_MCX_CONTRACTS.items():
            db_cfg = get_fno_lot_config(sym)
            if db_cfg:
                merged = {**fallback, **db_cfg}
                result[sym] = merged
            else:
                result[sym] = fallback
        return result
    except Exception:
        return _FALLBACK_MCX_CONTRACTS


# Live-loaded dicts (prefer DB, fallback to hardcoded)
FNO_LOT_SIZES = _load_fno_lot_sizes()
MCX_CONTRACTS = _load_mcx_contracts()

# Combined lookup
ALL_FNO_INSTRUMENTS = {**FNO_LOT_SIZES, **MCX_CONTRACTS}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. F&O COST CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FnoCost:
    """Breakdown of F&O trading charges (buy + sell round trip)."""
    buy_premium: float          # Total premium paid
    sell_premium: float         # Total premium received
    brokerage: float            # ₹20/order × 2 = ₹40
    stt: float                  # STT on sell-side premium
    exchange_txn: float         # Exchange transaction charges
    sebi_fee: float
    gst: float
    stamp_duty: float
    instrument_type: str        # "option" or "future"

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange_txn + self.sebi_fee + self.gst + self.stamp_duty

    @property
    def total_pct(self) -> float:
        return (self.total / self.buy_premium * 100) if self.buy_premium else 0

    @property
    def breakeven_move_pct(self) -> float:
        """How much premium must rise to break even."""
        return ((self.buy_premium + self.total) / self.buy_premium - 1) * 100 if self.buy_premium else 0

    def to_dict(self) -> dict:
        return {
            "buy_premium": round(self.buy_premium, 2),
            "sell_premium": round(self.sell_premium, 2),
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_txn": round(self.exchange_txn, 2),
            "sebi_fee": round(self.sebi_fee, 2),
            "gst": round(self.gst, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "total_charges": round(self.total, 2),
            "total_pct": round(self.total_pct, 2),
            "breakeven_move_pct": round(self.breakeven_move_pct, 2),
        }


def calculate_fno_costs(
    premium_per_unit: float,
    lot_size: int,
    sell_premium_per_unit: float = None,
    exchange: str = "NSE",
    instrument_type: str = "option",
) -> FnoCost:
    """
    Calculate F&O round-trip costs.
    Rates loaded from DB config_settings (key prefix: fno.*).
    Falls back to hardcoded defaults if DB unavailable.
    """
    # Load rates from DB config
    try:
        from auto_metadata import get_fno_cost_rate
        stt_option_pct = get_fno_cost_rate("stt.option_sell_pct", 0.0625)
        stt_futures_pct = get_fno_cost_rate("stt.futures_sell_pct", 0.0125)
        exc_nse = get_fno_cost_rate("exchange.nse_pct", 0.0495)
        exc_bse = get_fno_cost_rate("exchange.bse_pct", 0.0325)
        exc_mcx = get_fno_cost_rate("exchange.mcx_pct", 0.0260)
        sebi_pct = get_fno_cost_rate("sebi_pct", 0.0001)
        gst_pct = get_fno_cost_rate("gst_pct", 18.0)
        stamp_pct = get_fno_cost_rate("stamp_duty_pct", 0.003)
        brokerage_order = get_fno_cost_rate("brokerage_per_order", 20.0)
        brokerage_cap = get_fno_cost_rate("brokerage_pct_cap", 0.05)
    except Exception:
        stt_option_pct, stt_futures_pct = 0.0625, 0.0125
        exc_nse, exc_bse, exc_mcx = 0.0495, 0.0325, 0.0260
        sebi_pct, gst_pct, stamp_pct = 0.0001, 18.0, 0.003
        brokerage_order, brokerage_cap = 20.0, 0.05

    if sell_premium_per_unit is None:
        sell_premium_per_unit = premium_per_unit  # breakeven calc

    buy_premium = premium_per_unit * lot_size
    sell_premium = sell_premium_per_unit * lot_size

    # Brokerage
    brokerage_buy = min(brokerage_order, buy_premium * brokerage_cap / 100) if buy_premium > 0 else 0
    brokerage_sell = min(brokerage_order, sell_premium * brokerage_cap / 100) if sell_premium > 0 else 0
    brokerage = brokerage_buy + brokerage_sell

    # STT
    if instrument_type == "option":
        stt = sell_premium * stt_option_pct / 100
    else:  # futures
        stt = sell_premium * stt_futures_pct / 100

    # Exchange transaction charges
    exc_rates = {"NSE": exc_nse, "BSE": exc_bse, "MCX": exc_mcx}
    exc_rate = exc_rates.get(exchange, exc_nse)
    turnover = buy_premium + sell_premium
    exchange_txn = turnover * exc_rate / 100

    # SEBI fee
    sebi_fee = turnover * sebi_pct / 100

    # GST on brokerage + exchange + SEBI
    gst = (brokerage + exchange_txn + sebi_fee) * gst_pct / 100

    # Stamp duty (buy side only)
    stamp_duty = buy_premium * stamp_pct / 100

    return FnoCost(
        buy_premium=buy_premium,
        sell_premium=sell_premium,
        brokerage=brokerage,
        stt=stt,
        exchange_txn=exchange_txn,
        sebi_fee=sebi_fee,
        gst=gst,
        stamp_duty=stamp_duty,
        instrument_type=instrument_type,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CAPITAL MANAGER — syncs from Groww account balance
# ═══════════════════════════════════════════════════════════════════════════════


def sync_capital_from_groww():
    """
    Sync F&O trading capital from actual Groww account margin.
    Uses get_available_margin_details() to read real balance.
    Updates DB config so other functions use the live number.
    Skips sync in paper mode to preserve virtual capital.
    """
    try:
        # In paper mode, don't overwrite virtual capital with real balance
        from bot import is_paper_mode
        if is_paper_mode():
            current = get_fno_capital()
            if current > 0:
                logger.debug("Paper mode — keeping virtual F&O capital ₹%.2f", current)
                return current
            # If paper capital is 0, set a default virtual balance
            from db_manager import set_config
            set_config("fno.capital", "10000", "F&O paper trading virtual capital")
            logger.info("Paper mode — set default virtual F&O capital ₹10,000")
            return 10000.0
    except Exception:
        pass

    try:
        groww = _get_groww()
        margin = groww.get_available_margin_details()
        if not margin:
            logger.warning("Empty margin response from Groww")
            return None

        # Primary: F&O option buy balance
        fno_details = margin.get("fno_margin_details", {})
        option_buy_bal = fno_details.get("option_buy_balance_available", 0) or 0

        # Fallback: total clear cash (not yet allocated to any segment)
        clear_cash = margin.get("clear_cash", 0) or 0

        # Use whichever is higher — Groww may show cash in clear_cash before
        # the user allocates it to F&O segment
        available_for_fno = max(option_buy_bal, clear_cash)

        # Update DB
        from db_manager import set_config
        set_config("fno.capital", str(round(available_for_fno, 2)),
                    "F&O capital synced from Groww account")

        # Also store full margin snapshot for reference
        from db_manager import set_cached
        set_cached("fno_margin_snapshot", margin, cache_type="fno")

        logger.info("F&O capital synced from Groww: ₹%.2f (option_buy=%.2f, clear_cash=%.2f)",
                     available_for_fno, option_buy_bal, clear_cash)
        return available_for_fno

    except Exception as e:
        logger.error("Failed to sync capital from Groww: %s", e)
        return None


def get_fno_capital():
    """Get F&O trading capital from DB (synced from Groww account)."""
    try:
        from db_manager import get_config
        val = get_config("fno.capital", default="0")
        return float(val)
    except Exception:
        return 0.0


def get_used_capital():
    """Get currently deployed capital in open F&O positions."""
    try:
        from db_manager import get_config
        val = get_config("fno.used_capital", default="0")
        return float(val)
    except Exception:
        return 0.0


def update_used_capital(amount):
    """Update used capital (positive = deployed, negative = freed)."""
    try:
        from db_manager import set_config
        current = get_used_capital()
        new_val = max(0, current + amount)
        set_config("fno.used_capital", str(round(new_val, 2)), "Capital deployed in F&O positions")
    except Exception as e:
        logger.error("Failed to update used capital: %s", e)


def get_available_capital():
    """Available capital for new F&O trades."""
    return max(0, get_fno_capital() - get_used_capital())


# ═══════════════════════════════════════════════════════════════════════════════
# 4. OPTION CHAIN & OPPORTUNITY FINDER
# ═══════════════════════════════════════════════════════════════════════════════

def _get_groww():
    """Get authenticated Groww API client."""
    from growwapi import GrowwAPI
    token = os.getenv("GROWW_ACCESS_TOKEN", "")
    if not token:
        try:
            from config import GROWW_ACCESS_TOKEN
            token = GROWW_ACCESS_TOKEN
        except ImportError:
            pass
    if not token:
        raise RuntimeError("GROWW_ACCESS_TOKEN not set")
    return GrowwAPI(token)


def get_expiries(instrument_key):
    """Get available expiry dates for an instrument."""
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    groww = _get_groww()
    underlying = inst["underlying"]
    exchange = inst["exchange"]

    try:
        result = groww.get_expiries(exchange=exchange, underlying_symbol=underlying)
        return result
    except Exception as e:
        logger.error("Failed to get expiries for %s: %s", instrument_key, e)
        return {"error": str(e)}


def get_option_chain(instrument_key, expiry_date):
    """
    Fetch option chain for an instrument.
    Returns calls and puts at all strikes with LTP, OI, Greeks.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    groww = _get_groww()
    underlying = inst["underlying"]
    exchange = inst["exchange"]

    try:
        chain = groww.get_option_chain(
            exchange=exchange,
            underlying=underlying,
            expiry_date=expiry_date,
        )
        return chain
    except Exception as e:
        logger.error("Failed to get option chain for %s: %s", instrument_key, e)
        return {"error": str(e)}


def find_affordable_options(instrument_key, expiry_date, budget=None):
    """
    Find options that can be bought within the budget.

    Returns list of affordable options sorted by value score:
      - Cheap premium (within budget)
      - Good OI (liquidity)
      - Reasonable delta for directional plays

    With ₹1000 budget and ₹40 brokerage per round trip,
    only options < (budget - 40) / lot_size per unit are tradeable.
    """
    if budget is None:
        budget = get_available_capital()

    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    lot_size = inst["lot_size"]

    # Reserve ₹40 for round-trip brokerage
    max_premium_total = budget - 40
    if max_premium_total <= 0:
        return {"error": f"Insufficient capital. Need at least ₹40 for brokerage, have ₹{budget}"}

    max_premium_per_unit = max_premium_total / lot_size

    chain = get_option_chain(instrument_key, expiry_date)
    if "error" in chain:
        return chain

    affordable = []
    strikes = chain.get("option_chain_data", chain.get("data", []))

    for strike_data in strikes:
        strike_price = strike_data.get("strike_price", 0)

        for opt_type in ["call", "put", "CE", "PE"]:
            opt = strike_data.get(opt_type, {})
            if not opt:
                continue

            ltp = opt.get("ltp", opt.get("last_price", 0)) or 0
            oi = opt.get("oi", opt.get("open_interest", 0)) or 0
            trading_symbol = opt.get("trading_symbol", "")

            if ltp <= 0 or ltp > max_premium_per_unit:
                continue

            total_cost = ltp * lot_size
            costs = calculate_fno_costs(ltp, lot_size, exchange=inst["exchange"])
            all_in = total_cost + costs.total

            if all_in > budget:
                continue

            option_type = "CE" if opt_type in ("call", "CE") else "PE"

            affordable.append({
                "trading_symbol": trading_symbol,
                "strike_price": strike_price,
                "option_type": option_type,
                "ltp": ltp,
                "lot_size": lot_size,
                "total_premium": round(total_cost, 2),
                "total_charges": round(costs.total, 2),
                "all_in_cost": round(all_in, 2),
                "remaining_capital": round(budget - all_in, 2),
                "breakeven_move_pct": round(costs.breakeven_move_pct, 2),
                "open_interest": oi,
                "greeks": {
                    "delta": opt.get("delta", 0),
                    "theta": opt.get("theta", 0),
                    "iv": opt.get("iv", opt.get("implied_volatility", 0)),
                },
            })

    # Score and sort: prefer higher OI, lower breakeven, reasonable delta
    for opt in affordable:
        oi_score = min(opt["open_interest"] / 10000, 1.0) if opt["open_interest"] else 0
        cost_score = max(0, 1 - opt["breakeven_move_pct"] / 50)
        delta = abs(opt["greeks"].get("delta", 0) or 0)
        delta_score = delta  # higher absolute delta = more directional exposure
        opt["score"] = round(oi_score * 0.3 + cost_score * 0.4 + delta_score * 0.3, 3)

    affordable.sort(key=lambda x: x["score"], reverse=True)

    return {
        "instrument": instrument_key,
        "expiry": expiry_date,
        "budget": budget,
        "max_premium_per_unit": round(max_premium_per_unit, 2),
        "options_found": len(affordable),
        "options": affordable[:20],  # top 20
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MARKET ANALYSIS FOR F&O DECISIONS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Instrument search term mapping ──────────────────────────────────────────
_SEARCH_MAP = {
    "NIFTY": "NIFTY 50 stock market India",
    "BANKNIFTY": "Bank Nifty banking stocks India",
    "FINNIFTY": "Nifty Financial Services stocks",
    "SENSEX": "Sensex BSE India stock market",
    "MIDCPNIFTY": "Nifty Midcap Select stocks India",
    "HDFCBANK": "HDFC Bank",
    "CRUDEOIL": "crude oil prices India MCX",
    "NATURALGAS": "natural gas prices MCX India",
    "GOLD": "gold prices India MCX",
    "SILVER": "silver prices India",
}

# ── Historical data + Technical indicators ──────────────────────────────────

def _fetch_historical_candles(instrument_key, days=30, interval="1day"):
    """
    Fetch historical candle data for an F&O underlying.
    Uses V1 get_historical_candle_data (V2 not available on all tiers).
    Returns list of dicts with open/high/low/close/volume.
    Cached in DB for 1 hour.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return []

    cache_key = f"fno_hist:{instrument_key}:{days}:{interval}"
    try:
        from db_manager import get_cached
        cached = get_cached(cache_key, ttl_seconds=3600)
        if cached:
            return cached
    except Exception:
        pass

    try:
        groww = _get_groww()
        now = datetime.now()
        start = now - timedelta(days=days)
        start_str = start.strftime("%Y-%m-%d %H:%M:%S")
        end_str = now.strftime("%Y-%m-%d %H:%M:%S")

        groww_symbol = inst["underlying"]
        exchange = inst["exchange"]
        # For F&O underlyings: candle data lives in CASH segment
        # MCX commodities need contract symbols — fall back to yfinance
        segment = "CASH"

        # Map interval string to minutes for V1 API
        interval_map = {"1day": 1440, "1hour": 60, "15minute": 15, "5minute": 5, "1minute": 1}
        mins = interval_map.get(interval, 1440)

        data = None
        try:
            data = groww.get_historical_candle_data(
                trading_symbol=groww_symbol,
                exchange=exchange,
                segment=segment,
                start_time=start_str,
                end_time=end_str,
                interval_in_minutes=mins,
            )
        except Exception as e:
            logger.debug("Groww candles failed for %s: %s", instrument_key, e)

        # MCX fallback — try yfinance for commodity data
        if not data or not data.get("candles"):
            try:
                import yfinance as yf
                yf_map = {
                    "CRUDEOIL": "CL=F", "NATURALGAS": "NG=F",
                    "GOLD": "GC=F", "SILVER": "SI=F",
                }
                ticker = yf_map.get(groww_symbol)
                if ticker:
                    df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False)
                    if not df.empty:
                        result = []
                        for idx, row in df.iterrows():
                            result.append({
                                "timestamp": int(idx.timestamp()),
                                "open": float(row.get("Open", 0)),
                                "high": float(row.get("High", 0)),
                                "low": float(row.get("Low", 0)),
                                "close": float(row.get("Close", 0)),
                                "volume": int(row.get("Volume", 0)),
                            })
                        if result:
                            try:
                                from db_manager import set_cached
                                set_cached(cache_key, result, cache_type="fno_hist")
                            except Exception:
                                pass
                            return result
            except ImportError:
                logger.debug("yfinance not available for MCX fallback")
            except Exception as e:
                logger.debug("yfinance fallback failed for %s: %s", instrument_key, e)

        candles = data.get("candles", []) if data else []
        if isinstance(candles, list) and candles:
            result = []
            for c in candles:
                if isinstance(c, list) and len(c) >= 5:
                    # V1 format: [timestamp, open, high, low, close, volume]
                    # Note: volume can be None for indices
                    result.append({
                        "timestamp": c[0],
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": int(c[5]) if len(c) > 5 and c[5] is not None else 0,
                    })
                elif isinstance(c, dict):
                    result.append({
                        "timestamp": c.get("timestamp", ""),
                        "open": float(c.get("open", 0) or 0),
                        "high": float(c.get("high", 0) or 0),
                        "low": float(c.get("low", 0) or 0),
                        "close": float(c.get("close", 0) or 0),
                        "volume": int(c.get("volume", 0) or 0),
                    })
            try:
                from db_manager import set_cached
                set_cached(cache_key, result, cache_type="fno_hist")
            except Exception:
                pass
            return result
        return []
    except Exception as e:
        logger.warning("Historical candles failed for %s: %s", instrument_key, e)
        return []


def _compute_rsi(closes, period=14):
    """Compute RSI from a list of closing prices."""
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
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_ema(values, period):
    """Compute Exponential Moving Average."""
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def _compute_macd(closes, fast=12, slow=26, signal=9):
    """Compute MACD, signal line, and histogram."""
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = _compute_ema(closes, fast)
    ema_slow = _compute_ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None

    # Build full MACD line
    macd_line = []
    f_mult = 2 / (fast + 1)
    s_mult = 2 / (slow + 1)
    ema_f = sum(closes[:fast]) / fast
    ema_s = sum(closes[:slow]) / slow
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

    macd_val = macd_line[-1]
    histogram = macd_val - sig_ema
    return macd_val, sig_ema, histogram


def _compute_bollinger(closes, period=20, num_std=2):
    """Compute Bollinger Bands (upper, middle, lower)."""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = variance ** 0.5
    return middle + num_std * std, middle, middle - num_std * std


def compute_technicals(instrument_key):
    """
    Compute full technical analysis for an F&O underlying.
    Returns RSI, MACD, EMAs, Bollinger Bands, support/resistance, volume trend.
    Uses live Groww quote for current price, historical candles for indicators.
    """
    candles = _fetch_historical_candles(instrument_key, days=60, interval="1day")
    if len(candles) < 15:
        return {"error": "Insufficient historical data", "candle_count": len(candles)}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    # Get live price from Groww API (most recent)
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    current = closes[-1]  # fallback to last candle close
    if inst:
        try:
            groww = _get_groww()
            seg = "CASH" if inst["segment"] != "COMMODITY" else inst["segment"]
            quote = groww.get_quote(
                trading_symbol=inst["underlying"],
                exchange=inst["exchange"],
                segment=seg,
            )
            if quote and quote.get("last_price"):
                current = quote["last_price"]
                # Append live price to closes for indicator accuracy
                if current != closes[-1]:
                    closes.append(current)
                    highs.append(max(current, quote.get("ohlc", {}).get("high", current)))
                    lows.append(min(current, quote.get("ohlc", {}).get("low", current)))
                    volumes.append(0)
        except Exception as e:
            logger.debug("Live quote failed for %s technicals: %s", instrument_key, e)

    result = {"current_price": current, "candle_count": len(candles), "source": "groww_live"}

    # RSI
    rsi = _compute_rsi(closes)
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
    macd_val, macd_sig, macd_hist = _compute_macd(closes)
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

    # EMAs (9, 21, 50)
    for period in (9, 21, 50):
        ema = _compute_ema(closes, period)
        if ema is not None:
            result[f"ema_{period}"] = round(ema, 2)

    # EMA crossover signal
    ema9 = result.get("ema_9")
    ema21 = result.get("ema_21")
    if ema9 and ema21:
        if ema9 > ema21 and current > ema9:
            result["ema_signal"] = "BULLISH"
        elif ema9 < ema21 and current < ema9:
            result["ema_signal"] = "BEARISH"
        else:
            result["ema_signal"] = "NEUTRAL"

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = _compute_bollinger(closes)
    if bb_upper is not None:
        result["bb_upper"] = round(bb_upper, 2)
        result["bb_middle"] = round(bb_mid, 2)
        result["bb_lower"] = round(bb_lower, 2)
        bb_width = (bb_upper - bb_lower) / bb_mid * 100 if bb_mid else 0
        result["bb_width_pct"] = round(bb_width, 2)
        if current >= bb_upper:
            result["bb_signal"] = "OVERBOUGHT"
        elif current <= bb_lower:
            result["bb_signal"] = "OVERSOLD"
        else:
            position = (current - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
            result["bb_position"] = round(position, 2)
            result["bb_signal"] = "BULLISH" if position > 0.6 else ("BEARISH" if position < 0.4 else "NEUTRAL")

    # Support & Resistance (from recent highs/lows)
    if len(highs) >= 10:
        recent_highs = sorted(highs[-20:], reverse=True)
        recent_lows = sorted(lows[-20:])
        result["resistance"] = round(recent_highs[0], 2)
        result["support"] = round(recent_lows[0], 2)
        result["distance_to_resistance_pct"] = round((recent_highs[0] - current) / current * 100, 2)
        result["distance_to_support_pct"] = round((current - recent_lows[0]) / current * 100, 2)

    # Volume trend (last 5 vs avg)
    if len(volumes) >= 10 and any(v > 0 for v in volumes):
        avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
        recent_vol = sum(volumes[-5:]) / 5  if len(volumes) >= 5 else volumes[-1]
        if avg_vol > 0:
            result["volume_ratio"] = round(recent_vol / avg_vol, 2)
            result["volume_signal"] = "HIGH" if recent_vol > avg_vol * 1.5 else ("LOW" if recent_vol < avg_vol * 0.5 else "NORMAL")

    # ── SMM Course Indicators ────────────────────────────────────────────

    # Stochastic Oscillator (SMM Part 4)
    if len(closes) >= 17:
        k_period = 14
        d_period = 3
        lowest_low = min(lows[-k_period:])
        highest_high = max(highs[-k_period:])
        denom = highest_high - lowest_low
        stoch_k = 100 * (current - lowest_low) / denom if denom > 0 else 50
        # %D = 3-period SMA of %K — approximate from last 3 closes
        k_vals = []
        for offset in range(min(d_period, len(closes))):
            idx = -(offset + 1)
            ll = min(lows[max(0, len(lows)+idx-k_period):len(lows)+idx+1])
            hh = max(highs[max(0, len(highs)+idx-k_period):len(highs)+idx+1])
            d = hh - ll
            k_vals.append(100 * (closes[idx] - ll) / d if d > 0 else 50)
        stoch_d = sum(k_vals) / len(k_vals) if k_vals else stoch_k
        result["stoch_k"] = round(stoch_k, 2)
        result["stoch_d"] = round(stoch_d, 2)
        if stoch_k < 20 and stoch_d < 20:
            result["stoch_signal"] = "OVERSOLD"
        elif stoch_k > 80 and stoch_d > 80:
            result["stoch_signal"] = "OVERBOUGHT"
        elif stoch_k > stoch_d:
            result["stoch_signal"] = "BULLISH"
        elif stoch_k < stoch_d:
            result["stoch_signal"] = "BEARISH"
        else:
            result["stoch_signal"] = "NEUTRAL"

    # Candlestick Patterns (SMM Part 1) — last candle
    if len(candles) >= 3:
        c0 = candles[-1]  # current
        c1 = candles[-2]  # previous
        c2 = candles[-3]  # two ago
        body0 = c0["close"] - c0["open"]
        body1 = c1["close"] - c1["open"]
        body0_abs = abs(body0)
        body1_abs = abs(body1)
        range0 = c0["high"] - c0["low"] if c0["high"] != c0["low"] else 0.01
        upper0 = c0["high"] - max(c0["close"], c0["open"])
        lower0 = min(c0["close"], c0["open"]) - c0["low"]

        detected_patterns = []
        candle_score = 0.0

        # Doji
        if body0_abs / range0 < 0.1:
            detected_patterns.append("Doji")

        # Hammer (bullish reversal)
        if lower0 > 2 * body0_abs and upper0 < body0_abs * 0.5 and body0_abs > 0:
            detected_patterns.append("Hammer")
            candle_score += 0.4

        # Shooting Star (bearish reversal)
        if upper0 > 2 * body0_abs and lower0 < body0_abs * 0.5 and body0_abs > 0:
            detected_patterns.append("Shooting Star")
            candle_score -= 0.4

        # Bullish Engulfing
        if body1 < 0 and body0 > 0 and c0["open"] <= c1["close"] and c0["close"] >= c1["open"]:
            detected_patterns.append("Bullish Engulfing")
            candle_score += 0.6

        # Bearish Engulfing
        if body1 > 0 and body0 < 0 and c0["open"] >= c1["close"] and c0["close"] <= c1["open"]:
            detected_patterns.append("Bearish Engulfing")
            candle_score -= 0.6

        # Morning Star (3-candle bullish reversal)
        body2 = c2["close"] - c2["open"]
        range1 = c1["high"] - c1["low"] if c1["high"] != c1["low"] else 0.01
        if body2 < 0 and body1_abs / range1 < 0.3 and body0 > 0 and c0["close"] > (c2["open"] + c2["close"]) / 2:
            detected_patterns.append("Morning Star")
            candle_score += 0.7

        # Evening Star (3-candle bearish reversal)
        if body2 > 0 and body1_abs / range1 < 0.3 and body0 < 0 and c0["close"] < (c2["open"] + c2["close"]) / 2:
            detected_patterns.append("Evening Star")
            candle_score -= 0.7

        # Bullish Piercing
        prior_mid = (c1["open"] + c1["close"]) / 2
        if body1 < 0 and body0 > 0 and c0["close"] > prior_mid and c0["open"] <= c1["close"]:
            detected_patterns.append("Bullish Piercing")
            candle_score += 0.4

        # Dark Cloud Cover (bearish piercing)
        if body1 > 0 and body0 < 0 and c0["close"] < prior_mid and c0["open"] >= c1["close"]:
            detected_patterns.append("Dark Cloud Cover")
            candle_score -= 0.4

        if detected_patterns:
            result["candle_patterns"] = detected_patterns
            result["candle_score"] = round(candle_score, 2)
            candle_dir = "BULLISH" if candle_score > 0.2 else ("BEARISH" if candle_score < -0.2 else "NEUTRAL")
            result["candle_signal"] = candle_dir

    # Fibonacci Retracement (SMM Part 2)
    if len(highs) >= 50:
        fib_high = max(highs[-50:])
        fib_low = min(lows[-50:])
        fib_range = fib_high - fib_low
        if fib_range > 0:
            fib_levels = {}
            for name, ratio in [("23.6%", 0.236), ("38.2%", 0.382), ("50%", 0.500), ("61.8%", 0.618), ("78.6%", 0.786)]:
                fib_levels[name] = round(fib_high - fib_range * ratio, 2)
            result["fibonacci"] = fib_levels
            # Nearest Fibonacci level
            nearest = min(fib_levels.items(), key=lambda x: abs(x[1] - current))
            result["nearest_fib"] = nearest[0]
            result["nearest_fib_price"] = nearest[1]
            result["fib_distance_pct"] = round((current - nearest[1]) / current * 100, 2)

    # RSI Divergence (SMM Part 4) — compare last two swing lows/highs
    if len(closes) >= 30:
        half = len(closes) // 2
        recent_closes = closes[half:]
        older_closes = closes[:half]
        # Simple divergence check: price lower low but RSI higher low
        recent_low = min(recent_closes)
        older_low = min(older_closes)
        recent_rsi = _compute_rsi(recent_closes)
        older_rsi = _compute_rsi(older_closes)
        if recent_rsi is not None and older_rsi is not None:
            if recent_low < older_low and recent_rsi > older_rsi:
                result["rsi_divergence"] = "BULLISH"  # Price lower, RSI higher = reversal up
            elif max(recent_closes) > max(older_closes) and recent_rsi < older_rsi:
                result["rsi_divergence"] = "BEARISH"  # Price higher, RSI lower = reversal down
            else:
                result["rsi_divergence"] = "NONE"

    # DOW Volume Confirmation (SMM Part 1)
    if len(closes) >= 20 and len(volumes) >= 20 and any(v > 0 for v in volumes):
        price_trend_up = closes[-1] > closes[-6]  # 5-day price direction
        avg_vol_5 = sum(volumes[-5:]) / 5
        avg_vol_20 = sum(volumes[-20:]) / 20
        vol_rising = avg_vol_5 > avg_vol_20
        if price_trend_up and vol_rising:
            result["dow_confirmation"] = "CONFIRMED_UP"
        elif not price_trend_up and vol_rising:
            result["dow_confirmation"] = "CONFIRMED_DOWN"
        elif price_trend_up and not vol_rising:
            result["dow_confirmation"] = "WEAK_UP"
        else:
            result["dow_confirmation"] = "WEAK_DOWN"

    return result


# ── X/Social Media Sentiment ───────────────────────────────────────────────

def _get_x_sentiment(instrument_key):
    """
    Get X.com / social media sentiment for an F&O instrument.
    Uses news_sentiment._fetch_x_posts() and additional Google searches.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return None

    underlying = inst["underlying"]
    search_term = _SEARCH_MAP.get(underlying, underlying)

    try:
        import news_sentiment
        # Get X posts via Google News RSS
        x_posts = news_sentiment._fetch_x_posts(search_term)

        if not x_posts:
            return None

        scores = [p.sentiment_score for p in x_posts if hasattr(p, "sentiment_score")]
        if not scores:
            return None

        avg_score = sum(scores) / len(scores)
        bullish = sum(1 for s in scores if s > 0.1)
        bearish = sum(1 for s in scores if s < -0.1)
        total = len(scores)

        if avg_score > 0.15:
            signal = "BULLISH"
        elif avg_score < -0.15:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"

        headlines = [p.title for p in x_posts[:5] if hasattr(p, "title")]

        return {
            "signal": signal,
            "score": round(avg_score, 3),
            "post_count": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "top_headlines": headlines,
        }
    except Exception as e:
        logger.debug("X sentiment failed for %s: %s", instrument_key, e)
        return None


# ── Open Interest Analysis ─────────────────────────────────────────────────

def _analyze_oi(instrument_key, expiry_date=None):
    """
    Analyze Open Interest from option chain to gauge market positioning.
    - PCR (Put-Call Ratio) > 1 = bullish (more puts being sold as support)
    - PCR < 0.7 = bearish (more calls being sold as resistance)
    - Max Pain = strike where writers lose least (price gravitates here)
    """
    if not expiry_date:
        # Get nearest expiry
        try:
            exp = get_expiries(instrument_key)
            dates = exp.get("expiry_dates", exp.get("data", []))
            if not dates:
                return None
            expiry_date = dates[0] if isinstance(dates[0], str) else dates[0].get("expiry_date", "")
        except Exception:
            return None

    chain = get_option_chain(instrument_key, expiry_date)
    if not chain or "error" in chain:
        return None

    strikes = chain.get("option_chain_data", chain.get("data", []))
    if not strikes:
        return None

    total_call_oi = 0
    total_put_oi = 0
    max_call_oi = 0
    max_call_oi_strike = 0
    max_put_oi = 0
    max_put_oi_strike = 0
    pain_data = []

    for s in strikes:
        strike = s.get("strike_price", s.get("strikePrice", 0))
        ce = s.get("call", s.get("CE", {})) or {}
        pe = s.get("put", s.get("PE", {})) or {}
        ce_oi = ce.get("oi", ce.get("open_interest", 0)) or 0
        pe_oi = pe.get("oi", pe.get("open_interest", 0)) or 0

        total_call_oi += ce_oi
        total_put_oi += pe_oi

        if ce_oi > max_call_oi:
            max_call_oi = ce_oi
            max_call_oi_strike = strike
        if pe_oi > max_put_oi:
            max_put_oi = pe_oi
            max_put_oi_strike = strike

        pain_data.append((strike, ce_oi, pe_oi))

    # PCR
    pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0

    # Max Pain calculation
    max_pain_strike = 0
    min_pain_value = float("inf")
    for target_strike, _, _ in pain_data:
        pain = 0
        for strike, ce_oi, pe_oi in pain_data:
            if target_strike > strike:
                pain += ce_oi * (target_strike - strike)
            elif target_strike < strike:
                pain += pe_oi * (strike - target_strike)
        if pain < min_pain_value:
            min_pain_value = pain
            max_pain_strike = target_strike

    # Signal from OI
    if pcr > 1.2:
        signal = "BULLISH"
        oi_reason = f"PCR {pcr:.2f} > 1.2 — heavy put writing = support"
    elif pcr < 0.7:
        signal = "BEARISH"
        oi_reason = f"PCR {pcr:.2f} < 0.7 — heavy call writing = resistance"
    elif pcr > 1.0:
        signal = "MILDLY_BULLISH"
        oi_reason = f"PCR {pcr:.2f} — slight put advantage"
    else:
        signal = "NEUTRAL"
        oi_reason = f"PCR {pcr:.2f} — balanced"

    return {
        "signal": signal,
        "pcr": round(pcr, 2),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "max_call_oi_strike": max_call_oi_strike,
        "max_put_oi_strike": max_put_oi_strike,
        "max_pain": max_pain_strike,
        "reason": oi_reason,
    }


# ── Full Analysis Engine ───────────────────────────────────────────────────

# Signal weights for final scoring
_SIGNAL_WEIGHTS = {
    "technicals": 0.25,   # RSI + MACD + EMA + Bollinger
    "news":       0.15,   # News sentiment from 5 sources
    "x_social":   0.10,   # X.com / social media buzz
    "oi_pcr":     0.15,   # OI analysis + PCR + max pain
    "trend":      0.10,   # Intraday price trend
    "geopolitical": 0.10, # Geopolitical / commodity risk
    "global":     0.15,   # Global indices sentiment (S&P, VIX, etc.)
}


def analyze_fno_opportunity(instrument_key):
    """
    ENHANCED multi-signal F&O analysis using XGBoost for live trading.
    
    Primary: XGBoost ML model (trained on all stock/index candles)
    Fallback: Original multi-signal heuristic engine
    
    Combines:
      1. XGBoost ML signals (primary): Learned patterns from historical trades
      2. Technical indicators: RSI, MACD, EMA crossover, Bollinger
      3. News sentiment (bonus boost)
      4. Global sentiment (bonus boost/penalty)
    
    Returns BULLISH/BEARISH/NEUTRAL with confidence score.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    # Try XGBoost first — fast, data-driven signal
    try:
        import fno_backtester
        xgb_signal = fno_backtester.get_xgb_signal(instrument_key)
        
        if xgb_signal.get("direction") != "NEUTRAL" and xgb_signal.get("xgb_available"):
            # XGBoost found a signal — boost it with sentiment check
            try:
                global_sent = get_global_sentiment()
                global_score = global_sent.get("score", 0)
            except Exception:
                global_score = 0

            confidence = xgb_signal["confidence"]
            
            # Sentiment alignment bonus
            if confidence > 0.55:  # Only for moderate+ signals
                delta = xgb_signal.get("xgb_probs", {}).get("delta", 0)
                
                if delta > 0 and global_score > 0:  # Both bullish
                    confidence *= (1 + abs(global_score) * 0.3)
                elif delta < 0 and global_score < 0:  # Both bearish
                    confidence *= (1 + abs(global_score) * 0.3)
                elif abs(global_score) > 0.4:  # Global contradicts
                    confidence *= 0.8

            xgb_signal["confidence"] = min(1.0, confidence)
            xgb_signal["global_score"] = round(global_score, 4)
            xgb_signal["weighted_score"] = xgb_signal.get("xgb_probs", {}).get("delta", 0)
            
            logger.info("XGBoost signal for %s: %s (conf=%.3f, global=%.2f)",
                       instrument_key, xgb_signal["direction"], 
                       xgb_signal["confidence"], global_score)
            
            return xgb_signal
            
    except Exception as e:
        logger.debug("XGBoost signal failed for %s, falling back to heuristic: %s",
                    instrument_key, e)

    # Fallback: Original heuristic analysis
    return _analyze_fno_opportunity_heuristic(instrument_key)


def _analyze_fno_opportunity_heuristic(instrument_key):
    """
    Original multi-signal F&O analysis engine (heuristic-based).
    Used as fallback when XGBoost unavailable or for additional context.

    Combines 6 signal sources with weighted scoring:
      1. Technical indicators (30%): RSI, MACD, EMA crossover, Bollinger
      2. News sentiment (20%): 5 news sources, recency-weighted
      3. X/Social sentiment (10%): Twitter/X posts via Google RSS
      4. OI analysis (20%): PCR, max pain, OI concentration
      5. Price trend (10%): Intraday momentum
      6. Geopolitical (10%): Commodity risk factors, global events

    Returns BULLISH/BEARISH/NEUTRAL with confidence score and per-signal breakdown.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    signals = {}
    reasons = []
    weighted_score = 0.0  # -1 (max bearish) to +1 (max bullish)

    # ── 1. Technical Indicators (30%) ──────────────────────────────────────
    try:
        tech = compute_technicals(instrument_key)
        if "error" not in tech:
            tech_scores = []

            # RSI
            rsi_sig = tech.get("rsi_signal", "NEUTRAL")
            if rsi_sig == "OVERSOLD":
                tech_scores.append(0.8)  # Strong buy (mean reversion)
            elif rsi_sig == "OVERBOUGHT":
                tech_scores.append(-0.8)
            elif rsi_sig == "BULLISH":
                tech_scores.append(0.4)
            elif rsi_sig == "BEARISH":
                tech_scores.append(-0.4)
            else:
                tech_scores.append(0)

            # MACD
            macd_dir = tech.get("macd_direction", "NEUTRAL")
            if macd_dir == "BULLISH":
                tech_scores.append(0.5)
            elif macd_dir == "BEARISH":
                tech_scores.append(-0.5)
            else:
                tech_scores.append(0)

            # EMA crossover
            ema_sig = tech.get("ema_signal", "NEUTRAL")
            if ema_sig == "BULLISH":
                tech_scores.append(0.5)
            elif ema_sig == "BEARISH":
                tech_scores.append(-0.5)
            else:
                tech_scores.append(0)

            # Bollinger
            bb_sig = tech.get("bb_signal", "NEUTRAL")
            if bb_sig == "OVERSOLD":
                tech_scores.append(0.6)  # Near lower band = buy
            elif bb_sig == "OVERBOUGHT":
                tech_scores.append(-0.6)
            elif bb_sig == "BULLISH":
                tech_scores.append(0.3)
            elif bb_sig == "BEARISH":
                tech_scores.append(-0.3)
            else:
                tech_scores.append(0)

            # ── SMM Course Indicators ────────────────────────────────────

            # Stochastic Oscillator (SMM Part 4)
            stoch_sig = tech.get("stoch_signal", "NEUTRAL")
            if stoch_sig == "OVERSOLD":
                tech_scores.append(0.7)
            elif stoch_sig == "OVERBOUGHT":
                tech_scores.append(-0.7)
            elif stoch_sig == "BULLISH":
                tech_scores.append(0.3)
            elif stoch_sig == "BEARISH":
                tech_scores.append(-0.3)
            else:
                tech_scores.append(0)

            # Candlestick Patterns (SMM Part 1)
            candle_score = tech.get("candle_score", 0)
            if candle_score != 0:
                tech_scores.append(max(-1, min(1, candle_score)))

            # RSI Divergence (SMM Part 4) — strong reversal signal
            rsi_div = tech.get("rsi_divergence", "NONE")
            if rsi_div == "BULLISH":
                tech_scores.append(0.6)
            elif rsi_div == "BEARISH":
                tech_scores.append(-0.6)

            # DOW Volume Confirmation (SMM Part 1)
            dow = tech.get("dow_confirmation", "")
            if dow == "CONFIRMED_UP":
                tech_scores.append(0.4)
            elif dow == "CONFIRMED_DOWN":
                tech_scores.append(-0.4)
            elif dow == "WEAK_UP":
                tech_scores.append(0.1)
            elif dow == "WEAK_DOWN":
                tech_scores.append(-0.1)

            tech_avg = sum(tech_scores) / len(tech_scores) if tech_scores else 0
            weighted_score += tech_avg * _SIGNAL_WEIGHTS["technicals"]

            tech_signal = "BULLISH" if tech_avg > 0.15 else ("BEARISH" if tech_avg < -0.15 else "NEUTRAL")
            signals["technicals"] = {
                "signal": tech_signal,
                "score": round(tech_avg, 3),
                "rsi": tech.get("rsi"),
                "rsi_signal": rsi_sig,
                "macd_direction": macd_dir,
                "ema_signal": ema_sig,
                "bb_signal": bb_sig,
                "stoch_signal": stoch_sig,
                "stoch_k": tech.get("stoch_k"),
                "candle_patterns": tech.get("candle_patterns", []),
                "candle_signal": tech.get("candle_signal"),
                "rsi_divergence": rsi_div,
                "dow_confirmation": dow,
                "fibonacci": tech.get("fibonacci"),
                "nearest_fib": tech.get("nearest_fib"),
                "support": tech.get("support"),
                "resistance": tech.get("resistance"),
            }
            # Build detailed reason
            reason_parts = [f"RSI={tech.get('rsi', '?')}", f"MACD={macd_dir}", f"EMA={ema_sig}"]
            if stoch_sig != "NEUTRAL":
                reason_parts.append(f"Stoch={stoch_sig}({tech.get('stoch_k', '?')})")
            if tech.get("candle_patterns"):
                reason_parts.append(f"Candles={','.join(tech['candle_patterns'])}")
            if rsi_div != "NONE":
                reason_parts.append(f"RSI-Div={rsi_div}")
            if dow:
                reason_parts.append(f"DOW={dow}")
            if tech.get("nearest_fib"):
                reason_parts.append(f"Fib={tech['nearest_fib']}@{tech.get('nearest_fib_price')}")
            reasons.append(f"Technicals: {tech_signal} ({', '.join(reason_parts)})")
    except Exception as e:
        logger.debug("Technicals failed for %s: %s", instrument_key, e)

    # ── 2. News Sentiment (20%) ────────────────────────────────────────────
    try:
        import news_sentiment
        underlying = inst["underlying"]
        search_term = _SEARCH_MAP.get(underlying, underlying)
        news = news_sentiment.get_news_sentiment(search_term)
        if news:
            signal = news.get("signal", "NEUTRAL")
            score = news.get("score", 0)
            # Normalize score to -1..+1 range (typical scores are -0.5 to +0.5)
            norm_score = max(-1, min(1, score * 2))
            weighted_score += norm_score * _SIGNAL_WEIGHTS["news"]

            signals["news"] = {
                "signal": signal,
                "score": round(score, 3),
                "articles": news.get("total_articles", 0),
                "confidence": news.get("confidence", 0),
            }
            reasons.append(f"News: {signal} (score {score:.2f}, {news.get('total_articles', 0)} articles)")
    except Exception as e:
        logger.debug("News analysis failed for %s: %s", instrument_key, e)

    # ── 3. X/Social Sentiment (10%) ────────────────────────────────────────
    try:
        x_data = _get_x_sentiment(instrument_key)
        if x_data:
            x_signal = x_data["signal"]
            norm_x = max(-1, min(1, x_data["score"] * 2))
            weighted_score += norm_x * _SIGNAL_WEIGHTS["x_social"]

            signals["x_social"] = x_data
            reasons.append(f"X/Social: {x_signal} ({x_data['post_count']} posts, {x_data['bullish_count']}↑ {x_data['bearish_count']}↓)")
    except Exception as e:
        logger.debug("X sentiment failed for %s: %s", instrument_key, e)

    # ── 4. OI Analysis (20%) ──────────────────────────────────────────────
    if inst.get("segment") == "FNO":
        try:
            oi = _analyze_oi(instrument_key)
            if oi:
                oi_signal = oi["signal"]
                if oi_signal == "BULLISH":
                    oi_score = 0.6
                elif oi_signal == "MILDLY_BULLISH":
                    oi_score = 0.3
                elif oi_signal == "BEARISH":
                    oi_score = -0.6
                else:
                    oi_score = 0
                weighted_score += oi_score * _SIGNAL_WEIGHTS["oi_pcr"]

                signals["oi_analysis"] = oi
                reasons.append(f"OI: {oi['reason']} | Max Pain: {oi['max_pain']} | Call wall: {oi['max_call_oi_strike']} | Put wall: {oi['max_put_oi_strike']}")
        except Exception as e:
            logger.debug("OI analysis failed for %s: %s", instrument_key, e)

    # ── 5. Price Trend (10%) ──────────────────────────────────────────────
    try:
        groww = _get_groww()
        underlying = inst["underlying"]
        exchange = inst["exchange"]
        seg = inst["segment"] if inst["segment"] != "FNO" else "CASH"
        quote = groww.get_quote(trading_symbol=underlying, exchange=exchange, segment=seg)
        if quote:
            change_pct = quote.get("change_pct", quote.get("percent_change", 0)) or 0
            ltp = quote.get("ltp", quote.get("last_price", 0)) or 0

            trend_score = max(-1, min(1, change_pct / 3))  # ±3% = max signal
            weighted_score += trend_score * _SIGNAL_WEIGHTS["trend"]

            if change_pct > 1:
                trend_signal = "BULLISH"
            elif change_pct < -1:
                trend_signal = "BEARISH"
            else:
                trend_signal = "NEUTRAL"

            signals["trend"] = {"signal": trend_signal, "change_pct": round(change_pct, 2), "ltp": ltp}
            reasons.append(f"Price: {'+' if change_pct > 0 else ''}{change_pct:.1f}% today — {trend_signal.lower()}")
    except Exception as e:
        logger.debug("Quote failed for %s: %s", instrument_key, e)

    # ── 6. Geopolitical / Commodity Risk (10%) ────────────────────────────
    try:
        from commodity_tracker import get_geopolitical_context
        geo_map = {
            "CRUDEOIL": "Crude Oil", "NATURALGAS": "Coal",
            "GOLD": "Gold", "SILVER": "Gold",
            "NIFTY": None, "BANKNIFTY": None, "FINNIFTY": None,
            "SENSEX": None, "MIDCPNIFTY": None, "HDFCBANK": "HDFC Bank",
        }
        commodity_name = geo_map.get(inst["underlying"])
        if commodity_name:
            geo = get_geopolitical_context(commodity_name)
            if geo:
                risk_level = geo.get("risk_level", "low")
                risk_factors = geo.get("risk_factors", [])
                headlines = geo.get("recent_headlines", [])[:3]
                geo_score = 0
                if risk_level == "high":
                    geo_score = 0.5  # High risk = commodity bullish
                elif risk_level == "medium":
                    geo_score = 0.2

                # For commodities, geopolitical risk = bullish (supply worry)
                if inst.get("segment") == "COMMODITY":
                    weighted_score += geo_score * _SIGNAL_WEIGHTS["geopolitical"]
                    geo_signal = "BULLISH" if geo_score > 0.2 else "NEUTRAL"
                else:
                    # For indices, high geo risk = mildly bearish (uncertainty)
                    weighted_score -= geo_score * 0.5 * _SIGNAL_WEIGHTS["geopolitical"]
                    geo_signal = "BEARISH" if geo_score > 0.2 else "NEUTRAL"

                signals["geopolitical"] = {
                    "signal": geo_signal,
                    "risk_level": risk_level,
                    "risk_count": len(risk_factors),
                    "headlines": headlines,
                }
                reasons.append(f"Geopolitical: {risk_level} risk ({len(risk_factors)} factors)")
    except Exception as e:
        logger.debug("Geopolitical analysis failed for %s: %s", instrument_key, e)

    # ── 7. Global Indices Sentiment (15%) ─────────────────────────────────
    try:
        global_sent = get_global_sentiment()
        g_score = global_sent.get("score", 0)
        g_signal = global_sent.get("signal", "NEUTRAL")

        if g_score != 0:
            # For indices: direct correlation with global sentiment
            # For commodities: gold/oil have specific logic in global_sentiment already
            weighted_score += g_score * _SIGNAL_WEIGHTS["global"]

            signals["global"] = {
                "signal": g_signal,
                "score": round(g_score, 4),
                "index_count": global_sent.get("index_count", 0),
                "breakdown": global_sent.get("breakdown", {}),
            }
            reasons.append(f"Global: {g_signal} (score {g_score:.3f}, {global_sent.get('index_count', 0)} indices)")
    except Exception as e:
        logger.debug("Global sentiment failed: %s", e)

    # ── Final Decision ────────────────────────────────────────────────────
    # weighted_score: -1 (max bearish) to +1 (max bullish)
    confidence = abs(weighted_score)

    if weighted_score > 0.10:
        direction = "BULLISH"
        recommendation = "BUY CE (Call)"
        if confidence > 0.3:
            recommendation += " — STRONG conviction"
        strength = "strong" if confidence > 0.3 else "moderate" if confidence > 0.15 else "weak"
    elif weighted_score < -0.10:
        direction = "BEARISH"
        recommendation = "BUY PE (Put)"
        if confidence > 0.3:
            recommendation += " — STRONG conviction"
        strength = "strong" if confidence > 0.3 else "moderate" if confidence > 0.15 else "weak"
    else:
        direction = "NEUTRAL"
        recommendation = "WAIT — no clear direction (save your capital)"
        strength = "none"

    return {
        "instrument": instrument_key,
        "direction": direction,
        "recommendation": recommendation,
        "weighted_score": round(weighted_score, 4),
        "confidence": round(confidence, 4),
        "strength": strength,
        "signal_weights": _SIGNAL_WEIGHTS,
        "signals": signals,
        "reasons": reasons,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ORDER PLACEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def place_fno_buy(trading_symbol, instrument_key, premium_per_unit, quantity=None, reason="", prediction=None):
    """
    Place an F&O BUY order (option buying only — within capital limits).
    Respects paper trading mode.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    lot_size = inst["lot_size"]
    if quantity is None:
        quantity = lot_size  # 1 lot

    total_premium = premium_per_unit * quantity
    costs = calculate_fno_costs(premium_per_unit, quantity, exchange=inst["exchange"])
    all_in = total_premium + costs.total

    # Paper trading intercept
    try:
        from bot import is_paper_mode, _paper_trade
        if is_paper_mode():
            return _paper_trade(trading_symbol, "BUY", quantity, premium_per_unit,
                                segment=inst["segment"], product="NRML", reason=reason,
                                prediction=prediction)
    except Exception:
        pass

    # Capital check
    available = get_available_capital()
    if all_in > available:
        return {
            "error": f"Insufficient capital. Need ₹{all_in:.2f}, have ₹{available:.2f}",
            "required": round(all_in, 2),
            "available": round(available, 2),
        }

    # Safety: max budget check (never spend more than our capital)
    total_capital = get_fno_capital()
    if all_in > total_capital:
        return {"error": f"Order ₹{all_in:.2f} exceeds total F&O capital ₹{total_capital}"}

    try:
        groww = _get_groww()
        resp = groww.place_order(
            trading_symbol=trading_symbol,
            quantity=quantity,
            validity="DAY",
            exchange=inst["exchange"],
            segment=inst["segment"],
            product="NRML",  # Normal for F&O carry
            order_type="MARKET",
            transaction_type="BUY",
        )

        # Track capital deployed
        update_used_capital(all_in)

        # Log trade
        _log_fno_trade({
            "time": datetime.now().isoformat(),
            "action": "BUY",
            "trading_symbol": trading_symbol,
            "instrument": instrument_key,
            "quantity": quantity,
            "premium": premium_per_unit,
            "total_cost": round(all_in, 2),
            "charges": costs.to_dict(),
            "order_id": resp.get("groww_order_id", ""),
            "status": resp.get("order_status", ""),
        })

        return {
            "success": True,
            "order_id": resp.get("groww_order_id"),
            "status": resp.get("order_status"),
            "trading_symbol": trading_symbol,
            "quantity": quantity,
            "premium": premium_per_unit,
            "total_cost": round(all_in, 2),
            "charges": costs.to_dict(),
            "remaining_capital": round(available - all_in, 2),
        }

    except Exception as e:
        logger.exception("F&O buy failed for %s", trading_symbol)
        return {"error": str(e)}


def place_fno_sell(trading_symbol, instrument_key, quantity=None):
    """
    Sell/square off an existing F&O position (close the option buy).
    Respects paper trading mode.
    """
    inst = ALL_FNO_INSTRUMENTS.get(instrument_key)
    if not inst:
        return {"error": f"Unknown instrument: {instrument_key}"}

    if quantity is None:
        quantity = inst["lot_size"]

    # Paper trading intercept
    try:
        from bot import is_paper_mode, _paper_trade
        if is_paper_mode():
            return _paper_trade(trading_symbol, "SELL", quantity, 0,
                                segment=inst["segment"], product="NRML")
    except Exception:
        pass

    try:
        groww = _get_groww()
        resp = groww.place_order(
            trading_symbol=trading_symbol,
            quantity=quantity,
            validity="DAY",
            exchange=inst["exchange"],
            segment=inst["segment"],
            product="NRML",
            order_type="MARKET",
            transaction_type="SELL",
        )

        # Get sell premium from position/order
        try:
            ltp = groww.get_ltp(trading_symbol=trading_symbol, exchange=inst["exchange"],
                                segment=inst["segment"])
            sell_price = ltp.get("ltp", 0) if ltp else 0
            freed_capital = sell_price * quantity
            update_used_capital(-freed_capital)
        except Exception:
            pass

        _log_fno_trade({
            "time": datetime.now().isoformat(),
            "action": "SELL",
            "trading_symbol": trading_symbol,
            "instrument": instrument_key,
            "quantity": quantity,
            "order_id": resp.get("groww_order_id", ""),
            "status": resp.get("order_status", ""),
        })

        return {
            "success": True,
            "order_id": resp.get("groww_order_id"),
            "status": resp.get("order_status"),
            "trading_symbol": trading_symbol,
            "quantity": quantity,
        }

    except Exception as e:
        logger.exception("F&O sell failed for %s", trading_symbol)
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. POSITION TRACKING & TRADE LOG
# ═══════════════════════════════════════════════════════════════════════════════

def get_fno_positions():
    """Get current F&O positions from Groww."""
    try:
        groww = _get_groww()
        positions = groww.get_positions_for_user()
        # Filter to F&O only
        fno_positions = []
        if isinstance(positions, dict):
            for pos in positions.get("positions", positions.get("data", [])):
                seg = pos.get("segment", "")
                if seg in ("FNO", "COMMODITY", "FO"):
                    fno_positions.append(pos)
        return {"success": True, "positions": fno_positions}
    except Exception as e:
        logger.error("Failed to get F&O positions: %s", e)
        return {"error": str(e)}


def get_fno_margin():
    """Get available margin from Groww API."""
    try:
        groww = _get_groww()
        margin = groww.get_available_margin_details()
        return {"success": True, "margin": margin}
    except Exception as e:
        logger.error("Failed to get margin: %s", e)
        return {"error": str(e)}


def _log_fno_trade(trade_data):
    """Log F&O trade to DB for auditing."""
    try:
        from db_manager import set_cached
        import json
        # Append to trade log
        from db_manager import get_cached
        existing = get_cached("fno_trade_log", ttl_seconds=86400 * 365) or []
        existing.append(trade_data)
        # Keep last 100 trades
        set_cached("fno_trade_log", existing[-100:], cache_type="fno")
    except Exception as e:
        logger.error("Failed to log F&O trade: %s", e)


def get_fno_trade_log():
    """Get F&O trade history."""
    try:
        from db_manager import get_cached
        log = get_cached("fno_trade_log", ttl_seconds=86400 * 365) or []
        return {"success": True, "trades": log}
    except Exception:
        return {"success": True, "trades": []}


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DASHBOARD DATA — all instruments overview
# ═══════════════════════════════════════════════════════════════════════════════

def get_fno_dashboard():
    """
    Build full F&O dashboard data:
      - Available capital and positions
      - All instruments with live prices
      - Quick analysis for each
    """
    capital = get_fno_capital()
    used = get_used_capital()
    available = capital - used

    instruments = []
    for key, inst in ALL_FNO_INSTRUMENTS.items():
        lot_size = inst["lot_size"]
        # Budget check: can we afford at least 1 cheap option?
        min_cost_per_lot = 40  # brokerage alone
        can_afford = available > min_cost_per_lot

        item = {
            "key": key,
            "underlying": inst["underlying"],
            "exchange": inst["exchange"],
            "segment": inst["segment"],
            "type": inst.get("type", "commodity"),
            "lot_size": lot_size,
            "desc": inst.get("desc", key),
            "weekly_expiry": inst.get("weekly_expiry"),
            "can_afford": can_afford,
        }

        # Try to get live price from Groww
        try:
            groww = _get_groww()
            seg = inst["segment"] if inst["segment"] != "FNO" else "CASH"
            quote = groww.get_quote(
                trading_symbol=inst["underlying"],
                exchange=inst["exchange"],
                segment=seg,
            )
            if quote:
                item["ltp"] = quote.get("last_price", 0)
                item["change_pct"] = round(quote.get("day_change_perc", 0) or 0, 2)
        except Exception:
            pass

        instruments.append(item)

    return {
        "capital": {
            "total": capital,
            "used": used,
            "available": round(available, 2),
        },
        "instruments": instruments,
        "positions": get_fno_positions(),
        "trade_count": len(get_fno_trade_log().get("trades", [])),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GLOBAL INDICES MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

# Indian indices — fetched LIVE from Groww API (real-time)
GROWW_INDICES = {
    "NIFTY":      {"name": "NIFTY 50",      "exchange": "NSE", "region": "India", "weight": 0.15, "type": "equity"},
    "BANKNIFTY":  {"name": "BANK NIFTY",    "exchange": "NSE", "region": "India", "weight": 0.10, "type": "equity"},
    "FINNIFTY":   {"name": "FIN NIFTY",     "exchange": "NSE", "region": "India", "weight": 0.05, "type": "equity"},
    "SENSEX":     {"name": "SENSEX",        "exchange": "BSE", "region": "India", "weight": 0.05, "type": "equity"},
    "MIDCPNIFTY": {"name": "Midcap Select", "exchange": "NSE", "region": "India", "weight": 0.05, "type": "equity"},
    "INDIAVIX":   {"name": "India VIX",     "exchange": "NSE", "region": "India", "weight": 0.10, "type": "vix"},
}

# International indices — fetched from yfinance (Groww doesn't cover these)
INTL_INDICES = {
    "^GSPC":  {"name": "S&P 500",    "region": "US",        "weight": 0.15},
    "^IXIC":  {"name": "NASDAQ",     "region": "US",        "weight": 0.08},
    "^DJI":   {"name": "Dow Jones",  "region": "US",        "weight": 0.05},
    "^VIX":   {"name": "US VIX",     "region": "US",        "weight": 0.07},
    "^N225":  {"name": "Nikkei 225", "region": "Asia",      "weight": 0.05},
    "^HSI":   {"name": "Hang Seng",  "region": "Asia",      "weight": 0.05},
}


def _fetch_groww_indices():
    """Fetch Indian index data LIVE from Groww API — real-time prices."""
    results = {}
    try:
        groww = _get_groww()
        for symbol, meta in GROWW_INDICES.items():
            try:
                quote = groww.get_quote(
                    trading_symbol=symbol,
                    exchange=meta["exchange"],
                    segment="CASH",
                )
                if not quote:
                    continue

                ltp = quote.get("last_price", 0) or 0
                change = quote.get("day_change", 0) or 0
                change_pct = quote.get("day_change_perc", 0) or 0
                ohlc = quote.get("ohlc", {})
                prev_close = ohlc.get("close", ltp - change) if ohlc else (ltp - change)

                results[symbol] = {
                    "close": round(ltp, 2),
                    "prev_close": round(prev_close, 2),
                    "change_pct": round(change_pct, 2),
                    "day_change": round(change, 2),
                    "open": ohlc.get("open", 0) if ohlc else 0,
                    "high": ohlc.get("high", 0) if ohlc else 0,
                    "low": ohlc.get("low", 0) if ohlc else 0,
                    "week_52_high": quote.get("week_52_high", 0),
                    "week_52_low": quote.get("week_52_low", 0),
                    "name": meta["name"],
                    "region": meta["region"],
                    "weight": meta["weight"],
                    "source": "groww",
                    "type": meta.get("type", "equity"),
                }
            except Exception as e:
                logger.debug("Groww quote failed for %s: %s", symbol, e)
    except Exception as e:
        logger.warning("Groww indices fetch failed: %s", e)
    return results


def _fetch_intl_indices():
    """Fetch international indices via yfinance (Groww doesn't cover them)."""
    results = {}
    try:
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_one(ticker):
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if hist.empty or len(hist) < 2:
                    return ticker, None
                close_today = float(hist["Close"].iloc[-1])
                close_prev = float(hist["Close"].iloc[-2])
                change_pct = ((close_today - close_prev) / close_prev) * 100
                close_5d_ago = float(hist["Close"].iloc[0])
                trend_5d = ((close_today - close_5d_ago) / close_5d_ago) * 100
                return ticker, {
                    "close": round(close_today, 2),
                    "prev_close": round(close_prev, 2),
                    "change_pct": round(change_pct, 2),
                    "trend_5d_pct": round(trend_5d, 2),
                }
            except Exception as e:
                logger.debug("yfinance failed for %s: %s", ticker, e)
                return ticker, None

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch_one, t): t for t in INTL_INDICES}
            for fut in futures:
                try:
                    ticker, data = fut.result(timeout=20)
                    if data:
                        meta = INTL_INDICES[ticker]
                        results[ticker] = {
                            **data,
                            "name": meta["name"],
                            "region": meta["region"],
                            "weight": meta["weight"],
                            "source": "yfinance",
                        }
                except Exception:
                    pass
    except ImportError:
        logger.debug("yfinance not available for international indices")
    except Exception as e:
        logger.warning("International indices fetch failed: %s", e)
    return results


def fetch_global_indices():
    """
    Fetch all indices: Indian from Groww (live), international from yfinance.
    Stores combined results in DB cache.
    """
    # Indian indices from Groww — always live
    results = _fetch_groww_indices()

    # International indices — yfinance
    intl = _fetch_intl_indices()
    results.update(intl)

    # Cache in DB
    if results:
        try:
            from db_manager import set_cached
            snapshot = {
                "timestamp": datetime.now().isoformat(),
                "indices": results,
            }
            set_cached("global_indices", snapshot, cache_type="fno")
        except Exception:
            pass

    return results


def get_global_sentiment():
    """
    Compute a weighted global sentiment score from all tracked indices.
    Returns score from -1 (very bearish) to +1 (very bullish) and breakdown.

    Logic:
      - Positive equity changes = bullish for Indian F&O
      - High VIX (India or US) = bearish (fear/uncertainty)
      - Global equity selloff = bearish for Indian markets
    """
    # Try cache first
    try:
        from db_manager import get_cached
        cached = get_cached("global_indices", ttl_seconds=1800)  # 30 min cache
        if cached and cached.get("indices"):
            indices = cached["indices"]
        else:
            indices = fetch_global_indices()
    except Exception:
        indices = fetch_global_indices()

    if not indices:
        return {"score": 0, "signal": "UNKNOWN", "indices": {}}

    weighted_score = 0.0
    total_weight = 0.0
    breakdown = {}

    for ticker, data in indices.items():
        change = data.get("change_pct", 0)
        weight = data.get("weight", 0.05)
        idx_type = data.get("type", "")

        if ticker in ("^VIX", "INDIAVIX") or idx_type == "vix":
            # VIX: higher = more fear = bearish. Invert the signal.
            # VIX change > 10% in a day is extreme fear
            vix_score = max(-1, min(1, -change / 10))
            weighted_score += vix_score * weight
            breakdown[data.get("name", ticker)] = {
                "change_pct": change, "price": data.get("close"),
                "impact": round(vix_score, 3), "logic": "inverted (fear gauge)",
                "source": data.get("source", ""),
            }
        else:
            # Equity indices: positive change = bullish for Indian markets
            eq_score = max(-1, min(1, change / 3))
            weighted_score += eq_score * weight
            breakdown[data.get("name", ticker)] = {
                "change_pct": change, "price": data.get("close"),
                "impact": round(eq_score, 3), "logic": "positive correlation",
                "source": data.get("source", ""),
            }

        total_weight += weight

    # Normalize
    if total_weight > 0:
        weighted_score = weighted_score / total_weight

    if weighted_score > 0.15:
        signal = "BULLISH"
    elif weighted_score < -0.15:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    return {
        "score": round(weighted_score, 4),
        "signal": signal,
        "index_count": len(indices),
        "breakdown": breakdown,
        "timestamp": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 10. AUTOMATED F&O TRADING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

# Auto-trade config
_AUTO_TRADE_CONFIG = {
    "enabled": True,
    "min_confidence": 0.20,       # Minimum confidence to auto-trade
    "min_strength": "moderate",   # Minimum strength: "weak", "moderate", "strong"
    "max_positions": 2,           # Max open positions at once
    "stop_loss_pct": 50,          # Exit if premium drops 50%
    "target_pct": 80,             # Exit if premium gains 80%
    "trailing_sl_pct": 30,        # Trailing stop-loss after 30% gain
    "avoid_expiry_day": True,     # Don't enter on expiry day
    "preferred_instruments": ["NIFTY", "BANKNIFTY", "FINNIFTY"],  # Priority order
    "market_hours_only": True,
    # Indian market hours (IST)
    "nse_open_hour": 9, "nse_open_min": 20,   # Enter after 9:20 (skip first 5 min)
    "nse_close_hour": 15, "nse_close_min": 15, # Stop entering after 3:15 (before close)
    "mcx_close_hour": 23, "mcx_close_min": 30,
}


def _is_market_open():
    """Check if Indian markets are currently open (IST)."""
    now = datetime.now()  # Server runs in IST
    weekday = now.weekday()  # Mon=0 .. Sun=6

    # Markets closed on weekends
    if weekday >= 5:
        return False, "Weekend"

    hour, minute = now.hour, now.minute
    t = hour * 60 + minute

    cfg = _AUTO_TRADE_CONFIG
    nse_open = cfg["nse_open_hour"] * 60 + cfg["nse_open_min"]
    nse_close = cfg["nse_close_hour"] * 60 + cfg["nse_close_min"]

    if nse_open <= t <= nse_close:
        return True, "NSE open"
    return False, f"Market closed (NSE: 9:15-15:30, now {hour}:{minute:02d})"


def _count_open_positions():
    """Count current open F&O positions."""
    try:
        pos = get_fno_positions()
        positions = pos.get("positions", [])
        return len(positions)
    except Exception:
        return 0


def _check_position_exits():
    """
    Check all open F&O positions for stop-loss or target exit.
    Returns list of actions taken.
    """
    actions = []
    cfg = _AUTO_TRADE_CONFIG
    try:
        pos_data = get_fno_positions()
        positions = pos_data.get("positions", [])
        if not positions:
            return actions

        for pos in positions:
            trading_symbol = pos.get("tradingSymbol", pos.get("trading_symbol", ""))
            buy_price = pos.get("averagePrice", pos.get("average_price", 0)) or 0
            ltp = pos.get("ltp", pos.get("last_price", 0)) or 0
            quantity = pos.get("netQty", pos.get("quantity", pos.get("net_quantity", 0))) or 0
            segment = pos.get("segment", "FNO")

            if quantity <= 0 or buy_price <= 0 or ltp <= 0:
                continue

            pnl_pct = ((ltp - buy_price) / buy_price) * 100

            # Find instrument key from trading symbol
            instrument_key = None
            for key, inst in ALL_FNO_INSTRUMENTS.items():
                if inst["underlying"] in trading_symbol:
                    instrument_key = key
                    break

            # Stop-loss check
            if pnl_pct <= -cfg["stop_loss_pct"]:
                logger.info("AUTO-EXIT STOP-LOSS: %s at %.1f%% (bought %.2f, now %.2f)",
                           trading_symbol, pnl_pct, buy_price, ltp)
                if instrument_key:
                    result = place_fno_sell(trading_symbol, instrument_key, quantity)
                    actions.append({
                        "action": "STOP_LOSS_EXIT",
                        "symbol": trading_symbol,
                        "pnl_pct": round(pnl_pct, 2),
                        "buy_price": buy_price,
                        "exit_price": ltp,
                        "result": result,
                    })

            # Target check
            elif pnl_pct >= cfg["target_pct"]:
                logger.info("AUTO-EXIT TARGET: %s at %.1f%% (bought %.2f, now %.2f)",
                           trading_symbol, pnl_pct, buy_price, ltp)
                if instrument_key:
                    result = place_fno_sell(trading_symbol, instrument_key, quantity)
                    actions.append({
                        "action": "TARGET_EXIT",
                        "symbol": trading_symbol,
                        "pnl_pct": round(pnl_pct, 2),
                        "buy_price": buy_price,
                        "exit_price": ltp,
                        "result": result,
                    })

            # Trailing stop-loss (only if in profit)
            elif pnl_pct > cfg["trailing_sl_pct"]:
                # Check if price has pulled back from peak
                # Use a simple approach: if we're up >30% but dropping back
                peak_key = f"fno_peak:{trading_symbol}"
                try:
                    from db_manager import get_cached, set_cached
                    peak_data = get_cached(peak_key, ttl_seconds=86400)
                    peak_price = peak_data.get("peak", ltp) if peak_data else ltp

                    if ltp > peak_price:
                        set_cached(peak_key, {"peak": ltp}, cache_type="fno")
                    elif peak_price > 0:
                        drawdown_from_peak = ((peak_price - ltp) / peak_price) * 100
                        if drawdown_from_peak > 15:  # 15% drop from peak
                            logger.info("AUTO-EXIT TRAILING SL: %s dropped %.1f%% from peak %.2f",
                                       trading_symbol, drawdown_from_peak, peak_price)
                            if instrument_key:
                                result = place_fno_sell(trading_symbol, instrument_key, quantity)
                                actions.append({
                                    "action": "TRAILING_SL_EXIT",
                                    "symbol": trading_symbol,
                                    "pnl_pct": round(pnl_pct, 2),
                                    "drawdown_from_peak": round(drawdown_from_peak, 2),
                                    "result": result,
                                })
                except Exception:
                    pass

    except Exception as e:
        logger.error("Position exit check failed: %s", e)

    return actions


def _select_best_opportunity():
    """
    Scan preferred instruments, analyze each, and pick the best trade.
    Returns (instrument_key, analysis) or (None, None) if nothing qualifies.
    """
    cfg = _AUTO_TRADE_CONFIG
    best_instrument = None
    best_analysis = None
    best_confidence = 0

    # Also incorporate global sentiment
    try:
        global_sent = get_global_sentiment()
        global_score = global_sent.get("score", 0)
    except Exception:
        global_score = 0

    for instrument_key in cfg["preferred_instruments"]:
        try:
            analysis = analyze_fno_opportunity(instrument_key)
            if "error" in analysis:
                continue

            confidence = analysis.get("confidence", 0)
            strength = analysis.get("strength", "none")
            direction = analysis.get("direction", "NEUTRAL")

            # Skip neutral
            if direction == "NEUTRAL":
                continue

            # Check minimum thresholds
            strength_order = {"none": 0, "weak": 1, "moderate": 2, "strong": 3}
            min_strength_val = strength_order.get(cfg["min_strength"], 2)
            if strength_order.get(strength, 0) < min_strength_val:
                continue
            if confidence < cfg["min_confidence"]:
                continue

            # Boost/penalize based on global sentiment alignment
            adjusted_confidence = confidence
            weighted = analysis.get("weighted_score", 0)
            if weighted > 0 and global_score > 0:
                adjusted_confidence *= (1 + abs(global_score) * 0.5)  # Global confirms bullish
            elif weighted < 0 and global_score < 0:
                adjusted_confidence *= (1 + abs(global_score) * 0.5)  # Global confirms bearish
            elif abs(global_score) > 0.3:
                adjusted_confidence *= 0.7  # Global contradicts — reduce confidence

            if adjusted_confidence > best_confidence:
                best_confidence = adjusted_confidence
                best_instrument = instrument_key
                best_analysis = analysis
                best_analysis["global_adjustment"] = round(adjusted_confidence - confidence, 4)
                best_analysis["global_score"] = round(global_score, 4)

        except Exception as e:
            logger.debug("Analysis failed for %s: %s", instrument_key, e)

    return best_instrument, best_analysis


def auto_trade_fno():
    """
    Main automated F&O trading function. Called by scheduler.

    Flow:
      1. Check market hours
      2. Sync capital from Groww
      3. Check existing positions for stop-loss / target exit
      4. If room for new positions, scan for opportunities
      5. Auto-buy the best opportunity if conviction is high enough
      6. Log everything
    """
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "actions": [],
        "analysis": None,
        "skipped_reason": None,
    }

    try:
        # 1. Market hours check
        market_open, reason = _is_market_open()
        if _AUTO_TRADE_CONFIG["market_hours_only"] and not market_open:
            log_entry["skipped_reason"] = reason
            _log_auto_trade(log_entry)
            return log_entry

        # 2. Sync capital from Groww
        synced = sync_capital_from_groww()
        available = get_available_capital()
        log_entry["capital"] = {"synced": synced, "available": available}

        if available < 50:  # Need at least ₹50 to do anything meaningful
            log_entry["skipped_reason"] = f"Insufficient capital: ₹{available:.2f}"
            _log_auto_trade(log_entry)
            return log_entry

        # 3. Check positions for exit signals
        exits = _check_position_exits()
        if exits:
            log_entry["actions"].extend(exits)
            logger.info("Auto-trader executed %d exit(s)", len(exits))

        # 4. Check if we have room for new positions
        open_positions = _count_open_positions()
        max_positions = _AUTO_TRADE_CONFIG["max_positions"]

        if open_positions >= max_positions:
            log_entry["skipped_reason"] = f"Max positions reached ({open_positions}/{max_positions})"
            _log_auto_trade(log_entry)
            return log_entry

        # 5. Find best opportunity
        instrument_key, analysis = _select_best_opportunity()
        log_entry["analysis"] = analysis

        if not instrument_key or not analysis:
            log_entry["skipped_reason"] = "No qualifying opportunities"
            _log_auto_trade(log_entry)
            return log_entry

        direction = analysis["direction"]
        logger.info("Auto-trader found opportunity: %s %s (confidence: %.1f%%)",
                    instrument_key, direction, analysis["confidence"] * 100)

        # 6. Find the best affordable option to buy
        try:
            exp = get_expiries(instrument_key)
            dates = exp.get("expiry_dates", exp.get("data", []))
            if not dates:
                log_entry["skipped_reason"] = "No expiry dates available"
                _log_auto_trade(log_entry)
                return log_entry

            # Pick nearest expiry (weekly preferred)
            expiry = dates[0] if isinstance(dates[0], str) else dates[0].get("expiry_date", "")

            affordable = find_affordable_options(instrument_key, expiry)
            if "error" in affordable or not affordable.get("options"):
                log_entry["skipped_reason"] = f"No affordable options: {affordable.get('error', 'none found')}"
                _log_auto_trade(log_entry)
                return log_entry

            # Filter by direction: CE for bullish, PE for bearish
            target_type = "CE" if direction == "BULLISH" else "PE"
            candidates = [o for o in affordable["options"] if o["option_type"] == target_type]

            if not candidates:
                log_entry["skipped_reason"] = f"No affordable {target_type} options"
                _log_auto_trade(log_entry)
                return log_entry

            # Pick the best-scored option
            best_option = candidates[0]  # Already sorted by score

            # Additional liquidity filter
            if best_option.get("open_interest", 0) < 10000:
                log_entry["skipped_reason"] = f"Low OI ({best_option.get('open_interest', 0)}) — skip for liquidity"
                _log_auto_trade(log_entry)
                return log_entry

            # 7. Execute the buy
            logger.info("AUTO-BUY: %s %s at ₹%.2f (all-in ₹%.2f)",
                        best_option["trading_symbol"], target_type,
                        best_option["ltp"], best_option["all_in_cost"])

            # Build reasoning string from analysis
            analysis_reasons = analysis.get("reasons", [])
            fno_reason = f"{instrument_key} {direction} ({analysis['confidence']*100:.0f}% conf, {analysis['strength']})"
            if analysis_reasons:
                fno_reason += "\n" + "; ".join(analysis_reasons[:5])

            # Build a prediction-like dict for snapshot capture
            fno_prediction = {
                "signal": "BUY",
                "confidence": analysis.get("confidence", 0),
                "combined_score": analysis.get("score", 0),
                "indicators": analysis.get("technicals", {}),
                "reason": fno_reason,
                "sources": {
                    "fno_analysis": analysis,
                    "direction": direction,
                    "instrument": instrument_key,
                    "option": best_option.get("trading_symbol"),
                },
            }

            result = place_fno_buy(
                trading_symbol=best_option["trading_symbol"],
                instrument_key=instrument_key,
                premium_per_unit=best_option["ltp"],
                reason=fno_reason,
                prediction=fno_prediction,
            )

            log_entry["actions"].append({
                "action": "AUTO_BUY",
                "trading_symbol": best_option["trading_symbol"],
                "instrument": instrument_key,
                "direction": direction,
                "option_type": target_type,
                "premium": best_option["ltp"],
                "all_in_cost": best_option["all_in_cost"],
                "confidence": analysis["confidence"],
                "strength": analysis["strength"],
                "result": result,
            })

            if "error" in result:
                logger.warning("Auto-buy failed: %s", result["error"])
            else:
                logger.info("Auto-buy successful: order %s", result.get("order_id"))

        except Exception as e:
            logger.error("Auto-trade option selection failed: %s", e)
            log_entry["skipped_reason"] = f"Option selection error: {str(e)}"

    except Exception as e:
        logger.error("Auto-trade failed: %s", e)
        log_entry["skipped_reason"] = f"Error: {str(e)}"

    _log_auto_trade(log_entry)
    return log_entry


def _log_auto_trade(entry):
    """Log auto-trade run to DB."""
    try:
        from db_manager import get_cached, set_cached
        history = get_cached("fno_auto_trade_log", ttl_seconds=86400 * 30) or []
        history.append(entry)
        # Keep last 200 entries
        set_cached("fno_auto_trade_log", history[-200:], cache_type="fno")
    except Exception:
        pass


def get_auto_trade_log():
    """Get auto-trade history."""
    try:
        from db_manager import get_cached
        log = get_cached("fno_auto_trade_log", ttl_seconds=86400 * 30) or []
        return {"success": True, "log": log}
    except Exception:
        return {"success": True, "log": []}


def get_auto_trade_config():
    """Get current auto-trade configuration."""
    return _AUTO_TRADE_CONFIG


def update_auto_trade_config(updates):
    """Update auto-trade configuration (runtime only)."""
    for k, v in updates.items():
        if k in _AUTO_TRADE_CONFIG:
            _AUTO_TRADE_CONFIG[k] = v
    return _AUTO_TRADE_CONFIG


# ═══════════════════════════════════════════════════════════════════════════════
# 11. STRATEGY RULES
# ═══════════════════════════════════════════════════════════════════════════════

FNO_RULES = """
F&O TRADING RULES (₹1000 Capital):

1. ONLY BUY options — never sell/write (infinite risk, margin required)
2. Max 1-2 positions at a time (concentrate capital)
3. Set strict stop-loss: exit if option loses 50% of premium
4. Target: 50-100% premium gain (2x-3x return on cheap options)
5. Prefer weekly expiry for higher gamma (faster moves)
6. Trade liquid strikes only (OI > 1 lakh for index options)
7. ₹40 brokerage per round trip = 4% of capital — be selective
8. Avoid expiry day (theta decay accelerates)
9. Best time to enter: first 30 min OR after 2:30 PM
10. No overnight MCX positions with this capital — intraday only

INSTRUMENT PRIORITY (by affordability):
  1. NIFTY weekly options (lot=75, cheap OTM ₹2-10 = ₹150-750)
  2. BANKNIFTY weekly options (lot=15, ₹5-20 = ₹75-300)
  3. SENSEX weekly options (lot=10, ₹10-30 = ₹100-300)
  4. FINNIFTY weekly options (lot=25, ₹2-10 = ₹50-250)
  5. Crude Oil Mini options (lot=10, varies)
"""
