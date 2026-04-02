"""Quick test: what live data can Groww API provide?"""
import json
from fno_trader import _get_groww

g = _get_groww()

# 1. NIFTY quote
print("=== NIFTY QUOTE ===")
try:
    q = g.get_quote(trading_symbol="NIFTY", exchange="NSE", segment="CASH")
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print("Error:", e)

# 2. BANKNIFTY quote
print("\n=== BANKNIFTY QUOTE ===")
try:
    q = g.get_quote(trading_symbol="BANKNIFTY", exchange="NSE", segment="CASH")
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print("Error:", e)

# 3. India VIX
print("\n=== INDIA VIX ===")
for sym in ["INDIA VIX", "INDIAVIX", "NIFTY VIX"]:
    try:
        q = g.get_quote(trading_symbol=sym, exchange="NSE", segment="CASH")
        print(f"{sym}: {json.dumps(q, indent=2, default=str)}")
        break
    except Exception as e:
        print(f"{sym}: {e}")

# 4. OHLC for NIFTY
print("\n=== NIFTY OHLC ===")
try:
    q = g.get_ohlc(exchange_trading_symbols="NIFTY", exchange="NSE", segment="CASH")
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print("Error:", e)

# 5. LTP
print("\n=== LTP NIFTY ===")
try:
    q = g.get_ltp(exchange_trading_symbols="NIFTY", exchange="NSE", segment="CASH")
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print("Error:", e)

# 6. Batch OHLC multiple symbols
print("\n=== BATCH OHLC ===")
try:
    syms = [
        {"exchange": "NSE", "tradingSymbol": "NIFTY"},
        {"exchange": "NSE", "tradingSymbol": "BANKNIFTY"},
        {"exchange": "NSE", "tradingSymbol": "FINNIFTY"},
    ]
    q = g.get_ohlc(exchange_trading_symbols=syms, segment="CASH")
    print(json.dumps(q, indent=2, default=str))
except Exception as e:
    print("Batch error:", e)

# 7. Get quote fields list
print("\n=== NIFTY QUOTE KEYS ===")
try:
    q = g.get_quote(trading_symbol="NIFTY", exchange="NSE", segment="CASH")
    print("Keys:", list(q.keys()) if isinstance(q, dict) else type(q))
except Exception as e:
    print("Error:", e)

# 8. Candles - intraday 1hr for the last 5 days
print("\n=== NIFTY 1HR CANDLES (last 5 days) ===")
from datetime import datetime, timedelta
try:
    now = datetime.now()
    start = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")
    data = g.get_historical_candle_data(
        trading_symbol="NIFTY", exchange="NSE", segment="CASH",
        start_time=start, end_time=end, interval_in_minutes=60,
    )
    candles = data.get("candles", []) if data else []
    print(f"Candle count: {len(candles)}")
    if candles:
        print("Last candle:", candles[-1])
        print("First candle:", candles[0])
except Exception as e:
    print("Error:", e)
