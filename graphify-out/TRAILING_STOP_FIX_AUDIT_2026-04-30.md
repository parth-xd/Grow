# Trailing Stop Fix Audit Report

Date: 2026-04-30

## Scope

This audit covers two changes made on 2026-04-30 to fix the paper trade trailing stop logic:

1. `paper_trader.py` — `PaperTradeTracker.update_trailing_stop()`
2. `trailing_stop.py` — `check_and_close_trades_on_loss()`

## Bug Description

### Root Cause

`update_trailing_stop()` set `trailing_stop = current_price - 1.5` on every poll without checking the previous value. When the price dropped, the trailing stop dropped with it, so the trade never closed.

Example with old code (entry at ₹100):

| Price | PnL% | Trailing Stop |
|-------|------|---------------|
| 108   | +8%  | 106.50        |
| 107   | +7%  | **105.50** ← dropped |
| 104   | +4%  | **102.50** ← dropped |
| 102   | +2%  | **100.50** ← dropped |
| 100   | 0%   | 100.50 → finally closed at breakeven |

The trader gave back almost all profit (₹8 → ₹0) before closing.

### Second Issue

`check_and_close_trades_on_loss()` in `trailing_stop.py` never read the `trailing_stop` field from the trade. It used its own separate `peak_pnl` percentage-based system. The two systems were completely disconnected.

## Changes Made

### 1. `paper_trader.py` — Lines 231-268

**Before:**
```python
trade['trailing_stop'] = round(current_price - TRAILING_BUFFER, 2)
```

**After:**
```python
new_stop = round(current_price - TRAILING_BUFFER, 2)
old_stop = trade.get('trailing_stop')
trade['trailing_stop'] = max(new_stop, old_stop) if old_stop is not None else new_stop
```

Same fix applied for SELL trades using `min()` instead of `max()`.

Also removed duplicate `return None` on old line 262.

### 2. `trailing_stop.py` — Lines 247-262 (new CHECK 0.5)

Added a new check between CHECK 0 (hard stop loss) and CHECK 1 (breakeven floor) that reads `trade.get('trailing_stop')` and closes the trade if price breaches it.

**New check priority order:**
1. Target Hit
2. CHECK 0: Hard Stop Loss (`trade['stop_loss']`)
3. **CHECK 0.5: Trailing Stop Field** (`trade['trailing_stop']`) ← NEW
4. CHECK 1: Breakeven Floor
5. CHECK 2: Peak Profit Erosion (percentage-based)

## Verification — Nothing Broken

### Function Signatures (verified via import)

All four function signatures are unchanged:

| Function | Signature |
|----------|-----------|
| `PaperTradeTracker.update_trailing_stop` | `(self, trade_id, current_price)` |
| `PaperTradeTracker.close_trade` | `(self, trade_id, exit_price, exit_reason='manual')` |
| `check_and_close_trades_on_loss` | `(paper_trades_file='paper_trades.json', live_prices=None)` |
| `manage_loss_positions` | `(paper_trades_file='paper_trades.json', live_prices=None)` |

### Return Values (unchanged)

| Function | Returns | Change |
|----------|---------|--------|
| `update_trailing_stop` | `'trailing_updated'` or `None` | No change |
| `check_and_close_trades_on_loss` | `list[dict]` of closed trades | No change to shape |
| `manage_loss_positions` | Not modified | Not touched |

### All Callers Audited

| Caller | File | Line | Impact |
|--------|------|------|--------|
| `bot.monitor_and_update_trailing_stops()` | bot.py | 1193 | Calls `tracker.update_trailing_stop(trade_id, current_price)` — same signature, same return values. **No impact.** |
| `POST /api/update-trailing-stops` | app.py | 3637 | Calls `tracker.update_trailing_stop(trade['id'], current_price)` — same signature. **No impact.** |
| `bot.auto_trade()` | bot.py | 1251 | Calls `monitor_and_update_trailing_stops()` which wraps `update_trailing_stop`. **No impact.** |
| `_task_auto_close_trades()` | scheduler.py | 704 | Calls `check_and_close_trades_on_loss(file, prices)` — same signature. **No impact.** |
| `POST /api/auto-close/check` | app.py | 4294 | Calls `check_and_close_trades_on_loss(file, prices)` — same signature. **No impact.** |

### Frontend Display (unchanged)

`index.html` lines 7819-7823 read `t.trailing_stop` for display. Since the field name is unchanged and the value is now correct (only ratchets up), the UI will show the correct locked-in trailing stop price. **No impact.**

### Reconciliation Layer (unchanged)

`paper_trade_reconciliation.py` line 262 reads `tracker_trade.get("trailing_stop")` and passes it through to the canonical view. **No impact.**

### Data Shape (unchanged)

The `trailing_stop` field in `paper_trades.json` remains a float or null. No new fields were added. No fields were removed. Existing trades with `trailing_stop: null` will work correctly because of the `if old_stop is not None` guard.

## Simulation Proof

Simulation with entry at ₹100 and price sequence [101, 103, 105, 108, 107, 104]:

**Fixed code:**

| Price | PnL% | New Stop | Final Stop | Result |
|-------|------|----------|------------|--------|
| 101   | 1%   | 99.50    | 99.50      | |
| 103   | 3%   | 101.50   | 101.50     | |
| 105   | 5%   | 103.50   | 103.50     | |
| 108   | 8%   | 106.50   | **106.50** | Peak |
| 107   | 7%   | 105.50   | **106.50** | Locked! |
| 104   | 4%   | 102.50   | **106.50** | **CLOSED** (₹104 ≤ ₹106.50) |

Trade closed at ₹104 with +4% profit locked in. Under old code, the stop would have fallen to ₹102.50 and the trade would have kept bleeding.

## Existing Checks Preserved

All pre-existing closing logic remains fully intact:

- **Target Hit** — `current_price >= projected_exit` → unchanged
- **Hard Stop Loss** — `current_price <= stop_loss` → unchanged
- **Breakeven Floor** — `current_price <= breakeven AND pnl <= 0` → unchanged
- **Peak Erosion checks** — `ULTRA_TIGHT_TRAILING`, `TIGHT_TRAILING`, `LOOSE_TRAILING`, `PEAK_EROSION_50` → unchanged
- **Manual trade protection** — `can_system_close_trade()` → unchanged
- **Loss management** — `manage_loss_positions()` → not modified at all
- **Intraday candle fetch on close** — `_fetch_trade_candles()` → unchanged
- **Journal sync on tracker close** — `close_matching_paper_trade()` → unchanged

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Trailing stop triggers too early on volatile stocks | Low | ₹1.50 buffer unchanged; existing percentage-based checks (CHECK 2) provide additional layer |
| Old trades with stale `trailing_stop` values trigger immediate close | None | CHECK 0.5 only fires when `trailing_stop is not None` AND price crosses it. Old closed trades have `status != 'OPEN'` so they're skipped. |
| Null/missing `trailing_stop` field on legacy trades | None | Guarded by `if ts is not None` in CHECK 0.5 and `if old_stop is not None` in `update_trailing_stop()` |

## Files Changed

- `paper_trader.py` — `update_trailing_stop()` method (lines 231-268)
- `trailing_stop.py` — `check_and_close_trades_on_loss()` function (new lines 247-262)

## Conclusion

The fix is backward-compatible, preserves all existing close paths, and correctly implements the ratcheting trailing stop that the user intended. No function signatures, return values, data shapes, or caller contracts were changed.
