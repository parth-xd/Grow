#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/parthsharma/Desktop/Grow')

import bot
from datetime import datetime, date

# Clear cache
bot._predictors.clear()
bot._groww = None
bot._groww_token_cache = None

print("Testing predictions after collecting today's data...\n")

df = bot.fetch_historical("TCS", days=1, interval=5)

if not df.empty:
    first_ts = df.iloc[0]['datetime']
    last_ts = df.iloc[-1]['datetime']
    
    print(f"TCS TODAY'S DATA:")
    print(f"   Time range: {first_ts} to {last_ts}")
    print(f"   Total candles: {len(df)}")
    print(f"   Is today (Apr 2): {first_ts.date() == date.today()}")
    
    # Get new prediction
    pred = bot.get_prediction("TCS")
    print(f"\nNEW PREDICTION (based on today's market):")
    print(f"   Signal: {pred.get('signal')}")
    print(f"   Confidence: {pred.get('confidence'):.2f}")
    print(f"   Price: {pred.get('indicators', {}).get('price')}")
else:
    print("No today's data found")

print(f"\nCurrent time: {datetime.now()}")
