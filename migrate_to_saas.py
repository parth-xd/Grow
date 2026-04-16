#!/usr/bin/env python3
"""
Migration script: Convert single-user app to multi-user SaaS

This script:
1. Creates new user management tables
2. Adds user_id to all existing tables
3. Migrates current data to admin user
4. Creates encryption key for API credentials
"""

import os
import uuid
from sqlalchemy import create_engine, text
from cryptography.fernet import Fernet

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://grow:grow@localhost:5432/grow')
engine = create_engine(DATABASE_URL)

def run_migration():
    """Execute all migration steps"""
    print("\n" + "="*80)
    print("MIGRATING TO SAAS - MULTI-USER ARCHITECTURE")
    print("="*80)
    
    with engine.connect() as conn:
        with conn.begin():
            # Step 1: Create user management tables
            print("\n✓ Step 1: Creating user management tables...")
            create_user_tables(conn)
            
            # Step 2: Create encryption key (stored in .env)
            print("✓ Step 2: Setting up encryption...")
            create_encryption_key()
            
            # Step 3: Add user_id to existing tables
            print("✓ Step 3: Adding user_id to existing tables...")
            add_user_id_columns(conn)
            
            # Step 4: Create admin user
            print("✓ Step 4: Creating admin user...")
            admin_user_id = create_admin_user(conn)
            
            # Step 5: Migrate existing data to admin user
            print("✓ Step 5: Migrating existing data to admin user...")
            migrate_data_to_admin(conn, admin_user_id)
            
            conn.commit()
    
    print("\n" + "="*80)
    print("✅ MIGRATION COMPLETE!")
    print("="*80)
    print("\nNext steps:")
    print("1. Update your .env with ENCRYPTION_KEY, JWT_SECRET, GOOGLE_CLIENT_ID/SECRET")
    print("2. Deploy new backend with user authentication")
    print("3. Create frontend with Google OAuth")
    print("4. Test with admin account (email: admin@grow.app)")
    print("\n")

def create_user_tables(conn):
    """Create new user management tables"""
    
    # users table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email VARCHAR(255) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL,
            google_id VARCHAR(255) UNIQUE,
            profile_picture_url TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            
            INDEX idx_email (email),
            INDEX idx_google_id (google_id),
            INDEX idx_active (is_active)
        )
    """))
    
    # api_credentials table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS api_credentials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            encrypted_groww_api_key TEXT NOT NULL,
            encrypted_groww_secret TEXT NOT NULL,
            is_live_trading BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE(user_id),
            INDEX idx_user_id (user_id)
        )
    """))
    
    # user_settings table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            paper_trading_enabled BOOLEAN DEFAULT TRUE,
            real_trading_enabled BOOLEAN DEFAULT FALSE,
            max_risk_per_trade FLOAT DEFAULT 2.0,
            backtesting_enabled BOOLEAN DEFAULT TRUE,
            notifications_enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            INDEX idx_user_id (user_id)
        )
    """))
    
    # admin_logs table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_id UUID NOT NULL REFERENCES users(id),
            action_type VARCHAR(50),
            action_description TEXT,
            affected_user_id UUID REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            INDEX idx_created (created_at),
            INDEX idx_admin (admin_id),
            INDEX idx_affected_user (affected_user_id)
        )
    """))
    
    print("  ✓ users table")
    print("  ✓ api_credentials table")
    print("  ✓ user_settings table")
    print("  ✓ admin_logs table")

