"""
Tijori Finance Collector — automated supply-chain & fundamentals intelligence.

For every stock we track, this module scrapes Tijori Finance company pages and
persists, in a structured way:

  - suppliers / customers / competitors  → company_connections table
  - key ratios, peer table, price returns, forensic checks (quick_look),
    market share, corporate actions       → company_external_data snapshots

Design principles
  - NOTHING hardcoded: base URL, delays, intervals, max requests all come from
    the config_settings table (with sane defaults seeded on first run).
  - Every parser is independent: if Tijori changes one section, the others
    still work. A failed scrape NEVER deletes previously stored data.
  - Snapshots are append-only, so we can always compare "now vs last time"
    and analyse changes (ratio drift, new suppliers, forensic flag flips...).
  - Slug resolution is derived from company names in our own stocks table,
    verified against the NSE symbol embedded in the fetched page, and cached
    in external_slug_map so we only resolve each company once.
"""

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SOURCE = "tijori"

# ── Config (all overridable via config_settings table) ───────────────────────

_CONFIG_DEFAULTS = {
    "tijori.enabled": ("true", "Enable Tijori supply-chain/fundamentals collection"),
    "tijori.base_url": ("https://www.tijorifinance.com", "Tijori base URL"),
    "tijori.request_delay_seconds": ("2", "Delay between Tijori requests (politeness)"),
    "tijori.timeout_seconds": ("15", "HTTP timeout for Tijori requests"),
    "tijori.refresh_interval_days": ("7", "How often to refresh each symbol's Tijori data"),
    "tijori.max_symbols_per_run": ("10", "Max symbols refreshed per scheduler run"),
    "tijori.max_slug_resolutions_per_run": ("15", "Max connection-name→symbol resolutions per run"),
    "tijori.block_below_coverage_pct": ("95", "Lock analysis sections while coverage below this % AND collection is active"),
    "tijori.local_index_ttl_seconds": ("3600", "How long to cache the local company-name→NSE-symbol index"),
    "tijori.max_partner_snapshots_per_run": ("12", "Partner company pages fetched per scheduler run (fills missing supplier/customer data)"),
    "tijori.partner_retry_days": ("14", "Wait this long before retrying a partner whose page yielded no data"),
    "tijori.onboard_partner_limit": ("20", "Partner pages fetched immediately when a new stock is added"),
    "tijori.user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "User agent for Tijori requests",
    ),
}


def _cfg(key, default=None):
    """Read a config value from DB with fallback to seeded defaults."""
    try:
        from db_manager import get_config
        val = get_config(key)
        if val is not None:
            return val
    except Exception:
        pass
    if key in _CONFIG_DEFAULTS:
        return _CONFIG_DEFAULTS[key][0]
    return default


def seed_tijori_config():
    """Seed default Tijori config into config_settings (no-op if present)."""
    try:
        from db_manager import get_config, set_config
        for key, (val, desc) in _CONFIG_DEFAULTS.items():
            if get_config(key) is None:
                set_config(key, val, desc)
    except Exception as e:
        logger.debug("Tijori config seed skipped: %s", e)


def _enabled():
    return str(_cfg("tijori.enabled", "true")).lower() == "true"


# Rate limiting is enforced against the time of the last ACTUAL request rather
# than by unconditional sleeps. Unconditional sleeps double-count when calls
# nest (resolve_slug sleeps per slug candidate, and its callers sleep again per
# name), and they also pay the full delay even when the request itself already
# took longer than the delay. This guarantees the same minimum spacing between
# outbound requests while removing the wasted waiting.
_last_request_at = 0.0
_rate_lock = threading.Lock()


def _request_delay():
    try:
        return float(_cfg("tijori.request_delay_seconds", 2))
    except Exception:
        return 2.0


def _sleep_politely():
    """Wait only as long as is still needed before the next request is allowed."""
    delay = _request_delay()
    with _rate_lock:
        wait = delay - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(min(wait, delay))   # clamp: a cold start must not over-wait


def _http_get(url):
    headers = {"User-Agent": _cfg("tijori.user_agent")}
    timeout = float(_cfg("tijori.timeout_seconds", 15))
    # Honour spacing here too, so every request is covered even on paths that
    # don't call _sleep_politely explicitly.
    _sleep_politely()
    global _last_request_at
    try:
        return requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    finally:
        with _rate_lock:
            _last_request_at = time.monotonic()


# ── Slug resolution ──────────────────────────────────────────────────────────

def _slugify(name):
    """company name → url slug candidate: 'Larsen & Toubro' → 'larsen-toubro'."""
    s = (name or "").lower().strip()
    s = s.replace("&", " ").replace("'", "").replace(".", " ").replace(",", " ")
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.replace(" ", "-")


def _slug_candidates(company_name):
    """Generate slug guesses in priority order — derived, never hardcoded."""
    base = _slugify(company_name)
    # strip common suffixes to get clean root
    root = re.sub(r"-(ltd|limited|india)$", "", base)
    candidates = []
    for c in [
        f"{root}-limited",
        base,
        f"{base}-limited",
        f"{root}-ltd",
        f"{root}-india-limited",
        root,
    ]:
        if c and c not in candidates:
            candidates.append(c)
    return candidates


def _extract_company_details(soup):
    """Pull the embedded company_details_data JSON (contains NSE symbol)."""
    el = soup.find("script", id="company_details_data")
    if el and el.string:
        try:
            return json.loads(el.string)
        except Exception:
            return None
    return None


