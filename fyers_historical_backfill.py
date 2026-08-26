"""
FYERS historical backfill — daily + 1-minute + 5-second, per the resolution
ladder re-verified live on 2026-08-15:

  Daily:    1997-06-25 -> today        (platform floor — confirmed on TWO
                                         independent old-listed companies,
                                         RELIANCE and ITC, both landing on
                                         the same date)
  1-minute: 2017-07-03 -> today - 35d  (equity floor; index floor lags by
                                         about a month, handled naturally —
                                         FYERS returns no_data rather than
                                         erroring for pre-floor requests, so
                                         no separate index code path needed)
  5-second: today - 35d -> today       (real window is ~25-30 trading days;
                                         the 35-calendar-day request is a
                                         safety margin, FYERS truncates to
                                         what actually exists)

Request-window chunking uses the empirically-confirmed hard caps: 366
calendar days for 'D', 100 for '1' and '5S' (101+/367+ returns error -50).

Triggered ONLY per-symbol from the existing Watchlist-add flow. Never runs
for the full universe automatically — mirrors master_ticker_table's own
directory-not-collection boundary.

Additive: does not touch stock_prices, candles, or the existing Groww fetch.
Writes into fyers_candles alongside whatever else watchlist-add already does.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import fyers_client

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
PACE_SECONDS = 0.5  # well under FYERS's 10/sec, 200/min limits

DAILY_FLOOR = datetime(1997, 6, 25)
MINUTE_FLOOR = datetime(2017, 7, 3)
SECONDS_LOOKBACK_DAYS = 35

MAX_DAYS = {"D": 366, "1": 100, "5S": 100}


def _chunks(start, end, max_days):
    """Yield (from, to) date-string pairs, each span <= max_days, covering [start, end]."""
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days), end)
        yield cur.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        cur = chunk_end + timedelta(days=1)


def _to_ts(epoch, resolution):
    """
    Candle-open timestamp, resolution-aware.

    Intraday (1-min, 5S) epochs are already the true candle-open instant in
    IST — verified live this session (first 1-min bar of a day = 09:15:00
    IST). Daily epochs are stamped at 00:00 UTC (05:30 IST) of the trade
    date instead — a different, documented FYERS convention — so they're
    normalized here to 09:15 IST of the same calendar date, keeping `ts`
    meaning "session open" consistently across every resolution in this
    table rather than silently mixing two conventions.
    """
    raw = datetime.fromtimestamp(epoch, tz=IST)
    if resolution == "D":
        return raw.replace(hour=9, minute=15, second=0, microsecond=0)
    return raw


def _fetch_resolution(fyers_symbol, resolution, start, end):
    """Fetch one resolution across its full range, chunked to the confirmed request-window limit."""
    max_days = MAX_DAYS[resolution]
    rows = []
    repaired = dropped = 0
    for frm, to in _chunks(start, end, max_days):
        status, data = fyers_client.get_historical_candles(fyers_symbol, resolution, frm, to, date_format=1)
        time.sleep(PACE_SECONDS)
        if data.get("s") == "error":
            logger.warning("FYERS %s %s %s->%s: %s", fyers_symbol, resolution, frm, to, data.get("message"))
            continue
        for c in (data.get("candles") or []):
            epoch, o, h, l, cl, v = c[:6]
            # REPAIR a malformed bar rather than DROPPING it.
            #
            # FYERS occasionally returns a bar whose high/low do not bracket
            # its open/close — measured at 227 of 835,641 KOTAKBANK 1-minute
            # bars (0.027%), 85% of them with high and low simply transposed
            # (e.g. o=334.89 h=334.65 l=334.89 c=334.65).
            #
            # This used to `continue`, which silently punched holes in the
            # series. A hole is worse than a marginally widened bar: nothing
            # downstream can see it, and get_fyers_candles_as_5min() will
            # happily build a "5-minute" bar out of whatever minutes survived
            # without signalling that it did.
            #
            # max/min over the four reported prices is the minimal defensible
            # reconstruction — each of those prices genuinely traded, so the
            # true high is at least their max and the true low at most their
            # min. No price outside the reported set is ever invented. For a
            # well-formed bar it is a no-op (max is already h, min already l).
            # By construction the result always satisfies the DB's OHLC CHECK
            # (o and cl both lie within [min, max]), so no bar can be lost to
            # this path again for any symbol.
            if not (l <= o <= h and l <= cl <= h and l <= h):
                if min(o, h, l, cl) <= 0:
                    # Not a transposition — genuinely impossible data. FYERS
                    # returns a handful of these for pre-2001 daily bars
                    # (KOTAKBANK: 3 bars, o=h=l=0.0 with c=0.63). Repairing
                    # one yields a bar with a zero open/low, which turns every
                    # downstream return and ratio into inf/NaN. A zero-price
                    # bar has no defensible reconstruction, so this stays a
                    # drop — the ONLY case that still drops.
                    dropped += 1
                    logger.warning("Dropping non-positive-price candle %s %s %s: %s",
                                   fyers_symbol, resolution, epoch, c)
                    continue
                h, l = max(o, h, l, cl), min(o, h, l, cl)
                repaired += 1
            rows.append((_to_ts(epoch, resolution), o, h, l, cl, v))
    if repaired or dropped:
        # One summary line, not one per bar: the old per-bar warning produced
        # hundreds of lines and buried the outcome.
        logger.warning("%s %s: repaired %d malformed OHLC bar(s), dropped %d non-positive (%d kept)",
                       fyers_symbol, resolution, repaired, dropped, len(rows))
    return rows


def _store(symbol, resolution, rows):
    """
    Idempotent upsert into fyers_candles. Returns count of rows actually
    newly inserted.

    Deliberately does NOT trust cur.rowcount after execute_values(): with
    large row counts that call pages internally (default page_size=100,
    and a single backfill can be 800k+ rows), rowcount reflects only the
    last internal page, not the true total — confirmed by direct
    measurement (reported 51, actual 834,251). Counting before/after
    instead is correct regardless of internal batching.
    """
    if not rows:
        return 0
    import psycopg2
    from psycopg2.extras import execute_values

    conn = psycopg2.connect(os.getenv("DB_URL"))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM fyers_candles WHERE symbol=%s AND resolution=%s",
            (symbol, resolution),
        )
        before = cur.fetchone()[0]

        values = [(symbol, "historical", resolution, ts, o, h, l, cl, v) for ts, o, h, l, cl, v in rows]
        execute_values(cur, """
            INSERT INTO fyers_candles (symbol, source_type, resolution, ts, open, high, low, close, volume)
            VALUES %s
            ON CONFLICT (symbol, provider, resolution, ts) DO NOTHING
        """, values, page_size=1000)

        cur.execute(
            "SELECT count(*) FROM fyers_candles WHERE symbol=%s AND resolution=%s",
            (symbol, resolution),
        )
        after = cur.fetchone()[0]
        conn.commit()
        return after - before
    finally:
        conn.close()


def backfill_symbol(nse_ticker):
    """
    Backfill the full FYERS resolution ladder for one symbol, using its
    master_ticker_table mapping. Never raises for a missing FYERS mapping —
    returns a status the caller can use to fall back to Groww instead.
    """
    from db_manager import get_db, MasterTicker

    db = get_db()
    with db.Session() as session:
        row = session.query(MasterTicker).filter_by(nse_ticker=nse_ticker).first()

    if not row or row.fyers_resolution_status != "resolved":
        reason = row.fyers_unresolved_reason if row else "symbol not found in master_ticker_table"
        logger.warning("No FYERS mapping for %s: %s", nse_ticker, reason)
        return {"symbol": nse_ticker, "status": "no_fyers_mapping", "reason": reason}

    fyers_symbol = row.fyers_historical_symbol
    today = datetime.now(IST).replace(tzinfo=None)
    seconds_start = today - timedelta(days=SECONDS_LOOKBACK_DAYS)

    result = {"symbol": nse_ticker, "fyers_symbol": fyers_symbol, "status": "ok", "resolutions": {}}
    for resolution, start, end in [
        ("D", DAILY_FLOOR, today),
        ("1", MINUTE_FLOOR, seconds_start),
        ("5S", seconds_start, today),
    ]:
        rows = _fetch_resolution(fyers_symbol, resolution, start, end)
        inserted = _store(nse_ticker, resolution, rows)
        result["resolutions"][resolution] = {"fetched": len(rows), "inserted": inserted}
        logger.info("Backfilled %s %s: %d fetched, %d new", nse_ticker, resolution, len(rows), inserted)

    return result


# ── Intraday freshness top-up ────────────────────────────────────────────────
# The full backfill above runs on Watchlist-add. The cash prediction pipeline
# additionally needs today's bars to be current, which is what the legacy
# Groww `sync_candles_from_api()` provided for the old table. This is the
# minimum FYERS equivalent: a small, bounded, throttled top-up of the most
# recent 5-second data, reusing the same REST fetch/store path as the backfill.
# No new market-data architecture, no WebSocket.

_FRESHNESS_TTL_SECONDS = 300      # don't re-check the same symbol more often
_FRESHNESS_LOOKBACK_DAYS = 3      # small window: today + a weekend's slack
_last_freshness_check = {}


def ensure_recent(symbol, ttl_seconds=_FRESHNESS_TTL_SECONDS):
    """
    Top up the last few days of 5-second candles for one symbol if we haven't
    checked recently. Throttled in-process so a scan loop over many symbols
    doesn't issue an API call per symbol per iteration.

    Returns the number of new rows stored (0 if skipped or already current).
    Never raises — freshness is best-effort and must not break a prediction.
    """
    import time as _time
    now = _time.time()
    last = _last_freshness_check.get(symbol, 0)
    if now - last < ttl_seconds:
        return 0
    _last_freshness_check[symbol] = now

    try:
        from db_manager import get_db, MasterTicker
        db = get_db()
        with db.Session() as session:
            row = session.query(MasterTicker).filter_by(nse_ticker=symbol).first()
        if not row or row.fyers_resolution_status != "resolved":
            return 0

        today = datetime.now(IST).replace(tzinfo=None)
        start = today - timedelta(days=_FRESHNESS_LOOKBACK_DAYS)
        candles = _fetch_resolution(row.fyers_historical_symbol, "5S", start, today)
        stored = _store(symbol, "5S", candles)
        if stored:
            logger.debug("FYERS freshness: %s +%d new 5S rows", symbol, stored)
        return stored
    except Exception as e:
        logger.debug("FYERS freshness top-up failed for %s: %s", symbol, e)
        return 0


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    symbol = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    print(backfill_symbol(symbol))


# ── Daily-tier top-up ────────────────────────────────────────────────────────

def topup_daily(symbols=None):
    """
    Append recent DAILY bars for many symbols, incrementally.

    Why this exists: ensure_recent() refreshes the '5S' tier only, and
    backfill_symbol() is a first-time, whole-history operation (64 API calls
    per symbol, ~947k rows re-fetched to insert a few hundred). Nothing topped
    up resolution='D', so the daily tier drifted behind while 5S stayed current
    — measured at 2026-08-14 against a 5S tier current to 2026-08-21.

    This reads each symbol's newest stored daily bar and fetches only from
    there, so it is ONE API call per symbol in steady state and self-heals a
    long gap by chunking forward. Storage is ON CONFLICT DO NOTHING, so a
    re-run is a no-op rather than a duplicate.

    Both lookups are batched (one query for the latest-bar map, one for the
    FYERS symbol map) rather than queried per symbol — a per-symbol query here
    would be an N+1 over the whole watchlist.
    """
    from sqlalchemy import text
    from db_manager import CandleDatabase, MasterTicker, get_db

    if symbols is None:
        try:
            import bot
            symbols = list(bot.get_active_watchlist())
        except Exception:
            return {"checked": 0, "stored": 0, "skipped": 0}
    symbols = [s for s in symbols if s]
    if not symbols:
        return {"checked": 0, "stored": 0, "skipped": 0}

    db = CandleDatabase()
    with db.engine.connect() as conn:
        latest = {
            r[0]: r[1]
            for r in conn.execute(
                text("SELECT symbol, max(ts AT TIME ZONE 'Asia/Kolkata')::date "
                     "FROM fyers_candles WHERE resolution='D' AND symbol = ANY(:syms) "
                     "GROUP BY symbol"),
                {"syms": symbols},
            )
        }
    with get_db().Session() as session:
        fy = {
            r.nse_ticker: r.fyers_historical_symbol
            for r in session.query(MasterTicker)
                            .filter(MasterTicker.nse_ticker.in_(symbols),
                                    MasterTicker.fyers_resolution_status == "resolved")
                            .all()
        }

    today = datetime.now(IST).replace(tzinfo=None)
    stored_total = skipped = 0
    for sym in symbols:
        fsym = fy.get(sym)
        if not fsym:
            skipped += 1
            continue
        last = latest.get(sym)
        # No daily history at all -> that is a first-time backfill, not a
        # top-up; leave it to backfill_symbol() rather than pulling 29 years
        # through a task that runs every day.
        if not last:
            skipped += 1
            continue
        start = datetime(last.year, last.month, last.day)
        if (today.date() - last).days < 1:
            continue                      # already current
        try:
            rows = _fetch_resolution(fsym, "D", start, today)
            stored_total += _store(sym, "D", rows)
        except Exception as e:
            logger.debug("daily top-up failed for %s: %s", sym, e)
    logger.info("FYERS daily top-up: %d symbols, %d new bars, %d skipped",
                len(symbols), stored_total, skipped)
    return {"checked": len(symbols), "stored": stored_total, "skipped": skipped}
