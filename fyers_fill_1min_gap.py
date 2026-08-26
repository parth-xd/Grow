"""
Fill the 1-minute tier forward to the present.

fyers_historical_backfill.py deliberately splits tiers: 1-minute runs from
the 2017 floor up to (today - 35 days), and 5-second covers the tail. That
left resolution='1' ~37 days stale, which is fine for the 5-minute adapter
(it unions both tiers) but not for training a model on native 1-minute bars:
training would end 37 days before inference begins.

This fetches only the missing 1-minute window per symbol — one request each,
not a full re-backfill — using the same fetch/store path as the main script,
so it is idempotent (ON CONFLICT DO NOTHING) and never rewrites history.
"""

import logging
import os
from datetime import datetime, timedelta

import psycopg2
from dotenv import load_dotenv

import fyers_historical_backfill as fb
from fyers_historical_backfill import IST

load_dotenv()
logger = logging.getLogger(__name__)


def symbols_needing_fill():
    """Symbols whose 1-min tier lags the newest 1-min bar in the table."""
    conn = psycopg2.connect(os.getenv("DB_URL"))
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, max(ts) AS last_1m
            FROM fyers_candles WHERE resolution = '1'
            GROUP BY symbol ORDER BY symbol
        """)
        return cur.fetchall()
    finally:
        conn.close()


def fill(symbol, last_ts):
    """Fetch 1-minute bars from last_ts forward to now for one symbol."""
    from db_manager import get_db, MasterTicker

    db = get_db()
    with db.Session() as session:
        row = session.query(MasterTicker).filter_by(nse_ticker=symbol).first()
    if not row or row.fyers_resolution_status != "resolved":
        return {"symbol": symbol, "status": "no_mapping"}

    start = last_ts.astimezone(IST).replace(tzinfo=None) + timedelta(minutes=1)
    end = datetime.now(IST).replace(tzinfo=None)
    if start >= end:
        return {"symbol": symbol, "status": "current", "new": 0}

    candles = fb._fetch_resolution(row.fyers_historical_symbol, "1", start, end)
    stored = fb._store(symbol, "1", candles)
    return {"symbol": symbol, "status": "ok", "fetched": len(candles), "new": stored}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    rows = symbols_needing_fill()
    logger.info("Checking 1-minute freshness for %d symbols", len(rows))
    total_new = 0
    for symbol, last_ts in rows:
        try:
            r = fill(symbol, last_ts)
            total_new += r.get("new", 0)
            logger.info("%-14s %s  +%s rows", symbol, r["status"], r.get("new", 0))
        except Exception as e:
            logger.warning("%-14s FAILED %s", symbol, e)
    logger.info("1-minute gap fill complete: %d new rows", total_new)


if __name__ == "__main__":
    main()
