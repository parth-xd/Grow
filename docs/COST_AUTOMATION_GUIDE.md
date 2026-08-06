# Automated Cost/Charge Update System

Complete automated system for maintaining up-to-date trading costs from Groww.

## Overview

The cost automation system monitors Groww's trading charges and automatically updates the database when rates change. It includes:

- **Automated scraping** every 45 days
- **Validation & comparison** with existing rates
- **Suspicious change detection** (>10% changes flagged for manual review)
- **Audit trail** with full history
- **Notifications** via Telegram & dashboard
- **Graceful degradation** (system works even if scrape fails)
- **Rollback capability** to restore previous rates

## Components

### 1. `cost_scraper.py` — Scrapes trading costs
- Fetches rates from Groww's official charges page
- Parses HTML to extract charges
- Falls back to canonical rates if scraping fails
- Compares new vs old costs
- Validates costs against bounds

**Key Functions:**
```python
scrape()                    # Main function, returns scrape_result
_parse_groww_charges_page() # Parses HTML
compare_costs()             # Compares old vs new
validate_costs()            # Checks against min/max bounds
```

**Example output:**
```python
{
    "success": True,
    "timestamp": "2026-07-31T12:00:00",
    "charges": {
        "brokerage_flat_per_order": 20.0,
        "stt_pct_delivery_sell": 0.1,
        "exchange_charge_nse_pct": 0.00325,
        ...
    },
    "comparison": {
        "changed": True,
        "changes": [
            {
                "key": "brokerage_flat_per_order",
                "old_value": 20.0,
                "new_value": 21.0,
                "change_pct": 5.0,
                "suspicious": False,
            }
        ]
    }
}
```

### 2. `cost_updater.py` — Updates database with audit trail
- Updates config_settings table with new costs
- Stores costs as JSON with metadata
- Creates audit trail in cost_audit_log table
- Prevents self-overlapping updates via transaction safety
- Flags suspicious changes (>10%)

**Key Functions:**
```python
update_cost_in_db()         # Update single cost + audit
update_costs()              # Batch update with transaction safety
get_cost_history()          # Retrieve historical values
rollback_costs()            # Restore from audit log
get_current_costs()         # Get all active costs
```

**Database storage format:**
```json
{
    "value": 20.0,
    "data_type": "float",
    "unit": "₹",
    "min_value": 0.0,
    "max_value": 100.0,
    "category": "brokerage",
    "source_url": "https://groww.in/charges",
    "last_verified_date": "2026-07-31T12:00:00"
}
```

### 3. `cost_notifications.py` — Alerts on changes
- Sends notifications via Telegram
- Logs to dashboard database
- Formats human-readable messages
- Marks as read / unread for dashboard

**Example notification:**
```
🔔 Trading Cost Update
Updated: 2026-07-31 12:00:00 UTC

Updated: 2 costs

Changes:
📈 brokerage_flat_per_order: ₹20.00 → ₹21.00 (+5.0%)
📉 stt_pct_intraday: 0.0250% → 0.0245% (-2.0%)

Source: https://groww.in/charges
```

### 4. `costs.py` — Main orchestrator
- Provides `update_cost_rates()` called by scheduler
- Orchestrates scrape → validate → update → notify
- Provides helper functions for cost calculations
- Maintains in-memory cache for performance

**Key Functions:**
```python
update_cost_rates()         # Main orchestrator (called every 45 days)
calculate_costs()           # Calculate charges for a trade
min_profitable_move()       # Breakeven analysis
net_profit()                # P&L calculation
```

## Database Schema

### Table: `config_settings` (extended)
```sql
ALTER TABLE config_settings ADD COLUMN source_url VARCHAR(500);
ALTER TABLE config_settings ADD COLUMN last_verified_date TIMESTAMP;
ALTER TABLE config_settings ADD COLUMN verification_frequency_days INT;
ALTER TABLE config_settings ADD COLUMN change_log TEXT;  -- JSON array of historical changes
```

