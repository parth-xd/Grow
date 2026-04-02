"""
Deep Contextual Analysis Engine

Connects global events, commodities, sector trends, and macro news
to specific portfolio/watchlist stocks. Generates narrative "WHY"
explanations instead of just signals/chips.

Example output:
  "Crude oil surged +12% in 3 months due to Iran-Israel tensions threatening
   the Strait of Hormuz. Asian Paints uses naphtha (crude derivative) as key
   raw material — rising crude squeezes operating margins. OPM has already
   contracted from 20% → 16%. Combined with a BEARISH market and the stock
   trading near 5Y highs, risk-reward is unfavorable."
"""

import json
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ── Sector → News Tag Mapping ────────────────────────────────────────────────
# Maps stock sectors to relevant global_news tags for filtering
SECTOR_TAG_MAP = {
    "BANKING": ["banking", "rbi", "rate_cut", "nifty", "fii"],
    "IT": ["it_sector", "rupee", "fed", "us_jobs"],
    "PHARMA": ["pharma"],
    "AUTO": ["auto", "oil"],
    "ENERGY": ["oil", "opec"],
    "OIL_GAS": ["oil", "opec", "war", "middle_east"],
    "METALS": ["trade_war", "china"],
    "FMCG": ["fmcg", "inflation", "gdp"],
    "TELECOM": ["telecom"],
    "REAL_ESTATE": ["real_estate", "rbi", "rate_cut"],
    "PAINT": ["oil", "inflation"],
    "AIRLINE": ["oil"],
    "JEWELLERY": ["gold"],
    "FINANCE": ["rbi", "rate_cut", "banking", "fii"],
}

# Weight thresholds for dependency intensity
# weight >= 0.40 → critical dependency, 0.25-0.39 → significant, 0.15-0.24 → moderate, <0.15 → minor
def _weight_label(weight):
    """Classify commodity dependency weight into a human-readable intensity."""
    if weight >= 0.40:
        return "critical", "a critical raw material"
    elif weight >= 0.25:
        return "significant", "a significant cost/revenue driver"
    elif weight >= 0.15:
        return "moderate", "a moderate factor"
    else:
        return "minor", "a minor factor"

# Commodity → impact explanation templates
# {intensity} and {weight_pct} are injected at render time based on the stock's dependency weight
COMMODITY_IMPACT_TEMPLATES = {
    ("Crude Oil", "inverse"): {
        "RISING": "Rising crude oil (+{change}% in 3M) increases raw material costs for {company}. Crude-derived inputs are {dep_desc} ({weight_pct}% cost dependency) — {intensity_detail}.",
        "FALLING": "Falling crude oil ({change}% in 3M) reduces input costs for {company}. Crude is {dep_desc} ({weight_pct}% dependency) — {intensity_detail}.",
        "STABLE": "Crude oil prices are stable — neutral impact on {company}'s input costs ({weight_pct}% dependency).",
    },
    ("Crude Oil", "direct"): {
        "RISING": "Rising crude oil (+{change}% in 3M) boosts revenue/realizations for {company}. Oil is {dep_desc} ({weight_pct}% revenue link) — {intensity_detail}.",
        "FALLING": "Falling crude oil ({change}% in 3M) pressures {company}'s revenue. Oil is {dep_desc} ({weight_pct}% revenue link) — {intensity_detail}.",
        "STABLE": "Crude oil prices are stable — neutral impact on {company}'s revenue ({weight_pct}% link).",
    },
    ("Gold", "direct"): {
        "RISING": "Gold prices surging (+{change}% in 3M) driven by safe-haven demand — positive for {company}. Gold is {dep_desc} ({weight_pct}% dependency) — {intensity_detail}.",
        "FALLING": "Gold prices weakening ({change}% in 3M) — may reduce consumer demand for {company}. Gold is {dep_desc} ({weight_pct}% dependency).",
        "STABLE": "Gold prices stable — neutral impact on {company} ({weight_pct}% dependency).",
    },
    ("USD/INR", "direct"): {
        "RISING": "Rupee weakening against USD (+{change}%) benefits {company}'s export revenue in INR terms. Forex is {dep_desc} ({weight_pct}% exposure) — {intensity_detail}.",
        "FALLING": "Rupee strengthening vs USD ({change}%) pressures {company}'s INR revenue from exports. Forex is {dep_desc} ({weight_pct}% exposure).",
        "STABLE": "USD/INR stable — neutral forex impact on {company} ({weight_pct}% exposure).",
    },
    ("Iron Ore / Steel", "direct"): {
        "RISING": "Iron ore/steel prices rising (+{change}%) — positive for {company}'s realizations. Steel is {dep_desc} ({weight_pct}% dependency) — {intensity_detail}.",
        "FALLING": "Iron ore/steel prices falling ({change}%) — pressures {company}'s revenue. Steel is {dep_desc} ({weight_pct}% dependency).",
        "STABLE": "Steel/iron ore prices stable — neutral impact on {company} ({weight_pct}% dependency).",
    },
    ("Aluminium", "direct"): {
        "RISING": "Aluminium prices rising (+{change}%) — positive for {company}'s realizations. Aluminium is {dep_desc} ({weight_pct}% dependency) — {intensity_detail}.",
        "FALLING": "Aluminium prices falling ({change}%) — pressures {company}'s revenue. Aluminium is {dep_desc} ({weight_pct}% dependency).",
        "STABLE": "Aluminium prices stable — neutral impact on {company} ({weight_pct}% dependency).",
    },
    ("Zinc / Base Metals", "direct"): {
        "RISING": "Base metal prices rising (+{change}%) — positive for {company}'s realizations ({weight_pct}% dependency).",
        "FALLING": "Base metal prices falling ({change}%) — pressures {company}'s revenue ({weight_pct}% dependency).",
        "STABLE": "Base metal prices stable — neutral impact on {company} ({weight_pct}% dependency).",
    },
    ("Coal", "direct"): {
        "RISING": "Coal prices rising (+{change}%) — positive for {company}. Coal is {dep_desc} ({weight_pct}% dependency) — {intensity_detail}.",
        "FALLING": "Coal prices falling ({change}%) — pressures {company}'s revenue ({weight_pct}% dependency).",
        "STABLE": "Coal prices stable — neutral impact on {company} ({weight_pct}% dependency).",
    },
}


