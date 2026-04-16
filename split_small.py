#!/usr/bin/env python3
"""Split SQL into very small chunks (1MB max)"""

import os

INPUT_FILE = "/Users/parthsharma/Desktop/Grow/supabase_migration.sql"
OUTPUT_DIR = "/Users/parthsharma/Desktop/Grow/migration_chunks"
CHUNK_SIZE_MB = 1  # 1MB chunks
CHUNK_SIZE_BYTES = CHUNK_SIZE_MB * 1024 * 1024

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Clean old chunks
for f in os.listdir(OUTPUT_DIR):
    if f.endswith('.sql'):
        os.remove(os.path.join(OUTPUT_DIR, f))

print("📂 Splitting migration file into 1MB chunks...")

with open(INPUT_FILE, 'r') as f:
    total_size = os.path.getsize(INPUT_FILE)
    print(f"   Input: {INPUT_FILE}")
    print(f"   Size: {total_size / (1024*1024):.1f} MB")
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
            chunk_file = f"{OUTPUT_DIR}/chunk_{chunk_num:03d}.sql"
            with open(chunk_file, 'w') as out:
                out.writelines(current_chunk)
            
            file_size = os.path.getsize(chunk_file)
            print(f"✓ chunk_{chunk_num:03d}.sql ({file_size / 1024:.0f} KB)")
            
            chunk_num += 1
            current_chunk = []
            current_size = 0

# Write remaining
if current_chunk:
    chunk_file = f"{OUTPUT_DIR}/chunk_{chunk_num:03d}.sql"
    with open(chunk_file, 'w') as out:
        out.writelines(current_chunk)
    
    file_size = os.path.getsize(chunk_file)
    print(f"✓ chunk_{chunk_num:03d}.sql ({file_size / 1024:.0f} KB)")
    chunk_num += 1

print()
print(f"✅ Created {chunk_num} small chunks (1MB each)")
print()
print("📖 QUICK IMPORT:")
print("=" * 60)
print()
print("Total chunks to import: ", chunk_num)
print()
print("For each chunk:")
print("  1. Open: /Users/parthsharma/Desktop/Grow/migration_chunks/chunk_XXX.sql")
print("  2. Copy all content")
print("  3. Paste in Supabase SQL Editor")
print("  4. Click RUN")
print("  5. Move to next chunk")
print()
print(f"📁 Location: {OUTPUT_DIR}")
