#!/usr/bin/env python3
"""
PAPER TRADING TRACKER — Unified trading engine with pre/post trade analysis and hedging
- Integrates bot.py predictions for pre-trade reasoning
- Supports multiple positions per symbol (hedging)
- Records full trade journal with before/after analysis
- Handles signal reversals (opens opposite position without closing existing)
"""

import sys
import json
import os
import logging
from datetime import datetime, timedelta
import pytz

sys.path.insert(0, '/Users/parthsharma/Desktop/Grow')

import bot
from config import WATCHLIST, CONFIDENCE_THRESHOLD, TARGET_PCT, STOP_LOSS_PCT

ist = pytz.timezone('Asia/Kolkata')
logger = logging.getLogger(__name__)


def is_paper_trading_enabled():
    """Check if paper trading is enabled in the database config"""
    try:
        from db_manager import get_config
        enabled = get_config("paper_trading", "false").lower() == "true"
        return enabled
    except:
        # If DB not available, assume disabled
        return False


class PaperTradeTracker:
    """Track paper trades with entry, exit targets, and actual results"""
    
    def __init__(self, filename='paper_trades.json'):
        self.filename = os.path.join('/Users/parthsharma/Desktop/Grow', filename)
        self.trades = self._load_trades()
    
    def _load_trades(self):
        """Load existing trades from file"""
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_trades(self):
        """
        Persist under an exclusive lock, MERGING rather than blind-overwriting.

        This class loads the whole file at __init__ and previously wrote its
        whole in-memory list back, so any field another writer had added in the
        meantime was silently dropped. trailing_stop.py owns `peak_pnl` and
        this class does not even know the key exists — so every save deleted
        it, and the next trailing pass saw `peak_pnl` missing and reset it to
        the CURRENT P&L. That is exactly the fingerprint on MARUTI: stored
        peak_pnl -0.5553% (the final exit P&L) while highest_price_reached
        13826 proved the true peak was +1.016%. With peak_pnl corrupted
        negative, the profit-protection checks never armed.

        Locking the read-modify-write and merging per trade_id means a writer
        can only ever add or update its own fields, never erase another's.
        """
        import fcntl
        lock_path = self.filename + ".lock"
        try:
            with open(lock_path, "w") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    disk = []
                    if os.path.exists(self.filename):
                        with open(self.filename, "r") as f:
                            disk = json.load(f) or []
                    by_id = {t.get("id"): t for t in disk if isinstance(t, dict)}
                    for t in self.trades:
                        tid = t.get("id")
                        if tid in by_id:
                            merged = dict(by_id[tid])   # start from disk
                            merged.update(t)            # our updates win
                            by_id[tid] = merged
                        else:
                            by_id[tid] = t
                    out = list(by_id.values())
                    with open(self.filename, "w") as f:
                        json.dump(out, f, indent=2, default=str)
                    self.trades = out
                    return
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            logger.warning("locked save failed (%s) — falling back to plain write", e)
        self._save_trades_unlocked()

    def _save_trades_unlocked(self):
        """Save trades to file"""
        with open(self.filename, 'w') as f:
            json.dump(self.trades, f, indent=2, default=str)
    
    def record_entry(self, symbol, signal, confidence, entry_price, quantity=1, prediction=None,
                     exit_reason=None, model_source=None):
        """
        Record a new trade entry with trailing stop setup.

        Args:
            symbol: Trading symbol
            signal: BUY or SELL
            confidence: Model confidence (0-1)
            entry_price: Entry price
            quantity: Number of shares
            prediction: Dict with ML/news/market signals from bot.py
            exit_reason: Why trade is being entered
            model_source: Which model produced this signal —
                'GradientBoosting' or 'XGBoost'. Recorded on every trade so
                the two cash models' live performance can be compared
                directly. Falls back to prediction['model_source'] when the
                caller doesn't pass it explicitly, and finally to
                'GradientBoosting' (the only model that existed before the
                XGB addition, so unattributed trades are attributable to it).
        """
        
        # Calculate cost coverage price (0.06% for entry+exit charges)
        cost_buffer = 0.0006  # 0.06%
        cost_coverage_price = entry_price * (1 + cost_buffer) if signal == 'BUY' else entry_price * (1 - cost_buffer)
        
        # Generate trade ID
        now = datetime.now(ist)
        trade_id = f"{symbol}-{signal[0]}-{now.strftime('%Y%m%d%H%M%S%f')}"
        
        stop_loss = entry_price * (1 - STOP_LOSS_PCT / 100) if signal == 'BUY' else entry_price * (1 + STOP_LOSS_PCT / 100)
        # RULE 1: hard ceiling of MAX_CASH_SL_PCT (1%) on the initial stop, and
        # breakeven priced for THIS quantity.
        import trailing_strategy as _tstrat
        _be_seed = _tstrat.build_trade(entry_price, quantity, signal,
                                       stop_loss=stop_loss, symbol=symbol)
        stop_loss = _be_seed['stop_loss']
        projected_exit = entry_price * (1 + TARGET_PCT / 100) if signal == 'BUY' else entry_price * (1 - TARGET_PCT / 100)

        if model_source is None:
            model_source = (prediction or {}).get('model_source') or 'GradientBoosting'

        trade = {
            'id': trade_id,
            'symbol': symbol,
            'signal': signal,
            'side': signal,
            'model_source': model_source,
            'confidence': float(confidence),
            'entry_price': float(entry_price),
            'quantity': quantity,
            'entry_time': now.isoformat(),
            'stop_loss': round(float(stop_loss), 2),
            # Stamped at ENTRY so the trailing logic uses the figure this
            # position was actually sized against (breakeven is size-dependent:
            # fixed brokerage/DP do not scale with quantity).
            'breakeven_pct': _be_seed['breakeven_pct'],
            'breakeven_price': _be_seed['breakeven_price'],
            'projected_exit': round(float(projected_exit), 2),
            'entry_profit_target': TARGET_PCT if signal == 'BUY' else -TARGET_PCT,
            
            # ── TRAILING STOP CONFIGURATION ──
            'cost_coverage_price': float(cost_coverage_price),  # When costs are covered
            'highest_price_reached': float(entry_price),  # Track highest price for trailing
            'trailing_stop': None,  # Will be set once costs covered
            'has_covered_costs': False,  # Flag when cost coverage price is hit
            'costs_covered_at_price': None,
            'costs_covered_at_time': None,
            
            # ── PRE-TRADE ANALYSIS ──
            'pre_trade': {
                'ml_signal': prediction.get('ml', {}).get('signal') if prediction else None,
                'ml_confidence': prediction.get('ml', {}).get('confidence') if prediction else None,
                'news_signal': prediction.get('news', {}).get('signal') if prediction else None,
                'news_score': prediction.get('news', {}).get('avg_score') if prediction else None,
                'market_signal': prediction.get('market_context', {}).get('market_signal') if prediction else None,
                'combined_score': prediction.get('combined_score') if prediction else None,
                'reason_summary': prediction.get('reason') if prediction else None,
            },
            
            # ── POST-TRADE (filled when closed) ──
            'exit_price': None,
            'exit_time': None,
            'actual_profit_pct': None,
            'net_pnl': None,
            'gross_pnl': None,
            'total_charges': None,
            'exit_reason': None,
            'status': 'OPEN',  # OPEN, CLOSED, HIT_TARGET, HIT_SL
            'post_trade': None,
        }

        # BREAKEVEN, COMPUTED AT ENTRY.
        #
        # This is the price at which the trade stops losing money, and it is
        # specific to THIS position: fixed charges (brokerage, DP) do not scale
        # with quantity, so 2 shares and 10 shares of the same stock have very
        # different breakevens (1.029% vs 0.383% on a Rs3,900 name).
        #
        # Computed here, at the moment quantity and price are both known,
        # rather than lazily on the first trailing-stop check. Two reasons:
        # the figure is a property of the trade and belongs on the record, and
        # computing it later means the first few checks run without it — the
        # window in which a small position can erode straight back through
        # cost with nothing armed.
        #
        # Never fatal: a missing breakeven degrades the trailing arm threshold,
        # it must not block recording a trade that has already been placed.
        try:
            from trailing_stop import calculate_breakeven_price, breakeven_pct_for
            trade['breakeven_price'] = round(
                calculate_breakeven_price(entry_price, signal, quantity=quantity), 2)
            trade['breakeven_pct'] = round(breakeven_pct_for(entry_price, quantity), 4)
        except Exception as e:
            logger.warning("Could not compute breakeven at entry for %s: %s", symbol, e)
            trade['breakeven_price'] = None
            trade['breakeven_pct'] = None

        self.trades.append(trade)
        self._save_trades()
        return trade
    
    def close_trade(self, trade_id, exit_price, exit_reason="manual"):
        """
        Close a trade with actual exit price.
        
        Args:
            trade_id: Trade ID
            exit_price: Actual exit price
            exit_reason: Why trade was closed ("trailing_stop_hit", "manual", "target_hit", etc.)
        """
        for trade in self.trades:
            if trade['id'] == trade_id and trade['status'] == 'OPEN':
                trade['exit_price'] = float(exit_price)
                trade['exit_time'] = datetime.now(ist).isoformat()
                trade['exit_reason'] = exit_reason
                
                # Calculate actual P&L with the same charge model used by the journal.
                if trade['signal'] == 'BUY':
                    profit_pct = ((exit_price - trade['entry_price']) / trade['entry_price']) * 100
                    pnl_info = bot.costs.net_profit(trade['entry_price'], exit_price, trade['quantity'])
                else:  # SELL
                    profit_pct = ((trade['entry_price'] - exit_price) / trade['entry_price']) * 100
                    pnl_info = bot.costs.net_profit(exit_price, trade['entry_price'], trade['quantity'])

                gross_pnl = pnl_info['gross_profit']
                total_charges = pnl_info['total_charges']
                net_pnl = pnl_info['net_profit']
                
                trade['actual_profit_pct'] = round(profit_pct, 2)
                trade['gross_pnl'] = round(gross_pnl, 2)
                trade['total_charges'] = round(total_charges, 2)
                trade['net_pnl'] = round(net_pnl, 2)
                
                # Determine status
                if exit_reason == "trailing_stop_hit":
                    trade['status'] = 'CLOSED'  # Trailing stop triggered
                elif exit_reason == "target_hit":
                    trade['status'] = 'HIT_TARGET'
                # Was a hardcoded * 0.98 (2%), which went stale the moment RULE 1
                # capped the initial stop at 1%. Reads the stop actually armed on
                # THIS trade instead of assuming a percentage.
                elif exit_reason == "stop_loss_hit" or exit_price <= trade.get(
                        'stop_loss', trade['entry_price'] * 0.99):
                    trade['status'] = 'HIT_SL'
                else:
                    trade['status'] = 'CLOSED'
                
                # Build post-trade analysis
                duration_minutes = round((datetime.fromisoformat(trade['exit_time']) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 60, 1)
                
                trade['post_trade'] = {
                    'gross_pnl': trade['gross_pnl'],
                    'net_pnl': trade['net_pnl'],
                    'total_charges': trade['total_charges'],
                    'profit_pct': trade['actual_profit_pct'],
                    'duration_minutes': duration_minutes,
                    'profitable': net_pnl > 0,
                    'exit_reason': exit_reason,
                }
                
                # Record when costs were covered (if still tracked)
                if trade.get('has_covered_costs'):
                    trade['post_trade']['costs_covered_at_price'] = trade['costs_covered_at_price']
                    trade['post_trade']['costs_covered_at_time'] = trade['costs_covered_at_time']
                
                self._save_trades()
                
                # 🔥 NEW: SYNC TO TRADE JOURNAL — so journal status updates when trade closes!
                try:
                    import trade_journal
                    
                    # Map paper trade exit reason to journal exit reason
                    journal_exit_reason = 'MANUAL_EXIT'
                    if exit_reason == "trailing_stop_hit":
                        journal_exit_reason = 'HIT_SL'
                    elif exit_reason == "target_hit":
                        journal_exit_reason = 'HIT_TARGET'
                    elif exit_reason == "stop_loss_hit":
                        journal_exit_reason = 'HIT_SL'
                    elif exit_reason == "prediction_change":
                        journal_exit_reason = 'SIGNAL_REVERSED'
                    
                    # Find and close the corresponding trade journal entry
                    journal_entry = trade_journal.close_matching_paper_trade(
                        trade_id=trade_id,
                        symbol=trade.get('symbol'),
                        side=trade.get('side') or trade.get('signal'),
                        quantity=trade.get('quantity'),
                        entry_price=trade.get('entry_price'),
                        entry_time=trade.get('entry_time'),
                        exit_price=float(exit_price),
                        exit_reason=journal_exit_reason,
                    )
                    if journal_entry:
                        logger.info("✓ Synced paper trade closure %s to trade journal", trade_id)
                    else:
                        logger.error("❌ Paper trade closure %s could not be synced to trade journal (no journal entry created)", trade_id)
                except Exception as e:
                    logger.error(f"❌ CRITICAL: Failed to sync paper trade closure {trade_id} to journal: {e}", exc_info=True)
                
                return trade
        
        return None
    
    def update_trailing_stop(self, trade_id, current_price):
        """
        DELEGATES to trailing_strategy — no longer computes its own stop.

        This used to write a `trailing_stop` price from a flat 1.5%-of-price
        buffer with no breakeven floor and no cap against the profit actually
        made. On MARUTI that produced 13826 * 0.985 = 13618.61 — 68.39 below
        entry and 120.01 below breakeven — so the "profit-protecting" stop
        could only ever realise a loss. Meanwhile trailing_stop.py was running
        a second, different calculation. Two writers, two answers, one file.

        The signature and return value are unchanged so every existing caller
        keeps working; only the authority behind the number has moved.
        """
        import trailing_strategy
        for trade in self.trades:
            if trade['id'] == trade_id and trade.get('status') == 'OPEN':
                if not trade.get('breakeven_pct') or not trade.get('breakeven_price'):
                    seed = trailing_strategy.build_trade(
                        trade.get('entry_price'), trade.get('quantity') or 1,
                        trade.get('signal', 'BUY'), stop_loss=trade.get('stop_loss'),
                        symbol=trade.get('symbol', ''))
                    trade.setdefault('breakeven_pct', seed['breakeven_pct'])
                    trade.setdefault('breakeven_price', seed['breakeven_price'])
                    trade['stop_loss'] = seed['stop_loss']
                res = trailing_strategy.evaluate(trade, current_price, confidence_fn=None)
                trade.update(res["state"])
                self._save_trades()
                return 'trailing_updated'
        return None
    
    def get_open_positions(self, symbol=None):
        """Get all open trades, optionally filtered by symbol"""
        open_trades = [t for t in self.trades if t['status'] == 'OPEN']
        if symbol:
            open_trades = [t for t in open_trades if t['symbol'] == symbol]
        return open_trades


def get_live_price(symbol):
    """
    Get the current live price for a symbol (FYERS, via bot.fetch_live_price).

    The Groww 5-minute-candle fallback that used to live here has been
    removed: it constructed its own GrowwAPI client directly, which made it
    a second, hidden market-data path that would have kept quietly serving
    Groww prices into paper-trade fills after the migration. Returns None on
    failure — every caller already handles a None price.
    """
    try:
        from bot import fetch_live_price as bot_fetch_live_price
        price = bot_fetch_live_price(symbol)
        if price and price > 0:
            return float(price)
        print(f"[get_live_price] No FYERS price available for {symbol}")
    except Exception as e:
        print(f"[get_live_price] FYERS LTP fetch failed for {symbol}: {e}")

    return None


def main():
    print("\n" + "=" * 90)
    print("PAPER TRADING — Simulating Trades with Entry, Projected Exit & Actual Results")
    print("=" * 90)
    
    # Check if paper trading is enabled
    if not is_paper_trading_enabled():
        print("\n⛔ Paper trading is DISABLED")
        print("Enable it in the dashboard: Paper Trading tab → Toggle ON")
        sys.exit(1)
    
    # Check market hours
    now = datetime.now(ist)
    print(f"\n⏰ Time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
    
    if now.weekday() >= 5:
        print("❌ Market closed (weekend)")
        sys.exit(1)
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    if now < market_open:
        print(f"⏳ Market opens at 09:15 IST")
        sys.exit(0)
    
    if now > market_close:
        print("🔚 Market closed for the day")
        print("Updating all trades with actual closing prices...\n")
        
        # UPDATE TRADES WITH CLOSING PRICES
        tracker = PaperTradeTracker()
        
        if not tracker.trades:
            print("No trades to update")
            sys.exit(0)
        
        bot._predictors.clear()
        
        for trade in tracker.trades:
            if trade['status'] != 'OPEN':
                continue
            
            symbol = trade['symbol']
            
            try:
                df = bot.fetch_historical(symbol, days=1, interval=5)
                if not df.empty:
                    closing_price = df['close'].iloc[-1]
                    tracker.close_trade(trade['id'], closing_price)
            except:
                pass
        
        # PRINT SUMMARY
        print(f"\n{'-'*90}")
        print("TODAY'S TRADE SUMMARY")
        print(f"{'-'*90}\n")
        
        total_pnl = 0
        winners = 0
        losers = 0
        
        for trade in tracker.trades:
            if trade['exit_price'] is None:
                continue
            
            entry = trade['entry_price']
            exit_p = trade['exit_price']
            target = trade['projected_exit']
            pnl = trade['actual_profit_pct']
            
            # Emoji indicators
            if pnl > 0:
                emoji = "✅"
                winners += 1
            else:
                emoji = "❌"
                losers += 1
            
            if trade['status'] == 'HIT_TARGET':
                status_str = "🎯 TARGET"
            elif trade['status'] == 'HIT_SL':
                status_str = "🛑 SL"
            else:
                status_str = "📊 CLOSED"
            
            print(f"{emoji} {trade['symbol']:10} {trade['signal']:4} @ {entry:8.2f} → {exit_p:8.2f}")
            print(f"   Target: {target:8.2f} | Actual P&L: {pnl:+.2f}% | {status_str}")
            
            total_pnl += pnl
        
        win_rate = (winners / (winners + losers) * 100) if (winners + losers) > 0 else 0
        
        print(f"\n{'-'*90}")
        print(f"📈 Total P&L: {total_pnl:+.2f}% | Win rate: {win_rate:.1f}% ({winners}W/{losers}L)")
        print(f"{'-'*90}\n")
        
        sys.exit(0)
    
    print("✅ Market OPEN — Executing paper trades\n")
    
    # ─────────────────────────────────────────────────────────────────────────────
    # COLLECT SIGNALS
    # ─────────────────────────────────────────────────────────────────────────────
    
    print(f"{'-'*90}")
    print("GENERATING SIGNALS")
    print(f"{'-'*90}\n")
    
    signals = []
    bot._predictors.clear()
    
    for symbol in WATCHLIST[:5]:
        try:
            # Use 5-minute candles (Groww API doesn't support 1-minute)
            df = bot.fetch_historical(symbol, days=1, interval=1)
            if df.empty:
                continue
            
            pred = bot.get_prediction(symbol)
            signal = pred.get('signal')
            confidence = pred.get('confidence', 0)
            
            # Get LIVE current price instead of stale historical close
            live_price = get_live_price(symbol)
            if live_price is None:
                # Fallback to historical close only if live price unavailable
                live_price = df['close'].iloc[-1]
            
            if signal != 'HOLD' and confidence >= 0.40:  # Paper trading at lower threshold
                signals.append({
                    'symbol': symbol,
                    'signal': signal,
                    'confidence': confidence,
                    'price': live_price,
                })
        except:
            pass
    
    if not signals:
        print("❌ No signals generated today")
        sys.exit(0)
    
    # ─────────────────────────────────────────────────────────────────────────────
    # RECORD TRADES
    # ─────────────────────────────────────────────────────────────────────────────
    
    tracker = PaperTradeTracker()
    
    print(f"{'-'*90}")
    print(f"RECORDING {len(signals)} PAPER TRADES")
    print(f"{'-'*90}\n")
    
    for sig in signals:
        trade = tracker.record_entry(
            symbol=sig['symbol'],
            signal=sig['signal'],
            confidence=sig['confidence'],
            entry_price=sig['price'],
            quantity=1
        )
        
        if trade:
            conf_pct = sig['confidence'] * 100
            target = trade['projected_exit']
            sl = trade['stop_loss']
            
            # Validate trade is realistic
            df = bot.fetch_historical(sig['symbol'], days=1, interval=5)
            if not df.empty:
                day_high = df['high'].max()
                day_low = df['low'].min()
                
                # Check if entry price is within day's range
                if sig['price'] > day_high or sig['price'] < day_low:
                    print(f"⚠️  {sig['symbol']}")
                    print(f"   {sig['signal']:4} @ ₹{sig['price']:.2f} (UNREALISTIC)")
                    print(f"   Day Range: ₹{day_low:.2f} - ₹{day_high:.2f}")
                    print(f"   Entry price is outside today's range. Check live data.\n")
                else:
                    print(f"📊 {sig['symbol']}")
                    print(f"   {sig['signal']:4} @ ₹{sig['price']:.2f} | Confidence: {conf_pct:.1f}%")
                    print(f"   📈 Target: ₹{target:.2f} | 🛑 SL: ₹{sl:.2f}")
                    print(f"   P&T: {trade['entry_profit_target']:+.1f}%\n")
            else:
                print(f"📊 {sig['symbol']}")
                print(f"   {sig['signal']:4} @ ₹{sig['price']:.2f} | Confidence: {conf_pct:.1f}%")
                print(f"   📈 Target: ₹{target:.2f} | 🛑 SL: ₹{sl:.2f}")
                print(f"   P&T: {trade['entry_profit_target']:+.1f}%\n")
    
    print(f"{'-'*90}")
    print(f"✅ {len(tracker.trades)} paper trades recorded")
    print(f"⏰ Update exit prices at market close (15:30 IST)")
    print(f"{'-'*90}\n")


if __name__ == '__main__':
    main()
