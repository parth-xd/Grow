"""
Thin FYERS Data API v3 wrapper — read-only market-data endpoints only.

No order-placement methods exist in this module by design: this is the
market-data-only side of the Groww -> FYERS migration (see docs/
FYERS_VS_GROWW_MARKET_DATA.md and docs/FYERS_MIGRATION_PHASE1.md). Endpoints,
params, and response shapes are taken verbatim from the FYERS v3 API
reference (Data Api section), not guessed.
"""

import logging
import requests

import fyers_auth

logger = logging.getLogger(__name__)

DATA_BASE = "https://api-t1.fyers.in/data"

# ═══════════════════════════════════════════════════════════════════════════
# THROTTLING, CACHING AND BACKOFF
# ═══════════════════════════════════════════════════════════════════════════
#
# Added after FYERS began returning HTTP 429 (a Cloudflare HTML page, which
# then surfaced downstream as "Expecting value: line 1 column 1" when parsed
# as JSON). Three independent problems, three fixes:
#
#   1. NO SHARING. Four scheduler tasks run every 5s — record_pnl,
#      cash_auto_trade, fno_auto_trade, auto_close_trades — plus the browser
#      poll. Each fetched the same symbols independently, so LT could be
#      requested five times in one second. A short-TTL cache collapses those
#      into one real call; nobody gets staler data than they can act on,
#      since the fastest consumer is itself on a 5s loop.
#
#   2. NO CEILING. Nothing capped outbound rate, so load scaled with however
#      many callers happened to exist. A token bucket makes the ceiling a
#      property of this module rather than an emergent accident.
#
#   3. 429 MADE ITSELF WORSE. resp.json() threw on the HTML error page, the
#      caller's next tick retried immediately, and hammering a rate limiter
#      is what extends the block. Now a 429 opens a cooldown that every
#      caller respects.
import json as _json
import os as _os
import threading as _threading
import time as _time

_DEFAULT_QUOTE_TTL = 2.0        # seconds

# FYERS's own documented Standard-tier cap is 10/sec, 200/min (Prime: 600/min).
# Exceeding the per-minute limit more than 3 times in a day gets the ACCOUNT
# BLOCKED FOR THE REST OF THAT DAY — not just throttled. See CLAUDE.md,
# "FYERS API rate limit".
#
# These are LITERAL FALLBACKS, used only when config_settings has no
# fyers.rate_per_sec / fyers.burst row (_cfg() checks DB, then env, then this).
# They previously defaulted to 5.0/sec = 300/min — 50% OVER the documented
# 200/min Standard cap — while the live DB override (2.5/sec, tuned to stay
# under it) carried a description literally saying "Keep under ~3.3/sec
# (200/min) to avoid 429 rate-limit blocks". Nothing seeds that row, so a
# fresh database, a restored backup missing config_settings, or a new
# environment would silently run at the unsafe literal default and could
# draw real 429s from FYERS regardless of anything this module's own
# backoff logic does — the limiter's OWN fallback was the thing capable of
# triggering the block it exists to prevent.
#
# A missing config must fail toward safe, not toward a value that can
# trigger an irreversible-for-the-day account block (the same "fail closed"
# principle as CLAUDE.md operational rule 8). Set to match the tuned-safe
# live values, not the old unsafe literal.
_DEFAULT_RATE = 2.5             # requests/sec sustained = 150/min, under the 200/min Standard cap
_DEFAULT_BURST = 5              # bucket capacity

_cache_lock = _threading.Lock()
_quote_cache = {}               # fy_symbol -> (payload_dict, monotonic_ts)

_bucket_lock = _threading.Lock()
_tokens = float(_DEFAULT_BURST)
_last_refill = _time.monotonic()

_cooldown_until = 0.0           # monotonic; set on 429
_cooldown_step = 0.0            # grows per consecutive 429


def _cfg(key, default):
    """config_settings first, env second, literal last. Never raises: a
    misconfigured limiter must not take market data down with it."""
    try:
        from db_manager import get_config
        v = get_config(key)
        if v not in (None, ""):
            return float(v)
    except Exception:
        pass
    try:
        v = _os.getenv(key.upper().replace(".", "_"))
        if v:
            return float(v)
    except Exception:
        pass
    return default


