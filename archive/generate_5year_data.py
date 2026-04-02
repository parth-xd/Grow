#!/usr/bin/env python3
"""
Generate comprehensive 5-year synthetic hourly candle data for all NSE stocks and indices.
Creates realistic price patterns with volatility, trends, and seasonal variations.
"""

import logging
import random
import math
import numpy as np
from datetime import datetime, timedelta
from db_manager import CandleDatabase, Candle
from sqlalchemy import func

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

# Stock price ranges (realistic for NSE)
STOCK_PRICE_RANGES = {
    "NIFTY": (15000, 25000),
    "BANKNIFTY": (30000, 50000),
    "FINNIFTY": (15000, 22000),
    # Small cap
    "SUZLON": (3, 8),
    "GEMAROMA": (30, 150),
    # Mid cap
    "MARUTI": (7000, 12000),
    "BAJAJFINSV": (15000, 25000),
    # Large cap
    "RELIANCE": (1500, 2500),
    "TCS": (3000, 4500),
    "INFY": (1300, 2500),
    "HDFCBANK": (1400, 2500),
    "ICICIBANK": (900, 1600),
    "SBIN": (600, 1200),
    "WIPRO": (400, 700),
    "HDFC": (2500, 3500),
}

def get_stock_price_range(symbol):
    """Get realistic price range for a stock."""
    if symbol in STOCK_PRICE_RANGES:
        return STOCK_PRICE_RANGES[symbol]
    
    # Default ranges based on common categories
    if symbol in ["NIFTY", "BANKNIFTY"]:
        return (20000, 35000)
    elif symbol.endswith("BANK"):
        return (200, 3000)
    elif symbol.startswith("ADANI"):
        return (100, 3000)
    else:
        return (50, 2000)  # Default for most stocks


def generate_realistic_candle(prev_close, trend=0.0, volatility=0.02):
    """
    Generate a realistic hourly candle with trend and volatility.
    
    trend: 0 = no trend, >0 = uptrend, <0 = downtrend
    volatility: typical intraday volatility (0.02 = 2%)
    """
    # Open: close to previous close with slight drift
    open_price = prev_close * (1 + trend * random.uniform(-0.001, 0.001))
    
    # Range: based on volatility
    intraday_range = open_price * volatility * random.uniform(0.5, 1.5)
    
    # High/Low: can exceed open by range
    if random.random() < 0.5:  # Upside
        high = open_price + intraday_range
        low = open_price - intraday_range * random.uniform(0.2, 0.8)
    else:  # Downside
        high = open_price + intraday_range * random.uniform(0.2, 0.8)
        low = open_price - intraday_range
    
    # Close: somewhere within high-low, with tendency toward open+trend
    close_target = open_price * (1 + trend)
    close = np.clip(
        close_target + np.random.normal(0, intraday_range * 0.1),
        low,
        high
    )
    
    # Volume: realistic with volatility correlation
    base_volume = 500000
    volume_multiplier = 0.5 + 1.5 * abs(close - open_price) / open_price
    volume = int(base_volume * volume_multiplier * random.uniform(0.7, 1.3))
    
    return {
        'open': round(float(open_price), 2),
        'high': round(float(high), 2),
        'low': round(float(low), 2),
        'close': round(float(close), 2),
        'volume': max(10000, volume),
    }


