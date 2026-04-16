#!/usr/bin/env python3
"""
Check candle data in database - simple version.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
from datetime import datetime, timedelta
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

from config import DB_URL
from db_manager import get_db, get_all_stocks

def check_db():
    """Check what candle dates we have."""
    db = get_db(DB_URL)
    if not db:
        logger.error("❌ Database connection failed")
        return
    
    stocks = get_all_stocks(db)
    if not stocks:
        logger.error("❌ No stocks in database")
        return
    
    symbols = sorted([s.symbol for s in stocks if s.is_active])
    logger.info(f"📊 Checking {len(symbols)} stocks...\n")
    
    for symbol in symbols:
        # Fresh connection for each query to avoid transaction issues
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        
        try:
            # Get date range using DATE cast directly (timestamp is a proper timestamp column)
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_candles,
                    MIN(DATE(timestamp)) as first_date,
                    MAX(DATE(timestamp)) as last_date
                FROM candles
                WHERE symbol = %s
            """, (symbol,))
            
            row = cursor.fetchone()
            if row and row[0] > 0:
                total, first, last = row
                if first and last:
                    days = (last - first).days + 1
                    logger.info(f"  {symbol}: {total} candles | {first} → {last} ({days} days)")
                else:
                    logger.info(f"  {symbol}: {total} candles but no dates?")
            else:
                logger.warning(f"  {symbol}: No data")
        
        except Exception as e:
            logger.error(f"  {symbol}: {e}")
        
        finally:
            cursor.close()
            conn.close()

if __name__ == "__main__":
    check_db()