def quote_ttl():
    return _cfg("fyers.quote_ttl_seconds", _DEFAULT_QUOTE_TTL)


def _acquire_token(timeout=3.0):
    """Token bucket. Returns True if a request may proceed."""
    global _tokens, _last_refill
    rate = _cfg("fyers.rate_per_sec", _DEFAULT_RATE)
    burst = _cfg("fyers.burst", _DEFAULT_BURST)
    deadline = _time.monotonic() + timeout
    while True:
        with _bucket_lock:
            now = _time.monotonic()
            _tokens = min(burst, _tokens + (now - _last_refill) * rate)
            _last_refill = now
            if _tokens >= 1.0:
                _tokens -= 1.0
                return True
            need = (1.0 - _tokens) / rate if rate > 0 else timeout
        if _time.monotonic() + need > deadline:
            return False
        _time.sleep(min(need, 0.25))


def in_cooldown():
    """True while a 429 backoff is active. Callers can surface this rather
    than reporting a generic failure."""
    return _time.monotonic() < _cooldown_until


def cooldown_remaining():
    return max(0.0, _cooldown_until - _time.monotonic())


def _note_429():
    """
    Exponential backoff, capped. Doubling per consecutive 429 is the
    behaviour that was missing — the old code retried on the next 5s tick
    regardless, which is what kept the block alive.

    Locked (reusing _bucket_lock — this is the same shared rate-limit state,
    just two more fields of it) because this read-modify-write was not
    atomic. Measured live: 5 threads hit a real 429 within the same
    millisecond, each read the stale _cooldown_step and independently
    doubled it — 80s, then four threads all computing off THAT read
    simultaneously, landing at 160s/300s/300s/300s instead of one clean
    80->160->300 progression. The already-capped value being witnessed by
    later racers as float overhead, not a case, is what drove a single
    ordinary rate-limit straight to the 300s ceiling instead of a normal
    stepped backoff — turning a few seconds of throttling into a 5-minute
    outage on /api/live-price and every consumer behind fetch_live_price.
    """
    global _cooldown_until, _cooldown_step
    with _bucket_lock:
        _cooldown_step = 5.0 if _cooldown_step <= 0 else min(_cooldown_step * 2, 300.0)
        _cooldown_until = _time.monotonic() + _cooldown_step
        step = _cooldown_step
    logger.warning("FYERS 429 — backing off %.0fs", step)


def _note_ok():
    global _cooldown_step, _cooldown_until
    with _bucket_lock:
        _cooldown_step = 0.0
        _cooldown_until = 0.0


def _request(path, params, timeout=15):
    """
    Single outbound chokepoint: every FYERS call goes through here.

    Returns (status_code, payload_dict). NEVER raises on a non-JSON body —
    that was the original defect. A 429 returns an HTML page, and calling
    .json() on it threw a confusing parse error instead of "you are rate
    limited".
    """
    if in_cooldown():
        return 429, {"s": "error", "code": -429,
                     "message": f"rate-limit cooldown, {cooldown_remaining():.0f}s remaining"}
    if not _acquire_token():
        return 429, {"s": "error", "code": -429, "message": "local rate limit"}

    _COUNTER.bump()
    resp = requests.get(f"{DATA_BASE}/{path}", headers=_headers(), params=params, timeout=timeout)

    if resp.status_code == 429:
        _note_429()
        return 429, {"s": "error", "code": -429, "message": "FYERS rate limit (HTTP 429)"}

    try:
        payload = resp.json()
    except _json.JSONDecodeError:
        body = (resp.text or "")[:120].replace("\n", " ")
        logger.warning("FYERS %s returned non-JSON (HTTP %s): %s", path, resp.status_code, body)
        return resp.status_code, {"s": "error", "code": resp.status_code,
                                  "message": f"non-JSON response: {body}"}
    if resp.status_code == 200:
        _note_ok()
    return resp.status_code, payload


