#!/usr/bin/env python3
"""
Confidence-based trading: Analyze all instruments and trade only highest confidence signals.
Compare XGBoost predictions vs actual price movements to gauge confidence.
"""

import logging
from fno_backtester import run_fno_backtest, get_backtest_instruments
from datetime import datetime, timedelta
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

def analyze_confidence(symbol):
    """
    Run single backtest and analyze confidence level.
    Returns: (symbol, confidence_pct, signal, expected_pnl, reason)
    """
    try:
        result = run_fno_backtest(instrument_key=symbol, days_back=10)
        
        if "error" in result:
            return (symbol, 0, None, 0, f"No data: {result['error']}")
        
        if not result.get('trades'):
            return (symbol, 0, None, 0, "No trades generated")
        
        # Get most recent trade
        latest_trade = result['trades'][-1]
        
        # Calculate confidence metrics
        stats = result.get('stats', {})
        win_rate = stats.get('win_rate', 0)
        profit_factor = stats.get('profit_factor', 0)
        expected_pnl = stats.get('total_pnl', 0)
        
        # Confidence = win_rate + profit_factor score
        confidence = min(100, win_rate + (profit_factor - 1) * 50)
        confidence = max(0, confidence)
        
        signal = latest_trade.get('side', 'HOLD')
        
        reason = f"WR:{win_rate:.0f}% PF:{profit_factor:.2f} Trades:{len(result['trades'])}"
        
        return (symbol, confidence, signal, expected_pnl, reason)
        
    except Exception as e:
        return (symbol, 0, None, 0, f"Error: {str(e)[:50]}")

def find_high_confidence_trades(min_confidence=60):
    """Find all trades with confidence >= threshold."""
    logger.info("=" * 80)
    logger.info("HIGH-CONFIDENCE TRADING ANALYSIS")
    logger.info("=" * 80)
    logger.info(f"Scanning all instruments (confidence threshold: {min_confidence}%)")
    logger.info("")
    
    instruments = get_backtest_instruments()
    all_results = []
    
    # Analyze each instrument
    for idx, symbol in enumerate(sorted(instruments.keys()), 1):
        logger.debug(f"[{idx}/{len(instruments)}] Analyzing {symbol}...")
        
        confidence, signal, expected_pnl, reason = analyze_confidence(symbol)[1:]
        all_results.append((symbol, confidence, signal, expected_pnl, reason))
        
        # Print progress every 20
        if idx % 20 == 0:
            logger.info(f"[{idx}/{len(instruments)}] Progress...")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("RESULTS")
    logger.info("=" * 80)
    
    # Filter high confidence
    high_conf = [r for r in all_results if r[1] >= min_confidence and r[2] is not None]
    
    # Sort by confidence (descending)
    high_conf.sort(key=lambda x: x[1], reverse=True)
    
    logger.info(f"\n🎯 HIGH CONFIDENCE TRADES (≥{min_confidence}%): {len(high_conf)}")
    logger.info("")
    
    if high_conf:
        logger.info("Top opportunities:")
        for symbol, confidence, signal, pnl, reason in high_conf[:15]:
            logger.info(f"  {symbol:15} | ✓ {signal:4} | Conf: {confidence:5.1f}% | P&L: ₹{pnl:7,.0f} | {reason}")
        
        logger.info("")
        logger.info(f"💰 Total high-confidence signals: {len(high_conf)}")
        
        # Best opportunities (highest confidence)
        best_3 = high_conf[:3]
        logger.info("")
        logger.info("=" * 80)
        logger.info("RECOMMENDED FOR LIVE TRADING")
        logger.info("=" * 80)
        for i, (symbol, confidence, signal, pnl, reason) in enumerate(best_3, 1):
            logger.info(f"\n#{i}. {symbol} - Confidence: {confidence:.1f}%")
            logger.info(f"    Signal: {signal} | Expected P&L: ₹{pnl:,.0f}")
            logger.info(f"    Details: {reason}")
    else:
        logger.info("❌ No high-confidence opportunities found")
        logger.info("\nMid-confidence trades (for reference):")
        medium_conf = [r for r in all_results if r[1] >= min_confidence * 0.5 and r[2] is not None]
        medium_conf.sort(key=lambda x: x[1], reverse=True)
        for symbol, confidence, signal, pnl, reason in medium_conf[:10]:
            logger.info(f"  {symbol:15} | Conf: {confidence:5.1f}% | {reason}")
    
    logger.info("")
    logger.info("=" * 80)
    
    return high_conf

if __name__ == "__main__":
    high_conf_trades = find_high_confidence_trades(min_confidence=60)
    
    # Summary for trading
    print("\n")
    print("READY FOR TRADING:")
    if high_conf_trades:
        print(f"✅ Found {len(high_conf_trades)} high-confidence trades")
        for symbol, conf, signal, pnl, reason in high_conf_trades[:5]:
            print(f"   • {symbol}: {signal} (Confidence {conf:.0f}%, ₹{pnl:,.0f})")
    else:
        print("❌ No high-confidence trades available")
