#!/usr/bin/env python3
"""
Get ACTUAL current market prices from Groww API.
"""

from fno_trader import _get_groww
from datetime import datetime, timedelta
import pytz

ist = pytz.timezone('Asia/Kolkata')
now = datetime.now(ist)

print(f"\n{'='*80}")
print(f"ACTUAL CURRENT MARKET PRICES - {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
print(f"{'='*80}\n")

top_symbols = ["TCS", "NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "WIPRO"]

groww = _get_groww()
if not groww:
    print("❌ Cannot connect to Groww API")
    exit(1)

print("Fetching real-time prices...\n")

for symbol in top_symbols:
    try:
        # Get latest candle
        now_time = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S")
        start_time = (datetime.now(ist) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        
        resp = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_time,
            end_time=now_time,
            interval_in_minutes=5,
        )
        
        if resp and resp.get('candles'):
            latest = resp['candles'][-1]
            close = latest.get('close', 0)
            high = latest.get('high', 0)
            low = latest.get('low', 0)
            
            print(f"{symbol:15} | Close: ₹{close:8.2f} | High: ₹{high:8.2f} | Low: ₹{low:8.2f}")
        else:
            print(f"{symbol:15} | No data available")
            
    except Exception as e:
        print(f"{symbol:15} | Error: {str(e)[:50]}")

print(f"\n{'='*80}\n")
