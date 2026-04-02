#!/usr/bin/env python3
"""Inspect Screener.in P&L HTML structure"""
import requests, re

resp = requests.get(
    'https://www.screener.in/company/ASIANPAINT/consolidated/',
    headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'},
    timeout=15
)
html = resp.text

# Find section containing "Profit" near it
idx = html.find('Profit &amp; Loss')
if idx == -1:
    idx = html.find('profit-loss')
if idx == -1:
    idx = html.find('Profit &')
print(f"'Profit' found at index: {idx}")

if idx > 0:
    chunk = html[idx:idx+5000]
    # Print first 2000 chars of that section
    print("=== CHUNK ===")
    print(chunk[:3000])
else:
    # Try finding table headers
    print("Searching for date patterns...")
    for m in re.finditer(r'Mar.{0,10}20\d\d', html[:50000]):
        print(f"  Found: '{m.group()}' at {m.start()}")
    
    # Look for Sales
    for m in re.finditer(r'Sales', html[:100000]):
        ctx = html[max(0,m.start()-50):m.start()+200]
        print(f"\n  Sales ctx at {m.start()}: {repr(ctx[:150])}")
