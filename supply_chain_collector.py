"""
Supply Chain Data Collector — background job that:
1. Fetches live commodity prices from yfinance
2. Scans news for each disruption to dynamically score severity
3. Writes everything to PostgreSQL tables
4. Runs every 15 minutes in a daemon thread

The heatmap API just reads from Postgres — no live fetches at request time.
"""

import json
import logging
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Ticker map for yfinance ──────────────────────────────────────────────────
COMMODITY_TICKERS = {
    "Crude Oil": "CL=F",
    "Iron Ore / Steel": "TIO=F",
    "Gold": "GC=F",
    "Aluminium": "ALI=F",
    "Zinc / Base Metals": "ZNC=F",
    "Coal": "MTF=F",
    "USD/INR": "USDINR=X",
}

# ── Disruption watch — auto-generated from COMMODITY_SUPPLY_CHAIN ────────────

def _build_disruption_watch():
    """
    Dynamically generate disruption watch entries from COMMODITY_SUPPLY_CHAIN
    instead of hardcoding search queries. Uses existing disruption metadata
    (region, iso_a3, description) and auto-generates relevant search queries
    from the region name, commodity, and known context.
    """
    try:
        from commodity_tracker import COMMODITY_SUPPLY_CHAIN
    except ImportError:
        logger.warning("Cannot import COMMODITY_SUPPLY_CHAIN, using empty watch")
        return {}

    watch = {}
    for commodity, chain in COMMODITY_SUPPLY_CHAIN.items():
        entries = []
        disruptions = chain.get("disruptions", [])

        for d in disruptions:
            region = d.get("region", "")
            desc = d.get("desc", "")
            iso_a3 = d.get("iso_a3", "")
            iso_n3 = d.get("iso_n3", "")
            severity = d.get("severity", "low")

            # Auto-generate search queries from region + commodity + description
            queries = _auto_queries(commodity, region, desc)

            entries.append({
                "region": region,
                "iso_a3": iso_a3,
                "iso_n3": iso_n3,
                "queries": queries,
                "base_desc": desc,
            })

        # Also generate queries for top producers with roles that imply risk
        for producer in chain.get("producers", []):
            role = producer.get("role", "")
            country = producer.get("country", "")
            if any(kw in role.lower() for kw in ["sanctioned", "disrupted", "instability", "declining"]):
                region = f"{country} Supply Risk"
                if not any(e["region"] == region for e in entries):
                    entries.append({
                        "region": region,
                        "iso_a3": producer.get("iso_a3", ""),
                        "iso_n3": producer.get("iso_n3", ""),
                        "queries": [
                            f"{country} {commodity.split('/')[0].strip()} supply disruption",
                            f"{country} {commodity.split('/')[0].strip()} sanctions",
                        ],
                        "base_desc": f"{role} — supply risk from {country}",
                    })

        if entries:
            watch[commodity] = entries

    return watch


def _auto_queries(commodity, region, desc):
    """Generate search queries from commodity name, disruption region, and description."""
    commodity_short = commodity.split("/")[0].strip().lower()
    region_clean = region.lower()

    queries = []
    # Primary: region + commodity
    queries.append(f"{region} {commodity_short}")
    # Secondary: key terms from description
    import re
    # Extract important nouns/phrases from description
    desc_words = re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*|[a-z]+\s+(?:crisis|ban|war|conflict|sanctions|protest|embargo|tariff|cuts?|shortage)', desc)
    for phrase in desc_words[:2]:
        q = f"{phrase.strip()} {commodity_short}"
        if q not in queries:
            queries.append(q)
    # Tertiary: region standalone (for major geopolitical events)
    if any(kw in region_clean for kw in ["war", "conflict", "sanctions", "protest", "ban"]):
        queries.append(region)

    return queries[:3]  # limit to 3 queries per disruption


def _get_disruption_watch():
    """Get disruption watch, with caching to avoid rebuilding every cycle."""
    global _disruption_watch_cache
    if _disruption_watch_cache is None:
        _disruption_watch_cache = _build_disruption_watch()
    return _disruption_watch_cache

