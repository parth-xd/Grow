#!/usr/bin/env python3
"""
Fetch 5-year historical price data from Google Finance (via yfinance)
and store in PostgreSQL database.
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_batch
import yfinance as yf
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DB_URL")
symbols = ["ASIANPAINT", "SUZLON", "GEMAROMA"]

# Map symbols to Yahoo Finance tickers (NSE stocks)
NSE_TICKERS = {
    "ASIANPAINT": "ASIANPAINT.NS",
    "SUZLON": "SUZLON.NS", 
    "GEMAROMA": "GEMAROMA.NS"
}

def fetch_google_prices(symbol, years=5):
    """
    Fetch historical prices from Google Finance via yfinance.
    
    Args:
        symbol: Stock symbol (e.g., 'ASIANPAINT')
        years: How many years back
        
    Returns:
        List of candle dicts with timestamp, open, high, low, close, volume
    """
    ticker = NSE_TICKERS.get(symbol, f"{symbol}.NS")
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365 * years)
    
    logger.info(f"📊 Fetching {symbol} from Google Finance ({start_date.date()} to {end_date.date()})...")
    
    try:
        # Fetch data from Google Finance
        data = yf.download(ticker, start=start_date.date(), end=end_date.date(), progress=False)
        
        if data is None or len(data) == 0:
            logger.warning(f"⚠️  No data for {symbol}")
            return []
        
        # Convert to candle format
        candles = []
        for idx, row in data.iterrows():
            candle = {
                "timestamp": int(idx.timestamp()),
                "open": float(row['Open']),
                "high": float(row['High']),
                "low": float(row['Low']),
                "close": float(row['Close']),
                "volume": int(row['Volume']) if 'Volume' in row else 0
            }
            candles.append(candle)
        
        logger.info(f"  ✓ Got {len(candles)} daily candles")
        return candles
        
    except Exception as e:
        logger.error(f"  ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return []


def store_prices_in_db(symbol, candles):
    """Store prices in PostgreSQL."""
    if not candles:
        return 0
    
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        
        # Prepare data
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
        
        # Batch insert
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
        
        execute_batch(cursor, insert_query, rows, page_size=1000)
        conn.commit()
        
        inserted = len(rows)
        logger.info(f"    Stored: {inserted} records in DB")
        
        cursor.close()
        conn.close()
        
        return inserted
        
    except Exception as e:
        logger.error(f"    Database error: {e}")
        return 0


if __name__ == "__main__":
    print("🔄 Fetching 5-year prices from Google Finance...\n")
    
    # Clear old data
    if DB_URL:
        try:
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stock_prices")
            conn.commit()
            logger.info("✓ Cleared old data from database\n")
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning(f"⚠️  Could not clear database: {e}\n")
    
    # Fetch and store for each symbol
    for symbol in symbols:
        candles = fetch_google_prices(symbol, years=5)
        
        if candles and len(candles) > 0:
            # Show data quality
            prices = [c['close'] for c in candles]
            first = prices[0]
            last = prices[-1]
            min_p = min(prices)
            max_p = max(prices)
            avg_p = sum(prices) / len(prices)
            
            pct_change = ((last - first) / first * 100)
            
            print(f"  ✓ Got {len(candles)} candles")
            print(f"    Price range: ₹{min_p:.2f} - ₹{max_p:.2f}")
            print(f"    Average: ₹{avg_p:.2f}")
            print(f"    Trend: {first:.2f} → {last:.2f} ({pct_change:+.1f}%)")
            
            # Store
            if DB_URL:
                store_prices_in_db(symbol, candles)
            print()
        else:
            logger.info(f"  ✗ No data for {symbol}\n")
    
    print("✅ Done! Prices loaded from Google Finance")