def resolve_slug(company_name, expected_symbol=None, db=None):
    """
    Resolve a company name → verified Tijori slug (cached in external_slug_map).

    Returns dict {slug, symbol, external_id, status} — status one of
    "resolved" / "failed". Uses cache first; on miss, tries slug candidates and
    verifies via the NSE symbol embedded in the page.
    """
    from db_manager import get_db, ExternalSlugMap

    db = db or get_db()
    name_key = (company_name or "").strip()
    if not name_key:
        return {"slug": None, "symbol": None, "status": "failed"}

    # 1) cache lookup
    try:
        with db.Session() as session:
            row = session.query(ExternalSlugMap).filter_by(source=SOURCE, company_name=name_key).first()
            if row and row.resolution_status == "resolved" and row.slug:
                return {"slug": row.slug, "symbol": row.symbol,
                        "external_id": row.external_id, "status": "resolved"}

            # Before honouring a cached failure, look the symbol up as well.
            # The cache is keyed on company_name, but the same company reaches
            # this table under different names depending on the path that
            # discovered it: stocks.company_name for the principal collection,
            # and Tijori's own spelling when it turns up in another company's
            # partner list. ONGC is exactly that case — row 90 caches a
            # failure for "Oil & Natural Gas Corpn Ltd" (our DB's name) while
            # row 335 holds a *resolved* slug for the same symbol under "Oil &
            # Natural Gas Corporation Ltd." (Tijori's name). Keyed only on
            # name, the principal path can never see the slug it already has,
            # so ONGC stayed "uncollected" while holding all 7 snapshot types.
            if expected_symbol:
                by_symbol = session.query(ExternalSlugMap).filter_by(
                    source=SOURCE, symbol=expected_symbol, resolution_status="resolved"
                ).first()
                if by_symbol and by_symbol.slug:
                    logger.info(
                        "tijori: resolved %s via symbol cache (name %r had no match; "
                        "cached under %r)", expected_symbol, name_key, by_symbol.company_name
                    )
                    return {"slug": by_symbol.slug, "symbol": by_symbol.symbol,
                            "external_id": by_symbol.external_id, "status": "resolved"}

            if row and row.resolution_status == "failed":
                # don't retry failures more than once a month
                if row.updated_at and (datetime.utcnow() - row.updated_at) < timedelta(days=30):
                    return {"slug": None, "symbol": row.symbol, "status": "failed"}
    except Exception as e:
        logger.debug("slug cache lookup failed: %s", e)

    # 2) try candidates
    base_url = _cfg("tijori.base_url")
    resolved = None
    for cand in _slug_candidates(name_key):
        url = f"{base_url}/company/{cand}/"
        try:
            r = _http_get(url)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                details = _extract_company_details(soup)
                if details:
                    page_symbol = (details.get("symbol") or "").upper() or None
                    # verify if we were given an expected symbol
                    if expected_symbol and page_symbol and page_symbol != expected_symbol.upper():
                        logger.debug("slug %s verified but symbol mismatch (%s != %s)",
                                     cand, page_symbol, expected_symbol)
                        continue
                    resolved = {
                        "slug": cand,
                        "symbol": page_symbol,
                        "external_id": str(details.get("company_id") or ""),
                        "status": "resolved",
                        "_html": r.text,   # pass along so caller can avoid re-fetching
                    }
                    break
        except Exception as e:
            logger.debug("slug candidate %s error: %s", cand, e)
        _sleep_politely()

    # 3) persist result to cache
    try:
        with db.Session() as session:
            row = session.query(ExternalSlugMap).filter_by(source=SOURCE, company_name=name_key).first()
            if not row:
                row = ExternalSlugMap(source=SOURCE, company_name=name_key)
                session.add(row)
            if resolved:
                row.slug = resolved["slug"]
                row.symbol = resolved["symbol"]
                row.external_id = resolved.get("external_id")
                row.resolution_status = "resolved"
                row.verified_at = datetime.utcnow()
            else:
                row.resolution_status = "failed"
            row.updated_at = datetime.utcnow()
            session.commit()
    except Exception as e:
        logger.debug("slug cache write failed: %s", e)

    return resolved or {"slug": None, "symbol": None, "status": "failed"}


# ── Page parsers (each independent — isolated failures) ──────────────────────

def _parse_embedded_json(soup, script_id):
    el = soup.find("script", id=script_id)
    if el and el.string:
        try:
            return json.loads(el.string)
        except Exception:
            return None
    return None


def _parse_connections_section(soup, section_id):
    """Parse a suppliers/customers section → list of {name, slug}."""
    out = []
    section = soup.find("section", id=section_id)
    if not section:
        return out
    for li in section.find_all("li", class_="collapse_list__item"):
        name = li.get_text(" ", strip=True)
        if not name:
            continue
        slug = None
        a = li.find("a", href=True)
        if a and "/company/" in a["href"]:
            m = re.search(r"/company/([^/]+)/?", a["href"])
            if m:
                slug = m.group(1)
        out.append({"name": name, "slug": slug})
    return out


def _parse_competitor_names(soup):
    """Competitors from the peers chart config or peers table."""
    peers = _parse_embedded_json(soup, "price_chart_peers") or []
    names = []
    for p in peers:
        if isinstance(p, dict) and p.get("type") == "company" and p.get("name"):
            names.append({"name": p["name"], "symbol": (p.get("symbol") or "").upper() or None})
    # first entry is usually the company itself — the caller filters it out
    return names


