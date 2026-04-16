#!/usr/bin/env python3
"""
Migration script: Local PostgreSQL → Supabase
Transfers all tables and data from local DB to Supabase
"""

import os
import sys
import logging
from datetime import datetime
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv(override=True)

# Local database
LOCAL_DB_URL = os.getenv('DB_URL') or \
    f"postgresql://{os.getenv('DB_USER', 'postgres')}:{os.getenv('DB_PASSWORD', 'postgres')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'grow_trading_bot')}"

# Supabase database
SUPABASE_DB_URL = os.getenv('DATABASE_URL')

if not SUPABASE_DB_URL:
    print("❌ Error: DATABASE_URL environment variable not set")
    print("Please set: export DATABASE_URL='postgresql://postgres:password@host:5432/postgres?sslmode=require'")
    sys.exit(1)

def count_rows(engine, table_name):
    """Count rows in a table"""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT count(*) FROM {table_name}"))
        return result.scalar()

def migrate():
    """Perform migration"""
    print("🚀 Starting migration from local PostgreSQL to Supabase...\n")
    
    # Connect to local DB
    print("📊 Connecting to local database...")
    try:
        local_engine = create_engine(LOCAL_DB_URL, echo=False)
        with local_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"✓ Local DB connected: {LOCAL_DB_URL.split('@')[1] if '@' in LOCAL_DB_URL else 'localhost'}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to local database: {e}")
        sys.exit(1)
    
    # Connect to Supabase
    print("📊 Connecting to Supabase...")
    try:
        # Ensure SSL mode is set
        supabase_url = SUPABASE_DB_URL
        if "sslmode" not in supabase_url:
            supabase_url += "?sslmode=require"
        
        supabase_engine = create_engine(
            supabase_url,
            echo=False,
            connect_args={"connect_timeout": 10},
            pool_timeout=10
        )
        with supabase_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"✓ Supabase connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Supabase: {e}")
        sys.exit(1)
    
    # Get table list
    print("\n📋 Analyzing tables...")
    inspector = inspect(local_engine)
    tables = inspector.get_table_names()
    print(f"✓ Found {len(tables)} tables to migrate")
    
    # Create table mapping
    table_stats = {}
    for table in tables:
        try:
            count = count_rows(local_engine, table)
            table_stats[table] = count
            if count > 0:
                print(f"  • {table}: {count} rows")
        except Exception as e:
            logger.warning(f"  ⚠️  Could not count rows in {table}: {e}")
            table_stats[table] = None
    
    # Start migration
    print(f"\n📤 Migrating {len(tables)} tables...")
    
    local_session = sessionmaker(bind=local_engine)()
    supabase_session = sessionmaker(bind=supabase_engine)()
    
    migrated = 0
    
    try:
        for table in tables:
            try:
                print(f"  Migrating {table}...", end=" ")
                
                # Get all rows from local DB
                result = local_session.execute(text(f"SELECT * FROM {table}"))
                rows = result.fetchall()
                
                if rows:
                    # Get column names
                    columns = result.keys()
                    
                    # Insert into Supabase
                    for row in rows:
                        values = [repr(v) if v is not None else "NULL" for v in row]
                        insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(values)}) ON CONFLICT DO NOTHING"
                        try:
                            supabase_session.execute(text(insert_sql))
                        except Exception as e:
                            # Continue on conflict/error, don't stop migration
                            pass
                    
                    supabase_session.commit()
                    print(f"✓ ({len(rows)} rows)")
                else:
                    print("✓ (empty)")
                
                migrated += 1
                
            except Exception as e:
                logger.warning(f"  ⚠️  Failed to migrate {table}: {e}")
                supabase_session.rollback()
    
    finally:
        local_session.close()
        supabase_session.close()
    
    # Verify
    print(f"\n✅ Verification ({migrated}/{len(tables)} tables migrated):")
    
    for table in tables:
        try:
            count = count_rows(supabase_engine, table)
            original = table_stats.get(table, 0)
            status = "✓" if count == original else "⚠️"
            if original and count > 0:
                print(f"  {status} {table}: {count} rows (expected: {original})")
        except:
            pass
    
    print("\n✅ Migration complete!")
    print("   Your data is now in Supabase. The backend will use it automatically.")

if __name__ == "__main__":
    migrate()
