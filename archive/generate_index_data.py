#!/usr/bin/env python3
"""Generate synthetic candle data for indices (NIFTY, BANKNIFTY, FINNIFTY)."""

import random
from datetime import datetime, timedelta
from db_manager import CandleDatabase, Candle

def generate_candle(prev_close, volatility=0.015):
    """Generate a realistic candle based on previous close."""
    open_price = prev_close * random.uniform(0.9985, 1.0015)
    max_move = prev_close * volatility
    high = open_price + random.uniform(0, max_move)
    low = open_price - random.uniform(0, max_move)
    close = random.uniform(max(low, prev_close * 0.99), min(high, prev_close * 1.01))
    volume = int(random.gauss(1000000, 300000))
    volume = max(100000, volume)
    
    return {
        'open': round(open_price, 2),
        'high': round(max(open_price, high, close), 2),
        'low': round(min(open_price, low, close), 2),
        'close': round(close, 2),
        'volume': volume,
    }

def generate_index_data(symbol, initial_price, days=15):
    """Generate synthetic data for an index."""
    db = CandleDatabase()
    session = db.Session()
    
    try:
        # Check if already exists
        existing_count = session.query(Candle).filter_by(symbol=symbol).count()
        if existing_count > 0:
            session.close()
            return 0
        
        prev_close = initial_price
        added = 0
        now = datetime.now().replace(hour=16, minute=15, second=0, microsecond=0)
        
        for day_offset in range(days - 1, -1, -1):
            day_start = now - timedelta(days=day_offset)
            
            # 7 hourly candles per day (9:15-16:00)
            for hour_offset in range(7):
                timestamp = day_start - timedelta(hours=7 - hour_offset - 1)
                
                candle_data = generate_candle(prev_close, volatility=0.015)
                
                candle = Candle(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=candle_data['open'],
                    high=candle_data['high'],
                    low=candle_data['low'],
                    close=candle_data['close'],
                    volume=candle_data['volume'],
                )
                session.add(candle)
                added += 1
                prev_close = candle_data['close']
        
        session.commit()
        return added
        
    except Exception as e:
        print(f"Error generating {symbol}: {e}")
        session.rollback()
        return 0
    finally:
        session.close()

# Generate data for indices
indices = {
    "NIFTY": 23500,        # Approximate current NIFTY level
    "BANKNIFTY": 48000,    # Approximate current BANKNIFTY level
    "FINNIFTY": 20500,     # Approximate current FINNIFTY level
}

print("Generating synthetic data for indices...")
for symbol, initial_price in indices.items():
    added = generate_index_data(symbol, initial_price, days=15)
    if added > 0:
        print(f"✓ {symbol}: {added} candles generated")
    else:
        print(f"⊘ {symbol}: Already has data")

print("\nVerifying index data...")
from db_manager import CandleDatabase, Candle
from sqlalchemy import func

db = CandleDatabase()
session = db.Session()

for symbol in indices.keys():
    count = session.query(func.count(Candle.id)).filter(Candle.symbol == symbol).scalar()
    print(f"  {symbol}: {count} candles")

session.close()
print("✓ Complete")
