"""
Database migration: create the idempotency_keys table.

Additive and safe to re-run — create_all() skips tables that already exist and
touches nothing else. No existing table is altered or dropped.

Run once before starting the app:
    python migrate_idempotency.py
"""

import logging
from sqlalchemy import create_engine, inspect

from config import DB_URL
from db_manager import Base, IdempotencyKey

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _add_missing_columns(engine):
    """
    Add columns introduced after the table was first created.

    Purely additive — only ever ADD COLUMN, never drop or alter an existing one,
    and each is nullable so rows written by the previous version stay valid.
    """
    from sqlalchemy import text

    have = {c["name"] for c in inspect(engine).get_columns(IdempotencyKey.__tablename__)}

    # content_type: replay must reproduce the original response type instead of
    # assuming JSON. Rows written before this column existed replay as JSON,
    # which is what every endpoint using the table returns today.
    if "content_type" not in have:
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {IdempotencyKey.__tablename__} "
                f"ADD COLUMN content_type VARCHAR(100)"
            ))
        logger.info("✓ Added column content_type to %s", IdempotencyKey.__tablename__)
    else:
        logger.info("✓ Column content_type already present")


def migrate():
    """Create idempotency_keys if absent, then seed its config defaults."""
    engine = create_engine(DB_URL)

    existing = set(inspect(engine).get_table_names())
    if IdempotencyKey.__tablename__ in existing:
        logger.info("✓ %s already exists — nothing to create", IdempotencyKey.__tablename__)
        _add_missing_columns(engine)
    else:
        # Create ONLY this table, so a stale model elsewhere can't accidentally
        # create or alter anything we didn't intend to touch.
        Base.metadata.create_all(engine, tables=[IdempotencyKey.__table__])
        logger.info("✓ Created table %s", IdempotencyKey.__tablename__)

    # Operational knobs live in config_settings, not in constants, so they can
    # be changed from the Settings tab without a deploy.
    try:
        from db_manager import get_config, set_config

        if get_config("idempotency.require_key") is None:
            set_config(
                "idempotency.require_key", "0",
                "Reject money-path requests that omit an Idempotency-Key header "
                "(0 = accept for backward compatibility, 1 = require)",
            )
            logger.info("✓ Seeded config idempotency.require_key = 0 (backward compatible)")

        if get_config("idempotency.retention_hours") is None:
            set_config(
                "idempotency.retention_hours", "48",
                "How long to keep idempotency keys before pruning (hours)",
            )
            logger.info("✓ Seeded config idempotency.retention_hours = 48")
    except Exception as e:
        # The table is the important part; config defaults have safe fallbacks
        # in code, so a failure here must not fail the migration.
        logger.warning("Config seeding skipped: %s", e)

    logger.info("✅ Idempotency migration complete")


if __name__ == "__main__":
    migrate()
