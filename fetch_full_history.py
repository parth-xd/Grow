"""
Fetch comprehensive historical candle data from Groww V1 API.

Fetches DAILY candles in 2-year chunks back to 2020 for:
  - All 72 stocks already in DB
  - Indices: NIFTY, BANKNIFTY, FINNIFTY

Also fetches 1hr candles (90-day chunks) and 5min candles (15-day chunks)
for recent data to give XGBoost multi-timeframe features.

V1 API limits per request:
  5min  → max 15 days
  15min → max 30 days
  1hr   → max 90 days
  daily → max ~2 years

Run: python fetch_full_history.py
"""

import os
import time
import logging
import psycopg2
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ── Groww V1 API limits per interval ──────────────────────────────────────────
INTERVAL_CONFIGS = {
    "daily": {"minutes": 1440, "max_days": 700, "chunk_days": 365},
    "1hr":   {"minutes": 60,   "max_days": 90,  "chunk_days": 85},
    "5min":  {"minutes": 5,    "max_days": 15,   "chunk_days": 14},
}

# Indices to fetch (trading_symbol → DB symbol)
INDEX_SYMBOLS = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
}


def _get_groww():
    from growwapi import GrowwAPI
    token = os.getenv("GROWW_ACCESS_TOKEN")
    return GrowwAPI(token)


def _get_db_symbols():
    """Get all unique symbols from the candles table."""
    conn = psycopg2.connect("dbname=grow_trading_bot")
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM candles ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]
    conn.close()
    return symbols


def _get_existing_timestamps(symbol):
    """Get set of existing timestamps for a symbol to avoid duplicates."""
    conn = psycopg2.connect("dbname=grow_trading_bot")
    cur = conn.cursor()
    cur.execute("SELECT timestamp FROM candles WHERE symbol = %s", (symbol,))
    timestamps = {r[0] for r in cur.fetchall()}
    conn.close()
    return timestamps


def _insert_candles(symbol, candles_data, existing_ts):
    """Insert new candles into DB, skipping duplicates."""
    if not candles_data:
        return 0

    conn = psycopg2.connect("dbname=grow_trading_bot")
    cur = conn.cursor()
    inserted = 0

    for c in candles_data:
        try:
            ts_val = c[0]
            if isinstance(ts_val, (int, float)):
                ts = datetime.fromtimestamp(ts_val)
            else:
                ts = datetime.strptime(str(ts_val).replace("T", " "), "%Y-%m-%d %H:%M:%S")

            if ts in existing_ts:
                continue

            o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
            vol = int(c[5]) if c[5] is not None else 0

            if o <= 0 or h <= 0 or l <= 0 or cl <= 0:
                continue

            cur.execute(
                "INSERT INTO candles (symbol, timestamp, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (symbol, ts, o, h, l, cl, vol),
            )
            existing_ts.add(ts)
            inserted += 1
        except Exception as e:
            logger.debug("Skip candle for %s: %s", symbol, e)

    conn.commit()
    conn.close()
    return inserted


def fetch_chunked(groww, trading_symbol, db_symbol, interval_cfg, start_date, end_date):
    """Fetch candles in chunks respecting API limits."""
    chunk_days = interval_cfg["chunk_days"]
    interval_min = interval_cfg["minutes"]
    
    existing_ts = _get_existing_timestamps(db_symbol)
    total_inserted = 0
    
    current_start = start_date
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_days), end_date)
        start_str = current_start.strftime("%Y-%m-%d 09:15:00")
        end_str = current_end.strftime("%Y-%m-%d 15:30:00")
        
        try:
            result = groww.get_historical_candle_data(
                trading_symbol=trading_symbol,
                exchange="NSE",
                segment="CASH",
                start_time=start_str,
                end_time=end_str,
                interval_in_minutes=interval_min,
            )
            candles = result.get("candles", [])
            if candles:
                n = _insert_candles(db_symbol, candles, existing_ts)
                total_inserted += n
                if n > 0:
                    logger.info("  %s %s→%s: +%d candles", db_symbol,
                               current_start.strftime("%Y-%m-%d"),
                               current_end.strftime("%Y-%m-%d"), n)
        except Exception as e:
            err = str(e)[:80]
            if "Invalid interval" not in err:
                logger.warning("  %s chunk error: %s", db_symbol, err)
        
        current_start = current_end
        time.sleep(0.25)  # Rate limit
    
    return total_inserted


