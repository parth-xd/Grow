-- Proposed schema for FYERS-sourced market data.
-- NOT YET EXECUTED against the live database — this is a reviewable
-- proposal per Phase 1's stop condition ("recommended database architecture
-- produced"), not a completed migration step. Run manually after review.
--
-- Does NOT touch, rename, or alter candles / intraday_candles / stock_prices.
-- Those stay exactly as they are; see docs/FYERS_MIGRATION_PHASE1.md section I
-- for why (existing `candles` table audit: 127x disk bloat, three silently
-- mixed resolutions, never vacuumed — reasons to not extend that table
-- further, not reasons this new one needs anything exotic).

-- NOTE: an earlier draft of this schema used `id BIGSERIAL PRIMARY KEY` with
-- no partition-key column in the PK. That is invalid in Postgres — a unique
-- constraint (including a PK) on a partitioned table must include every
-- partitioning column. Caught by test-creating this exact DDL in a rolled-
-- back transaction before ever running it for real. Fixed below with a
-- composite `PRIMARY KEY (id, ts)`.

CREATE TABLE fyers_candles (
    id              BIGSERIAL NOT NULL,
    symbol          VARCHAR(40)  NOT NULL,   -- canonical symbol e.g. 'RELIANCE' — matches master_ticker_table.nse_ticker (NOT FYERS's 'NSE:RELIANCE-EQ' wire format; that's resolved via master_ticker_table.fyers_historical_symbol at fetch time)
    exchange        VARCHAR(10)  NOT NULL DEFAULT 'NSE',
    provider        VARCHAR(20)  NOT NULL DEFAULT 'FYERS',
    source_type     VARCHAR(20)  NOT NULL,   -- 'historical' | 'websocket' — lets you answer "where did this candle come from" per requirement 23
    resolution      VARCHAR(10)  NOT NULL,   -- '5S','10S','15S','30S','45S','1'..'240','D','1W','1M' — explicit always, never inferred from timestamp spacing (requirement 22)
    ts              TIMESTAMPTZ  NOT NULL,   -- candle OPEN time, timezone-aware. Existing `candles` table uses naive TIMESTAMP (confirmed in the DB audit) — this is a deliberate improvement, not an oversight; naive timestamps are exactly the kind of ambiguity flagged in requirement 16.
    open            DOUBLE PRECISION NOT NULL,
    high            DOUBLE PRECISION NOT NULL,
    low             DOUBLE PRECISION NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    volume          BIGINT,
    open_interest   BIGINT,                  -- nullable; only populated when oi_flag=1 was requested (F&O only, per FYERS docs)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, ts),
    CONSTRAINT uq_fyers_candles UNIQUE (symbol, provider, resolution, ts),
    CONSTRAINT chk_ohlc_sane CHECK (
        low <= open AND low <= close AND
        high >= open AND high >= close AND
        low <= high
    )
) PARTITION BY RANGE (ts);

-- Yearly partitions, 1997-2028. At current real scale (per-symbol backfill
-- triggered by an explicit Watchlist add, not a bulk universe load — a
-- handful of symbols at a time, not hundreds) yearly partitions keep
-- pruning benefits for date/resolution-scoped queries without the
-- management overhead of ~350 monthly partitions. Revisit toward monthly
-- only if symbol count grows enough that a single year's 1-minute data
-- becomes unwieldy (would need ~150+ actively-backfilled symbols).
DO $$
DECLARE yr INT;
BEGIN
    FOR yr IN 1997..2028 LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS fyers_candles_%s PARTITION OF fyers_candles FOR VALUES FROM (%L) TO (%L)',
            yr, yr || '-01-01', (yr + 1) || '-01-01'
        );
    END LOOP;
END $$;

CREATE INDEX idx_fyers_candles_lookup ON fyers_candles (symbol, resolution, ts);
CREATE INDEX idx_fyers_candles_source ON fyers_candles (provider, source_type);

-- No TimescaleDB: at this symbol count (~75-150) and with FYERS's seconds
-- data structurally capped to a 30-trading-day rolling window (can't be
-- backfilled at all — see docs/FYERS_MIGRATION_PHASE1.md section E), native
-- partitioning + these two indexes cover the real access patterns. Revisit
-- only if this table's growth rate turns out to need continuous aggregates
-- TimescaleDB would provide for free.
