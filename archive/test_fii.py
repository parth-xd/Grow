#!/usr/bin/env python3
"""Test that FII data is being added to analysis"""

import sys
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Import required modules
from portfolio_analyzer import _analyze_stock

# Mock functions for testing
def mock_get_prediction(symbol, **kwargs):
    return {
        "signal": "HOLD",
        "confidence": 0.5,
        "combined_score": 0.0,
        "sources": {},
        "indicators": {},
        "long_term_trend": {}
    }

def mock_fetch_live_price(symbol, **kwargs):
    return {"ASIANPAINT": 2165.2, "SUZLON": 39.56, "GEMAROMA": 138.06}.get(symbol, 100)

# Get Groww API for testing
from bot import _get_groww
try:
    groww_api = _get_groww()
except:
    groww_api = None

# Test analyze_stock for ASIANPAINT
print("Testing _analyze_stock for ASIANPAINT...")
result = _analyze_stock(
    symbol="ASIANPAINT",
    quantity=16,
    avg_price=2286.39,
    source="holding",
    get_prediction_fn=mock_get_prediction,
    fetch_live_price_fn=mock_fetch_live_price,
    groww_api=groww_api
)

# Check for FII fields
fii_fields = [k for k in result.keys() if 'fii' in k.lower() or 'shareholding' in k.lower() or 'mf' in k.lower()]
print(f"\n✅ FII/Share fields found: {fii_fields}")
print(f"📋 shareholding_summary: {result.get('shareholding_summary')}")
print(f"📈 fii_signal: {result.get('fii_signal')}")
print(f"📊 mf_signal: {result.get('mf_signal')}")

if 'shareholding_summary' in result:
    print("\n✅ SUCCESS! FII data is being added to analysis!")
else:
    print("\n❌ FAIL: FII data not found in result")
    print(f"\nAll result keys: {list(result.keys())}")
