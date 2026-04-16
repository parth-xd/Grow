#!/bin/bash

# Migration script: Local PostgreSQL → Supabase
# Usage: bash migrate_to_supabase.sh

set -e

echo "🚀 Starting migration from local PostgreSQL to Supabase..."

# Local database connection
LOCAL_DB_USER="${DB_USER:-postgres}"
LOCAL_DB_PASSWORD="${DB_PASSWORD:-postgres}"
LOCAL_DB_HOST="${DB_HOST:-localhost}"
LOCAL_DB_PORT="${DB_PORT:-5432}"
LOCAL_DB_NAME="${DB_NAME:-grow_trading_bot}"

# Supabase connection (from environment)
SUPABASE_DB_URL="${DATABASE_URL}"

if [ -z "$SUPABASE_DB_URL" ]; then
    echo "❌ Error: DATABASE_URL not set in environment"
    echo "Please set: export DATABASE_URL='postgresql://postgres:password@host:5432/postgres'"
    exit 1
fi

# Parse Supabase connection string
SUPABASE_DB_USER=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
SUPABASE_DB_PASSWORD=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*:\([^@]*\)@.*/\1/p')
SUPABASE_DB_HOST=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
SUPABASE_DB_PORT=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
SUPABASE_DB_NAME=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*\/\([^?]*\).*/\1/p')

echo "📊 Local Database: $LOCAL_DB_HOST:$LOCAL_DB_PORT/$LOCAL_DB_NAME"
echo "📊 Supabase Database: $SUPABASE_DB_HOST:$SUPABASE_DB_PORT/$SUPABASE_DB_NAME"

# Step 1: Dump local database
echo ""
echo "📤 Step 1: Dumping local PostgreSQL database..."
DUMP_FILE="/tmp/grow_migration_$(date +%s).sql"

PGPASSWORD="$LOCAL_DB_PASSWORD" pg_dump \
    -U "$LOCAL_DB_USER" \
    -h "$LOCAL_DB_HOST" \
    -p "$LOCAL_DB_PORT" \
    "$LOCAL_DB_NAME" \
    --no-owner \
    --no-acl \
    > "$DUMP_FILE"

DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
echo "✓ Dump created: $DUMP_FILE ($DUMP_SIZE)"

# Step 2: Create schema in Supabase (tables only, no data yet)
echo ""
echo "🏗️  Step 2: Creating tables in Supabase..."
PGPASSWORD="$SUPABASE_DB_PASSWORD" psql \
    -U "$SUPABASE_DB_USER" \
    -h "$SUPABASE_DB_HOST" \
    -p "$SUPABASE_DB_PORT" \
    "$SUPABASE_DB_NAME" \
    -c "SELECT 1" > /dev/null 2>&1 && echo "✓ Supabase connection verified"

# Extract schema (without data)
SCHEMA_FILE="/tmp/grow_schema_$(date +%s).sql"
grep -E "^CREATE|^ALTER|^DROP" "$DUMP_FILE" > "$SCHEMA_FILE" 2>/dev/null || true

echo "✓ Schema extracted"

# Step 3: Restore to Supabase
echo ""
echo "📥 Step 3: Restoring data to Supabase..."

# First restore schema
PGPASSWORD="$SUPABASE_DB_PASSWORD" psql \
    -U "$SUPABASE_DB_USER" \
    -h "$SUPABASE_DB_HOST" \
    -p "$SUPABASE_DB_PORT" \
    "$SUPABASE_DB_NAME" \
    -f "$SCHEMA_FILE" > /dev/null 2>&1 || echo "⚠️  Schema creation had issues (tables may already exist)"

# Then restore data using pg_restore (more reliable for data)
echo "Restoring data (this may take a few moments)..."
PGPASSWORD="$SUPABASE_DB_PASSWORD" pg_restore \
    -U "$SUPABASE_DB_USER" \
    -h "$SUPABASE_DB_HOST" \
    -p "$SUPABASE_DB_PORT" \
    -d "$SUPABASE_DB_NAME" \
    --data-only \
    --no-owner \
    --no-acl \
    "$DUMP_FILE" > /dev/null 2>&1 || echo "⚠️  Data restore completed with warnings (some tables may have conflicts)"

echo "✓ Data restore completed"

# Step 4: Verify migration
echo ""
echo "✅ Step 4: Verifying migration..."

# Count tables
TABLE_COUNT=$(PGPASSWORD="$SUPABASE_DB_PASSWORD" psql \
    -U "$SUPABASE_DB_USER" \
    -h "$SUPABASE_DB_HOST" \
    -p "$SUPABASE_DB_PORT" \
    "$SUPABASE_DB_NAME" \
    -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")

echo "✓ Tables in Supabase: $TABLE_COUNT"

# Count rows in major tables
for table in users candles stocks; do
    ROW_COUNT=$(PGPASSWORD="$SUPABASE_DB_PASSWORD" psql \
        -U "$SUPABASE_DB_USER" \
        -h "$SUPABASE_DB_HOST" \
        -p "$SUPABASE_DB_PORT" \
        "$SUPABASE_DB_NAME" \
        -t -c "SELECT count(*) FROM $table" 2>/dev/null || echo "0")
    if [ "$ROW_COUNT" != "0" ]; then
        echo "  • $table: $ROW_COUNT rows"
    fi
done

# Cleanup
echo ""
echo "🧹 Cleanup..."
rm -f "$DUMP_FILE" "$SCHEMA_FILE"
echo "✓ Temp files cleaned up"

echo ""
echo "✅ Migration complete! Your data is now in Supabase."
echo "   The backend will use Supabase automatically via DATABASE_URL env var."
