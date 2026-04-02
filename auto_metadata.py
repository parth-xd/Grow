"""
auto_metadata.py — Automated stock metadata discovery and refresh.

Replaces ALL hardcoded stock dictionaries with live-scraped data:
  • Company names  → Screener.in <h1>
  • Sector/Industry → Screener.in peer section breadcrumbs (4-level hierarchy)
  • Peer/competitor lists → Screener.in industry pages (multi-level fallback)
  • Commodity links → Sector + about-text heuristic inference
  • F&O lot sizes → DB config (seeded from current values, editable via admin)
  • F&O cost rates → DB config
"""

import logging, re, json, time, requests
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Screener.in Broad Sector → internal sector code mapping ──────────
# This maps Screener.in's GICS-style classification to our internal codes.
# Structural mapping (rarely changes). New sectors auto-detected and stored.
_BROAD_SECTOR_TO_CODE = {
    "Financials":                      "BANKING",
    "Financial Services":               "BANKING",
    "Information Technology":          "IT",
    "Energy":                          "ENERGY",
    "Consumer Staples":                "FMCG",
    "Consumer Discretionary":          "CONSUMER",
    "Automobile and Auto Components":  "AUTO",
    "Healthcare":                      "PHARMA",
    "Materials":                       "METALS",
    "Industrials":                     "INFRA",
    "Communication Services":          "TELECOM",
    "Utilities":                       "ENERGY",
    "Real Estate":                     "REALTY",
}

# ── Commodity inference rules (sector + keyword based) ────────────────
_COMMODITY_RULES = [
    # (sector_pattern_or_keyword_in_about, commodity, ticker, relationship, weight)
    # IT → USD/INR
    {"sector": "IT",      "commodity": "USD/INR",             "ticker": "USDINR=X", "rel": "direct",  "weight": 0.20},
    # Oil & Gas / Petroleum
    {"about_kw": ["crude oil", "petroleum", "oil refin", "oil exploration", "upstream oil"],
     "commodity": "Crude Oil", "ticker": "CL=F", "rel": "direct", "weight": 0.40},
    # Airlines, Paints, Tyres → Crude Oil inverse (raw material cost)
    {"about_kw": ["paint", "coating", "decorative"],
     "commodity": "Crude Oil", "ticker": "CL=F", "rel": "inverse", "weight": 0.35},
    {"about_kw": ["airline", "aviation", "air transport"],
     "commodity": "Crude Oil", "ticker": "CL=F", "rel": "inverse", "weight": 0.40},
    {"about_kw": ["tyre", "tire", "rubber"],
     "commodity": "Crude Oil", "ticker": "CL=F", "rel": "direct", "weight": 0.30},
    {"about_kw": ["polymer", "petrochemical", "chemical"],
     "commodity": "Crude Oil", "ticker": "CL=F", "rel": "inverse", "weight": 0.25},
    # Steel / Iron
    {"about_kw": ["steel", "iron ore", "flat steel", "long steel"],
     "commodity": "Iron Ore / Steel", "ticker": "TIO=F", "rel": "direct", "weight": 0.45},
    # Aluminium
    {"about_kw": ["aluminium", "aluminum", "alumina"],
     "commodity": "Aluminium", "ticker": "ALI=F", "rel": "direct", "weight": 0.45},
    # Zinc / Base metals
    {"about_kw": ["zinc smelter", "zinc mining", "base metal mining"],
     "commodity": "Zinc / Base Metals", "ticker": "ZNC=F", "rel": "direct", "weight": 0.40},
    # Coal
    {"about_kw": ["coal mining", "coal india", "thermal coal"],
     "commodity": "Coal", "ticker": "MTF=F", "rel": "direct", "weight": 0.50},
    # Gold / Jewellery
    {"about_kw": ["gold", "jewellery", "jewelry", "ornament"],
     "commodity": "Gold", "ticker": "GC=F", "rel": "direct", "weight": 0.30},
    # Power / Energy companies using coal
    {"about_kw": ["power generation", "thermal power", "power plant"],
     "commodity": "Coal", "ticker": "MTF=F", "rel": "inverse", "weight": 0.25},
]


