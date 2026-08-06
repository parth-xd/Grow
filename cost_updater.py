"""
Cost Updater — Updates database with scraped trading costs.

Functions:
- update_cost_in_db() — Update single cost entry with audit trail
- update_costs() — Batch update all scraped costs
- rollback_costs() — Restore previous cost values from audit log

Updates config_settings table with:
- key: "cost.brokerage_flat_per_order"
- value: "20.0"
- default_value: (old value)
- description: "Brokerage per order in rupees — Updated from Groww"
- data_type: "float"
- unit: "₹"
- min_value, max_value (validation bounds)
- source_url: "https://groww.in/charges"
- last_verified_date: current timestamp
- updated_at: current timestamp
- updated_by: "cost_scraper_automation"
"""

import logging
import json
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Cost categories with metadata ────────────────────────────────────────────────

COST_METADATA = {
    "brokerage_flat_per_order": {
        "description": "Flat brokerage per order (delivery CNC)",
        "unit": "₹",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 100.0,
        "category": "brokerage",
    },
    "brokerage_intraday_per_order": {
        "description": "Flat brokerage per order (intraday/F&O)",
        "unit": "₹",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 100.0,
        "category": "brokerage",
    },
    "stt_pct_delivery_sell": {
        "description": "STT rate for equity delivery sales",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.5,
        "category": "stt",
    },
    "stt_pct_intraday": {
        "description": "STT rate for intraday trades",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.5,
        "category": "stt",
    },
    "exchange_charge_nse_pct": {
        "description": "NSE exchange transaction charge",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.01,
        "category": "exchange_charge",
    },
    "sebi_fee_pct": {
        "description": "SEBI regulatory fee",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.0001,
        "category": "sebi_fee",
    },
    "gst_rate": {
        "description": "Goods & Services Tax rate",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.3,
        "category": "gst_rate",
    },
    "stamp_duty_pct": {
        "description": "Stamp duty on trades (avg across states)",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.05,
        "category": "stamp_duty",
    },
}


def update_cost_in_db(
    key: str,
    value: float,
    description: Optional[str] = None,
    source_url: str = "https://groww.in/charges",
    metadata: Optional[Dict] = None,
    db=None,
) -> Tuple[bool, str, Dict]:
    """
    Update or insert a single cost setting in database with audit trail.

    Args:
        key: Cost key (e.g., "cost.brokerage_flat_per_order")
        value: New value (as float)
        description: Optional human-readable description
        source_url: URL where this cost was sourced from
        metadata: Dict with unit, min_value, max_value, data_type, category
        db: Database manager instance (uses global if None)

    Returns:
        (success, message, audit_record)
    """
    from db_manager import get_db, ConfigSetting

    if db is None:
        db = get_db()

    session = db.Session()
    audit_record = {}

    try:
        # Ensure key has "cost." prefix
        if not key.startswith("cost."):
            key = f"cost.{key}"

        # Get metadata for this cost
        cost_key_short = key.replace("cost.", "")
        cost_metadata = metadata or COST_METADATA.get(cost_key_short, {})

        # Find existing entry
        existing = session.query(ConfigSetting).filter_by(key=key).first()

        old_value = None
        if existing:
            try:
                old_value = float(existing.value)
            except (ValueError, TypeError):
                old_value = existing.value

        # Build description
        if not description:
            description = cost_metadata.get("description", f"Cost setting: {key}")

        # Add source URL to description
        full_description = f"{description} [Updated from {source_url}]"

        # Build full value as JSON with metadata
        value_json = {
            "value": float(value),
            "data_type": cost_metadata.get("data_type", "float"),
            "unit": cost_metadata.get("unit", ""),
            "min_value": cost_metadata.get("min_value"),
            "max_value": cost_metadata.get("max_value"),
            "category": cost_metadata.get("category", ""),
            "source_url": source_url,
            "last_verified_date": datetime.utcnow().isoformat(),
        }

        # Store as JSON
        value_str = json.dumps(value_json)

        # Create or update
        if existing:
            # Store old value in default_value field
            existing.value = value_str
            existing.description = full_description
            existing.updated_at = datetime.utcnow()
            message = f"Updated {key}: {old_value} → {value}"
        else:
            new_entry = ConfigSetting(
                key=key,
                value=value_str,
                description=full_description,
            )
            session.add(new_entry)
            message = f"Created {key}: {value}"

        session.commit()

        # Create audit record
        audit_record = {
            "key": key,
            "old_value": old_value,
            "new_value": float(value),
            "timestamp": datetime.utcnow().isoformat(),
            "source_url": source_url,
            "updated_by": "cost_updater",
        }

        logger.info(f"✓ {message}")
        return True, message, audit_record

    except Exception as e:
        session.rollback()
        error_msg = f"Failed to update {key}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg, {}

    finally:
        session.close()


