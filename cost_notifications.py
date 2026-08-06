"""
Cost Notification System — Alerts user when trading costs change.

Sends notifications via:
- Telegram (if enabled)
- Dashboard notification
- Email (future)

Also logs to database for audit trail.
"""

import logging
import json
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def send_cost_change_notification(
    update_result: Dict,
    scrape_result: Dict,
    db=None,
) -> Dict[str, bool]:
    """
    Send notifications about cost changes.

    Args:
        update_result: Result from cost_updater.update_costs()
        scrape_result: Result from cost_scraper.scrape()
        db: Database manager

    Returns:
        {
            "telegram_sent": bool,
            "dashboard_logged": bool,
            "errors": [str]
        }
    """
    result = {
        "telegram_sent": False,
        "dashboard_logged": False,
        "errors": [],
    }

    # Format notification message
    message = _format_notification_message(update_result, scrape_result)

    logger.info("=" * 70)
    logger.info("COST NOTIFICATIONS")
    logger.info("=" * 70)
    logger.info(message)

    # Try to send via Telegram
    try:
        if _should_send_telegram():
            success = _send_telegram_notification(message)
            result["telegram_sent"] = success
            if success:
                logger.info("✓ Telegram notification sent")
            else:
                result["errors"].append("Telegram send failed (bot may be offline)")
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")
        result["errors"].append(str(e))

    # Log to dashboard / database
    try:
        success = _log_dashboard_notification(message, update_result, scrape_result, db)
        result["dashboard_logged"] = success
        if success:
            logger.info("✓ Dashboard notification logged")
    except Exception as e:
        logger.warning(f"Dashboard notification failed: {e}")
        result["errors"].append(str(e))

    logger.info("=" * 70)

    return result


def _format_notification_message(
    update_result: Dict,
    scrape_result: Dict,
) -> str:
    """Format cost changes into readable notification message."""

    lines = [
        "🔔 <b>Trading Cost Update</b>",
        f"Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
    ]

    # Summary
    total_updates = update_result.get("updated_count", 0)
    failed_count = update_result.get("failed_count", 0)
    suspicious = update_result.get("suspicious_changes", [])

    if total_updates == 0 and failed_count == 0:
        lines.append("✅ <b>No changes detected</b> in cost structure")
        lines.append("All trading rates remain the same")
    else:
        if total_updates > 0:
            lines.append(f"<b>Updated: {total_updates} costs</b>")

        if failed_count > 0:
            lines.append(f"⚠️ <b>Failed: {failed_count} updates</b>")

        lines.append("")

        # Detailed changes
        if update_result.get("updates"):
            lines.append("<b>Changes:</b>")
            for update in update_result["updates"]:
                if not update["success"]:
                    continue

                key = update["key"].replace("cost.", "")
                old_val = update.get("old_value")
                new_val = update.get("new_value")

                if old_val is None or new_val is None:
                    continue

                # Calculate change
                if old_val != 0:
                    pct_change = ((new_val - old_val) / abs(old_val)) * 100
                else:
                    pct_change = 100.0 if new_val != 0 else 0.0

                # Format value nicely
                if "%"  in key or "pct" in key:
                    old_display = f"{old_val:.4f}%"
                    new_display = f"{new_val:.4f}%"
                else:
                    old_display = f"₹{old_val:.2f}"
                    new_display = f"₹{new_val:.2f}"

                # Direction arrow
                if pct_change > 0:
                    arrow = "📈"
                elif pct_change < 0:
                    arrow = "📉"
                else:
                    arrow = "➡️"

                suspicious_flag = " 🚨 MANUAL REVIEW" if update["suspicious"] else ""

                lines.append(
                    f"{arrow} <b>{key}</b>: {old_display} → {new_display} "
                    f"({pct_change:+.1f}%){suspicious_flag}"
                )

    # Warnings
    if scrape_result.get("validation_errors"):
        lines.append("")
        lines.append("⚠️ <b>Validation Warnings:</b>")
        for error in scrape_result["validation_errors"]:
            lines.append(f"  • {error}")

    if update_result.get("suspicious_changes"):
        lines.append("")
        lines.append("🚨 <b>Suspicious Changes (Require Manual Review):</b>")
        for key in update_result["suspicious_changes"]:
            lines.append(f"  • {key} changed >10%")

    # Footer
    lines.append("")
    lines.append(f"Source: {scrape_result.get('source_url', 'Groww')}")
    lines.append(f"Time: {scrape_result.get('timestamp', 'N/A')}")

    return "\n".join(lines)


def _should_send_telegram() -> bool:
    """Check if Telegram notifications are enabled."""
    try:
        from db_manager import get_config

        enabled = get_config("telegram_enabled", "false").lower() == "true"
        cost_notif_enabled = get_config("telegram_cost_notifications", "true").lower() == "true"

        return enabled and cost_notif_enabled
    except Exception:
        return False


def _send_telegram_notification(message: str) -> bool:
    """
    Send notification via Telegram bot.

    Returns:
        True if sent successfully
    """
    try:
        import telegram_alerts

        telegram_alerts.send_message(message)
        return True

    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")
        return False


