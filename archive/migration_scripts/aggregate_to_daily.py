#!/usr/bin/env python3
"""
Aggregate 5-minute candles into daily prices for watchlist display.
Fills the stock_prices table from candles table data.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import execute_batch

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

from config import DB_URL
from db_manager import get_db, get_all_stocks

def aggregate_candles_to_daily():
    """Aggregate 5-minute candles into daily OHLCV prices."""
    db = get_db(DB_URL)
    if not db:
        logger.error("❌ Database connection failed")
        return
    
    stocks = get_all_stocks(db)
    if not stocks:
        logger.error("❌ No stocks in database")
        return
    
    symbols = [s.symbol for s in stocks if s.is_active]
    logger.info(f"📊 Aggregating candles to daily prices for {len(symbols)} stocks...\n")
    
    total_inserted = 0
    
    for symbol in sorted(symbols):
        # Fresh connection for each symbol
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        
        try:
            # Get all candles, aggregate by day
            cursor.execute("""
                SELECT 
                    DATE(timestamp) as trade_date,
                    MIN(open) as open_price,
                    MAX(high) as high_price,
                    MIN(low) as low_price,
                    (array_agg(close ORDER BY timestamp DESC))[1] as close_price,
                    SUM(CAST(volume AS BIGINT)) as total_volume
                FROM candles
                WHERE symbol = %s
                GROUP BY DATE(timestamp)
                ORDER BY DATE(timestamp) ASC
            """, (symbol,))
            
            rows = cursor.fetchall()
            if not rows:
                logger.warning(f"  {symbol}: No candles found")
                cursor.close()
                conn.close()
                continue
            
            # Insert daily prices (upsert)
            insert_rows = []
            for row in rows:
                trade_date, open_p, high_p, low_p, close_p, vol = row
                insert_rows.append((
                    symbol,
                    trade_date,
                    float(open_p) if open_p else None,
                    float(high_p) if high_p else None,
                    float(low_p) if low_p else None,
                    float(close_p) if close_p else None,
                    int(vol) if vol else 0,
                ))
            
            if insert_rows:
                insert_query = """
                    INSERT INTO stock_prices (symbol, date, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, date) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """
                
                execute_batch(cursor, insert_query, insert_rows, page_size=1000)
                conn.commit()
                
                inserted = len(insert_rows)
                total_inserted += inserted
                
                # Get date range
                first_date = min(r[1] for r in insert_rows)
                last_date = max(r[1] for r in insert_rows)
                logger.info(f"  {symbol}: Aggregated {inserted} days ({first_date} → {last_date})")
            
        except Exception as e:
            logger.error(f"  {symbol}: {e}")
        
        finally:
            cursor.close()
            conn.close()
    
    logger.info(f"\n✅ Aggregation complete! Total daily prices: {total_inserted}")

if __name__ == "__main__":
    aggregate_candles_to_daily()
