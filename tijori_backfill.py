"""
One-time Tijori backfill — collects supply-chain & fundamentals data for EVERY
stock currently in the dashboard (all symbols with price data), then resolves
supplier/customer names → NSE symbols so health scores start working.

Safe to re-run: symbols already collected within the refresh interval are
skipped automatically. After this, the scheduler keeps everything fresh.

Run:  .venv/bin/python tijori_backfill.py
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tijori_backfill")


def main():
    from db_manager import get_db, set_config
    from tijori_collector import (seed_tijori_config, collect_stale_symbols,
                                  resolve_pending_connections)

    db = get_db()
    db.init_db()
    seed_tijori_config()
    set_config("tijori.backfill_status", "running", "Tijori backfill state (running/complete)")

    # Collect every stale symbol in the dashboard universe (loop until done)
    total_ok = 0
    total_processed = 0
    while True:
        result = collect_stale_symbols(db=db, max_symbols=15)
        total_processed += result.get("processed", 0)
        total_ok += result.get("ok", 0)
        remaining = result.get("stale_remaining", 0)
        logger.info("Backfill progress: %d processed (%d ok), %d remaining",
                    total_processed, total_ok, remaining)
        if remaining <= 0 or result.get("processed", 0) == 0:
            break

    # A few extra resolution passes so supplier/customer symbols + performance
    # data start flowing into health scores immediately
    for i in range(3):
        res = resolve_pending_connections(db=db, limit=20)
        logger.info("Resolution pass %d: %s", i + 1, res)
        if res.get("checked", 0) == 0:
            break

    set_config("tijori.backfill_status", "complete")
    logger.info("✓ Backfill complete: %d symbols collected ok", total_ok)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        try:
            from db_manager import set_config
            set_config("tijori.backfill_status", "interrupted")
        except Exception:
            pass
        sys.exit(1)