# ═══════════════════════════════════════════════════════════════════════
#  SCREENER.IN SCRAPING
# ═══════════════════════════════════════════════════════════════════════

def scrape_stock_info(symbol: str) -> dict:
    """
    Scrape Screener.in company page for:
      - company_name: from <h1>
      - about: company description paragraph
      - classification: [broad_sector, sector, broad_industry, industry] with hrefs
      - sector_code: mapped internal code (BANKING/IT/etc)
      - sector_display: human-readable industry name
    """
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code == 404:
            # Try standalone (non-consolidated)
            url = f"https://www.screener.in/company/{symbol}/"
            r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            logger.warning(f"Screener.in returned {r.status_code} for {symbol}")
            return {}
    except Exception as e:
        logger.error(f"Failed to fetch Screener.in for {symbol}: {e}")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    result = {"symbol": symbol}

    # Company name from <h1>
    h1 = soup.find("h1")
    if h1:
        name = h1.text.strip()
        # Remove " Ltd", " Limited" suffix for cleaner news search
        result["company_name"] = name
        result["search_name"] = re.sub(r"\s+(Ltd\.?|Limited)$", "", name, flags=re.I).strip()

    # About section
    about_div = soup.find("div", class_="about")
    if about_div:
        p = about_div.find("p")
        if p:
            result["about"] = p.text.strip()

    # Sector classification from #peers section breadcrumbs
    peer_section = soup.find("section", id="peers")
    if peer_section:
        market_links = []
        for a in peer_section.find_all("a"):
            href = a.get("href", "")
            if href.startswith("/market/"):
                market_links.append({
                    "name": a.text.strip(),
                    "href": href,
                    "title": a.get("title", ""),
                })

        if market_links:
            result["classification"] = market_links

            # Map broad sector to internal code
            broad_sector = market_links[0]["name"] if market_links else ""
            result["sector_code"] = _BROAD_SECTOR_TO_CODE.get(broad_sector, broad_sector.upper().replace(" ", "_"))

            # sector_display = most specific industry name
            result["sector_display"] = market_links[-1]["name"] if market_links else ""

            # Store all levels for reference
            levels = ["broad_sector", "sector", "broad_industry", "industry"]
            for i, ml in enumerate(market_links):
                if i < len(levels):
                    result[levels[i]] = ml["name"]
                    result[f"{levels[i]}_href"] = ml["href"]

    return result


def discover_peers(symbol: str, classification: list = None, min_peers: int = 3) -> list:
    """
    Auto-discover peers from Screener.in industry pages.
    Multi-level fallback: Industry → Broad Industry → Sector.
    Returns list of {symbol, name} dicts (max 10, sorted by relevance).
    """
    if not classification:
        # Fetch classification first
        info = scrape_stock_info(symbol)
        classification = info.get("classification", [])

    if not classification:
        return []

    # Try from most specific (industry) to least specific (sector)
    # Accumulate peers across levels, preferring more specific levels
    all_peers = []
    seen_symbols = set()

    for level_idx in range(len(classification) - 1, 0, -1):
        href = classification[level_idx]["href"]
        level_name = classification[level_idx]["name"]
        level_peers = _scrape_industry_page(href, exclude_symbol=symbol)
        for p in level_peers:
            if p["symbol"] not in seen_symbols:
                seen_symbols.add(p["symbol"])
                all_peers.append(p)
        if len(all_peers) >= min_peers:
            logger.info(f"{symbol}: Found {len(all_peers)} peers (up to {level_name} level)")
            return all_peers[:10]
        logger.debug(f"{symbol}: {len(all_peers)} peers so far, trying broader level")
        time.sleep(0.5)  # Rate limit

    # Also try to supplement from existing DB competitors
    if len(all_peers) < min_peers:
        try:
            from db_manager import get_competitors, get_stock
            existing = get_competitors(symbol)
            for esym in existing:
                if esym not in seen_symbols:
                    seen_symbols.add(esym)
                    stock = get_stock(esym)
                    all_peers.append({"symbol": esym, "name": stock.company_name if stock else esym})
        except Exception:
            pass

    return all_peers[:10]


