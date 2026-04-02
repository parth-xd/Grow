#!/usr/bin/env python3
"""
LIVE TRADING EXECUTOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Real-time workflow:
  1. Pull live 5-min candles from Groww API for today (market hours)
  2. Analyze with bot's ML prediction engine
  3. Auto-execute BUY/SELL trades with >80% confidence
"""

import sys
import logging
from datetime import datetime
import pytz

sys.path.insert(0, '/Users/parthsharma/Desktop/Grow')

import bot
from fno_trader import place_fno_buy, place_fno_sell, _get_groww
from config import WATCHLIST, CONFIDENCE_THRESHOLD

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: PREPARE ENVIRONMENT
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 80)
print("LIVE TRADING EXECUTOR — Pull Today's Data → Predict → Trade")
print("=" * 80)

# Check market hours
ist = pytz.timezone('Asia/Kolkata')
now = datetime.now(ist)

print(f"\n📅 Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

if now.weekday() >= 5:
    print("❌ Market CLOSED (Weekend)")
    sys.exit(1)

market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

if now < market_open:
    print(f"⏳ Market opens at 09:15 IST")
    sys.exit(0)
elif now > market_close:
    print(f"⏳ Market closed at 15:30 IST")
    sys.exit(0)

print("✅ Market OPEN — Ready to trade")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: FORCE TODAY'S DATA COLLECTION FROM GROWW
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 80)
print("STEP 1: Ready to analyze today's data...")
print("-" * 80 + "\n")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: ANALYZE EACH WATCHLIST SYMBOL
# ─────────────────────────────────────────────────────────────────────────────

print("-" * 80)
print("STEP 2: Analyzing predictions based on today's data...")
print("-" * 80 + "\n")

high_confidence_trades = []

# Clear predictor cache to force fresh analysis with today's data
bot._predictors.clear()

for symbol in WATCHLIST[:5]:  # Analyze first 5 symbols (avoid rate limits)
    
    print(f"📊 Analyzing {symbol}...")
    
    try:
        # Fetch today's data
        df = bot.fetch_historical(symbol, days=1, interval=5)
        
        if df.empty:
            print(f"   ⚠️  No today's data available")
            continue
        
        today_candles = len(df)
        first_time = df['datetime'].iloc[0]
        last_time = df['datetime'].iloc[-1]
        last_close = df['close'].iloc[-1]
        
        print(f"   📈 Data: {today_candles} candles (9:15 AM - {last_time.strftime('%H:%M')})")
        print(f"   💰 Current price: ₹{last_close:.2f}")
        
        # Run prediction
        prediction = bot.get_prediction(symbol)
        
        signal = prediction.get('signal', 'HOLD')
        confidence = prediction.get('confidence', 0)
        
        print(f"   🎯 Signal: {signal} | Confidence: {confidence:.1f}%")
        
        # Check if high confidence
        if confidence >= CONFIDENCE_THRESHOLD:  # Usually 80
            print(f"   ✅ HIGH CONFIDENCE SIGNAL DETECTED!")
            
            high_confidence_trades.append({
                'symbol': symbol,
                'signal': signal,
                'confidence': confidence,
                'price': last_close,
                'candles_today': today_candles,
                'prediction': prediction,
            })
        
        print()
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}\n")
        continue

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: EXECUTE HIGH-CONFIDENCE TRADES
# ─────────────────────────────────────────────────────────────────────────────

if not high_confidence_trades:
    print("-" * 80)
    print("ℹ️  No high-confidence signals found. Exiting.")
    print("-" * 80)
    sys.exit(0)

print("-" * 80)
print(f"STEP 3: High-confidence trades identified ({len(high_confidence_trades)} signals)")
print("-" * 80 + "\n")

print("📋 TRADES READY TO EXECUTE:\n")

for trade in high_confidence_trades:
    symbol = trade['symbol']
    signal = trade['signal']
    price = trade['price']
    confidence = trade['confidence']
    
    print(f"🚀 {symbol}")
    print(f"   Action: {signal:>6} | Price: ₹{price:>8.2f} | Confidence: {confidence:>5.1f}%")
print()

print("=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"\n📊 Analyzed: {len(WATCHLIST[:5])} symbols")
print(f"✅ High-confidence signals: {len(high_confidence_trades)}")
for trade in high_confidence_trades:
    print(f"   • {trade['symbol']} - {trade['signal']} ({trade['confidence']:.1f}%)")

print(f"\n💡 Ready to execute these trades with place_fno_buy() / place_fno_sell()")
print(f"⏰ Analysis completed at: {datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S %Z')}")
print("\n" + "=" * 80 + "\n")
