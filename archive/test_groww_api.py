#!/usr/bin/env python3
"""Test Groww API connectivity and data availability."""

from datetime import datetime, timedelta
from fno_trader import _get_groww

groww = _get_groww()
if not groww:
    print("✗ Groww API not available")
    exit(1)

print("✓ Groww API initialized")

# Try fetching data for RELIANCE (NSE CASH)
now = datetime.now()
start_time = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
end_time = now.strftime("%Y-%m-%d %H:%M:%S")

print(f"Fetching RELIANCE data from {start_time} to {end_time}")

try:
    resp = groww.get_historical_candle_data(
        trading_symbol="RELIANCE",
        exchange="NSE",
        segment="CASH",
        start_time=start_time,
        end_time=end_time,
        interval_in_minutes=60,
    )
    
    if resp:
        print(f"✓ API Response received")
        print(f"  Status: {resp.get('status')}")
        print(f"  Message: {resp.get('message')}")
        
        candles = resp.get("candles", [])
        print(f"  Candles count: {len(candles)}")
        if candles:
            print(f"  First candle: {candles[0]}")
            print(f"  Last candle: {candles[-1]}")
    else:
        print("✗ No response from API")
        print(f"Response: {resp}")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