def _get_stock_info(symbol):
    """Get stock info from DB (sector, company name, commodity mapping)."""
    try:
        from config import DB_URL
        from db_manager import get_db, Stock
        session = get_db(DB_URL).Session()
        stock = session.query(Stock).filter(Stock.symbol == symbol).first()
        if stock:
            info = {
                "symbol": symbol,
                "company_name": stock.company_name,
                "sector": stock.sector or "",
                "commodity": stock.commodity,
                "commodity_ticker": stock.commodity_ticker,
                "commodity_relationship": stock.commodity_relationship,
                "commodity_weight": stock.commodity_weight or 0,
            }
            session.close()
            return info
        session.close()
    except Exception as e:
        logger.debug("DB stock lookup failed for %s: %s", symbol, e)

    # Fallback: try commodity_tracker's fallback map
    try:
        from commodity_tracker import get_commodity_map_dict
        cmap = get_commodity_map_dict()
        if not isinstance(cmap, dict):
            cmap = {}
        entry = cmap.get(symbol, {}) if isinstance(cmap, dict) else {}
        return {
            "symbol": symbol,
            "company_name": symbol,
            "sector": "",
            "commodity": entry.get("commodity") if isinstance(entry, dict) else None,
            "commodity_ticker": entry.get("ticker") if isinstance(entry, dict) else None,
            "commodity_relationship": entry.get("relationship") if isinstance(entry, dict) else None,
            "commodity_weight": entry.get("weight", 0) if isinstance(entry, dict) else 0,
        }
    except Exception as e:
        logger.debug("Commodity map fallback failed: %s", e)
        return {"symbol": symbol, "company_name": symbol, "sector": "", "commodity": None}


