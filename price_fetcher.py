"""
Price data fetcher — Download 5 years of historical OHLCV data from Groww API
and store in PostgreSQL for backtesting and analysis.
"""

import logging
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_batch

load_dotenv()
logger = logging.getLogger(__name__)

GROWW_ACCESS_TOKEN = os.getenv("GROWW_ACCESS_TOKEN")
DB_URL = os.getenv("DB_URL")

# Use the same GrowwAPI client that works for other endpoints
def get_groww_client():
    """Get authenticated Groww API client."""
    from growwapi import GrowwAPI
    if not GROWW_ACCESS_TOKEN:
        raise RuntimeError("GROWW_ACCESS_TOKEN is not set. Configure it in .env")
    return GrowwAPI(GROWW_ACCESS_TOKEN)


def get_segment():
    """Get the CASH segment constant from GrowwAPI."""
    from growwapi import GrowwAPI
    return GrowwAPI.SEGMENT_CASH


def fetch_historical_prices(symbol, years=5):
    """
    Fetch historical OHLCV data from Groww API using the working GrowwAPI client.
    
    Args:
        symbol: Stock symbol (e.g., 'ASIANPAINT')
        years: How many years back to fetch
        
    Returns:
        List of price candles with timestamp, open, high, low, close, volume
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years)
    
    logger.info(f"Fetching {symbol} prices from {start_date.date()} to {end_date.date()}")
    
    try:
        groww = get_groww_client()
        
        # Use the same method that works for live data
        end_time = end_date.strftime("%Y-%m-%d %H:%M:%S")
        start_time = start_date.strftime("%Y-%m-%d %H:%M:%S")
        
        # Fetch weekly candles for 5+ years (1440-min only supports ~3 years)
        # Weekly interval: 10080 minutes = 7 days, supports full history
        response = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange="NSE",
            segment=get_segment(),  # Use SEGMENT_CASH constant for equity stocks
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=10080,  # Weekly candles for 5+ year history
        )
        
        candles = response.get("candles", []) if isinstance(response, dict) else response
        
        if not candles or len(candles) == 0:
            logger.warning(f"⚠️  No candles fetched for {symbol}")
            return []
        
        # Convert array format [timestamp, open, high, low, close, volume] to dict format
        converted_candles = []
        for candle in candles:
            converted_candles.append({
                "timestamp": candle[0],
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5] if len(candle) > 5 else 0
            })
        
        logger.info(f"✓ Fetched {len(converted_candles)} candles for {symbol}")
        return converted_candles
        
    except Exception as e:
        logger.error(f"✗ Failed to fetch {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return []


def store_prices_in_db(symbol, candles):
    """
    Store historical prices in PostgreSQL.
    
    Args:
        symbol: Stock symbol
        candles: List of price candles
    """
    if not candles:
        logger.warning(f"No candles to store for {symbol}")
        return 0
    
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        
        # Prepare data for batch insert
        rows = []
        for candle in candles:
            date = datetime.fromtimestamp(candle["timestamp"]).date()
            row = (
                symbol,
                date,
                candle.get("open"),
                candle.get("high"),
                candle.get("low"),
                candle.get("close"),
                candle.get("volume"),
            )
            rows.append(row)
        
        # Batch insert (upsert: insert or ignore if duplicate)
        insert_query = """
            INSERT INTO stock_prices (symbol, date, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, date) DO NOTHING
        """
        
        execute_batch(cursor, insert_query, rows, page_size=1000)
        conn.commit()
        
        inserted = cursor.rowcount
        logger.info(f"✓ Stored {inserted} price records for {symbol}")
        
        cursor.close()
        conn.close()
        
        return inserted
        
    except Exception as e:
        logger.error(f"✗ Database error: {e}")
        return 0


def fetch_and_store_all_stocks(symbols=None):
    """
    Fetch and store prices for multiple stocks.
    
    Args:
        symbols: List of stock symbols (if None, uses config watchlist)
    """
    if symbols is None:
        watchlist_str = os.getenv("WATCHLIST", "")
        symbols = [s.strip() for s in watchlist_str.split(",")]
    
    logger.info(f"Fetching prices for {len(symbols)} stocks...")
    
    total_stored = 0
    for symbol in symbols:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing {symbol}...")
        
        # Fetch from API
        candles = fetch_historical_prices(symbol, years=5)
        
        # Store in DB
        stored = store_prices_in_db(symbol, candles)
        total_stored += stored
    
    logger.info(f"\n{'='*50}")
    logger.info(f"✓ DONE! Stored {total_stored} total price records")
    
    return total_stored


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Fetch real data from Groww API for portfolio symbols
    portfolio_symbols = ["ASIANPAINT", "SUZLON", "GEMAROMA"]
    total_stored = 0
    
    for symbol in portfolio_symbols:
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing {symbol}...")
        candles = fetch_historical_prices(symbol, years=5)
        stored = store_prices_in_db(symbol, candles)
        total_stored += stored
    
    logger.info(f"\n✅ Total stored: {total_stored} records")
    
    # Verify data was stored
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, COUNT(*) FROM stock_prices GROUP BY symbol;")
        results = cursor.fetchall()
        
        logger.info("\n📊 Price data summary:")
        for symbol, count in results:
            logger.info(f"  {symbol}: {count} candles")
        
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Error reading data: {e}")
