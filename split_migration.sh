#!/bin/bash

# Split large SQL file into smaller chunks for Supabase web editor
# Each chunk will be ~2MB (well under the limit)

INPUT_FILE="/Users/parthsharma/Desktop/Grow/supabase_migration.sql"
OUTPUT_DIR="/Users/parthsharma/Desktop/Grow/migration_chunks"

mkdir -p "$OUTPUT_DIR"

echo "📂 Splitting migration file into chunks..."
echo "   Input: $INPUT_FILE ($(du -h "$INPUT_FILE" | cut -f1))"

# Get line count
LINE_COUNT=$(wc -l < "$INPUT_FILE")
echo "   Total lines: $LINE_COUNT"

# Split into ~1000 line chunks (each ~1MB)
LINES_PER_CHUNK=1000
CHUNK_NUM=1

split -l $LINES_PER_CHUNK "$INPUT_FILE" "$OUTPUT_DIR/chunk_" -d

echo ""
echo "✅ Chunks created:"
ls -lh "$OUTPUT_DIR/" | tail -n +2 | awk '{print "   • " $9 " (" $5 ")"}'

echo ""
echo "📖 IMPORT INSTRUCTIONS:"
echo "===================="
echo ""
echo "1. Go to Supabase SQL Editor"
echo "2. For each chunk (chunk_00, chunk_01, etc):"
echo "   a. Open the file: $OUTPUT_DIR/chunk_XX"
echo "   b. Copy the contents"
echo "   c. Paste into Supabase SQL Editor"
echo "   d. Click RUN"
echo "   e. Wait for completion (you'll see 'No rows' or the rows affected)"
echo "   f. Move to next chunk"
echo ""
echo "3. Verify after all chunks are imported:"
echo "   SELECT count(*) FROM candles;"
echo "   Should return: 250102"
echo ""