def _get_relevant_news(symbol, stock_info, limit=15, days=7):
    """Find global news articles relevant to this stock."""
    try:
        from world_news_collector import get_recent_news
    except ImportError:
        return []

    # Ensure stock_info is a dict
    if not isinstance(stock_info, dict):
        stock_info = {"symbol": symbol}

    articles = []
    seen_ids = set()

    def _add(items):
        if not items:
            return
        if not isinstance(items, (list, tuple)):
            return
        for a in items:
            if not isinstance(a, dict):
                continue
            aid = a.get("id")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                articles.append(a)

    # 1. Sector-based news
    sector = (stock_info.get("sector") or "").upper() if isinstance(stock_info, dict) else ""
    tags = SECTOR_TAG_MAP.get(sector, [])
    if tags:
        _add(get_recent_news(tags=tags, limit=limit, days=days))

    # 2. Commodity-linked news
    commodity = stock_info.get("commodity", "") if isinstance(stock_info, dict) else ""
    if commodity:
        commodity_tags = []
        cl = commodity.lower()
        if "crude" in cl or "oil" in cl:
            commodity_tags = ["oil", "opec", "middle_east", "war"]
        elif "gold" in cl:
            commodity_tags = ["gold"]
        elif "usd" in cl or "inr" in cl:
            commodity_tags = ["rupee", "fed"]
        elif "iron" in cl or "steel" in cl:
            commodity_tags = ["trade_war", "china"]
        if commodity_tags:
            _add(get_recent_news(tags=commodity_tags, limit=8, days=days))

    # 3. General macro (always relevant)
    _add(get_recent_news(tags=["fii", "rbi", "gdp", "inflation"], limit=5, days=days))

    # 4. Geopolitical (if commodity-linked)
    if commodity:
        _add(get_recent_news(category="geopolitical", limit=5, days=days))

    # Sort by relevance (published_at desc) and cap
    # Filter to ensure all items are dicts before sorting
    articles = [a for a in articles if isinstance(a, dict)]
    articles.sort(key=lambda a: a.get("published_at", "") if isinstance(a, dict) else "", reverse=True)
    return articles[:25]


def _build_commodity_narrative(stock_info, commodity_data):
    """Build a weight-aware narrative about commodity impact on this stock."""
    if not isinstance(commodity_data, dict) or commodity_data.get("trend") == "UNKNOWN":
        return None

    # Ensure stock_info is a dict
    if not isinstance(stock_info, dict):
        stock_info = {}

    commodity = commodity_data.get("commodity", "")
    relationship = commodity_data.get("relationship", "")
    trend = commodity_data.get("trend", "STABLE")
    change_3m = commodity_data.get("price_change_3m_pct", commodity_data.get("price_change_pct", 0))
    change_1m = commodity_data.get("price_change_pct", 0)
    company = stock_info.get("company_name", stock_info.get("symbol", "Unknown"))
    weight = (stock_info.get("commodity_weight") or commodity_data.get("weight") or 0)

    # Generate weight-aware context
    intensity, dep_desc = _weight_label(weight)
    weight_pct = round(weight * 100)

    # Intensity detail varies by weight level
    intensity_details = {
        "critical": "expect significant margin/revenue impact",
        "significant": "meaningful impact on financials expected",
        "moderate": "some impact on margins but not the dominant driver",
        "minor": "limited direct impact on overall financials",
    }
    intensity_detail = intensity_details.get(intensity, "some impact expected")

    # Get template
    key = (commodity, relationship)
    templates = COMMODITY_IMPACT_TEMPLATES.get(key)
    if not templates:
        # Generic weight-aware fallback
        if relationship == "inverse":
            if trend == "RISING":
                return f"{commodity} is rising (+{change_3m:.1f}% 3M) — negative for {company}. {commodity} is {dep_desc} ({weight_pct}% cost dependency) — {intensity_detail}."
            elif trend == "FALLING":
                return f"{commodity} is falling ({change_3m:.1f}% 3M) — positive for {company}. {commodity} is {dep_desc} ({weight_pct}% dependency) — {intensity_detail}."
        else:
            if trend == "RISING":
                return f"{commodity} is rising (+{change_3m:.1f}% 3M) — positive for {company}. {commodity} is {dep_desc} ({weight_pct}% revenue link) — {intensity_detail}."
            elif trend == "FALLING":
                return f"{commodity} is falling ({change_3m:.1f}% 3M) — negative for {company}. {commodity} is {dep_desc} ({weight_pct}% revenue link) — {intensity_detail}."
        return None

    template = templates.get(trend, templates.get("STABLE", ""))
    return template.format(
        change=f"{change_3m:+.1f}",
        company=company,
        dep_desc=dep_desc,
        weight_pct=weight_pct,
        intensity_detail=intensity_detail,
    )


