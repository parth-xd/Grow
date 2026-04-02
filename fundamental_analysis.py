"""
Fundamental Analysis Engine — Scrape and analyze company financials,
balance sheet, P&L, cash flow, competitors, and management actions.

Sources:
  - Screener.in (free public pages)
  - MoneyControl (key ratios)
  - BSE/NSE filings via Groww

Extracts: Revenue, Profit, PE, PB, ROE, ROCE, Debt/Equity, 
Promoter Holding, Free Cash Flow, Dividend Yield, Sector Peers, 
52-week high/low, and more.
"""

import logging
import re
import requests
from datetime import datetime, timedelta
from typing import Optional
from threading import Lock

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# ── Cache for fundamental analysis (TTL: 6 hours) ────────────────────────────
# In-memory cache as fast layer; DB cache as persistent layer
_cache = {}
_cache_lock = Lock()
_CACHE_TTL = timedelta(hours=6)
_CACHE_TTL_SECONDS = 6 * 3600

# ── Sector competitors mapping — loaded from DB with fallback ────────────────
_FALLBACK_COMPETITORS = {
    "ASIANPAINT": ["BERGEPAINT", "NEROLAC", "INDIGO", "AKZONOBEL"],
    "RELIANCE": ["TCS", "INFY", "HDFCBANK", "ICICIBANK"],
    "TCS": ["INFY", "WIPRO", "HCLTECH", "TECHM", "LTI"],
    "INFY": ["TCS", "WIPRO", "HCLTECH", "TECHM", "LTI"],
    "HDFCBANK": ["ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
    "ICICIBANK": ["HDFCBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
    "WIPRO": ["TCS", "INFY", "HCLTECH", "TECHM"],
    "BHARTIARTL": ["JIO", "VODAFONEIDEA", "TATACOMM"],
    "ITC": ["HINDUNILVR", "DABUR", "MARICO", "GODREJCP"],
    "SBIN": ["HDFCBANK", "ICICIBANK", "BANKBARODA", "PNB"],
    "LT": ["SIEMENS", "ABB", "BHEL", "THERMAX"],
    "SUZLON": ["TATAPOWER", "ADANIGREEN", "INOXWIND", "JSWEN"],
    "GEMAROMA": [],
}

_FALLBACK_SECTOR = {
    "ASIANPAINT": "Paints & Coatings", "RELIANCE": "Conglomerate / Oil & Gas",
    "TCS": "IT Services", "INFY": "IT Services", "HDFCBANK": "Banking",
    "ICICIBANK": "Banking", "WIPRO": "IT Services", "BHARTIARTL": "Telecom",
    "ITC": "FMCG / Tobacco", "SBIN": "Banking (PSU)",
    "LT": "Engineering / Infrastructure", "SUZLON": "Renewable Energy",
    "GEMAROMA": "Chemicals / Fragrances",
}


def _get_competitors(symbol):
    """Get competitors from DB, fallback to hardcoded."""
    try:
        from db_manager import get_competitors
        c = get_competitors(symbol)
        if c is not None:
            return c
    except Exception:
        pass
    return _FALLBACK_COMPETITORS.get(symbol, [])


def _get_sector_display(symbol):
    """Get sector display name from DB, fallback to hardcoded."""
    try:
        from db_manager import get_stock
        s = get_stock(symbol)
        if s and s.sector_display:
            return s.sector_display
    except Exception:
        pass
    return _FALLBACK_SECTOR.get(symbol, "Unknown")


def _safe_float(text):
    """Extract a float from a string like '₹1,234.56' or '12.3%'."""
    if not text:
        return None
    cleaned = re.sub(r"[₹,%\s\xa0]", "", str(text).replace(",", "").replace("&nbsp;", ""))
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def scrape_annual_financials(symbol):
    """
    Scrape year-wise P&L data from Screener.in.
    Returns list of dicts like:
    [{"year": "Mar 2022", "revenue": 29101, "expenses": 24298, "operating_profit": 4804,
      "net_profit": 3085, "eps": 31.59, "opm_pct": 16.5}, ...]
    Also returns YoY growth rates.
    """
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code == 404:
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            return {"years": [], "annual": [], "growth": []}

        html = resp.text

        # Find the profit-loss section
        pl_idx = html.find('id="profit-loss"')
        if pl_idx == -1:
            return {"years": [], "annual": [], "growth": []}

        section = html[pl_idx:pl_idx+30000]

        # Extract year headers from first table only (P&L, not balance sheet)
        first_table = re.search(r'<table[^>]*>(.*?)</table>', section, re.DOTALL)
        if not first_table:
            return {"years": [], "annual": [], "growth": []}

        table_html = first_table.group(1)
        # Year labels from th tags
        year_labels = re.findall(r'>\s*((?:Mar|Jun|Sep|Dec)\s+\d{4})\s*<', table_html)
        has_ttm = bool(re.search(r'>\s*TTM\s*<', table_html))
        if has_ttm:
            year_labels.append("TTM")

        # Extract rows
        tbody = re.search(r'</thead>\s*(.*)', table_html, re.DOTALL)
        if not tbody:
            return {"years": year_labels, "annual": [], "growth": []}

        rows_html = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.DOTALL)

        # Parse each row
        row_data = {}
        row_keys = {
            "sales": "revenue", "revenue": "revenue",
            "expenses": "expenses",
            "operating profit": "operating_profit",
            "other income": "other_income",
            "interest": "interest",
            "depreciation": "depreciation",
            "profit before tax": "pbt",
            "net profit": "net_profit",
            "eps in rs": "eps",
            "opm": "opm_pct",
            "dividend payout": "dividend_payout",
        }

        for row in rows_html:
            label_m = re.search(r'class="text"[^>]*>\s*(?:<[^>]*>)*\s*([^<]+)', row)
            if not label_m:
                continue
            raw_label = label_m.group(1).replace("&nbsp;", "").strip().lower()
            key = None
            for k, v in row_keys.items():
                if k in raw_label:
                    key = v
                    break
            if not key:
                continue

            cells = re.findall(r'<td[^>]*>\s*([\d,.-]+)\s*</td>', row)
            row_data[key] = [_safe_float(c) for c in cells]

        # Build annual data (align with year labels — take last N values matching year count)
        n_years = len(year_labels)
        annual = []
        for i in range(n_years):
            entry = {"year": year_labels[i]}
            for key, values in row_data.items():
                if i < len(values):
                    entry[key] = values[i]
            # Compute OPM% if not present
            if "opm_pct" not in entry and entry.get("revenue") and entry.get("operating_profit"):
                entry["opm_pct"] = round(entry["operating_profit"] / entry["revenue"] * 100, 1)
            # Net profit margin
            if entry.get("revenue") and entry.get("net_profit"):
                entry["npm_pct"] = round(entry["net_profit"] / entry["revenue"] * 100, 1)
            annual.append(entry)

        # Take last 5 years + TTM (skip old data)
        if len(annual) > 6:
            annual = annual[-6:]

        # Compute YoY growth
        growth = []
        for i in range(1, len(annual)):
            prev = annual[i - 1]
            curr = annual[i]
            g = {"year": curr["year"]}
            for metric in ["revenue", "operating_profit", "net_profit", "eps"]:
                pv = prev.get(metric)
                cv = curr.get(metric)
                if pv and cv and pv != 0:
                    g[f"{metric}_growth"] = round(((cv - pv) / abs(pv)) * 100, 1)
            growth.append(g)

        return {"years": [a["year"] for a in annual], "annual": annual, "growth": growth}

    except Exception as e:
        logger.warning("Annual financials scrape failed for %s: %s", symbol, e)
        return {"years": [], "annual": [], "growth": []}


def _scrape_screener(symbol):
    """
    Scrape key financial data from Screener.in.
    Returns dict with revenue, profit, PE, PB, ROE, ROCE, debt_to_equity, 
    promoter_holding, market_cap, dividend_yield, book_value, free_cash_flow, etc.
    """
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    data = {}
    
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 404:
            # Try standalone instead of consolidated
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=_HEADERS, timeout=10)
        
        if resp.status_code != 200:
            logger.warning("Screener returned %d for %s", resp.status_code, symbol)
            return data
        
        html = resp.text
        
        # ── Key ratios from the top section ──────────────────────────────
        patterns = {
            "market_cap": r"Market Cap[^₹]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
            "pe_ratio": r"Stock P/E[^0-9]*([\d.]+)",
            "pb_ratio": r"Book Value[^₹]*₹\s*([\d,]+(?:\.\d+)?)",
            "dividend_yield": r"Dividend Yield[^0-9]*([\d.]+)\s*%",
            "roce": r"ROCE[^0-9]*([\d.]+)\s*%",
            "roe": r"ROE[^0-9]*([\d.]+)\s*%",
            "face_value": r"Face Value[^₹]*₹\s*([\d.]+)",
            "book_value": r"Book Value[^₹]*₹\s*([\d,]+(?:\.\d+)?)",
            "high_low": r"High / Low[^₹]*₹?\s*([\d,]+)\s*/\s*₹?\s*([\d,]+)",
            "debt_to_equity": r"Debt to equity[^0-9]*([\d.]+)",
            "promoter_holding": r"Promoter holding[^0-9]*([\d.]+)\s*%",
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                if key == "high_low":
                    data["52w_high"] = _safe_float(match.group(1))
                    data["52w_low"] = _safe_float(match.group(2))
                else:
                    data[key] = _safe_float(match.group(1))
        
        # ── Quarterly results (latest quarter revenue & profit) ──────────
        # Look for "Quarterly Results" table
        qr_match = re.search(
            r'Sales.*?<td[^>]*>([\d,]+)</td>.*?Net Profit.*?<td[^>]*>([\d,.-]+)</td>',
            html, re.DOTALL | re.IGNORECASE
        )
        if qr_match:
            data["latest_quarterly_revenue"] = _safe_float(qr_match.group(1))
            data["latest_quarterly_profit"] = _safe_float(qr_match.group(2))
        
        # ── Annual revenue & profit trend (last 3 years) ────────────────
        # Extract from "Profit & Loss" section
        revenue_match = re.findall(
            r'Sales.*?<td[^>]*>([\d,]+)</td>', html, re.DOTALL | re.IGNORECASE
        )
        profit_match = re.findall(
            r'Net Profit.*?<td[^>]*>([\d,.-]+)</td>', html, re.DOTALL | re.IGNORECASE
        )
        
        if revenue_match:
            data["revenue_trend"] = [_safe_float(r) for r in revenue_match[-4:]]
        if profit_match:
            data["profit_trend"] = [_safe_float(p) for p in profit_match[-4:]]
        
        # ── Cash flow (operating cash flow) ──────────────────────────────
        ocf_match = re.search(
            r'Cash from Operating Activity.*?<td[^>]*>([\d,.-]+)</td>',
            html, re.DOTALL | re.IGNORECASE
        )
        if ocf_match:
            data["operating_cash_flow"] = _safe_float(ocf_match.group(1))
        
        # ── Free cash flow (OCF - Capex) ─────────────────────────────────
        fcf_match = re.search(
            r'Free Cash Flow.*?<td[^>]*>([\d,.-]+)</td>',
            html, re.DOTALL | re.IGNORECASE
        )
        if fcf_match:
            data["free_cash_flow"] = _safe_float(fcf_match.group(1))
        
    except requests.RequestException as e:
        logger.warning("Screener scrape failed for %s: %s", symbol, e)
    except Exception as e:
        logger.warning("Screener parse error for %s: %s", symbol, e)
    
    return data


def _get_groww_quote_fundamentals(groww_api, symbol):
    """Extract fundamental data from Groww quote API."""
    data = {}
    try:
        quote = groww_api.get_quote(exchange="NSE", trading_symbol=symbol)
        if quote:
            data["ltp"] = quote.get("ltp", 0)
            data["open"] = quote.get("open", 0)
            data["high"] = quote.get("high", 0)
            data["low"] = quote.get("low", 0)
            data["prev_close"] = quote.get("prev_close", 0)
            data["volume"] = quote.get("volume", 0)
            data["avg_volume"] = quote.get("avg_traded_volume", 0)
            data["upper_circuit"] = quote.get("upper_circuit", 0)
            data["lower_circuit"] = quote.get("lower_circuit", 0)
            
            # Volume spike detection
            if data["avg_volume"] and data["volume"]:
                data["volume_ratio"] = round(data["volume"] / data["avg_volume"], 2) if data["avg_volume"] > 0 else 1.0
            else:
                data["volume_ratio"] = 1.0
    except Exception as e:
        logger.warning("Groww quote fundamentals failed for %s: %s", symbol, e)
    return data


def _analyze_financials(screener_data):
    """
    Analyze raw financial data and generate scores & flags.
    
    Scoring:
      - Revenue growing → +1
      - Profit growing → +1 
      - ROE > 15% → +1
      - ROCE > 15% → +1
      - Debt/Equity < 1 → +1
      - PE < industry avg → +1
      - Promoter holding > 50% → +1
      - Positive FCF → +1
      - Dividend paying → +0.5
    """
    score = 0
    max_score = 9.5
    flags = []
    concerns = []
    
    # Revenue growth
    rev = screener_data.get("revenue_trend", [])
    if len(rev) >= 2 and rev[-1] and rev[-2]:
        rev_growth = (rev[-1] - rev[-2]) / rev[-2] * 100 if rev[-2] != 0 else 0
        if rev_growth > 10:
            score += 1
            flags.append(f"Revenue growing {rev_growth:.0f}% YoY")
        elif rev_growth > 0:
            score += 0.5
            flags.append(f"Revenue growing {rev_growth:.0f}% YoY (moderate)")
        else:
            concerns.append(f"Revenue declining {rev_growth:.0f}% YoY")
    
    # Profit growth
    prof = screener_data.get("profit_trend", [])
    if len(prof) >= 2 and prof[-1] and prof[-2]:
        prof_growth = (prof[-1] - prof[-2]) / prof[-2] * 100 if prof[-2] != 0 else 0
        if prof_growth > 10:
            score += 1
            flags.append(f"Profit growing {prof_growth:.0f}% YoY")
        elif prof_growth > 0:
            score += 0.5
            flags.append(f"Profit growing {prof_growth:.0f}% YoY (moderate)")
        elif prof[-1] and prof[-1] < 0:
            concerns.append("Company is loss-making")
        else:
            concerns.append(f"Profit declining {prof_growth:.0f}% YoY")
    
    # ROE
    roe = screener_data.get("roe")
    if roe is not None:
        if roe > 20:
            score += 1
            flags.append(f"ROE {roe:.1f}% — excellent capital efficiency")
        elif roe > 15:
            score += 0.75
            flags.append(f"ROE {roe:.1f}% — good")
        elif roe > 10:
            score += 0.5
            flags.append(f"ROE {roe:.1f}% — average")
        else:
            concerns.append(f"ROE {roe:.1f}% — poor capital efficiency")
    
    # ROCE
    roce = screener_data.get("roce")
    if roce is not None:
        if roce > 20:
            score += 1
            flags.append(f"ROCE {roce:.1f}% — efficient capital employed")
        elif roce > 15:
            score += 0.75
            flags.append(f"ROCE {roce:.1f}% — decent")
        elif roce > 10:
            score += 0.5
        else:
            concerns.append(f"ROCE {roce:.1f}% — low returns on capital")
    
    # Debt/Equity
    de = screener_data.get("debt_to_equity")
    if de is not None:
        if de < 0.3:
            score += 1
            flags.append(f"Debt/Equity {de:.2f} — almost debt-free")
        elif de < 1:
            score += 0.75
            flags.append(f"Debt/Equity {de:.2f} — manageable")
        elif de < 2:
            score += 0.25
            concerns.append(f"Debt/Equity {de:.2f} — moderately leveraged")
        else:
            concerns.append(f"Debt/Equity {de:.2f} — highly leveraged")
    
    # PE Ratio
    pe = screener_data.get("pe_ratio")
    if pe is not None:
        if pe < 15:
            score += 1
            flags.append(f"PE {pe:.1f} — undervalued")
        elif pe < 25:
            score += 0.5
            flags.append(f"PE {pe:.1f} — fairly valued")
        elif pe < 50:
            concerns.append(f"PE {pe:.1f} — expensive")
        else:
            concerns.append(f"PE {pe:.1f} — very expensive")
    
    # Promoter holding
    ph = screener_data.get("promoter_holding")
    if ph is not None:
        if ph > 60:
            score += 1
            flags.append(f"Promoter holding {ph:.1f}% — strong insider confidence")
        elif ph > 50:
            score += 0.75
            flags.append(f"Promoter holding {ph:.1f}% — decent")
        elif ph > 30:
            score += 0.5
        else:
            concerns.append(f"Promoter holding {ph:.1f}% — low insider ownership")
    
    # Free cash flow
    fcf = screener_data.get("free_cash_flow")
    if fcf is not None:
        if fcf > 0:
            score += 1
            flags.append(f"Positive free cash flow: ₹{fcf:,.0f} Cr")
        else:
            concerns.append(f"Negative free cash flow: ₹{fcf:,.0f} Cr")
    
    # Dividend yield
    dy = screener_data.get("dividend_yield")
    if dy is not None and dy > 0:
        score += 0.5
        flags.append(f"Dividend yield {dy:.1f}%")
    
    # Overall rating
    pct = (score / max_score) * 100
    if pct >= 70:
        rating = "STRONG"
    elif pct >= 50:
        rating = "MODERATE"
    elif pct >= 30:
        rating = "WEAK"
    else:
        rating = "POOR"
    
    return {
        "fundamental_score": round(score, 1),
        "max_score": max_score,
        "fundamental_pct": round(pct, 1),
        "fundamental_rating": rating,
        "positive_flags": flags,
        "concerns": concerns,
    }


def _fetch_competitor_prices(groww_api, symbol):
    """Fetch LTP of competitors for comparison."""
    peers = _get_competitors(symbol)
    peer_data = []
    
    for peer in peers[:5]:  # Max 5 competitors
        try:
            quote = groww_api.get_quote(exchange="NSE", trading_symbol=peer)
            if quote:
                ltp = quote.get("ltp", 0)
                prev = quote.get("prev_close", 0)
                change_pct = round((ltp - prev) / prev * 100, 2) if prev else 0
                peer_data.append({
                    "symbol": peer,
                    "ltp": ltp,
                    "change_pct": change_pct,
                })
        except Exception:
            pass
    
    return peer_data


def get_fundamental_analysis(groww_api, symbol):
    """
    Full fundamental analysis of a stock (cached for 6 hours).
    
    Args:
        groww_api: Authenticated GrowwAPI instance
        symbol: Stock trading symbol
    
    Returns dict with all fundamentals data needed for decisions.
    """
    global _cache
    
    # Check in-memory cache first
    with _cache_lock:
        if symbol in _cache:
            cached_result, cached_time = _cache[symbol]
            if datetime.now() - cached_time < _CACHE_TTL:
                logger.debug(f"Using cached fundamental analysis for {symbol}")
                return cached_result

    # Check DB cache as persistent fallback
    try:
        from db_manager import get_cached
        db_cached = get_cached(f"fundamentals_{symbol}", ttl_seconds=_CACHE_TTL_SECONDS)
        if db_cached:
            with _cache_lock:
                _cache[symbol] = (db_cached, datetime.now())
            return db_cached
    except Exception:
        pass
    
    result = {
        "symbol": symbol,
        "sector": _get_sector_display(symbol),
        "analysis_time": datetime.now().isoformat(),
    }
    
    # ── 1. Screener financials ───────────────────────────────────────────
    screener_data = _scrape_screener(symbol)
    result["financials"] = screener_data
    
    # ── 2. Analyze financials ────────────────────────────────────────────
    analysis = _analyze_financials(screener_data)
    result.update(analysis)
    
    # ── 3. Live quote data ───────────────────────────────────────────────
    quote_data = _get_groww_quote_fundamentals(groww_api, symbol)
    result["quote"] = quote_data
    
    # ── 4. Volume analysis ───────────────────────────────────────────────
    vol_ratio = quote_data.get("volume_ratio", 1.0)
    if vol_ratio > 2.0:
        result["volume_signal"] = "HIGH_VOLUME"
        result["positive_flags"].append(f"Volume spike: {vol_ratio:.1f}x average — institutional interest likely")
    elif vol_ratio > 1.5:
        result["volume_signal"] = "ABOVE_AVERAGE"
    elif vol_ratio < 0.5:
        result["volume_signal"] = "LOW_VOLUME"
        result["concerns"].append("Very low volume — liquidity risk")
    else:
        result["volume_signal"] = "NORMAL"
    
    # ── 5. 52-week position ──────────────────────────────────────────────
    h52 = screener_data.get("52w_high")
    l52 = screener_data.get("52w_low")
    ltp = quote_data.get("ltp", 0)
    if h52 and l52 and ltp and h52 > l52:
        position_pct = round((ltp - l52) / (h52 - l52) * 100, 1)
        result["52w_position_pct"] = position_pct
        result["52w_high"] = h52
        result["52w_low"] = l52
        
        if position_pct > 90:
            result["concerns"].append(f"Trading near 52-week high ({position_pct:.0f}%) — limited upside")
        elif position_pct < 20:
            result["positive_flags"].append(f"Near 52-week low ({position_pct:.0f}%) — potential value buy")
    
    # ── 6. Competitor comparison ─────────────────────────────────────────
    competitors = _fetch_competitor_prices(groww_api, symbol)
    result["competitors"] = competitors
    
    if competitors:
        avg_peer_change = sum(c["change_pct"] for c in competitors) / len(competitors)
        stock_change = quote_data.get("ltp", 0) - quote_data.get("prev_close", 0)
        stock_change_pct = round(stock_change / quote_data["prev_close"] * 100, 2) if quote_data.get("prev_close") else 0
        
        result["vs_peers"] = round(stock_change_pct - avg_peer_change, 2)
        if result["vs_peers"] > 1:
            result["positive_flags"].append(f"Outperforming peers by {result['vs_peers']:.1f}%")
        elif result["vs_peers"] < -1:
            result["concerns"].append(f"Underperforming peers by {abs(result['vs_peers']):.1f}%")
    
    # Store in memory cache + DB cache
    with _cache_lock:
        _cache[symbol] = (result, datetime.now())
    try:
        from db_manager import set_cached
        set_cached(f"fundamentals_{symbol}", result, cache_type="fundamentals")
    except Exception:
        pass
    
    return result
