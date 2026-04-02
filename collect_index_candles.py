"""
Collect historical hourly candle data for indices (NIFTY, BANKNIFTY, FINNIFTY)
and store in the database for XGBoost training.

Run: python collect_index_candles.py
"""

import logging
from datetime import datetime, timedelta
from db_manager import CandleDatabase, Candle

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def collect_index_candles():
    """Fetch index candles from Groww and store in database."""
    try:
        from groww_api import get_historical_candles
    except ImportError:
        logger.error("Groww API not available. Ensure groww_api.py is configured.")
        return

    indices = {
        "NIFTY": "index_nse_nifty_50",  # Groww index symbols
        "BANKNIFTY": "index_nse_bank_nifty",
        "FINNIFTY": "index_nse_nifty_financial",
    }

    db = CandleDatabase()
    session = db.Session()

    for symbol, groww_key in indices.items():
        try:
            logger.info(f"Collecting candles for {symbol}...")

            # Fetch recent candles (30 days of 5-min data = ~2250 candles)
            candles_data = get_historical_candles(
                groww_key,
                start_date=(datetime.now() - timedelta(days=30)).date(),
                end_date=datetime.now().date(),
                interval_minutes=5,
            )

            if not candles_data:
                logger.warning(f"No candle data retrieved for {symbol}")
                continue

            count = 0
            for c in candles_data:
                ts = c.get("timestamp")
                if not ts:
                    continue

                # Check if already exists
                existing = session.query(Candle).filter_by(
                    symbol=symbol,
                    timestamp=ts,
                ).first()

                if not existing:
                    candle = Candle(
                        symbol=symbol,
                        timestamp=ts,
                        open=float(c.get("open", 0)),
                        high=float(c.get("high", 0)),
                        low=float(c.get("low", 0)),
                        close=float(c.get("close", 0)),
                        volume=int(c.get("volume", 0)),
                    )
                    session.add(candle)
                    count += 1

            session.commit()
            logger.info(f"Added {count} new candles for {symbol}")

        except Exception as e:
            logger.error(f"Error collecting {symbol}: {e}")
            session.rollback()

    session.close()
    logger.info("Index candle collection complete.")


if __name__ == "__main__":
    collect_index_candles()