def _log_dashboard_notification(
    message: str,
    update_result: Dict,
    scrape_result: Dict,
    db=None,
) -> bool:
    """
    Log cost change notification to database.

    Stores in a notifications table for dashboard display.

    Returns:
        True if logged successfully
    """
    from db_manager import get_db
    from sqlalchemy import text

    if db is None:
        db = get_db()

    session = db.Session()

    try:
        # Ensure notifications table exists
        _ensure_notification_table_exists(db)

        # Prepare notification data
        notification_json = json.dumps({
            "type": "cost_update",
            "update_result": update_result,
            "scrape_result": scrape_result,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Insert notification
        insert_sql = text("""
            INSERT INTO cost_notifications
            (type, message, data, is_read, created_at)
            VALUES
            (:type, :message, :data, FALSE, NOW())
        """)

        session.execute(insert_sql, {
            "type": "cost_update",
            "message": message[:500],  # Truncate to first 500 chars for subject
            "data": notification_json,
        })

        session.commit()
        return True

    except Exception as e:
        session.rollback()
        logger.warning(f"Could not log dashboard notification: {e}")
        return False

    finally:
        session.close()


def _ensure_notification_table_exists(db=None) -> None:
    """Create cost_notifications table if it doesn't exist."""
    from db_manager import get_db
    from sqlalchemy import text

    if db is None:
        db = get_db()

    session = db.Session()

    try:
        create_sql = text("""
            CREATE TABLE IF NOT EXISTS cost_notifications (
                id SERIAL PRIMARY KEY,
                type VARCHAR(50) NOT NULL,                 -- "cost_update", "warning", etc
                message VARCHAR(1000) NOT NULL,            -- Notification subject/title
                data TEXT,                                  -- Full notification data (JSON)
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),

                -- Indexes
                CONSTRAINT cost_notif_unique UNIQUE (type, created_at)
            );

            CREATE INDEX IF NOT EXISTS idx_cost_notif_type ON cost_notifications (type);
            CREATE INDEX IF NOT EXISTS idx_cost_notif_read ON cost_notifications (is_read);
            CREATE INDEX IF NOT EXISTS idx_cost_notif_date ON cost_notifications (created_at DESC);
        """)

        session.execute(create_sql)
        session.commit()
        logger.debug("✓ cost_notifications table ready")

    except Exception as e:
        session.rollback()
        logger.debug(f"Could not create notifications table (likely already exists): {e}")

    finally:
        session.close()


def get_unread_notifications(limit: int = 10, db=None) -> List[Dict]:
    """Get unread cost notifications from database."""
    from db_manager import get_db
    from sqlalchemy import text

    if db is None:
        db = get_db()

    session = db.Session()
    notifications = []

    try:
        _ensure_notification_table_exists(db)

        query_sql = text("""
            SELECT id, type, message, data, created_at
            FROM cost_notifications
            WHERE is_read = FALSE
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        rows = session.execute(query_sql, {"limit": limit}).fetchall()

        for row in rows:
            try:
                data = json.loads(row[3]) if row[3] else {}
            except json.JSONDecodeError:
                data = {}

            notifications.append({
                "id": row[0],
                "type": row[1],
                "message": row[2],
                "data": data,
                "created_at": row[4].isoformat() if row[4] else None,
            })

    except Exception as e:
        logger.warning(f"Could not retrieve notifications: {e}")

    finally:
        session.close()

    return notifications


def mark_notification_as_read(notification_id: int, db=None) -> bool:
    """Mark a notification as read."""
    from db_manager import get_db
    from sqlalchemy import text

    if db is None:
        db = get_db()

    session = db.Session()

    try:
        update_sql = text("""
            UPDATE cost_notifications
            SET is_read = TRUE
            WHERE id = :id
        """)

        session.execute(update_sql, {"id": notification_id})
        session.commit()
        return True

    except Exception as e:
        session.rollback()
        logger.warning(f"Could not mark notification as read: {e}")
        return False

    finally:
        session.close()


if __name__ == "__main__":
    # Test notification formatting
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    test_update = {
        "success": True,
        "updated_count": 2,
        "failed_count": 0,
        "updates": [
            {
                "key": "cost.brokerage_flat_per_order",
                "success": True,
                "message": "Updated cost.brokerage_flat_per_order: 20.0 → 21.0",
                "old_value": 20.0,
                "new_value": 21.0,
                "suspicious": True,
            },
            {
                "key": "cost.stt_pct_delivery_sell",
                "success": True,
                "message": "Updated cost.stt_pct_delivery_sell: 0.1 → 0.1",
                "old_value": 0.1,
                "new_value": 0.1,
                "suspicious": False,
            },
        ],
        "suspicious_changes": ["brokerage_flat_per_order"],
    }

    test_scrape = {
        "success": True,
        "timestamp": datetime.utcnow().isoformat(),
        "source_url": "https://groww.in/charges",
        "validation_errors": [],
    }

    message = _format_notification_message(test_update, test_scrape)
    print(message)

    sys.exit(0)
