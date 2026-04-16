#!/usr/bin/env python3
"""
Backfill missing candles for all watchlist stocks.
Fetches from API only for dates where we have gaps.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

from config import DB_URL, DEFAULT_EXCHANGE, DEFAULT_SEGMENT, CANDLE_INTERVAL_MINUTES
from db_manager import get_db, get_all_stocks
from growwapi import GrowwAPI
import os as _os

def backfill_all_smart():
    """Backfill missing candles by fetching only the gaps."""
    db = get_db(DB_URL)
    if not db:
        logger.error("❌ Database connection failed")
        return
    
    stocks = get_all_stocks(db)
    if not stocks:
        logger.error("❌ No stocks found in database")
        return
    
    symbols = [s.symbol for s in stocks if s.is_active]
    logger.info(f"🔄 Smart backfill for {len(symbols)} stocks...\n")
    
    # Get Groww API token
    token = _os.getenv("GROWW_ACCESS_TOKEN")
    if not token:
        logger.error("❌ GROWW_ACCESS_TOKEN not set")
        return
    
    groww = GrowwAPI(token)
    total_synced = 0
    failed = []
    
    for i, symbol in enumerate(symbols, 1):
        try:
            # Get latest timestamp in DB
            latest_ts = db.get_latest_timestamp(symbol)
            
            if latest_ts:
                last_date = latest_ts.date() if hasattr(latest_ts, 'date') else datetime.fromtimestamp(latest_ts).date()
                days_stale = (datetime.utcnow().date() - last_date).days
                logger.info(f"  [{i}/{len(symbols)}] {symbol}")
                logger.info(f"      Last candle: {last_date} ({days_stale} days ago)")
                
                if days_stale == 0:
                    logger.info(f"      ↷ Current")
                    continue
                
                # Fetch from day after last candle to today
                start_date = last_date + timedelta(days=1)
                end_date = datetime.utcnow().date()
                
                # Skip weekends when searching for start date
                while start_date.weekday() >= 5:  # 5=Sat, 6=Sun
                    start_date += timedelta(days=1)
                
                if start_date > end_date:
                    logger.info(f"      ✅ No trading days missed")
                    continue
                
                logger.info(f"      Fetching from {start_date} to {end_date}...")
                
                # Format times for API
                start_time = start_date.strftime("%Y-%m-%d 09:15:00")
                end_time = end_date.strftime("%Y-%m-%d 15:30:00")
                
                # Fetch from API
                try:
                    resp = groww.get_historical_candle_data(
                        trading_symbol=symbol,
                        exchange=DEFAULT_EXCHANGE,
                        segment=DEFAULT_SEGMENT,
                        start_time=start_time,
                        end_time=end_time,
                        interval_in_minutes=CANDLE_INTERVAL_MINUTES,
                    )
                    
                    candles = resp.get("candles", [])
                    if candles:
                        # Format and insert into DB
                        candles_formatted = [
                            {
                                "timestamp": int(c[0]),
                                "open": float(c[1]),
                                "high": float(c[2]),
                                "low": float(c[3]),
                                "close": float(c[4]),
                                "volume": float(c[5]),
                            }
                            for c in candles
                        ]
                        
                        db.insert_candles(symbol, candles_formatted)
                        total_synced += len(candles)
                        logger.info(f"      ✅ Synced {len(candles)} candles")
                    else:
                        logger.warning(f"      ⚠️  No candles returned by API")
                
                except Exception as e:
                    failed.append((symbol, str(e)))
                    logger.error(f"      ❌ API Error: {e}")
            
            else:
                # No data at all - fetch last 365 days
                logger.info(f"  [{i}/{len(symbols)}] {symbol}")
                logger.info(f"      No historical data - fetching last 365 days...")
                
                start_date = datetime.utcnow().date() - timedelta(days=365)
                end_date = datetime.utcnow().date()
                start_time = start_date.strftime("%Y-%m-%d 09:15:00")
                end_time = end_date.strftime("%Y-%m-%d 15:30:00")
                
                try:
                    resp = groww.get_historical_candle_data(
                        trading_symbol=symbol,
                        exchange=DEFAULT_EXCHANGE,
                        segment=DEFAULT_SEGMENT,
                        start_time=start_time,
                        end_time=end_time,
                        interval_in_minutes=CANDLE_INTERVAL_MINUTES,
                    )
                    
                    candles = resp.get("candles", [])
                    if candles:
                        candles_formatted = [
                            {
                                "timestamp": int(c[0]),
                                "open": float(c[1]),
                                "high": float(c[2]),
                                "low": float(c[3]),
                                "close": float(c[4]),
                                "volume": float(c[5]),
                            }
                            for c in candles
                        ]
                        db.insert_candles(symbol, candles_formatted)
                        total_synced += len(candles)
                        logger.info(f"      ✅ Synced {len(candles)} candles")
                    else:
                        logger.warning(f"      ⚠️  No candles returned by API")
                
                except Exception as e:
                    failed.append((symbol, str(e)))
                    logger.error(f"      ❌ API Error: {e}")
        
        except Exception as e:
            failed.append((symbol, str(e)))
            logger.error(f"  [{i}/{len(symbols)}] {symbol}: Error - {e}")
        
        # Small delay to avoid rate limiting
        import time
        time.sleep(0.5)
    
    logger.info(f"\n📊 Backfill complete!")
    logger.info(f"   Total candles synced: {total_synced}")
    logger.info(f"   Failed: {len(failed)}/{len(symbols)}")
    if failed:
        logger.warning("   Failed symbols:")
        for sym, err in failed:
            logger.warning(f"     - {sym}: {err}")

if __name__ == "__main__":
    backfill_all_smart()

