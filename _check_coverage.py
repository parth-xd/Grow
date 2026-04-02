"""Check today's data coverage."""
from db_manager import CandleDatabase, Candle
from datetime import datetime

db = CandleDatabase()
s = db.Session()

# Get all unique symbols
all_syms_list = [r[0] for r in s.query(Candle.symbol).distinct().order_by(Candle.symbol).all()]
print(f'Total unique symbols in DB: {len(all_syms_list)}')
print(f'All symbols: {", ".join(all_syms_list)}')

# Get symbols with TODAY data
today_syms_list = [r[0] for r in s.query(Candle.symbol).distinct().filter(
    Candle.timestamp >= datetime.strptime('2026-04-01', '%Y-%m-%d')
).order_by(Candle.symbol).all()]
print(f'\nSymbols with TODAY data: {len(today_syms_list)}')
print(f'Today symbols: {", ".join(today_syms_list)}')

# Missing today's data
missing = set(all_syms_list) - set(today_syms_list)
if missing:
    print(f'\n❌ Symbols WITHOUT today data ({len(missing)}):')
    for sym in sorted(missing):
        print(f'  - {sym}')

s.close()
