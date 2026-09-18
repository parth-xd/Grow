"""
Database migration: one Tijori snapshot per (symbol, data_type, day).

Adds a PARTIAL unique index so the daily partner refresh can upsert today's
row instead of appending a duplicate, while every previous day's row is left
untouched — uniqueness is per-day, so history is preserved by construction.

Why PARTIAL: `company_external_data` has two writers. `_store_snapshots()`
writes the seven snapshot blocks, and `_mark_collection_attempt()` writes
`collection_attempt` rows recording failures. The attempt rows are an
append-only audit trail and several may legitimately share a day, so the
index deliberately excludes them and that writer needs no change.

Verified against live data before writing this: zero (symbol, data_type, day)
groups currently hold more than one row, and zero rows have a NULL
scraped_at, so the index builds without any cleanup.

Additive and safe to re-run — IF NOT EXISTS, and no existing row is altered
or dropped.

Run once before enabling the daily refresh:
    python migrate_tijori_daily_snapshot.py
"""

import logging

import psycopg2

from config import DB_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

INDEX_NAME = "uq_ext_symbol_type_day"

# CONCURRENTLY keeps the dashboard's reads unblocked while it builds, but it
# cannot run inside a transaction block — hence autocommit below.
CREATE_SQL = f"""
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME}
    ON company_external_data (symbol, data_type, (scraped_at::date))
    WHERE data_type <> 'collection_attempt'
"""


def migrate():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True          # required: CONCURRENTLY forbids a txn block
    try:
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_class WHERE relname = %s", (INDEX_NAME,))
        if cur.fetchone():
            logger.info("Index %s already present — nothing to do", INDEX_NAME)
        else:
            # Refuse to build on data that would violate it, rather than
            # failing halfway and leaving an INVALID index behind.
            cur.execute("""
                SELECT count(*) FROM (
                    SELECT 1 FROM company_external_data
                    WHERE data_type <> 'collection_attempt'
                    GROUP BY symbol, data_type, scraped_at::date
                    HAVING count(*) > 1) x
            """)
            dupes = cur.fetchone()[0]
            if dupes:
                logger.error("Refusing to build: %d (symbol,data_type,day) groups "
                             "already hold >1 row. Deduplicate first.", dupes)
                return False
            logger.info("No conflicting rows — building %s …", INDEX_NAME)
            cur.execute(CREATE_SQL)

        # A failed CONCURRENTLY build leaves the index present but INVALID,
        # which silently enforces nothing. Verify rather than assume.
        cur.execute("""
            SELECT i.indisvalid FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = %s
        """, (INDEX_NAME,))
        row = cur.fetchone()
        if not row:
            logger.error("Index %s missing after create", INDEX_NAME)
            return False
        if not row[0]:
            logger.error("Index %s exists but is INVALID — drop it and re-run", INDEX_NAME)
            return False

        logger.info("✓ %s present and valid", INDEX_NAME)
        return True
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(0 if migrate() else 1)
