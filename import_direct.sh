#!/bin/bash

# Direct psql import to Supabase
# This connects directly to Supabase and imports the entire dump at once

MIGRATION_FILE="/Users/parthsharma/Desktop/Grow/supabase_migration.sql"
DB_URL="postgresql://postgres:f6n2GYbXyTYi1TlD@db.vvonimxqwporrofklnvf.supabase.co:5432/postgres?sslmode=require"

echo "🚀 Connecting to Supabase and importing data..."
echo ""
echo "📊 Database: db.vvonimxqwporrofklnvf.supabase.co"
echo "📄 File: $MIGRATION_FILE"
echo "📈 Size: $(du -h "$MIGRATION_FILE" | cut -f1)"
echo ""

# Extract connection details from URL
PASSWORD=$(echo "$DB_URL" | sed -n 's/.*:\([^@]*\)@.*/\1/p')
USER=$(echo "$DB_URL" | sed -n 's/.*:\/\/\([^:]*\).*/\1/p')
HOST=$(echo "$DB_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
PORT=$(echo "$DB_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
DBNAME=$(echo "$DB_URL" | sed -n 's/.*\/\([^?]*\).*/\1/p')

echo "🔗 Connection Details:"
echo "   Host: $HOST"
echo "   Port: $PORT"
echo "   Database: $DBNAME"
echo "   User: $USER"
echo ""
echo "⏳ Importing... (This will take 5-10 minutes)"
echo ""

# Run import with progress indicator
PGPASSWORD="$PASSWORD" psql \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DBNAME" \
    -f "$MIGRATION_FILE" \
    -v ON_ERROR_STOP=1

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Import successful!"
    echo ""
    echo "🔍 Verifying data..."
    
    # Verify import
    PGPASSWORD="$PASSWORD" psql \
        -h "$HOST" \
        -p "$PORT" \
        -U "$USER" \
        -d "$DBNAME" \
        -c "SELECT count(*) as candles_count FROM candles;" \
        -c "SELECT count(*) as stocks_count FROM stocks;" \
        -c "SELECT count(*) as news_count FROM global_news;"
    
    echo ""
    echo "✅ Data migration complete!"
else
    echo ""
    echo "❌ Import failed. Check the errors above."
    exit 1
fi
