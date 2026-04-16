#!/usr/bin/env python3
"""
Show profit potential at DIFFERENT confidence thresholds
Help decide what threshold makes sense
"""

import sys
import logging
from datetime import datetime
import pytz

sys.path.insert(0, PROJECT_ROOT)

import bot
from config import WATCHLIST

logging.basicConfig(level=logging.WARNING)

ist = pytz.timezone('Asia/Kolkata')
now = datetime.now(ist)

print("\n" + "=" * 90)
print("THRESHOLD ANALYSIS — Profit at Different Confidence Levels")
print("=" * 90)

print(f"\n⏰ Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

# Market open check
if now.weekday() >= 5 or now.hour < 9 or now.hour > 15:
    print("❌ Market closed")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────

print("Collecting predictions...")

trades = []
bot._predictors.clear()

for symbol in WATCHLIST[:5]:
    try:
        df = bot.fetch_historical(symbol, days=1, interval=5)
        if df.empty:
            continue
        
        pred = bot.get_prediction(symbol)
        trades.append({
            'symbol': symbol,
            'signal': pred.get('signal'),
            'confidence': pred.get('confidence', 0),
            'price': df['close'].iloc[-1],
            'high': df['high'].max(),
            'low': df['low'].min(),
            'open': df['open'].iloc[0],
        })
    except:
        pass

# Sort by confidence
trades.sort(key=lambda x: x['confidence'], reverse=True)

# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'-'*90}")
print(f"ALL SIGNALS (sorted by confidence)")
print(f"{'-'*90}\n")

for t in trades:
    conf_pct = t['confidence'] * 100
    print(f"{t['symbol']:10} | {t['signal']:4} @ ₹{t['price']:8.2f} | Confidence: {conf_pct:6.2f}%")

# ─────────────────────────────────────────────────────────────────────────────

thresholds = [0.01, 0.05, 0.10, 0.20, 0.50, 0.65, 0.80]

print(f"\n{'-'*90}")
print(f"PROFIT ANALYSIS AT DIFFERENT THRESHOLDS")
print(f"{'-'*90}\n")

for threshold in thresholds:
    
    # Filter by threshold
    candidates = [t for t in trades if t['confidence'] >= threshold]
    
    if not candidates:
        print(f"📊 Threshold: {threshold*100:5.1f}% → ❌ 0 trades")
        continue
    
    # Calculate potential profit
    total_profit = 0
    winning_trades = 0
    
    for t in candidates:
        entry = t['price']
        today_move = (entry - t['open']) / t['open'] * 100  # Today's close - open move
        
        if t['signal'] == 'BUY':
            # Would make money if price goes up
            if today_move > 0:
                winning_trades += 1
                total_profit += today_move
        elif t['signal'] == 'SELL':
           # Would make money if price goes down
            if today_move < 0:
                winning_trades += 1
                total_profit += abs(today_move)
    
    win_pct = (winning_trades / len(candidates) * 100) if candidates else 0
    
    print(f"📊 Threshold: {threshold*100:5.1f}% → {len(candidates)} trades | Win rate: {win_pct:5.1f}%")
    
    for t in candidates:
        today_move = (t['price'] - t['open']) / t['open'] * 100
        signal_match = "✅" if (t['signal'] == 'BUY' and today_move > 0) or (t['signal'] == 'SELL' and today_move < 0) else "❌"
        conf_pct = t['confidence'] * 100
        print(f"         {signal_match} {t['symbol']:6} {t['signal']:4} @ {t['price']:8.2f} | Move: {today_move:+.2f}% | Conf: {conf_pct:5.2f}%")

# ─────────────────────────────────────────────────────────────────────────────

print(f"\n{'-'*90}")
print(f"RECOMMENDATION")
print(f"{'-'*90}\n")

best_threshold = None
best_winrate = 0

for threshold in thresholds:
    candidates = [t for t in trades if t['confidence'] >= threshold]
    if not candidates:
        continue
    
    win = sum(1 for t in candidates if (t['signal'] == 'BUY' and t['price'] > t['open']) or (t['signal'] == 'SELL' and t['price'] < t['open']))
    winrate = win / len(candidates) * 100
    
    if winrate > best_winrate:
        best_winrate = winrate
        best_threshold = threshold

if best_threshold is not None:
    print(f"✅ Best threshold: {best_threshold*100:.1f}% (win rate: {best_winrate:.1f}%)")
    print(f"   This gives reasonable signal quality with good win rate\n")
else:
    print("⚠️  No good threshold found today\n")

print("=" * 90 + "\n")
