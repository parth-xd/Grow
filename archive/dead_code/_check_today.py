"""Check today's market data in DB."""
from db_manager import CandleDatabase, Candle
from sqlalchemy import func
from datetime import datetime

db = CandleDatabase()
s = db.Session()

today = '2026-04-01'

# Count candles by symbol for today
today_candles = s.query(
    Candle.symbol,
    func.count(Candle.id).label('count'),
    func.min(Candle.timestamp).label('first'),
    func.max(Candle.timestamp).label('last'),
    func.min(Candle.close).label('low'),
    func.max(Candle.close).label('high')
).filter(
    Candle.timestamp >= datetime.strptime(today, '%Y-%m-%d')
).group_by(Candle.symbol).order_by(func.count(Candle.id).desc()).all()

print(f'\nToday ({today}) - Candles by symbol:')
print('=' * 90)
for sym, cnt, first, last, low, high in today_candles:
    change = ((high - low) / low * 100) if low > 0 else 0
    print(f'{sym:15s} {cnt:3d} candles | {first.strftime("%H:%M")} → {last.strftime("%H:%M")} | Low ₹{low:8.2f} → High ₹{high:8.2f} ({change:+.2f}%)')

total = s.query(func.count(Candle.id)).filter(
    Candle.timestamp >= datetime.strptime(today, '%Y-%m-%d')
).scalar()

print('=' * 90)
print(f'Total candles for today: {total}')

if total > 0:
    print("\n✓ Yes, we have TODAY'S market movement data for multiple symbols")
else:
    print("\n✗ No today's data yet - likely after market hours")

s.close()