def _scrape_industry_page(href: str, exclude_symbol: str = None) -> list:
    """Scrape a Screener.in /market/... page for company links."""
    url = f"https://www.screener.in{href}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    peers = []
    seen = set()

    for a in soup.find_all("a"):
        ahref = a.get("href", "")
        m = re.match(r"^/company/([A-Z0-9]+)/$", ahref)
        if m:
            sym = m.group(1)
            name = a.text.strip()
            if name and sym != (exclude_symbol or "").upper() and sym not in seen:
                seen.add(sym)
                peers.append({"symbol": sym, "name": name})

    return peers


def infer_commodity_links(symbol: str, about: str = "", sector_code: str = "") -> dict:
    """
    Infer commodity dependency from sector and about text.
    Returns {commodity, ticker, relationship, weight} or empty dict.
    """
    about_lower = (about or "").lower()

    # Check rules in order (first match wins, most specific rules first)
    for rule in _COMMODITY_RULES:
        if "sector" in rule and rule["sector"] == sector_code:
            return {
                "commodity": rule["commodity"],
                "ticker": rule["ticker"],
                "relationship": rule["rel"],
                "weight": rule["weight"],
            }
        if "about_kw" in rule:
            for kw in rule["about_kw"]:
                if kw in about_lower:
                    return {
                        "commodity": rule["commodity"],
                        "ticker": rule["ticker"],
                        "relationship": rule["rel"],
                        "weight": rule["weight"],
                    }

    return {}


# ═══════════════════════════════════════════════════════════════════════
#  DB UPDATE
# ═══════════════════════════════════════════════════════════════════════

def refresh_stock_metadata(symbol: str) -> dict:
    """
    Full metadata refresh for one stock:
    1. Scrape Screener.in for company info + sector
    2. Discover peers from industry pages
    3. Infer commodity links
    4. Update DB stocks table
    Returns summary dict.
    """
    result = {"symbol": symbol, "updated": False}

    # 1. Scrape company info
    info = scrape_stock_info(symbol)
    if not info or not info.get("company_name"):
        result["error"] = "Could not scrape Screener.in"
        return result

    time.sleep(1)  # Rate limit between requests

    # 2. Discover peers — merge Screener.in discoveries with existing DB peers
    classification = info.get("classification", [])
    scraped_peers = discover_peers(symbol, classification)
    scraped_symbols = [p["symbol"] for p in scraped_peers]

    # Get existing DB peers
    try:
        from db_manager import get_competitors, get_all_stocks
        existing_peers = get_competitors(symbol)
        # Get set of all tracked stock symbols for filtering
        all_tracked = {s.symbol for s in get_all_stocks()}
    except Exception:
        existing_peers = []
        all_tracked = set()

    # Build merged peer list:
    # 1. Keep existing (seed) peers that are still tracked — these are curated large-cap peers
    # 2. Add Screener.in peers that are tracked (same sector, already in our DB)
    # 3. Add remaining Screener.in peers if we still need more
    merged = []
    seen = set()

    # Priority 1: Existing DB peers (curated)
    for p in existing_peers:
        if p not in seen:
            seen.add(p)
            merged.append(p)

    # Priority 2: Screener.in peers that are already tracked in our DB
    for p in scraped_symbols:
        if p not in seen and p in all_tracked:
            seen.add(p)
            merged.append(p)

    # Priority 3: Screener.in peers not in our DB (new discoveries)
    for p in scraped_symbols:
        if p not in seen:
            seen.add(p)
            merged.append(p)

    peer_symbols = merged[:10]

    time.sleep(1)

    # 3. Infer commodity links
    commodity = infer_commodity_links(
        symbol,
        about=info.get("about", ""),
        sector_code=info.get("sector_code", ""),
    )

    # 4. Update DB
    try:
        from db_manager import get_db, Stock
        db = get_db()
        session = db.Session()
        try:
            stock = session.query(Stock).filter_by(symbol=symbol.upper()).first()
            if not stock:
                # Create new stock entry
                stock = Stock(symbol=symbol.upper(), company_name=info["company_name"])
                session.add(stock)

            # Update fields
            stock.company_name = info["company_name"]

            if info.get("sector_code"):
                stock.sector = info["sector_code"]
            if info.get("sector_display"):
                stock.sector_display = info["sector_display"]
            if peer_symbols:
                stock.set_competitors(peer_symbols)
            # Only infer commodity if stock doesn't already have one set (preserve manual overrides)
            if commodity and not stock.commodity:
                stock.commodity = commodity["commodity"]
                stock.commodity_ticker = commodity["ticker"]
                stock.commodity_relationship = commodity["relationship"]
                stock.commodity_weight = commodity["weight"]

            stock.updated_at = datetime.utcnow()
            session.commit()

            result["updated"] = True
            result["company_name"] = info["company_name"]
            result["sector"] = info.get("sector_code", "")
            result["sector_display"] = info.get("sector_display", "")
            result["peers"] = peer_symbols
            result["commodity"] = commodity.get("commodity", "")
            result["about"] = info.get("about", "")[:200]

            logger.info(
                f"✓ {symbol}: {info['company_name']} | "
                f"{info.get('sector_code','')} / {info.get('sector_display','')} | "
                f"{len(peer_symbols)} peers | "
                f"commodity={commodity.get('commodity','none')}"
            )
        except Exception as e:
            session.rollback()
            result["error"] = str(e)
            logger.error(f"DB error updating {symbol}: {e}")
        finally:
            session.close()
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Failed to update {symbol}: {e}")

    return result


