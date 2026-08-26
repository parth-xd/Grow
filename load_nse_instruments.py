"""
Load the full NSE main-board equity directory from Groww's instrument master
into `nse_instruments`, for search/autocomplete only.

Read-only against Groww (get_all_instruments — no orders, no account data).
Idempotent upsert, safe to re-run to refresh the list (e.g. new listings).
"""

import logging
import os

from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import insert

load_dotenv()
logger = logging.getLogger(__name__)


def load_nse_instruments():
    from growwapi import GrowwAPI
    from db_manager import get_db, NSEInstrument

    token = os.getenv("GROWW_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GROWW_ACCESS_TOKEN is not set. Configure it in .env")

    groww = GrowwAPI(token)
    df = groww.get_all_instruments()
    eq = df[(df["exchange"] == "NSE") & (df["segment"] == "CASH") & (df["series"] == "EQ")]

    rows = [
        {"symbol": r.trading_symbol, "name": r.name, "isin": r.isin, "series": r.series}
        for r in eq.itertuples()
    ]
    logger.info("Fetched %d NSE main-board equities from Groww", len(rows))

    db = get_db()
    db.init_db()  # creates nse_instruments if it doesn't exist yet; no-op otherwise
    session = db.Session()
    try:
        stmt = insert(NSEInstrument).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol"],
            set_={"name": stmt.excluded.name, "isin": stmt.excluded.isin, "series": stmt.excluded.series},
        )
        session.execute(stmt)
        session.commit()
        logger.info("✓ Upserted %d rows into nse_instruments", len(rows))
    finally:
        session.close()

    return len(rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    n = load_nse_instruments()
    print(f"✓ Loaded {n} NSE main-board equities into nse_instruments")
