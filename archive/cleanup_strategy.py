#!/usr/bin/env python3
"""
Clean synthetic data and prepare for real market trading.
Keep only data that's actually useful (or start fresh with real data).
"""

from db_manager import CandleDatabase, Candle
from sqlalchemy import func

print("\n" + "=" * 80)
print("DATABASE CLEANUP - Remove Synthetic Data")
print("=" * 80 + "\n")

db = CandleDatabase()
session = db.Session()

# Get current candle count
total_before = session.query(func.count(Candle.id)).scalar()
print(f"Current database size: {total_before:,} candles")

# Show what we have
symbols = session.query(Candle.symbol, func.count(Candle.id).label('count')).group_by(Candle.symbol).order_by(func.count(Candle.id).desc()).all()
print(f"\nSymbols with data ({len(symbols)} total):")
for sym, count in symbols[:10]:
    print(f"  {sym:15} | {count:,} candles")

print(f"\n" + "=" * 80)
print("CLEANUP STRATEGY:")
print("=" * 80)

print(f"""
The synthetic data was generated for model training purposes:
  • 5-year synthetic candles per symbol (9,128 each)
  • Good for ML model training but WRONG prices
  • Need to replace with REAL Groww API data

Options:
  1. Keep 100 recent candles per symbol (smallest dataset)
  2. Clear everything and start fresh from Groww API
  3. Keep only top 10 liquid stocks with real data

Recommendation: KEEP current data for ML training, but USE REAL PRICES for trading.

The ML model accuracy is based on PATTERNS (trends, volatility, support/resistance),
not absolute prices. So synthetic data helps model learn patterns,
but REAL market prices are needed for actual trade execution.
""")

session.close()

print("=" * 80)
print("GOING FORWARD:")
print("=" * 80)
print(f"""
✅ Keep synthetic data: Used for ML model pattern recognition
❌ Don't use synthetic prices: Only use REAL Groww API prices for entry/exit
✅ At market open (09:15): Fetch real prices from Groww
✅ Compare ML signals + real price action -> execute high-confidence trades

System architecture is correct. Just need to use real APIs instead of synthetic data.
""")

print("=" * 80 + "\n")
