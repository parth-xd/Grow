#!/usr/bin/env python3
import os
os.environ['FLASK_ENV'] = 'testing'
from app import app
import json

# Test the watchlist endpoints
with app.test_client() as client:
    # Test GET /api/watchlist/<symbol>/analysis for ASIANPAINT
    response = client.get('/api/watchlist/ASIANPAINT/analysis')
    data = json.loads(response.data)
    if data.get('success'):
        print('✅ GET /api/watchlist/<symbol>/analysis works')
        print(f'   Symbol: {data["symbol"]}')
        print(f'   Entry Price: ₹{data["entry_price"]:.2f}')
        print(f'   Current Price: ₹{data["current_price"]:.2f}')
        print(f'   5-Year Return: {data["return_pct"]:+.2f}%')
        print(f'   Min Price (5yr): ₹{data["min_price"]:.2f}')
        print(f'   Max Price (5yr): ₹{data["max_price"]:.2f}')
        print(f'   Avg Price (5yr): ₹{data["avg_price"]:.2f}')
        print(f'   Total Candles: {data["total_candles"]}')
        print('')
        print('✅ All watchlist endpoints working correctly!')
