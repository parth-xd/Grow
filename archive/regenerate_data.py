#!/usr/bin/env python3
"""
Clear bad price data and regenerate clean sample data for all watchlist stocks.
"""

import os
from dotenv import load_dotenv
from price_fetcher import generate_sample_data, store_prices_in_db

load_dotenv()

DB_URL = os.getenv("DB_URL")
WATCHLIST = os.getenv("WATCHLIST", "").split(",")

# Clean watchlist from the main config
symbols = ["ASIANPAINT", "SUZLON", "GEMAROMA"]

print("🧹 Clearing bad price data...")
if DB_URL:
    import psycopg2
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stock_prices")
        conn.commit()
        print(f"✓ Cleared all stock_prices records")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"ℹ️  Database not available (using in-memory): {e}")
else:
    print("ℹ️  No database configured, will use in-memory data")

print("\n📊 Regenerating clean sample data...\n")

for symbol in symbols:
    print(f"Generating {symbol}...")
    candles = generate_sample_data(symbol, years=5)
    
    # Show sample of generated data
    if candles and len(candles) > 0:
        first = candles[0]
        last = candles[-1]
        print(f"  First candle: Close = ₹{first['close']:.2f}")
        print(f"  Last candle:  Close = ₹{last['close']:.2f}")
        print(f"  Total candles: {len(candles)}")
        
        # Store in DB
        if DB_URL:
            stored = store_prices_in_db(symbol, candles)
            print(f"  Stored: {stored} records")
    print()

print("✅ Done! Server will use fresh, clean price data.")
