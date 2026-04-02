#!/usr/bin/env python3
"""Analyze and recommend actions for loss positions"""

import json
import os
from paper_trader import get_live_price
import pytz

ist = pytz.timezone('Asia/Kolkata')

with open('paper_trades.json', 'r') as f:
    trades = json.load(f)

open_trades = [t for t in trades if t['status'] == 'OPEN']

print("\n" + "="*110)
print("OPEN POSITIONS ANALYSIS - LOSS EVALUATION")
print("="*110 + "\n")

loss_trades = []
building_trades = []
won_trades = []

for trade in open_trades:
    symbol = trade['symbol']
    entry = trade['entry_price']
    signal = trade['signal']
    trade_id = trade['id']
    target = trade['entry_profit_target']
    
    try:
        current_price = get_live_price(symbol)
        
        if not current_price:
            print(f"  ⚠️  {symbol} - Could not fetch current price")
            continue
            pnl = ((current_price - entry) / entry) * 100
        else:  # SELL
            pnl = ((entry - current_price) / entry) * 100
        
        distance_from_target = pnl - target
        
        trade_info = {
            'id': trade_id,
            'symbol': symbol,
            'signal': signal,
            'entry': entry,
            'current': current_price,
            'pnl': pnl,
            'target': target,
            'distance': distance_from_target,
            'peak_pnl': trade.get('peak_pnl', 0)
        }
        
        if pnl < 0:
            loss_trades.append(trade_info)
        elif pnl >= target:
            won_trades.append(trade_info)
        else:
            building_trades.append(trade_info)
            
    except Exception as e:
        print(f"ERROR fetching {symbol}: {e}")

# LOSS POSITIONS
print(f"📉 LOSS POSITIONS ({len(loss_trades)} trades):")
print("-" * 110)
if loss_trades:
    for t in loss_trades:
        severity = "CRITICAL" if t['pnl'] < -1.5 else "HIGH" if t['pnl'] < -1.0 else "MEDIUM"
        action = ""
        
        # Recommendation logic
        if t['pnl'] < -1.5:
            action = "→ CLOSE NOW (severe loss, recovery unlikely)"
        elif t['pnl'] < -1.0:
            action = "→ HOLD/REVERSE (wait for reversal signal)"
        elif t['peak_pnl'] > 0:
            action = "→ SCALE OUT (was profitable, now unwinding)"
        else:
            action = "→ WAIT FOR REVERSAL (never hit target)"
        
        print(f"  ID:{t['id']:2} {t['symbol']:12} {t['signal']:4} Entry:₹{t['entry']:7.2f} Current:₹{t['current']:7.2f} PnL:{t['pnl']:+7.2f}% [{severity:8}] {action}")
else:
    print("  ✓ None - all positions profitable or building!")

# BUILDING POSITIONS
print(f"\n📊 BUILDING POSITIONS ({len(building_trades)} trades):")
print("-" * 110)
if building_trades:
    building_trades.sort(key=lambda x: x['distance'], reverse=True)  # Show closest to target first
    for t in building_trades:
        proximity = f"{t['distance']:+.2f}% from target"
        print(f"  ID:{t['id'] :2} {t['symbol']:12} {t['signal']:4} Entry:₹{t['entry']:7.2f} Current:₹{t['current']:7.2f} PnL:{t['pnl']:+7.2f}% [{proximity:18}]")
else:
    print("  ✓ None - all positions won or in loss!")

# WON POSITIONS
print(f"\n✅ WON POSITIONS ({len(won_trades)} trades):")
print("-" * 110)
if won_trades:
    for t in won_trades:
        excess = t['pnl'] - t['target']
        print(f"  ID:{t['id']:2} {t['symbol']:12} {t['signal']:4} Entry:₹{t['entry']:7.2f} Current:₹{t['current']:7.2f} PnL:{t['pnl']:+7.2f}% [+{excess:.2f}% above target] → CLOSE")
else:
    print("  ✓ None - no positions at target yet!")

print("\n" + "="*110)
print(f"SUMMARY: {len(loss_trades)} in loss | {len(building_trades)} building | {len(won_trades)} won")
print("="*110 + "\n")

if loss_trades:
    print("⚠️  RECOMMENDED AUTOMATIONS:")
    print("1. Auto-close trades that drop below -1.5% (severe losses)")
    print("2. Auto-reverse (open counter-position) when loss > -1% + price touches entry")
    print("3. Auto-scale-out when peaked >0% now in loss (half position, reduce exposure)")
    print("4. Detect mean-reversion patterns for loss trades (if price comes close to entry, opportunity)\n")
