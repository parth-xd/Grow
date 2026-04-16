#!/usr/bin/env python3
"""
Database schema audit: Compare local PostgreSQL vs Supabase
Ensures both databases have identical schemas before migration
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
    sys.exit(1)

def get_schema_info(engine, db_name="Unknown"):
    """Extract complete schema information from database"""
    inspector = inspect(engine)
    
    schema = {
        'tables': {},
        'indexes': {},
        'constraints': {}
    }
    
    tables = inspector.get_table_names()
    
    for table in tables:
        # Get columns
        columns = inspector.get_columns(table)
        schema['tables'][table] = {
            'columns': [
                {
                    'name': col['name'],
                    'type': str(col['type']),
                    'nullable': col['nullable'],
                    'default': col['default'],
                    'primary_key': col.get('primary_key', False)
                }
                for col in columns
            ],
            'row_count': None  # Will be filled later
        }
        
        # Get indexes
        indexes = inspector.get_indexes(table)
        schema['indexes'][table] = indexes
        
        # Get constraints
        constraints = inspector.get_unique_constraints(table)
        schema['constraints'][table] = constraints
    
    return schema, tables

def count_rows(engine, table_name):
    """Count rows in a table"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT count(*) FROM {table_name}"))
            return result.scalar()
    except Exception as e:
        logger.warning(f"Could not count rows in {table_name}: {e}")
        return None

def compare_schemas(local_schema, local_tables, supabase_schema, supabase_tables):
    """Compare two schemas and report differences"""
    print("\n" + "="*80)
    print("SCHEMA COMPARISON REPORT")
    print("="*80)
    
    local_only = set(local_tables) - set(supabase_tables)
    supabase_only = set(supabase_tables) - set(local_tables)
    common_tables = set(local_tables) & set(supabase_tables)
    
    issues = []
    
    # Check for tables only in local
    if local_only:
        print(f"\n⚠️  Tables only in LOCAL database ({len(local_only)}):")
        for table in sorted(local_only):
            print(f"   • {table}")
            issues.append(f"Table '{table}' missing in Supabase")
    
    # Check for tables only in Supabase
    if supabase_only:
        print(f"\n⚠️  Tables only in SUPABASE database ({len(supabase_only)}):")
        for table in sorted(supabase_only):
            print(f"   • {table}")
    
    # Compare columns in common tables
    column_mismatches = []
    for table in sorted(common_tables):
        local_cols = {col['name']: col for col in local_schema['tables'][table]['columns']}
        supabase_cols = {col['name']: col for col in supabase_schema['tables'][table]['columns']}
        
        local_col_names = set(local_cols.keys())
        supabase_col_names = set(supabase_cols.keys())
        
        # Missing columns
        missing_in_supabase = local_col_names - supabase_col_names
        if missing_in_supabase:
            for col in missing_in_supabase:
                msg = f"Column '{col}' missing in Supabase.{table}"
                column_mismatches.append(msg)
                issues.append(msg)
        
        # Extra columns in Supabase
        extra_in_supabase = supabase_col_names - local_col_names
        if extra_in_supabase:
            for col in extra_in_supabase:
                msg = f"Column '{col}' extra in Supabase.{table}"
                column_mismatches.append(msg)
        
        # Type mismatches
        for col in local_col_names & supabase_col_names:
            local_type = local_cols[col]['type']
            supabase_type = supabase_cols[col]['type']
            if local_type.lower() != supabase_type.lower():
                msg = f"Type mismatch in {table}.{col}: LOCAL={local_type} vs SUPABASE={supabase_type}"
                column_mismatches.append(msg)
                issues.append(msg)
    
    if column_mismatches:
        print(f"\n⚠️  Column mismatches ({len(column_mismatches)}):")
        for issue in column_mismatches:
            print(f"   • {issue}")
    
    print(f"\n📊 SUMMARY:")
    print(f"   • Common tables: {len(common_tables)}")
    print(f"   • Tables only in LOCAL: {len(local_only)}")
    print(f"   • Tables only in SUPABASE: {len(supabase_only)}")
    print(f"   • Column mismatches: {len(column_mismatches)}")
    
    return len(issues) == 0, issues

def audit():
    """Perform schema audit"""
    print("🔍 Starting database schema audit...\n")
    
    # Connect to local DB
    print("📊 Connecting to LOCAL database...")
    try:
        local_engine = create_engine(LOCAL_DB_URL, echo=False)
        with local_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✓ Local DB connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to local database: {e}")
        sys.exit(1)
    
    # Get local schema
    print("📋 Analyzing LOCAL schema...")
    try:
        local_schema, local_tables = get_schema_info(local_engine, "LOCAL")
        print(f"✓ Found {len(local_tables)} tables")
        for table in sorted(local_tables):
            cols = len(local_schema['tables'][table]['columns'])
            rows = count_rows(local_engine, table)
            if rows is not None:
                print(f"   • {table}: {cols} columns, {rows} rows")
            else:
                print(f"   • {table}: {cols} columns")
    except Exception as e:
        logger.error(f"❌ Failed to analyze local schema: {e}")
        sys.exit(1)
    
    # Connect to Supabase
    print("\n📊 Connecting to SUPABASE database...")
    try:
        supabase_url = SUPABASE_DB_URL
        if "sslmode" not in supabase_url:
            supabase_url += "?sslmode=require"
        
        supabase_engine = create_engine(
            supabase_url,
            echo=False,
            connect_args={"connect_timeout": 10},
            pool_timeout=10,
            pool_pre_ping=True
        )
        with supabase_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✓ Supabase connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to Supabase: {e}")
        logger.error("   Make sure DATABASE_URL is correctly set and network is available")
        sys.exit(1)
    
    # Get Supabase schema
    print("📋 Analyzing SUPABASE schema...")
    try:
        supabase_schema, supabase_tables = get_schema_info(supabase_engine, "SUPABASE")
        print(f"✓ Found {len(supabase_tables)} tables")
        for table in sorted(supabase_tables):
            cols = len(supabase_schema['tables'][table]['columns'])
            rows = count_rows(supabase_engine, table)
            if rows is not None:
                print(f"   • {table}: {cols} columns, {rows} rows")
            else:
                print(f"   • {table}: {cols} columns")
    except Exception as e:
        logger.error(f"❌ Failed to analyze Supabase schema: {e}")
        sys.exit(1)
    
    # Compare
    print("\n🔄 Comparing schemas...")
    schemas_match, issues = compare_schemas(local_schema, local_tables, supabase_schema, supabase_tables)
    
    if schemas_match:
        print("\n" + "="*80)
        print("✅ SCHEMAS MATCH - Ready for data migration!")
        print("="*80)
        return True
    else:
        print("\n" + "="*80)
        print("⚠️  SCHEMA MISMATCHES DETECTED")
        print("="*80)
        print("\nIssues found:")
        for issue in issues:
            print(f"  • {issue}")
        print("\n⚠️  Please fix schema differences before migrating data.")
        return False

if __name__ == "__main__":
    success = audit()
    sys.exit(0 if success else 1)