def parse_company_page(html):
    """
    Parse everything we care about from a Tijori company page.
    Every block is optional; missing blocks are simply omitted.
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {"parsed_at": datetime.utcnow().isoformat(), "sections_ok": [], "sections_failed": []}

    blocks = {
        "company_info": lambda: _extract_company_details(soup),
        "ratios": lambda: _parse_embedded_json(soup, "ratios_table"),
        "peers": lambda: _parse_embedded_json(soup, "peers_table_data"),
        "returns": lambda: _parse_embedded_json(soup, "price_returns"),
        "market_share": lambda: _parse_embedded_json(soup, "ms-charts"),
        "corporate_actions": lambda: _parse_embedded_json(soup, "corporate_actions"),
    }
    for key, fn in blocks.items():
        try:
            data = fn()
            if data:
                result[key] = data
                result["sections_ok"].append(key)
            else:
                result["sections_failed"].append(key)
        except Exception as e:
            logger.debug("parse block %s failed: %s", key, e)
            result["sections_failed"].append(key)

    # forensic quick-look lives inside company_info
    try:
        ql = (result.get("company_info") or {}).get("quick_look")
        if ql:
            result["forensics"] = ql
            result["sections_ok"].append("forensics")
    except Exception:
        pass

    # connections (server-rendered HTML sections)
    try:
        result["suppliers"] = _parse_connections_section(soup, "suppliers")
        result["customers"] = _parse_connections_section(soup, "customers")
        result["competitors"] = _parse_competitor_names(soup)
        result["sections_ok"] += ["suppliers", "customers", "competitors"]
    except Exception as e:
        logger.debug("connections parse failed: %s", e)
        result["sections_failed"].append("connections")

    return result


# ── Persistence ──────────────────────────────────────────────────────────────

_SNAPSHOT_TYPES = ["company_info", "ratios", "peers", "returns", "forensics",
                   "market_share", "corporate_actions"]


def _store_snapshots(symbol, parsed, db):
    """Append new snapshots for each data block that parsed successfully."""
    from db_manager import CompanyExternalData
    stored = []
    with db.Session() as session:
        for dtype in _SNAPSHOT_TYPES:
            data = parsed.get(dtype)
            if not data:
                continue
            try:
                session.add(CompanyExternalData(
                    symbol=symbol, data_type=dtype, source=SOURCE,
                    payload_json=json.dumps(data, default=str),
                ))
                stored.append(dtype)
            except Exception as e:
                logger.debug("snapshot store %s/%s failed: %s", symbol, dtype, e)
        session.commit()
    return stored


def _store_connections(symbol, parsed, db):
    """
    Upsert supplier/customer/competitor relationships.
    New → insert with first_seen. Existing → bump last_seen.
    Disappeared → mark is_active=False (never delete).
    """
    from db_manager import CompanyConnection
    now = datetime.utcnow()
    counts = {"supplier": 0, "customer": 0, "competitor": 0}

    rel_map = {
        "supplier": parsed.get("suppliers") or [],
        "customer": parsed.get("customers") or [],
        "competitor": [
            {"name": c["name"], "slug": None, "symbol": c.get("symbol")}
            for c in (parsed.get("competitors") or [])
        ],
    }
    own_name = ((parsed.get("company_info") or {}).get("company") or "").strip().lower()

    with db.Session() as session:
        for rel_type, items in rel_map.items():
            seen_names = set()
            for item in items:
                name = (item.get("name") or "").strip()
                if not name or name.lower() == own_name:
                    continue
                seen_names.add(name)
                row = (session.query(CompanyConnection)
                       .filter_by(symbol=symbol, relation_type=rel_type, related_name=name)
                       .first())
                if row:
                    row.last_seen = now
                    row.is_active = True
                    if item.get("slug") and not row.related_slug:
                        row.related_slug = item["slug"]
                    if item.get("symbol") and not row.related_symbol:
                        row.related_symbol = item["symbol"]
                else:
                    session.add(CompanyConnection(
                        symbol=symbol, relation_type=rel_type, related_name=name,
                        related_slug=item.get("slug"), related_symbol=item.get("symbol"),
                        source=SOURCE, first_seen=now, last_seen=now, is_active=True,
                    ))
                counts[rel_type] += 1
            # deactivate relationships that vanished from the source
            if items:  # only if the section parsed at all (don't deactivate on parse failure)
                stale = (session.query(CompanyConnection)
                         .filter(CompanyConnection.symbol == symbol,
                                 CompanyConnection.relation_type == rel_type,
                                 CompanyConnection.source == SOURCE,
                                 CompanyConnection.is_active == True,
                                 ~CompanyConnection.related_name.in_(seen_names))
                         .all())
                for s in stale:
                    s.is_active = False
        session.commit()
    return counts


# ── Main collection API ──────────────────────────────────────────────────────

def collect_for_symbol(symbol, db=None, html=None):
    """
    Full Tijori collection for one of OUR stocks:
      resolve slug → fetch page → parse everything → store snapshots + connections.

    Returns summary dict. Never raises; never deletes old data on failure.
    """
    from db_manager import get_db, get_stock

    if not _enabled():
        return {"symbol": symbol, "skipped": "tijori disabled"}

    symbol = symbol.upper()
    db = db or get_db()
    summary = {"symbol": symbol, "ok": False}

    try:
        stock = get_stock(symbol, db)
        company_name = getattr(stock, "company_name", None) or symbol

        if html is None:
            res = resolve_slug(company_name, expected_symbol=symbol, db=db)
            if res.get("status") != "resolved":
                # fallback: try resolving by symbol as name (e.g. "ONGC")
                res = resolve_slug(symbol, expected_symbol=symbol, db=db)
            if res.get("status") != "resolved":
                summary["error"] = f"could not resolve Tijori page for {company_name}"
                # This return was silent. The symbol then simply never appears
                # in the coverage count, with no record of why — across all
                # 6.5M lines of server.log there is not one occurrence of
                # "could not resolve", so four symbols failed here every pass
                # for nine days and the only visible trace was the aggregate
                # "4 symbols processed (0 ok)". Logging the name we tried is
                # what makes the next mismatch diagnosable in seconds instead
                # of an afternoon.
                logger.warning(
                    "tijori: could not resolve page for %s (company_name=%r) — "
                    "no slug candidate matched and no resolved cache entry by symbol",
                    symbol, company_name
                )
                return summary
            summary["slug"] = res["slug"]
            html = res.pop("_html", None)
            if html is None:
                url = f"{_cfg('tijori.base_url')}/company/{res['slug']}/"
                r = _http_get(url)
                r.raise_for_status()
                html = r.text

        parsed = parse_company_page(html)
        summary["sections_ok"] = parsed.get("sections_ok", [])
        summary["sections_failed"] = parsed.get("sections_failed", [])

        summary["snapshots_stored"] = _store_snapshots(symbol, parsed, db)
        summary["connections"] = _store_connections(symbol, parsed, db)
        summary["ok"] = bool(summary["snapshots_stored"] or any(summary["connections"].values()))

        # record freshness marker
        try:
            from db_manager import set_config
            set_config(f"tijori.last_collected.{symbol}", datetime.utcnow().isoformat())
        except Exception:
            pass

        logger.info("✓ Tijori collected %s: snapshots=%s connections=%s",
                    symbol, summary["snapshots_stored"], summary["connections"])
    except Exception as e:
        logger.warning("Tijori collection failed for %s: %s", symbol, e)
        summary["error"] = str(e)

    return summary


# ── Local name → symbol resolution ───────────────────────────────────────────
# Resolving a partner company to its NSE symbol by scraping the source site is
# slow and unreliable: pages outside the free tier return HTTP 200 with a
# paywall shell, which looks like success but carries no symbol. We already
# hold the authoritative answer locally (Groww's NSE instrument master), so we
# check that first and only fall back to the network for genuine unknowns.

_COMPANY_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|pvt|private|inc|corp|corpn|corporation|co|the|india|indias)\b")


def _normalize_company_name(name):
    """Normalize a company name for cross-source matching.

    Collapses the differences that keep the same company from matching itself:
    trailing periods ('Tata Steel Ltd.' vs 'Tata Steel Ltd'), parentheticals
    ('Dixon Technologies (India) Ltd.'), '&' vs 'and', and Ltd/Limited suffixes.
    """
    n = str(name or "").lower().strip()
    n = re.sub(r"-\s*\(amalgamated\)", " ", n)
    n = re.sub(r"\(.*?\)", " ", n)              # drop "(India)", "(Amalgamated)"
    n = re.sub(r"[^a-z0-9& ]+", " ", n)         # strip punctuation incl. periods
    n = n.replace("&", " and ")
    n = _COMPANY_SUFFIX_RE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


_LOCAL_INDEX = {"map": None, "built_at": 0.0}


def _build_local_symbol_index(db=None):
    """Build {normalized company name: NSE symbol} from local sources.

    Sources are merged weakest-first so the most authoritative one wins:
      1. company_info snapshots we've already scraped
      2. previously resolved external_slug_map entries
      3. Groww's NSE CASH instrument master (authoritative)
    """
    from db_manager import get_db, ExternalSlugMap, CompanyExternalData
    db = db or get_db()
    idx = {}

    # (1) names seen in company_info payloads
    try:
        with db.Session() as session:
            for r in session.query(CompanyExternalData).filter_by(data_type="company_info").all():
                p = r.get_payload() or {}
                sym = (p.get("symbol") or "").upper()
                if not sym:
                    continue
                for key in ("company", "shortname"):
                    k = _normalize_company_name(p.get(key))
                    if k:
                        idx[k] = sym
    except Exception as e:
        logger.debug("local index: company_info pass failed: %s", e)

    # (2) anything we resolved before — this alone fixes exact-string cache misses
    try:
        with db.Session() as session:
            for m in session.query(ExternalSlugMap).filter(ExternalSlugMap.symbol.isnot(None)).all():
                k = _normalize_company_name(m.company_name)
                if k:
                    idx[k] = (m.symbol or "").upper()
    except Exception as e:
        logger.debug("local index: slug map pass failed: %s", e)

    # (3) Groww NSE cash master — authoritative, overwrites the above
    try:
        import bot
        df = bot._get_groww().get_all_instruments()
        cash = df[(df["exchange"] == "NSE") & (df["segment"] == "CASH")
                  & df["trading_symbol"].notna() & df["name"].notna()]
        groww = {}
        for nm, ts in zip(cash["name"], cash["trading_symbol"]):
            k = _normalize_company_name(nm)
            if k and k not in groww:          # first listing wins
                groww[k] = str(ts).upper()
        idx.update(groww)
        logger.info("Local symbol index: %d names from Groww NSE master", len(groww))
    except Exception as e:
        logger.info("Groww instrument master unavailable (%s) — using DB-only index", e)

    return idx


def _get_local_index(db=None, force=False):
    ttl = float(_cfg("tijori.local_index_ttl_seconds", 3600))
    now = time.time()
    if force or _LOCAL_INDEX["map"] is None or (now - _LOCAL_INDEX["built_at"]) > ttl:
        _LOCAL_INDEX["map"] = _build_local_symbol_index(db)
        _LOCAL_INDEX["built_at"] = now
        logger.info("Local symbol index built: %d entries", len(_LOCAL_INDEX["map"]))
    return _LOCAL_INDEX["map"]


def resolve_locally(name, db=None):
    """Return the NSE symbol for a company name using local data only, or None."""
    key = _normalize_company_name(name)
    if not key:
        return None
    return _get_local_index(db).get(key)


def _mark_collection_attempt(symbol, db, reason):
    """Record that we tried to collect a partner and got nothing usable.

    Stored as an ordinary append-only snapshot row with its own data_type, so
    it needs no schema change and is naturally excluded from read paths (which
    filter to the block types they consume). Without this marker a permanently
    gated company would be re-fetched on every single run.
    """
    from db_manager import CompanyExternalData
    try:
        with db.Session() as session:
            session.add(CompanyExternalData(
                symbol=symbol, data_type="collection_attempt", source=SOURCE,
                payload_json=json.dumps({"ok": False, "reason": reason,
                                         "at": datetime.utcnow().isoformat()})))
            session.commit()
    except Exception as e:
        logger.debug("could not mark collection attempt for %s: %s", symbol, e)


def _fetch_partner_html(name, slug, db):
    """Get a partner's page HTML, preferring a slug we already verified."""
    base = _cfg("tijori.base_url")
    if slug:
        try:
            r = _http_get(f"{base}/company/{slug}/")
            if r.status_code == 200:
                return r.text, slug
        except Exception as e:
            logger.debug("partner fetch via known slug failed (%s): %s", slug, e)
    res = resolve_slug(name, db=db)
    html = res.pop("_html", None)
    if html:
        return html, res.get("slug")
    if res.get("slug"):
        try:
            r = _http_get(f"{base}/company/{res['slug']}/")
            if r.status_code == 200:
                return r.text, res["slug"]
        except Exception as e:
            logger.debug("partner fetch via resolved slug failed: %s", e)
    return None, None