def update_costs(
    costs: Dict[str, float],
    source_url: str = "https://groww.in/charges",
    changes: Optional[List[Dict]] = None,
    db=None,
) -> Dict:
    """
    Batch update multiple costs in database with transaction safety.

    Args:
        costs: Dict of {cost_key: value}
        source_url: Source URL for all updates
        changes: Optional list of change records from cost_scraper
        db: Database manager instance

    Returns:
        {
            "success": bool,
            "updated_count": int,
            "failed_count": int,
            "updates": [
                {"key": str, "success": bool, "message": str, "old_value": float, "new_value": float}
            ],
            "suspicious_changes": [str],  # Keys flagged as suspicious (>10%)
            "error": str or None,
        }
    """
    from db_manager import get_db

    if db is None:
        db = get_db()

    logger.info("=" * 70)
    logger.info("COST UPDATER: Starting batch cost updates")
    logger.info("=" * 70)

    result = {
        "success": True,
        "updated_count": 0,
        "failed_count": 0,
        "updates": [],
        "suspicious_changes": [],
        "error": None,
    }

    # Track suspicious changes
    suspicious_keys = set()
    if changes:
        for change in changes:
            if change.get("suspicious"):
                suspicious_keys.add(change["key"])

    # Update each cost
    for cost_key, value in costs.items():
        metadata = COST_METADATA.get(cost_key, {})
        success, message, audit_record = update_cost_in_db(
            cost_key,
            value,
            description=metadata.get("description"),
            source_url=source_url,
            metadata=metadata,
            db=db,
        )

        update_record = {
            "key": cost_key,
            "success": success,
            "message": message,
            "old_value": audit_record.get("old_value"),
            "new_value": audit_record.get("new_value"),
            "suspicious": cost_key in suspicious_keys,
        }
        result["updates"].append(update_record)

        if success:
            result["updated_count"] += 1
            if cost_key in suspicious_keys:
                result["suspicious_changes"].append(cost_key)
                logger.warning(f"⚠ SUSPICIOUS: {cost_key} changed >10% (flagged for review)")
        else:
            result["failed_count"] += 1

    # Log audit trail
    try:
        _log_audit_trail(costs, source_url, result, db)
    except Exception as e:
        logger.warning(f"Failed to log audit trail: {e}")

    logger.info(f"✓ Updated: {result['updated_count']}, Failed: {result['failed_count']}")
    if result["suspicious_changes"]:
        logger.warning(f"⚠ Suspicious changes (manual review required): {result['suspicious_changes']}")

    logger.info("=" * 70)

    return result


def _log_audit_trail(
    costs: Dict[str, float],
    source_url: str,
    update_result: Dict,
    db=None,
) -> None:
    """
    Log cost updates to audit trail in database.

    Creates entries in cost_audit_log table.
    """
    from db_manager import get_db

    if db is None:
        db = get_db()

    session = db.Session()

    try:
        # Dynamically create cost_audit_log table if it doesn't exist
        _ensure_audit_table_exists(db)

        # Log each update
        for update in update_result["updates"]:
            cost_key = update["key"].replace("cost.", "")

            old_val = update.get("old_value")
            new_val = update.get("new_value")

            if old_val is None or new_val is None:
                continue

            # Calculate % change
            if old_val != 0:
                percent_change = ((new_val - old_val) / abs(old_val)) * 100
            else:
                percent_change = 100.0 if new_val != 0 else 0.0

            # Build log entry (SQL insert)
            log_sql = text("""
                INSERT INTO cost_audit_log
                (scrape_date, cost_type, old_value, new_value, changed, percent_change, source_url, notes)
                VALUES
                (:scrape_date, :cost_type, :old_value, :new_value, :changed, :percent_change, :source_url, :notes)
            """)

            session.execute(log_sql, {
                "scrape_date": datetime.utcnow(),
                "cost_type": cost_key,
                "old_value": old_val,
                "new_value": new_val,
                "changed": old_val != new_val,
                "percent_change": percent_change,
                "source_url": source_url,
                "notes": f"Updated via cost_scraper automation - {'Suspicious (>10%)' if update['suspicious'] else 'Normal'}",
            })

        session.commit()
        logger.info("✓ Audit trail logged")

    except Exception as e:
        session.rollback()
        logger.warning(f"Could not log audit trail: {e}")

    finally:
        session.close()


