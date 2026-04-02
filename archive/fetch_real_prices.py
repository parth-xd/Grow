#!/usr/bin/env python3
"""
Fetch real historical price data from Groww API and store in database.
Uses the actual GROWW_API_KEY from .env
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Import after loading env
from price_fetcher import fetch_historical_prices, store_prices_in_db

DB_URL = os.getenv("DB_URL")
symbols = ["ASIANPAINT", "SUZLON", "GEMAROMA"]

print("🔄 Clearing old data and fetching real prices from Groww API...\n")

# Clear old data from DB
if DB_URL:
    import psycopg2
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stock_prices")
        conn.commit()
        print("✓ Cleared old corrupted data from database\n")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"⚠️  Could not clear database: {e}\n")

# Fetch real data for each stock
for symbol in symbols:
    print(f"📊 Fetching 5-year history for {symbol}...")
    
    # Fetch from real Groww API
    candles = fetch_historical_prices(symbol, years=5)
    
    if candles and len(candles) > 0:
        # Show data quality check
        prices = [c['close'] for c in candles]
        first_price = prices[0]
        last_price = prices[-1]
        min_price = min(prices)
        max_price = max(prices)
        avg_price = sum(prices) / len(prices)
        
        print(f"  ✓ Got {len(candles)} candles")
        print(f"    Price range: ₹{min_price:.2f} - ₹{max_price:.2f}")
        print(f"    Average: ₹{avg_price:.2f}")
        print(f"    Trend: {first_price:.2f} → {last_price:.2f} ({((last_price-first_price)/first_price*100):+.1f}%)")
        
        # Store in database
        if DB_URL:
            stored = store_prices_in_db(symbol, candles)
            print(f"    Stored: {stored} records in DB")
        print()
    else:
        print(f"  ✗ Failed to fetch data for {symbol}\n")

print("✅ Price data refresh complete!")
print("💡 Restart the server to see real analysis with accurate data")
