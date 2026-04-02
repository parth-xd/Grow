#!/usr/bin/env python3
"""Temp script to inspect Screener.in P&L structure"""
import requests, re

resp = requests.get(
    'https://www.screener.in/company/ASIANPAINT/consolidated/',
    headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'},
    timeout=15
)
html = resp.text
print(f"Status: {resp.status_code}, Length: {len(html)}")

# Find the P&L section
pl = re.search(r'Profit &amp; Loss(.*?)</section>', html, re.DOTALL | re.IGNORECASE)
if not pl:
    pl = re.search(r'profit-loss(.*?)</section>', html, re.DOTALL | re.IGNORECASE)
if not pl:
    pl = re.search(r'id="profit-loss"(.*?)</section>', html, re.DOTALL | re.IGNORECASE)
    
if pl:
    section = pl.group(0)
    # Year headers
    years = re.findall(r'<th[^>]*>\s*((?:Mar|Dec|Sep|Jun)\s+\d{4}|TTM)\s*</th>', section)
    print("YEARS:", years)
    
    # Find rows with data
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', section, re.DOTALL)
    for row in rows[:20]:
        label_m = re.search(r'class="text"[^>]*>([^<]+)<', row)
        if not label_m:
            label_m = re.search(r'>([A-Za-z][^<]{2,30})<', row)
        cells = re.findall(r'<td[^>]*>\s*([\d,.-]+)\s*</td>', row)
        if label_m and cells:
            lbl = label_m.group(1).strip()[:30]
            print(f"  {lbl:30s} | {' | '.join(cells[-6:])}")
else:
    print("P&L section NOT FOUND")
    # Try to find any table headers with year dates
    all_years = re.findall(r'((?:Mar|Dec)\s+\d{4})', html)
    print("Year mentions:", list(set(all_years))[:10])
    
    # Try finding Sales row anywhere
    sales = re.search(r'(?:>Sales\s*<|>Revenue\s*<)(.*?)</tr>', html, re.DOTALL)
    if sales:
        cells = re.findall(r'<td[^>]*>([\d,]+)</td>', sales.group(0))
        print("Sales values:", cells)