def _build_geopolitical_narrative(stock_info, geo_data):
    """Build a narrative about geopolitical risks."""
    if not geo_data or not isinstance(geo_data, dict):
        return None

    risk_factors = geo_data.get("risk_factors", [])
    if not isinstance(risk_factors, (list, tuple)):
        risk_factors = []
    commodity = geo_data.get("commodity", "")
    risk_level = geo_data.get("risk_level", "unknown")

    if not risk_factors:
        return None

    # Filter to most relevant (non-LIVE) static factors + recent LIVE factors
    static_factors = [r for r in risk_factors if not r.startswith("[LIVE]")][:2]
    live_factors = [r.replace("[LIVE] ", "") for r in risk_factors if r.startswith("[LIVE]")][:2]

    parts = []
    if risk_level in ("high", "critical"):
        parts.append(f"Geopolitical risk for {commodity} supply chain is **{risk_level.upper()}**.")
    if static_factors:
        parts.append("Key risks: " + "; ".join(static_factors) + ".")
    if live_factors:
        parts.append("Recent developments: " + "; ".join(live_factors) + ".")

    return " ".join(parts) if parts else None


def _build_news_narrative(articles, stock_info):
    """Summarize the most impactful news themes for this stock."""
    if not articles or not isinstance(articles, (list, tuple)):
        return None

    # Filter articles to ensure they're dicts
    articles = [a for a in articles if isinstance(a, dict)]
    if not articles:
        return None

    # Count sentiment distribution
    bullish = sum(1 for a in articles if isinstance(a, dict) and a.get("sentiment") == "BULLISH")
    bearish = sum(1 for a in articles if isinstance(a, dict) and a.get("sentiment") == "BEARISH")
    total = len(articles)

    # Identify dominant themes from tags
    tag_counts = {}
    for a in articles:
        if not isinstance(a, dict):
            continue
        tags = a.get("tags")
        if not isinstance(tags, (list, tuple)):
            tags = []
        for t in tags:
            if isinstance(t, str):
                tag_counts[t] = tag_counts.get(t, 0) + 1

    top_themes = sorted(tag_counts.items(), key=lambda x: -x[1])[:4]
    theme_names = {
        "rbi": "RBI policy", "fed": "US Fed decisions", "oil": "crude oil",
        "opec": "OPEC supply", "fii": "FII flows", "inflation": "inflation",
        "gdp": "GDP/growth", "gold": "gold prices", "rupee": "rupee/forex",
        "war": "geopolitical conflict", "trade_war": "trade tensions",
        "banking": "banking sector", "it_sector": "IT sector",
        "pharma": "pharma sector", "auto": "auto sector",
        "nifty": "market indices", "earnings": "earnings results",
        "rate_cut": "interest rates", "election": "elections",
        "middle_east": "Middle East tensions",
    }

    themes_text = ", ".join(theme_names.get(t, t) for t, _ in top_themes) if top_themes else "general market"

    # Sentiment summary
    if bearish > bullish * 1.5:
        sentiment_text = f"News flow is predominantly negative ({bearish}/{total} bearish)"
        mood = "headwind"
    elif bullish > bearish * 1.5:
        sentiment_text = f"News flow is predominantly positive ({bullish}/{total} bullish)"
        mood = "tailwind"
    else:
        sentiment_text = f"Mixed news sentiment ({bullish} bullish, {bearish} bearish out of {total})"
        mood = "mixed signals"

    # Top bearish headline
    bearish_articles = [a for a in articles if isinstance(a, dict) and a.get("sentiment") == "BEARISH"]
    bullish_articles = [a for a in articles if isinstance(a, dict) and a.get("sentiment") == "BULLISH"]

    parts = [f"{sentiment_text} — dominant themes: {themes_text}."]

    # Ensure stock_info is a dict
    if not isinstance(stock_info, dict):
        stock_info = {}
    company = stock_info.get("company_name", stock_info.get("symbol", "Unknown"))
    sector = stock_info.get("sector", "")

    if mood == "headwind":
        parts.append(f"This creates a {mood} for {company}.")
    elif mood == "tailwind":
        parts.append(f"This is a {mood} for {company}.")

    # Add top 2 impactful headlines
    key_headlines = (bearish_articles[:1] + bullish_articles[:1]) if bearish_articles and bullish_articles else articles[:2]
    if key_headlines:
        hl_texts = [f'"{a.get("title", "No title")}"' for a in key_headlines[:2] if isinstance(a, dict) and a.get("title")]
        if hl_texts:
            parts.append("Key headlines: " + " | ".join(hl_texts))

    return " ".join(parts)


