#!/usr/bin/env python3
"""
TRAILING STOP LOSS — Dynamically moves stop loss to protect profits
- Initial SL: Set just above breakeven (after covering charges + tax buffer)
- Trailing SL: Moves up with price to lock in gains
- Protects unrealized P&L while covering costs
Also stores intraday candle data with each trade for accurate chart plotting
"""

import json
import logging
import os
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# ═══════════════════════════════════════════════════════════════════════════
# END-OF-DAY EXIT FREEZE
# ═══════════════════════════════════════════════════════════════════════════
#
# After the cutoff (default 15:15 IST) NO automated path may close a position
# — not the trailing stop, not the hard stop loss, not a model signal reversal.
# Only a human can close a trade after that point.
#
# WHY A HARD FREEZE RATHER THAN A TIGHTER RULE:
# The last 15 minutes of the session are the thinnest and most volatile part
# of the day. A stop triggered at 15:22 on a one-tick wick exits at whatever
# the book offers, and the system has no way to distinguish that from a real
# move. The product here is CNC (delivery), so a position that is not closed
# simply carries overnight rather than being force-squared — holding is a
# legitimate outcome, not a failure.
#
# THE RISK THIS ACCEPTS, STATED PLAINLY:
# Blocking the stop loss means a position can keep falling after 15:15 with
# nothing automated protecting it, and can gap further overnight. That is a
# deliberate trade-off chosen by the operator, not an oversight. It is why
# this is config-driven and why the manual path is always left open.
#
# Manual closes bypass this entirely — see is_manual_exit().

_DEFAULT_CUTOFF = "15:15"


def _exit_freeze_config():
    """(enabled, cutoff_hhmm). Never raises: a config failure must not decide
    whether money can be protected, so it falls back to the documented
    default rather than silently disabling the freeze."""
    enabled, cutoff = True, _DEFAULT_CUTOFF
    try:
        from db_manager import get_config
        raw_on = get_config("trade.no_auto_exit_enabled")
        if raw_on is not None and str(raw_on).strip() != "":
            enabled = str(raw_on).strip().lower() in ("1", "true", "yes", "on")
        raw_cut = get_config("trade.no_auto_exit_after")
        if raw_cut and str(raw_cut).strip():
            cutoff = str(raw_cut).strip()
    except Exception as e:
        logger.debug("Exit-freeze config unavailable (%s) — using defaults", e)
    return enabled, cutoff


def is_manual_exit(exit_reason):
    """A close initiated by a person. These are never frozen."""
    return "manual" in str(exit_reason or "").lower()


def automated_exits_allowed(now=None):
    """
    (allowed: bool, reason: str) — may an AUTOMATED path close a position now?

    Consulted by every automated exit path. Manual closes do not call this.
    """
    enabled, cutoff = _exit_freeze_config()
    if not enabled:
        return True, "freeze disabled"

    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = IST.localize(now)

    try:
        hh, mm = [int(x) for x in cutoff.split(":")]
    except Exception:
        logger.warning("Bad trade.no_auto_exit_after=%r — using %s", cutoff, _DEFAULT_CUTOFF)
        hh, mm = 15, 15

    # Weekends and pre-open are not "frozen" — there is simply no session.
    # The freeze is specifically about the tail of a live trading day.
    if now.weekday() >= 5:
        return True, "non-trading day"

    if (now.hour, now.minute) >= (hh, mm):
        return False, f"exit freeze active after {hh:02d}:{mm:02d} IST (now {now:%H:%M})"
    return True, "within trading window"


ist = pytz.timezone('Asia/Kolkata')