def main():
    groww = _get_groww()
    now = datetime(2026, 4, 1)
    
    # ── Phase 1: Fetch DAILY candles back to 2020 for all stocks ─────
    logger.info("=" * 60)
    logger.info("PHASE 1: Daily candles (2020 → 2026) for all stocks + indices")
    logger.info("=" * 60)
    
    db_symbols = _get_db_symbols()
    all_symbols = list(db_symbols)  # existing stocks
    
    # Add indices
    for ts, ds in INDEX_SYMBOLS.items():
        if ds not in all_symbols:
            all_symbols.append(ds)
    
    daily_cfg = INTERVAL_CONFIGS["daily"]
    start_from = datetime(2020, 1, 1)
    
    total_daily = 0
    for i, symbol in enumerate(all_symbols):
        # For indices, use the index trading symbol; for stocks, same name
        trading_sym = symbol
        for ts, ds in INDEX_SYMBOLS.items():
            if ds == symbol:
                trading_sym = ts
                break
        
        logger.info("[%d/%d] %s (daily)", i + 1, len(all_symbols), symbol)
        n = fetch_chunked(groww, trading_sym, symbol, daily_cfg, start_from, now)
        total_daily += n
        if n > 0:
            logger.info("  → %s: +%d daily candles", symbol, n)
    
    logger.info("Phase 1 complete: +%d daily candles total", total_daily)
    
    # ── Phase 2: 1hr candles for last 6 months (XGBoost needs this) ──
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 2: 1hr candles (last 6 months) for indices")
    logger.info("=" * 60)
    
    hr_cfg = INTERVAL_CONFIGS["1hr"]
    hr_start = now - timedelta(days=180)
    
    total_hr = 0
    for ts, ds in INDEX_SYMBOLS.items():
        logger.info("  %s (1hr)", ds)
        n = fetch_chunked(groww, ts, ds, hr_cfg, hr_start, now)
        total_hr += n
    
    logger.info("Phase 2 complete: +%d hourly candles", total_hr)
    
    # ── Phase 3: 5min candles for last 15 days (indices only) ────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 3: 5min candles (last 15 days) for indices")
    logger.info("=" * 60)
    
    min5_cfg = INTERVAL_CONFIGS["5min"]
    min5_start = now - timedelta(days=14)
    
    total_5m = 0
    for ts, ds in INDEX_SYMBOLS.items():
        logger.info("  %s (5min)", ds)
        n = fetch_chunked(groww, ts, ds, min5_cfg, min5_start, now)
        total_5m += n
    
    logger.info("Phase 3 complete: +%d 5min candles", total_5m)
    
    # ── Summary ──────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("DONE: +%d daily, +%d hourly, +%d 5min candles",
                total_daily, total_hr, total_5m)
    logger.info("=" * 60)
    
    # Final DB stats
    conn = psycopg2.connect("dbname=grow_trading_bot")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM candles")
    total, syms = cur.fetchone()
    cur.execute("SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles WHERE symbol IN ('NIFTY','BANKNIFTY','FINNIFTY') GROUP BY symbol")
    idx_rows = cur.fetchall()
    conn.close()
    
    logger.info("DB total: %d candles across %d symbols", total, syms)
    for r in idx_rows:
        logger.info("  %s: %d candles (%s → %s)", r[0], r[1],
                    r[2].strftime("%Y-%m-%d"), r[3].strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main()