def _build_fundamental_narrative(symbol, fund_data):
    """Build narrative from fundamental analysis data."""
    if not fund_data or not isinstance(fund_data, dict) or not fund_data.get("rating"):
        return None

    parts = []
    rating = fund_data.get("rating", "N/A")
    pe = fund_data.get("pe")
    roe = fund_data.get("roe")
    de = fund_data.get("de")
    flags = fund_data.get("flags", [])
    concerns = fund_data.get("concerns", [])

    if rating == "STRONG":
        parts.append(f"Fundamentals are strong")
    elif rating == "MODERATE":
        parts.append(f"Fundamentals are decent")
    elif rating == "WEAK":
        parts.append(f"Fundamentals are weak")
    elif rating == "POOR":
        parts.append(f"Fundamentals are poor — high risk")

    metrics = []
    if pe:
        if pe > 50:
            metrics.append(f"PE of {pe}x is expensive")
        elif pe < 15:
            metrics.append(f"PE of {pe}x is attractive")
        else:
            metrics.append(f"PE at {pe}x")
    if roe:
        if roe > 20:
            metrics.append(f"ROE {roe}% (excellent capital efficiency)")
        elif roe < 10:
            metrics.append(f"ROE {roe}% (poor returns)")
    if de is not None and de > 1:
        metrics.append(f"D/E of {de} — leveraged balance sheet")

    if metrics:
        parts.append(" — " + ", ".join(metrics) + ".")
    else:
        parts.append(".")

    if concerns:
        parts.append("Concerns: " + "; ".join(concerns[:2]) + ".")
    if flags:
        parts.append("Positives: " + "; ".join(flags[:2]) + ".")

    return " ".join(parts)


def _build_market_narrative(ctx):
    """Build narrative from market context."""
    if not ctx or not isinstance(ctx, dict):
        return None

    market_signal = ctx.get("market_signal", "NEUTRAL")
    sector = ctx.get("sector", "UNKNOWN")
    sector_signal = ctx.get("sector_signal", "NEUTRAL")
    volatility = ctx.get("volatility_regime", "NORMAL")

    parts = []

    if market_signal == "BULLISH":
        parts.append("Broad market (Nifty 50) is in bullish territory")
    elif market_signal == "BEARISH":
        parts.append("Broad market (Nifty 50) is in bearish territory")
    else:
        parts.append("Broad market is range-bound")

    if sector != "UNKNOWN" and sector_signal != "NEUTRAL":
        direction = "outperforming" if sector_signal == "BULLISH" else "underperforming"
        parts.append(f"and {sector} sector is {direction}")

    if volatility == "HIGH":
        parts.append("— elevated volatility means wider swings and higher risk.")
    elif volatility == "LOW":
        parts.append("— low volatility suggests calm markets.")
    else:
        parts.append(".")

    return " ".join(parts)


