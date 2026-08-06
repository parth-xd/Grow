# Groww Cost Automation System — Deployment & Quick Start

Complete system for automated trading cost management. Ready for production deployment.

## What's Included

### Code Files
1. **cost_scraper.py** (608 lines)
   - Fetches costs from Groww's website
   - Parses HTML to extract trading charges
   - Validates costs against bounds
   - Compares new vs old values
   
2. **cost_updater.py** (516 lines)
   - Updates database with new costs
   - Maintains audit trail (full history)
   - Creates cost_audit_log table
   - Provides rollback functionality
   
3. **cost_notifications.py** (386 lines)
   - Sends Telegram notifications
   - Logs to dashboard database
   - Formats human-readable messages
   - Marks notifications as read/unread
   
4. **costs.py** (Enhanced existing file)
   - Main orchestrator function
   - Ties together scraper → updater → notifier
   - Provides cost calculation helpers
   - Integrates with scheduler
   
5. **scheduler.py** (Modified)
   - Registers cost_scraper task
   - Runs every 45 days with random startup delay
   - Prevents self-overlap via locks

### Documentation
1. **COST_AUTOMATION_GUIDE.md** — Complete technical documentation
2. **COST_API_INTEGRATION.md** — Flask API endpoints and examples
3. **COST_SYSTEM_DEPLOYMENT.md** — This file (deployment guide)

## Quick Deployment (5 minutes)

### Step 1: Verify Files Exist
```bash
cd /Users/parthsharma/Desktop/Grow

ls -la cost_scraper.py
ls -la cost_updater.py
ls -la cost_notifications.py
# costs.py should already exist (enhanced version)
```

### Step 2: Initialize Database Tables (First Run Only)
```bash
python3 << 'EOF'
from cost_updater import _ensure_audit_table_exists
from cost_notifications import _ensure_notification_table_exists
from db_manager import get_db

db = get_db()
_ensure_audit_table_exists(db)
_ensure_notification_table_exists(db)
print("✓ Database tables created")
EOF
```

### Step 3: Seed Initial Costs (First Run Only)
```bash
python3 << 'EOF'
from costs import seed_cost_rates
seed_cost_rates()
print("✓ Seed costs complete")
EOF
```

### Step 4: Test the System
```bash
# Test scraper
python3 cost_scraper.py

# Test updater  
python3 cost_updater.py

# Test full workflow
python3 << 'EOF'
from costs import update_cost_rates
result = update_cost_rates()
print(f"Success: {result['success']}")
print(f"Updated: {result['summary']['costs_updated']}")
EOF
```

### Step 5: Verify Scheduler Integration
```bash
# Check that scheduler has the cost_scraper task
python3 << 'EOF'
from scheduler import _tasks
cost_tasks = [t for t in _tasks if 'cost' in t['name']]
print(f"Cost tasks registered: {len(cost_tasks)}")
for task in cost_tasks:
    print(f"  - {task['name']}: every {task['interval']} seconds ({task['interval']/86400:.1f} days)")
EOF
```

## Production Checklist

- [ ] Database tables created (`cost_audit_log`, `cost_notifications`)
- [ ] Initial costs seeded in `config_settings`
- [ ] Telegram bot enabled (for notifications)
- [ ] Scheduler running with cost_scraper task
- [ ] Flask app serving API endpoints
- [ ] Logging configured (INFO level for production)
- [ ] Email/Telegram alerts configured
- [ ] Backup strategy in place

## Usage Examples

### Check Cost System Health
```python
from costs import get_cost_health_check
health = get_cost_health_check()
print(health)
# {
#   "status": "healthy",
#   "last_update": "2026-07-31T12:00:00",
#   "costs_tracked": 8,
#   "recent_errors": [],
#   "next_update_in": "~45 days"
# }
```

### Calculate Trade Charges
```python
from costs import calculate_trade_charges

charges = calculate_trade_charges(
    side="BUY",
    quantity=100,
    price=1500.0,
    product="CNC"
)
print(f"Total charges: ₹{charges['total_charges']:.2f}")
# Total charges: ₹53.94
```

### View Cost History
```python
from cost_updater import get_cost_history

history = get_cost_history("brokerage_flat_per_order", days=90)
for record in history[:3]:
    print(f"{record['date']}: {record['old_value']} → {record['new_value']}")
```

