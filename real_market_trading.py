#!/usr/bin/env python3
"""
CORRECTED: Real-time trading using ACTUAL market prices from Groww API.
This will run at market open (09:15 IST) daily.
"""

import logging
from datetime import datetime, timedelta
from fno_trader import place_fno_buy, _get_groww
import pytz

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def get_current_price(symbol, groww_api):
    """Get current price from Groww API (real market data)."""
    try:
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        start_time = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        end_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        resp = groww_api.get_historical_candle_data(
            trading_symbol=symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=5,
        )
        
        if resp and resp.get('candles'):
            candles = resp['candles']
            latest = candles[-1]
            return {
                'close': latest.get('close', 0),
                'high': latest.get('high', 0),
                'low': latest.get('low', 0),
                'open': latest.get('open', 0),
                'timestamp': latest.get('timestamp'),
            }
        return None
        
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None

def analyze_real_signals():
    """Analyze with REAL market data."""
    
    print("\n" + "=" * 80)
    print("REAL-TIME MARKET ANALYSIS (Using Groww API)")
    print("=" * 80)
    
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    
    print(f"\nTime: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    # Check market hours
    if now.weekday() >= 5:
        print("❌ Market CLOSED (Weekend)")
        return []
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    if now < market_open or now > market_close:
        print(f"⏳ Market is closed (next open: 09:15 IST)")
        return []
    
    print("✅ Market is OPEN\n")
    
    # Connect to Groww
    try:
        groww = _get_groww()
        if not groww:
            print("❌ Cannot connect to Groww API")
            return []
    except Exception as e:
        print(f"❌ Groww error: {e}")
        return []
    
    # Check top symbols with real prices
    top_symbols = ["TCS", "RELIANCE", "HDFCBANK", "INFY", "NIFTY", "BANKNIFTY"]
    
    print("Fetching REAL prices...\n")
    
    high_confidence = []
    
    for symbol in top_symbols:
        price_data = get_current_price(symbol, groww)
        
        if not price_data:
            print(f"  {symbol:15} | No data")
            continue
        
        close = price_data['close']
        high = price_data['high']
        low = price_data['low']
        
        # Analyze real market structure
        # Simple: if price near high = uptrend (BUY), near low = downtrend (SELL)
        range_pct = (high - low) / low * 100 if low > 0 else 0
        pct_from_low = (close - low) / low * 100 if low > 0 else 0
        
        if range_pct < 1:  # Low volatility - no clear direction
            signal = "HOLD"
            confidence = 20
        elif pct_from_low > 70:  # Near high - uptrend
            signal = "BUY"
            confidence = min(90, 40 + pct_from_low)
        elif pct_from_low < 30:  # Near low - downtrend
            signal = "SELL"
            confidence = min(90, 40 + (100 - pct_from_low))
        else:  # Middle range
            signal = "HOLD"
            confidence = 30
        
        print(f"  {symbol:15} | ₹{close:10.2f} | {signal:4} | Conf: {confidence:5.1f}%")
        
        if confidence >= 70 and signal != "HOLD":
            high_confidence.append({
                'symbol': symbol,
                'signal': signal,
                'price': close,
                'confidence': confidence,
                'high': high,
                'low': low,
            })
    
    print(f"\n" + "=" * 80)
    print(f"HIGH-CONFIDENCE TRADES: {len(high_confidence)}")
    print("=" * 80 + "\n")
    
    if high_confidence:
        high_confidence.sort(key=lambda x: x['confidence'], reverse=True)
        
        for i, trade in enumerate(high_confidence, 1):
            print(f"#{i}. {trade['symbol']:15} | {trade['signal']:4} @ ₹{trade['price']:.2f}")
            print(f"    Confidence: {trade['confidence']:.1f}%")
            print(f"    Range: ₹{trade['low']:.2f} - ₹{trade['high']:.2f}\n")
    
    return high_confidence

if __name__ == "__main__":
    trades = analyze_real_signals()
    
    print("=" * 80)
    if trades:
        print(f"✅ Ready to execute {len(trades)} real-market trades")
    else:
        print("⏳ Waiting for high-confidence signals (≥70%)")
    print("=" * 80 + "\n")
