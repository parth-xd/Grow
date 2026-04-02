"""
Commodity & Environmental Factor Tracker

Tracks commodity prices (crude oil, gold, etc.) and maps them to stock
dependencies. For example:
  - Asian Paints → crude oil (naphtha is a key raw material)
  - Tata Steel  → iron ore, coking coal
  - IT stocks   → INR/USD exchange rate
  - ONGC        → crude oil (direct revenue link)

Stock-commodity mappings are now read from the DB `stocks` table.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Thread pool for running blocking calls with timeouts
_executor = ThreadPoolExecutor(max_workers=2)

# ── Stock-to-Commodity dependency — loaded from DB ─────────────────────────
_FALLBACK_COMMODITY_MAP = {
    "ASIANPAINT": {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.35},
    "BERGEPAINT": {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.35},
    "KANSAINER":  {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.30},
    "ONGC":       {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "direct", "weight": 0.50},
    "RELIANCE":   {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "direct", "weight": 0.25},
    "BPCL":       {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.30},
    "IOC":        {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.30},
    "TATASTEEL":  {"commodity": "Iron Ore / Steel", "ticker": "TIO=F", "relationship": "direct", "weight": 0.40},
    "JSWSTEEL":   {"commodity": "Iron Ore / Steel", "ticker": "TIO=F", "relationship": "direct", "weight": 0.40},
    "HINDALCO":   {"commodity": "Aluminium", "ticker": "ALI=F", "relationship": "direct", "weight": 0.45},
    "VEDL":       {"commodity": "Zinc / Base Metals", "ticker": "ZNC=F", "relationship": "direct", "weight": 0.35},
    "COALINDIA":  {"commodity": "Coal", "ticker": "MTF=F", "relationship": "direct", "weight": 0.50},
    "TCS":        {"commodity": "USD/INR", "ticker": "USDINR=X", "relationship": "direct", "weight": 0.20},
    "INFY":       {"commodity": "USD/INR", "ticker": "USDINR=X", "relationship": "direct", "weight": 0.20},
    "WIPRO":      {"commodity": "USD/INR", "ticker": "USDINR=X", "relationship": "direct", "weight": 0.20},
    "HCLTECH":    {"commodity": "USD/INR", "ticker": "USDINR=X", "relationship": "direct", "weight": 0.20},
    "TITAN":      {"commodity": "Gold", "ticker": "GC=F", "relationship": "direct", "weight": 0.30},
    "KALYANKJIL": {"commodity": "Gold", "ticker": "GC=F", "relationship": "direct", "weight": 0.40},
    "INDIGO":     {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.40},
    "SPICEJET":   {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.45},
    "APOLLOTYRE": {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.25},
    "MRF":        {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.25},
    "PIDILITIND": {"commodity": "Crude Oil", "ticker": "CL=F", "relationship": "inverse", "weight": 0.20},
}

_commodity_map_cache = None


def _get_commodity_map():
    """Get commodity map from DB, with in-memory cache and fallback."""
    global _commodity_map_cache
    if _commodity_map_cache is not None:
        return _commodity_map_cache
    try:
        from db_manager import get_commodity_map
        m = get_commodity_map()
        if m:
            _commodity_map_cache = m
            return m
    except Exception:
        pass
    return _FALLBACK_COMMODITY_MAP


def get_commodity_map_dict():
    """Public accessor for the commodity map (used by app.py)."""
    return _get_commodity_map()


# ── Geopolitical context map ────────────────────────────────────────────────
# Maps commodities to current geopolitical events/search terms that affect them
GEOPOLITICAL_CONTEXT = {
    "Crude Oil": {
        "search_terms": [
            "Iran Israel war crude oil",
            "Strait of Hormuz oil tanker",
            "Middle East conflict oil supply",
            "OPEC production cut",
            "Red Sea Houthi oil shipping",
            "Russia Ukraine oil sanctions",
            "oil supply disruption geopolitical",
        ],
        "x_search_terms": [
            '"crude oil" "Iran" OR "Israel" OR "Hormuz" OR "Middle East"',
            '"oil prices" war OR conflict OR sanctions',
            '"Strait of Hormuz" blockade OR closure OR threat',
        ],
        "risk_factors": [
            "Iran-Israel conflict threatening Strait of Hormuz (20% of global oil transit)",
            "Red Sea/Houthi attacks on oil tankers raising shipping costs",
            "OPEC+ production decisions affecting global supply",
            "Russia-Ukraine sanctions affecting energy markets",
        ],
    },
    "Iron Ore / Steel": {
        "search_terms": [
            "China steel demand iron ore",
            "iron ore supply disruption",
            "steel tariff trade war",
        ],
        "x_search_terms": [
            '"iron ore" OR "steel prices" China OR tariff OR trade',
        ],
        "risk_factors": [
            "China demand slowdown affecting global steel/iron ore prices",
            "Trade tariffs on steel imports/exports",
        ],
    },
    "Gold": {
        "search_terms": [
            "gold safe haven war geopolitical",
            "gold prices Middle East conflict",
            "central bank gold buying",
            "gold demand geopolitical risk",
        ],
        "x_search_terms": [
            '"gold" safe haven OR war OR geopolitical OR "central bank"',
        ],
        "risk_factors": [
            "Wars/conflicts drive safe-haven gold demand",
            "Central bank gold accumulation trend",
            "Dollar weakness boosting gold prices",
        ],
    },
    "Aluminium": {
        "search_terms": [
            "aluminium supply sanctions Russia",
            "bauxite supply chain disruption",
        ],
        "x_search_terms": [
            '"aluminium" OR "aluminum" sanctions OR supply OR tariff',
        ],
        "risk_factors": [
            "Russia sanctions affecting global aluminium supply",
            "Energy costs impacting smelter economics",
        ],
    },
    "Zinc / Base Metals": {
        "search_terms": [
            "zinc supply mine disruption",
            "base metals demand China",
        ],
        "x_search_terms": [
            '"zinc" OR "base metals" supply OR demand OR China',
        ],
        "risk_factors": [
            "Mine closures affecting zinc supply",
            "China industrial activity driving demand",
        ],
    },
    "USD/INR": {
        "search_terms": [
            "rupee dollar RBI FII outflow",
            "USD INR geopolitical risk",
            "India current account deficit oil",
        ],
        "x_search_terms": [
            '"rupee" OR "USD INR" RBI OR FII OR outflow OR oil',
        ],
        "risk_factors": [
            "Rising crude oil prices widen India's current account deficit → rupee weakens",
            "FII outflows during global risk-off events",
            "RBI intervention to stabilize rupee",
        ],
    },
    "Coal": {
        "search_terms": [
            "coal prices supply disruption",
            "thermal coal demand India",
        ],
        "x_search_terms": [
            '"coal prices" supply OR demand OR India',
        ],
        "risk_factors": [
            "Energy transition reducing long-term demand",
            "Supply chain disruptions from weather/mining issues",
        ],
    },
}


def get_geopolitical_context(symbol):
    """
    Get geopolitical risk context for a stock based on its commodity dependency.
    Reads dynamic articles from DB first, falls back to static GEOPOLITICAL_CONTEXT.
    """
    mapping = _get_commodity_map().get(symbol)
    if not mapping:
        return None
    commodity_name = mapping["commodity"]

    # Try to load dynamic geopolitical data from DB
    dynamic = _get_dynamic_geopolitical(commodity_name)
    if dynamic and isinstance(dynamic, dict):
        static = GEOPOLITICAL_CONTEXT.get(commodity_name, {})
        return {
            "commodity": commodity_name,
            "relationship": mapping["relationship"],
            "search_terms": static.get("search_terms", []),
            "x_search_terms": static.get("x_search_terms", []),
            "risk_factors": dynamic.get("risk_factors", static.get("risk_factors", [])),
            "recent_headlines": dynamic.get("recent_headlines", []),
            "risk_level": dynamic.get("risk_level", "unknown"),
            "last_updated": dynamic.get("last_updated"),
        }

    # Fallback to static
    geo = GEOPOLITICAL_CONTEXT.get(commodity_name)
    if not geo:
        return None
    return {
        "commodity": commodity_name,
        "relationship": mapping["relationship"],
        **geo,
    }


def _get_dynamic_geopolitical(commodity_name):
    """Load accumulated geopolitical articles from DB for a commodity."""
    try:
        from db_manager import get_cached
        data = get_cached(f"geopolitical:{commodity_name}",
                          ttl_seconds=86400)  # 24h TTL
        if data:
            return data
    except Exception:
        pass
    return None


def collect_geopolitical_news():
    """
    Fetch geopolitical news for all commodities and store in DB.
    Called by scheduler every 30 min. Incrementally builds context
    from new articles while keeping history of past articles.
    """
    import json
    from datetime import datetime, timedelta

    for commodity_name, geo in GEOPOLITICAL_CONTEXT.items():
        try:
            # Fetch news using search terms
            new_articles = []
            search_terms = geo.get("search_terms", [])[:3]  # limit queries

            for term in search_terms:
                try:
                    from news_sentiment import _fetch_google_news
                    articles = _fetch_google_news(term, max_results=5)
                    for a in articles:
                        new_articles.append({
                            "title": a.get("title", "")[:200],
                            "source": a.get("source", ""),
                            "date": a.get("date", ""),
                            "sentiment": a.get("sentiment", 0),
                        })
                except Exception:
                    pass

            # De-duplicate by title
            seen_titles = set()
            unique_articles = []
            for a in new_articles:
                key = a["title"][:80].lower()
                if key not in seen_titles:
                    seen_titles.add(key)
                    unique_articles.append(a)

            # Load existing data from DB
            existing = _get_dynamic_geopolitical(commodity_name) or {}
            old_articles = existing.get("all_articles", [])

            # Merge: add new articles, keep last 50
            merged_titles = {a["title"][:80].lower() for a in old_articles}
            for a in unique_articles:
                if a["title"][:80].lower() not in merged_titles:
                    old_articles.append(a)
                    merged_titles.add(a["title"][:80].lower())
            all_articles = old_articles[-50:]  # keep last 50

            # Analyze: build dynamic risk factors from headlines
            risk_factors = list(geo.get("risk_factors", []))  # start with static
            recent = [a for a in all_articles[-10:] if a.get("title")]
            headlines = [a["title"] for a in recent]

            # Calculate risk level from sentiment
            sentiments = [a.get("sentiment", 0) for a in all_articles[-20:] if a.get("sentiment")]
            avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0
            negative_ratio = len([s for s in sentiments if s < -0.1]) / max(len(sentiments), 1)

            if negative_ratio > 0.6:
                risk_level = "high"
            elif negative_ratio > 0.3:
                risk_level = "medium"
            else:
                risk_level = "low"

            # Add headline-derived risk factors (top negative headlines)
            negative_headlines = [a for a in recent if a.get("sentiment", 0) < -0.1]
            for nh in negative_headlines[:3]:
                factor = f"[LIVE] {nh['title']}"
                if factor not in risk_factors:
                    risk_factors.append(factor)

            # Store in DB
            data = {
                "risk_factors": risk_factors[-10:],
                "recent_headlines": headlines,
                "all_articles": all_articles,
                "risk_level": risk_level,
                "avg_sentiment": round(avg_sentiment, 3),
                "article_count": len(all_articles),
                "last_updated": datetime.utcnow().isoformat(),
            }

            try:
                from db_manager import set_cached
                set_cached(
                    f"geopolitical:{commodity_name}",
                    data,
                    cache_type="geopolitical",
                )
            except Exception as e:
                logger.warning("Failed to store geopolitical data for %s: %s", commodity_name, e)

            logger.debug("Geopolitical: %s — %d articles, risk=%s", commodity_name, len(all_articles), risk_level)

        except Exception as e:
            logger.warning("Geopolitical collection failed for %s: %s", commodity_name, e)


def get_commodity_impact(symbol):
    """
    Fetch commodity data for a stock and return its impact analysis.

    Returns dict with:
      - commodity: name of the commodity
      - ticker: yfinance ticker
      - relationship: "inverse" or "direct"
      - trend: "RISING" / "FALLING" / "STABLE"
      - price_change_pct: % change over lookback period
      - current_price: latest commodity price
      - summary: human-readable impact summary
    Returns None if the stock has no known commodity dependency.
    """
    mapping = _get_commodity_map().get(symbol)
    if not mapping:
        return None

    commodity_name = mapping["commodity"]
    ticker = mapping["ticker"]
    relationship = mapping["relationship"]
    weight = mapping["weight"]

    try:
        import yfinance as yf

        future = _executor.submit(yf.download, ticker, period="3mo", interval="1wk", progress=False)
        try:
            data = future.result(timeout=15)
        except FuturesTimeout:
            logger.warning("yfinance download timed out for %s (%s)", commodity_name, ticker)
            future.cancel()
            return _fallback_result(commodity_name, relationship)

        if data.empty or len(data) < 4:
            logger.warning("Insufficient commodity data for %s (%s)", commodity_name, ticker)
            return _fallback_result(commodity_name, relationship)

        # Handle multi-level columns from yfinance
        close_col = data["Close"]
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]

        current_price = float(close_col.iloc[-1])
        price_1m_ago = float(close_col.iloc[-4]) if len(close_col) >= 4 else current_price
        price_3m_ago = float(close_col.iloc[0])

        # Short-term (1 month) change
        change_1m_pct = ((current_price - price_1m_ago) / price_1m_ago * 100) if price_1m_ago > 0 else 0
        # Longer-term (3 month) change
        change_3m_pct = ((current_price - price_3m_ago) / price_3m_ago * 100) if price_3m_ago > 0 else 0

        # Determine trend from weighted short + long term
        weighted_change = change_1m_pct * 0.6 + change_3m_pct * 0.4

        if weighted_change > 5:
            trend = "RISING"
        elif weighted_change < -5:
            trend = "FALLING"
        else:
            trend = "STABLE"

        # Build summary
        if relationship == "inverse":
            if trend == "RISING":
                impact = "negative (higher input costs)"
            elif trend == "FALLING":
                impact = "positive (lower input costs)"
            else:
                impact = "neutral (stable input costs)"
        else:
            if trend == "RISING":
                impact = "positive (higher revenue/realizations)"
            elif trend == "FALLING":
                impact = "negative (lower revenue/realizations)"
            else:
                impact = "neutral (stable prices)"

        summary = f"{commodity_name} is {trend.lower()} ({change_1m_pct:+.1f}% 1M, {change_3m_pct:+.1f}% 3M) → {impact} for {symbol}"

        return {
            "commodity": commodity_name,
            "ticker": ticker,
            "relationship": relationship,
            "weight": weight,
            "trend": trend,
            "price_change_pct": round(change_1m_pct, 1),
            "price_change_3m_pct": round(change_3m_pct, 1),
            "current_price": round(current_price, 2),
            "summary": summary,
        }

    except ImportError:
        logger.warning("yfinance not installed — commodity tracking disabled")
        return None
    except Exception as e:
        logger.warning("Failed to fetch commodity data for %s (%s): %s", symbol, ticker, e)
        return _fallback_result(commodity_name, relationship)


def _fallback_result(commodity_name, relationship):
    """Return a neutral fallback when data fetch fails."""
    return {
        "commodity": commodity_name,
        "relationship": relationship,
        "trend": "UNKNOWN",
        "price_change_pct": 0,
        "price_change_3m_pct": 0,
        "current_price": 0,
        "summary": f"{commodity_name} data unavailable — could not assess impact",
    }


# ── Supply Chain / Global Production Data ─────────────────────────────────
# ISO 3166-1 numeric codes used by TopoJSON world-110m
# producers: list of {country, iso_n3, share_pct, role, volume}
# chokepoints: key transit routes / supply bottlenecks
# disruptions: current active disruptions with severity
COMMODITY_SUPPLY_CHAIN = {
    "Crude Oil": {
        "unit": "million barrels/day",
        "global_production": 101.0,
        "producers": [
            {"country": "United States",   "iso_a3": "USA", "iso_n3": "840", "share_pct": 19.5, "role": "Producer",  "volume": "19.7 mb/d"},
            {"country": "Saudi Arabia",    "iso_a3": "SAU", "iso_n3": "682", "share_pct": 12.1, "role": "Producer & Exporter", "volume": "12.2 mb/d"},
            {"country": "Russia",          "iso_a3": "RUS", "iso_n3": "643", "share_pct": 11.2, "role": "Producer & Exporter", "volume": "11.3 mb/d"},
            {"country": "Canada",          "iso_a3": "CAN", "iso_n3": "124", "share_pct": 5.7,  "role": "Producer & Exporter", "volume": "5.8 mb/d"},
            {"country": "Iraq",            "iso_a3": "IRQ", "iso_n3": "368", "share_pct": 4.5,  "role": "OPEC Producer", "volume": "4.5 mb/d"},
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 4.1,  "role": "Producer & Importer", "volume": "4.1 mb/d"},
            {"country": "UAE",             "iso_a3": "ARE", "iso_n3": "784", "share_pct": 3.8,  "role": "OPEC Exporter", "volume": "3.8 mb/d"},
            {"country": "Brazil",          "iso_a3": "BRA", "iso_n3": "076", "share_pct": 3.7,  "role": "Producer",  "volume": "3.7 mb/d"},
            {"country": "Iran",            "iso_a3": "IRN", "iso_n3": "364", "share_pct": 3.6,  "role": "OPEC (sanctioned)", "volume": "3.6 mb/d"},
            {"country": "Kuwait",          "iso_a3": "KWT", "iso_n3": "414", "share_pct": 2.7,  "role": "OPEC Exporter", "volume": "2.7 mb/d"},
        ],
        "top_importers": [
            {"country": "China",  "iso_a3": "CHN", "iso_n3": "156", "volume": "11.4 mb/d"},
            {"country": "India",  "iso_a3": "IND", "iso_n3": "356", "volume": "4.8 mb/d"},
            {"country": "Japan",  "iso_a3": "JPN", "iso_n3": "392", "volume": "2.5 mb/d"},
            {"country": "South Korea", "iso_a3": "KOR", "iso_n3": "410", "volume": "2.8 mb/d"},
        ],
        "chokepoints": [
            {"name": "Strait of Hormuz", "lat": 26.5, "lon": 56.3, "flow": "21 mb/d (21% of global)", "risk": "high"},
            {"name": "Strait of Malacca", "lat": 2.5, "lon": 101.0, "flow": "16 mb/d", "risk": "medium"},
            {"name": "Suez Canal", "lat": 30.5, "lon": 32.3, "flow": "5.5 mb/d", "risk": "high"},
            {"name": "Bab el-Mandeb", "lat": 12.6, "lon": 43.3, "flow": "6.2 mb/d", "risk": "high"},
        ],
        "disruptions": [
            {"region": "Iran-Israel Conflict", "iso_a3": "IRN", "iso_n3": "364", "severity": "critical", "desc": "Threat to Strait of Hormuz — 20% of global oil transit at risk"},
            {"region": "Red Sea / Houthi Attacks", "iso_a3": "YEM", "iso_n3": "887", "severity": "high", "desc": "Houthi attacks on tankers → +$2-4/barrel shipping premium"},
            {"region": "Russia Sanctions", "iso_a3": "RUS", "iso_n3": "643", "severity": "medium", "desc": "Western sanctions redirecting Russian crude to Asia"},
        ],
    },
    "Iron Ore / Steel": {
        "unit": "million tonnes/year",
        "global_production": 2500,
        "producers": [
            {"country": "Australia",       "iso_a3": "AUS", "iso_n3": "036", "share_pct": 36.0, "role": "Top Exporter", "volume": "900 Mt"},
            {"country": "Brazil",          "iso_a3": "BRA", "iso_n3": "076", "share_pct": 15.2, "role": "Major Exporter", "volume": "380 Mt"},
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 14.0, "role": "Producer & Top Importer", "volume": "350 Mt"},
            {"country": "India",           "iso_a3": "IND", "iso_n3": "356", "share_pct": 10.4, "role": "Producer & Exporter", "volume": "260 Mt"},
            {"country": "Russia",          "iso_a3": "RUS", "iso_n3": "643", "share_pct": 4.0,  "role": "Producer", "volume": "100 Mt"},
            {"country": "South Africa",    "iso_a3": "ZAF", "iso_n3": "710", "share_pct": 2.8,  "role": "Exporter",  "volume": "70 Mt"},
            {"country": "Ukraine",         "iso_a3": "UKR", "iso_n3": "804", "share_pct": 2.4,  "role": "Producer (disrupted)", "volume": "60 Mt"},
            {"country": "Canada",          "iso_a3": "CAN", "iso_n3": "124", "share_pct": 1.6,  "role": "Producer",  "volume": "40 Mt"},
        ],
        "top_importers": [
            {"country": "China",  "iso_a3": "CHN", "iso_n3": "156", "volume": "1,120 Mt (70% of seaborne)"},
            {"country": "Japan",  "iso_a3": "JPN", "iso_n3": "392", "volume": "100 Mt"},
            {"country": "South Korea", "iso_a3": "KOR", "iso_n3": "410", "volume": "70 Mt"},
        ],
        "chokepoints": [
            {"name": "Cape of Good Hope", "lat": -34.4, "lon": 18.5, "flow": "Brazil→Asia route", "risk": "low"},
            {"name": "Strait of Malacca", "lat": 2.5, "lon": 101.0, "flow": "Australia→China route", "risk": "medium"},
        ],
        "disruptions": [
            {"region": "China Demand Slowdown", "iso_a3": "CHN", "iso_n3": "156", "severity": "high", "desc": "Property crisis reducing steel demand → iron ore price pressure"},
            {"region": "Ukraine War", "iso_a3": "UKR", "iso_n3": "804", "severity": "medium", "desc": "Ukrainian iron ore/steel exports heavily disrupted since 2022"},
        ],
    },
    "Gold": {
        "unit": "tonnes/year",
        "global_production": 3650,
        "producers": [
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 10.0, "role": "Top Producer", "volume": "370 t"},
            {"country": "Australia",       "iso_a3": "AUS", "iso_n3": "036", "share_pct": 8.8,  "role": "Major Producer", "volume": "320 t"},
            {"country": "Russia",          "iso_a3": "RUS", "iso_n3": "643", "share_pct": 8.5,  "role": "Major Producer", "volume": "310 t"},
            {"country": "Canada",          "iso_a3": "CAN", "iso_n3": "124", "share_pct": 5.5,  "role": "Producer",  "volume": "200 t"},
            {"country": "United States",   "iso_a3": "USA", "iso_n3": "840", "share_pct": 4.8,  "role": "Producer",  "volume": "175 t"},
            {"country": "Ghana",           "iso_a3": "GHA", "iso_n3": "288", "share_pct": 3.8,  "role": "African Leader", "volume": "140 t"},
            {"country": "Peru",            "iso_a3": "PER", "iso_n3": "604", "share_pct": 3.6,  "role": "Producer",  "volume": "130 t"},
            {"country": "Mexico",          "iso_a3": "MEX", "iso_n3": "484", "share_pct": 2.9,  "role": "Producer",  "volume": "105 t"},
            {"country": "Indonesia",       "iso_a3": "IDN", "iso_n3": "360", "share_pct": 3.6,  "role": "Producer (Grasberg)", "volume": "130 t"},
            {"country": "South Africa",    "iso_a3": "ZAF", "iso_n3": "710", "share_pct": 2.7,  "role": "Historic producer", "volume": "100 t"},
        ],
        "top_importers": [
            {"country": "India",   "iso_a3": "IND", "iso_n3": "356", "volume": "700-800 t (world's largest)"},
            {"country": "China",   "iso_a3": "CHN", "iso_n3": "156", "volume": "600 t"},
            {"country": "Switzerland", "iso_a3": "CHE", "iso_n3": "756", "volume": "Refining hub"},
        ],
        "chokepoints": [],
        "disruptions": [
            {"region": "Central Bank Buying", "iso_a3": "CHN", "iso_n3": "156", "severity": "medium", "desc": "China & emerging market CBs aggressively accumulating gold reserves"},
            {"region": "Geopolitical Safe Haven", "iso_a3": "USA", "iso_n3": "840", "severity": "low", "desc": "Wars & conflicts driving safe-haven buying — structural floor on prices"},
        ],
    },
    "Aluminium": {
        "unit": "million tonnes/year",
        "global_production": 70,
        "producers": [
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 58.0, "role": "Dominant Producer", "volume": "40.6 Mt"},
            {"country": "India",           "iso_a3": "IND", "iso_n3": "356", "share_pct": 5.7,  "role": "Growing Producer", "volume": "4.0 Mt"},
            {"country": "Russia",          "iso_a3": "RUS", "iso_n3": "643", "share_pct": 5.4,  "role": "Producer (Rusal)", "volume": "3.8 Mt"},
            {"country": "Canada",          "iso_a3": "CAN", "iso_n3": "124", "share_pct": 4.3,  "role": "Hydro-powered smelting", "volume": "3.0 Mt"},
            {"country": "UAE",             "iso_a3": "ARE", "iso_n3": "784", "share_pct": 3.7,  "role": "Gulf smelting hub", "volume": "2.6 Mt"},
            {"country": "Australia",       "iso_a3": "AUS", "iso_n3": "036", "share_pct": 2.3,  "role": "Bauxite & smelting", "volume": "1.6 Mt"},
            {"country": "Norway",          "iso_a3": "NOR", "iso_n3": "578", "share_pct": 1.9,  "role": "Hydro smelting",  "volume": "1.3 Mt"},
            {"country": "Guinea",          "iso_a3": "GIN", "iso_n3": "324", "share_pct": 0,    "role": "Top Bauxite Exporter", "volume": "Bauxite: 110 Mt"},
        ],
        "top_importers": [
            {"country": "Japan",  "iso_a3": "JPN", "iso_n3": "392", "volume": "Major importer"},
            {"country": "Germany", "iso_a3": "DEU", "iso_n3": "276", "volume": "European demand"},
        ],
        "chokepoints": [],
        "disruptions": [
            {"region": "Russia Sanctions Risk", "iso_a3": "RUS", "iso_n3": "643", "severity": "medium", "desc": "Rusal supplies ~6% of global Al — sanctions risk premiums remain"},
            {"region": "Guinea Instability", "iso_a3": "GIN", "iso_n3": "324", "severity": "high", "desc": "Military coup 2021 threatens world's largest bauxite reserves"},
            {"region": "China Energy Curbs", "iso_a3": "CHN", "iso_n3": "156", "severity": "medium", "desc": "Power rationing in Yunnan/Sichuan cuts smelter output"},
        ],
    },
    "Zinc / Base Metals": {
        "unit": "million tonnes/year",
        "global_production": 13.0,
        "producers": [
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 33.0, "role": "Top Producer", "volume": "4.3 Mt"},
            {"country": "Peru",            "iso_a3": "PER", "iso_n3": "604", "share_pct": 11.5, "role": "Major Miner", "volume": "1.5 Mt"},
            {"country": "Australia",       "iso_a3": "AUS", "iso_n3": "036", "share_pct": 10.0, "role": "Major Miner", "volume": "1.3 Mt"},
            {"country": "India",           "iso_a3": "IND", "iso_n3": "356", "share_pct": 6.2,  "role": "Vedanta/HZL", "volume": "0.8 Mt"},
            {"country": "United States",   "iso_a3": "USA", "iso_n3": "840", "share_pct": 5.4,  "role": "Producer",  "volume": "0.7 Mt"},
            {"country": "Mexico",          "iso_a3": "MEX", "iso_n3": "484", "share_pct": 5.0,  "role": "Producer",  "volume": "0.65 Mt"},
            {"country": "Canada",          "iso_a3": "CAN", "iso_n3": "124", "share_pct": 2.3,  "role": "Producer",  "volume": "0.3 Mt"},
        ],
        "top_importers": [
            {"country": "China",  "iso_a3": "CHN", "iso_n3": "156", "volume": "Net importer of concentrate"},
            {"country": "South Korea", "iso_a3": "KOR", "iso_n3": "410", "volume": "Smelting imports"},
        ],
        "chokepoints": [],
        "disruptions": [
            {"region": "Peru Mining Protests", "iso_a3": "PER", "iso_n3": "604", "severity": "medium", "desc": "Recurring community protests blocking mine operations"},
            {"region": "China Smelter Cuts", "iso_a3": "CHN", "iso_n3": "156", "severity": "low", "desc": "Environmental regulations tightening smelter output"},
        ],
    },
    "Coal": {
        "unit": "million tonnes/year",
        "global_production": 8700,
        "producers": [
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 52.0, "role": "Top Producer & Consumer", "volume": "4,500 Mt"},
            {"country": "India",           "iso_a3": "IND", "iso_n3": "356", "share_pct": 10.3, "role": "2nd Producer", "volume": "900 Mt"},
            {"country": "Indonesia",       "iso_a3": "IDN", "iso_n3": "360", "share_pct": 7.8,  "role": "Top Exporter", "volume": "680 Mt"},
            {"country": "United States",   "iso_a3": "USA", "iso_n3": "840", "share_pct": 6.3,  "role": "Producer (declining)", "volume": "550 Mt"},
            {"country": "Australia",       "iso_a3": "AUS", "iso_n3": "036", "share_pct": 5.7,  "role": "Major Exporter", "volume": "500 Mt"},
            {"country": "Russia",          "iso_a3": "RUS", "iso_n3": "643", "share_pct": 4.8,  "role": "Producer & Exporter", "volume": "420 Mt"},
            {"country": "South Africa",    "iso_a3": "ZAF", "iso_n3": "710", "share_pct": 3.2,  "role": "Exporter", "volume": "280 Mt"},
        ],
        "top_importers": [
            {"country": "China",  "iso_a3": "CHN", "iso_n3": "156", "volume": "300 Mt (net)"},
            {"country": "India",  "iso_a3": "IND", "iso_n3": "356", "volume": "230 Mt"},
            {"country": "Japan",  "iso_a3": "JPN", "iso_n3": "392", "volume": "175 Mt"},
        ],
        "chokepoints": [],
        "disruptions": [
            {"region": "Indonesia Export Ban Risk", "iso_a3": "IDN", "iso_n3": "360", "severity": "high", "desc": "Periodic coal export bans to ensure domestic supply"},
            {"region": "Australia-China Trade", "iso_a3": "AUS", "iso_n3": "036", "severity": "medium", "desc": "China reducing Australian coal imports amid political tensions"},
        ],
    },
    "USD/INR": {
        "unit": "exchange rate",
        "global_production": 0,
        "producers": [
            {"country": "United States",   "iso_a3": "USA", "iso_n3": "840", "share_pct": 60.0, "role": "Reserve Currency Issuer", "volume": "Dollar Index ~104"},
            {"country": "India",           "iso_a3": "IND", "iso_n3": "356", "share_pct": 0,    "role": "INR — RBI managed", "volume": "~₹83-84/USD"},
            {"country": "China",           "iso_a3": "CHN", "iso_n3": "156", "share_pct": 0,    "role": "Yuan affects EM currencies", "volume": "CNY/USD ~7.2"},
            {"country": "Japan",           "iso_a3": "JPN", "iso_n3": "392", "share_pct": 0,    "role": "Yen carry trade impact", "volume": "JPY/USD ~155"},
        ],
        "top_importers": [],
        "chokepoints": [],
        "disruptions": [
            {"region": "FII Outflows", "iso_a3": "IND", "iso_n3": "356", "severity": "medium", "desc": "FII selling → INR depreciation pressure → benefits IT exporters"},
            {"region": "Fed Rate Policy", "iso_a3": "USA", "iso_n3": "840", "severity": "high", "desc": "Higher-for-longer US rates strengthening dollar vs EM currencies"},
        ],
    },
}


def get_supply_chain_data():
    """Return supply chain data for all commodities."""
    return COMMODITY_SUPPLY_CHAIN
