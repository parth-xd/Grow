#!/usr/bin/env python3
"""Split SQL file into chunks for Supabase web editor"""

import os

INPUT_FILE = "/Users/parthsharma/Desktop/Grow/supabase_migration.sql"
OUTPUT_DIR = "/Users/parthsharma/Desktop/Grow/migration_chunks"
CHUNK_SIZE_MB = 10  # 10MB chunks (well under web editor limit)
CHUNK_SIZE_BYTES = CHUNK_SIZE_MB * 1024 * 1024

os.makedirs(OUTPUT_DIR, exist_ok=True)

print("📂 Splitting migration file into chunks...")

with open(INPUT_FILE, 'r') as f:
    total_size = os.path.getsize(INPUT_FILE)
    print(f"   Input: {INPUT_FILE}")
    print(f"   Size: {total_size / (1024*1024):.1f} MB")
    print(f"   Chunk size: {CHUNK_SIZE_MB} MB")
    print()

chunk_num = 0
current_size = 0
current_chunk = []

with open(INPUT_FILE, 'r') as f:
    for line in f:
        current_chunk.append(line)
        current_size += len(line.encode('utf-8'))
        
        if current_size >= CHUNK_SIZE_BYTES:
            # Write chunk
            chunk_file = f"{OUTPUT_DIR}/chunk_{chunk_num:02d}.sql"
            with open(chunk_file, 'w') as out:
                out.writelines(current_chunk)
            
            file_size = os.path.getsize(chunk_file)
            print(f"✓ chunk_{chunk_num:02d}.sql ({file_size / (1024*1024):.1f} MB)")
            
            chunk_num += 1
            current_chunk = []
            current_size = 0

# Write remaining
if current_chunk:
    chunk_file = f"{OUTPUT_DIR}/chunk_{chunk_num:02d}.sql"
    with open(chunk_file, 'w') as out:
        out.writelines(current_chunk)
    
    file_size = os.path.getsize(chunk_file)
    print(f"✓ chunk_{chunk_num:02d}.sql ({file_size / (1024*1024):.1f} MB)")
    chunk_num += 1

print()
print(f"✅ Created {chunk_num} chunks")
print()
print("📖 IMPORT INSTRUCTIONS:")
print("=" * 60)
print()
print("1. Go to Supabase: https://app.supabase.com")
print("2. Open SQL Editor → New Query")
print()
print(f"3. Import chunks in order:")
for i in range(chunk_num):
    print(f"   • Open: migration_chunks/chunk_{i:02d}.sql")
    print(f"     Copy all content → Paste in SQL Editor → Click RUN")
    print(f"     Wait for 'Query complete' message")
    print()

print("4. After all chunks are imported, run verification:")
print("   SELECT count(*) FROM candles;")
print("   Should return: 250102")
print()
print("Location of chunks:")
print(f"  {OUTPUT_DIR}")
