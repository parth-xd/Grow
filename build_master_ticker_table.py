"""
Build / daily-refresh the master ticker table — the complete NSE security
directory plus each data provider's identifier for the same security.

DIRECTORY ONLY. This script never fetches prices, never subscribes to any
feed, and never triggers Tijori collection for a security that hasn't
already been onboarded via the Watchlist. See db_manager.MasterTicker for
the full rationale.

Sources, both read-only / no-auth:
  - Groww instrument master (get_all_instruments) — NSE universe + ISIN
  - FYERS public instrument master (public.fyers.in/sym_details/NSE_CM.csv)
    — FYERS historical/WebSocket symbol + FYERS token, joined by ISIN

Tijori identifiers are read (never fetched) from the existing
`external_slug_map` cache that tijori_collector.py already maintains.

Idempotent: re-running only touches rows whose mapped fields actually
changed, per spec ("existing securities should NOT have all their provider
mappings unnecessarily rebuilt every day").
"""

import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FYERS_NSE_CM_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"

# The only indices this build handles: the ones our own code already
# resolves and calls by these exact FYERS symbols (fyers_market_data_provider.py
# _INDEX_SYMBOLS, fetch_full_history.py INDEX_SYMBOLS), cross-checked against
# the live FYERS master below rather than assumed.
_KNOWN_INDICES = {
    "NIFTY":     {"fyers_symbol": "NSE:NIFTY50-INDEX",   "groww_name_hint": "NIFTY 50"},
    "BANKNIFTY": {"fyers_symbol": "NSE:NIFTYBANK-INDEX", "groww_name_hint": "NIFTY BANK"},
    "FINNIFTY":  {"fyers_symbol": "NSE:FINNIFTY-INDEX",  "groww_name_hint": "NIFTY FIN SERVICE"},
}


def _fetch_groww_universe():
    """Groww instrument master, filtered to NSE main-board equities + the 3 known indices."""
    from growwapi import GrowwAPI
    token = os.getenv("GROWW_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GROWW_ACCESS_TOKEN is not set. Configure it in .env")
    groww = GrowwAPI(token)
    df = groww.get_all_instruments()
    nse = df[df["exchange"] == "NSE"]

    eq = nse[(nse["segment"] == "CASH") & (nse["series"] == "EQ")]
    equities = [
        {"nse_ticker": r.trading_symbol, "company_name": r.name, "isin": r.isin}
        for r in eq.itertuples()
    ]

    idx = nse[nse["instrument_type"] == "IDX"]
    indices = []
    for canonical, meta in _KNOWN_INDICES.items():
        hint = meta["groww_name_hint"]
        match = idx[idx["name"].str.upper() == hint.upper()]
        company_name = match.iloc[0]["name"] if len(match) else hint
        indices.append({"nse_ticker": canonical, "company_name": company_name, "isin": None})

    logger.info("Groww: %d main-board equities, %d known indices", len(equities), len(indices))
    return equities, indices


def _fetch_fyers_master():
    """FYERS NSE Cash instrument master (public, no auth). Returns (isin_map, index_map)."""
    r = requests.get(FYERS_NSE_CM_URL, timeout=30)
    r.raise_for_status()
    lines = r.text.strip().split("\n")

    isin_map = {}   # isin -> {fyers_symbol, fyers_token, fyers_isin}
    index_map = {}  # "NSE:XXX-INDEX" -> {fyers_token}
    for line in lines:
        cols = line.split(",")
        if len(cols) < 11:
            continue
        fy_token, isin, sym_ticker = cols[0], cols[5], cols[9]
        if sym_ticker.endswith("-EQ") and isin:
            isin_map[isin] = {"fyers_symbol": sym_ticker, "fyers_token": fy_token, "fyers_isin": isin}
        elif sym_ticker.endswith("-INDEX"):
            index_map[sym_ticker] = {"fyers_token": fy_token}

    logger.info("FYERS master: %d EQ ISINs, %d index symbols", len(isin_map), len(index_map))
    return isin_map, index_map


def _fetch_tijori_cache(db):
    """Existing verified Tijori slugs — read-only, no new Tijori requests."""
    from db_manager import ExternalSlugMap
    with db.Session() as session:
        rows = (
            session.query(ExternalSlugMap.symbol, ExternalSlugMap.slug)
            .filter_by(source="tijori", resolution_status="resolved")
            .filter(ExternalSlugMap.symbol.isnot(None))
            .all()
        )
    cache = {symbol: slug for symbol, slug in rows if slug}
    logger.info("Tijori cache (existing, read-only): %d verified slugs", len(cache))
    return cache


_MAPPED_FIELDS = [
    "company_name", "isin", "exchange", "segment", "instrument_type",
    "fyers_historical_symbol", "fyers_websocket_symbol", "fyers_token", "fyers_isin",
    "fyers_resolution_status", "fyers_unresolved_reason",
    "tijori_ticker", "tijori_resolution_status", "tijori_unresolved_reason",
]


