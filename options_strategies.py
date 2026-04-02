"""
Options Strategies Lab — Black-Scholes pricing, Greeks, IV, and strategy P&L analysis.

Features:
  • Black-Scholes option pricing (calls + puts)
  • Full Greeks: Delta, Gamma, Theta, Vega, Rho
  • Implied Volatility via Newton-Raphson
  • IV Rank & IV Percentile
  • 7 pre-built strategies: Bull/Bear spreads, Straddle, Strangle, Iron Condor, Butterfly, Covered Call
  • Payoff curve generation for charting
  • Max profit, max loss, breakeven calculation
"""

import logging
import math
import numpy as np
from scipy.stats import norm
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Black-Scholes Model ────────────────────────────────────────────────────

def _d1(S, K, T, r, sigma):
    return (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))

def _d2(S, K, T, r, sigma):
    return _d1(S, K, T, r, sigma) - sigma * math.sqrt(T)


def bs_call_price(S, K, T, r, sigma):
    """Black-Scholes European call price."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_put_price(S, K, T, r, sigma):
    """Black-Scholes European put price."""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0)
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# ─── Greeks ──────────────────────────────────────────────────────────────────

def greeks(S, K, T, r, sigma, option_type="call"):
    """Calculate all Greeks for a European option.
    Returns dict with delta, gamma, theta, vega, rho."""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}

    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    sqrt_T = math.sqrt(T)

    gamma = norm.pdf(d1) / (S * sigma * sqrt_T)
    vega = S * norm.pdf(d1) * sqrt_T / 100  # per 1% IV change

    if option_type == "call":
        delta = norm.cdf(d1)
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * sqrt_T)
                 - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365
        rho = K * T * math.exp(-r * T) * norm.cdf(d2) / 100
    else:
        delta = norm.cdf(d1) - 1
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * sqrt_T)
                 + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


def full_analysis(S, K, T, r, sigma, option_type="call"):
    """Full option analysis: price + all Greeks."""
    price = bs_call_price(S, K, T, r, sigma) if option_type == "call" else bs_put_price(S, K, T, r, sigma)
    g = greeks(S, K, T, r, sigma, option_type)
    intrinsic = max(S - K, 0) if option_type == "call" else max(K - S, 0)
    return {
        "price": round(price, 2),
        "intrinsic": round(intrinsic, 2),
        "time_value": round(price - intrinsic, 2),
        "option_type": option_type,
        "spot": S, "strike": K,
        "time_to_expiry_years": round(T, 4),
        "risk_free_rate": r,
        "volatility": sigma,
        **g,
    }


# ─── Implied Volatility ─────────────────────────────────────────────────────

def implied_volatility(market_price, S, K, T, r, option_type="call",
                       max_iter=100, tol=1e-6):
    """Calculate IV using Newton-Raphson method."""
    if T <= 0:
        return 0
    sigma = 0.3  # Initial guess

    for _ in range(max_iter):
        if option_type == "call":
            price = bs_call_price(S, K, T, r, sigma)
        else:
            price = bs_put_price(S, K, T, r, sigma)

        diff = price - market_price
        if abs(diff) < tol:
            return round(sigma, 4)

        # Vega for Newton-Raphson step
        d1 = _d1(S, K, T, r, sigma)
        vega = S * norm.pdf(d1) * math.sqrt(T)
        if vega < 1e-10:
            break

        sigma -= diff / vega
        sigma = max(sigma, 0.001)
        sigma = min(sigma, 5.0)

    return round(sigma, 4)


def iv_rank(current_iv, iv_high_52w, iv_low_52w):
    """IV Rank: where current IV sits in 52-week range (0-100)."""
    rng = iv_high_52w - iv_low_52w
    if rng <= 0:
        return 50
    return round((current_iv - iv_low_52w) / rng * 100, 1)


# ─── Strategy Definitions ────────────────────────────────────────────────────

STRATEGY_DEFS = {
    "bull_call_spread": {
        "name": "Bull Call Spread",
        "desc": "Buy lower strike call, sell higher strike call. Bullish, limited risk/reward.",
        "legs": 2, "direction": "BULLISH",
    },
    "bear_put_spread": {
        "name": "Bear Put Spread",
        "desc": "Buy higher strike put, sell lower strike put. Bearish, limited risk/reward.",
        "legs": 2, "direction": "BEARISH",
    },
    "long_straddle": {
        "name": "Long Straddle",
        "desc": "Buy ATM call + ATM put. Profits from big moves either direction.",
        "legs": 2, "direction": "NEUTRAL",
    },
    "long_strangle": {
        "name": "Long Strangle",
        "desc": "Buy OTM call + OTM put. Cheaper than straddle, needs bigger move.",
        "legs": 2, "direction": "NEUTRAL",
    },
    "iron_condor": {
        "name": "Iron Condor",
        "desc": "Sell OTM call + put spreads. Profits from range-bound market.",
        "legs": 4, "direction": "NEUTRAL",
    },
    "iron_butterfly": {
        "name": "Iron Butterfly",
        "desc": "Sell ATM straddle + buy OTM wings. Max profit at strike.",
        "legs": 4, "direction": "NEUTRAL",
    },
    "covered_call": {
        "name": "Covered Call",
        "desc": "Hold stock + sell OTM call. Generate income, cap upside.",
        "legs": 1, "direction": "MILDLY_BULLISH",
    },
}


def get_strategy_list():
    """Return available strategy definitions for UI."""
    return STRATEGY_DEFS


# ─── Strategy Builder ────────────────────────────────────────────────────────

def build_strategy(strategy_type, S, strikes, premiums, T, r, sigma, lot_size=1):
    """
    Build a strategy and return full analysis.

    Args:
        strategy_type: key from STRATEGY_DEFS
        S: current spot price
        strikes: list of strike prices (varies by strategy)
        premiums: list of market premiums (same order as strikes)
        T: time to expiry in years
        r: risk-free rate
        sigma: IV
        lot_size: contract lot size

    Returns:
        dict with legs, max_profit, max_loss, breakevens, payoff_curve
    """
    builders = {
        "bull_call_spread": _build_bull_call,
        "bear_put_spread": _build_bear_put,
        "long_straddle": _build_straddle,
        "long_strangle": _build_strangle,
        "iron_condor": _build_iron_condor,
        "iron_butterfly": _build_iron_butterfly,
        "covered_call": _build_covered_call,
    }

    builder = builders.get(strategy_type)
    if not builder:
        return {"error": f"Unknown strategy: {strategy_type}"}

    try:
        result = builder(S, strikes, premiums, T, r, sigma, lot_size)
        result["strategy"] = strategy_type
        result["strategy_name"] = STRATEGY_DEFS[strategy_type]["name"]
        result["direction"] = STRATEGY_DEFS[strategy_type]["direction"]
        result["spot"] = S
        result["lot_size"] = lot_size
        return result
    except Exception as e:
        return {"error": str(e)}


def _payoff_range(S, padding_pct=20, points=100):
    """Generate price range for payoff curve."""
    low = S * (1 - padding_pct / 100)
    high = S * (1 + padding_pct / 100)
    return np.linspace(low, high, points)


def _call_payoff(price, strike, premium, qty):
    """Call payoff at expiry (per unit)."""
    return (max(price - strike, 0) - premium) * qty


def _put_payoff(price, strike, premium, qty):
    """Put payoff at expiry (per unit)."""
    return (max(strike - price, 0) - premium) * qty


def _build_bull_call(S, strikes, premiums, T, r, sigma, lot_size):
    """Bull Call Spread: Buy K1 call, Sell K2 call (K2 > K1)."""
    K1, K2 = strikes[0], strikes[1]
    P1, P2 = premiums[0], premiums[1]

    net_debit = (P1 - P2) * lot_size
    max_profit = (K2 - K1) * lot_size - net_debit
    max_loss = net_debit
    breakeven = K1 + (P1 - P2)

    prices = _payoff_range(S)
    payoff = []
    for p in prices:
        pnl = (_call_payoff(p, K1, P1, 1) + _call_payoff(p, K2, -P2, -1)) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "CALL", "strike": K1, "action": "BUY", "premium": P1},
            {"type": "CALL", "strike": K2, "action": "SELL", "premium": P2},
        ],
        "net_debit": round(net_debit, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(-max_loss, 2),
        "breakevens": [round(breakeven, 2)],
        "payoff_curve": payoff,
    }


def _build_bear_put(S, strikes, premiums, T, r, sigma, lot_size):
    """Bear Put Spread: Buy K2 put, Sell K1 put (K2 > K1)."""
    K1, K2 = strikes[0], strikes[1]
    P1, P2 = premiums[0], premiums[1]  # P1=lower put premium, P2=higher put premium

    net_debit = (P2 - P1) * lot_size
    max_profit = (K2 - K1) * lot_size - net_debit
    max_loss = net_debit
    breakeven = K2 - (P2 - P1)

    prices = _payoff_range(S)
    payoff = []
    for p in prices:
        pnl = (_put_payoff(p, K2, P2, 1) + _put_payoff(p, K1, -P1, -1)) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "PUT", "strike": K1, "action": "SELL", "premium": P1},
            {"type": "PUT", "strike": K2, "action": "BUY", "premium": P2},
        ],
        "net_debit": round(net_debit, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(-max_loss, 2),
        "breakevens": [round(breakeven, 2)],
        "payoff_curve": payoff,
    }


def _build_straddle(S, strikes, premiums, T, r, sigma, lot_size):
    """Long Straddle: Buy ATM call + Buy ATM put at same strike."""
    K = strikes[0]
    Pc, Pp = premiums[0], premiums[1]  # call premium, put premium

    total_cost = (Pc + Pp) * lot_size
    be_upper = K + Pc + Pp
    be_lower = K - Pc - Pp

    prices = _payoff_range(S, padding_pct=25)
    payoff = []
    for p in prices:
        pnl = (_call_payoff(p, K, Pc, 1) + _put_payoff(p, K, Pp, 1)) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "CALL", "strike": K, "action": "BUY", "premium": Pc},
            {"type": "PUT", "strike": K, "action": "BUY", "premium": Pp},
        ],
        "net_debit": round(total_cost, 2),
        "max_profit": "UNLIMITED",
        "max_loss": round(-total_cost, 2),
        "breakevens": [round(be_lower, 2), round(be_upper, 2)],
        "payoff_curve": payoff,
    }


def _build_strangle(S, strikes, premiums, T, r, sigma, lot_size):
    """Long Strangle: Buy OTM put (K1) + Buy OTM call (K2), K1 < K2."""
    K1, K2 = strikes[0], strikes[1]
    Pp, Pc = premiums[0], premiums[1]

    total_cost = (Pp + Pc) * lot_size
    be_lower = K1 - Pp - Pc
    be_upper = K2 + Pp + Pc

    prices = _payoff_range(S, padding_pct=25)
    payoff = []
    for p in prices:
        pnl = (_put_payoff(p, K1, Pp, 1) + _call_payoff(p, K2, Pc, 1)) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "PUT", "strike": K1, "action": "BUY", "premium": Pp},
            {"type": "CALL", "strike": K2, "action": "BUY", "premium": Pc},
        ],
        "net_debit": round(total_cost, 2),
        "max_profit": "UNLIMITED",
        "max_loss": round(-total_cost, 2),
        "breakevens": [round(be_lower, 2), round(be_upper, 2)],
        "payoff_curve": payoff,
    }


def _build_iron_condor(S, strikes, premiums, T, r, sigma, lot_size):
    """Iron Condor: Buy K1 put, Sell K2 put, Sell K3 call, Buy K4 call."""
    K1, K2, K3, K4 = strikes
    P1, P2, P3, P4 = premiums  # premiums in order of strikes

    net_credit = (P2 + P3 - P1 - P4) * lot_size
    max_profit = net_credit
    max_loss_put = (K2 - K1) * lot_size - net_credit
    max_loss_call = (K4 - K3) * lot_size - net_credit
    max_loss = max(max_loss_put, max_loss_call)
    be_lower = K2 - (P2 + P3 - P1 - P4)
    be_upper = K3 + (P2 + P3 - P1 - P4)

    prices = _payoff_range(S)
    payoff = []
    for p in prices:
        pnl = (_put_payoff(p, K1, P1, -1) +  # buy put = -1 cost direction
               _put_payoff(p, K2, -P2, 1) +   # sell put
               _call_payoff(p, K3, -P3, 1) +  # sell call
               _call_payoff(p, K4, P4, -1)     # buy call
               ) * lot_size
        # Simpler: calculate directly
        put_spread = max(K2 - p, 0) - max(K1 - p, 0)
        call_spread = max(p - K3, 0) - max(p - K4, 0)
        pnl = (-(put_spread + call_spread) + (P2 + P3 - P1 - P4)) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "PUT", "strike": K1, "action": "BUY", "premium": P1},
            {"type": "PUT", "strike": K2, "action": "SELL", "premium": P2},
            {"type": "CALL", "strike": K3, "action": "SELL", "premium": P3},
            {"type": "CALL", "strike": K4, "action": "BUY", "premium": P4},
        ],
        "net_credit": round(net_credit, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(-max_loss, 2),
        "breakevens": [round(be_lower, 2), round(be_upper, 2)],
        "payoff_curve": payoff,
    }


def _build_iron_butterfly(S, strikes, premiums, T, r, sigma, lot_size):
    """Iron Butterfly: Buy K1 put, Sell K2 put+call (ATM), Buy K3 call."""
    K1, K2, K3 = strikes  # K1 < K2 (ATM) < K3
    Pp_buy, Pp_sell_and_Pc_sell, Pc_buy = premiums[0], premiums[1], premiums[2]
    # premiums[1] is the ATM (both put and call sold) — user gives them separately
    # Let's expect 4 premiums: buy_put, sell_put, sell_call, buy_call
    if len(premiums) == 4:
        P1, P2, P3, P4 = premiums
    else:
        P1 = premiums[0]  # buy OTM put
        P2 = premiums[1]  # sell ATM put
        P3 = premiums[1]  # sell ATM call (same strike)
        P4 = premiums[2]  # buy OTM call

    net_credit = (P2 + P3 - P1 - P4) * lot_size
    max_profit = net_credit
    width = max(K2 - K1, K3 - K2)
    max_loss = width * lot_size - net_credit

    be_lower = K2 - (P2 + P3 - P1 - P4)
    be_upper = K2 + (P2 + P3 - P1 - P4)

    prices = _payoff_range(S)
    payoff = []
    for p in prices:
        ps = max(K2 - p, 0) - max(K1 - p, 0)
        cs = max(p - K2, 0) - max(p - K3, 0)
        pnl = (-(ps + cs) + (P2 + P3 - P1 - P4)) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "PUT", "strike": K1, "action": "BUY", "premium": P1},
            {"type": "PUT", "strike": K2, "action": "SELL", "premium": P2},
            {"type": "CALL", "strike": K2, "action": "SELL", "premium": P3},
            {"type": "CALL", "strike": K3, "action": "BUY", "premium": P4},
        ],
        "net_credit": round(net_credit, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(-max_loss, 2),
        "breakevens": [round(be_lower, 2), round(be_upper, 2)],
        "payoff_curve": payoff,
    }


def _build_covered_call(S, strikes, premiums, T, r, sigma, lot_size):
    """Covered Call: Hold stock + Sell OTM call."""
    K = strikes[0]
    P = premiums[0]

    max_profit = (K - S + P) * lot_size
    breakeven = S - P

    prices = _payoff_range(S)
    payoff = []
    for p in prices:
        stock_pnl = p - S
        call_pnl = -(max(p - K, 0) - P)
        pnl = (stock_pnl + call_pnl) * lot_size
        payoff.append({"price": round(float(p), 2), "pnl": round(float(pnl), 2)})

    return {
        "legs": [
            {"type": "STOCK", "action": "BUY", "price": S},
            {"type": "CALL", "strike": K, "action": "SELL", "premium": P},
        ],
        "net_debit": round((S - P) * lot_size, 2),
        "max_profit": round(max_profit, 2),
        "max_loss": round(-(S - P) * lot_size, 2),
        "breakevens": [round(breakeven, 2)],
        "payoff_curve": payoff,
    }


# ─── Option Chain Analysis ───────────────────────────────────────────────────

def analyze_option_chain(chain_data, spot_price, risk_free=0.06):
    """
    Analyze a Groww option chain: compute IV, Greeks for each strike.

    Args:
        chain_data: list of {strike, call_ltp, put_ltp, call_oi, put_oi, expiry_days}
        spot_price: current spot price
        risk_free: annual risk-free rate

    Returns:
        Enriched chain with IV, Greeks, PCR analysis.
    """
    enriched = []
    total_call_oi = 0
    total_put_oi = 0

    for row in chain_data:
        K = row["strike"]
        T = max(row.get("expiry_days", 7), 1) / 365
        call_ltp = row.get("call_ltp", 0)
        put_ltp = row.get("put_ltp", 0)
        call_oi = row.get("call_oi", 0)
        put_oi = row.get("put_oi", 0)

        total_call_oi += call_oi
        total_put_oi += put_oi

        # Compute IV
        call_iv = implied_volatility(call_ltp, spot_price, K, T, risk_free, "call") if call_ltp > 0 else 0
        put_iv = implied_volatility(put_ltp, spot_price, K, T, risk_free, "put") if put_ltp > 0 else 0

        # Compute Greeks
        avg_iv = (call_iv + put_iv) / 2 if call_iv > 0 and put_iv > 0 else max(call_iv, put_iv)
        if avg_iv <= 0:
            avg_iv = 0.2

        call_greeks = greeks(spot_price, K, T, risk_free, avg_iv, "call")
        put_greeks = greeks(spot_price, K, T, risk_free, avg_iv, "put")

        enriched.append({
            "strike": K,
            "call_ltp": call_ltp,
            "put_ltp": put_ltp,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_iv": round(call_iv * 100, 1),
            "put_iv": round(put_iv * 100, 1),
            "call_greeks": call_greeks,
            "put_greeks": put_greeks,
            "moneyness": "ITM" if (spot_price > K) else ("ATM" if abs(spot_price - K) / spot_price < 0.01 else "OTM"),
        })

    # PCR
    pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 0

    # Max pain
    max_pain = _calculate_max_pain(chain_data, spot_price)

    return {
        "chain": enriched,
        "pcr": round(pcr, 2),
        "max_pain": max_pain,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
    }


def _calculate_max_pain(chain_data, spot):
    """Find the strike where total option writer pain is minimized."""
    strikes = [r["strike"] for r in chain_data]
    if not strikes:
        return spot

    min_pain = float("inf")
    max_pain_strike = spot

    for test_price in strikes:
        total_pain = 0
        for row in chain_data:
            K = row["strike"]
            call_oi = row.get("call_oi", 0)
            put_oi = row.get("put_oi", 0)
            # Call writers pain
            if test_price > K:
                total_pain += (test_price - K) * call_oi
            # Put writers pain
            if test_price < K:
                total_pain += (K - test_price) * put_oi

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = test_price

    return max_pain_strike
