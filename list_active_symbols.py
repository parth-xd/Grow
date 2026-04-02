#!/usr/bin/env python3
from db_manager import CandleDatabase, Candle
from datetime import datetime

db = CandleDatabase()
s = db.Session()

# Get all unique dates in DB
dates = s.query(Candle.timestamp).distinct().order_by(Candle.timestamp.desc()).limit(1).all()
if not dates:
    print("No data in DB")
    s.close()
    exit(0)

latest_date = dates[0][0].date()

# Get symbols with data from today
today_syms = sorted([r[0] for r in s.query(Candle.symbol).distinct().filter(
    Candle.timestamp >= datetime.combine(latest_date, datetime.min.time())
).all()])

print(f"Symbols actively providing 5-min data TODAY ({len(today_syms)}):")
print(", ".join(today_syms))

s.close()
