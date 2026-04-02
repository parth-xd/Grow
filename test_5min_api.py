#!/usr/bin/env python3
from fno_trader import _get_groww
from datetime import datetime, timedelta

groww = _get_groww()
if not groww:
    print("No Groww API available")
else:
    now = datetime.now()
    start_time = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    end_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"Testing API from {start_time} to {end_time}")
    
    # Try a symbol that IS working
    try:
        print("\n[WORKING] Testing TCS:")
        resp = groww.get_historical_candle_data(
            trading_symbol="TCS", exchange="NSE", segment="CASH",
            start_time=start_time, end_time=end_time, interval_in_minutes=5
        )
        candles = resp.get("candles", []) if resp else []
        print(f"  TCS: {len(candles)} candles")
    except Exception as e:
        print(f"  TCS ERROR: {e}")
    
    # Try a symbol that is NOT working
    try:
        print("\n[MISSING] Testing NIFTY:")
        resp = groww.get_historical_candle_data(
            trading_symbol="NIFTY", exchange="NSE", segment="CASH",
            start_time=start_time, end_time=end_time, interval_in_minutes=5
        )
        candles = resp.get("candles", []) if resp else []
        print(f"  NIFTY: {len(candles)} candles")
    except Exception as e:
        print(f"  NIFTY ERROR: {e}")

    # Try another missing one  
    try:
        print("\n[MISSING] Testing AXISBANK:")
        resp = groww.get_historical_candle_data(
            trading_symbol="AXISBANK", exchange="NSE", segment="CASH",
            start_time=start_time, end_time=end_time, interval_in_minutes=5
        )
        candles = resp.get("candles", []) if resp else []
        print(f"  AXISBANK: {len(candles)} candles")
    except Exception as e:
        print(f"  AXISBANK ERROR: {e}")

    # Try another working one
    try:
        print("\n[MISSING] Testing INFY:")
        resp = groww.get_historical_candle_data(
            trading_symbol="INFY", exchange="NSE", segment="CASH",
            start_time=start_time, end_time=end_time, interval_in_minutes=5
        )
        candles = resp.get("candles", []) if resp else []
        print(f"  INFY: {len(candles)} candles")
    except Exception as e:
        print(f"  INFY ERROR: {e}")