### Table: `cost_audit_log` (new)
```sql
CREATE TABLE cost_audit_log (
    id SERIAL PRIMARY KEY,
    scrape_date TIMESTAMP NOT NULL DEFAULT NOW(),
    cost_type VARCHAR(100) NOT NULL,              -- "brokerage", "stt", etc
    old_value FLOAT,
    new_value FLOAT,
    changed BOOLEAN DEFAULT FALSE,
    percent_change FLOAT,
    source_url VARCHAR(500),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT cost_audit_unique UNIQUE (scrape_date, cost_type)
);

CREATE INDEX idx_cost_audit_date ON cost_audit_log (scrape_date);
CREATE INDEX idx_cost_audit_type ON cost_audit_log (cost_type);
CREATE INDEX idx_cost_audit_changed ON cost_audit_log (changed);
```

### Table: `cost_notifications` (new)
```sql
CREATE TABLE cost_notifications (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50) NOT NULL,                    -- "cost_update", "warning"
    message VARCHAR(1000) NOT NULL,
    data TEXT,                                    -- JSON with full details
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT cost_notif_unique UNIQUE (type, created_at)
);

CREATE INDEX idx_cost_notif_type ON cost_notifications (type);
CREATE INDEX idx_cost_notif_read ON cost_notifications (is_read);
CREATE INDEX idx_cost_notif_date ON cost_notifications (created_at DESC);
```

### Key Storage Format (config_settings)
```
key: "cost.brokerage_flat_per_order"
value: {
    "value": 20.0,
    "data_type": "float",
    "unit": "₹",
    "min_value": 0.0,
    "max_value": 100.0,
    "category": "brokerage",
    "source_url": "https://groww.in/charges",
    "last_verified_date": "2026-07-31T12:00:00"
}
description: "Flat brokerage per order (delivery CNC) [Updated from https://groww.in/charges]"
updated_by: "cost_updater"
```

## Scheduler Integration

### Registration
```python
# In scheduler.py start_scheduler()
import random
cost_scraper_delay = random.randint(0, 170)
_register("cost_scraper", _task_cost_rate_update, 3888000, initial_delay=cost_scraper_delay)
```

**Settings:**
- **Interval**: 3,888,000 seconds = 45 days
- **Initial delay**: Random 0-170 seconds (staggered startup to avoid API storms)
- **Task**: `_task_cost_rate_update()` in scheduler.py
- **On error**: Logs error, keeps using old values
- **On retry**: Automatic retry in 7 days if initial attempt fails

### Execution Flow
```
Scheduler checks every 15 seconds
↓
45 days elapsed since last run?
↓ YES
Submit to thread pool (_task_cost_rate_update)
↓
costs.update_cost_rates()
  ├─ cost_scraper.scrape()
  │  ├─ Fetch from Groww
  │  ├─ Parse HTML
  │  ├─ Validate costs
  │  └─ Compare with DB
  ├─ cost_updater.update_costs()
  │  ├─ Update config_settings
  │  ├─ Log audit trail
  │  └─ Handle errors
  ├─ cost_notifications.send_cost_change_notification()
  │  ├─ Send Telegram
  │  └─ Log to dashboard
  └─ costs.reload_rates()
     └─ Refresh in-memory cache
```

## Cost Categories & Metadata

All costs have metadata defining:
- **description**: Human-readable explanation
- **unit**: "₹" for absolute, "%" for percentage
- **data_type**: "float" or "int"
- **min_value**: Validation lower bound
- **max_value**: Validation upper bound
- **category**: "brokerage", "stt", "exchange_charge", "sebi_fee", "dp_charge", "gst_rate", "stamp_duty"

