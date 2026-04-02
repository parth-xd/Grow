#!/usr/bin/env python3
"""Verify the Flask API is responding with all new instruments."""

import subprocess
import time

print("Testing Flask API...")
time.sleep(2)

try:
    result = subprocess.run(
        ["curl", "-s", "http://localhost:8000/api/fno/backtest/instruments"],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    if result.returncode == 0:
        import json
        data = json.loads(result.stdout)
        total = data.get('total', 0)
        indices = len(data.get('indices', {}))
        stocks = len(data.get('stocks', {}))
        
        print(f"✓ API responding!")
        print(f"  Total instruments: {total}")
        print(f"  Indices: {indices}")
        print(f"  Stocks: {stocks}")
    else:
        print(f"✗ API error: {result.stderr}")
except Exception as e:
    print(f"✗ Connection error: {e}")
