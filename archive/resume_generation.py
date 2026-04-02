#!/usr/bin/env python3
"""Resume 5-min candle generation for symbols that are still incomplete."""
import logging
from sqlalchemy import text
from db_manager import CandleDatabase
from generate_5year_optimized import generate_symbol_data_fast, generate_trading_dates

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

EXPECTED_PER_SYMBOL = 97_800  # approx 5yr × 75 candles/day

def main():
    db = CandleDatabase()
    trading_dates = generate_trading_dates(years=5)
    expected = len(trading_dates) * 75
    logger.info(f"Trading dates: {len(trading_dates)}, expected candles/symbol: {expected:,}")

    # Find incomplete symbols
    with db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT symbol, count(*) as cnt FROM candles GROUP BY symbol HAVING count(*) < :exp ORDER BY symbol"
        ), {"exp": expected}).fetchall()

    incomplete = [(r[0], r[1]) for r in rows]
    logger.info(f"Found {len(incomplete)} incomplete symbols to regenerate")

    insert_sql = text(
        "INSERT INTO candles (symbol, timestamp, open, high, low, close, volume) "
        "VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume) "
        "ON CONFLICT (symbol, timestamp) DO UPDATE SET "
        "open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
        "close=EXCLUDED.close, volume=EXCLUDED.volume"
    )

    total = 0
    for idx, (symbol, current_count) in enumerate(incomplete, 1):
        try:
            rows = generate_symbol_data_fast(symbol, trading_dates)
            with db.engine.begin() as conn:
                conn.execute(text("DELETE FROM candles WHERE symbol = :sym"), {"sym": symbol})
                batch_size = 5000
                for i in range(0, len(rows), batch_size):
                    conn.execute(insert_sql, rows[i:i + batch_size])
            total += len(rows)
            logger.info(f"[{idx}/{len(incomplete)}] {symbol}: {current_count:,} → {len(rows):,} candles (total: {total:,})")
        except Exception as e:
            logger.error(f"[{idx}/{len(incomplete)}] {symbol}: FAILED — {e}")

    logger.info(f"Done! Generated {total:,} candles for {len(incomplete)} symbols")

if __name__ == "__main__":
    main()
