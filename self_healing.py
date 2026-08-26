"""
Self-healing for the FYERS market-data pipeline.

Detects the recurring *data/state* failures seen during the Groww->FYERS
migration and repairs the ones that are safely repairable, automatically.

DESIGN RULES — read before adding a healer:

1. NEVER touch order execution, position state, or trading decisions. This
   module only repairs market DATA. A healer that could change what the bot
   trades does not belong here.

2. Every remediation must be IDEMPOTENT and INSERT-ONLY. backfill_symbol()
   qualifies (ON CONFLICT DO NOTHING). Anything that deletes, updates or
   overwrites does not.

3. If a fault CANNOT be safely auto-fixed, the healer reports it instead of
   guessing. The FYERS token is the clearest example: its refresh API is
   disabled by FYERS for SEBI compliance (verified, code=-16), so no code
   can renew it — a human must log in. Pretending otherwise would hide a
   real outage behind a retry loop.

4. Guardrails are mandatory: per-symbol cooldowns and a per-run action cap,
   so a persistent fault becomes one alert rather than an infinite repair
   loop hammering the FYERS API.

5. NO BACKFILLING WHILE THE MARKET IS OPEN. Historical backfill is locked
   during live trading hours — a multi-minute, multi-thousand-row bulk
   fetch must not compete with the live path for FYERS rate limit or DB
   writes while the bot is trading. Detected faults are still reported
   during market hours; only the repair is deferred to after close.

Every action is recorded in _HISTORY and surfaced at /api/self-healing.
"""

import logging
import time
from collections import deque
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ── Guardrails ───────────────────────────────────────────────────────────────
# A full per-symbol backfill is minutes of API calls, so a symbol that keeps
# failing (delisted, no FYERS mapping) must not be retried every cycle.
_BACKFILL_COOLDOWN_SECONDS = 6 * 3600
# Cap per run so one bad day can't turn into dozens of simultaneous backfills.
_MAX_BACKFILLS_PER_RUN = 2
# Keep the last N actions for the dashboard/audit trail.
_HISTORY = deque(maxlen=100)

_last_backfill_attempt = {}   # symbol -> epoch seconds


def _record(kind, target, status, detail=""):
    entry = {
        "at": datetime.now(IST).isoformat(),
        "kind": kind,
        "target": target,
        "status": status,      # healed | failed | alert | skipped
        "detail": detail,
    }
    _HISTORY.appendleft(entry)
    lvl = logger.info if status in ("healed", "skipped") else logger.warning
    lvl("self-heal [%s] %s: %s %s", kind, target, status, detail)
    return entry


def history(limit=25):
    return list(_HISTORY)[:limit]


def _market_is_open():
    """
    Reuse fno_trader's canonical market-hours check rather than duplicating
    the NSE session definition (it reads the same configurable open/close
    times the trading loop uses, so the two can never drift apart).
    Fails CLOSED — if the check itself errors we assume the market is open
    and skip backfill, because a wrong "closed" is the harmful direction.
    """
    try:
        import fno_trader
        is_open, reason = fno_trader._is_market_open()
        return bool(is_open), reason
    except Exception as e:
        logger.warning("market-hours check failed, assuming OPEN (no backfill): %s", e)
        return True, "market-hours check unavailable"


# ── Healer 1: FYERS token ────────────────────────────────────────────────────

def check_token():
    """
    Detect an expired/expiring FYERS access token.

    NOT auto-fixable: FYERS disabled the refresh-token API for SEBI
    compliance, so renewal requires a human OAuth login. We still call
    refresh_if_needed() because it is harmless and will start working
    immediately if FYERS ever re-enables it — but the expected outcome is an
    alert, not a fix.
    """
    try:
        import fyers_auth
        exp = fyers_auth.token_expiry()
        if exp is None:
            return _record("token", "FYERS", "alert", "No token present — manual login required")

        remaining = (exp - datetime.now(IST)).total_seconds()
        if remaining > 1800:
            return None  # healthy, nothing to report

        if fyers_auth.refresh_if_needed():
            return _record("token", "FYERS", "healed", f"refreshed, now valid until {fyers_auth.token_expiry()}")

        mins = int(remaining / 60)
        state = "EXPIRED" if remaining <= 0 else f"expires in {mins}m"
        return _record(
            "token", "FYERS", "alert",
            f"{state} — refresh API disabled by FYERS (SEBI); manual login needed. "
            "Use the Reconnect button in Data Coverage.",
        )
    except Exception as e:
        return _record("token", "FYERS", "failed", f"{type(e).__name__}: {e}")