def calculate_breakeven_price(entry_price, signal, quantity,
                              product=None, exchange=None):
    """
    The price at which THIS trade stops losing money.

    Breakeven is per-position, not a constant. Brokerage (~Rs20/order) and DP
    charges (~Rs16) do not scale with quantity, so the move needed to cover
    them depends on size:

        2 shares  @ Rs3,917  ->  1.029%   (breakeven Rs3,957.21)
       10 shares  @ Rs3,950  ->  0.383%   (breakeven Rs3,965.14)
       10 shares  @ Rs317    ->  2.215%   (breakeven Rs324.02)

    This previously hardcoded a flat 0.16% regardless of size or price —
    understating the real figure by 6.4x on the first case and 13.8x on the
    third. It also bypassed the cost rates in config_settings, which are
    scraped and carry a last_verified_date, so a brokerage change would never
    have reached it.

    quantity is REQUIRED and has no default. Every trade has one by
    construction — record_entry() takes it, and no stored trade in either
    store has ever lacked it. A missing quantity is a programming error, and
    a silent fallback would hide it behind a plausible-looking wrong number.

    Raises on a bad quantity, and lets cost-model failures propagate. A guard
    that invents a breakeven when it cannot compute one removes itself exactly
    when it is least safe.
    """
    from config import DEFAULT_PRODUCT, DEFAULT_EXCHANGE
    import costs

    qty = int(quantity)
    if qty <= 0:
        raise ValueError(f"calculate_breakeven_price needs a positive quantity, got {quantity!r}")
    if not entry_price or entry_price <= 0:
        raise ValueError(f"calculate_breakeven_price needs a positive entry price, got {entry_price!r}")

    # Round trip at the same price isolates the cost — which is what breakeven
    # means: the move needed purely to cover charges.
    move_pct = costs.calculate_costs(
        entry_price, qty, sell_price=entry_price,
        product=product or DEFAULT_PRODUCT,
        exchange=exchange or DEFAULT_EXCHANGE,
    ).breakeven_pct

    if signal == 'BUY':
        return entry_price * (1 + move_pct / 100)
    return entry_price * (1 - move_pct / 100)


def breakeven_pct_for(entry_price, quantity, product=None, exchange=None):
    """
    Breakeven as a PERCENTAGE move. Same model as above — the trailing-stop
    arming logic reasons in percent rather than price.

    Also raises rather than returning a default: see the note above.
    """
    from config import DEFAULT_PRODUCT, DEFAULT_EXCHANGE
    import costs

    qty = int(quantity)
    if qty <= 0:
        raise ValueError(f"breakeven_pct_for needs a positive quantity, got {quantity!r}")
    return costs.calculate_costs(
        entry_price, qty, sell_price=entry_price,
        product=product or DEFAULT_PRODUCT,
        exchange=exchange or DEFAULT_EXCHANGE,
    ).breakeven_pct




def _fetch_trade_candles(symbol, entry_time, exit_time):
    """
    Fetch 1-minute candles between trade entry and exit times.
    
    Returns list of candles: [timestamp, open, high, low, close, volume]
    """
    try:
        import os
        from growwapi import GrowwAPI
        
        token = os.getenv("GROWW_ACCESS_TOKEN")
        if not token:
            return None
        
        groww = GrowwAPI(token)
        
        # Parse entry/exit times
        entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00')).astimezone(ist)
        exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00')).astimezone(ist)
        
        start_str = entry_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_str = exit_dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # Fetch 5-minute candles (Groww doesn't support 1-minute)
        resp = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange='NSE',
            segment='EQ',
            start_time=start_str,
            end_time=end_str,
            interval_in_minutes=5
        )
        
        candles_raw = resp.get("candles", [])
        if not candles_raw:
            return None
        
        # Format candles for storage: keep [timestamp, open, high, low, close, volume]
        formatted = []
        for candle in candles_raw:
            if len(candle) >= 6:
                formatted.append({
                    "time": candle[0],  # ISO timestamp
                    "o": float(candle[1]),  # open
                    "h": float(candle[2]),  # high
                    "l": float(candle[3]),  # low
                    "c": float(candle[4]),  # close
                    "v": int(candle[5]) if len(candle) > 5 else 0  # volume
                })
        
        return formatted if formatted else None
        
    except Exception as e:
        print(f"[_fetch_trade_candles] Failed to fetch candles for {symbol}: {e}")
        return None


