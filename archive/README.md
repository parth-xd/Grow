# Archive Organization

This folder contains files that have been archived from the main codebase.

## Folders

### `/dead_code`
**Purpose:** Test and debug utilities that are no longer used in production

**Contents:** 17 files
- Debug/test scripts for validating candles, prices, tokens, etc.
- Never imported by production code
- Safe to delete permanently if needed

**Files:**
- `_check_coverage.py` - Candle coverage validation
- `_check_intervals.py` - Interval checking
- `_check_today.py` - Today's data validation
- `_test_bt_api.py` - Backtesting API test
- `check_db.py` - Database connectivity test
- `check_db_dates.py` - Date range validation
- `check_db_status.py` - Database status check
- `check_missing_candles.py` - Missing candle detection
- `check_candles_simple.py` - Simple candle validation
- `check_data_recency.py` - Data freshness check
- `check_prices.py` - Price data validation
- `check_token.py` - Token validation
- `debug_confidence.py` - Confidence debugging
- `test_5min_api.py` - 5-minute API test
- `test_daily_candles.py` - Daily candle test
- `test_symbol_availability.py` - Symbol availability test
- `test_today_data.py` - Today's data test

### `/migration_scripts`
**Purpose:** One-time setup and data migration scripts

**Contents:** 5 files
- Scripts that were run during initial setup
- Database schema changes and data loading
- Safe to keep for reference, rarely needed again

**Files:**
- `migrate_schema.py` - Added columns to trade_journal table
- `migrate_trades_to_db.py` - Loaded JSON trades into PostgreSQL
- `import_nse_stocks.py` - Initial stock universe import
- `backfill_candles.py` - Historical candle data loading
- `aggregate_to_daily.py` - Daily candle aggregation

## Usage

### Dead Code
- These files are for reference only
- **Safe to delete permanently** - nothing depends on them
- If needed in future: `cp archive/dead_code/<file> .` to restore

### Migration Scripts
- **Keep for reference** - useful to understand setup process
- Run only during initial setup, not needed in production
- If needed to re-run: `cp archive/migration_scripts/<file> .` to restore

## Archival Date
- **Date:** 16 April 2026
- **Reason:** Code cleanup and organization
- **Risk Level:** ZERO - no production code depends on these files

## Notes

All files have been moved to archive to keep the main codebase clean:
- **Reduced clutter** - main folder is now cleaner
- **Preserved history** - files still accessible if needed
- **Better organization** - dead code separated from migration scripts
- **Git history** - all changes tracked in version control

See `AUDIT_SUMMARY.md` in the main folder for complete audit details.
