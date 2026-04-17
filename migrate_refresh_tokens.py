#!/usr/bin/env python3
"""
Migration: Add refresh tokens table for OAuth session management
Run once to add refresh_tokens table to Supabase
"""

import os
from sqlalchemy import create_engine, text

DB_URL = os.getenv('DATABASE_URL')
if not DB_URL:
    print("ERROR: DATABASE_URL not set")
    exit(1)

engine = create_engine(DB_URL)

def create_refresh_tokens_table():
    """Create refresh_tokens table for storing OAuth refresh tokens"""
    with engine.connect() as conn:
        # Create refresh_tokens table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash VARCHAR(255) NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                revoked BOOLEAN DEFAULT FALSE,
                revoked_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                
                INDEX idx_user_id (user_id),
                INDEX idx_revoked (revoked),
                INDEX idx_expires_at (expires_at)
            )
        """))
        
        # Add email_verified column to users table if not exists
        try:
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT TRUE
            """))
            print("✓ Added email_verified column to users table")
        except Exception as e:
            if 'already exists' in str(e):
                print("✓ email_verified column already exists")
            else:
                raise
        
        conn.commit()
        print("✓ refresh_tokens table created successfully")

if __name__ == '__main__':
    try:
        create_refresh_tokens_table()
        print("\n✅ Migration complete")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