### Tracked Costs
| Key | Unit | Min | Max | Category |
|-----|------|-----|-----|----------|
| `brokerage_flat_per_order` | ₹ | 0.0 | 100.0 | brokerage |
| `brokerage_intraday_per_order` | ₹ | 0.0 | 100.0 | brokerage |
| `stt_pct_delivery_sell` | % | 0.0 | 0.5 | stt |
| `stt_pct_intraday` | % | 0.0 | 0.5 | stt |
| `exchange_charge_nse_pct` | % | 0.0 | 0.01 | exchange_charge |
| `sebi_fee_pct` | % | 0.0 | 0.0001 | sebi_fee |
| `gst_rate` | % | 0.0 | 0.3 | gst_rate |
| `stamp_duty_pct` | % | 0.0 | 0.05 | stamp_duty |

## Error Handling & Validation

### Validation Checks
1. **Bounds checking**: Each cost must be within [min_value, max_value]
2. **Suspicious change detection**: Changes >10% are flagged for manual review
3. **Network resilience**: If scrape fails, falls back to canonical rates
4. **Transaction safety**: All-or-nothing database updates

### Error Recovery
```python
If scrape fails:
  ├─ Use canonical Groww rates as fallback
  ├─ Log error with timestamp
  └─ Retry in 7 days

If database update fails:
  ├─ Rollback transaction
  ├─ Log error
  └─ Keep using old values (no corruption)

If notification fails:
  ├─ Log warning
  └─ System continues normally (data already updated)
```

## Manual Verification & Rollback

### Check Current Costs
```python
from cost_updater import get_current_costs, COST_METADATA
from db_manager import get_db

costs = get_current_costs()
for key, value in costs.items():
    metadata = COST_METADATA.get(key, {})
    print(f"{key}: {value} {metadata.get('unit', '')}")
```

### View History
```python
from cost_updater import get_cost_history

# Get last 90 days of changes for a specific cost
history = get_cost_history("brokerage_flat_per_order", days=90)
for record in history:
    print(f"{record['date']}: {record['old_value']} → {record['new_value']}")
```

### Rollback to Previous Value
```python
from cost_updater import rollback_costs

# Get audit_id from cost_audit_log, then rollback
success, message = rollback_costs(audit_id=123)
print(message)

# After rollback, reload cache
from costs import reload_rates
reload_rates()
```

### Health Check
```python
from costs import get_cost_health_check

health = get_cost_health_check()
print(health)
# {
#     "status": "healthy|warning|error",
#     "last_update": "2026-07-31T12:00:00",
#     "costs_tracked": 8,
#     "recent_errors": [],
#     "next_update_in": "~45 days"
# }
```

## API Endpoints (for Dashboard)

### Get Current Cost Configuration
```
GET /api/costs/config
Response:
{
    "updated_at": "2026-07-31T12:00:00",
    "source": "Groww",
    "costs": {
        "brokerage": {
            "name": "Brokerage",
            "items": [...]
        }
    },
    "total_tracked": 8
}
```

### Calculate Trade Charges
```
POST /api/costs/calculate
Body:
{
    "side": "BUY",
    "quantity": 10,
    "price": 2500.0,
    "product": "CNC",
    "segment": "CASH"
}
Response:
{
    "turnover": 25000.0,
    "brokerage": 20.0,
    "stt": 0.0,
    "exchange_charge": 8.13,
    "sebi_fee": 0.08,
    "dp_charge": 0.0,
    "gst": 5.04,
    "total_charges": 33.24,
    "net_value": 25033.24
}
```

### Get Cost History
```
GET /api/costs/history?cost_type=brokerage_flat_per_order&days=90
Response:
[
    {
        "date": "2026-07-31T12:00:00",
        "cost_type": "brokerage_flat_per_order",
        "old_value": 20.0,
        "new_value": 21.0,
        "percent_change": 5.0,
        "source_url": "https://groww.in/charges",
        "notes": "Updated via cost_scraper automation"
    }
]
```

