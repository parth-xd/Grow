#!/usr/bin/env python3
from db_manager import CandleDatabase, Candle
from sqlalchemy import func

db = CandleDatabase()
session = db.Session()

total_candles = session.query(func.count(Candle.id)).scalar()
unique_symbols = session.query(func.count(func.distinct(Candle.symbol))).scalar()

print(f"✓ Final database statistics:")
print(f"  Total unique symbols: {unique_symbols}")
print(f"  Total candles: {total_candles}")

session.close()