def generate_5year_data(symbol, initial_price=None, batch_size=1000):
    """Generate 5 years of hourly candle data for a symbol."""
    db = CandleDatabase()
    session = db.Session()
    
    try:
        # Check if symbol already has substantial data
        existing_count = session.query(func.count(Candle.id)).filter(
            Candle.symbol == symbol
        ).scalar()
        
        if existing_count >= 5000:
            logger.debug(f"{symbol}: Already has {existing_count} candles, skipping")
            session.close()
            return 0
        
        # Clear existing data for this symbol to regenerate
        session.query(Candle).filter(Candle.symbol == symbol).delete()
        session.commit()
        
        # Get price range
        if initial_price is None:
            price_low, price_high = get_stock_price_range(symbol)
            initial_price = random.uniform(price_low, price_high)
        
        logger.info(f"Generating 5-year data for {symbol} (starting ₹{initial_price:.2f})")
        
        # Generate data backwards from now to 5 years ago
        now = datetime.now().replace(hour=16, minute=15, second=0, microsecond=0)
        five_years_ago = now - timedelta(days=365*5)
        
        added = 0
        prev_close = initial_price
        current_date = five_years_ago
        
        # Track trends (for multi-day patterns)
        trend = 0.0
        trend_duration = 0
        
        while current_date <= now:
            # Occasional trend changes (every 20-50 days)
            if trend_duration <= 0:
                trend = random.uniform(-0.0002, 0.0002)  # Small daily trend
                trend_duration = random.randint(20, 50)
            trend_duration -= 1
            
            # Skip weekends (simplified: skip if day is 5=Saturday or 6=Sunday)
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue
            
            # Market hours: 7 candles per day (9:15, 10:15, 11:15, 12:15, 13:15, 14:15, 15:15-16:15)
            for hour in [9, 10, 11, 12, 13, 14, 15]:
                timestamp = current_date.replace(hour=hour, minute=15)
                
                # Volatility varies: lower in summer, higher in monsoon/winter
                month = timestamp.month
                if 3 <= month <= 5:  # Summer: lower volatility
                    vol = random.uniform(0.015, 0.025)
                elif 6 <= month <= 9:  # Monsoon: higher volatility
                    vol = random.uniform(0.025, 0.035)
                else:  # Winter: medium volatility
                    vol = random.uniform(0.02, 0.03)
                
                candle_data = generate_realistic_candle(prev_close, trend=trend, volatility=vol)
                
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
                
                # Batch commit for performance
                if added % batch_size == 0:
                    session.commit()
            
            current_date += timedelta(days=1)
        
        session.commit()
        logger.info(f"{symbol}: Generated {added} candles")
        return added
        
    except Exception as e:
        logger.error(f"Error generating data for {symbol}: {e}")
        session.rollback()
        return 0
    finally:
        session.close()


def main():
    """Generate 5-year data for all instruments."""
    logger.info("=" * 80)
    logger.info("5-YEAR SYNTHETIC DATA GENERATOR (All 240 instruments)")
    logger.info("=" * 80)
    logger.info(f"This will generate ~40,000+ candles per instrument")
    logger.info("")
    
    # Get all unique symbols from current database
    db = CandleDatabase()
    session = db.Session()
    
    # Get existing symbols
    existing_symbols = set()
    symbols_in_db = session.query(Candle.symbol).distinct().all()
    existing_symbols = {s[0] for s in symbols_in_db}
    
    # Add indices if not present
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY"]
    all_symbols = list(existing_symbols.union(set(indices)))
    
    session.close()
    
    logger.info(f"Found {len(all_symbols)} total symbols to generate")
    logger.info("")
    
    total_added = 0
    successful = 0
    failed = 0
    
    for idx, symbol in enumerate(sorted(all_symbols), 1):
        try:
            added = generate_5year_data(symbol)
            if added > 0:
                total_added += added
                successful += 1
                if idx % 10 == 0:
                    logger.info(f"[{idx}/{len(all_symbols)}] Progress: {total_added:,} total candles generated")
            else:
                successful += 1
        except Exception as e:
            logger.error(f"[{idx}/{len(all_symbols)}] {symbol}: Failed - {e}")
            failed += 1
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("GENERATION COMPLETE")
    logger.info(f"  Total symbols processed: {successful}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Total candles generated: {total_added:,}")
    logger.info(f"  Average per symbol: {total_added // max(successful, 1):,}")
    logger.info("=" * 80)
    
    # Final verification
    db = CandleDatabase()
    session = db.Session()
    
    total_candles = session.query(func.count(Candle.id)).scalar()
    unique_symbols = session.query(func.count(func.distinct(Candle.symbol))).scalar()
    
    logger.info(f"\nDatabase verification:")
    logger.info(f"  Total unique symbols: {unique_symbols}")
    logger.info(f"  Total candles: {total_candles:,}")
    logger.info(f"  Ready for XGBoost training on {total_candles:,} samples")
    
    session.close()


if __name__ == "__main__":
    main()
