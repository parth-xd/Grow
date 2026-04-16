#!/usr/bin/env python3
"""
Check what candle dates we have and what's missing in the watchlist.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

from config import DB_URL
from db_manager import get_db, get_all_stocks

def check_missing_dates():
    """Check for missing dates in candle data."""
    db = get_db(DB_URL)
    if not db:
        logger.error("❌ Database connection failed")
        return
    
    stocks = get_all_stocks(db)
    symbols = [s.symbol for s in stocks if s.is_active]
    
    logger.info(f"📊 Checking {len(symbols)} watchlist stocks for missing dates...\n")
    
    conn = psycopg2.connect(DB_URL)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    for symbol in sorted(symbols):
        try:
            # Get date range of candles we have (timestamp is unix integer)
            cursor.execute("""
                SELECT 
                    MIN(to_timestamp(timestamp)::date) as first_date,
                    MAX(to_timestamp(timestamp)::date) as last_date,
                    COUNT(DISTINCT (to_timestamp(timestamp)::date)) as unique_dates,
                    COUNT(*) as total_candles
                FROM candles
                WHERE symbol = %s
            """, (symbol,))
            
            result = cursor.fetchone()
            if not result or not result['last_date']:
                logger.warning(f"  {symbol}: No data found")
                continue
            
            first_date = result['first_date']
            last_date = result['last_date']
            unique_dates = result['unique_dates']
            total_candles = result['total_candles']
            
            # Calculate expected dates (trading days only: Mon-Fri)
            current = first_date
            expected_dates = 0
            while current <= last_date:
                # 0=Mon, 1=Tue, ..., 4=Fri, 5=Sat, 6=Sun
                if current.weekday() < 5:  # Monday to Friday
                    expected_dates += 1
                current += timedelta(days=1)
            
            missing_dates = expected_dates - unique_dates
            
            logger.info(f"  {symbol}:")
            logger.info(f"    Range: {first_date} → {last_date}")
            logger.info(f"    Candles: {total_candles} total, {unique_dates}/{expected_dates} trading days")
            
            if missing_dates > 0:
                logger.warning(f"    ⚠️  MISSING: {missing_dates} trading days")
                
                # Find actual gap dates in Python instead of SQL
                cursor.execute("""
                    SELECT DISTINCT (to_timestamp(timestamp)::date) as candle_date
                    FROM candles
                    WHERE symbol = %s
                    ORDER BY candle_date
                """, (symbol,))
                
                candle_dates = {row['candle_date'] for row in cursor.fetchall()}
                
                # Find missing trading days
                missing = []
                current = first_date
                while current <= last_date and len(missing) < 5:
                    if current.weekday() < 5 and current not in candle_dates:
                        missing.append(current)
                    current += timedelta(days=1)
                
                if missing:
                    dates_str = ', '.join([str(d) for d in missing])
                    logger.warning(f"       First missing dates: {dates_str}")
            else:
                logger.info(f"    ✅ All trading days covered!")
            
            logger.info("")
            
        except Exception as e:
            logger.error(f"  {symbol}: Error - {e}")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    check_missing_dates()
