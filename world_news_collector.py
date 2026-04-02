"""
World News Collector — automated collection of global macro, sector, and
market-moving news from multiple free RSS feeds.

Categories:
  - macro:        RBI, Fed, inflation, GDP, employment data
  - sector:       Banking, IT, Pharma, FMCG, Auto, Energy sector news
  - geopolitical: Wars, sanctions, trade agreements, elections
  - market:       Nifty, Sensex, FII/DII flows, IPOs, results season
  - global:       US markets, China, EU, oil, crypto, global recession

All articles stored in `global_news` table with dedup by title hash.
Runs every 15 minutes via scheduler.
"""

import hashlib
import json
import logging
import re
import time
import urllib.parse
from datetime import datetime, timedelta

import feedparser
import requests

logger = logging.getLogger(__name__)

# ── RSS Feed Sources ─────────────────────────────────────────────────────────

# Each entry: (name, url, default_category)
RSS_FEEDS = [
    # Indian financial — dedicated feeds
    ("Economic Times Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "market"),
    ("Economic Times Economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "macro"),
    ("LiveMint Markets", "https://www.livemint.com/rss/markets", "market"),
    ("LiveMint Economy", "https://www.livemint.com/rss/economy", "macro"),
    ("MoneyControl Markets", "https://www.moneycontrol.com/rss/marketreports.xml", "market"),
    ("MoneyControl Business", "https://www.moneycontrol.com/rss/business.xml", "macro"),
    ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest", "market"),
    ("Business Standard Markets", "https://www.business-standard.com/rss/markets-106.rss", "market"),
    ("Business Standard Economy", "https://www.business-standard.com/rss/economy-102.rss", "macro"),

    # Global financial
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews", "global"),
    ("Reuters World", "https://feeds.reuters.com/Reuters/worldNews", "geopolitical"),
    ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "global"),
    ("CNBC World", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362", "geopolitical"),
    ("MarketWatch Top Stories", "https://feeds.marketwatch.com/marketwatch/topstories/", "global"),
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss", "global"),
]

# Google News RSS search queries for targeted collection
GOOGLE_NEWS_QUERIES = [
    # Indian macro
    ("RBI monetary policy interest rate India", "macro", ["rbi", "interest_rate"]),
    ("India GDP growth inflation CPI WPI", "macro", ["gdp", "inflation"]),
    ("FII DII buying selling India stock market", "market", ["fii", "dii", "flows"]),
    ("India budget fiscal policy government spending", "macro", ["budget", "fiscal"]),
    ("rupee dollar exchange rate India forex", "macro", ["rupee", "forex"]),

    # Global macro
    ("Federal Reserve interest rate decision US", "macro", ["fed", "us_rates"]),
    ("US jobs report employment data nonfarm", "macro", ["us_jobs", "employment"]),
    ("China economy PMI manufacturing GDP", "global", ["china", "pmi"]),
    ("crude oil OPEC production supply", "geopolitical", ["oil", "opec"]),
    ("gold price safe haven inflation hedge", "global", ["gold", "safe_haven"]),

    # Geopolitical
    ("India China border trade relations", "geopolitical", ["india_china"]),
    ("Russia Ukraine war sanctions energy", "geopolitical", ["russia_ukraine"]),
    ("US China trade war tariffs technology", "geopolitical", ["us_china_trade"]),
    ("Middle East conflict oil supply disruption", "geopolitical", ["middle_east", "oil"]),

    # Sector-specific Indian
    ("Indian banking sector NPA loans RBI", "sector", ["banking"]),
    ("India IT sector outsourcing TCS Infosys", "sector", ["it_sector"]),
    ("India pharma sector drug approval FDA", "sector", ["pharma"]),
    ("India auto sales EV electric vehicle", "sector", ["auto"]),
    ("India real estate housing RERA", "sector", ["real_estate"]),
    ("India FMCG consumer spending rural demand", "sector", ["fmcg"]),
    ("India telecom 5G spectrum Jio Airtel", "sector", ["telecom"]),
    ("Indian IPO listing market debut", "market", ["ipo"]),
    ("Nifty Sensex market today technical analysis", "market", ["nifty", "sensex"]),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _title_hash(title: str) -> str:
    key = re.sub(r'\W+', ' ', title.lower().strip())[:80]
    return hashlib.md5(key.encode()).hexdigest()


def _parse_date(date_str: str):
    """Parse various date formats from RSS feeds."""
    if not date_str:
        return None
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%d %b %Y %H:%M:%S %z",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, TypeError):
            continue
    # feedparser's time struct
    try:
        import calendar
        ts = feedparser._parse_date(date_str)
        if ts:
            return datetime(*ts[:6])
    except Exception:
        pass
    return None


def _is_recent(date_str: str, max_days: int = 7) -> bool:
    dt = _parse_date(date_str)
    if dt is None:
        return True
    return (datetime.utcnow() - dt).days <= max_days


def _score_text(text: str) -> float:
    """Quick sentiment score using the existing engine."""
    try:
        from news_sentiment import _score_text as ns_score
        return ns_score(text)
    except Exception:
        pass
    # Minimal fallback
    from textblob import TextBlob
    return TextBlob(text).sentiment.polarity


def _classify(score: float) -> str:
    if score > 0.15:
        return "BULLISH"
    elif score < -0.15:
        return "BEARISH"
    return "NEUTRAL"


def _auto_tag(title: str, category: str) -> list:
    """Auto-detect tags from title content."""
    tags = []
    t = title.lower()
    tag_keywords = {
        "rbi": ["rbi", "reserve bank"],
        "fed": ["federal reserve", "fed rate", "fomc", "powell"],
        "inflation": ["inflation", "cpi", "wpi", "price rise"],
        "gdp": ["gdp", "growth rate", "economic growth"],
        "fii": ["fii", "foreign institutional"],
        "dii": ["dii", "domestic institutional"],
        "ipo": ["ipo", "listing", "market debut"],
        "oil": ["crude oil", "brent", "opec", "petroleum"],
        "gold": ["gold price", "gold rate", "bullion"],
        "rupee": ["rupee", "inr", "dollar", "forex"],
        "rate_cut": ["rate cut", "rate hike", "repo rate"],
        "earnings": ["quarterly results", "q1 results", "q2 results", "q3 results", "q4 results", "profit", "revenue"],
        "banking": ["banking", "npa", "credit growth", "bank"],
        "it_sector": ["it sector", "outsourcing", "tech layoff"],
        "pharma": ["pharma", "drug", "fda approval"],
        "auto": ["auto sales", "ev ", "electric vehicle"],
        "nifty": ["nifty", "sensex", "market rally", "market crash"],
        "war": ["war", "conflict", "sanction", "military"],
        "trade_war": ["tariff", "trade war", "trade restriction"],
        "election": ["election", "vote", "mandate"],
    }
    for tag, kws in tag_keywords.items():
        if any(kw in t for kw in kws):
            tags.append(tag)
    return tags


# ── DB Persistence ───────────────────────────────────────────────────────────

def _get_session():
    try:
        from config import DB_URL
        from db_manager import get_db
        return get_db(DB_URL).Session()
    except Exception:
        return None


def _known_hashes() -> set:
    """Get all title hashes already stored."""
    session = _get_session()
    if not session:
        return set()
    try:
        from db_manager import GlobalNews
        rows = session.query(GlobalNews.title_hash).all()
        return {r[0] for r in rows}
    except Exception:
        return set()
    finally:
        session.close()


def _persist_articles(articles: list) -> int:
    """Store new articles. Returns count added."""
    session = _get_session()
    if not session:
        return 0
    try:
        from db_manager import GlobalNews
        added = 0
        for a in articles:
            try:
                session.add(GlobalNews(
                    title_hash=a["title_hash"],
                    title=a["title"],
                    source=a["source"],
                    url=a["url"],
                    published=a["published"],
                    published_at=a["published_at"],
                    category=a["category"],
                    tags=json.dumps(a.get("tags", [])),
                    sentiment_score=a["sentiment_score"],
                    sentiment=a["sentiment"],
                    summary=a.get("summary", ""),
                ))
                added += 1
            except Exception:
                session.rollback()
                continue
        if added:
            session.commit()
        return added
    except Exception as e:
        session.rollback()
        logger.warning("Failed to persist global news: %s", e)
        return 0
    finally:
        session.close()


# ── Feed Fetchers ────────────────────────────────────────────────────────────

def _parse_rss(url: str, timeout: int = 12) -> list:
    """Parse an RSS feed with timeout."""
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; GrowwBot/1.0)"
        })
        if resp.status_code != 200:
            return []
        return feedparser.parse(resp.text).entries
    except Exception:
        return []


