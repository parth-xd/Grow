#!/usr/bin/env python3
"""
Database management utility for Groww Trading Bot.
Usage: python db_cli.py [command] [args]

Commands:
  init            Initialize database tables
  stats           Show database statistics
  sync SYMBOL     Manually sync symbol from API (e.g., RELIANCE)
  sync-all        Sync all watchlist symbols
  prune SYMBOL    Delete old candles for a symbol (keep 365 days)
  clear SYMBOL    Delete ALL candles for a symbol (caution!)
  export SYMBOL   Export candles to CSV
"""

import sys
import os
import logging
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

from config import DB_URL, WATCHLIST, PREDICTION_LOOKBACK_DAYS, CANDLE_INTERVAL_MINUTES
from db_manager import get_db
from bot import sync_candles_from_api


def show_stats():
    """Display database statistics."""
    db = get_db(DB_URL)
    stats = db.get_stats()
    
    if not stats:
        logger.warning("Database empty or connection failed")
        return
    
    logger.info("=" * 60)
    logger.info(f"📊 DATABASE STATISTICS")
    logger.info("=" * 60)
    logger.info(f"Total candles: {stats['total_candles']:,}")
    logger.info(f"Symbols tracked: {stats['symbols']}")
    logger.info("=" * 60)


def sync_symbol(symbol):
    """Sync a specific symbol from API."""
    logger.info(f"🔄 Syncing {symbol}...")
    
    count = sync_candles_from_api(
        symbol,
        days=PREDICTION_LOOKBACK_DAYS,
        interval=CANDLE_INTERVAL_MINUTES
    )
    
    if count > 0:
        logger.info(f"✓ Synced {count} new candles for {symbol}")
    else:
        logger.info(f"↷ No new candles for {symbol}")


def sync_all():
    """Sync all watchlist symbols."""
    logger.info(f"🔄 Syncing all {len(WATCHLIST)} watchlist symbols...")
    
    total = 0
    for symbol in WATCHLIST:
        count = sync_candles_from_api(
            symbol.strip(),
            days=PREDICTION_LOOKBACK_DAYS,
            interval=CANDLE_INTERVAL_MINUTES
        )
        total += count
    
    logger.info(f"✓ Total synced: {total} candles across {len(WATCHLIST)} symbols")


def prune_symbol(symbol, keep_days=365):
    """Delete old candles for a symbol."""
    db = get_db(DB_URL)
    logger.warning(f"🗑️  Pruning {symbol} (keeping only {keep_days} days)...")
    db.prune_old_candles(symbol, keep_days=keep_days)
    logger.info(f"✓ Pruned {symbol}")


def clear_symbol(symbol):
    """Delete ALL candles for a symbol (dangerous!)."""
    response = input(f"⚠️  Are you SURE you want to delete ALL candles for {symbol}? (yes/no): ")
    if response.lower() != "yes":
        logger.info("Cancelled")
        return
    
    db = get_db(DB_URL)
    session = db.Session()
    from db_manager import Candle
    
    try:
        count = session.query(Candle).filter_by(symbol=symbol).delete()
        session.commit()
        logger.warning(f"🗑️  Deleted {count} candles for {symbol}")
    except Exception as e:
        session.rollback()
        logger.error(f"✗ Error: {e}")
    finally:
        session.close()


def export_symbol(symbol):
    """Export candles to CSV."""
    db = get_db(DB_URL)
    df = db.get_candles(symbol, days=None)
    
    if df.empty:
        logger.error(f"No data for {symbol}")
        return
    
    filename = f"{symbol}_candles.csv"
    df.to_csv(filename, index=False)
    logger.info(f"✓ Exported {len(df)} candles to {filename}")


def init_db():
    """Initialize database."""
    logger.info("🗄️  Initializing database...")
    db = get_db(DB_URL)
    logger.info("✓ Database initialized successfully")
    show_stats()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == "init":
            init_db()
        elif command == "stats":
            show_stats()
        elif command == "sync":
            if len(sys.argv) < 3:
                logger.error("Usage: python db_cli.py sync SYMBOL")
                return
            sync_symbol(sys.argv[2].upper())
        elif command == "sync-all":
            sync_all()
        elif command == "prune":
            if len(sys.argv) < 3:
                logger.error("Usage: python db_cli.py prune SYMBOL")
                return
            prune_symbol(sys.argv[2].upper())
        elif command == "clear":
            if len(sys.argv) < 3:
                logger.error("Usage: python db_cli.py clear SYMBOL")
                return
            clear_symbol(sys.argv[2].upper())
        elif command == "export":
            if len(sys.argv) < 3:
                logger.error("Usage: python db_cli.py export SYMBOL")
                return
            export_symbol(sys.argv[2].upper())
        else:
            logger.error(f"Unknown command: {command}")
            print(__doc__)
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
