#!/usr/bin/env python3
"""Extract full P&L table from Screener.in"""
import requests, re

resp = requests.get(
    'https://www.screener.in/company/ASIANPAINT/consolidated/',
    headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'},
    timeout=15
)
html = resp.text

# Find the profit-loss table
idx = html.find('id="profit-loss"')
section = html[idx:idx+30000]

# Extract year headers
years = re.findall(r'data-date-key="(\d{4}-\d{2}-\d{2})"', section)
year_labels = re.findall(r'>\s*((?:Mar|Jun|Sep|Dec)\s+\d{4})\s*<', section)
ttm = re.findall(r'>\s*(TTM)\s*<', section)
print("Year keys:", years)
print("Year labels:", year_labels)
print("TTM:", bool(ttm))

# Find </thead>...</table> to get rows
tbody = re.search(r'</thead>\s*(.*?)</table>', section, re.DOTALL)
if tbody:
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody.group(1), re.DOTALL)
    print(f"\n{len(rows)} rows found:\n")
    for row in rows[:20]:
        # Row label
        label_m = re.search(r'class="text"[^>]*>\s*(?:<[^>]*>)*\s*([^<]+)', row)
        label = label_m.group(1).strip() if label_m else '???'
        # Data cells
        cells = re.findall(r'<td[^>]*>\s*([\d,.-]+)\s*</td>', row)
        if cells:
            print(f"  {label:28s} | {' | '.join(c.rjust(8) for c in cells[-6:])}")
