"""Find correct trading symbols for BANKNIFTY/FINNIFTY."""
import os, time
from growwapi import GrowwAPI

token = os.getenv('GROWW_ACCESS_TOKEN')
g = GrowwAPI(token)

# Try different symbol variations for BANKNIFTY
candidates = [
    'NIFTY BANK', 'BANKNIFTY', 'NIFTYBANK', 'BANK NIFTY',
    'NIFTY FIN SERVICE', 'FINNIFTY', 'NIFTYFIN', 'NIFTY FINANCIAL',
    'NIFTY IT', 'NIFTYIT', 'NIFTY ENERGY', 'NIFTY MIDCAP',
    'SENSEX', 'BSE SENSEX',
]

for sym in candidates:
    try:
        result = g.get_historical_candle_data(
            trading_symbol=sym, exchange='NSE', segment='CASH',
            start_time='2026-03-25 09:15:00',
            end_time='2026-03-28 15:30:00',
            interval_in_minutes=1440,
        )
        candles = result.get('candles', [])
        print(f"  '{sym}': {len(candles)} candles {'OK' if candles else '(empty)'}")
    except Exception as e:
        print(f"  '{sym}': ERROR - {e}")
    time.sleep(0.3)

# Also try BSE exchange for SENSEX
print("\n=== BSE ===")
for sym in ['SENSEX', 'BSE SENSEX']:
    try:
        result = g.get_historical_candle_data(
            trading_symbol=sym, exchange='BSE', segment='CASH',
            start_time='2026-03-25 09:15:00',
            end_time='2026-03-28 15:30:00',
            interval_in_minutes=1440,
        )
        candles = result.get('candles', [])
        print(f"  BSE '{sym}': {len(candles)} candles")
    except Exception as e:
        print(f"  BSE '{sym}': ERROR - {e}")
    time.sleep(0.3)

# Also check what instrument search returns
print("\n=== Instrument Search ===")
try:
    inst = g.get_instrument_by_exchange_and_trading_symbol('NSE', 'NIFTY')
    print(f"  NIFTY instrument: {inst}")
except Exception as e:
    print(f"  ERROR: {e}")
try:
    inst = g.get_instrument_by_exchange_and_trading_symbol('NSE', 'BANKNIFTY')
    print(f"  BANKNIFTY instrument: {inst}")
except Exception as e:
    print(f"  ERROR: {e}")

# Check V1 API interval limits properly
print("\n=== V1 API INTERVAL LIMITS ===")
tests = [
    ('5min 15d',   'RELIANCE', '2026-03-15 09:15:00', '2026-03-30 15:30:00', 5),
    ('5min 30d',   'RELIANCE', '2026-03-01 09:15:00', '2026-03-30 15:30:00', 5),
    ('15min 30d',  'RELIANCE', '2026-03-01 09:15:00', '2026-03-30 15:30:00', 15),
    ('15min 90d',  'RELIANCE', '2026-01-01 09:15:00', '2026-03-30 15:30:00', 15),
    ('1hr 90d',    'RELIANCE', '2026-01-01 09:15:00', '2026-03-30 15:30:00', 60),
    ('1hr 180d',   'RELIANCE', '2025-10-01 09:15:00', '2026-03-30 15:30:00', 60),
    ('daily 1yr',  'RELIANCE', '2025-04-01 09:15:00', '2026-03-30 15:30:00', 1440),
    ('daily 6yr',  'RELIANCE', '2020-01-01 09:15:00', '2026-03-30 15:30:00', 1440),
]
for label, sym, st, en, iv in tests:
    try:
        result = g.get_historical_candle_data(
            trading_symbol=sym, exchange='NSE', segment='CASH',
            start_time=st, end_time=en, interval_in_minutes=iv,
        )
        candles = result.get('candles', [])
        print(f"  {label}: {len(candles)} candles")
    except Exception as e:
        err = str(e)[:60]
        print(f"  {label}: ERROR - {err}")
    time.sleep(0.3)