def check_and_close_trades_on_loss(paper_trades_file='paper_trades.json', live_prices=None):
    """
    TRAILING STOP LOSS with BREAKEVEN FLOOR + AGGRESSIVE PEAK PROTECTION
    
    Strategy:
    1. Initial SL: Set at breakeven price (covers charges + tax buffer)
       - For BUY: SL = Entry * (1 + 0.16%) 
       - For SELL: SL = Entry * (1 - 0.16%)
    
    2. Trailing SL: As trade becomes profitable, SL moves UP with AGGRESSIVE trailing
       - Peak +1% to +2%: TIGHT_TRAILING (0.5% erosion allowed)
       - Peak > +2%: ULTRA_TIGHT_TRAILING (0.25% erosion allowed)
       - OR: If profit erodes >50% of peak (e.g., +2% → +1%), CLOSE immediately
       - SL NEVER goes below breakeven floor
    
    3. Exit Conditions:
       - Hard close at breakeven or below (no point holding losing trade)
       - Aggressive trailing stop activated (early profit erosion detection)
       - Peak profit erosion >50% (prevents giving back gains)
    
    Returns:
        List of closed trades with reasons
    """
    if live_prices is None:
        live_prices = {}

    # EXIT FREEZE: this is the main automated close path (scheduler every 5s,
    # plus the dashboard's own poll). Gated here rather than at the callers so
    # no caller can forget — the endpoints in app.py are hit automatically by
    # the browser and are not "manual" despite being HTTP requests.
    _allowed, _why = automated_exits_allowed()
    if not _allowed:
        logger.info("Auto-close skipped — %s", _why)
        return []

    filepath = os.path.join('/Users/parthsharma/Desktop/Grow', paper_trades_file)
    
    try:
        with open(filepath, 'r') as f:
            trades = json.load(f)
    except:
        return []
    
    closed_trades = []
    _state_changed = False   # persist ratchet state even when nothing closes
    
    for trade in trades:
        # Only check OPEN trades
        if trade['status'] != 'OPEN':
            continue
        
        symbol = trade['symbol']
        
        # Skip if we don't have live price for this symbol
        if symbol not in live_prices or not live_prices[symbol]:
            continue
        
        current_price = live_prices[symbol]
        entry_price = trade['entry_price']
        signal = trade['signal']
        entry_profit_target = trade.get('entry_profit_target', 2.0)
        
        # Calculate breakeven (only once per trade)
        if 'breakeven_price' not in trade:
            # Quantity passed so the figure reflects THIS position's real cost.
            trade['breakeven_price'] = round(
                calculate_breakeven_price(entry_price, signal,
                                          quantity=trade.get('quantity')), 2)
        
        breakeven = trade['breakeven_price']
        
        # Calculate current unrealized P&L
        if signal == 'BUY':
            current_pnl = ((current_price - entry_price) / entry_price) * 100
        else:  # SELL
            current_pnl = ((entry_price - current_price) / entry_price) * 100
        
        # peak_pnl is OWNED by trailing_strategy.evaluate() (CHECK 0.5), which
        # derives it from highest_price_reached and returns it in its state.
        # This block is kept only to seed the key for trades recorded before
        # that existed; it must never lower a value the strategy has set, hence
        # max(). Two independent writers with different definitions is what
        # produced the corrupted peak_pnl on MARUTI.
        if 'peak_pnl' not in trade:
            trade['peak_pnl'] = current_pnl
        
        should_close = False
        exit_reason = ""
        
        # CHECK TARGET PRICE HIT WITH SIGNAL VALIDATION
        target_price = trade.get('projected_exit')
        target_hit = False
        
        if target_price:
            if signal == 'BUY':
                target_hit = current_price >= target_price
            elif signal == 'SELL':
                target_hit = current_price <= target_price
        
        # If target was hit, CLOSE IMMEDIATELY to lock in profits
        if target_hit:
            if signal == 'BUY':
                # BUY STRATEGY: Close immediately at target with profit
                if current_pnl > 0:
                    should_close = True
                    exit_reason = f"TARGET_HIT_PROFIT_LOCKED (Price: ₹{current_price:.2f} ≥ Target: ₹{target_price:.2f} | P&L: +{current_pnl:.2f}%)"
                else:
                    # Negative P&L at target - close to minimize loss
                    should_close = True
                    exit_reason = f"TARGET_HIT_NO_PROFIT (Price: ₹{current_price:.2f} ≥ Target: ₹{target_price:.2f})"
            
            elif signal == 'SELL':
                # SELL STRATEGY: Close immediately at target with profit
                if current_pnl > 0:
                    should_close = True
                    exit_reason = f"TARGET_HIT_PROFIT_LOCKED (Price: ₹{current_price:.2f} ≤ Target: ₹{target_price:.2f} | P&L: +{current_pnl:.2f}%)"
                else:
                    # Negative P&L at target - close to minimize loss
                    should_close = True
                    exit_reason = f"TARGET_HIT_NO_PROFIT (Price: ₹{current_price:.2f} ≤ Target: ₹{target_price:.2f})"
        
        # If target was hit with negative P&L, close the trade
        if should_close:
            trade['exit_price'] = round(current_price, 2)
            trade['exit_time'] = datetime.now(ist).isoformat()
            trade['actual_profit_pnl'] = round(current_pnl, 2)
            trade['status'] = 'HIT_TARGET'
            trade['exit_reason'] = exit_reason
            
            # Fetch and store intraday candles for this trade (entry -> exit)
            candles = _fetch_trade_candles(symbol, trade.get('entry_time'), trade['exit_time'])
            if candles:
                trade['intraday_candles'] = candles
                trade['candle_count'] = len(candles)
            
            # Propagate the close into trade_journal. Without this the journal
            # keeps the trade OPEN forever: this module closes trades by writing
            # paper_trades.json directly and never notified the journal, while
            # _task_auto_close_trades (the 5s caller) only logged the result.
            # That is why MARUTI-B-20260819102622101215 read CLOSED in JSON and
            # OPEN in both journal stores.
            try:
                import trade_journal
                # Keyword args, deliberately. This was three POSITIONAL args
                # into a function with seven required ones, so every call
                # raised TypeError: missing a required argument: 'quantity' —
                # and the blanket except below logged it as a warning and moved
                # on. It never once succeeded: 25 of 26 trades closed through
                # this module and 0 of them ever reached the journal, which is
                # why TITAN/HINDUNILVR read CLOSED in paper_trades.json and
                # OPEN in both journal stores. Read from `trade` rather than
                # the loop locals so this mirrors paper_trader.close_trade's
                # call exactly.
                trade_journal.close_matching_paper_trade(
                    trade_id=trade['id'],
                    symbol=trade.get('symbol'),
                    side=trade.get('side') or trade.get('signal'),
                    quantity=trade.get('quantity'),
                    entry_price=trade.get('entry_price'),
                    entry_time=trade.get('entry_time'),
                    exit_price=round(current_price, 2),
                    exit_reason=exit_reason,
                    # The moment the trade actually exited, not the moment the
                    # journal happened to be notified.
                    exit_time=trade.get('exit_time'),
                )
            except Exception as _je:
                # ERROR + traceback, not a one-line warning: a signature error
                # here is a code defect, not a transient hiccup, and logging it
                # quietly is what hid this for 25 trades. Still swallowed — the
                # exit has already happened and must not be unwound by a
                # bookkeeping failure — but it must be impossible to miss.
                logger.error("journal sync FAILED for %s: %s", trade.get('id'), _je, exc_info=True)

            closed_trades.append({
                'id': trade['id'],
                'symbol': symbol,
                'signal': signal,
                'entry_price': entry_price,
                'exit_price': current_price,
                'pnl': current_pnl,
                'reason': exit_reason,
                'target': target_price
            })
            
            print(f"✓ TARGET HIT: {symbol} {signal} | Entry: ₹{entry_price:.2f} → Target: ₹{target_price:.2f} (at: ₹{current_price:.2f}) | P&L: {current_pnl:.2f}%")
            continue  # Move to next trade
        
        # Get the hard stop loss
        hard_stop_loss = trade.get('stop_loss')
        
        # CHECK 0: ABSOLUTE HARD STOP LOSS (HIGHEST PRIORITY - CANNOT BE BREACHED)
        if hard_stop_loss:
            if signal == 'BUY':
                # For BUY: if price drops to or below stop loss, close immediately
                if current_price <= hard_stop_loss:
                    should_close = True
                    exit_reason = f"HARD_STOP_LOSS_HIT (Price: ₹{current_price:.2f} ≤ SL: ₹{hard_stop_loss:.2f})"
            elif signal == 'SELL':
                # For SELL: if price rises to or above stop loss, close immediately
                if current_price >= hard_stop_loss:
                    should_close = True
                    exit_reason = f"HARD_STOP_LOSS_HIT (Price: ₹{current_price:.2f} ≥ SL: ₹{hard_stop_loss:.2f})"
        
        # CHECK 0.5: THE SINGLE TRAILING STRATEGY — trailing_strategy.evaluate()
        #
        # Replaces BOTH mechanisms that used to run here: the old CHECK 0.5
        # (which honoured a `trailing_stop` written by
        # paper_trader.update_trailing_stop using a flat 1.5%-of-price buffer
        # with no breakeven floor) and CHECK 2 below (a separate peak_pnl
        # ladder). They disagreed: on MARUTI the first put the stop 120.01
        # BELOW breakeven, guaranteeing a loss on a trade that peaked +1.016%,
        # while the second never armed because a lost-update race had corrupted
        # peak_pnl to a negative value. One authority now owns the decision.
        #
        # The model is consulted ONLY on a soft-stop breach — rare, at most
        # once per trade — so this adds no per-tick I/O to the 5s loop, and it
        # fails CLOSED if the model is unavailable.
        if not should_close:
            try:
                import trailing_strategy

                # Backfill breakeven/SL for trades recorded before this existed.
                if not trade.get('breakeven_pct') or not trade.get('breakeven_price'):
                    _seed = trailing_strategy.build_trade(
                        entry_price, trade.get('quantity') or 1, signal,
                        stop_loss=trade.get('stop_loss'), symbol=symbol)
                    trade.setdefault('breakeven_pct', _seed['breakeven_pct'])
                    trade.setdefault('breakeven_price', _seed['breakeven_price'])
                    trade['stop_loss'] = _seed['stop_loss']

                def _confidence(sym):
                    import bot
                    return bot.get_prediction_xgb(sym)

                _r = trailing_strategy.evaluate(trade, current_price,
                                                confidence_fn=_confidence)
                if _r["state"] and any(trade.get(k) != v for k, v in _r["state"].items()):
                    _state_changed = True
                trade.update(_r["state"])
                if _r["action"] == trailing_strategy.ACTION_CLOSE:
                    should_close = True
                    exit_reason = _r["reason"]
            except Exception as _e:
                logger.warning("trailing_strategy failed for %s: %s", symbol, _e)
        
        # CHECK 1: (Removed) BREAKEVEN_FLOOR was closing trades at tiny losses
        # (-0.03%) when the hard SL is at -2%. The hard SL handles real risk.
        # Trades need room to breathe before the hard SL is hit.
        
        # CHECK 2: PEAK PROFIT PROTECTION (only once trade has reached meaningful profit)
        # NOTE: this was `elif`, which made it unreachable because it was chained to the
        # `if not should_close:` block above.  Both checks should run independently.
        # SUPERSEDED by trailing_strategy.evaluate() in CHECK 0.5 above.
        # Left in place rather than deleted so the tiering rationale stays
        # on record; `False and` makes it inert without disturbing the
        # surrounding control flow.
        if False and current_pnl > 0 and not should_close:
            peak_pnl = trade['peak_pnl']
            
            # ARM AS SOON AS COSTS ARE COVERED — not at a fixed +1.5%.
            #
            # The 1.5% was a constant while breakeven is SIZE-DEPENDENT: fixed
            # charges (brokerage ~Rs40, DP ~Rs16) do not scale with quantity, so
            # 2 shares of a Rs3,900 stock need 1.03% to break even while 10
            # shares need 0.38%. Between breakeven and 1.5% a trade was
            # genuinely profitable with NOTHING guarding it, and could slide
            # back through breakeven into a net loss untouched.
            #
            # Measured: SIEMENS peaked at +0.845%, never armed, exited at
            # -Rs14.50 net on a move the model called correctly.
            #
            # Uses the breakeven stamped on the trade at entry — see
            # calculate_breakeven_price(), which prices the real quantity via
            # costs.calculate_costs() rather than assuming a flat percentage.
            # Prefer the value stamped on the trade AT ENTRY — it is the
            # figure this position was actually sized against. Recompute only
            # for older trades recorded before entry-time breakeven existed.
            # Breakeven is stamped on the trade at entry. Older records
            # predating that get it computed once and backfilled.
            _be_pct = trade.get('breakeven_pct')
            if not _be_pct:
                _be_pct = breakeven_pct_for(entry_price, trade.get('quantity'))
                trade['breakeven_pct'] = round(_be_pct, 4)

            arm_at = max(_be_pct * 1.2, 0.20)
            if peak_pnl >= arm_at:
                # Determine trailing stop distance based on peak profit level
                # Tiers measured in MULTIPLES OF BREAKEVEN, not absolute
                # percentages. A trade arming at 1.2x breakeven previously fell
                # straight past 3.0/2.0/1.5 into the loosest 1.0% give-back —
                # which on a small position is wider than the entire profit.
                # The give-back is also capped at half the peak, so it can never
                # hand back more than half of what was actually made.
                if peak_pnl >= _be_pct * 4:
                    trailing_distance = 0.5
                    stop_type = "ULTRA_TIGHT_TRAILING"
                elif peak_pnl >= _be_pct * 2.5:
                    trailing_distance = 0.75
                    stop_type = "TIGHT_TRAILING"
                else:
                    trailing_distance = 1.0
                    stop_type = "MODERATE_TRAILING"
                trailing_distance = min(trailing_distance, peak_pnl * 0.5)
                
                # Calculate trailing stop threshold
                trailing_threshold = peak_pnl - trailing_distance
                
                if current_pnl < trailing_threshold:
                    should_close = True
                    exit_reason = f"{stop_type} (Peak: +{peak_pnl:.2f}% → Current: {current_pnl:.2f}%, Distance: {trailing_distance:.2f}%)"
                
                # ALSO CHECK: If profit eroded >60% from peak and peak was meaningful, close
                profit_erosion_pct = ((peak_pnl - current_pnl) / peak_pnl) * 100
                if profit_erosion_pct > 60 and peak_pnl >= arm_at and current_pnl > 0:
                    should_close = True
                    exit_reason = f"PEAK_EROSION_60 (Peak: +{peak_pnl:.2f}% → Current: {current_pnl:.2f}%, Eroded: {profit_erosion_pct:.1f}%)"
        
        if should_close:
            # CHECK: Is this a manual trade that system cannot touch?
            trade_id = trade.get('id', f"{symbol}_{trade.get('entry_time','')}")
            try:
                from trade_origin_manager import can_system_close_trade, log_trade_boundary_event
                
                if not can_system_close_trade(trade_id):
                    # This is a MANUAL trade - system cannot close it
                    log_trade_boundary_event(
                        'MANUAL_TRADE_PROTECTED',
                        trade_id,
                        symbol,
                        f"System tried to {exit_reason} but trade is MANUAL - protected"
                    )
                    continue  # Skip this trade
            except:
                pass  # If origin manager not available, allow close
            
            # Close the trade
            trade['exit_price'] = round(current_price, 2)
            trade['exit_time'] = datetime.now(ist).isoformat()
            trade['actual_profit_pnl'] = round(current_pnl, 2)
            trade['status'] = 'CLOSED'
            trade['exit_reason'] = exit_reason
            
            # Fetch and store intraday candles for this trade (entry -> exit)
            candles = _fetch_trade_candles(symbol, trade.get('entry_time'), trade['exit_time'])
            if candles:
                trade['intraday_candles'] = candles
                trade['candle_count'] = len(candles)
            
            # Propagate the close into trade_journal. Without this the journal
            # keeps the trade OPEN forever: this module closes trades by writing
            # paper_trades.json directly and never notified the journal, while
            # _task_auto_close_trades (the 5s caller) only logged the result.
            # That is why MARUTI-B-20260819102622101215 read CLOSED in JSON and
            # OPEN in both journal stores.
            try:
                import trade_journal
                # Keyword args, deliberately. This was three POSITIONAL args
                # into a function with seven required ones, so every call
                # raised TypeError: missing a required argument: 'quantity' —
                # and the blanket except below logged it as a warning and moved
                # on. It never once succeeded: 25 of 26 trades closed through
                # this module and 0 of them ever reached the journal, which is
                # why TITAN/HINDUNILVR read CLOSED in paper_trades.json and
                # OPEN in both journal stores. Read from `trade` rather than
                # the loop locals so this mirrors paper_trader.close_trade's
                # call exactly.
                trade_journal.close_matching_paper_trade(
                    trade_id=trade['id'],
                    symbol=trade.get('symbol'),
                    side=trade.get('side') or trade.get('signal'),
                    quantity=trade.get('quantity'),
                    entry_price=trade.get('entry_price'),
                    entry_time=trade.get('entry_time'),
                    exit_price=round(current_price, 2),
                    exit_reason=exit_reason,
                    # The moment the trade actually exited, not the moment the
                    # journal happened to be notified.
                    exit_time=trade.get('exit_time'),
                )
            except Exception as _je:
                # ERROR + traceback, not a one-line warning: a signature error
                # here is a code defect, not a transient hiccup, and logging it
                # quietly is what hid this for 25 trades. Still swallowed — the
                # exit has already happened and must not be unwound by a
                # bookkeeping failure — but it must be impossible to miss.
                logger.error("journal sync FAILED for %s: %s", trade.get('id'), _je, exc_info=True)

            closed_trades.append({
                'id': trade['id'],
                'symbol': symbol,
                'signal': signal,
                'entry_price': entry_price,
                'exit_price': current_price,
                'breakeven_price': breakeven,
                'pnl': current_pnl,
                'reason': exit_reason,
                'target': entry_profit_target,
                'peak_pnl': trade.get('peak_pnl', current_pnl)
            })
            
            print(f"✓ CLOSED {symbol} {signal} | Entry: ₹{entry_price:.2f} → Exit: ₹{current_price:.2f} | Breakeven: ₹{breakeven:.2f} | P&L: {current_pnl:.2f}% (Peak: +{trade.get('peak_pnl', current_pnl):.2f}%) | {exit_reason}")
        else:
            # Trade still open: log the aggressive protection status
            if current_pnl > 0:
                peak = trade.get('peak_pnl', current_pnl)
                if peak >= 2.0:
                    protection_level = "ULTRA_TIGHT (0.25%)"
                elif peak >= 1.0:
                    protection_level = "TIGHT (0.5%)"
                else:
                    protection_level = "LOOSE (1.0%)"
                print(f"  {symbol} {signal} | Current: {current_pnl:+.2f}% | Peak: +{peak:.2f}% | Protection: {protection_level} | Breakeven: ₹{breakeven:.2f}")
            else:
                print(f"  {symbol} {signal} | Current: {current_pnl:+.2f}% | Breakeven Floor: ₹{breakeven:.2f}")
    
    # Persist whenever ANYTHING changed — not only on a close.
    #
    # This previously wrote only `if closed_trades`, so on every tick where
    # nothing closed the ratchet state computed above (highest_price_reached,
    # trailing_stop, hard_floor, peak_pnl) was mutated in memory and then
    # DISCARDED. A trailing stop cannot ratchet if its peak is forgotten
    # between ticks: measured over a 52-tick replay of the MARUTI path, peak
    # and trailing_stop both stayed None the whole way and the trade never
    # closed. It is also why peak_pnl only ever survived when the separate
    # PaperTradeTracker path happened to write it.
    #
    # Written under the same exclusive lock and merge-by-id that
    # PaperTradeTracker._save_trades uses, so the two writers cannot erase each
    # other's fields.
    if closed_trades or _state_changed:
        import fcntl
        lock_path = filepath + ".lock"
        try:
            with open(lock_path, "w") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    disk = []
                    if os.path.exists(filepath):
                        with open(filepath, "r") as f:
                            disk = json.load(f) or []
                    by_id = {t.get("id"): t for t in disk if isinstance(t, dict)}
                    for t in trades:
                        tid = t.get("id")
                        by_id[tid] = {**by_id.get(tid, {}), **t} if tid in by_id else t
                    with open(filepath, "w") as f:
                        json.dump(list(by_id.values()), f, indent=2, default=str)
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            logger.warning("locked save failed (%s) — plain write", e)
            with open(filepath, "w") as f:
                json.dump(trades, f, indent=2, default=str)
    if closed_trades:
        print(f"\n✓ {len(closed_trades)} trades closed with aggressive peak protection")

    return closed_trades




