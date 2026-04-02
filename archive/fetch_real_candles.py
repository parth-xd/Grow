"""
Replace ALL synthetic candles with REAL Groww API data.
Fetches at multiple intervals to maximize history:
  - 5-min candles: last 15 days
  - 15-min candles: 15-30 days ago
  - 1-hr candles: 30-90 days ago
  - 1-day candles: 90 days - 2 years ago
"""
import time
import sys
from datetime import datetime, timedelta
from sqlalchemy import text

import bot
from db_manager import CandleDatabase
from config import DB_URL

db = CandleDatabase()
groww = bot._get_groww()

# Get all symbols from stocks table + indices
with db.engine.connect() as conn:
    result = conn.execute(text('SELECT symbol FROM stocks ORDER BY symbol'))
    stock_syms = [r[0] for r in result]
    # Get already-done symbols
    result2 = conn.execute(text('SELECT DISTINCT symbol FROM candles'))
    done_syms = set(r[0] for r in result2)

ALL_SYMBOLS = sorted(set(stock_syms + ['NIFTY', 'BANKNIFTY', 'FINNIFTY']))
REMAINING = [s for s in ALL_SYMBOLS if s not in done_syms]

print(f"Total symbols: {len(ALL_SYMBOLS)}, Already done: {len(done_syms)}, Remaining: {len(REMAINING)}")

# Define time windows (most recent first)
NOW = datetime.utcnow()
WINDOWS = [
    # (label, interval_minutes, start_offset_days, end_offset_days)
    ("5min",  5,    15,  0),
    ("15min", 15,   30,  15),
    ("1hr",   60,   90,  30),
    ("1day",  1440, 730, 90),
]

def fetch_candles(symbol, interval, start_dt, end_dt):
    """Fetch candles from Groww API. Returns list of dicts."""
    try:
        resp = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            interval_in_minutes=interval,
        )
        candles = resp.get("candles", [])
        return [
            {
                "timestamp": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
            for c in candles
        ]
    except Exception as e:
        return []


# Step 1: No need to purge — already done. Just fetch missing symbols.
print(f"\n=== Fetching REAL candles from Groww API ({len(REMAINING)} symbols) ===")
total_inserted = 0
failed_symbols = []

for i, symbol in enumerate(REMAINING, 1):
    symbol_total = 0
    parts = []

    for label, interval, start_days, end_days in WINDOWS:
        start_dt = NOW - timedelta(days=start_days)
        end_dt = NOW - timedelta(days=end_days)

        candles = fetch_candles(symbol, interval, start_dt, end_dt)
        if candles:
            db.insert_candles(symbol, candles)
            symbol_total += len(candles)
            parts.append(f"{label}:{len(candles)}")

        # Small delay to avoid rate limiting
        time.sleep(0.3)

    total_inserted += symbol_total
    status = " + ".join(parts) if parts else "FAILED"
    print(f"[{i:3d}/{len(REMAINING)}] {symbol:20s} => {symbol_total:5d} candles  ({status})")

    if symbol_total == 0:
        failed_symbols.append(symbol)

    # Longer pause every 10 symbols to avoid rate limit
    if i % 10 == 0:
        time.sleep(2)

print(f"\n=== DONE ===")
print(f"Total real candles inserted: {total_inserted:,}")
print(f"Failed symbols ({len(failed_symbols)}): {failed_symbols[:20]}")

# Verify a few
print("\n=== VERIFICATION ===")
for sym in ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ITC']:
    df = db.get_candles(sym)
    if df is not None and len(df) > 0:
        print(f"{sym:15s} candles={len(df):5d}  last_close=₹{df['close'].iloc[-1]:.2f}  range={df['datetime'].iloc[0].date()} to {df['datetime'].iloc[-1].date()}")
    else:
        print(f"{sym:15s} NO DATA")