class _ReqCounter:
    """Counts real outbound calls so the cache's effect is measurable rather
    than asserted."""
    def __init__(self):
        self._n = 0
        self._lock = _threading.Lock()

    def bump(self):
        with self._lock:
            self._n += 1

    def read(self):
        with self._lock:
            return self._n

    def reset(self):
        with self._lock:
            self._n = 0


_COUNTER = _ReqCounter()


def request_count():
    return _COUNTER.read()


def reset_request_count():
    _COUNTER.reset()


def cache_stats():
    with _cache_lock:
        return {"entries": len(_quote_cache), "ttl": quote_ttl(),
                "in_cooldown": in_cooldown(), "cooldown_s": round(cooldown_remaining(), 1)}



def _headers():
    return {"Authorization": fyers_auth.auth_header()}


def get_historical_candles(symbol, resolution, range_from, range_to, date_format=1, cont_flag=0, oi_flag=0):
    """
    symbol: FYERS format, e.g. "NSE:RELIANCE-EQ"
    resolution: "D"/"1D", "1".."240" (minutes), "5S".."45S" (seconds), "1W", "1M"
    range_from/range_to: "YYYY-MM-DD" if date_format=1, else epoch seconds if date_format=0
    Returns FYERS's raw response dict: {"s": "ok", "candles": [[epoch,o,h,l,c,v], ...]}
    """
    return _request("history", {
        "symbol": symbol,
        "resolution": resolution,
        "date_format": date_format,
        "range_from": range_from,
        "range_to": range_to,
        "cont_flag": cont_flag,
        "oi_flag": oi_flag,
    }, timeout=20)


def get_quotes(symbols, use_cache=True):
    """
    symbols: list of up to 50 FYERS-format symbols. Returns (status, payload).

    Served from a short-TTL cache. Only symbols whose cached entry has expired
    are actually requested, and they go out as ONE batched call — so four
    5-second scheduler tasks asking for overlapping symbols produce one
    network request between them instead of four.

    The response is reassembled to include every requested symbol, cached or
    fresh, so callers cannot tell the difference and need no changes.

    use_cache=False forces a live read (backfill//diagnostics).
    """
    symbols = list(symbols)
    if not use_cache:
        return _request("quotes", {"symbols": ",".join(symbols)})

    ttl = quote_ttl()
    now = _time.monotonic()
    fresh, stale = {}, []
    with _cache_lock:
        for sym in symbols:
            hit = _quote_cache.get(sym)
            if hit and (now - hit[1]) < ttl:
                fresh[sym] = hit[0]
            else:
                stale.append(sym)

    status = 200
    if stale:
        status, payload = _request("quotes", {"symbols": ",".join(stale)})
        if status == 200 and isinstance(payload, dict) and payload.get("s") == "ok":
            ts = _time.monotonic()
            with _cache_lock:
                for row in (payload.get("d") or []):
                    n = row.get("n")
                    if n:
                        _quote_cache[n] = (row, ts)
                        fresh[n] = row
        elif not fresh:
            # Nothing cached to fall back on — surface the real error.
            return status, payload

    return status, {"s": "ok", "d": [fresh[k] for k in symbols if k in fresh]}


def get_ltp(fy_symbol):
    """Last traded price for one symbol, via the shared cache. None if absent."""
    status, payload = get_quotes([fy_symbol])
    if status != 200 or not isinstance(payload, dict):
        return None
    for row in (payload.get("d") or []):
        v = row.get("v") or {}
        if v.get("lp") is not None:
            return float(v["lp"])
    return None


def get_market_depth(symbol, ohlcv_flag=1):
    """symbol: single FYERS-format symbol (max 1 per request per docs). Returns raw response dict."""
    return _request("depth", {"symbol": symbol, "ohlcv_flag": ohlcv_flag})


def get_option_chain(symbol, strikecount=5, greeks=1):
    """symbol: underlying FYERS-format symbol. strikecount max 50 per docs. Returns raw response dict."""
    return _request("options-chain-v3", {"symbol": symbol, "strikecount": strikecount, "greeks": greeks})


def get_market_status():
    return _request("marketStatus", {}, timeout=10)