def _fetch_all_rss(known: set) -> list:
    """Fetch from all configured RSS feeds."""
    articles = []
    for name, url, default_cat in RSS_FEEDS:
        try:
            entries = _parse_rss(url)
            for entry in entries[:30]:  # cap per feed
                title = entry.get("title", "").strip()
                if not title or len(title) < 15:
                    continue
                th = _title_hash(title)
                if th in known:
                    continue
                known.add(th)

                pub = entry.get("published", entry.get("updated", ""))
                if not _is_recent(pub, max_days=7):
                    continue

                summary = entry.get("summary", entry.get("description", ""))
                # Strip HTML
                summary = re.sub(r'<[^>]+>', '', summary or "")[:400]
                combined = f"{title} {summary}"
                score = _score_text(combined)
                tags = _auto_tag(title, default_cat)

                articles.append({
                    "title_hash": th,
                    "title": title[:500],
                    "source": name,
                    "url": entry.get("link", ""),
                    "published": pub,
                    "published_at": _parse_date(pub),
                    "category": default_cat,
                    "tags": tags,
                    "sentiment_score": score,
                    "sentiment": _classify(score),
                    "summary": summary[:500],
                })
        except Exception as e:
            logger.debug("RSS feed %s failed: %s", name, e)
    return articles


def _fetch_google_queries(known: set) -> list:
    """Fetch from Google News RSS search queries."""
    articles = []
    for query, category, default_tags in GOOGLE_NEWS_QUERIES:
        try:
            encoded = urllib.parse.quote(query + " when:7d")
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
            entries = _parse_rss(url)
            for entry in entries[:10]:
                title = entry.get("title", "").strip()
                if not title or len(title) < 15:
                    continue
                th = _title_hash(title)
                if th in known:
                    continue
                known.add(th)

                pub = entry.get("published", "")
                if not _is_recent(pub, max_days=7):
                    continue

                summary = entry.get("summary", "")
                summary = re.sub(r'<[^>]+>', '', summary or "")[:400]
                combined = f"{title} {summary}"
                score = _score_text(combined)
                tags = list(set(default_tags + _auto_tag(title, category)))

                articles.append({
                    "title_hash": th,
                    "title": title[:500],
                    "source": entry.get("source", {}).get("title", "Google News"),
                    "url": entry.get("link", ""),
                    "published": pub,
                    "published_at": _parse_date(pub),
                    "category": category,
                    "tags": tags,
                    "sentiment_score": score,
                    "sentiment": _classify(score),
                    "summary": summary[:500],
                })
        except Exception as e:
            logger.debug("Google query '%s' failed: %s", query[:30], e)
        # Small delay between Google queries to avoid rate limiting
        time.sleep(0.5)
    return articles