def refresh_all_metadata() -> dict:
    """
    Refresh metadata for ALL tracked stocks (watchlist + DB).
    Rate-limited to ~2 seconds between stocks.
    """
    results = {"refreshed": 0, "failed": 0, "stocks": []}

    try:
        from db_manager import get_all_stocks
        stocks = get_all_stocks()
        symbols = [s.symbol for s in stocks]
    except Exception:
        # Fallback to watchlist
        from config import WATCHLIST
        symbols = WATCHLIST

    logger.info(f"Auto-metadata refresh starting for {len(symbols)} stocks...")

    for sym in symbols:
        try:
            r = refresh_stock_metadata(sym)
            results["stocks"].append(r)
            if r.get("updated"):
                results["refreshed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            logger.error(f"Error refreshing {sym}: {e}")
            results["failed"] += 1
            results["stocks"].append({"symbol": sym, "error": str(e)})

        time.sleep(2)  # Rate limit: max ~30 stocks/minute

    # Invalidate caches in other modules
    _invalidate_caches()

    logger.info(
        f"Auto-metadata refresh complete: "
        f"{results['refreshed']} updated, {results['failed']} failed"
    )
    return results


def _invalidate_caches():
    """Clear cached sector/commodity/name maps so they reload from DB next time."""
    try:
        import commodity_tracker
        commodity_tracker._commodity_map_cache = None
    except Exception:
        pass
    try:
        import market_context
        market_context._sector_map_cache = None
    except Exception:
        pass
    try:
        import news_sentiment
        news_sentiment._symbol_names_cache = None
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  F&O CONFIG → DB
# ═══════════════════════════════════════════════════════════════════════

def seed_fno_config():
    """
    Seed F&O lot sizes and cost rates into config_settings if not already there.
    Run once at startup. Values are then editable via DB.
    """
    from db_manager import get_config, set_config

    # Lot sizes (from current hardcoded values — will be updated manually when NSE changes)
    _FNO_LOTS = {
        "NIFTY":      {"lot_size": 75,   "exchange": "NSE", "type": "index", "tick": 0.05, "weekly_expiry": "THU"},
        "BANKNIFTY":  {"lot_size": 15,   "exchange": "NSE", "type": "index", "tick": 0.05, "weekly_expiry": "WED"},
        "FINNIFTY":   {"lot_size": 25,   "exchange": "NSE", "type": "index", "tick": 0.05, "weekly_expiry": "TUE"},
        "SENSEX":     {"lot_size": 10,   "exchange": "BSE", "type": "index", "tick": 0.05, "weekly_expiry": "FRI"},
        "MIDCPNIFTY": {"lot_size": 50,   "exchange": "NSE", "type": "index", "tick": 0.05, "weekly_expiry": "MON"},
        "HDFCBANK":   {"lot_size": 550,  "exchange": "NSE", "type": "stock", "tick": 0.05, "weekly_expiry": None},
    }

    _MCX_LOTS = {
        "CRUDEOILM":  {"lot_size": 10,   "unit": "barrels", "exchange": "MCX", "tick": 1.0,  "underlying": "CRUDEOIL"},
        "NATURALGAS": {"lot_size": 1250, "unit": "MMBtu",   "exchange": "MCX", "tick": 0.10, "underlying": "NATURALGAS"},
        "NATGASMINI": {"lot_size": 250,  "unit": "MMBtu",   "exchange": "MCX", "tick": 0.10, "underlying": "NATURALGAS"},
        "GOLDM":      {"lot_size": 100,  "unit": "grams",   "exchange": "MCX", "tick": 1.0,  "underlying": "GOLD"},
        "SILVERM":    {"lot_size": 5,    "unit": "kg",       "exchange": "MCX", "tick": 1.0,  "underlying": "SILVER"},
    }

    # Seed lot sizes
    for sym, data in _FNO_LOTS.items():
        key = f"fno.lot.{sym}"
        if get_config(key) is None:
            set_config(key, json.dumps(data), f"F&O lot config for {sym}")

    for sym, data in _MCX_LOTS.items():
        key = f"mcx.lot.{sym}"
        if get_config(key) is None:
            set_config(key, json.dumps(data), f"MCX lot config for {sym}")

    # Seed F&O cost rates
    _FNO_COSTS = {
        "fno.stt.option_sell_pct":  ("0.0625",  "STT on option sell-side (%)"),
        "fno.stt.futures_sell_pct": ("0.0125",  "STT on futures sell-side (%)"),
        "fno.exchange.nse_pct":     ("0.0495",  "NSE exchange txn charge (%)"),
        "fno.exchange.bse_pct":     ("0.0325",  "BSE exchange txn charge (%)"),
        "fno.exchange.mcx_pct":     ("0.0260",  "MCX exchange txn charge (%)"),
        "fno.sebi_pct":             ("0.0001",  "SEBI turnover fee (%)"),
        "fno.gst_pct":              ("18.0",    "GST on brokerage+charges (%)"),
        "fno.stamp_duty_pct":       ("0.003",   "Stamp duty on buy-side (%)"),
        "fno.brokerage_per_order":  ("20.0",    "Brokerage per order (₹)"),
        "fno.brokerage_pct_cap":    ("0.05",    "Max brokerage as % of premium"),
    }

    for key, (val, desc) in _FNO_COSTS.items():
        if get_config(key) is None:
            set_config(key, val, desc)

    logger.info("✓ F&O config seeded in DB")


def get_fno_lot_config(instrument: str) -> dict:
    """Get F&O lot size config from DB, falling back to hardcoded."""
    from db_manager import get_config
    # Try NSE F&O first, then MCX
    for prefix in ("fno.lot.", "mcx.lot."):
        val = get_config(f"{prefix}{instrument}")
        if val:
            try:
                return json.loads(val)
            except Exception:
                pass
    return None


def get_fno_cost_rate(key: str, default: float = 0) -> float:
    """Get an F&O cost rate from DB config."""
    from db_manager import get_config
    val = get_config(f"fno.{key}" if not key.startswith("fno.") else key)
    if val is not None:
        try:
            return float(val)
        except Exception:
            pass
    return default