def collect_missing_partner_snapshots(db=None, limit=None, symbols=None):
    """Fill in performance data for partners we matched but never fetched.

    Partners resolved by local name-matching get an NSE symbol without their
    page ever being fetched, so they hold no returns/ratios/forensics. The
    name-resolution queue only covers rows where related_symbol IS NULL, so
    without this pass those partners would never be collected at all.

    `symbols` scopes the work to the partners of specific principal companies
    (used when onboarding a newly added stock).
    """
    from db_manager import get_db, CompanyConnection, CompanyExternalData

    if not _enabled():
        return {"collected": 0, "skipped": "tijori disabled"}

    db = db or get_db()
    limit = limit or int(_cfg("tijori.max_partner_snapshots_per_run", 12))
    retry_days = int(_cfg("tijori.partner_retry_days", 14))

    with db.Session() as session:
        # updated_at is selected because Postgres requires ORDER BY columns to
        # appear in the SELECT list of a DISTINCT query.
        q = (session.query(CompanyConnection.related_symbol,
                           CompanyConnection.related_name,
                           CompanyConnection.related_slug,
                           CompanyConnection.updated_at)
             .filter(CompanyConnection.is_active == True,
                     CompanyConnection.related_symbol.isnot(None)))
        if symbols:
            q = q.filter(CompanyConnection.symbol.in_(list(symbols)))
        # Oldest-touched first, so even a symbol that somehow escapes the
        # attempt-marker still yields its slot instead of blocking the queue.
        cand = {}
        for sym, name, slug, _upd in q.order_by(CompanyConnection.updated_at.asc()).distinct().all():
            if not sym:
                continue
            if sym not in cand:
                cand[sym] = (name, slug)
            elif slug and not cand[sym][1]:
                cand[sym] = (cand[sym][0], slug)   # prefer a row with a known slug
        if not cand:
            return {"collected": 0, "pending": 0, "checked": 0}

        keys = list(cand.keys())
        # Two batched lookups — never query per candidate
        done = {r[0] for r in session.query(CompanyExternalData.symbol).filter(
            CompanyExternalData.symbol.in_(keys),
            CompanyExternalData.data_type == "returns").distinct().all()}
        cutoff = datetime.utcnow() - timedelta(days=retry_days)
        recently_tried = {r[0] for r in session.query(CompanyExternalData.symbol).filter(
            CompanyExternalData.symbol.in_(keys),
            CompanyExternalData.data_type == "collection_attempt",
            CompanyExternalData.scraped_at >= cutoff).distinct().all()}

    pending = [s for s in keys if s not in done and s not in recently_tried]
    collected = 0
    for sym in pending[:limit]:
        name, slug = cand[sym]
        try:
            html, used_slug = _fetch_partner_html(name, slug, db)
            if not html:
                _mark_collection_attempt(sym, db, "page not reachable")
            else:
                parsed = parse_company_page(html)
                stored = _store_snapshots(sym, parsed, db) or []
                # `done` (above) keys off a stored "returns" row. A gated page
                # can yield ratios but no returns — without a marker such a
                # symbol would never enter `done` and would be re-fetched on
                # every run forever, blocking the queue behind it.
                if "returns" not in stored:
                    _mark_collection_attempt(
                        sym, db,
                        f"partial data only ({','.join(stored)})" if stored
                        else "page returned no data (likely gated)")
                if stored:
                    collected += 1 if "returns" in stored else 0
                    if used_slug:
                        with db.Session() as session:
                            for r in session.query(CompanyConnection).filter(
                                    CompanyConnection.related_symbol == sym,
                                    CompanyConnection.is_active == True).all():
                                if not r.related_slug:
                                    r.related_slug = used_slug
                            session.commit()
        except Exception as e:
            logger.debug("partner snapshot collection failed for %s: %s", sym, e)
            _mark_collection_attempt(sym, db, f"error: {e}")
        _sleep_politely()

    logger.info("Partner snapshots: %d collected, %d/%d still missing data",
                collected, max(0, len(pending) - collected), len(keys))
    return {"collected": collected, "checked": min(len(pending), limit),
            "pending": max(0, len(pending) - collected), "total_partners": len(keys)}


