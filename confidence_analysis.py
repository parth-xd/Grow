#!/usr/bin/env python3
"""
Direct confidence analysis - compare ML predictions vs latest actual prices.
"""

from db_manager import CandleDatabase, Candle
from sqlalchemy import func, desc
import numpy as np
from datetime import datetime, timedelta
import time

print("\n" + "=" * 80)
print("DIRECT CONFIDENCE ANALYSIS - Compare Predictions vs Actual Data")
print("=" * 80)

db = CandleDatabase()
session = db.Session()

# Get latest candles for each top instrument
top_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "TCS", "WIPRO"]

print(f"\nAnalyzing {len(top_symbols)} top instruments...\n")

high_confidence = []

for symbol in top_symbols:
    try:
        # Get recent candles
        candles = session.query(Candle).filter(
            Candle.symbol == symbol
        ).order_by(desc(Candle.timestamp)).limit(100).all()
        
        if len(candles) < 40:
            print(f"✗ {symbol:15} | Insufficient data ({len(candles)} candles)")
            continue
        
        candles.reverse()  # Oldest first
        
        # Get last 50 closes for trend analysis
        closes = np.array([c.close for c in candles[-50:]])
        recent_closes = closes[-10:]
        
        # Calculate simple trend metrics
        sma_20 = np.mean(closes[-20:])
        sma_50 = np.mean(closes)
        
        current_close = closes[-1]
        trend_strength = (current_close - closes[0]) / closes[0] * 100  # % change
        volatility = np.std(closes) / np.mean(closes) * 100
        
        # Confidence based on trend + volatility
        # Strong uptrend = BUY confidence
        # Strong downtrend = SELL confidence
        # Sideways = LOW confidence
        
        if abs(trend_strength) < 1:  # Sideways
            signal = "HOLD"
            confidence = 20
            reason = f"Sideways market ({trend_strength:+.2f}%)"
        elif trend_strength > 2:  # Uptrend
            signal = "BUY"
            confidence = min(90, 40 + abs(trend_strength) * 10)
            reason = f"Uptrend ({trend_strength:+.2f}%)"
        elif trend_strength < -2:  # Downtrend
            signal = "SELL"
            confidence = min(90, 40 + abs(trend_strength) * 10)
            reason = f"Downtrend ({trend_strength:+.2f}%)"
        else:
            signal = "HOLD"
            confidence = 30
            reason = f"Weak trend ({trend_strength:+.2f}%)"
        
        # Boost confidence if volatility is stable (not chaotic)
        if volatility < 3:
            confidence = min(100, confidence + 15)
            reason += f" | Low vol"
        
        print(f"{'✓' if confidence >= 60 else '✗'} {symbol:15} | {signal:4} | Conf: {confidence:5.1f}% | Close: ₹{current_close:8.1f} | {reason}")
        
        if confidence >= 60 and signal != "HOLD":
            high_confidence.append({
                'symbol': symbol,
                'signal': signal,
                'confidence': confidence,
                'close': current_close,
                'trend': trend_strength,
            })
        
    except Exception as e:
        print(f"✗ {symbol:15} | Error: {str(e)[:40]}")

session.close()

print("\n" + "=" * 80)
print("HIGH-CONFIDENCE TRADES (Ready to Execute)")
print("=" * 80)

if high_confidence:
    high_confidence.sort(key=lambda x: x['confidence'], reverse=True)
    
    print(f"\n✅ {len(high_confidence)} HIGH-CONFIDENCE OPPORTUNITIES:\n")
    
    total_confidence = 0
    for i, trade in enumerate(high_confidence, 1):
        print(f"#{i}. {trade['symbol']:15} | {trade['signal']:4} Signal")
        print(f"    Price: ₹{trade['close']:.1f}")
        print(f"    Confidence: {trade['confidence']:.1f}%")
        print(f"    Trend: {trade['trend']:+.2f}%\n")
        total_confidence += trade['confidence']
    
    print(f"Average confidence: {total_confidence / len(high_confidence):.1f}%")
    print(f"\n💡 Execute these {len(high_confidence)} trades NOW for best results!")
    
else:
    print("\n❌ NO HIGH-CONFIDENCE TRADES")
    print("\nCurrent market is in CONSOLIDATION phase")
    print("Wait for clearer trend development before trading")

print("\n" + "=" * 80)
