"""
Database migration: Create users table for multi-tenant authentication.
Run this once before starting the app.
"""

import os
import logging
from sqlalchemy import create_engine
from auth_manager import Base, User
from config import DB_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    """Create users table if it doesn't exist."""
    try:
        engine = create_engine(DB_URL)
        
        # Create all tables defined in Base
        Base.metadata.create_all(engine)
        
        logger.info("✓ Database migration complete — users table ready")
    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate()