def _cached_slug_status(name, db=None):
    """Return the cached resolution_status for a name, or None if not cached.

    Used so a known-failed name can be skipped *without* consuming one of the
    per-run network attempts.
    """
    from db_manager import get_db, ExternalSlugMap
    db = db or get_db()
    try:
        with db.Session() as session:
            row = (session.query(ExternalSlugMap)
                   .filter_by(source=SOURCE, company_name=(name or "").strip()).first())
            if not row:
                return None
            if row.resolution_status == "failed" and row.updated_at and \
               (datetime.utcnow() - row.updated_at) < timedelta(days=30):
                return "failed"
            return row.resolution_status
    except Exception as e:
        logger.debug("slug status lookup failed for %s: %s", name, e)
        return None


def _touch_connections(name, db=None):
    """Bump updated_at on a name's connection rows so the pending queue rotates.

    The queue is ordered by updated_at ASC. Without this, names that fail are
    never written to, so they stay at the front forever and starve every other
    pending name.
    """
    from db_manager import get_db, CompanyConnection
    db = db or get_db()
    try:
        with db.Session() as session:
            # Active rows only — bumping updated_at on inactive rows would push
            # them into the 90-day "recently removed" window and resurface old
            # "no longer listed" alerts.
            rows = (session.query(CompanyConnection)
                    .filter(CompanyConnection.related_name == name,
                            CompanyConnection.is_active == True)
                    .all())
            for r in rows:
                r.updated_at = datetime.utcnow()
            session.commit()
    except Exception as e:
        logger.debug("touch connections failed for %s: %s", name, e)


def resolve_pending_connections(db=None, limit=None, symbols=None):
    """
    Second pass: resolve connection names (suppliers/customers) → NSE symbols
    via their own Tijori pages, so we can track their prices/performance.
    Processes up to tijori.max_slug_resolutions_per_run names per call.
    """
    from db_manager import get_db, CompanyConnection

    if not _enabled():
        return {"resolved": 0, "skipped": "tijori disabled"}

    db = db or get_db()
    limit = limit or int(_cfg("tijori.max_slug_resolutions_per_run", 15))
    resolved_count = 0
    checked = 0
    local_count = 0

    # Every pending name, not just a slice — pass 1 below is free, so there is
    # no reason to ration it.
    with db.Session() as session:
        q = (session.query(CompanyConnection)
             .filter(CompanyConnection.related_symbol.is_(None),
                     CompanyConnection.is_active == True))
        if symbols:
            # Scope to one principal company's partners (used when onboarding
            # a newly added stock, so it doesn't drag in the global backlog).
            q = q.filter(CompanyConnection.symbol.in_(list(symbols)))
        pending = q.order_by(CompanyConnection.updated_at.asc()).all()
        names = []
        seen = set()
        for p in pending:
            if p.related_name not in seen:
                seen.add(p.related_name)
                names.append(p.related_name)

    def _apply(name, symbol, slug=None):
        """Stamp a resolved symbol onto the ACTIVE connection rows for a name.

        The is_active filter matters: writing to a row bumps updated_at
        (onupdate=), and inactive rows updated within 90 days are reported as
        "supplier no longer listed" changes. Touching them here would resurrect
        stale alerts into narratives and the UI.
        """
        with db.Session() as session:
            rows = (session.query(CompanyConnection)
                    .filter(CompanyConnection.related_name == name,
                            CompanyConnection.is_active == True)
                    .all())
            for r in rows:
                # Fill only. A name is matched globally, so a row may already
                # carry a symbol resolved for a different principal — often
                # from the authoritative Groww master. Overwriting it here
                # would silently replace good data with a scraped guess.
                if not r.related_symbol:
                    r.related_symbol = symbol
                if slug and not r.related_slug:
                    r.related_slug = slug
            session.commit()

    # ── Pass 1: local index (no network, no budget) ──────────────────────
    # Resolutions are collected first and written in ONE transaction — a
    # session per name would be an N+1 write.
    remaining = []
    local_map = {}
    for name in names:
        try:
            sym = resolve_locally(name, db=db)
        except Exception as e:
            logger.debug("local resolve failed for %s: %s", name, e)
            sym = None
        if sym:
            local_map[name] = sym
        else:
            remaining.append(name)

    if local_map:
        with db.Session() as session:
            rows = (session.query(CompanyConnection)
                    .filter(CompanyConnection.related_name.in_(list(local_map.keys())),
                            CompanyConnection.is_active == True)
                    .all())
            for r in rows:
                sym = local_map.get(r.related_name)
                if sym and not r.related_symbol:
                    r.related_symbol = sym
            session.commit()
        local_count = len(local_map)
        logger.info("Tijori resolution: %d names resolved locally across %d rows (no network)",
                    local_count, len(rows))

    # ── Pass 2: network fallback, budgeted ───────────────────────────────
    # Only genuine HTTP attempts consume the per-run budget. Previously a
    # cached failure returned instantly but still burned a slot, so a handful
    # of bad names could starve the queue indefinitely.
    for name in remaining:
        if checked >= limit:
            break
        cached = _cached_slug_status(name, db)
        if cached == "failed":
            # Rotate this name to the back so it stops blocking fresh ones
            _touch_connections(name, db)
            continue
        checked += 1
        res = resolve_slug(name, db=db)
        partner_html = res.pop("_html", None)
        if res.get("status") == "resolved" and res.get("symbol"):
            _apply(name, res["symbol"], res.get("slug"))
            resolved_count += 1
            # We already have their page in hand — store their snapshots too
            # (returns/ratios power the supply-chain health score, zero extra requests)
            if partner_html:
                try:
                    parsed = parse_company_page(partner_html)
                    _store_snapshots(res["symbol"], parsed, db)
                except Exception as e:
                    logger.debug("partner snapshot store failed for %s: %s", name, e)
        else:
            # Failed this round — rotate so the next run tries different names
            _touch_connections(name, db)
        _sleep_politely()

    total = local_count + resolved_count
    logger.info("Tijori connection resolution: %d local + %d network = %d resolved "
                "(%d HTTP attempts, %d names still pending)",
                local_count, resolved_count, total, checked,
                max(0, len(remaining) - resolved_count))
    return {"resolved": total, "local": local_count, "network": resolved_count,
            "checked": checked, "pending": max(0, len(remaining) - resolved_count)}