### Get Unread Notifications
```
GET /api/notifications/cost-updates?limit=10
Response:
[
    {
        "id": 1,
        "type": "cost_update",
        "message": "2 trading costs updated",
        "data": {...},
        "created_at": "2026-07-31T12:00:00"
    }
]
```

### Mark Notification as Read
```
POST /api/notifications/1/read
Response: {"success": true}
```

## Testing

### Test Scraping
```python
python cost_scraper.py
# Output: JSON dump of scrape_result
```

### Test Update
```python
python cost_updater.py
# Output: JSON dump of update_result
```

### Test Full Workflow
```python
from costs import update_cost_rates
result = update_cost_rates()
print(result)
```

### Test Charge Calculation
```python
from costs import calculate_trade_charges

charges = calculate_trade_charges(
    side="BUY",
    quantity=100,
    price=1500.0,
    product="CNC"
)
print(charges)
```

## Monitoring & Alerts

### Dashboard Indicators
- ✅ **Green**: All costs fresh, no pending changes
- ⚠️ **Yellow**: Some costs haven't been verified in 45 days
- 🔴 **Red**: Multiple recent errors, or suspicious changes awaiting review

### Telegram Alerts
When costs change:
```
🔔 Trading Cost Update
Updated: 2026-07-31 12:00:00 UTC

Updated: 2 costs

Changes:
📈 brokerage_flat_per_order: ₹20.00 → ₹21.00 (+5.0%)
📉 stt_pct_intraday: 0.0250% → 0.0245% (-2.0%)

Source: https://groww.in/charges
```

On suspicious changes:
```
🚨 Suspicious Changes (Require Manual Review):
  • brokerage_flat_per_order changed 15.0%

Review recommended: Check Groww website manually
Command: /costs review
```

## Configuration

### Environment Variables
```bash
# Enable cost notifications via Telegram
TELEGRAM_ENABLED=true
TELEGRAM_COST_NOTIFICATIONS=true

# Database connection (used by cost_updater)
DB_URL=postgresql://user:pass@localhost/grow_trading_bot
```

### Database Config
```python
# In DB: config_settings table
key: "cost.scraper_enabled"
value: "true"

key: "cost.notification_enabled"
value: "true"

key: "cost.verification_frequency_days"
value: "45"
```

## Troubleshooting

### Scrape Fails But System Keeps Working
✅ **Expected behavior**. System falls back to canonical rates. Check logs:
```
logger.warning("Could not parse charges from HTML, using canonical fallback")
```

### Notification Not Sent
Check if Telegram is enabled:
```python
from db_manager import get_config
print(get_config("telegram_enabled"))  # Should be "true"
```

### Costs Not Updating
1. Check scheduler is running: `ps aux | grep master-scheduler`
2. Check database connection: `psql -d grow_trading_bot`
3. Manually trigger: `python costs.py`

### Suspicious Change Detected
Review manually:
```python
from cost_updater import get_cost_history
history = get_cost_history("brokerage_flat_per_order")
print(history[0])  # Latest change
```

If legitimate, accept. If not, rollback:
```python
from cost_updater import rollback_costs
rollback_costs(audit_id=<id from history>)
```

## Future Enhancements

- [ ] Support multiple brokers (Zerodha, Angel, etc)
- [ ] API integration with Groww charges endpoint (if released)
- [ ] Email alerts for suspicious changes
- [ ] Automated acceptance of known rate changes
- [ ] Cost comparison across brokers
- [ ] Historical cost analytics dashboard

## Summary

| Component | Purpose | Runs | Triggers |
|-----------|---------|------|----------|
| `cost_scraper.py` | Fetch & validate costs | Manual / Scheduled | Every 45 days |
| `cost_updater.py` | Update DB with audit trail | Automatic | After scrape |
| `cost_notifications.py` | Alert on changes | Automatic | After update |
| `costs.py` | Orchestrate workflow | Scheduler | Every 45 days |

**All-or-nothing updates ensure data integrity.** If any step fails, database remains unchanged until next successful run.
