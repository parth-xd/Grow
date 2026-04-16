#!/usr/bin/env python3
"""Debug TCS prediction to understand low confidence"""

import sys
sys.path.insert(0, '/Users/parthsharma/Desktop/Grow')

import bot
import logging

logging.basicConfig(level=logging.WARNING)

symbol = 'TCS'
print(f"\n{'='*70}")
print(f"🔍 DEBUGGING: {symbol} Prediction Confidence")
print(f"{'='*70}\n")

# Get today's data
df = bot.fetch_historical(symbol, days=1, interval=5)
print(f"📊 Data collected:")
print(f"   Candles today: {len(df)}")
print(f"   Current price: ₹{df['close'].iloc[-1]:.2f}")
print(f"   Price range: {df['low'].min():.2f} - {df['high'].max():.2f}")

# Get full prediction
full_pred = bot.get_prediction(symbol)

print(f"\n🎯 FINAL PREDICTION:")
print(f"   Signal: {full_pred.get('signal')}")
print(f"   Confidence: {full_pred.get('confidence'):.2f}%")

print(f"\n📋 Full prediction details:")
for key, val in full_pred.items():
    if isinstance(val, dict):
        print(f"   {key}:")
        for k2, v2 in val.items():
            print(f"      {k2}: {v2}")
    elif isinstance(val, (int, float)):
        print(f"   {key}: {val:.4f}")
    else:
        print(f"   {key}: {val}")