def manage_loss_positions(paper_trades_file='paper_trades.json', live_prices=None):
    """
    AUTOMATED LOSS POSITION MANAGEMENT
    
    Handles loss positions intelligently based on severity:
    - CRITICAL (< -1.5%): Close immediately
    - HIGH (-1.0% to -1.5%): Hold + reverse at entry (scalp reversal)
    - MEDIUM (-0.5% to -1.0%): Hold + scale-out if recovers 50%
    - LIGHT (> -0.5%): Hold + patience
    
    Returns:
        Dict with actions: {
            'closed': [...],
            'reversed': [...],
            'held': [...],
            'scaled_out': [...]
        }
    """
    if live_prices is None:
        live_prices = {}

    # EXIT FREEZE. This is the SECOND automated closer in this module — it
    # closes CRITICAL (< -1.5%) positions outright — and app.py calls it back
    # to back with check_and_close_trades_on_loss. Gating only that one would
    # have left this wide open, which is exactly the kind of gap a "we added
    # the guard" claim hides.
    _allowed, _why = automated_exits_allowed()
    if not _allowed:
        logger.info("Loss-position management skipped — %s", _why)
        return {'closed': [], 'reversed': [], 'held': [], 'scaled_out': [],
                'skipped': _why}
    
    filepath = os.path.join('/Users/parthsharma/Desktop/Grow', paper_trades_file)
    
    try:
        with open(filepath, 'r') as f:
            trades = json.load(f)
    except:
        return {'closed': [], 'reversed': [], 'held': [], 'scaled_out': []}
    
    actions = {'closed': [], 'reversed': [], 'held': [], 'scaled_out': []}
    
    for trade in trades:
        if trade['status'] != 'OPEN':
            continue
        
        symbol = trade['symbol']
        if symbol not in live_prices or not live_prices[symbol]:
            continue
        
        current_price = live_prices[symbol]
        entry_price = trade['entry_price']
        signal = trade['signal']
        
        # Calculate current P&L
        if signal == 'BUY':
            pnl = ((current_price - entry_price) / entry_price) * 100
        else:  # SELL
            pnl = ((entry_price - current_price) / entry_price) * 100
        
        # Only process loss positions
        if pnl >= 0:
            continue
        
        # Initialize loss tracking fields if needed
        if 'loss_tracked_since' not in trade:
            trade['loss_tracked_since'] = datetime.now(ist).isoformat()
            trade['loss_actions'] = []
        
        # CLASSIFY LOSS SEVERITY
        if pnl < -1.5:
            severity = "CRITICAL"
            action_type = "CLOSE"
        elif pnl < -1.0:
            severity = "HIGH"
            action_type = "REVERSE"
        elif pnl < -0.5:
            severity = "MEDIUM"
            action_type = "SCALE_OUT"
        else:
            severity = "LIGHT"
            action_type = "HOLD"
        
        # EXECUTE AUTOMATED ACTIONS
        # SUPERSEDED — this was a THIRD exit authority running alongside
        # check_and_close_trades_on_loss (app.py calls both, back to back), with
        # thresholds that now contradict RULE 1: it closed at -1.5% while the
        # hard stop-loss sits at -1.0%, so the hard SL always fires first and
        # this branch is unreachable in normal tick-by-tick operation. Worse, it
        # wrote exit_price/exit_time directly without notifying trade_journal —
        # the same desync that left MARUTI OPEN in the journal.
        #
        # Downside risk is now owned solely by the hard SL (checked first, at a
        # TIGHTER level), so this branch is disabled rather than deleted; the
        # reporting it produces ('held'/'scaled_out') still works.
        if False and action_type == "CLOSE" and pnl < -1.5:
            # Close critical losses
            trade['exit_price'] = round(current_price, 2)
            trade['exit_time'] = datetime.now(ist).isoformat()
            trade['actual_profit_pnl'] = round(pnl, 2)
            trade['status'] = 'CLOSED'
            trade['exit_reason'] = f"CRITICAL_LOSS_AUTO_CLOSE ({pnl:.2f}%)"
            
            actions['closed'].append({
                'id': trade['id'],
                'symbol': symbol,
                'pnl': pnl,
                'reason': f"Critical loss {pnl:.2f}% - auto-closed"
            })
            
            print(f"🔴 AUTO-CLOSED {symbol} CRITICAL LOSS: {pnl:.2f}%")
        
        elif action_type == "REVERSE":
            # For HIGH losses: Setup reverse position opportunity
            # Only record if price hasn't already reversed
            if 'reverse_opportunity' not in trade or not trade.get('reverse_opportunity'):
                trade['reverse_opportunity'] = {
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'distance_from_entry': abs(current_price - entry_price),
                    'identified_at': datetime.now(ist).isoformat()
                }
                actions['reversed'].append({
                    'id': trade['id'],
                    'symbol': symbol,
                    'signal': signal,
                    'pnl': pnl,
                    'opportunity': f"Price ₹{current_price:.2f}, Entry ₹{entry_price:.2f} - Reverse opportunity"
                })
                print(f"🔄 REVERSE OPPORTUNITY {symbol}: Current ₹{current_price:.2f} vs Entry ₹{entry_price:.2f}")
        
        elif action_type == "SCALE_OUT":
            # For MEDIUM losses: Scale out if price recovers 50% of loss
            # Track recovery opportunity
            if 'scale_out_target' not in trade:
                # If loss is -0.75%, recovery target is 50% back = -0.375%
                recovery_target = pnl / 2  # Halfway back to breakeven
                trade['scale_out_target'] = recovery_target
                trade['scale_out_identified'] = datetime.now(ist).isoformat()
                actions['scaled_out'].append({
                    'id': trade['id'],
                    'symbol': symbol,
                    'current_loss': pnl,
                    'scale_out_at': recovery_target,
                    'status': 'WAITING_FOR_RECOVERY'
                })
                print(f"📊 SCALE-OUT SETUP {symbol}: Current loss {pnl:.2f}%, will reduce if recovers to {recovery_target:.2f}%")
        
        else:  # HOLD
            actions['held'].append({
                'id': trade['id'],
                'symbol': symbol,
                'pnl': pnl,
                'severity': severity,
                'reason': f"Light loss {pnl:.2f}% - holding"
            })
    
    # Save updated trades with loss tracking
    if actions['closed'] or actions['reversed'] or actions['scaled_out']:
        with open(filepath, 'w') as f:
            json.dump(trades, f, indent=2, default=str)
        print(f"\n✓ Loss management updated: {len(actions['closed'])} critical closed, {len(actions['reversed'])} reverse opportunities tracked")
    
    return actions


if __name__ == '__main__':
    # Test with sample prices
    test_prices = {
        'TCS': 2420.0,
        'INFY': 1274.0,
        'ICICIBANK': 1196.0
    }
    
    closed = check_and_close_trades_on_loss(live_prices=test_prices)
    if closed:
        print(f"\nClosed trades: {len(closed)}")
        for trade in closed:
            print(f"  {trade['symbol']}: {trade['reason']}")
    else:
        print("No trades closed")