# ── Main Collector ───────────────────────────────────────────────────────────

def collect_world_news() -> dict:
    """
    Run a full collection pass. Fetches from all RSS feeds + Google News queries,
    deduplicates against DB, persists new articles.
    Returns summary dict.
    """
    start = time.time()
    known = _known_hashes()
    initial_known = len(known)

    # Fetch from both source types
    rss_articles = _fetch_all_rss(known)
    google_articles = _fetch_google_queries(known)

    all_new = rss_articles + google_articles

    # Persist
    added = _persist_articles(all_new) if all_new else 0

    elapsed = time.time() - start
    logger.info(
        "🌍 World news collected: %d new articles (%d RSS + %d Google), "
        "%d already known, %.1fs",
        added, len(rss_articles), len(google_articles), initial_known, elapsed
    )

    return {
        "new_articles": added,
        "rss_fetched": len(rss_articles),
        "google_fetched": len(google_articles),
        "total_in_db": initial_known + added,
        "elapsed_seconds": round(elapsed, 1),
    }


# ── Query Functions ──────────────────────────────────────────────────────────

def get_recent_news(category: str = None, tags: list = None,
                    limit: int = 50, days: int = 7) -> list:
    """
    Query recent global news from DB.
    Optional filters by category and/or tags.
    """
    session = _get_session()
    if not session:
        return []
    try:
        from db_manager import GlobalNews
        cutoff = datetime.utcnow() - timedelta(days=days)
        q = session.query(GlobalNews).filter(GlobalNews.published_at >= cutoff)
        if category:
            q = q.filter(GlobalNews.category == category)
        if tags:
            # Match any of the provided tags (JSON contains)
            from sqlalchemy import or_
            tag_filters = [GlobalNews.tags.contains(f'"{t}"') for t in tags]
            q = q.filter(or_(*tag_filters))
        rows = q.order_by(GlobalNews.published_at.desc()).limit(limit).all()
        return [{
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "url": r.url,
            "published_at": r.published_at.isoformat() + "Z" if r.published_at else None,
            "category": r.category,
            "tags": json.loads(r.tags) if r.tags else [],
            "sentiment_score": r.sentiment_score,
            "sentiment": r.sentiment,
            "summary": r.summary,
        } for r in rows]
    except Exception as e:
        logger.warning("Failed to query global news: %s", e)
        return []
    finally:
        session.close()


def get_news_stats() -> dict:
    """Get summary stats of collected news."""
    session = _get_session()
    if not session:
        return {}
    try:
        from db_manager import GlobalNews
        from sqlalchemy import func
        total = session.query(func.count(GlobalNews.id)).scalar() or 0
        today = session.query(func.count(GlobalNews.id)).filter(
            GlobalNews.published_at >= datetime.utcnow() - timedelta(days=1)
        ).scalar() or 0
        week = session.query(func.count(GlobalNews.id)).filter(
            GlobalNews.published_at >= datetime.utcnow() - timedelta(days=7)
        ).scalar() or 0

        # Category breakdown (last 7 days)
        cats = session.query(
            GlobalNews.category, func.count(GlobalNews.id)
        ).filter(
            GlobalNews.published_at >= datetime.utcnow() - timedelta(days=7)
        ).group_by(GlobalNews.category).all()

        # Sentiment breakdown (last 7 days)
        sents = session.query(
            GlobalNews.sentiment, func.count(GlobalNews.id)
        ).filter(
            GlobalNews.published_at >= datetime.utcnow() - timedelta(days=7)
        ).group_by(GlobalNews.sentiment).all()

        return {
            "total_articles": total,
            "last_24h": today,
            "last_7d": week,
            "categories": {c: n for c, n in cats if c},
            "sentiment": {s: n for s, n in sents if s},
        }
    except Exception as e:
        logger.warning("Failed to get news stats: %s", e)
        return {}
    finally:
        session.close()
