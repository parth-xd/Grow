"""
Alter trade_journal table to add new columns for paper trading metrics.
"""

import logging
from sqlalchemy import text
from db_manager import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_columns_to_trade_journal():
    """Add new columns to existing trade_journal table."""
    db = get_db()
    
    columns_to_add = [
        ("is_paper", "BOOLEAN DEFAULT TRUE"),
        ("exit_reason", "VARCHAR(100)"),
        ("signal", "VARCHAR(20)"),
        ("confidence", "FLOAT"),
        ("stop_loss", "FLOAT"),
        ("projected_exit", "FLOAT"),
        ("peak_pnl", "FLOAT"),
        ("actual_profit_pct", "FLOAT"),
        ("breakeven_price", "FLOAT"),
    ]
    
    try:
        with db.engine.connect() as conn:
            for col_name, col_type in columns_to_add:
                try:
                    # Check if column already exists
                    check_sql = text(f"""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'trade_journal' 
                        AND column_name = '{col_name}'
                    """)
                    result = conn.execute(check_sql).fetchone()
                    
                    if result:
                        logger.info(f"✓ Column '{col_name}' already exists")
                    else:
                        # Add the column
                        alter_sql = text(f"ALTER TABLE trade_journal ADD COLUMN {col_name} {col_type}")
                        conn.execute(alter_sql)
                        conn.commit()
                        logger.info(f"✅ Added column '{col_name}'")
                except Exception as e:
                    logger.error(f"Error with column '{col_name}': {e}")
            
            logger.info("\n✅ Schema migration complete!")
            return True
            
    except Exception as e:
        logger.error(f"Failed to add columns: {e}")
        return False

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("SCHEMA MIGRATION: Adding paper trading columns")
    logger.info("=" * 60)
    success = add_columns_to_trade_journal()
    logger.info("=" * 60)
