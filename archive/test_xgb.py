"""Test XGBoost-powered backtester."""
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

import fno_backtester as fb

# Single test
print('=== Single Backtest: RELIANCE ===')
r = fb.run_fno_backtest('RELIANCE')
ts = r.get('trade_simulation', {})
a = r.get('analysis', {})
print(f"Entry: {r.get('entry_label')} @ Rs{r.get('entry_price')}")
print(f"Direction: {a.get('direction')} ({a.get('strength')})")
print(f"Confidence: {a.get('confidence')}")
print(f"Days held: {r.get('days_held')}")
print(f"Exit: {ts.get('exit_reason')}")
print(f"PnL: Rs{ts.get('total_pnl')} ({ts.get('total_pnl_pct')}%)")
print(f"XGB probs: {a.get('xgb_probs')}")
print()

# Multi test
print('=== Multi Backtest: RELIANCE ===')
m = fb.run_multi_backtest('RELIANCE', 10)
print(f"Entries found: {m.get('entries_found')}")
print(f"Win rate: {m.get('win_rate')}%")
print(f"Total PnL: Rs{m.get('total_pnl')}")
for x in m.get('results', []):
    print(f"  {x['date']} {x['direction']} days={x['days_held']} pnl=Rs{x['pnl']} exit={x['exit_reason']}")
print()

# Test across ALL 16 stocks
print('=== ALL 16 Stocks Results ===')
total_pnl = 0
total_wins = 0
total_trades = 0
all_stocks = list(fb.BACKTEST_INSTRUMENTS.keys())
for stock in all_stocks:
    m = fb.run_multi_backtest(stock, 10)
    entries = m.get('entries_found', 0)
    wr = m.get('win_rate', 0)
    pnl = m.get('total_pnl', 0)
    wins = m.get('wins', 0)
    trades = m.get('trades_taken', 0)
    total_pnl += pnl
    total_wins += wins
    total_trades += trades
    print(f"  {stock:15s} entries={entries} wins={wins}/{trades} wr={wr}% pnl=Rs{pnl:.0f}")

print(f"\nOVERALL: {total_wins}/{total_trades} wins ({total_wins/total_trades*100:.0f}%) Total PnL: Rs{total_pnl:.0f}")
