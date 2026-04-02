#!/usr/bin/env python3
from fno_trader import _get_groww
from datetime import datetime, timedelta

g = _get_groww()
now = datetime.now()
st = (now - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
et = now.strftime('%Y-%m-%d %H:%M:%S')

missing_syms = ['AXISBANK', 'KOTAKBANK', 'HCLTECH', 'MARUTI', 'TITAN', 'NESTLEIND', 'CIPLA']
working_syms = ['TCS', 'INFY', 'RELIANCE', 'SBIN']

print(f"Testing symbols from {st} to {et}")
print()

for sym in working_syms[:2] + missing_syms[:3]:
    try:
        resp = g.get_historical_candle_data(
            trading_symbol=sym, exchange='NSE', segment='CASH',
            start_time=st, end_time=et, interval_in_minutes=5
        )
        c = resp.get('candles', []) if resp else []
        status = '✓' if len(c) > 0 else '✗'
        print(f"{status} {sym:15} {len(c):3} candles")
    except Exception as e:
        print(f"✗ {sym:15} ERROR: {str(e)[:60]}")