# ── Healer 2: symbols with no FYERS candle data ──────────────────────────────

def check_missing_symbols(dry_run=False):
    """
    Any watchlist symbol with zero fyers_candles rows gets backfilled.

    This is the gap that silently broke market_context for NIFTY/BANKNIFTY
    and dropped symbols out of the ML pipeline — the read path returns an
    empty frame and callers treat it as "no signal" rather than "no data",
    so without this check it stays invisible.
    """
    out = []
    try:
        import os
        import psycopg2
        conn = psycopg2.connect(os.getenv("DB_URL"), connect_timeout=5)
        try:
            cur = conn.cursor()
            # Universe = the ACTIVE watchlist (`stocks`), not stock_prices.
            #
            # stock_prices stopped receiving rows for newly-added symbols on
            # 2026-08-15 when the Groww weekly-candle fetch in
            # /api/watchlist/add was disabled (see the comment block there).
            # Sourcing this query from stock_prices therefore made a
            # newly-added symbol invisible to the very healer meant to
            # backfill it — it would never appear as "missing" and never get
            # repaired. That matters more now that watchlist-add defers its
            # own backfill during market hours and relies on this healer to
            # complete the job after close.
            #
            # `stocks` is the same table bot.get_active_watchlist() reads via
            # db_manager.get_all_stocks(), so this now matches what the rest
            # of the system considers "the watchlist".
            cur.execute("""
                SELECT s.symbol FROM stocks s
                WHERE s.is_active = true
                  AND s.symbol NOT IN (SELECT DISTINCT symbol FROM fyers_candles)
                ORDER BY 1
            """)
            missing = [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

        if not missing:
            return out

        # Backfill is locked during live market hours — report only.
        market_open, reason = _market_is_open()
        if market_open:
            out.append(_record(
                "missing_data", ", ".join(missing[:5]) + ("..." if len(missing) > 5 else ""),
                "alert",
                f"{len(missing)} symbol(s) missing FYERS data — backfill deferred, market is open ({reason})",
            ))
            return out

        now = time.time()
        healed = 0
        for sym in missing:
            if healed >= _MAX_BACKFILLS_PER_RUN:
                out.append(_record("missing_data", sym, "skipped",
                                   f"deferred to next run (cap {_MAX_BACKFILLS_PER_RUN}/run)"))
                continue

            last = _last_backfill_attempt.get(sym, 0)
            if now - last < _BACKFILL_COOLDOWN_SECONDS:
                mins = int((_BACKFILL_COOLDOWN_SECONDS - (now - last)) / 60)
                out.append(_record("missing_data", sym, "skipped", f"cooldown, retry in ~{mins}m"))
                continue

            if dry_run:
                out.append(_record("missing_data", sym, "alert", "would backfill (dry run)"))
                continue

            _last_backfill_attempt[sym] = now
            try:
                import fyers_historical_backfill
                res = fyers_historical_backfill.backfill_symbol(sym)
                status = (res or {}).get("status")
                if status == "ok":
                    healed += 1
                    out.append(_record("missing_data", sym, "healed", str((res or {}).get("resolutions", ""))))
                else:
                    out.append(_record("missing_data", sym, "failed",
                                       str((res or {}).get("reason", status))))
            except Exception as e:
                out.append(_record("missing_data", sym, "failed", f"{type(e).__name__}: {e}"))
    except Exception as e:
        out.append(_record("missing_data", "-", "failed", f"{type(e).__name__}: {e}"))
    return out


# ── Healer 3: stale intraday data ────────────────────────────────────────────

def check_stale_intraday(max_symbols=10):
    """
    Top up watchlist symbols whose newest 5-second bar is behind the rest.

    Bounded to `max_symbols` per run: ensure_recent() is individually cheap
    and self-throttling, but a market-wide gap shouldn't fan out into 67
    simultaneous API calls.
    """
    out = []
    try:
        import os
        import psycopg2
        conn = psycopg2.connect(os.getenv("DB_URL"), connect_timeout=5)
        try:
            cur = conn.cursor()
            # Compare each symbol's newest 5S bar against the newest across
            # all symbols — a symbol behind the leader is the actual signal.
            # Absolute wall-clock staleness would flag every symbol on a
            # weekend or holiday.
            cur.execute("""
                WITH latest AS (
                    SELECT max(ts) AS market_latest FROM fyers_candles WHERE resolution = '5S'
                )
                SELECT f.symbol, max(f.ts) AS sym_latest, l.market_latest
                FROM fyers_candles f
                CROSS JOIN latest l
                WHERE f.resolution = '5S'
                  AND f.symbol IN (SELECT DISTINCT symbol FROM stock_prices)
                GROUP BY f.symbol, l.market_latest
                HAVING max(f.ts) < l.market_latest - interval '1 day'
                ORDER BY 2 ASC
                LIMIT %s
            """, (max_symbols,))
            stale = cur.fetchall()
        finally:
            conn.close()

        if not stale:
            return out

        # Same lock as the full backfill: repairs wait for market close.
        market_open, reason = _market_is_open()
        if market_open:
            out.append(_record(
                "stale_data", f"{len(stale)} symbol(s)", "alert",
                f"stale FYERS data — top-up deferred, market is open ({reason})",
            ))
            return out

        import fyers_historical_backfill
        for sym, sym_latest, market_latest in stale:
            try:
                n = fyers_historical_backfill.ensure_recent(sym, ttl_seconds=0)
                if n:
                    out.append(_record("stale_data", sym, "healed", f"+{n} rows"))
                else:
                    out.append(_record("stale_data", sym, "alert",
                                       f"no new data (last {sym_latest}, market {market_latest})"))
            except Exception as e:
                out.append(_record("stale_data", sym, "failed", f"{type(e).__name__}: {e}"))
    except Exception as e:
        out.append(_record("stale_data", "-", "failed", f"{type(e).__name__}: {e}"))
    return out


# ── Entry point ──────────────────────────────────────────────────────────────

def run_all(dry_run=False):
    """
    Run every healer. Safe to call on a schedule; never raises.

    Token is checked first: if it's dead, the other healers cannot fetch
    anything anyway, so they're skipped rather than logging a cascade of
    failures that all trace back to one cause.
    """
    started = datetime.now(IST)
    actions = []

    tok = check_token()
    if tok:
        actions.append(tok)

    token_dead = bool(tok and tok["status"] == "alert" and "EXPIRED" in tok.get("detail", ""))
    if token_dead:
        actions.append(_record("skip", "data-healers", "skipped",
                               "FYERS token expired — data repair impossible until reconnected"))
    else:
        actions.extend(check_missing_symbols(dry_run=dry_run))
        actions.extend(check_stale_intraday())

    healed = sum(1 for a in actions if a["status"] == "healed")
    alerts = sum(1 for a in actions if a["status"] == "alert")
    failed = sum(1 for a in actions if a["status"] == "failed")
    if actions:
        logger.info("self-heal run: %d healed, %d alerts, %d failed (%.1fs)",
                    healed, alerts, failed, (datetime.now(IST) - started).total_seconds())
    return {"healed": healed, "alerts": alerts, "failed": failed, "actions": actions}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import json
    print(json.dumps(run_all(dry_run=True), indent=2))
