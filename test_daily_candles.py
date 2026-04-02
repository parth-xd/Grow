#!/usr/bin/env python3
from growwapi import GrowwAPI
from datetime import datetime, timedelta
import os

token = ""
with open(".env") as f:
    for line in f:
        if "GROWW_ACCESS_TOKEN=" in line:
            token = line.split("=")[1].strip()
            break

g = GrowwAPI(token)

# Try fetching 30 days of 1-day candles
now = datetime.now()
st = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
et = now.strftime("%Y-%m-%d %H:%M:%S")

print(f"Fetching daily candles from {st} to {et}")

try:
    resp = g.get_historical_candle_data(
        trading_symbol="TCS",
        exchange="NSE",
        segment="CASH",
        start_time=st,
        end_time=et,
        interval_in_minutes=1440  # 1440 mins = 1 day
    )
    candles = resp.get("candles", [])
    print(f"✓ Got {len(candles)} daily candles")
    if len(candles) >= 2:
        print(f"  First: {candles[0]}")
        print(f"  Last: {candles[-1]}")
except Exception as e:
    print(f"✗ Error: {e}")