def generate_deep_analysis(symbol):
    """
    Generate a comprehensive narrative analysis for a single stock.
    Connects global events, commodities, fundamentals, and market context
    into a human-readable "why" explanation.

    Returns dict with:
      - symbol, company_name
      - narrative: full text analysis
      - sections: dict of individual section narratives
      - key_factors: list of {factor, impact, direction} for quick display
      - risk_level: LOW/MEDIUM/HIGH
      - overall_sentiment: BULLISH/BEARISH/NEUTRAL
      - relevant_news: list of matched global news articles
      - generated_at: timestamp
    """
    symbol = symbol.upper()
    stock_info = _get_stock_info(symbol)
    # Ensure stock_info is always a dict
    if not isinstance(stock_info, dict):
        stock_info = {"symbol": symbol, "company_name": symbol, "sector": "", "commodity": None}
    company = stock_info.get("company_name", symbol)

    sections = {}
    key_factors = []
    risk_score = 0  # negative = more risk

    # ── 1. Commodity Impact ──────────────────────────────────────────────
    commodity_data = None
    try:
        from commodity_tracker import get_commodity_impact
        commodity_data = get_commodity_impact(symbol)
    except Exception:
        pass

    commodity_narrative = _build_commodity_narrative(stock_info, commodity_data)
    if commodity_narrative:
        sections["commodity"] = commodity_narrative
        if commodity_data:
            trend = commodity_data.get("trend", "STABLE")
            rel = commodity_data.get("relationship", "")
            pct = commodity_data.get("price_change_3m_pct", commodity_data.get("price_change_pct", 0))
            weight = stock_info.get("commodity_weight") or commodity_data.get("weight") or 0
            intensity, _ = _weight_label(weight)
            weight_pct = round(weight * 100)
            is_negative = (rel == "inverse" and trend == "RISING") or (rel == "direct" and trend == "FALLING")
            is_positive = (rel == "inverse" and trend == "FALLING") or (rel == "direct" and trend == "RISING")
            key_factors.append({
                "factor": f"{commodity_data.get('commodity', 'Commodity')} {trend.lower()} ({pct:+.1f}%) — {intensity} ({weight_pct}%)",
                "impact": "negative" if is_negative else "positive" if is_positive else "neutral",
                "direction": "headwind" if is_negative else "tailwind" if is_positive else "neutral",
                "weight": weight,
            })
            # Scale risk_score by weight: critical (×2), significant (×1.5), moderate (×1), minor (×0.5)
            weight_multiplier = 2.0 if weight >= 0.40 else 1.5 if weight >= 0.25 else 1.0 if weight >= 0.15 else 0.5
            if is_negative:
                risk_score -= 1 * weight_multiplier
            elif is_positive:
                risk_score += 1 * weight_multiplier

    # ── 2. Geopolitical Risk ─────────────────────────────────────────────
    geo_data = None
    try:
        from commodity_tracker import get_geopolitical_context
        geo_data = get_geopolitical_context(symbol)
    except Exception:
        pass

    geo_narrative = _build_geopolitical_narrative(stock_info, geo_data)
    if geo_narrative:
        sections["geopolitical"] = geo_narrative
        risk_level = (geo_data or {}).get("risk_level", "low")
        if risk_level in ("high", "critical"):
            risk_score -= 2
            key_factors.append({
                "factor": f"Geopolitical risk: {risk_level.upper()}",
                "impact": "negative",
                "direction": "headwind",
            })
        elif risk_level == "medium":
            risk_score -= 1
            key_factors.append({
                "factor": "Geopolitical risk: MEDIUM",
                "impact": "moderate_negative",
                "direction": "headwind",
            })

    # ── 3. Relevant Global News ──────────────────────────────────────────
    relevant_news = _get_relevant_news(symbol, stock_info, limit=15, days=7)
    news_narrative = _build_news_narrative(relevant_news, stock_info)
    if news_narrative:
        sections["news_flow"] = news_narrative
        # Count sentiment for risk scoring
        bearish = sum(1 for a in relevant_news if a.get("sentiment") == "BEARISH")
        bullish = sum(1 for a in relevant_news if a.get("sentiment") == "BULLISH")
        if bearish > bullish * 1.5 and bearish >= 3:
            risk_score -= 1
            key_factors.append({
                "factor": f"News sentiment: mostly negative ({bearish} bearish)",
                "impact": "negative",
                "direction": "headwind",
            })
        elif bullish > bearish * 1.5 and bullish >= 3:
            risk_score += 1
            key_factors.append({
                "factor": f"News sentiment: mostly positive ({bullish} bullish)",
                "impact": "positive",
                "direction": "tailwind",
            })

    # ── 4. AI Prediction + Market Context ────────────────────────────────
    try:
        import bot
        prediction = bot.get_prediction(symbol)
        if prediction and isinstance(prediction, dict):
            sources = prediction.get("sources", {})
            if isinstance(sources, dict):
                ctx = sources.get("market_context", {})
                market_narrative = _build_market_narrative(ctx)
                if market_narrative:
                    sections["market"] = market_narrative

            signal = prediction.get("signal", "HOLD")
            confidence = prediction.get("confidence", 0)
            key_factors.append({
                "factor": f"AI signal: {signal} ({confidence*100:.0f}% confidence)",
                "impact": "positive" if signal == "BUY" else "negative" if signal == "SELL" else "neutral",
                "direction": "tailwind" if signal == "BUY" else "headwind" if signal == "SELL" else "neutral",
            })
            if signal == "BUY":
                risk_score += 1
            elif signal == "SELL":
                risk_score -= 1
    except Exception as e:
        logger.warning("Prediction failed in deep analysis for %s: %s", symbol, e)

    # ── 5. Fundamentals ──────────────────────────────────────────────────
    fund_data = {}
    try:
        import fundamental_analysis as fa
        import bot as _bot
        groww = _bot._get_groww()
        fundamentals = fa.get_fundamental_analysis(groww, symbol)
        if fundamentals and isinstance(fundamentals, dict):
            financials = fundamentals.get("financials", {})
            if not isinstance(financials, dict):
                financials = {}
            fund_data = {
                "rating": fundamentals.get("fundamental_rating"),
                "pe": financials.get("pe_ratio"),
                "roe": financials.get("roe"),
                "de": financials.get("debt_to_equity"),
                "flags": fundamentals.get("positive_flags", []),
                "concerns": fundamentals.get("concerns", []),
            }
    except Exception:
        pass

    fund_narrative = _build_fundamental_narrative(symbol, fund_data)
    if fund_narrative:
        sections["fundamentals"] = fund_narrative
        rating = fund_data.get("rating", "")
        if rating == "STRONG":
            risk_score += 1
            key_factors.append({"factor": "Strong fundamentals", "impact": "positive", "direction": "tailwind"})
        elif rating in ("WEAK", "POOR"):
            risk_score -= 1
            key_factors.append({"factor": f"{rating} fundamentals", "impact": "negative", "direction": "headwind"})

    # ── 6. FII/MF Interest ───────────────────────────────────────────────
    try:
        from fii_tracker import get_shareholding_breakdown
        sh = get_shareholding_breakdown(symbol)
        if sh:
            fii = sh.get("fiis", 0)
            mf = sh.get("mfs", 0)
            if fii > 15 or mf > 10:
                key_factors.append({
                    "factor": f"Strong institutional backing (FII: {fii:.1f}%, MF: {mf:.1f}%)",
                    "impact": "positive",
                    "direction": "tailwind",
                })
                risk_score += 0.5
            elif fii < 3 and mf < 3:
                key_factors.append({
                    "factor": f"Low institutional interest (FII: {fii:.1f}%, MF: {mf:.1f}%)",
                    "impact": "negative",
                    "direction": "headwind",
                })
                risk_score -= 0.5
    except Exception:
        pass

    # ── Synthesize Full Narrative ─────────────────────────────────────────
    narrative_parts = []
    narrative_parts.append(f"**{company} ({symbol})** — Deep Analysis")
    narrative_parts.append("")

    if sections.get("commodity"):
        narrative_parts.append(f"**Commodity Impact:** {sections['commodity']}")
        narrative_parts.append("")

    if sections.get("geopolitical"):
        narrative_parts.append(f"**Geopolitical Risk:** {sections['geopolitical']}")
        narrative_parts.append("")

    if sections.get("news_flow"):
        narrative_parts.append(f"**News Flow:** {sections['news_flow']}")
        narrative_parts.append("")

    if sections.get("market"):
        narrative_parts.append(f"**Market Context:** {sections['market']}")
        narrative_parts.append("")

    if sections.get("fundamentals"):
        narrative_parts.append(f"**Fundamentals:** {sections['fundamentals']}")
        narrative_parts.append("")

    # ── Overall Assessment ────────────────────────────────────────────────
    if risk_score >= 3:
        overall = "BULLISH"
        risk_level = "LOW"
        conclusion = f"Multiple tailwinds align for {company} — favorable setup."
    elif risk_score >= 1:
        overall = "CAUTIOUSLY_BULLISH"
        risk_level = "MEDIUM"
        conclusion = f"Slightly positive outlook for {company}, but watch for headwinds."
    elif risk_score <= -3:
        overall = "BEARISH"
        risk_level = "HIGH"
        conclusion = f"Significant headwinds for {company} — risk-reward unfavorable."
    elif risk_score <= -1:
        overall = "CAUTIOUSLY_BEARISH"
        risk_level = "HIGH"
        conclusion = f"Headwinds outweigh tailwinds for {company} — exercise caution."
    else:
        overall = "NEUTRAL"
        risk_level = "MEDIUM"
        conclusion = f"Mixed signals for {company} — no clear directional edge."

    narrative_parts.append(f"**Bottom Line:** {conclusion}")

    # Summary of tailwinds/headwinds
    tailwinds = [f for f in key_factors if f["direction"] == "tailwind"]
    headwinds = [f for f in key_factors if f["direction"] == "headwind"]
    if tailwinds:
        narrative_parts.append("")
        narrative_parts.append("**Tailwinds:** " + " | ".join(f["factor"] for f in tailwinds))
    if headwinds:
        narrative_parts.append("")
        narrative_parts.append("**Headwinds:** " + " | ".join(f["factor"] for f in headwinds))

    return {
        "symbol": symbol,
        "company_name": company,
        "narrative": "\n".join(narrative_parts),
        "sections": sections,
        "key_factors": key_factors,
        "risk_level": risk_level,
        "overall_sentiment": overall,
        "risk_score": risk_score,
        "relevant_news": relevant_news[:10],
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def generate_portfolio_deep_analysis(holdings):
    """
    Generate deep analysis for all portfolio holdings.
    Also identifies cross-stock correlations and portfolio-level risks.

    Args:
        holdings: list of dicts with at minimum {"symbol": "..."}

    Returns dict with:
      - stocks: {symbol: deep_analysis_result}
      - portfolio_insights: list of cross-stock insights
      - sector_exposure: {sector: count}
      - commodity_exposure: {commodity: [symbols]}
    """
    symbols = [h["symbol"] if isinstance(h, dict) else h for h in holdings]
    results = {}

    # Run analysis for each stock (parallel threads)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(generate_deep_analysis, sym): sym for sym in symbols}
        for future in as_completed(futures, timeout=120):
            sym = futures[future]
            try:
                results[sym] = future.result()
            except Exception as e:
                logger.warning("Deep analysis failed for %s: %s", sym, e)
                results[sym] = {
                    "symbol": sym,
                    "company_name": sym,
                    "narrative": f"Analysis unavailable for {sym}.",
                    "sections": {},
                    "key_factors": [],
                    "risk_level": "UNKNOWN",
                    "overall_sentiment": "NEUTRAL",
                    "risk_score": 0,
                    "relevant_news": [],
                    "generated_at": datetime.utcnow().isoformat() + "Z",
                }

    # ── Cross-stock analysis ──────────────────────────────────────────────
    portfolio_insights = []
    sector_exposure = {}
    commodity_exposure = {}

    for sym in symbols:
        info = _get_stock_info(sym)
        # Ensure info is a dict
        if not isinstance(info, dict):
            info = {"symbol": sym, "sector": "", "commodity": None}
        sector = (info.get("sector") or "OTHER").upper()
        sector_exposure[sector] = sector_exposure.get(sector, 0) + 1

        commodity = info.get("commodity")
        if commodity:
            if commodity not in commodity_exposure:
                commodity_exposure[commodity] = []
            commodity_exposure[commodity].append(sym)

    # Sector concentration warnings
    for sector, count in sector_exposure.items():
        if count >= 3:
            portfolio_insights.append({
                "type": "concentration",
                "severity": "warning",
                "message": f"High {sector} sector concentration — {count} stocks. A sector downturn impacts {count}/{len(symbols)} of your portfolio.",
            })
        elif count >= 2:
            portfolio_insights.append({
                "type": "concentration",
                "severity": "info",
                "message": f"{count} stocks in {sector} sector — moderate overlap.",
            })

    # Commodity exposure correlation
    for commodity, syms in commodity_exposure.items():
        if len(syms) >= 2:
            portfolio_insights.append({
                "type": "commodity_correlation",
                "severity": "info",
                "message": f"{', '.join(syms)} are all linked to {commodity} — correlated risk.",
            })

    # Count overall portfolio risk
    total_risk = sum(r.get("risk_score", 0) for r in results.values() if isinstance(r, dict))
    bearish_count = sum(1 for r in results.values() if isinstance(r, dict) and (r.get("overall_sentiment", "").startswith("BEAR") or r.get("overall_sentiment") == "CAUTIOUSLY_BEARISH"))
    if len(symbols) > 0 and bearish_count > len(symbols) / 2:
        portfolio_insights.append({
            "type": "macro_risk",
            "severity": "danger",
            "message": f"Majority of your holdings ({bearish_count}/{len(symbols)}) face headwinds — consider defensive positioning.",
        })

    return {
        "stocks": results,
        "portfolio_insights": portfolio_insights,
        "sector_exposure": sector_exposure,
        "commodity_exposure": {k: v for k, v in commodity_exposure.items()},
        "total_risk_score": total_risk,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