def onboard_symbol(symbol, db=None):
    """Populate everything for ONE newly added stock, end to end.

    Scoped deliberately to this symbol — it does not touch the global backlog,
    so adding a stock stays fast and predictable. Runs the same three stages the
    scheduler runs continuously, just narrowed:

      1. the company's own page (connections, ratios, forensics, peers)
      2. match its suppliers/customers to NSE symbols (local index first)
      3. fetch those partners' pages so their performance data exists

    Safe to re-run: every stage skips work that is already done.
    """
    from db_manager import get_db, set_config
    db = db or get_db()
    symbol = symbol.upper()
    out = {"symbol": symbol}

    out["company"] = collect_for_symbol(symbol, db=db)
    try:
        out["resolve"] = resolve_pending_connections(
            db=db, limit=int(_cfg("tijori.onboard_partner_limit", 20)), symbols=[symbol])
    except Exception as e:
        out["resolve"] = {"error": str(e)}
    try:
        out["partner_data"] = collect_missing_partner_snapshots(
            db=db, limit=int(_cfg("tijori.onboard_partner_limit", 20)), symbols=[symbol])
    except Exception as e:
        out["partner_data"] = {"error": str(e)}

    # Anything still missing is picked up by the routine scheduler passes
    try:
        set_config(f"tijori.onboarded.{symbol}", datetime.utcnow().isoformat(),
                   "When this symbol completed initial supply-chain onboarding")
    except Exception:
        pass
    logger.info("Onboarded %s: %s", symbol, out)
    return out


def collect_stale_symbols(db=None, max_symbols=None):
    """
    Scheduler entry point: refresh Tijori data for symbols whose data is older
    than tijori.refresh_interval_days. Covers ALL stocks with price data
    (watchlist) — same universe the analysis endpoints use.
    """
    from db_manager import get_db, get_config

    if not _enabled():
        return {"skipped": "tijori disabled"}

    db = db or get_db()
    max_symbols = max_symbols or int(_cfg("tijori.max_symbols_per_run", 10))
    interval_days = float(_cfg("tijori.refresh_interval_days", 7))

    # Universe: every symbol with price data (mirrors watchlist analysis universe)
    symbols = []
    try:
        with db.Session() as session:
            from sqlalchemy import text as _text
            rows = session.execute(_text("SELECT DISTINCT symbol FROM stock_prices ORDER BY symbol")).fetchall()
            symbols = [r[0] for r in rows]
    except Exception as e:
        logger.debug("stock_prices universe query failed (%s); falling back to stocks table", e)
        try:
            from db_manager import get_all_stocks
            symbols = [s.symbol for s in get_all_stocks(db)]
        except Exception:
            symbols = []

    # Filter to stale ones
    stale = []
    now = datetime.utcnow()
    # One batched read instead of a get_config round-trip per symbol
    try:
        from db_manager import get_configs_prefix
        _last_map = {k.rsplit(".", 1)[-1]: v
                     for k, v in get_configs_prefix("tijori.last_collected.").items()}
    except Exception as e:
        logger.debug("batched last_collected read failed (%s); falling back", e)
        _last_map = None
    for sym in symbols:
        last = _last_map.get(sym) if _last_map is not None else get_config(f"tijori.last_collected.{sym}")
        if last:
            try:
                if (now - datetime.fromisoformat(last)) < timedelta(days=interval_days):
                    continue
            except Exception:
                pass
        stale.append(sym)

    results = []
    for sym in stale[:max_symbols]:
        results.append(collect_for_symbol(sym, db=db))
        _sleep_politely()

    # Opportunistically resolve pending connection names too
    try:
        resolve_pending_connections(db=db)
    except Exception as e:
        logger.debug("connection resolution pass failed: %s", e)

    # Third pass: fill in performance data for partners that have a symbol but
    # were never fetched. Runs every cycle so the backlog drains on its own.
    partner_stats = {}
    try:
        partner_stats = collect_missing_partner_snapshots(db=db)
    except Exception as e:
        logger.debug("partner snapshot pass failed: %s", e)

    ok = sum(1 for r in results if r.get("ok"))
    logger.info("Tijori refresh pass: %d symbols processed (%d ok, %d stale remaining), "
                "partner data +%d (%d still missing)",
                len(results), ok, max(0, len(stale) - max_symbols),
                partner_stats.get("collected", 0), partner_stats.get("pending", 0))
    return {"processed": len(results), "ok": ok,
            "stale_remaining": max(0, len(stale) - max_symbols),
            "partner_snapshots": partner_stats}


# ── Analysis / read API ──────────────────────────────────────────────────────

