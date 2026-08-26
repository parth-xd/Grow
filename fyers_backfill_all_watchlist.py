"""
Bulk-run fyers_historical_backfill.backfill_symbol() for every symbol
currently in stock_prices (the current watchlist). One-off/maintenance
driver — reruns are safe AND resumable: any symbol that already has all
three resolutions (D/1/5S) in fyers_candles is skipped before making any
API calls, so an interrupted run picks back up without redoing finished
work. Storage itself was already idempotent (ON CONFLICT DO NOTHING); this
adds the same guarantee at the fetch level, not just the write level.

Paced the same as fyers_historical_backfill itself; per-symbol errors are
logged and skipped, not fatal to the batch.
"""

import logging
import time

logger = logging.getLogger(__name__)

_EXPECTED_RESOLUTIONS = {"D", "1", "5S"}


def backfill_all_watchlist():
    import psycopg2
    import os
    from dotenv import load_dotenv
    load_dotenv()

    conn = psycopg2.connect(os.getenv("DB_URL"))
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM stock_prices ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]

    # Resume support: symbols that already have all 3 resolutions stored
    # need no API calls at all.
    cur.execute("SELECT symbol, array_agg(DISTINCT resolution) FROM fyers_candles GROUP BY symbol")
    already_complete = {
        sym for sym, resolutions in cur.fetchall()
        if _EXPECTED_RESOLUTIONS.issubset(set(resolutions))
    }
    conn.close()

    logger.info(
        "Backfilling FYERS historical data for %d watchlist symbols (%d already complete, skipping those)",
        len(symbols), len(set(symbols) & already_complete),
    )

    import fyers_historical_backfill
    results = {"ok": [], "already_done": [], "no_fyers_mapping": [], "failed": []}

    for i, symbol in enumerate(symbols, 1):
        if symbol in already_complete:
            results["already_done"].append(symbol)
            logger.info("[%d/%d] %s already complete, skipping", i, len(symbols), symbol)
            continue
        t0 = time.time()
        try:
            r = fyers_historical_backfill.backfill_symbol(symbol)
            elapsed = time.time() - t0
            if r.get("status") == "ok":
                results["ok"].append(symbol)
                logger.info("[%d/%d] %s done in %.0fs: %s", i, len(symbols), symbol, elapsed, r["resolutions"])
            else:
                results["no_fyers_mapping"].append(symbol)
                logger.info("[%d/%d] %s skipped: %s", i, len(symbols), symbol, r.get("reason"))
        except Exception as e:
            results["failed"].append(symbol)
            logger.error("[%d/%d] %s FAILED: %s", i, len(symbols), symbol, e)

    logger.info(
        "Batch complete: %d ok, %d already done, %d no FYERS mapping, %d failed",
        len(results["ok"]), len(results["already_done"]), len(results["no_fyers_mapping"]), len(results["failed"]),
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print(backfill_all_watchlist())