_disruption_watch_cache = None


def _fetch_commodity_price(ticker):
    """Fetch 3-month weekly data for a commodity from yfinance with timeout."""
    try:
        import yfinance as yf
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(yf.download, ticker, period="3mo", interval="1wk", progress=False)
            data = future.result(timeout=15)
        if data.empty or len(data) < 4:
            return None
        close_col = data["Close"]
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]
        current = float(close_col.iloc[-1])
        price_1m = float(close_col.iloc[-4]) if len(close_col) >= 4 else current
        price_3m = float(close_col.iloc[0])
        chg_1m = ((current - price_1m) / price_1m * 100) if price_1m > 0 else 0
        chg_3m = ((current - price_3m) / price_3m * 100) if price_3m > 0 else 0
        weighted = chg_1m * 0.6 + chg_3m * 0.4
        trend = "RISING" if weighted > 5 else "FALLING" if weighted < -5 else "STABLE"
        return {
            "current_price": round(current, 2),
            "price_change_1m": round(chg_1m, 1),
            "price_change_3m": round(chg_3m, 1),
            "trend": trend,
        }
    except Exception as e:
        logger.warning("yfinance failed for %s: %s", ticker, e)
        return None


def _scan_disruption_news(queries, limit=6):
    """
    Search Google News for disruption-related headlines.
    Returns (news_count, avg_sentiment, sample_headlines_json).
    Sentiment < -0.1 = bearish/negative = disruption is active/worsening.
    """
    try:
        from news_sentiment import _parse_feed, _score_text, _is_recent
    except ImportError:
        return 0, 0, "[]"

    all_titles = []
    scores = []
    seen = set()

    for query in queries[:3]:
        try:
            encoded = urllib.parse.quote(query + " when:7d")
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = _parse_feed(url, timeout=8)
            for entry in feed.entries[:6]:
                title = entry.get("title", "")
                key = re.sub(r'\W+', ' ', title.lower().strip())[:50]
                if key in seen:
                    continue
                pub = entry.get("published", "")
                if not _is_recent(pub, max_days=7):
                    continue
                seen.add(key)
                score = _score_text(f"{title} {entry.get('summary', '')}")
                scores.append(score)
                all_titles.append({"title": title, "published": pub, "score": round(score, 3)})
                if len(all_titles) >= limit:
                    break
        except Exception:
            continue
        if len(all_titles) >= limit:
            break

    avg_sent = sum(scores) / len(scores) if scores else 0
    return len(all_titles), round(avg_sent, 3), json.dumps(all_titles[:5])


def _score_severity(news_count, avg_sentiment, price_change_1m, commodity):
    """
    Dynamically score disruption severity based on live signals.
    Returns: critical | high | medium | low
    """
    score = 0

    # News volume: more articles = bigger story
    if news_count >= 5:
        score += 3
    elif news_count >= 3:
        score += 2
    elif news_count >= 1:
        score += 1

    # Negative sentiment = disruption is active/worsening
    if avg_sentiment < -0.3:
        score += 3
    elif avg_sentiment < -0.1:
        score += 2
    elif avg_sentiment < 0:
        score += 1

    # Price movement confirms real-world impact
    abs_chg = abs(price_change_1m) if price_change_1m else 0
    if abs_chg > 10:
        score += 3
    elif abs_chg > 5:
        score += 2
    elif abs_chg > 2:
        score += 1

    if score >= 7:
        return "critical"
    elif score >= 5:
        return "high"
    elif score >= 3:
        return "medium"
    else:
        return "low"