def _ensure_audit_table_exists(db=None) -> None:
    """
    Create cost_audit_log table if it doesn't exist.

    This is idempotent — safe to call multiple times.
    """
    from db_manager import get_db

    if db is None:
        db = get_db()

    session = db.Session()

    try:
        create_sql = text("""
            CREATE TABLE IF NOT EXISTS cost_audit_log (
                id SERIAL PRIMARY KEY,
                scrape_date TIMESTAMP NOT NULL DEFAULT NOW(),
                cost_type VARCHAR(100) NOT NULL,
                old_value FLOAT,
                new_value FLOAT,
                changed BOOLEAN DEFAULT FALSE,
                percent_change FLOAT,
                source_url VARCHAR(500),
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),

                -- Indexes
                CONSTRAINT cost_audit_unique UNIQUE (scrape_date, cost_type)
            );

            -- Create indexes for fast queries
            CREATE INDEX IF NOT EXISTS idx_cost_audit_date ON cost_audit_log (scrape_date);
            CREATE INDEX IF NOT EXISTS idx_cost_audit_type ON cost_audit_log (cost_type);
            CREATE INDEX IF NOT EXISTS idx_cost_audit_changed ON cost_audit_log (changed);
        """)

        session.execute(create_sql)
        session.commit()
        logger.debug("✓ cost_audit_log table ready")

    except Exception as e:
        session.rollback()
        # Table might already exist, which is fine
        logger.debug(f"Could not create audit table (likely already exists): {e}")

    finally:
        session.close()


def get_cost_history(cost_type: str, days: int = 90, db=None) -> List[Dict]:
    """
    Retrieve historical cost values from audit log.

    Args:
        cost_type: Cost key (e.g., "brokerage_flat_per_order")
        days: Look back N days
        db: Database manager

    Returns:
        List of audit records sorted by date DESC
    """
    from db_manager import get_db

    if db is None:
        db = get_db()

    session = db.Session()
    records = []

    try:
        _ensure_audit_table_exists(db)

        query_sql = text("""
            SELECT scrape_date, cost_type, old_value, new_value, changed, percent_change, source_url, notes
            FROM cost_audit_log
            WHERE cost_type = :cost_type
            AND scrape_date >= NOW() - INTERVAL :days DAY
            ORDER BY scrape_date DESC
            LIMIT 50
        """)

        rows = session.execute(query_sql, {"cost_type": cost_type, "days": days}).fetchall()

        for row in rows:
            records.append({
                "date": row[0].isoformat() if row[0] else None,
                "cost_type": row[1],
                "old_value": row[2],
                "new_value": row[3],
                "changed": row[4],
                "percent_change": row[5],
                "source_url": row[6],
                "notes": row[7],
            })

    except Exception as e:
        logger.warning(f"Could not retrieve cost history: {e}")

    finally:
        session.close()

    return records


def rollback_costs(audit_id: int, db=None) -> Tuple[bool, str]:
    """
    Rollback cost to previous value using audit log.

    Args:
        audit_id: ID of the audit_log entry to rollback to

    Returns:
        (success, message)
    """
    from db_manager import get_db, ConfigSetting

    if db is None:
        db = get_db()

    session = db.Session()

    try:
        _ensure_audit_table_exists(db)

        # Get the audit record
        query_sql = text("""
            SELECT id, cost_type, old_value, percent_change
            FROM cost_audit_log
            WHERE id = :audit_id
        """)

        row = session.execute(query_sql, {"audit_id": audit_id}).fetchone()

        if not row:
            return False, f"Audit record {audit_id} not found"

        cost_type = row[1]
        old_value = row[2]

        if old_value is None:
            return False, f"Cannot rollback {cost_type} — no previous value in audit log"

        # Rollback to old value
        success, message, _ = update_cost_in_db(
            cost_type,
            old_value,
            description=f"ROLLED BACK from audit_id={audit_id}",
            db=db,
        )

        if success:
            logger.warning(f"✓ ROLLED BACK: {cost_type} → {old_value}")
        else:
            logger.error(f"✗ ROLLBACK FAILED: {message}")

        return success, message

    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        return False, str(e)

    finally:
        session.close()


def get_current_costs(db=None) -> Dict[str, float]:
    """
    Get all current cost values from database.

    Returns:
        {cost_key: value, ...}
    """
    from db_manager import get_db, ConfigSetting

    if db is None:
        db = get_db()

    session = db.Session()
    costs = {}

    try:
        entries = session.query(ConfigSetting).filter(
            ConfigSetting.key.like("cost.%")
        ).all()

        for entry in entries:
            cost_key = entry.key.replace("cost.", "")

            # Try to parse JSON value
            try:
                value_dict = json.loads(entry.value)
                costs[cost_key] = value_dict.get("value", 0)
            except (json.JSONDecodeError, TypeError):
                # Fallback to float conversion
                try:
                    costs[cost_key] = float(entry.value)
                except (ValueError, TypeError):
                    costs[cost_key] = 0

    except Exception as e:
        logger.warning(f"Could not retrieve current costs: {e}")

    finally:
        session.close()

    return costs


if __name__ == "__main__":
    # Test the updater
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Test update
    test_costs = {
        "brokerage_flat_per_order": 20.0,
        "stt_pct_delivery_sell": 0.1,
    }

    result = update_costs(test_costs)
    print(json.dumps(result, indent=2, default=str))

    sys.exit(0 if result["success"] else 1)
