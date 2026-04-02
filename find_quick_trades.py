#!/usr/bin/env python3
"""
Quick confidence analysis on top liquid instruments only.
Focuses on NIFTY, BANKNIFTY, FINNIFTY, and top 10 liquid stocks.
"""

import logging
from fno_backtester import run_fno_backtest

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Most liquid/tradeable instruments
TOP_INSTRUMENTS = [
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    "RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
    "TCS", "WIPRO",
]

def analyze_symbol(symbol):
    """Analyze confidence for a symbol."""
    try:
        result = run_fno_backtest(instrument_key=symbol, days_back=10)
        
        if "error" in result:
            return (symbol, 0, None, "error")
        
        stats = result.get('stats', {})
        trades = result.get('trades', [])
        
        if not trades:
            return (symbol, 0, None, "no_trades")
        
        win_rate = stats.get('win_rate', 0)
        profit_factor = stats.get('profit_factor', 1.0)
        total_pnl = stats.get('total_pnl', 0)
        
        # Confidence score
        confidence = min(100, win_rate + max(0, (profit_factor - 1) * 50))
        
        # Get latest signal
        latest_trade = trades[-1]
        signal = latest_trade.get('side', 'HOLD')
        entry_price = latest_trade.get('entry_price', 0)
        
        return (symbol, confidence, signal, entry_price, len(trades), total_pnl)
        
    except Exception as e:
        return (symbol, 0, None, str(e)[:30])

print("\n" + "=" * 90)
print("HIGH-CONFIDENCE TRADE ANALYSIS")
print("=" * 90)
print(f"\nAnalyzing top {len(TOP_INSTRUMENTS)} liquid instruments for confidence...")
print("")

results = []
for symbol in TOP_INSTRUMENTS:
    data = analyze_symbol(symbol)
    results.append(data)
    
    if len(data) >= 6:
        symbol, confidence, signal, entry_price, trade_count, pnl = data
        status = "✓" if confidence >= 60 else "✗"
        print(f"{status} {symbol:15} | Conf: {confidence:5.1f}% | {signal:4} | @₹{entry_price:8.1f} | {trade_count} trades | P&L: ₹{pnl:7,.0f}")
    else:
        print(f"✗ {data[0]:15} | Error: {data[3]}")

print("\n" + "=" * 90)
print("RECOMMENDATION FOR LIVE TRADING")
print("=" * 90)

# Filter high confidence
high_conf = [r for r in results if len(r) >= 6 and r[1] >= 60]
high_conf.sort(key=lambda x: x[1], reverse=True)

if high_conf:
    print(f"\n✅ FOUND {len(high_conf)} HIGH-CONFIDENCE OPPORTUNITIES (≥60% confidence)")
    print("")
    
    total_capital_needed = 0
    trades_to_execute = []
    
    for i, (symbol, confidence, signal, entry_price, trade_count, pnl) in enumerate(high_conf, 1):
        print(f"#{i}. {symbol}")
        print(f"    Signal: {signal} @ ₹{entry_price:.1f}")
        print(f"    Confidence: {confidence:.1f}%")
        print(f"    Historical P&L: ₹{pnl:,.0f} ({trade_count} trades)")
        
        # Estimate capital needed (assume 1 lot for indices, standard lot for stocks)
        if symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
            lot_multiplier = 1
        else:
            lot_multiplier = 0.5
        
        estimated_capital = entry_price * 75 * lot_multiplier  # Assume 75x leverage
        total_capital_needed += estimated_capital
        
        trades_to_execute.append({
            'symbol': symbol,
            'signal': signal,
            'confidence': confidence,
            'entry_price': entry_price
        })
        print("")
    
    print(f"💰 Estimated total capital needed for all trades: ₹{total_capital_needed:,.0f}")
    print(f"📊 Execute these {len(trades_to_execute)} trades now for best results")
    
else:
    print(f"\n❌ NO HIGH-CONFIDENCE OPPORTUNITIES FOUND")
    print(f"   All signals have <60% confidence")
    print(f"\n📊 Medium confidence opportunities (30-60%):")
    
    medium_conf = [r for r in results if len(r) >= 6 and r[1] >= 30]
    medium_conf.sort(key=lambda x: x[1], reverse=True)
    
    for symbol, confidence, signal, entry_price, trade_count, pnl in medium_conf[:5]:
        print(f"    {symbol:15} | Conf: {confidence:5.1f}% | {signal:4} | P&L: ₹{pnl:7,.0f}")

print("")
print("=" * 90)
