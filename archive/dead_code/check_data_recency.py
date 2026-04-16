#!/usr/bin/env python3
from db_manager import CandleDatabase, Candle
from datetime import datetime, timedelta
from sqlalchemy import func

db = CandleDatabase()
s = db.Session()

# Check what data exists for TCS
tcs_candles = s.query(Candle).filter(Candle.symbol == "TCS").order_by(Candle.timestamp.desc()).limit(10).all()

print("Latest TCS candles in DB:")
for c in tcs_candles:
    ts = datetime.fromtimestamp(c.timestamp)
    print(f"  {ts} | O:{c.open} H:{c.high} L:{c.low} C:{c.close}")

earliest = s.query(func.min(Candle.timestamp)).filter(Candle.symbol == 'TCS').scalar()
latest = s.query(func.max(Candle.timestamp)).filter(Candle.symbol == 'TCS').scalar()

if earliest:
    print(f"\nEarliest TCS candle: {datetime.fromtimestamp(earliest)}")
if latest:
    print(f"Latest TCS candle: {datetime.fromtimestamp(latest)}")

# Check today's data
today = datetime.now().date()
today_start = int(datetime.combine(today, datetime.min.time()).timestamp())
today_candles = s.query(Candle).filter(
    Candle.symbol == "TCS",
    Candle.timestamp >= today_start
).count()

print(f"\nCandles for today (2026-04-02): {today_candles}")

# Check historical range being used for predictions
print(f"\nPREDICTION LOOKBACK = 30 days")
lookback_start = datetime.now() - timedelta(days=30)
lookback_timestamp = int(lookback_start.timestamp())
lookback_candles = s.query(Candle).filter(
    Candle.symbol == "TCS",
    Candle.timestamp >= lookback_timestamp
).count()
print(f"Candles in last 30 days: {lookback_candles}")

s.close()
EOF
