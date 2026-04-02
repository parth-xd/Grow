#!/usr/bin/env python3
from db_manager import CandleDatabase, Candle
from datetime import datetime
from sqlalchemy import func

db = CandleDatabase()
s = db.Session()

# Get total candles
dates = s.query(func.count(Candle.id)).filter(Candle.symbol == "TCS").scalar()
print(f"Total TCS candles: {dates}")

# Check the earliest date
earliest = s.query(func.min(Candle.timestamp)).filter(Candle.symbol == "TCS").scalar()
if earliest:
    print(f"Earliest: {datetime.fromtimestamp(earliest)}")

# Check Jan 21
jan21 = s.query(Candle).filter(
    Candle.symbol == "TCS",
    Candle.timestamp >= int(datetime(2026, 1, 21, 0, 0, 0).timestamp()),
    Candle.timestamp < int(datetime(2026, 1, 22, 0, 0, 0).timestamp())
).count()
print(f"Candles on Jan 21, 2026: {jan21}")

# Check Mar 4
mar4 = s.query(Candle).filter(
    Candle.symbol == "TCS",
    Candle.timestamp >= int(datetime(2026, 3, 4, 0, 0, 0).timestamp()),
    Candle.timestamp < int(datetime(2026, 3, 5, 0, 0, 0).timestamp())
).count()
print(f"Candles on Mar 4, 2026: {mar4}")

# Check today
today_start = int(datetime(2026, 4, 2, 0, 0, 0).timestamp())
today = s.query(Candle).filter(
    Candle.symbol == "TCS",
    Candle.timestamp >= today_start
).count()
print(f"Candles on Apr 2, 2026: {today}")

s.close()
