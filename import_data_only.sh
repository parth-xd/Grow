#!/bin/bash

# Import data only (skip table creation errors)

MIGRATION_FILE="/Users/parthsharma/Desktop/Grow/supabase_migration.sql"

HOST="aws-1-ap-northeast-1.pooler.supabase.com"
PORT="5432"
DATABASE="postgres"
USER="postgres.vvonimxqwporrofklnvf"
PASSWORD="f6n2GYbXyTYi1TlD"

echo "🚀 Importing data to Supabase (skipping existing tables)"
echo ""
echo "⏳ Starting... (this may take 10 minutes)"
echo ""

# Import WITHOUT -v ON_ERROR_STOP=1 so it continues even if tables exist
PGPASSWORD="$PASSWORD" psql \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DATABASE" \
    -f "$MIGRATION_FILE" \
    2>&1 | grep -v "ERROR.*already exists" | tail -50

echo ""
echo "✅ Import completed!"
echo ""
echo "🔍 Verifying data..."

PGPASSWORD="$PASSWORD" psql \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DATABASE" \
    -c "SELECT 'candles' as table_name, count(*) as rows FROM candles UNION ALL SELECT 'stocks', count(*) FROM stocks UNION ALL SELECT 'global_news', count(*) FROM global_news UNION ALL SELECT 'users', count(*) FROM users;" \
    2>&1

echo ""
echo "✅ Data migration complete!"