def collect_once(db_url=None):
    """
    Single collection pass: fetch prices + scan news → write to Postgres.
    Called by the background loop AND can be triggered manually.
    """
    from config import DB_URL as default_url
    from db_manager import get_db, CommoditySnapshot, DisruptionEvent

    db = get_db(db_url or default_url)
    session = db.Session()
    now = datetime.utcnow()

    logger.info("🔄 Supply chain collector: starting pass")

    for commodity, ticker in COMMODITY_TICKERS.items():
        try:
            # 1. Fetch live price
            price_data = _fetch_commodity_price(ticker)

            # 2. Upsert commodity snapshot (track previous values for change detection)
            snap = session.query(CommoditySnapshot).filter_by(commodity=commodity).first()
            if not snap:
                snap = CommoditySnapshot(commodity=commodity, ticker=ticker)
                session.add(snap)

            price_changed = False
            if price_data:
                new_price = price_data["current_price"]
                new_trend = price_data["trend"]
                # Check if anything actually changed
                if (snap.current_price != new_price
                        or snap.trend != new_trend
                        or snap.price_change_1m != price_data["price_change_1m"]):
                    price_changed = True
                    # Store previous values before overwriting
                    if snap.current_price is not None:
                        snap.prev_price = snap.current_price
                        if snap.current_price and new_price:
                            snap.price_change_since_last = round(
                                ((new_price - snap.current_price) / snap.current_price) * 100, 2
                            )
                    if snap.trend:
                        snap.prev_trend = snap.trend
                    snap.current_price = new_price
                    snap.price_change_1m = price_data["price_change_1m"]
                    snap.price_change_3m = price_data["price_change_3m"]
                    snap.trend = new_trend
                    snap.updated_at = now
            elif snap.current_price is None:
                # First run, no price yet — still mark as updated
                snap.updated_at = now

            # 3. Scan news for each disruption watch item
            disruptions = _get_disruption_watch().get(commodity, [])
            for dw in disruptions:
                news_count, avg_sent, headlines_json = _scan_disruption_news(dw["queries"])
                price_chg = price_data["price_change_1m"] if price_data else 0
                severity = _score_severity(news_count, avg_sent, price_chg, commodity)

                # Build dynamic description from live headlines
                desc = dw["base_desc"]
                if news_count > 0:
                    try:
                        top = json.loads(headlines_json)
                        if top:
                            desc = top[0]["title"][:200]
                    except Exception:
                        pass

                evt = session.query(DisruptionEvent).filter_by(
                    commodity=commodity, region=dw["region"]
                ).first()
                if not evt:
                    evt = DisruptionEvent(commodity=commodity, region=dw["region"])
                    session.add(evt)

                evt.iso_a3 = dw["iso_a3"]
                evt.iso_n3 = dw["iso_n3"]
                # Only update timestamp when severity, description, or news actually changed
                disruption_changed = (
                    evt.severity != severity
                    or evt.description != desc
                    or evt.news_count != news_count
                )
                if evt.severity:
                    evt.prev_severity = evt.severity
                if evt.description:
                    evt.prev_description = evt.description
                evt.severity = severity
                evt.description = desc
                evt.news_count = news_count
                evt.avg_sentiment = avg_sent
                evt.sample_headlines = headlines_json
                if disruption_changed:
                    evt.updated_at = now

            session.commit()
            logger.info("  ✓ %s: price=%s, trend=%s, disruptions=%d",
                        commodity,
                        price_data["current_price"] if price_data else "N/A",
                        price_data["trend"] if price_data else "N/A",
                        len(disruptions))

        except Exception as e:
            session.rollback()
            logger.error("  ✗ %s collection failed: %s", commodity, e)

    session.close()
    logger.info("✅ Supply chain collector: pass complete")


def _collector_loop(interval_seconds=900):
    """Background loop: collect every interval_seconds (default 15 min)."""
    while True:
        try:
            collect_once()
        except Exception as e:
            logger.error("Supply chain collector error: %s", e)
        time.sleep(interval_seconds)


_collector_thread = None


def start_collector(interval_seconds=900):
    """Start the background supply chain collector daemon thread."""
    global _collector_thread
    if _collector_thread and _collector_thread.is_alive():
        logger.info("Supply chain collector already running")
        return
    _collector_thread = threading.Thread(
        target=_collector_loop,
        args=(interval_seconds,),
        daemon=True,
        name="supply-chain-collector"
    )
    _collector_thread.start()
    logger.info("🟢 Supply chain collector started (interval=%ds)", interval_seconds)
