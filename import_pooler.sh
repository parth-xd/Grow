#!/bin/bash

# Direct import using Supabase session pooler
# Session pooler is more reliable for imports than direct connection

MIGRATION_FILE="/Users/parthsharma/Desktop/Grow/supabase_migration.sql"

# Session pooler endpoint (more reliable than direct)
HOST="aws-1-ap-northeast-1.pooler.supabase.com"
PORT="5432"
DATABASE="postgres"
USER="postgres.vvonimxqwporrofklnvf"
PASSWORD="f6n2GYbXyTYi1TlD"

echo "🚀 Direct import to Supabase (Session Pooler)"
echo ""
echo "📊 Connection:"
echo "   Host: $HOST"
echo "   Port: $PORT"
echo "   Database: $DATABASE"
echo "   User: $USER"
echo ""
echo "📄 File: $MIGRATION_FILE"
echo "   Size: $(du -h "$MIGRATION_FILE" | cut -f1)"
echo ""
echo "⏳ Starting import... (5-10 minutes)"
echo ""

# Import with progress
PGPASSWORD="$PASSWORD" psql \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DATABASE" \
    -f "$MIGRATION_FILE" \
    -v ON_ERROR_STOP=1 \
    2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Import successful!"
    echo ""
    echo "🔍 Verifying data..."
    
    PGPASSWORD="$PASSWORD" psql \
        -h "$HOST" \
        -p "$PORT" \
        -U "$USER" \
        -d "$DATABASE" \
        -c "SELECT 'Candles' as table_name, count(*) as row_count FROM candles UNION ALL SELECT 'Stocks', count(*) FROM stocks UNION ALL SELECT 'News', count(*) FROM global_news;"
    
    echo ""
    echo "✅ Migration complete! Data is now in Supabase."
else
    echo ""
    echo "❌ Import failed"
    exit 1
fi