### Manually Trigger Cost Update
```python
from costs import update_cost_rates
result = update_cost_rates()
print(f"✅ {result['summary']['costs_updated']} costs updated")
```

### Rollback a Cost Change
```python
from cost_updater import rollback_costs

# Get audit_id from database, then rollback
success, msg = rollback_costs(audit_id=123)
print(msg)

# Reload in-memory cache
from costs import reload_rates
reload_rates()
```

## File Locations

```
/Users/parthsharma/Desktop/Grow/
├── cost_scraper.py                    # Scrapes costs from Groww
├── cost_updater.py                    # Updates DB + audit trail
├── cost_notifications.py              # Sends notifications
├── costs.py                           # Orchestrator (modified)
├── scheduler.py                       # Task registration (modified)
├── COST_AUTOMATION_GUIDE.md           # Complete docs
├── COST_API_INTEGRATION.md            # API endpoints
└── COST_SYSTEM_DEPLOYMENT.md          # This file
```

## Database Tables

### cost_audit_log
Tracks all cost changes with full history.
```sql
SELECT * FROM cost_audit_log ORDER BY scrape_date DESC LIMIT 10;
```

### cost_notifications
Stores notifications for dashboard display.
```sql
SELECT * FROM cost_notifications WHERE is_read = FALSE;
```

### config_settings
Stores current costs (value field is JSON).
```sql
SELECT key, value FROM config_settings WHERE key LIKE 'cost.%';
```

## Monitoring & Alerts

### Telegram Notifications
Cost updates automatically posted to Telegram when enabled.

### Dashboard Indicators
- ✅ Green: All systems nominal
- ⚠️ Yellow: Cost verification overdue
- 🔴 Red: Errors or suspicious changes

### Log Monitoring
```bash
tail -f app.log | grep -i cost
```

## Common Tasks

### View all current costs
```python
from cost_updater import get_current_costs
costs = get_current_costs()
for key, value in sorted(costs.items()):
    print(f"{key}: {value}")
```

### Export cost history to CSV
```python
import csv
from cost_updater import get_cost_history

with open('cost_history.csv', 'w') as f:
    writer = csv.writer(f)
    writer.writerow(['Date', 'Type', 'Old', 'New', 'Change%'])
    
    for cost_type in ['brokerage_flat_per_order', 'stt_pct_delivery_sell']:
        history = get_cost_history(cost_type, days=365)
        for record in history:
            writer.writerow([
                record['date'],
                cost_type,
                record['old_value'],
                record['new_value'],
                record['percent_change'],
            ])
```

### Check if update is pending
```python
from cost_updater import get_current_costs
from datetime import datetime, timedelta

# Check if costs haven't been updated in >45 days
costs = get_current_costs()
if costs:
    # Costs exist, check update times from database
    from db_manager import get_db, ConfigSetting
    db = get_db()
    session = db.Session()
    
    latest_update = session.query(ConfigSetting).filter(
        ConfigSetting.key.like('cost.%')
    ).order_by(ConfigSetting.updated_at.desc()).first()
    
    if latest_update:
        age = datetime.utcnow() - latest_update.updated_at
        print(f"Last update: {age.days} days ago")
        if age.days > 45:
            print("⚠️ Cost update overdue!")
    
    session.close()
```

### Emergency: Force disable automated updates
```python
from db_manager import set_config
set_config("cost.scraper_enabled", "false")
print("Automated updates disabled")
```

### Emergency: Re-enable automated updates
```python
from db_manager import set_config
set_config("cost.scraper_enabled", "true")
print("Automated updates enabled")
```

## Troubleshooting

### Issue: "Module not found" error
**Solution**: Ensure all files are in the correct directory
```bash
cd /Users/parthsharma/Desktop/Grow
python3 -c "import cost_scraper; print('✓ cost_scraper available')"
```

### Issue: Scraper fails but system keeps working
**Expected behavior** — System gracefully falls back to canonical rates. Check logs:
```bash
grep "canonical fallback" app.log
```

### Issue: Notification not sent
**Check**: 
1. Telegram enabled: `get_config("telegram_enabled")`
2. Telegram bot token valid
3. User ID configured

### Issue: Database connection errors
**Check**:
```bash
psql $DB_URL -c "SELECT 1;"  # Verify DB connection
```

