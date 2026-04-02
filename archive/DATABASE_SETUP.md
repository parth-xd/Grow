# PostgreSQL Database Setup Guide

## 1. Install PostgreSQL

### macOS (using Homebrew)
```bash
brew install postgresql@15
brew services start postgresql@15
```

### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
```

### Windows
Download and install from: https://www.postgresql.org/download/windows/

---

## 2. Create Database & User

Open PostgreSQL:
```bash
psql -U postgres
```

Run these commands:
```sql
-- Create user
CREATE ROLE groww_user WITH LOGIN PASSWORD 'your_secure_password_here';

-- Create database
CREATE DATABASE groww_trading OWNER groww_user;

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE groww_trading TO groww_user;

-- Connect and set permissions on schema
\c groww_trading
GRANT ALL PRIVILEGES ON SCHEMA public TO groww_user;

-- Exit
\q
```

---

## 3. Update .env File

Add these lines to your `./Grow/.env`:

```env
# PostgreSQL Configuration
DB_USER=groww_user
DB_PASSWORD=your_secure_password_here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=groww_trading
```

**Replace `your_secure_password_here` with the password you set above.**

---

## 4. Install Python Packages

```bash
cd /Users/parthsharma/Desktop/Grow
pip install -r requirements.txt
```

This installs:
- `psycopg2-binary` — PostgreSQL adapter for Python
- `sqlalchemy` — ORM for database operations
- `alembic` — Database migrations (optional, for future schema versions)

---

## 5. Test Connection

Run this in Python to verify DB connection:

```python
from db_manager import get_db
from config import DB_URL

db = get_db(DB_URL)
print("✓ Database connected!")
print(db.get_stats())
```

---

## 6. How It Works

### Before (Old Way)
```
API Request → Fetch 30 days of data (720 candles) → Train ML Model → Cache in memory
```
**Problems**: Slow API calls, redundant fetches, no persistence

### After (New Way)
```
First Run:  API → Database → Train ML Model
Subsequent: Database → Train ML Model → Incremental Sync at end of day
```
**Benefits**:
- ✅ Database persists historical data permanently
- ✅ Only fetches NEW candles since last sync (incremental)
- ✅ Fast local DB queries instead of slow API calls
- ✅ Multiple instances can share the same database
- ✅ Historical data grows automatically each day

---

## 7. Key Files Modified

| File | Changes |
|------|---------|
| `db_manager.py` | NEW — Database manager with ORM |
| `config.py` | Added `DB_*` settings from .env |
| `bot.py` | Modified `fetch_historical()` to use DB + `sync_candles_from_api()` |
| `requirements.txt` | Added `psycopg2-binary`, `sqlalchemy`, `alembic` |

---

## 8. Database Schema

The system creates one table automatically:

```sql
CREATE TABLE candles (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp DATETIME NOT NULL,
    open FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    close FLOAT NOT NULL,
    volume FLOAT NOT NULL,
    created_at DATETIME DEFAULT NOW(),
    updated_at DATETIME DEFAULT NOW(),
    UNIQUE KEY (symbol, timestamp)
);

CREATE INDEX idx_symbol_timestamp ON candles(symbol, timestamp);
```

---

## 9. Monitoring Database

Check how much data is stored:

```bash
psql -U groww_user -d groww_trading -c "SELECT symbol, COUNT(*) as candle_count, MIN(timestamp) as earliest, MAX(timestamp) as latest FROM candles GROUP BY symbol ORDER BY symbol;"
```

---

## 10. Troubleshooting

### "connection refused"
```bash
# Check if PostgreSQL is running
brew services list  # macOS

# Restart if needed
brew services restart postgresql@15
```

### "FATAL: Ident authentication failed"
Edit `/usr/local/var/postgres/pg_hba.conf` and change `ident` to `md5` for localhost

### "ERROR: permission denied for schema public"
```sql
-- Run as postgres superuser:
GRANT ALL PRIVILEGES ON SCHEMA public TO groww_user;
```

### "psycopg2.OperationalError: server closed the connection unexpectedly"
The database might have restarted. Just restart the Flask server:
```bash
kill -9 $(lsof -t -i:8000)
python3 app.py
```

---

## 11. Optional: Remote Database

If you want to use a cloud PostgreSQL (e.g., AWS RDS, Supabase):

```env
DB_USER=postgres_user
DB_PASSWORD=your_cloud_password
DB_HOST=your-db-instance.c9akciq32.us-east-1.rds.amazonaws.com
DB_PORT=5432
DB_NAME=groww_trading
```

The code works the same way!

---

**That's it! Your app now has persistent incremental data storage. 🚀**