def _latest_two_snapshots(session, symbol, data_type):
    from db_manager import CompanyExternalData
    rows = (session.query(CompanyExternalData)
            .filter_by(symbol=symbol, data_type=data_type, source=SOURCE)
            .order_by(CompanyExternalData.scraped_at.desc())
            .limit(2).all())
    latest = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None
    return latest, prev


def _load_snapshots_bulk(session, symbols, data_types=None):
    """Fetch the latest two snapshots for MANY symbols in a single query.

    Returns {(symbol, data_type): (latest, prev)}. Replaces per-symbol,
    per-type calls to _latest_two_snapshots, which cost 3 queries per partner
    and dominated the supply-chain read path.
    """
    from db_manager import CompanyExternalData
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols:
        return {}
    q = (session.query(CompanyExternalData)
         .filter(CompanyExternalData.symbol.in_(symbols),
                 CompanyExternalData.source == SOURCE))
    if data_types:
        q = q.filter(CompanyExternalData.data_type.in_(list(data_types)))
    rows = q.order_by(CompanyExternalData.symbol,
                      CompanyExternalData.data_type,
                      CompanyExternalData.scraped_at.desc()).all()

    out = {}
    for r in rows:
        key = (r.symbol, r.data_type)
        cur = out.get(key)
        if cur is None:
            out[key] = (r, None)
        elif cur[1] is None:
            out[key] = (cur[0], r)   # rows arrive newest-first per group
    return out


def get_supply_chain_intel(symbol, db=None):
    """
    Read stored Tijori data for a symbol and build the supply-chain intelligence
    view used by deep analysis / the dashboard:

      - suppliers & customers (with resolved symbols where known)
      - their latest performance (returns/ratios) if we have their snapshots
      - what changed since the previous scrape (ratios drift, forensic flips,
        supplier/customer additions & removals)
    """
    from db_manager import get_db, CompanyConnection

    symbol = symbol.upper()
    db = db or get_db()
    out = {"symbol": symbol, "source": SOURCE, "available": False,
           "suppliers": [], "customers": [], "competitors": [],
           "ratios": None, "returns": None, "forensics_summary": None,
           "peers": None, "market_share": None, "impact": None,
           "changes": [], "health": None}

    try:
        with db.Session() as session:
            # connections
            conns = (session.query(CompanyConnection)
                     .filter_by(symbol=symbol)
                     .filter(CompanyConnection.is_active == True)
                     .all())
            for c in conns:
                entry = {"name": c.related_name, "symbol": c.related_symbol,
                         "since": c.first_seen.isoformat() if c.first_seen else None}
                if c.relation_type == "supplier":
                    out["suppliers"].append(entry)
                elif c.relation_type == "customer":
                    out["customers"].append(entry)
                elif c.relation_type == "competitor":
                    out["competitors"].append(entry)

            # recently deactivated (removed) connections — a signal by itself
            removed = (session.query(CompanyConnection)
                       .filter_by(symbol=symbol)
                       .filter(CompanyConnection.is_active == False)
                       .filter(CompanyConnection.updated_at >= datetime.utcnow() - timedelta(days=90))
                       .all())
            for r in removed:
                out["changes"].append({
                    "type": "connection_removed",
                    "detail": f"{r.relation_type.title()} '{r.related_name}' no longer listed",
                })

            # One bulk read covering this company AND every resolved partner,
            # instead of 3 queries per partner + 5 for ourselves.
            partner_syms = [e["symbol"] for e in out["suppliers"] + out["customers"]
                            if e.get("symbol")]
            # Only the block types this function actually reads. company_external_data
            # is append-only, so without this filter we materialise every historical
            # snapshot row (incl. large company_info/corporate_actions payloads) for
            # every partner — cost that grows as partner coverage rises.
            snaps = _load_snapshots_bulk(
                session, [symbol] + partner_syms,
                data_types=("ratios", "returns", "forensics", "peers", "market_share"))
            snap = lambda s, t: snaps.get((s, t), (None, None))

            # latest ratios + returns + forensics with prev comparison
            lat, prev = snap(symbol, "ratios")
            if lat:
                out["ratios"] = lat.get_payload()
                out["available"] = True
                if prev:
                    out["changes"] += _diff_ratios(prev.get_payload(), lat.get_payload())

            lat_r, _ = snap(symbol, "returns")
            if lat_r:
                out["returns"] = lat_r.get_payload()
                out["available"] = True

            lat_f, prev_f = snap(symbol, "forensics")
            if lat_f:
                out["forensics_summary"] = _summarize_forensics(lat_f.get_payload())
                out["available"] = True
                if prev_f:
                    out["changes"] += _diff_forensics(prev_f.get_payload(), lat_f.get_payload())

            # peer comparison table (as scraped from Tijori — PE/mcap/ROE/ROCE/YoY sales)
            lat_p, _ = snap(symbol, "peers")
            if lat_p:
                out["peers"] = lat_p.get_payload()
                out["available"] = True

            # market share series → compact latest-value summary
            lat_ms, _ = snap(symbol, "market_share")
            if lat_ms:
                ms = lat_ms.get_payload()
                if isinstance(ms, list):
                    out["market_share"] = [
                        {"name": m.get("name"), "value": m.get("latest_value"),
                         "unit": m.get("unit"), "as_of": m.get("latest_date")}
                        for m in ms if isinstance(m, dict) and m.get("latest_value") is not None
                    ] or None
                    if out["market_share"]:
                        out["available"] = True

            # supplier/customer enrichment: returns + key financial stats +
            # forensics, all served from the single bulk read above
            partner_data = {}
            for ps in set(partner_syms):
                d = {}
                lat_pr, _ = snap(ps, "returns")
                if lat_pr:
                    d["returns"] = lat_pr.get_payload()
                lat_rt, _ = snap(ps, "ratios")
                if lat_rt:
                    stats = _key_ratios(lat_rt.get_payload())
                    if stats:
                        d["stats"] = stats
                lat_fx, _ = snap(ps, "forensics")
                if lat_fx:
                    c = (lat_fx.get_payload() or {}).get("count") or {}
                    d["forensics"] = {"green": c.get("green", 0), "red": c.get("red", 0),
                                      "total": c.get("total", 0)}
                if d:
                    partner_data[ps] = d
            for e in out["suppliers"] + out["customers"]:
                if e.get("symbol") and e["symbol"] in partner_data:
                    e.update(partner_data[e["symbol"]])

            out["health"] = _compute_health(out)
            out["impact"] = _impact_narrative(symbol, out)
    except Exception as e:
        logger.debug("get_supply_chain_intel(%s) failed: %s", symbol, e)
        out["error"] = str(e)

    return out