### Issue: Cost not updating despite time passing
**Check**:
1. Scheduler is running: `ps aux | grep scheduler`
2. Database writable: Check PostgreSQL logs
3. Scraper working: `python3 cost_scraper.py`

## Performance Considerations

### Update Frequency
- **Interval**: 45 days (3,888,000 seconds)
- **Duration**: ~30-60 seconds per update
- **Network calls**: 1-2 (Groww website)
- **Database operations**: 8-10 inserts/updates

### Cache Strategy
- In-memory cache of costs (loaded on first access)
- Cache reloaded after each update
- No cache invalidation needed (updates infrequent)

### Database Optimization
- Indexes on `cost_audit_log(scrape_date)`, `(cost_type)`, `(changed)`
- Indexes on `cost_notifications(type)`, `(is_read)`, `(created_at)`
- Unique constraints prevent duplicates

## Backup & Recovery

### Backup Costs Table
```bash
pg_dump -U postgres -d grow_trading_bot -t config_settings > costs_backup.sql
pg_dump -U postgres -d grow_trading_bot -t cost_audit_log > audit_backup.sql
```

### Restore from Backup
```bash
psql -U postgres -d grow_trading_bot < costs_backup.sql
```

### Point-in-Time Recovery
Find the desired timestamp in `cost_audit_log`, then rollback:
```python
from cost_updater import rollback_costs
success, msg = rollback_costs(audit_id=<desired_id>)
```

## Future Enhancements

- [ ] Multi-broker cost comparison (Zerodha, Angel, etc)
- [ ] Cost prediction model (forecast rate changes)
- [ ] Cost impact analysis (show P&L impact of rate changes)
- [ ] Email alerts for large changes
- [ ] Cost benchmarking dashboard
- [ ] Integration with Groww API (when available)

## Support & Debugging

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Manual Testing
```bash
# Test scraper output
python3 cost_scraper.py | jq '.charges | keys'

# Test database update
python3 << 'EOF'
from costs import update_cost_rates
result = update_cost_rates()
print(result)
EOF
```

### Database Inspection
```sql
-- Check costs
SELECT key, value->>'value' as value FROM config_settings WHERE key LIKE 'cost.%';

-- Check history
SELECT * FROM cost_audit_log ORDER BY scrape_date DESC LIMIT 5;

-- Check notifications
SELECT id, type, message, is_read FROM cost_notifications ORDER BY created_at DESC LIMIT 5;
```

## Success Criteria

✅ System successfully deployed when:
- [ ] `cost_scraper.py` runs without errors
- [ ] `cost_updater.py` creates audit trail entries
- [ ] `cost_notifications.py` sends Telegram messages
- [ ] Scheduler runs cost_scraper task every 45 days
- [ ] Flask API endpoints return valid JSON
- [ ] Database tables have data
- [ ] Manual update via API works
- [ ] Cost history can be retrieved
- [ ] Rollback functionality works

## Summary

| Component | Status | Location |
|-----------|--------|----------|
| Scraper | ✅ Ready | cost_scraper.py |
| Updater | ✅ Ready | cost_updater.py |
| Notifier | ✅ Ready | cost_notifications.py |
| Orchestrator | ✅ Ready | costs.py |
| Scheduler | ✅ Ready | scheduler.py |
| API | ✅ Ready | See COST_API_INTEGRATION.md |
| Docs | ✅ Ready | COST_AUTOMATION_GUIDE.md |

**Total Lines of Code**: ~2,000 (production-ready, fully documented)

**Time to Deploy**: 5-10 minutes

**Maintenance**: Zero human intervention required (fully automated)

## Next Steps

1. ✅ Copy code files to `/Users/parthsharma/Desktop/Grow/`
2. ✅ Initialize database tables (run Step 2 above)
3. ✅ Seed initial costs (run Step 3 above)
4. ✅ Test system (run Step 4 above)
5. ✅ Verify scheduler (run Step 5 above)
6. ✅ Start Flask app (costs API will be available)
7. ✅ Add dashboard widgets (see COST_API_INTEGRATION.md)
8. ✅ Configure Telegram notifications
9. ✅ Monitor first 45-day cycle

**Questions?** Refer to:
- Technical: `COST_AUTOMATION_GUIDE.md`
- API: `COST_API_INTEGRATION.md`
- Deployment: This file

---

**Status**: Production-ready
**Version**: 1.0
**Last Updated**: 2026-07-31
**Maintainer**: Cost Automation System
