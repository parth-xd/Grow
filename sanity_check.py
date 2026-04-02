#!/usr/bin/env python3
"""Quick sanity check - verify trading flow works with new automation infrastructure."""

import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("=" * 70)
    logger.info("TRADING FLOW SANITY CHECK")
    logger.info("=" * 70)
    
    try:
        # Test 1: Can we fetch candles for all instruments?
        logger.info("\n📊 Testing candle availability:")
        from fno_backtester import BACKTEST_INSTRUMENTS, _fetch_candles_from_db
        
        for symbol in list(BACKTEST_INSTRUMENTS.keys())[:3]:
            candles = _fetch_candles_from_db(symbol)
            logger.info(f"   {symbol}: {len(candles)} candles available")
        
        # Test 2: Are XGBoost models available?
        logger.info("\n🧠 Testing XGBoost models:")
        from fno_backtester import _get_xgb_models
        
        models = _get_xgb_models()
        if models:
            logger.info("   ✓ XGBoost models available")
            logger.info(f"   Long model: {models['long'].__class__.__name__}")
            logger.info(f"   Short model: {models['short'].__class__.__name__}")
        else:
            logger.error("   ✗ XGBoost models not ready")
            return 1
        
        # Test 3: Can we get a live signal?
        logger.info("\n📈 Testing live signal generation:")
        from fno_backtester import get_xgb_signal
        
        signal = get_xgb_signal('NIFTY')
        logger.info(f"   NIFTY signal: {signal.get('direction', 'N/A')}")
        logger.info(f"   Confidence: {signal.get('confidence', 'N/A'):.2%}")
        logger.info(f"   Recommendation: {signal.get('recommendation', 'N/A')}")
        
        # Test 4: Check scheduler is ready
        logger.info("\n⏰ Testing scheduler infrastructure:")
        from scheduler import _task_collect_hourly_candles, _task_retrain_xgb_daily
        logger.info("   ✓ Collection task available")
        logger.info("   ✓ Retraining task available")
        
        # Test 5: Check metadata tracking
        logger.info("\n📋 Testing metadata tracking:")
        from db_manager import CandleTrainingMetadata, CandleDatabase
        db = CandleDatabase()
        session = db.Session()
        count = session.query(CandleTrainingMetadata).count()
        session.close()
        logger.info(f"   ✓ Metadata table ready ({count} historical records)")
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ ALL SYSTEMS GO - Trading flow is operational!")
        logger.info("=" * 70)
        
        return 0
        
    except Exception as e:
        logger.error(f"\n❌ Sanity check failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