_KEY_RATIO_NAMES = {"mcap": "mcap", "pe": "pe", "roe": "roe", "roce": "roce",
                    "tpftotalpromoter": "promoter_holding"}


def _key_ratios(payload):
    """Extract key stats (mcap/pe/roe/roce/promoter) from a ratios_table payload."""
    out = {}
    if not isinstance(payload, list):
        return out
    for r in payload:
        if isinstance(r, dict) and r.get("name") in _KEY_RATIO_NAMES:
            try:
                out[_KEY_RATIO_NAMES[r["name"]]] = round(float(r.get("value")), 2)
            except (TypeError, ValueError):
                pass
    return out


def _impact_narrative(symbol, intel):
    """One-paragraph read on how the supply-chain network affects the principal
    company, built from partner health, laggards, and partner red flags."""
    sup_n = len(intel.get("suppliers") or [])
    cus_n = len(intel.get("customers") or [])
    if not sup_n and not cus_n:
        return None

    parts = [f"{symbol} has {sup_n} tracked supplier{'s' if sup_n != 1 else ''}"
             + (f" and {cus_n} customer{'s' if cus_n != 1 else ''}" if cus_n else "") + "."]

    h = intel.get("health")
    if h:
        avg = h.get("avg_partner_return_6m")
        n = h.get("partners_tracked", 0)
        dec = h.get("partners_declining", 0)
        status = h.get("status", "")
        if status == "STRONG":
            parts.append(f"The network is a tailwind: {n} listed partners average "
                         f"{avg:+.1f}% over 6 months ({dec} declining), suggesting a "
                         f"healthy demand/supply ecosystem around {symbol}.")
        elif status == "WEAK":
            parts.append(f"The network is a headwind: {n} listed partners average "
                         f"{avg:+.1f}% over 6 months with {dec} declining — stress among "
                         f"partners can foreshadow input disruptions or demand weakness for {symbol}.")
        else:
            parts.append(f"Partner performance is mixed: {n} listed partners average "
                         f"{avg:+.1f}% over 6 months ({dec} declining).")

    # Worst laggard among partners with return data
    partners = (intel.get("suppliers") or []) + (intel.get("customers") or [])
    with_ret = [p for p in partners if isinstance(p.get("returns"), dict)
                and p["returns"].get("6m") is not None]
    if with_ret:
        worst = min(with_ret, key=lambda p: p["returns"]["6m"])
        if worst["returns"]["6m"] <= -15:
            parts.append(f"Weakest link: {worst.get('symbol') or worst.get('name')} "
                         f"({worst['returns']['6m']:+.1f}% 6m) — worth watching for knock-on effects.")

    # Partners with heavy forensic red flags
    flagged = [p for p in partners if (p.get("forensics") or {}).get("red", 0) >= 5]
    if flagged:
        names = ", ".join((p.get("symbol") or p.get("name")) for p in flagged[:3])
        parts.append(f"Governance watch: {names} carr{'y' if len(flagged) > 1 else 'ies'} "
                     f"5+ forensic red flags.")

    return " ".join(parts)


def _diff_ratios(old, new):
    """Compare two ratios_table payloads → list of change dicts."""
    changes = []
    if not (isinstance(old, list) and isinstance(new, list)):
        return changes
    old_map = {r.get("name"): r for r in old if isinstance(r, dict)}
    for r in new:
        if not isinstance(r, dict):
            continue
        o = old_map.get(r.get("name"))
        if not o:
            continue
        try:
            ov, nv = float(o.get("value")), float(r.get("value"))
            if ov == 0:
                continue
            pct = (nv - ov) / abs(ov) * 100
            if abs(pct) >= 5:  # only meaningful moves
                changes.append({
                    "type": "ratio_change",
                    "detail": f"{r.get('display_name') or r.get('name')}: "
                              f"{round(ov, 2)} → {round(nv, 2)} ({pct:+.1f}%)",
                })
        except (TypeError, ValueError):
            continue
    return changes


def _summarize_forensics(ql):
    """quick_look payload → compact summary {green, red, neutral, red_flags[]}."""
    if not isinstance(ql, dict):
        return None
    counts = ql.get("count") or {}
    red_flags = []
    for grp in ql.get("data") or []:
        for f in grp.get("factories") or []:
            if f.get("flag") == 3:          # red
                red_flags.append(f.get("sentence") or f.get("name"))
    return {"green": counts.get("green"), "red": counts.get("red"),
            "neutral": counts.get("neutral"), "total": counts.get("total"),
            "red_flags": red_flags}


def _diff_forensics(old, new):
    """Detect forensic flag flips between snapshots."""
    changes = []
    def _flags(ql):
        m = {}
        for grp in (ql or {}).get("data") or []:
            for f in grp.get("factories") or []:
                m[f.get("name")] = f.get("flag")
        return m
    of, nf = _flags(old), _flags(new)
    for name, flag in nf.items():
        if name in of and of[name] != flag:
            direction = "improved" if (flag or 0) < (of[name] or 0) else "worsened"
            changes.append({"type": "forensic_flip",
                            "detail": f"Forensic check '{name}' {direction}"})
    return changes


def _compute_health(intel):
    """
    Supply-chain health score from partner returns.
    Uses 3m/6m returns of resolved suppliers+customers.
    """
    # De-duplicate by resolved symbol: the same company can appear under two
    # name spellings ("Tata Steel Ltd." / "Tata Steel"), and counting it twice
    # would skew the average. Falls back to name when unresolved.
    partners, seen_keys = [], set()
    for e in intel["suppliers"] + intel["customers"]:
        if not e.get("returns"):
            continue
        key = e.get("symbol") or e.get("name")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        partners.append(e)
    if not partners:
        return None
    vals = []
    for p in partners:
        r = p["returns"]
        v = r.get("6m") if r.get("6m") is not None else r.get("1m")
        if v is not None:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                pass
    if not vals:
        return None
    avg = sum(vals) / len(vals)
    declining = sum(1 for v in vals if v < -10)
    status = "STRONG" if avg > 10 else "WEAK" if avg < -5 else "STABLE"
    return {"avg_partner_return_6m": round(avg, 2), "partners_tracked": len(vals),
            "partners_declining": declining, "status": status}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    sym = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    print(json.dumps(collect_for_symbol(sym), indent=2, default=str))
    print(json.dumps(get_supply_chain_intel(sym), indent=2, default=str))
