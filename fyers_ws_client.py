"""
FYERS API v3 Market Data WebSocket — latest live state per symbol.

INERT BY DESIGN
---------------
Nothing in the trading path reads this module. `fetch_live_price()`, paper
trading, order entry/exit and every scheduler task are untouched: they still
use the REST quote path. This module only maintains state and reports health,
so it can be proven in production before anything trades on it.

WHAT IT REUSES (nothing here is new infrastructure)
---------------------------------------------------
- Universe:  PORTFOLIO-SCOPED — whatever holdings are pushed in via
             set_symbols(). It prices what is actually held, nothing else,
             and grows as positions are added. Deliberately not polled: the
             only source of holdings is Groww, and each call there
             re-downloads a ~19MB instrument file.
- Mapping:   `master_ticker_table.fyers_websocket_symbol`, already populated
             for 2,465 symbols and byte-identical to the historical symbol.
             Batched in ONE query, mirroring `topup_daily()`'s idiom rather
             than querying per symbol (CLAUDE.md standard #1).
- Auth:      `fyers_auth.auth_header()` returns "APP_ID:ACCESS_TOKEN", which
             is exactly what FyersDataSocket wants — it does
             `access_token.split(":")[1]` internally (data_ws.py:32).
- Expiry:    `fyers_auth.token_expiry()` — local JWT decode, no API call.
- Config:    the `_cfg` DB -> env -> literal pattern from fyers_client.py.
- Thread:    the daemon-thread idiom from fyers_boot_warmup.start_in_background.

RATE LIMITER
------------
Deliberately NOT routed through `fyers_client._acquire_token()`. That bucket
meters REST calls against FYERS's 200/min cap, and the watchlist scan already
saturates it. A WebSocket is one long-lived connection, not metered requests;
borrowing REST tokens for it would starve live prices. Our reconnect backoff
is what bounds connection attempts.

RECONNECTION
------------
The SDK reconnects on its own but gives UP: max_reconnect_attempts =
min(reconnect_retry, 50), with the delay growing 5s every 5 attempts
(data_ws.py:1602-1616). So the SDK handles blips, and this module's supervisor
handles the case where the SDK has exhausted itself — recreating the socket
under our own capped exponential backoff. That is the division of labour;
we do not reimplement what the SDK already does.

EXPIRED TOKEN (documented assumption)
-------------------------------------
FYERS access tokens die at 06:00 IST and unattended refresh is disabled for
SEBI compliance, so a dead token is a DAILY certainty, not an edge case. The
simplest safe behaviour, chosen deliberately: when the token is absent or
expired we do not connect at all, and we do not retry on the connection
backoff. We re-check the token every `fyers.ws_token_recheck_seconds` — a
local JWT decode, no network — and connect once it becomes valid again. So a
dead credential produces zero connection attempts, and the socket comes up on
its own after the daily manual login without a restart.

FRESHNESS
---------
Age is measured from FYERS's own `exch_feed_time` (epoch seconds), not from
local arrival time, per requirement. This assumes the host clock is roughly
NTP-correct; it is IST-correct on this machine. Outside market hours no ticks
arrive, so symbols correctly read STALE — that is honest, not a fault, and the
connection is deliberately kept open anyway.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

# ── Freshness states (exactly these three) ───────────────────────────────────
NEVER_RECEIVED = "NEVER_RECEIVED"
FRESH = "FRESH"
STALE = "STALE"

# Literal fallbacks, used only when config_settings has no row.
_DEFAULT_ENABLED = "true"
_DEFAULT_FRESHNESS_SECONDS = 2.0
_DEFAULT_RECONNECT_RETRY = 10        # handed to the SDK's own reconnect
_DEFAULT_BACKOFF_START_SECONDS = 5.0
_DEFAULT_BACKOFF_MAX_SECONDS = 300.0
_DEFAULT_TOKEN_RECHECK_SECONDS = 60.0
_DEFAULT_STALL_SECONDS = 60.0        # no tick this long while open == dead feed

# Full SymbolUpdate fields the SDK emits (map.json "data_val"), minus the ones
# it pops for equities (OI/Yhigh/Ylow). `ch`/`chp` are computed by the SDK.
_TICK_FIELDS = (
    "ltp", "vol_traded_today", "last_traded_time", "exch_feed_time",
    "bid_size", "ask_size", "bid_price", "ask_price", "last_traded_qty",
    "tot_buy_qty", "tot_sell_qty", "avg_trade_price",
    "low_price", "high_price", "open_price", "prev_close_price",
    "lower_ckt", "upper_ckt", "ch", "chp", "type",
)

_lock = threading.RLock()
_ticks = {}          # nse_symbol -> latest tick dict (LATEST ONLY, no history)
_fy_to_nse = {}      # fyers ws symbol -> nse symbol
_subscribed = set()  # fyers ws symbols currently subscribed
_socket = None
_active = False

_status = {
    "enabled": None,
    "connected": False,
    "connected_at": None,
    "connect_attempts": 0,
    "reconnects": 0,
    "last_tick_at": None,        # epoch seconds, local
    "last_tick_symbol": None,
    "last_error": None,
    "token_error": None,
    "started_at": None,
}


def _cfg(key, default):
    """config_settings first, env second, literal last. Never raises."""
    try:
        from db_manager import get_config
        val = get_config(key)
        if val is not None and str(val).strip() != "":
            return val
    except Exception:
        pass
    import os
    return os.getenv(key.replace(".", "_").upper(), default)


def _cfg_float(key, default):
    try:
        return float(_cfg(key, default))
    except (TypeError, ValueError):
        return default


def _enabled():
    return str(_cfg("fyers.ws_enabled", _DEFAULT_ENABLED)).strip().lower() == "true"


# ── Public read API (nothing in the trading path calls these yet) ────────────

def freshness(symbol):
    """NEVER_RECEIVED / FRESH / STALE for one symbol, by FYERS tick time."""
    threshold = _cfg_float("fyers.ws_freshness_seconds", _DEFAULT_FRESHNESS_SECONDS)
    with _lock:
        tick = _ticks.get(symbol)
    if not tick:
        return NEVER_RECEIVED
    ts = tick.get("exch_feed_time") or tick.get("last_traded_time")
    if not ts:
        return NEVER_RECEIVED
    return FRESH if (time.time() - float(ts)) <= threshold else STALE


def get_tick(symbol):
    """Latest structured state for a symbol, or None. A copy, so callers
    cannot mutate the shared store."""
    with _lock:
        tick = _ticks.get(symbol)
        return dict(tick) if tick else None


def get_price(symbol):
    """
    Last traded price, but ONLY when FRESH — the TRADING-SAFE accessor.

    Returns None for a missing or stale symbol, deliberately with no REST
    fallback, so a caller can never trade on a stale WebSocket price. Use this
    anywhere a decision risks money. For display, use get_last_price().
    """
    if freshness(symbol) != FRESH:
        return None
    tick = get_tick(symbol)
    return tick.get("ltp") if tick else None


def get_last_price(symbol):
    """
    Last price this feed ever received, regardless of age — the DISPLAY
    accessor. None only if no tick has EVER arrived for the symbol.

    Separate from get_price() on purpose. The 2-second freshness rule exists
    so trading logic cannot act on a stale quote; applying it to a display
    would blank a perfectly good last price every time an illiquid holding
    simply had not traded in the last two seconds. A real last-traded price is
    the honest thing to show; a blank or a substituted cost price is not.

    Still NO REST fallback: if the feed never carried this symbol, callers get
    None and should render "unavailable" rather than sourcing it elsewhere.
    """
    tick = get_tick(symbol)
    return tick.get("ltp") if tick else None


def status():
    """Health snapshot for the dashboard. Never raises."""
    try:
        threshold = _cfg_float("fyers.ws_freshness_seconds", _DEFAULT_FRESHNESS_SECONDS)
        now = time.time()
        fresh, stale, never = [], [], []
        with _lock:
            subscribed_nse = sorted(_fy_to_nse.values())
            snapshot = {s: _ticks.get(s) for s in subscribed_nse}
            st = dict(_status)
            subscribed_n = len(_subscribed)
        for sym in subscribed_nse:
            tick = snapshot.get(sym)
            ts = (tick or {}).get("exch_feed_time") or (tick or {}).get("last_traded_time")
            if not tick or not ts:
                never.append(sym)
            elif (now - float(ts)) <= threshold:
                fresh.append(sym)
            else:
                stale.append(sym)
        st.update({
            "enabled": _enabled(),
            # Symbols the socket has actually SUBSCRIBED, not merely the size
            # of the symbol map. Reporting the map made a dead feed look
            # healthy — "66 subscribed, 0 receiving" while nothing was even
            # subscribed. `tracked_count` keeps the map size visible.
            "subscribed_count": subscribed_n,
            "tracked_count": len(subscribed_nse),
            "receiving_count": len(fresh),
            "stale_count": len(stale),
            "never_received_count": len(never),
            "stale_symbols": stale[:20],
            "never_received_symbols": never[:20],
            "freshness_threshold_seconds": threshold,
            "last_tick_age_seconds": (
                round(now - st["last_tick_at"], 2) if st.get("last_tick_at") else None
            ),
        })
        return st
    except Exception as e:
        return {"enabled": False, "connected": False, "error": str(e)}


# ── Symbol universe (one batched query — no N+1, no new watchlist) ───────────

def _load_symbol_map(symbols):
    """
    {fyers_ws_symbol: nse_symbol} for the given NSE tickers.

    One batched lookup, never per symbol. Tickers with no resolved FYERS
    mapping are simply absent from the result — the caller can compare sizes
    to see which were dropped.
    """
    from db_manager import MasterTicker, get_db

    symbols = [s for s in (symbols or []) if s]
    if not symbols:
        return {}
    with get_db().Session() as session:
        rows = (session.query(MasterTicker)
                .filter(MasterTicker.nse_ticker.in_(symbols),
                        MasterTicker.fyers_resolution_status == "resolved")
                .all())
    return {r.fyers_websocket_symbol: r.nse_ticker
            for r in rows if r.fyers_websocket_symbol}


def set_symbols(symbols):
    """
    Set the symbols this feed should carry, and sync subscriptions to match.

    The feed is PORTFOLIO-SCOPED: it prices what is actually held, nothing
    else. Callers push the current holdings here rather than the module
    polling for them, because the only source of holdings is Groww's API and
    every call to it re-downloads a ~19MB instrument file — polling that on a
    timer would cost gigabytes a day. Portfolio analysis already fetches
    holdings, so it passes them on for free.

    Safe to call repeatedly with the same list: only the delta is subscribed
    or unsubscribed. Returns the number of symbols now tracked.
    """
    new_map = _load_symbol_map(symbols)
    with _lock:
        old_map = dict(_fy_to_nse)
        old, new = set(old_map), set(new_map)
        _fy_to_nse.clear()
        _fy_to_nse.update(new_map)
        for fy in (old - new):                 # dropped from the portfolio
            nse = old_map.get(fy)
            if nse:
                _ticks.pop(nse, None)
        sock, connected = _socket, _status["connected"]
    added, removed = list(new - old), list(old - new)
    if sock and connected:
        if added:
            try:
                sock.subscribe(symbols=added, data_type="SymbolUpdate")
                with _lock:
                    _subscribed.update(added)
                logger.info("FYERS WS +%d symbol(s) from portfolio", len(added))
            except Exception as e:
                logger.warning("FYERS WS subscribe failed: %s", e)
        if removed:
            try:
                sock.unsubscribe(symbols=removed, data_type="SymbolUpdate")
                with _lock:
                    _subscribed.difference_update(removed)
                logger.info("FYERS WS -%d symbol(s) no longer held", len(removed))
            except Exception as e:
                logger.warning("FYERS WS unsubscribe failed: %s", e)
    return len(new_map)


# ── SDK callbacks ────────────────────────────────────────────────────────────

def _on_message(msg):
    """
    Store the latest state for one symbol. Wrapped so that a single malformed
    or unmappable message can never kill the socket or affect other symbols.
    """
    try:
        if not isinstance(msg, dict):
            return
        fy_symbol = msg.get("symbol")
        if not fy_symbol:
            return
        with _lock:
            nse = _fy_to_nse.get(fy_symbol)
        if not nse:
            return                      # not ours (e.g. just unsubscribed)
        tick = {k: msg[k] for k in _TICK_FIELDS if k in msg}
        tick["symbol"] = nse
        tick["fyers_symbol"] = fy_symbol
        tick["received_at"] = time.time()
        with _lock:
            _ticks[nse] = tick          # latest only — no tick history
            _status["last_tick_at"] = tick["received_at"]
            _status["last_tick_symbol"] = nse
    except Exception as e:
        logger.debug("FYERS WS message parse failed: %s", e)


def _on_connect():
    logger.info("FYERS WS connected")
    with _lock:
        _status["connected"] = True
        _status["connected_at"] = time.time()
        _status["last_error"] = None
    _resubscribe_all()


def _on_close(msg=None):
    logger.warning("FYERS WS closed: %s", msg)
    with _lock:
        _status["connected"] = False
        _status["connected_at"] = None
        _subscribed.clear()


def _on_error(msg=None):
    logger.warning("FYERS WS error: %s", msg)
    with _lock:
        _status["connected"] = False
        _status["last_error"] = str(msg)[:300]


def _resubscribe_all():
    """Subscribe the full current map. Called on every (re)connect, so a
    reconnect always restores subscriptions."""
    with _lock:
        wanted = list(_fy_to_nse.keys())
        sock = _socket
    if not sock or not wanted:
        return
    try:
        sock.subscribe(symbols=wanted, data_type="SymbolUpdate")
        with _lock:
            _subscribed.clear()
            _subscribed.update(wanted)
        logger.info("FYERS WS subscribed %d symbol(s)", len(wanted))
    except Exception as e:
        logger.warning("FYERS WS subscribe failed: %s", e)


# ── Supervisor ───────────────────────────────────────────────────────────────

def _stalled():
    """
    True when we believe we are connected but no tick has arrived for
    `fyers.ws_stall_seconds` WHILE THE MARKET IS OPEN.

    Why this exists rather than trusting the SDK: measured on SDK 3.1.17,
    neither available liveness signal is reliable. `is_connected()` only
    checks that the socket OBJECT exists, so it returns True after a close;
    and `on_close` fired on one forced-drop run but not on an identical
    second run, so the callback alone is racy. Tick recency is the only
    signal that actually means "data is flowing".

    Gated on market hours because silence outside them is correct, not a
    fault — the connection is deliberately kept open all day.
    """
    try:
        stall = _cfg_float("fyers.ws_stall_seconds", _DEFAULT_STALL_SECONDS)
        if stall <= 0:
            return False
        from fno_trader import _is_market_open
        is_open, _ = _is_market_open()
        if not is_open:
            return False
        with _lock:
            last = _status.get("last_tick_at")
            since = _status.get("connected_at")
            subscribed = len(_fy_to_nse)
        if not subscribed or not since:
            return False
        # Measure from the LATER of "connected" and "last tick", so a fresh
        # connection gets a full stall window to produce its first tick
        # instead of being torn down immediately in a rebuild loop.
        return (time.time() - max(since, last or 0)) > stall
    except Exception:
        return False        # never let the watchdog itself break the loop


def _force_rebuild():
    """Drop the current socket so the supervisor reconnects on the next pass."""
    global _socket
    with _lock:
        sock = _socket
        _socket = None
        _status["connected"] = False
        _status["connected_at"] = None
        # Counted here rather than on the next connect: _force_rebuild clears
        # _socket, so the supervisor's "did we have a socket before?" test
        # would otherwise never see one and the count would stay 0.
        _status["reconnects"] += 1
        _subscribed.clear()
    if sock:
        try:
            sock.close_connection()
        except Exception:
            pass


def _token_ok():
    """(ok, reason). Local JWT decode only — never a network call."""
    try:
        import fyers_auth
        exp = fyers_auth.token_expiry()
        if exp is None:
            return False, "no FYERS access token"
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        if exp <= now:
            return False, f"token expired at {exp.isoformat()}"
        return True, ""
    except Exception as e:
        return False, f"token check failed: {e}"


def _connect_once():
    """Build and connect a socket. Returns True if connect() was issued."""
    global _socket
    import fyers_auth
    from fyers_apiv3.FyersWebsocket import data_ws

    # Close the previous socket FIRST. Without this every reconnect leaked a
    # live FyersDataSocket: the old object kept its own internal reconnect
    # loop running and its callbacks kept firing into the shared _status, so
    # two instances fought over the same state and the module reported
    # "connected, 66 subscribed" while receiving nothing. Observed directly —
    # the process held two open handles to fyersDataSocket.log, one per
    # orphaned SDK instance.
    with _lock:
        old = _socket
        _socket = None
    if old is not None:
        try:
            old.close_connection()
        except Exception as e:
            logger.debug("FYERS WS: closing previous socket failed: %s", e)

    retry = int(_cfg_float("fyers.ws_reconnect_retry", _DEFAULT_RECONNECT_RETRY))
    sock = data_ws.FyersDataSocket(
        access_token=fyers_auth.auth_header(),   # "APP_ID:ACCESS_TOKEN"
        litemode=False,                          # FULL SymbolUpdate
        write_to_file=False,
        reconnect=True,                          # SDK handles blips
        reconnect_retry=retry,
        on_connect=_on_connect,
        on_close=_on_close,
        on_error=_on_error,
        on_message=_on_message,
    )
    with _lock:
        _socket = sock
        _status["connect_attempts"] += 1
    sock.connect()                               # non-blocking
    return True


def _run():
    """Supervisor loop: token gate -> connect -> watch health -> reconnect."""
    global _active
    backoff = _cfg_float("fyers.ws_backoff_start_seconds", _DEFAULT_BACKOFF_START_SECONDS)
    backoff_max = _cfg_float("fyers.ws_backoff_max_seconds", _DEFAULT_BACKOFF_MAX_SECONDS)
    token_recheck = _cfg_float("fyers.ws_token_recheck_seconds", _DEFAULT_TOKEN_RECHECK_SECONDS)
    backoff_cur = backoff

    with _lock:
        _status["started_at"] = time.time()

    while _active:
        try:
            ok, reason = _token_ok()
            if not ok:
                # Dead credential: do NOT burn connection attempts. Re-check
                # cheaply until the daily manual login restores the token.
                with _lock:
                    _status["token_error"] = reason
                    _status["connected"] = False
                time.sleep(token_recheck)
                continue
            with _lock:
                _status["token_error"] = None
                connected = _status["connected"]
                have_socket = _socket is not None

            if not connected:
                # No symbol reload here: the feed is portfolio-scoped, so the
                # set is whatever set_symbols() last pushed. _on_connect ->
                # _resubscribe_all() re-subscribes that same set, so a
                # reconnect restores exactly what was being priced before.
                if have_socket:
                    with _lock:
                        _status["reconnects"] += 1
                _connect_once()
                time.sleep(backoff_cur)
                with _lock:
                    if _status["connected"]:
                        backoff_cur = backoff        # reset on success
                    else:
                        backoff_cur = min(backoff_cur * 2, backoff_max)
                continue

            backoff_cur = backoff
            if _stalled():
                # Connected by the flag, but no data is arriving while the
                # market is open — the connection is dead in the only sense
                # that matters. Tear it down so the next iteration rebuilds.
                logger.warning("FYERS WS stalled — no ticks while market open; rebuilding")
                _force_rebuild()
                continue
            # No periodic symbol polling: holdings only come from Groww, and
            # every call there re-downloads a ~19MB instrument file. Portfolio
            # analysis already fetches them, so it calls set_symbols() instead.
            time.sleep(1.0)
        except Exception as e:
            logger.warning("FYERS WS supervisor error: %s", e)
            with _lock:
                _status["last_error"] = str(e)[:300]
            time.sleep(backoff_cur)
            backoff_cur = min(backoff_cur * 2, backoff_max)


def start_in_background():
    """Launch the supervisor on a daemon thread. Returns the thread or None."""
    global _active
    if not _enabled():
        logger.info("FYERS WS disabled (fyers.ws_enabled=false)")
        with _lock:
            _status["enabled"] = False
        return None
    if _active:
        return None
    _active = True
    try:
        t = threading.Thread(target=_run, daemon=True, name="fyers-ws")
        t.start()
        return t
    except Exception as e:
        _active = False
        logger.warning("FYERS WS thread failed to start: %s", e)
        with _lock:
            _status["last_error"] = f"thread start failed: {e}"
        return None


def stop():
    """Stop the supervisor and close the socket (used by tests)."""
    global _active, _socket
    _active = False
    with _lock:
        sock = _socket
        _socket = None
        _status["connected"] = False
    if sock:
        try:
            sock.close_connection()
        except Exception:
            pass
