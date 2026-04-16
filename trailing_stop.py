#!/usr/bin/env python3
"""
TRAILING STOP LOSS — Dynamically moves stop loss to protect profits
- Initial SL: Set just above breakeven (after covering charges + tax buffer)
- Trailing SL: Moves up with price to lock in gains
- Protects unrealized P&L while covering costs
Also stores intraday candle data with each trade for accurate chart plotting
"""

import json
import os
from datetime import datetime
import pytz

ist = pytz.timezone('Asia/Kolkata')

def calculate_breakeven_price(entry_price, signal='BUY', charges_pct=0.06, tax_buffer_pct=0.10):
    """
    Calculate break-even price after covering transaction charges and tax buffer.
    
    Args:
        entry_price: Entry price per unit
        signal: 'BUY' or 'SELL'
        charges_pct: Round-trip charges as % (default 0.06%)
        tax_buffer_pct: Tax buffer as % above charges (default 0.10%)
    
    Returns:
        Break-even price (the price above which profit starts)
    """
    total_cost_pct = charges_pct + tax_buffer_pct  # ~0.16%
    
    if signal == 'BUY':
        # For BUY: need price to go up by cost_pct to breakeven
        breakeven = entry_price * (1 + total_cost_pct / 100)
    else:  # SELL
        # For SELL: need price to go down by cost_pct to breakeven
        breakeven = entry_price * (1 - total_cost_pct / 100)
    
    return breakeven

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
    
    filepath = os.path.join('/Users/parthsharma/Desktop/Grow', paper_trades_file)
    
    try:
        with open(filepath, 'r') as f:
            trades = json.load(f)
    except:
        return []
    
    closed_trades = []
    
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
            trade['breakeven_price'] = round(calculate_breakeven_price(entry_price, signal), 2)
        
        breakeven = trade['breakeven_price']
        
        # Calculate current unrealized P&L
        if signal == 'BUY':
            current_pnl = ((current_price - entry_price) / entry_price) * 100
        else:  # SELL
            current_pnl = ((entry_price - current_price) / entry_price) * 100
        
        # Track peak P&L reached so far (for trailing stop)
        if 'peak_pnl' not in trade:
            trade['peak_pnl'] = current_pnl
        else:
            trade['peak_pnl'] = max(trade['peak_pnl'], current_pnl)
        
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
        
        # CHECK 1: HARD FLOOR - If price at breakeven, close (no point holding)
        if not should_close:
            if signal == 'BUY':
                at_breakeven = current_price <= breakeven
            elif signal == 'SELL':
                at_breakeven = current_price >= breakeven
            else:
                at_breakeven = False
            
            if at_breakeven and current_pnl <= 0:
                should_close = True
                if signal == 'BUY':
                    exit_reason = f"BREAKEVEN_FLOOR (P&L: {current_pnl:.2f}% | Price: ₹{current_price:.2f} ≤ Breakeven: ₹{breakeven:.2f})"
                else:
                    exit_reason = f"BREAKEVEN_FLOOR (P&L: {current_pnl:.2f}% | Price: ₹{current_price:.2f} ≥ Breakeven: ₹{breakeven:.2f})"
        
        # CHECK 2: AGGRESSIVE PEAK PROFIT PROTECTION (for both BUY and SELL)
        elif current_pnl > 0 and not should_close:  # Trade is profitable
            peak_pnl = trade['peak_pnl']
            
            # AGGRESSIVE PROTECTION: Once profit > +1%, protect it aggressively
            if peak_pnl >= 1.0:
                # Determine trailing stop distance based on peak profit level
                if peak_pnl >= 2.0:
                    # Peak > +2%: ULTRA_TIGHT trailing (0.25% allowed erosion)
                    trailing_distance = 0.25
                    stop_type = "ULTRA_TIGHT_TRAILING"
                else:
                    # Peak +1% to +2%: TIGHT trailing (0.5% allowed erosion)
                    trailing_distance = 0.5
                    stop_type = "TIGHT_TRAILING"
                
                # Calculate trailing stop threshold
                trailing_threshold = peak_pnl - trailing_distance
                
                if current_pnl < trailing_threshold:
                    should_close = True
                    exit_reason = f"{stop_type} (Peak: +{peak_pnl:.2f}% → Current: {current_pnl:.2f}%, Distance: {trailing_distance:.2f}%)"
                
                # ALSO CHECK: If profit eroded >50% from peak, close it (prevents giving back all gains)
                profit_erosion_pct = ((peak_pnl - current_pnl) / peak_pnl) * 100
                if profit_erosion_pct > 50 and current_pnl > 0:
                    should_close = True
                    exit_reason = f"PEAK_EROSION_50 (Peak: +{peak_pnl:.2f}% → Current: {current_pnl:.2f}%, Eroded: {profit_erosion_pct:.1f}%)"
            
            else:
                # Still building to +1%: use loose trailing (1.0% distance)
                trailing_distance = 1.0
                trailing_threshold = peak_pnl - trailing_distance
                
                if current_pnl < trailing_threshold:
                    should_close = True
                    exit_reason = f"LOOSE_TRAILING (Peak: +{peak_pnl:.2f}% → Current: {current_pnl:.2f}%, Distance: {trailing_distance:.1f}%)"
        
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
    
    # Save updated trades if any were closed
    if closed_trades:
        with open(filepath, 'w') as f:
            json.dump(trades, f, indent=2, default=str)
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
        if action_type == "CLOSE" and pnl < -1.5:
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
