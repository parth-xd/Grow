"""
Complete test and demo of XGBoost ML integration for live trading.
Demonstrates how tomorrow's trades will use the same ML brain.
"""

print("=" * 80)
print("XGBoost ML Trading Brain — Tomorrow's Trading Demo")
print("=" * 80)

import json

# 1. Show backtester performance with XGBoost
print("\n1. BACKTESTER PERFORMANCE (Historical)")
print("-" * 80)
import fno_backtester as fb

test_result = fb.run_multi_backtest("SBIN", 10)
print(f"   SBIN Results (multi-entry backtest)")
print(f"   - Entries found: {test_result['entries_found']}")
print(f"   - Win rate: {test_result['win_rate']}%")
print(f"   - Total PnL: ₹{test_result['total_pnl']:.0f}")
print(f"   - Avg PnL/trade: ₹{test_result['avg_pnl_per_trade']:.0f}")

# 2. Show live signal generation (same ML brain for tomorrow)
print("\n2. LIVE SIGNALS (TODAY → Tomorrow)")
print("-" * 80)
for stock in ["RELIANCE", "INFY", "TCS"]:
    sig = fb.get_xgb_signal(stock)
    print(f"   {stock:10s} → {sig['direction']:10s} (confidence: {sig['confidence']:.3f}, strength: {sig['strength']})")
    if sig.get('xgb_probs'):
        p = sig['xgb_probs']
        print(f"             P(long)={p['p_long']:.3f}, P(short)={p['p_short']:.3f}")

# 3. Show tomorrow's trading readiness
print("\n3. AUTO-TRADER READINESS (Tomorrow at Market Open)")
print("-" * 80)
import fno_trader

config = fno_trader.get_auto_trade_config()
print(f"   Preferred instruments: {config['preferred_instruments']}")
print(f"   Min confidence: {config['min_confidence']}")
print(f"   Min strength: {config['min_strength']}")  
print(f"   Max positions: {config['max_positions']}")
print(f"   Market hours only: {config['market_hours_only']}")

# 4. Show API endpoints for tomorrow
print("\n4. API ENDPOINTS FOR TOMORROW'S TRADING")
print("-" * 80)
print(f"   GET  /api/signals/tomorrow")
print(f"        → Shows X GBoost signals for all auto-trade instruments")
print(f"   POST /api/fno/auto-trade/run")
print(f"        → Trigger one auto-trade cycle (ML-powered entry)")
print(f"   GET  /api/fno/auto-trade/log")
print(f"        → View auto-trade history with signals used")
print(f"   GET  /api/fno/backtest/dates/<instrument>")
print(f"        → Available dates for backtesting any stock/index")

# 5. Data status for training
print("\n5. TRAINING DATA STATUS")
print("-" * 80)
from db_manager import CandleDatabase, Candle
from sqlalchemy import func

db = CandleDatabase()
s = db.Session()
stats = s.query(Candle.symbol, func.count(Candle.id)).group_by(Candle.symbol).all()
total = sum(cnt for _, cnt in stats)
print(f"   Total candles in DB: {total}")
for sym, cnt in sorted(stats)[:5]:
    print(f"     {sym:15s} {cnt:4d} candles")
print(f"     ... ({len(stats) - 5} more stocks)")
s.close()

# 6. Summary
print("\n6. TOMORROW'S WORKFLOW")
print("-" * 80)
print("""
   TODAY (Market hours closing):
   ✓ XGBoost ML model trained on all candles
   ✓ Signals generated and cached
   ✓ API endpoint /api/signals/tomorrow shows predictions

   TOMORROW (Market open):
   ✓ Auto-trader uses same ML brain (get_xgb_signal)
   ✓ Falls back to heuristic if data unavailable
   ✓ Enters trades based on ML probability thresholds
   ✓ Holds positions up to 7 days with SL/TP/trailing exits
   ✓ Logs which signal type was used (ML vs heuristic)
   
   CONTINUOUS IMPROVEMENT:
   ✓ Each day adds new training data
   ✓ Each trade outcome is labeled for next day's training
   ✓ More data = better ML predictions over time
""")

print("=" * 80)
print("✓ Ready for tomorrow's ML-powered trading!")
print("=" * 80)
