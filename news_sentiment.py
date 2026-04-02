"""
News Sentiment Engine — fetches financial news from multiple free sources
and scores sentiment for trading signals.

Sources:
  1. Google News RSS (always free, no API key)
  2. NewsAPI.org (optional, if key provided — 100 free req/day)
  3. RSS feeds from Economic Times, MoneyControl, LiveMint

Sentiment scoring: keyword-based financial NLP + TextBlob fallback.
"""

import re
import time
import logging
import urllib.parse
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional

import requests
import feedparser
from textblob import TextBlob

from config import NEWS_API_KEY

logger = logging.getLogger(__name__)

# ── DB helpers for article persistence ───────────────────────────────────────
import hashlib

def _title_hash(title: str) -> str:
    """Consistent hash for dedup."""
    key = re.sub(r'\W+', ' ', title.lower().strip())[:80]
    return hashlib.md5(key.encode()).hexdigest()

def _get_news_db_session():
    """Get a DB session for news article persistence."""
    try:
        from config import DB_URL
        from db_manager import get_db
        return get_db(DB_URL).Session()
    except Exception:
        return None

def _persist_articles(symbol: str, articles: list):
    """Store new articles into DB. Skip duplicates by title_hash."""
    session = _get_news_db_session()
    if not session:
        return
    try:
        from db_manager import NewsArticle
        added = 0
        for a in articles:
            th = _title_hash(a.title)
            exists = session.query(NewsArticle.id).filter_by(
                symbol=symbol, title_hash=th
            ).first()
            if exists:
                continue
            dt = _parse_published_date(a.published)
            session.add(NewsArticle(
                symbol=symbol,
                title_hash=th,
                title=a.title,
                source=a.source,
                url=a.url,
                published=a.published,
                published_at=dt.replace(tzinfo=None) if dt and dt.tzinfo else dt,
                sentiment_score=a.sentiment_score,
                sentiment=a.sentiment,
            ))
            added += 1
        if added:
            session.commit()
            logger.debug("Persisted %d new articles for %s", added, symbol)
    except Exception as e:
        session.rollback()
        logger.warning("Failed to persist articles for %s: %s", symbol, e)
    finally:
        session.close()

def _load_db_articles(symbol: str, max_days: int = 7) -> list:
    """Load recent articles from DB for this symbol."""
    session = _get_news_db_session()
    if not session:
        return []
    try:
        from db_manager import NewsArticle
        cutoff = datetime.utcnow() - timedelta(days=max_days)
        rows = session.query(NewsArticle).filter(
            NewsArticle.symbol == symbol,
            NewsArticle.published_at >= cutoff,
        ).order_by(NewsArticle.published_at.desc()).all()
        items = []
        for r in rows:
            items.append(NewsItem(
                title=r.title,
                source=r.source or "",
                url=r.url or "",
                published=r.published,
                sentiment_score=r.sentiment_score or 0,
                sentiment=r.sentiment or "NEUTRAL",
            ))
        return items
    except Exception as e:
        logger.warning("Failed to load DB articles for %s: %s", symbol, e)
        return []
    finally:
        session.close()

def _known_title_hashes(symbol: str) -> set:
    """Get set of title hashes already in DB for this symbol."""
    session = _get_news_db_session()
    if not session:
        return set()
    try:
        from db_manager import NewsArticle
        rows = session.query(NewsArticle.title_hash).filter_by(symbol=symbol).all()
        return {r[0] for r in rows}
    except Exception:
        return set()
    finally:
        session.close()

# ── NewsAPI circuit breaker ──────────────────────────────────────────────────
_newsapi_fail_count = 0
_newsapi_disabled_until = 0.0
_NEWSAPI_FAIL_LIMIT = 3        # disable after this many consecutive 429s
_NEWSAPI_COOLDOWN = 3600       # re-enable after 1 hour


