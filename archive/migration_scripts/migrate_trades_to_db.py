"""
Migration script: Load all trades from JSON files into PostgreSQL database.
This consolidates trade_journal.json and paper_trades.json into a single unified table.
"""

import json
import logging
from datetime import datetime
from db_manager import get_db, TradeJournalEntry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_datetime(dt_str):
    """Parse datetime string to datetime object."""
    if not dt_str:
        return None
    try:
        # Handle ISO format with optional timezone
        if isinstance(dt_str, str):
            # Remove timezone info if present
            if '+' in dt_str:
                dt_str = dt_str.split('+')[0]
            return datetime.fromisoformat(dt_str)
        return dt_str
    except Exception as e:
        logger.warning(f"Failed to parse datetime {dt_str}: {e}")
        return None


def load_and_merge_trades():
    """Load trade_journal.json and paper_trades.json, merge, and save to DB."""
    
    # Load both JSON files
    journal_trades = []
    paper_trades = {}
    
    try:
        with open('/Users/parthsharma/Desktop/Grow/trade_journal.json', 'r') as f:
            journal_trades = json.load(f)
            logger.info(f"✓ Loaded {len(journal_trades)} trades from trade_journal.json")
    except Exception as e:
        logger.error(f"Failed to load trade_journal.json: {e}")
        return False
    
    try:
        with open('/Users/parthsharma/Desktop/Grow/paper_trades.json', 'r') as f:
            paper_list = json.load(f)
            # Index paper trades by trade_id (or 'id' field)
            for pt in paper_list:
                trade_id = pt.get('id') or pt.get('trade_id')
                if trade_id:
                    paper_trades[trade_id] = pt
            logger.info(f"✓ Loaded {len(paper_trades)} paper trades for enrichment")
    except Exception as e:
        logger.error(f"Failed to load paper_trades.json: {e}")
        paper_trades = {}
    
    # Connect to database
    db = get_db()
    
    try:
        with db.Session() as session:
            # Clear existing trades
            count_before = session.query(TradeJournalEntry).count()
            session.query(TradeJournalEntry).delete()
            session.commit()
            logger.info(f"✓ Cleared {count_before} existing trades from database")
            
            # Migrate all trades
            inserted = 0
            failed = 0
            
            for jt in journal_trades:
                try:
                    trade_id = jt.get('trade_id')
                    if not trade_id:
                        logger.warning(f"Skipping trade without trade_id: {jt}")
                        failed += 1
                        continue
                    
                    # Get paper trading data if available
                    pt = paper_trades.get(trade_id, {})
                    
                    # Create DB entry with merged data
                    entry = TradeJournalEntry(
                        trade_id=trade_id,
                        status=jt.get('status', 'OPEN'),
                        symbol=jt.get('symbol', ''),
                        side=jt.get('side', ''),
                        quantity=int(jt.get('quantity', 1)),
                        trigger=jt.get('trigger', 'auto'),
                        is_paper=jt.get('is_paper', True),
                        
                        # Entry details
                        entry_time=parse_datetime(jt.get('entry_time')),
                        entry_price=float(jt.get('entry_price', 0)),
                        
                        # Exit details
                        exit_time=parse_datetime(jt.get('exit_time')),
                        exit_price=float(jt.get('exit_price', 0)) if jt.get('exit_price') else None,
                        exit_reason=pt.get('exit_reason'),
                        
                        # Paper trading fields (from paper_trades.json)
                        signal=pt.get('signal') or jt.get('pre_trade', {}).get('signal'),
                        confidence=float(pt.get('confidence', 0)) if pt.get('confidence') else None,
                        stop_loss=float(pt.get('stop_loss', 0)) if pt.get('stop_loss') else None,
                        projected_exit=float(pt.get('projected_exit', 0)) if pt.get('projected_exit') else None,
                        peak_pnl=float(pt.get('peak_pnl', 0)) if pt.get('peak_pnl') else None,
                        actual_profit_pct=float(pt.get('actual_profit_pct', 0)) if pt.get('actual_profit_pct') else None,
                        breakeven_price=float(pt.get('breakeven_price', 0)) if pt.get('breakeven_price') else None,
                        
                        # Store full analysis as JSON
                        pre_trade_json=json.dumps(jt.get('pre_trade', {})),
                        post_trade_json=json.dumps(jt.get('post_trade')) if jt.get('post_trade') else None,
                    )
                    
                    session.add(entry)
                    inserted += 1
                    
                except Exception as e:
                    logger.error(f"Failed to insert trade {jt.get('trade_id')}: {e}")
                    failed += 1
            
            # Commit all inserts
            session.commit()
            logger.info(f"✅ Migration complete: {inserted} trades inserted, {failed} failed")
            
            # Verify
            final_count = session.query(TradeJournalEntry).count()
            logger.info(f"✓ Database now contains {final_count} trades")
            
            # Show sample
            sample = session.query(TradeJournalEntry).first()
            if sample:
                logger.info(f"\n📊 Sample trade: {sample.trade_id}")
                logger.info(f"  Symbol: {sample.symbol}, Side: {sample.side}, Qty: {sample.quantity}")
                logger.info(f"  Status: {sample.status}, Entry Price: ₹{sample.entry_price}")
                if sample.exit_price:
                    logger.info(f"  Exit Price: ₹{sample.exit_price}, P&L: {sample.actual_profit_pct}%")
            
            return True
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("TRADE MIGRATION: JSON → PostgreSQL")
    logger.info("=" * 60)
    success = load_and_merge_trades()
    logger.info("=" * 60)
    if success:
        logger.info("✅ Migration successful!")
    else:
        logger.error("❌ Migration failed!")
    logger.info("=" * 60)