def _build_rows(equities, indices, fyers_isin_map, fyers_index_map, tijori_cache):
    rows = {}

    for e in equities:
        fy = fyers_isin_map.get(e["isin"]) if e["isin"] else None
        row = {
            "nse_ticker": e["nse_ticker"], "company_name": e["company_name"], "isin": e["isin"],
            "exchange": "NSE", "segment": "CASH", "instrument_type": "EQ",
        }
        if fy:
            row.update({
                "fyers_historical_symbol": fy["fyers_symbol"],
                "fyers_websocket_symbol": fy["fyers_symbol"],
                "fyers_token": fy["fyers_token"],
                "fyers_isin": fy["fyers_isin"],
                "fyers_resolution_status": "resolved",
                "fyers_unresolved_reason": None,
            })
        else:
            row.update({
                "fyers_historical_symbol": None, "fyers_websocket_symbol": None,
                "fyers_token": None, "fyers_isin": None,
                "fyers_resolution_status": "unresolved",
                "fyers_unresolved_reason": "ISIN not found in FYERS NSE_CM.csv instrument master"
                if e["isin"] else "No ISIN available from Groww instrument master to join on",
            })
        rows[e["nse_ticker"]] = row

    for i in indices:
        meta = _KNOWN_INDICES[i["nse_ticker"]]
        fy_sym = meta["fyers_symbol"]
        fy = fyers_index_map.get(fy_sym)
        row = {
            "nse_ticker": i["nse_ticker"], "company_name": i["company_name"], "isin": None,
            "exchange": "NSE", "segment": "INDEX", "instrument_type": "INDEX",
        }
        if fy:
            row.update({
                "fyers_historical_symbol": fy_sym, "fyers_websocket_symbol": fy_sym,
                "fyers_token": fy["fyers_token"], "fyers_isin": None,
                "fyers_resolution_status": "resolved", "fyers_unresolved_reason": None,
            })
        else:
            row.update({
                "fyers_historical_symbol": None, "fyers_websocket_symbol": None,
                "fyers_token": None, "fyers_isin": None,
                "fyers_resolution_status": "unresolved",
                "fyers_unresolved_reason": f"{fy_sym} not found in current FYERS NSE_CM.csv master",
            })
        rows[i["nse_ticker"]] = row

    for nse_ticker, row in rows.items():
        slug = tijori_cache.get(nse_ticker)
        if slug:
            row["tijori_ticker"] = slug
            row["tijori_resolution_status"] = "resolved"
            row["tijori_unresolved_reason"] = None
        else:
            row["tijori_ticker"] = None
            row["tijori_resolution_status"] = "not_attempted"
            row["tijori_unresolved_reason"] = (
                "Not yet added to Watchlist — Tijori identifiers resolve only via the "
                "existing onboarding flow (tijori_collector.onboard_symbol) at watchlist-add "
                "time; this build never bulk-scrapes Tijori for the full universe."
            )

    return rows


def build_master_ticker_table():
    from db_manager import get_db, MasterTicker

    db = get_db()
    db.init_db()

    equities, indices = _fetch_groww_universe()
    fyers_isin_map, fyers_index_map = _fetch_fyers_master()
    tijori_cache = _fetch_tijori_cache(db)
    new_rows = _build_rows(equities, indices, fyers_isin_map, fyers_index_map, tijori_cache)

    now = datetime.utcnow()
    session = db.Session()
    try:
        existing = {row.nse_ticker: row for row in session.query(MasterTicker).all()}

        to_insert, to_update = [], []
        seen_tickers = set(new_rows.keys())

        for nse_ticker, row in new_rows.items():
            cur = existing.get(nse_ticker)
            if cur is None:
                row["is_active"] = True
                row["first_seen_at"] = now
                row["last_seen_at"] = now
                row["updated_at"] = now
                to_insert.append(row)
                continue

            changed = any(getattr(cur, f) != row[f] for f in _MAPPED_FIELDS)
            update = {"nse_ticker": nse_ticker, "last_seen_at": now}
            if not cur.is_active:
                update["is_active"] = True
            if changed:
                update.update({f: row[f] for f in _MAPPED_FIELDS})
                update["updated_at"] = now
            if changed or not cur.is_active:
                to_update.append(update)

        to_deactivate = [
            t for t, cur in existing.items() if t not in seen_tickers and cur.is_active
        ]

        if to_insert:
            session.bulk_insert_mappings(MasterTicker, to_insert)
        if to_update:
            session.bulk_update_mappings(MasterTicker, to_update)
        if to_deactivate:
            session.query(MasterTicker).filter(MasterTicker.nse_ticker.in_(to_deactivate)).update(
                {"is_active": False, "updated_at": now}, synchronize_session=False
            )
        session.commit()

        unchanged = len(seen_tickers) - len(to_insert) - len(to_update)
        logger.info(
            "master_ticker_table: %d new, %d updated, %d deactivated, %d unchanged",
            len(to_insert), len(to_update), len(to_deactivate), unchanged,
        )
        return {
            "total_seen": len(seen_tickers),
            "inserted": len(to_insert),
            "updated": len(to_update),
            "deactivated": len(to_deactivate),
        }
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = build_master_ticker_table()
    print(f"✓ master_ticker_table build complete: {result}")
