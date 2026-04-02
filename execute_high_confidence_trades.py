#!/usr/bin/env python3
"""
Execute high-confidence trades identified by ML model.
Only trades symbols with >80% confidence where prediction > actual.
"""

import logging
from datetime import datetime
from fno_trader import place_fno_buy, place_fno_sell, get_fno_margin, _get_groww
import pytz

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# High-confidence trades (from confidence_analysis.py)
TRADES_TO_EXECUTE = [
    {
        'symbol': 'TCS',
        'signal': 'BUY',
        'confidence': 94.7,
        'entry_price': 3433.2,
        'qty': 1,  # 1 lot
    },
    {
        'symbol': 'NIFTY',
        'signal': 'BUY',
        'confidence': 84.3,
        'entry_price': 35302.9,
        'qty': 1,  # 1 lot for index
    },
]

def execute_trades():
    """Execute the high-confidence trades."""
    
    print("\n" + "=" * 80)
    print("EXECUTING HIGH-CONFIDENCE TRADES")
    print("=" * 80)
    
    # Check if market is open
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    
    print(f"\nCurrent time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    if now.weekday() >= 5:
        print("❌ Market CLOSED (Weekend)")
        return False
    elif now > market_close:
        print("❌ Market CLOSED (after 15:30)")
        return False
    elif now < market_open:
        print(f"⏳ Market not open yet, opens at 09:15 IST")
        return False
    
    print("✅ Market is OPEN - Ready to trade")
    
    # Get Groww connection
    try:
        groww = _get_groww()
        if not groww:
            print("❌ Cannot connect to Groww API")
            return False
    except Exception as e:
        print(f"❌ Groww connection error: {e}")
        return False
    
    # Check available margin
    try:
        margin_data = get_fno_margin()
        margin = margin_data.get('available_margin', 0) if margin_data else 0
        print(f"\n💰 Available margin: ₹{margin:,.0f}")
    except Exception as e:
        print(f"⚠️  Could not fetch margin: {e}")
        margin = 0
    
    # Execute trades
    print(f"\n" + "=" * 80)
    print(f"EXECUTING {len(TRADES_TO_EXECUTE)} TRADES")
    print("=" * 80 + "\n")
    
    executed_trades = []
    total_invested = 0
    
    for trade in TRADES_TO_EXECUTE:
        symbol = trade['symbol']
        signal = trade['signal']
        qty = trade['qty']
        confidence = trade['confidence']
        entry_price = trade['entry_price']
        
        print(f"Executing: {symbol}")
        print(f"  Action: {signal}")
        print(f"  Qty: {qty}")
        print(f"  Entry Price: ₹{entry_price:.2f}")
        print(f"  Confidence: {confidence:.1f}%")
        
        try:
            # Place order
            if signal == "BUY":
                # For indices: use instrument key; for cash stocks: use trading symbol
                if symbol in ['NIFTY', 'BANKNIFTY', 'FINNIFTY']:
                    order_result = place_fno_buy(
                        trading_symbol=symbol,
                        instrument_key=symbol,
                        premium_per_unit=entry_price,
                        quantity=qty,
                        reason=f"High-confidence ML signal ({confidence:.1f}%)",
                        prediction=confidence
                    )
                else:
                    order_result = place_fno_buy(
                        trading_symbol=symbol,
                        instrument_key=symbol,
                        premium_per_unit=entry_price,
                        quantity=qty,
                        reason=f"High-confidence ML signal ({confidence:.1f}%)",
                        prediction=confidence
                    )
                
                if order_result and isinstance(order_result, dict) and order_result.get('order_status'):
                    order_id = order_result.get('order_id', 'PENDING')
                    print(f"  ✅ Order placed: {order_id}")
                    
                    executed_trades.append({
                        'symbol': symbol,
                        'signal': signal,
                        'qty': qty,
                        'price': entry_price,
                        'order_id': order_id,
                        'timestamp': datetime.now(ist),
                    })
                    
                    total_invested += entry_price * qty
                else:
                    print(f"  ⚠️  Order result: {order_result}")
                    
        except Exception as e:
            print(f"  ❌ Error: {str(e)[:60]}")
        
        print("")
    
    # Summary
    print("=" * 80)
    print("EXECUTION SUMMARY")
    print("=" * 80)
    
    print(f"\n✅ Orders Executed: {len(executed_trades)}/{len(TRADES_TO_EXECUTE)}")
    
    if executed_trades:
        print(f"\nTrades:")
        for trade in executed_trades:
            print(f"  • {trade['symbol']:15} {trade['signal']:4} {trade['qty']} @ ₹{trade['price']:.1f}")
        
        print(f"\n💰 Total Capital Invested: ₹{total_invested:,.0f}")
        print(f"⚡ Average Confidence: {sum(t['confidence'] for t in TRADES_TO_EXECUTE) / len(TRADES_TO_EXECUTE):.1f}%")
        
        print(f"\n📊 Next Steps:")
        print(f"  1. Monitor positions in Dashboard")
        print(f"  2. Set stop-loss at entry price - 2%")
        print(f"  3. Take profit at entry price + 3%")
        print(f"  4. Exit if ML signal reverses")
    else:
        print("\n❌ No trades could be executed")
    
    print("\n" + "=" * 80)
    
    return len(executed_trades) > 0

if __name__ == "__main__":
    success = execute_trades()
    exit(0 if success else 1)