def add_user_id_columns(conn):
    """Add user_id column to existing tables"""
    
    # List of tables that need user_id
    tables_to_update = [
        'trade_journal',
        'trade_log',
        'trade_snapshots',
        'pnl_snapshots',
        'paper_trades',
        'stock_theses',
        'watchlist_notes',
    ]
    
    for table in tables_to_update:
        try:
            # Check if column already exists
            result = conn.execute(text(f"""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = 'user_id'
            """))
            
            if result.fetchone():
                print(f"  ✓ {table} - user_id already exists")
                continue
            
            # Add user_id column (nullable for now, will be populated)
            conn.execute(text(f"""
                ALTER TABLE {table} 
                ADD COLUMN user_id UUID
            """))
            
            # Add foreign key constraint
            conn.execute(text(f"""
                ALTER TABLE {table}
                ADD CONSTRAINT fk_{table}_user_id 
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            """))
            
            # Create index for performance
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)
            """))
            
            print(f"  ✓ {table} - added user_id column")
            
        except Exception as e:
            print(f"  ⚠️  {table} - {str(e)}")

def create_encryption_key():
    """Create and save encryption key for API credentials"""
    
    encryption_key = Fernet.generate_key().decode()
    
    # Add to .env file
    env_path = '/Users/parthsharma/Desktop/Grow/.env'
    
    try:
        # Read existing .env
        try:
            with open(env_path, 'r') as f:
                env_content = f.read()
        except FileNotFoundError:
            env_content = ""
        
        # Add encryption key if not present
        if 'ENCRYPTION_KEY=' not in env_content:
            if env_content and not env_content.endswith('\n'):
                env_content += '\n'
            env_content += f'ENCRYPTION_KEY={encryption_key}\n'
            
            with open(env_path, 'w') as f:
                f.write(env_content)
        
        print(f"  ✓ Encryption key generated and saved to .env")
    except Exception as e:
        print(f"  ⚠️  Could not save encryption key: {e}")
        print(f"     Please manually add to .env: ENCRYPTION_KEY={encryption_key}")

def create_admin_user(conn):
    """Create admin user account"""
    
    admin_id = str(uuid.uuid4())
    
    conn.execute(text("""
        INSERT INTO users (id, email, name, is_admin, is_active)
        VALUES (:id, :email, :name, :is_admin, :is_active)
        ON CONFLICT (email) DO NOTHING
    """), {
        'id': admin_id,
        'email': 'admin@grow.app',
        'name': 'Admin User',
        'is_admin': True,
        'is_active': True
    })
    
    # Get the actual admin user ID (in case it already existed)
    result = conn.execute(text("""
        SELECT id FROM users WHERE email = 'admin@grow.app'
    """))
    admin_user_id = result.scalar()
    
    # Create settings for admin
    conn.execute(text("""
        INSERT INTO user_settings (user_id, paper_trading_enabled, real_trading_enabled)
        VALUES (:user_id, :paper_enabled, :real_enabled)
        ON CONFLICT (user_id) DO NOTHING
    """), {
        'user_id': admin_user_id,
        'paper_enabled': True,
        'real_enabled': False
    })
    
    print(f"  ✓ Admin user created: admin@grow.app")
    print(f"  ✓ Admin ID: {admin_user_id}")
    
    return admin_user_id

def migrate_data_to_admin(conn, admin_user_id):
    """Migrate existing data to admin user"""
    
    tables_to_migrate = [
        'trade_journal',
        'trade_log',
        'trade_snapshots',
        'pnl_snapshots',
        'paper_trades',
        'stock_theses',
        'watchlist_notes',
    ]
    
    for table in tables_to_migrate:
        try:
            # Count existing records
            result = conn.execute(text(f"""
                SELECT COUNT(*) FROM {table} WHERE user_id IS NULL
            """))
            count = result.scalar()
            
            if count > 0:
                # Update all NULL user_id to admin user
                conn.execute(text(f"""
                    UPDATE {table} SET user_id = :admin_id WHERE user_id IS NULL
                """), {'admin_id': admin_user_id})
                
                print(f"  ✓ {table} - migrated {count} records to admin")
            else:
                print(f"  ✓ {table} - no records to migrate")
                
        except Exception as e:
            print(f"  ⚠️  {table} - {str(e)}")

if __name__ == '__main__':
    try:
        run_migration()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
