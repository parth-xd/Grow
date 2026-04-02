#!/usr/bin/env python3
"""
PROFIT SIMULATOR — Paper trading with profit/loss analysis
Shows what trades would happen and potential PnL
"""

import sys
import logging
from datetime import datetime
import pytz

sys.path.insert(0, '/Users/parthsharma/Desktop/Grow')

import bot
from config import WATCHLIST

logging.basicConfig(level=logging.WARNING)  # Suppress debug logs

ist = pytz.timezone('Asia/Kolkata')
now = datetime.now(ist)

print("\n" + "=" * 90)
print("PROFIT SIMULATOR — Today's Trading Signals & Potential PnL")
print("=" * 90)

print(f"\n⏰ Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

# Check market hours
if now.weekday() >= 5:
    print("❌ Market CLOSED (Weekend)")
    sys.exit(1)

market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)

if now < market_open:
    print(f"⏳ Market opens at 09:15 IST")
    sys.exit(0)

print("✅ Market OPEN\n")

# ─────────────────────────────────────────────────────────────────────────────

print("-" * 90)
print("ANALYZING TODAY'S SIGNALS")
print("-" * 90 + "\n")

trades = []
bot._predictors.clear()

for symbol in WATCHLIST[:5]:
    print(f"📊 {symbol}...", end=" ", flush=True)
    
    try:
        # Get data
        df = bot.fetch_historical(symbol, days=1, interval=5)
        
        if df.empty:
            print("❌ No data")
            continue
        
        current_price = df['close'].iloc[-1]
        today_open = df['open'].iloc[0]
        today_high = df['high'].max()
        today_low = df['low'].min()
        day_move_pct = ((current_price - today_open) / today_open) * 100
        
        # Get prediction
        prediction = bot.get_prediction(symbol)
        signal = prediction.get('signal', 'HOLD')
        confidence = prediction.get('confidence', 0)
        
        print(f"${current_price:.2f} | {signal:>4} ({confidence:.1f}%)")
        
        trades.append({
            'symbol': symbol,
            'signal': signal,
            'confidence': confidence,
            'price': current_price,
            'open': today_open,
            'high': today_high,
            'low': today_low,
            'day_move_pct': day_move_pct,
        })
        
    except Exception as e:
        print(f"❌ {str(e)[:40]}")

# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "-" * 90)
print("PROFIT ANALYSIS (Paper Trading Scenarios)")
print("-" * 90 + "\n")

# Scenario 1: Execute only >80% confidence trades
print("📈 SCENARIO 1: STRICT (Confidence >80%)")
print("─" * 90)

strict_trades = [t for t in trades if t['confidence'] >= 80]

if not strict_trades:
    print("   ⚠️  No signals above 80% confidence today")
else:
    total_pnl = 0
    for t in strict_trades:
        # Assume entry at current price
        entry = t['price']
        
        if t['signal'] == 'BUY':
            # Profit if price goes up
            sell_target = entry * 1.02  # 2% profit target
            stop_loss = entry * 0.98   # 2% stop loss
            potential_profit = sell_target - entry
            pnl_pct = 2.0
        elif t['signal'] == 'SELL':
            # Profit if price goes down
            sell_target = entry * 0.98  # 2% profit target
            stop_loss = entry * 1.02
            potential_profit = entry - sell_target
            pnl_pct = 2.0
        else:
            continue
        
        print(f"   {t['symbol']}: {t['signal']} @ ₹{entry:.2f}")
        print(f"      Target: ₹{sell_target:.2f} | SL: ₹{stop_loss:.2f} | Potential: +{pnl_pct:.1f}%")
        
        total_pnl += potential_profit

# Scenario 2: Execute >50% confidence trades
print("\n📈 SCENARIO 2: MODERATE (Confidence >50%)")
print("─" * 90)

moderate_trades = [t for t in trades if t['confidence'] >= 50]

if not moderate_trades:
    print("   ⚠️  No signals above 50% confidence today")
else:
    total_pnl = 0
    for t in moderate_trades:
        entry = t['price']
        
        if t['signal'] == 'BUY':
            sell_target = entry * 1.02
            stop_loss = entry * 0.98
            potential_profit = sell_target - entry
            pnl_pct = 2.0
        elif t['signal'] == 'SELL':
            sell_target = entry * 0.98
            stop_loss = entry * 1.02
            potential_profit = entry - sell_target
            pnl_pct = 2.0
        else:
            continue
        
        confidence_color = "✅" if t['confidence'] >= 80 else "⚠️"
        print(f"   {confidence_color} {t['symbol']}: {t['signal']} @ ₹{entry:.2f} ({t['confidence']:.1f}%)")
        print(f"      Target: ₹{sell_target:.2f} | SL: ₹{stop_loss:.2f} | Potential: +{pnl_pct:.1f}%")
        
        total_pnl += potential_profit

if moderate_trades:
    print(f"\n   💰 Total Potential (all moderate trades): ₹{total_pnl:.2f}")

# Scenario 3: Today's Price Action
print("\n📈 SCENARIO 3: TODAY'S MARKET MOVES (What Happened)")
print("─" * 90 + "\n")

for t in trades:
    today_move = t['day_move_pct']
    move_emoji = "📈" if today_move > 0 else "📉"
    print(f"   {move_emoji} {t['symbol']:10} | Open: ₹{t['open']:8.2f} → Now: ₹{t['price']:8.2f} ({today_move:+.2f}%)")
    print(f"      Today: {t['high']:.2f} (high) / {t['low']:.2f} (low)")

# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 90)
print("SUMMARY")
print("=" * 90)

high_conf = len([t for t in trades if t['confidence'] >= 80])
med_conf = len([t for t in trades if 50 <= t['confidence'] < 80])
low_conf = len([t for t in trades if t['confidence'] < 50])

print(f"\n📊 Signal Distribution:")
print(f"   🟢 High Confidence (>80%):    {high_conf} signals")
print(f"   🟡 Medium Confidence (50-80%): {med_conf} signals")
print(f"   🔴 Low Confidence (<50%):     {low_conf} signals")

print(f"\n💡 Today's Market: {sum([1 for t in trades if t['day_move_pct'] > 0])}/{len(trades)} stocks up")

print(f"\n✅ Paper trading simulation completed at {now.strftime('%H:%M IST')}")
print("\n" + "=" * 90 + "\n")
