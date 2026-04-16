"""Quick check of candle intervals in DB."""
from db_manager import CandleDatabase, Candle
from sqlalchemy import func

db = CandleDatabase()
s = db.Session()

for sym in ['RELIANCE', 'NIFTY', 'BANKNIFTY']:
    total = s.query(func.count(Candle.id)).filter(Candle.symbol == sym).scalar()
    if total == 0:
        print(f"{sym}: 0 candles")
        continue

    first = s.query(Candle).filter(Candle.symbol == sym).order_by(Candle.timestamp).first()
    last = s.query(Candle).filter(Candle.symbol == sym).order_by(Candle.timestamp.desc()).first()

    intraday = s.query(func.count(Candle.id)).filter(
        Candle.symbol == sym,
        func.extract('hour', Candle.timestamp) != 0
    ).scalar()
    daily = total - intraday

    print(f"\n=== {sym} ===")
    print(f"Total: {total} candles")
    print(f"Range: {first.timestamp} -> {last.timestamp}")
    print(f"Daily (hour=0): {daily}")
    print(f"Intraday (hour!=0): {intraday}")

    # Show first 5 timestamps
    rows = s.query(Candle.timestamp).filter(Candle.symbol == sym).order_by(Candle.timestamp).limit(5).all()
    print("First 5:", [str(r[0]) for r in rows])

    # Show last 5 timestamps
    rows = s.query(Candle.timestamp).filter(Candle.symbol == sym).order_by(Candle.timestamp.desc()).limit(5).all()
    print("Last 5:", [str(r[0]) for r in rows])

    # Show timestamps around transition (where intraday starts)
    if intraday > 0 and daily > 0:
        first_intraday = s.query(Candle).filter(
            Candle.symbol == sym,
            func.extract('hour', Candle.timestamp) != 0
        ).order_by(Candle.timestamp).first()
        print(f"First intraday candle: {first_intraday.timestamp}")

s.close()
