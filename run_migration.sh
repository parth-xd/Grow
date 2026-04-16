#!/bin/bash

# Direct Supabase migration via psql
# Bypasses web editor size limit

set -e

SUPABASE_DB_URL="${DATABASE_URL}"

if [ -z "$SUPABASE_DB_URL" ]; then
    echo "❌ Error: DATABASE_URL not set"
    echo "Set it with: export DATABASE_URL='postgresql://postgres:password@host:5432/postgres?sslmode=require'"
    exit 1
fi

MIGRATION_FILE="/Users/parthsharma/Desktop/Grow/supabase_migration.sql"

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "❌ Migration file not found: $MIGRATION_FILE"
    exit 1
fi

echo "🚀 Starting direct PostgreSQL migration to Supabase..."
echo "📊 Database URL: $SUPABASE_DB_URL"
echo "📄 Migration file: $MIGRATION_FILE ($(du -h "$MIGRATION_FILE" | cut -f1))"
echo ""

# Run migration with progress
echo "⏳ Importing data... This may take 5-10 minutes..."
PGPASSWORD="${SUPABASE_DB_URL##*://}" 
PGPASSWORD="${PGPASSWORD%%@*}"

# Extract password from URL
PASSWORD=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*:\([^@]*\)@.*/\1/p')
USER=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
HOST=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
PORT=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
DBNAME=$(echo "$SUPABASE_DB_URL" | sed -n 's/.*\/\([^?]*\).*/\1/p')

echo "Connecting to: $HOST:$PORT/$DBNAME as $USER"
echo ""

# Run psql with file input
PGPASSWORD="$PASSWORD" psql \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DBNAME" \
    -f "$MIGRATION_FILE" \
    --set=sslmode=require

echo ""
echo "✅ Migration complete!"
echo "   Your data is now in Supabase."
