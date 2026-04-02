#!/usr/bin/env python3
"""Find the P&L table data in Screener.in"""
import requests, re, json

resp = requests.get(
    'https://www.screener.in/company/ASIANPAINT/consolidated/',
    headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'},
    timeout=15
)
html = resp.text

# Check for JSON data embedded in page
# Screener often uses data-* attributes or embedded JSON
for pattern in [r'data-result="([^"]+)"', r'"annual":\s*(\{[^}]+\})', r'var\s+data\s*=\s*(\{.*?\});']:
    m = re.search(pattern, html)
    if m:
        print(f"Found pattern: {pattern}")
        print(m.group(1)[:500])
        print()

# Look for the profit-loss section specifically
idx = html.find('id="profit-loss"')
if idx == -1:
    idx = html.find('profit-loss')
print(f"profit-loss id at: {idx}")
if idx > 0:
    section = html[idx:idx+8000]
    print(section[:4000])
else:
    # Search for table near "Profit & Loss"
    idx = html.find('Profit &amp; Loss')
    # Search forward for <table
    tidx = html.find('<table', idx)
    if tidx > 0:
        print(f"Table found at {tidx} ({tidx-idx} after P&L header)")
        print(html[tidx:tidx+3000])
    else:
        # Search for data-warehouse or api endpoint
        api_urls = re.findall(r'data-url="([^"]*(?:profit|annual|financial)[^"]*)"', html, re.IGNORECASE)
        print("API URLs found:", api_urls)
        
        # Search for script tags with data
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
        for i, s in enumerate(scripts):
            if 'Sales' in s or 'revenue' in s.lower() or 'profit' in s.lower():
                print(f"\nScript {i} has financial data:")
                print(s[:1000])
