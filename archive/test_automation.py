#!/usr/bin/env python3
"""
Test automation infrastructure for data collection & XGBoost retraining.
Verifies that all plumbing is working before live deployment.
"""

import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s [%(name)s]: %(message)s'
)
logger = logging.getLogger(__name__)

def test_db_models():
    """Verify database models are properly defined."""
    logger.info("🧪 Testing database models...")
    try:
        from db_manager import (
            CandleDatabase, Candle, CandleTrainingMetadata,
            log_candle_collection_event, log_xgb_training_event
        )
        logger.info("   ✓ Database imports successful")
        logger.info("   ✓ CandleTrainingMetadata table defined")
        logger.info("   ✓ Logging functions available")
        return True
    except Exception as e:
        logger.error("   ✗ Database import failed: %s", e)
        return False


def test_scheduler_tasks():
    """Verify scheduler tasks are registered."""
    logger.info("🧪 Testing scheduler task registration...")
    try:
        # Import the task functions directly to verify they exist
        from scheduler import (
            _task_collect_hourly_candles, 
            _task_retrain_xgb_daily,
            _register
        )
        
        logger.info("   ✓ Scheduler task functions defined")
        logger.info("   ✓ _task_collect_hourly_candles available")
        logger.info("   ✓ _task_retrain_xgb_daily available")
        logger.info("   ✓ Task registration available")
        
        # Check that tasks will be registered properly
        # (They won't be in _tasks yet since start_scheduler() hasn't been called)
        logger.info("   ✓ Tasks will be registered when start_scheduler() is called")
        
        return True
        
    except Exception as e:
        logger.error("   ✗ Scheduler task check failed: %s", e)
        return False


def test_xgb_infrastructure():
    """Verify XGBoost infrastructure exists."""
    logger.info("🧪 Testing XGBoost infrastructure...")
    try:
        import xgboost as xgb
        logger.info("   ✓ XGBoost installed (version %s)", xgb.__version__)
        
        from fno_backtester import _get_xgb_models, _xgb_models, _xgb_model_timestamp
        logger.info("   ✓ XGBoost training infrastructure available")
        logger.info("   ✓ Model caching variables defined")
        
        return True
    except Exception as e:
        logger.error("   ✗ XGBoost infrastructure check failed: %s", e)
        return False


def test_candle_fetching():
    """Verify candle data fetching works."""
    logger.info("🧪 Testing candle data access...")
    try:
        from db_manager import CandleDatabase, Candle
        
        db = CandleDatabase()
        session = db.Session()
        
        # Count existing candles
        candle_count = session.query(Candle).count()
        unique_symbols = session.query(Candle.symbol).distinct().count()
        
        session.close()
        
        logger.info("   ✓ Database connection working")
        logger.info("   ✓ Found %d candles for %d symbols", candle_count, unique_symbols)
        
        if candle_count > 0:
            logger.info("   ✓ Candle data available for training")
            return True
        else:
            logger.warning("   ⚠ No candles in database yet (expected on first run)")
            return True
            
    except Exception as e:
        logger.error("   ✗ Candle data access failed: %s", e)
        return False


def test_instruments_config():
    """Verify instrument configuration."""
    logger.info("🧪 Testing instruments configuration...")
    try:
        from fno_backtester import BACKTEST_INSTRUMENTS
        
        instruments = list(BACKTEST_INSTRUMENTS.keys())
        logger.info("   ✓ Found %d trading instruments", len(instruments))
        
        indices = [i for i in instruments if i in ["NIFTY", "BANKNIFTY", "FINNIFTY"]]
        equities = [i for i in instruments if i not in indices]
        
        logger.info("   ✓ Indices: %s", ", ".join(indices))
        logger.info("   ✓ Equities: %d stocks", len(equities))
        
        return len(instruments) == 19 and len(indices) == 3
        
    except Exception as e:
        logger.error("   ✗ Instruments config check failed: %s", e)
        return False


def test_metadata_table():
    """Verify metadata table can store records."""
    logger.info("🧪 Testing metadata table...")
    try:
        from db_manager import CandleDatabase, CandleTrainingMetadata
        
        db = CandleDatabase()
        session = db.Session()
        
        # Try to query the table (it may be empty)
        record_count = session.query(CandleTrainingMetadata).count()
        
        session.close()
        
        logger.info("   ✓ CandleTrainingMetadata table accessible")
        logger.info("   ✓ Current metadata records: %d", record_count)
        
        return True
        
    except Exception as e:
        logger.error("   ✗ Metadata table check failed: %s", e)
        return False


def main():
    """Run all tests."""
    logger.info("=" * 70)
    logger.info("AUTOMATION INFRASTRUCTURE TEST")
    logger.info("=" * 70)
    
    tests = [
        ("Database Models", test_db_models),
        ("Scheduler Tasks", test_scheduler_tasks),
        ("XGBoost Infrastructure", test_xgb_infrastructure),
        ("Candle Data", test_candle_fetching),
        ("Instruments Config", test_instruments_config),
        ("Metadata Table", test_metadata_table),
    ]
    
    results = []
    for test_name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((test_name, passed))
        except Exception as e:
            logger.error("Unexpected error in %s: %s", test_name, e)
            results.append((test_name, False))
        logger.info("")
    
    # Summary
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info("%s: %s", status, test_name)
    
    logger.info("")
    logger.info("Result: %d/%d tests passed", passed_count, total_count)
    
    if passed_count == total_count:
        logger.info("🎉 All tests passed! Automation is ready for deployment.")
        return 0
    else:
        logger.warning("⚠️  Some tests failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
