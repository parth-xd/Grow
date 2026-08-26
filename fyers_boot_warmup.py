"""
Boot-phase FYERS warm-up coordinator.

WHY THIS EXISTS
---------------
`fyers_historical_backfill._last_freshness_check` is a plain in-process dict
backing `ensure_recent()`'s per-symbol 300s throttle. It resets to empty on
every process restart. `bot.fetch_historical()` calls `ensure_recent()` on
effectively every prediction, and `bot.auto_trade()` -> `scan_watchlist()`
fans out over the whole ~73-symbol watchlist with 6 worker threads.

So the first watchlist pass after any restart fires ~73 mutually
uncoordinated FYERS requests. That draws real HTTP 429s from FYERS, which
trip `fyers_client`'s exponential backoff, which blocks live prices for
minutes. Measured live: repeated `FYERS 429 - backing off` escalations to the
300s cap, with /api/live-price returning HTTP 500 the whole time.

Two earlier fixes in fyers_client.py (a lock around the cooldown
read-modify-write, and a safe literal rate fallback) made the *arithmetic* of
backing off correct. Neither addressed the burst itself - a restart still
reproduced it. This module is the burst fix.

WHAT IT DOES
------------
On startup, walk the watchlist ONCE, sequentially, at a deliberate pace, and
populate the shared freshness cache. Because that cache is keyed by SYMBOL
rather than by caller, warming a symbol here satisfies every later caller of
that symbol for the remaining TTL - so this does not need to intercept call
sites, only to get there first in an orderly way.

While that runs, bulk/recurring FYERS work is paused (see scheduler.py's
guards). Money-path work - open-position P&L, stop-loss and trailing-stop
evaluation - is deliberately NEVER paused; see the note on that below.

DESIGN NOTES
------------
- Concurrency is 1, on purpose. `scan_watchlist()` uses 6 workers; this uses
  one, plus extra inter-symbol pacing, so it stays well under the shared
  token bucket's ceiling and leaves headroom for live quote calls that share
  that same bucket.

- `_active` is True from IMPORT time, not from when `run()` starts. If it
  defaulted to False, a scheduler tick landing between import and thread
  start would see "not warming up" and fire the very burst this prevents.

- `_active` is cleared in a `finally:`, so it cannot get stuck True if
  `run()` raises. A permanently-True flag would silently pause auto-analysis,
  self-healing and new-entry scanning forever - a much worse failure than the
  one being fixed. Same "must not break the caller" discipline as
  `ensure_recent()` and `training_progress._locked()`.

- The timeout is a hard safety valve, not a target. On breach it stops
  issuing requests and un-pauses everything regardless of how much is left
  cold; the remainder is picked up lazily by the first real caller, which is
  exactly today's existing behaviour - just no longer 73 at once.

- Nothing here is persisted. The cache's job is intra-process throttling
  inside one TTL window; the underlying candles already persist in Postgres,
  so a cold cache means "re-check freshness once", not "stale data". Durable
  shared mutable state would need its own concurrency story, which is the
  exact class of bug already fixed in fyers_client.py this session.

MONEY-PATH GUARANTEE
--------------------
This module never pauses `record_pnl`, `auto_close_trades`, `fno_auto_trade`,
or `cash_auto_trade`'s trailing-stop management. Only bulk scanning pauses.
Worst case for an open position is losing a race for a bucket token against
this (slow, single-consumer) pass - bounded by `_acquire_token`'s existing 3s
timeout, after which the caller's existing catch-and-skip-one-cycle path
handles it. That is ~1 missed 5s tick, self-healing on the next.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

# True from import time - see DESIGN NOTES. Guards read this via is_active().
_active = True

_state_lock = threading.Lock()
_state = {
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "done": 0,
    "warmed": 0,      # symbols where ensure_recent actually stored new rows
    "current": None,
    "timed_out": False,
    "enabled": True,
    "error": None,
    "token_ok": None,          # None = not checked yet
    "token_detail": None,
    "aborted_no_token": False,
}

# Defaults used when the config_settings row is absent (fresh DB, restored
# backup, new environment). Mirrors the fyers.rate_per_sec precedent: the
# literal fallback must itself be safe, never a value that reintroduces the
# problem.
_DEFAULT_ENABLED = "true"
_DEFAULT_TIMEOUT_SECONDS = 150.0
_DEFAULT_EXTRA_PACE_SECONDS = 0.3

# How long to wait for a valid FYERS token before giving up and deferring the
# warm-up entirely. Bounded on purpose: if auth is genuinely broken (expired
# token needing a human OAuth login), waiting longer does not help and would
# just keep bulk tasks paused.
_DEFAULT_TOKEN_WAIT_SECONDS = 45.0
_TOKEN_POLL_INTERVAL = 1.5


def _cfg(key, default):
    """config_settings first, literal fallback second. Never raises."""
    try:
        from db_manager import get_config
        v = get_config(key)
        if v not in (None, ""):
            return v
    except Exception:
        pass
    return default


def _cfg_float(key, default):
    try:
        return float(_cfg(key, default))
    except (TypeError, ValueError):
        return float(default)


def _token_is_valid():
    """
    True if a FYERS access token exists and has not expired.

    Uses fyers_auth.token_expiry(), which decodes the JWT's own `exp` claim
    locally — no network call, so a readiness check can never itself consume
    a request or trip the rate limiter.

    Re-reads .env each attempt: the token is written to .env by the login
    flow / refresh task, and this process may have started before that
    happened. Without the reload we would keep seeing the stale os.environ
    value captured at import time.
    """
    try:
        from datetime import datetime, timezone, timedelta
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        except Exception:
            pass
        import fyers_auth
        exp = fyers_auth.token_expiry()
        if exp is None:
            return False, "no token"
        remaining = (exp - datetime.now(timezone(timedelta(hours=5, minutes=30)))).total_seconds()
        if remaining <= 0:
            return False, f"token expired {abs(int(remaining))}s ago"
        return True, f"valid, {int(remaining)}s remaining"
    except Exception as e:
        return False, f"token check failed: {e}"


def _wait_for_token(max_wait):
    """
    Block until the token is valid, or until max_wait elapses.

    WHY THIS EXISTS
    ---------------
    The warm-up thread is started from app.py BEFORE start_scheduler(), so its
    _active flag is set before the first scheduler tick can evaluate the bulk
    -task guards. That ordering is deliberate — but it also means the warm-up
    can begin before token_refresh/fyers_token_refresh (initial_delay 0 and 1)
    have run.

    Measured consequence on the 2026-08-25 08:56 restart: warm-up started at
    08:57:02 and its first 7 FYERS calls came back "Could not authenticate the
    user" / "Please provide valid token" (code -15). FYERS rate-limits failed
    -auth requests too, so a 429 landed at 08:57:08 and the backoff escalated
    to the 300s cap — live prices were down through 09:12. Every one of those
    73 warm-up requests was wasted AND actively harmful.

    Waiting costs nothing (the check is a local JWT decode) and removes the
    entire failure mode.
    """
    deadline = time.time() + max_wait
    attempts = 0
    while True:
        ok, detail = _token_is_valid()
        if ok:
            if attempts:
                logger.info("FYERS boot warm-up: token ready after %.1fs (%s)",
                            max_wait - (deadline - time.time()), detail)
            return True, detail
        attempts += 1
        if time.time() >= deadline:
            return False, detail
        time.sleep(_TOKEN_POLL_INTERVAL)


def is_active():
    """
    True while the boot warm-up is still running.

    Read by scheduler.py's bulk-task guards. Deliberately a plain bool read:
    this is a single-process app, the value is written exactly twice (import,
    and once in run()'s finally), and a torn read is not possible for a bool
    in CPython. No lock needed on the hot path.
    """
    return _active


def status():
    """Snapshot for /api/data-health. Never raises."""
    with _state_lock:
        s = dict(_state)
    s["active"] = _active
    if s["started_at"] and not s["finished_at"]:
        s["elapsed_seconds"] = round(time.time() - s["started_at"], 1)
    elif s["started_at"] and s["finished_at"]:
        s["elapsed_seconds"] = round(s["finished_at"] - s["started_at"], 1)
    else:
        s["elapsed_seconds"] = 0
    return s


def _set(**kw):
    with _state_lock:
        _state.update(kw)


def run(symbols=None):
    """
    Warm the FYERS freshness cache for every watchlist symbol, once, paced.

    Safe to call exactly once per process, from a daemon thread. Never
    raises - a warm-up failure must not take down startup, and must not
    leave bulk work paused.
    """
    global _active
    try:
        enabled = str(_cfg("fyers.boot_warmup_enabled", _DEFAULT_ENABLED)).lower() == "true"
        _set(enabled=enabled)
        if not enabled:
            # Kill switch: restores pre-coordinator behaviour with no code
            # change, for a fast rollback if this ever misbehaves.
            logger.info("FYERS boot warm-up disabled by config - skipping")
            return

        timeout = _cfg_float("fyers.boot_warmup_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        pace = _cfg_float("fyers.boot_warmup_extra_pace_seconds", _DEFAULT_EXTRA_PACE_SECONDS)
        token_wait = _cfg_float("fyers.boot_warmup_token_wait_seconds", _DEFAULT_TOKEN_WAIT_SECONDS)

        # Do not send a single request until auth is confirmed. An invalid
        # token does not just fail — FYERS rate-limits the failed attempts,
        # so a bad-token warm-up actively causes the outage it exists to
        # prevent (see _wait_for_token's docstring for the measured case).
        token_ok, token_detail = _wait_for_token(token_wait)
        _set(token_ok=token_ok, token_detail=token_detail)
        if not token_ok:
            # Abort rather than defer-and-retry: if the token is missing or
            # expired, it needs a human OAuth login (FYERS disabled unattended
            # refresh for SEBI compliance), which no amount of waiting fixes.
            # Symbols warm lazily on first real use once auth is restored.
            logger.warning(
                "FYERS boot warm-up ABORTED — no valid token after %.0fs (%s). "
                "Sending requests now would be rejected AND rate-limited. "
                "Symbols will warm lazily once FYERS auth is restored.",
                token_wait, token_detail,
            )
            _set(aborted_no_token=True)
            return

        if symbols is None:
            try:
                import bot
                symbols = list(bot.get_active_watchlist())
            except Exception as e:
                logger.warning("FYERS boot warm-up: could not load watchlist: %s", e)
                _set(error=f"watchlist load failed: {e}")
                return

        symbols = [s for s in symbols if s]
        started = time.time()
        _set(started_at=started, total=len(symbols), done=0, warmed=0,
             timed_out=False, error=None)
        logger.info("FYERS boot warm-up: warming %d symbol(s), timeout %.0fs, pace %.2fs",
                    len(symbols), timeout, pace)

        import fyers_historical_backfill

        warmed = 0
        for i, sym in enumerate(symbols):
            if time.time() - started > timeout:
                remaining = symbols[i:]
                _set(timed_out=True)
                logger.warning(
                    "FYERS boot warm-up: timeout after %.0fs with %d symbol(s) still cold "
                    "(%s%s) - resuming normal operation; these warm lazily on first use",
                    timeout, len(remaining), ", ".join(remaining[:5]),
                    "..." if len(remaining) > 5 else "",
                )
                break

            _set(current=sym)
            try:
                # ensure_recent() is called unchanged, as a black box. It does
                # its own TTL check and its own storage; all this adds is
                # ordering and pacing.
                n = fyers_historical_backfill.ensure_recent(sym)
                if n:
                    warmed += 1
            except Exception as e:
                # Per-symbol failures are expected and survivable (unmapped
                # ticker, no FYERS data yet). Keep going - one bad symbol
                # must not leave the rest of the watchlist cold.
                logger.debug("FYERS boot warm-up: %s failed: %s", sym, e)

            _set(done=i + 1, warmed=warmed)

            if pace > 0:
                time.sleep(pace)

    except Exception as e:
        logger.warning("FYERS boot warm-up failed: %s", e)
        _set(error=str(e))
    finally:
        # ALWAYS clear, whatever happened above. A stuck-True flag would
        # pause auto-analysis, self-healing and new-entry scanning for the
        # life of the process.
        _active = False
        _set(finished_at=time.time(), current=None)
        s = status()
        logger.info(
            "FYERS boot warm-up complete in %.1fs - %d/%d symbol(s) checked, "
            "%d refreshed%s. Bulk tasks resuming.",
            s.get("elapsed_seconds", 0), s.get("done", 0), s.get("total", 0),
            s.get("warmed", 0), " (TIMED OUT)" if s.get("timed_out") else "",
        )


def start_in_background(symbols=None):
    """
    Launch run() on a daemon thread. Returns the thread, or None if it could
    not start - in which case _active is cleared so nothing stays paused.
    """
    global _active
    try:
        t = threading.Thread(target=run, args=(symbols,), daemon=True,
                             name="fyers-boot-warmup")
        t.start()
        return t
    except Exception as e:
        logger.warning("FYERS boot warm-up thread failed to start: %s", e)
        _active = False
        _set(error=f"thread start failed: {e}", finished_at=time.time())
        return None