def _parse_feed(url: str, timeout: int = 10):
    """Parse RSS feed with a request timeout to avoid hangs."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return feedparser.parse(resp.content)
    except Exception:
        return feedparser.FeedParserDict(entries=[])

# ── Financial sentiment lexicon ──────────────────────────────────────────────
# Tuned for Indian equity markets — words weighted by impact

BULLISH_WORDS = {
    # Strong positive
    "upgrade": 3, "outperform": 3, "breakout": 3, "rally": 3, "surge": 3,
    "record high": 4, "all-time high": 4, "strong buy": 4, "beat estimates": 3,
    "beat expectations": 3, "above estimate": 3, "profit jumps": 3, "dividend": 2,
    "buyback": 3, "bonus": 2, "stock split": 2, "acquisition": 2,
    # Moderate positive
    "buy": 2, "bullish": 2, "uptrend": 2, "growth": 2, "positive": 2,
    "gains": 2, "higher": 1, "rises": 1, "climbs": 1, "up": 1, "jumps": 2,
    "soars": 2, "profit": 2, "revenue growth": 2, "beat": 2, "recovery": 2,
    "expand": 1, "boost": 2, "strong results": 3, "order win": 2, "deal": 1,
    "partnership": 1, "fii buying": 3, "dii buying": 2, "green": 1,
    # Indian market specific
    "nifty up": 2, "sensex gains": 2, "rbi rate cut": 3, "reform": 2,
    "fpi inflow": 3, "rupee strengthens": 2, "gdp growth": 2,
}

BEARISH_WORDS = {
    # Strong negative
    "downgrade": 3, "underperform": 3, "crash": 4, "plunge": 3, "slump": 3,
    "sell": 2, "tank": 3, "miss estimates": 3, "below estimate": 3,
    "profit warning": 4, "fraud": 5, "scam": 5, "default": 4, "bankruptcy": 5,
    "debt concern": 3, "npa": 3, "write-off": 3,
    # Moderate negative
    "bearish": 2, "downtrend": 2, "decline": 2, "negative": 2, "falls": 2,
    "drops": 2, "lower": 1, "loss": 2, "weak": 2, "concern": 1, "risk": 1,
    "volatility": 1, "uncertainty": 1, "correction": 2, "breakdown": 2,
    "selling pressure": 2, "fii selling": 3, "dii selling": 2, "red": 1,
    # Indian market specific
    "nifty down": 2, "sensex falls": 2, "rbi rate hike": 3, "inflation": 2,
    "fpi outflow": 3, "rupee weakens": 2, "slowdown": 2, "recession": 3,
}


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    published: Optional[str] = None
    summary: str = ""
    sentiment_score: float = 0.0  # -1 to +1
    sentiment: str = "NEUTRAL"    # BULLISH / BEARISH / NEUTRAL


@dataclass
class NewsSentiment:
    symbol: str
    articles: List[NewsItem] = field(default_factory=list)
    avg_score: float = 0.0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    signal: str = "NEUTRAL"  # BULLISH / BEARISH / NEUTRAL
    confidence: float = 0.0  # 0 to 1

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "avg_score": round(self.avg_score, 4),
            "signal": self.signal,
            "confidence": round(self.confidence, 4),
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "neutral_count": self.neutral_count,
            "total_articles": len(self.articles),
            "articles": [
                {
                    "title": a.title,
                    "source": a.source,
                    "sentiment": a.sentiment,
                    "score": round(a.sentiment_score, 4),
                    "url": a.url,
                    "published": a.published,
                }
                for a in self.articles[:10]  # top 10 for display
            ],
        }


# ── Sentiment scoring ────────────────────────────────────────────────────────

def _score_text(text: str) -> float:
    """Score text using enhanced NLP (FinBERT if available, else enhanced keywords + TextBlob)."""
    # Try enhanced NLP engine first (FinBERT or enhanced keyword model)
    try:
        from enhanced_nlp import score_text as enhanced_score
        nlp_score = enhanced_score(text)
        if abs(nlp_score) > 0.05:
            # Blend enhanced NLP with TextBlob for robustness
            blob_score = TextBlob(text).sentiment.polarity
            return 0.75 * nlp_score + 0.25 * blob_score
    except Exception:
        pass

    # Fallback: original keyword + TextBlob
    text_lower = text.lower()
    bull_score = 0
    bear_score = 0
    for phrase, weight in BULLISH_WORDS.items():
        if phrase in text_lower:
            bull_score += weight
    for phrase, weight in BEARISH_WORDS.items():
        if phrase in text_lower:
            bear_score += weight

    total = bull_score + bear_score
    if total > 0:
        keyword_score = (bull_score - bear_score) / total
    else:
        keyword_score = 0

    blob_score = TextBlob(text).sentiment.polarity
    if total > 0:
        return 0.7 * keyword_score + 0.3 * blob_score
    else:
        return blob_score


def _classify_sentiment(score: float) -> str:
    if score > 0.15:
        return "BULLISH"
    elif score < -0.15:
        return "BEARISH"
    return "NEUTRAL"


def _parse_published_date(date_str: str) -> Optional[datetime]:
    """Try to parse a published date string into a datetime."""
    if not date_str:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%a, %d %b %Y %H:%M:%S GM",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    # Last resort: try dateutil if available
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    return None


def _is_recent(date_str: str, max_days: int = 7) -> bool:
    """Check if a published date is within max_days of today."""
    dt = _parse_published_date(date_str)
    if dt is None:
        return True  # if we can't parse the date, keep it (benefit of doubt)
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return (now - dt).days <= max_days


# ── News fetchers ────────────────────────────────────────────────────────────

_cache = {}  # symbol -> (timestamp, NewsSentiment)
CACHE_TTL = 600  # 10 minutes


def _fetch_google_news(query: str, limit: int = 10) -> List[NewsItem]:
    """Fetch from Google News RSS (no API key needed)."""
    items = []
    try:
        encoded = urllib.parse.quote(query + " when:7d")
        url = f"https://news.google.com/rss/search?q={encoded}+stock+market&hl=en-IN&gl=IN&ceid=IN:en"
        feed = _parse_feed(url)
        for entry in feed.entries[:limit * 2]:  # fetch extra, filter below
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            combined = f"{title} {summary}"
            score = _score_text(combined)
            pub = entry.get("published", "")
            if not _is_recent(pub, max_days=7):
                continue
            items.append(NewsItem(
                title=title,
                source=entry.get("source", {}).get("title", "Google News"),
                url=entry.get("link", ""),
                published=pub,
                summary=summary[:200],
                sentiment_score=score,
                sentiment=_classify_sentiment(score),
            ))
            if len(items) >= limit:
                break
    except Exception as e:
        logger.warning("Google News fetch failed: %s", e)
    return items


def _fetch_newsapi(query: str, limit: int = 10) -> List[NewsItem]:
    """Fetch from NewsAPI.org (needs free API key). Auto-disables on rate limit."""
    global _newsapi_fail_count, _newsapi_disabled_until
    if not NEWS_API_KEY:
        return []
    # Circuit breaker: skip if disabled due to repeated 429s
    if _newsapi_disabled_until > time.time():
        return []
    items = []
    try:
        url = "https://newsapi.org/v2/everything"
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "from": from_date,
            "pageSize": limit,
            "apiKey": NEWS_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 429:
            _newsapi_fail_count += 1
            if _newsapi_fail_count >= _NEWSAPI_FAIL_LIMIT:
                _newsapi_disabled_until = time.time() + _NEWSAPI_COOLDOWN
                logger.warning("NewsAPI rate-limited %d times — disabled for 1 hour", _newsapi_fail_count)
                _newsapi_fail_count = 0
            return []
        resp.raise_for_status()
        _newsapi_fail_count = 0  # reset on success
        data = resp.json()
        for article in data.get("articles", []):
            title = article.get("title", "")
            desc = article.get("description", "") or ""
            combined = f"{title} {desc}"
            score = _score_text(combined)
            items.append(NewsItem(
                title=title,
                source=article.get("source", {}).get("name", "NewsAPI"),
                url=article.get("url", ""),
                published=article.get("publishedAt", ""),
                summary=desc[:200],
                sentiment_score=score,
                sentiment=_classify_sentiment(score),
            ))
    except Exception as e:
        logger.warning("NewsAPI fetch failed: %s", e)
    return items


def _fetch_et_rss(symbol: str, limit: int = 5) -> List[NewsItem]:
    """Fetch from Economic Times RSS."""
    items = []
    try:
        url = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
        feed = _parse_feed(url)
        sym_lower = symbol.lower()
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if sym_lower in title.lower() or sym_lower in summary.lower():
                pub = entry.get("published", "")
                if not _is_recent(pub, max_days=7):
                    continue
                combined = f"{title} {summary}"
                score = _score_text(combined)
                items.append(NewsItem(
                    title=title,
                    source="Economic Times",
                    url=entry.get("link", ""),
                    published=pub,
                    summary=summary[:200],
                    sentiment_score=score,
                    sentiment=_classify_sentiment(score),
                ))
                if len(items) >= limit:
                    break
    except Exception as e:
        logger.warning("ET RSS failed: %s", e)
    return items


def _fetch_moneycontrol_rss(symbol: str, limit: int = 5) -> List[NewsItem]:
    """Fetch from MoneyControl RSS."""
    items = []
    try:
        url = "https://www.moneycontrol.com/rss/marketreports.xml"
        feed = _parse_feed(url)
        sym_lower = symbol.lower()
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            if sym_lower in title.lower() or sym_lower in summary.lower():
                pub = entry.get("published", "")
                if not _is_recent(pub, max_days=7):
                    continue
                combined = f"{title} {summary}"
                score = _score_text(combined)
                items.append(NewsItem(
                    title=title,
                    source="MoneyControl",
                    url=entry.get("link", ""),
                    published=pub,
                    summary=summary[:200],
                    sentiment_score=score,
                    sentiment=_classify_sentiment(score),
                ))
                if len(items) >= limit:
                    break
    except Exception as e:
        logger.warning("MoneyControl RSS failed: %s", e)
    return items


# ── Additional RSS feeds (LiveMint, NDTV Profit, Business Standard) ─────────

_EXTRA_RSS_FEEDS = [
    ("LiveMint", "https://www.livemint.com/rss/markets"),
    ("NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
]


def _fetch_extra_rss(symbol: str, limit: int = 5) -> List[NewsItem]:
    """Fetch from LiveMint, NDTV Profit, Business Standard RSS feeds."""
    items = []
    company = _get_symbol_names().get(symbol, symbol)
    sym_lower = symbol.lower()
    company_lower = company.lower()

    for source_name, url in _EXTRA_RSS_FEEDS:
        try:
            feed = _parse_feed(url)
            for entry in feed.entries[:40]:
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                text = f"{title} {summary}".lower()
                # Match on symbol or company name
                if sym_lower not in text and company_lower not in text:
                    continue
                pub = entry.get("published", entry.get("updated", ""))
                if not _is_recent(pub, max_days=7):
                    continue
                combined = f"{title} {summary}"
                score = _score_text(combined)
                items.append(NewsItem(
                    title=title,
                    source=source_name,
                    url=entry.get("link", ""),
                    published=pub,
                    summary=(summary or "")[:200],
                    sentiment_score=score,
                    sentiment=_classify_sentiment(score),
                ))
                if len(items) >= limit:
                    return items
        except Exception as e:
            logger.debug("%s RSS failed: %s", source_name, e)
    return items


# X.com / Twitter influential finance accounts to track
_X_FINANCE_ACCOUNTS = [
    "ABORANA75",       # Ajay Bagga, market analyst
    "aborana75",
    "zeaborana75rodha", 
]

def _fetch_x_posts(symbol: str, limit: int = 8) -> List[NewsItem]:
    """
    Fetch X.com (Twitter) posts about a stock via Google News RSS.
    Searches Google News for tweets/X posts mentioning the stock.
    This catches viral X posts that get indexed by news aggregators.
    """
    items = []
    try:
        company = _get_symbol_names().get(symbol, symbol)
        # Search Google News for X.com/Twitter mentions of the stock
        queries = [
            f'"{ company}" OR "{symbol}" site:x.com stock when:3d',
            f'"{symbol}" NSE twitter analysis investment when:3d',
        ]
        
        # Add geopolitical/commodity context queries for stocks with commodity dependencies
        try:
            from commodity_tracker import get_geopolitical_context
            geo = get_geopolitical_context(symbol)
            if geo and geo.get("x_search_terms"):
                for xq in geo["x_search_terms"][:2]:
                    queries.append(f'{xq} site:x.com when:3d')
        except Exception:
            pass
        
        seen = set()
        for query in queries:
            encoded = urllib.parse.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = _parse_feed(url)
            for entry in feed.entries[:limit]:
                title = entry.get("title", "")
                key = title.lower().strip()[:40]
                if key in seen:
                    continue
                seen.add(key)
                summary = entry.get("summary", "")
                combined = f"{title} {summary}"
                score = _score_text(combined)
                source_name = entry.get("source", {}).get("title", "X / Twitter")
                # Tag it as X source if it's from x.com or twitter  
                link = entry.get("link", "")
                if "x.com" in link or "twitter.com" in link:
                    source_name = "X (Twitter)"
                pub = entry.get("published", "")
                if not _is_recent(pub, max_days=3):
                    continue
                items.append(NewsItem(
                    title=title,
                    source=source_name,
                    url=link,
                    published=pub,
                    summary=summary[:200],
                    sentiment_score=score,
                    sentiment=_classify_sentiment(score),
                ))
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
    except Exception as e:
        logger.warning("X/Twitter fetch failed for %s: %s", symbol, e)
    return items


def _fetch_market_general_news(limit: int = 10) -> List[NewsItem]:
    """Fetch general Indian market news for overall sentiment."""
    items = []
    try:
        encoded = urllib.parse.quote("nifty sensex indian stock market when:3d")
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
        feed = _parse_feed(url)
        for entry in feed.entries[:limit * 2]:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            combined = f"{title} {summary}"
            score = _score_text(combined)
            pub = entry.get("published", "")
            if not _is_recent(pub, max_days=3):
                continue
            items.append(NewsItem(
                title=title,
                source=entry.get("source", {}).get("title", "Google News"),
                url=entry.get("link", ""),
                published=pub,
                summary=summary[:200],
                sentiment_score=score,
                sentiment=_classify_sentiment(score),
            ))
            if len(items) >= limit:
                break
    except Exception as e:
        logger.warning("Market news fetch failed: %s", e)
    return items


# ── Main API ─────────────────────────────────────────────────────────────────

# Company name mapping for better news search (DB-backed with fallback)
_FALLBACK_SYMBOL_NAMES = {
    "RELIANCE": "Reliance Industries",
    "TCS": "TCS Tata Consultancy",
    "INFY": "Infosys",
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "WIPRO": "Wipro",
    "BHARTIARTL": "Bharti Airtel",
    "ITC": "ITC Limited",
    "SBIN": "SBI State Bank India",
    "LT": "Larsen Toubro L&T",
    "BAJFINANCE": "Bajaj Finance",
    "KOTAKBANK": "Kotak Mahindra Bank",
    "HINDUNILVR": "Hindustan Unilever HUL",
    "AXISBANK": "Axis Bank",
    "MARUTI": "Maruti Suzuki",
    "TATAMOTORS": "Tata Motors",
    "TATASTEEL": "Tata Steel",
    "SUNPHARMA": "Sun Pharma",
    "ASIANPAINT": "Asian Paints",
    "TECHM": "Tech Mahindra",
}

_symbol_names_cache = None


def _get_symbol_names():
    """Get symbol->company name map from DB, with fallback."""
    global _symbol_names_cache
    if _symbol_names_cache is not None:
        return _symbol_names_cache
    try:
        from db_manager import get_symbol_names
        m = get_symbol_names()
        if m:
            _symbol_names_cache = m
            return m
    except Exception:
        pass
    return _FALLBACK_SYMBOL_NAMES


def get_news_sentiment(symbol: str, force_refresh: bool = False) -> NewsSentiment:
    """
    Fetch and analyze news sentiment for a stock symbol.
    Articles are persisted in DB — only new ones are fetched from external sources.
    Results cached in memory for 10 minutes.
    """
    now = time.time()
    if not force_refresh and symbol in _cache:
        ts, cached = _cache[symbol]
        if now - ts < CACHE_TTL:
            return cached

    # 1. Load articles already stored in DB (recent 7 days)
    db_articles = _load_db_articles(symbol, max_days=7)
    known_hashes = {_title_hash(a.title) for a in db_articles}

    # 2. Fetch fresh articles from external sources
    company = _get_symbol_names().get(symbol, symbol)
    search_query = f"{company} share price NSE"

    fresh = []
    fresh.extend(_fetch_google_news(search_query, limit=10))
    fresh.extend(_fetch_newsapi(f"{company} stock", limit=10))
    fresh.extend(_fetch_et_rss(symbol, limit=5))
    fresh.extend(_fetch_moneycontrol_rss(symbol, limit=5))
    fresh.extend(_fetch_extra_rss(symbol, limit=5))
    fresh.extend(_fetch_x_posts(symbol, limit=5))

    # 3. Deduplicate fresh articles against DB + each other
    new_articles = []
    for a in fresh:
        th = _title_hash(a.title)
        if th not in known_hashes:
            known_hashes.add(th)
            new_articles.append(a)

    # 4. Persist new articles to DB
    if new_articles:
        _persist_articles(symbol, new_articles)

    # 5. Combine: DB articles (already recent) + genuinely new ones (filter to 7d)
    all_articles = list(db_articles)
    for a in new_articles:
        if _is_recent(a.published, max_days=7):
            all_articles.append(a)

    # 6. Sort by date — newest first
    def _sort_key(article):
        dt = _parse_published_date(article.published)
        if dt:
            if dt.tzinfo:
                return dt.replace(tzinfo=None)
            return dt
        return datetime.min
    all_articles.sort(key=_sort_key, reverse=True)

    # 7. Recency-weighted sentiment
    result = NewsSentiment(symbol=symbol, articles=all_articles)

    if all_articles:
        now_dt = datetime.now()
        weighted_sum = 0.0
        weight_total = 0.0
        for a in all_articles:
            dt = _parse_published_date(a.published)
            if dt:
                age_hours = max((now_dt - dt.replace(tzinfo=None)).total_seconds() / 3600, 1)
            else:
                age_hours = 72
            w = 1.0 / (age_hours ** 0.5)
            weighted_sum += a.sentiment_score * w
            weight_total += w

        result.avg_score = weighted_sum / weight_total if weight_total > 0 else 0
        result.bullish_count = sum(1 for a in all_articles if a.sentiment == "BULLISH")
        result.bearish_count = sum(1 for a in all_articles if a.sentiment == "BEARISH")
        result.neutral_count = sum(1 for a in all_articles if a.sentiment == "NEUTRAL")
        result.signal = _classify_sentiment(result.avg_score)

        if len(all_articles) >= 3:
            agreement = max(result.bullish_count, result.bearish_count, result.neutral_count) / len(all_articles)
            coverage = min(len(all_articles) / 10, 1.0)
            result.confidence = agreement * coverage * min(abs(result.avg_score) * 3, 1.0)
        else:
            result.confidence = 0.2 * abs(result.avg_score)

    _cache[symbol] = (now, result)
    return result


def get_market_sentiment() -> NewsSentiment:
    """Get overall Indian stock market sentiment."""
    now = time.time()
    cache_key = "__MARKET__"
    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return cached

    articles = _fetch_market_general_news(limit=15)
    result = NewsSentiment(symbol="MARKET")

    if articles:
        result.articles = articles
        scores = [a.sentiment_score for a in articles]
        result.avg_score = sum(scores) / len(scores)
        result.bullish_count = sum(1 for a in articles if a.sentiment == "BULLISH")
        result.bearish_count = sum(1 for a in articles if a.sentiment == "BEARISH")
        result.neutral_count = sum(1 for a in articles if a.sentiment == "NEUTRAL")
        result.signal = _classify_sentiment(result.avg_score)
        agreement = max(result.bullish_count, result.bearish_count, result.neutral_count) / len(articles)
        result.confidence = agreement * min(abs(result.avg_score) * 3, 1.0)

    _cache[cache_key] = (now, result)
    return result


def get_geopolitical_news(symbol: str, limit: int = 8) -> dict:
    """
    Fetch geopolitical news and X posts affecting a stock's commodity supply chain.
    Returns dict with news articles, X posts, risk_factors, and commodity info.
    Returns None if stock has no commodity dependency.
    """
    try:
        from commodity_tracker import get_geopolitical_context
        geo = get_geopolitical_context(symbol)
        if not geo:
            return None
    except Exception:
        return None

    cache_key = f"__GEO_{symbol}__"
    now = time.time()
    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return cached

    # Fetch news using geopolitical search terms
    geo_news = []
    seen = set()
    for query in geo.get("search_terms", [])[:4]:
        articles = _fetch_google_news(query, limit=4)
        for a in articles:
            key = re.sub(r'\W+', ' ', a.title.lower().strip())[:50]
            if key not in seen:
                seen.add(key)
                geo_news.append(a)
            if len(geo_news) >= limit:
                break
        if len(geo_news) >= limit:
            break

    # Fetch X posts with geopolitical context
    geo_x_posts = []
    seen_x = set()
    for xq in geo.get("x_search_terms", [])[:2]:
        try:
            encoded = urllib.parse.quote(f'{xq} site:x.com')
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = _parse_feed(url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                key = title.lower().strip()[:40]
                if key in seen_x:
                    continue
                seen_x.add(key)
                summary = entry.get("summary", "")
                combined = f"{title} {summary}"
                score = _score_text(combined)
                link = entry.get("link", "")
                source_name = entry.get("source", {}).get("title", "X / Twitter")
                if "x.com" in link or "twitter.com" in link:
                    source_name = "X (Twitter)"
                geo_x_posts.append(NewsItem(
                    title=title,
                    source=source_name,
                    url=link,
                    published=entry.get("published", ""),
                    summary=summary[:200],
                    sentiment_score=score,
                    sentiment=_classify_sentiment(score),
                ))
                if len(geo_x_posts) >= 6:
                    break
        except Exception:
            pass
        if len(geo_x_posts) >= 6:
            break

    result = {
        "commodity": geo["commodity"],
        "relationship": geo["relationship"],
        "risk_factors": geo.get("risk_factors", []),
        "news": [
            {
                "title": a.title,
                "source": a.source,
                "sentiment": a.sentiment,
                "score": round(a.sentiment_score, 3),
                "url": a.url,
                "published": a.published or "",
            }
            for a in geo_news[:limit]
        ],
        "x_posts": [
            {
                "title": a.title,
                "source": a.source,
                "url": a.url,
                "published": a.published or "",
            }
            for a in geo_x_posts[:6]
        ],
    }

    _cache[cache_key] = (now, result)
    return result
