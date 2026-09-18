"""
Sessions — the one place that knows what "logged in" means.

Before this, "unlocked" lived in the browser's sessionStorage and the server
checked a single static token on writes only: every GET (trades, journal,
holdings, tokens) was readable by anyone who knew the URL, and the token was
the same string for every device until someone edited .env. Now:

  - POST /api/unlock with the right PIN creates a row in auth_sessions and
    sets an HttpOnly cookie carrying a 256-bit random ID. Only the SHA-256
    of that ID is stored, so the table never holds a usable credential.
  - Every request except a short allowlist (see app._require_session) needs
    that cookie to map to a live row. GETs included. SSE included - the
    browser sends cookies with EventSource, which is why this is a cookie
    and not a header.
  - Two clocks, enforced here, not in the browser: idle (no request for
    auth.idle_minutes) and absolute (auth.absolute_hours after unlock). Both
    editable in Settings. Logout revokes the row; a stolen cookie is dead
    once either clock runs out.
  - Cookie attributes: HttpOnly (scripts cannot read it), SameSite=Lax
    (not sent from other sites, but still sent on the top-level redirect
    back from FYERS's login), Path=/, Secure whenever the request came over
    HTTPS. Not Secure on plain http://127.0.0.1 - Safari refuses Secure
    cookies there and the laptop workflow would silently lock out.
  - The two scheduler tasks that call the app over loopback authenticate
    with SERVICE_TOKEN, a random value minted at process start and accepted
    only from 127.0.0.1. Same process, same value; nothing to configure.

Validated sessions are cached in memory for CACHE_SECONDS so the dashboard's
one-request-per-second polling does not become one query per second on a
pool of 15, and last_seen_at is written at most once per TOUCH_SECONDS.
Revocation clears the cache entry, so logout is immediate.
"""
import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

COOKIE = "sid"
SERVICE_TOKEN = secrets.token_urlsafe(32)
CACHE_SECONDS = 30
TOUCH_SECONDS = 60
DEFAULT_IDLE_MINUTES = 30
DEFAULT_ABSOLUTE_HOURS = 12

_lock = threading.Lock()
_cache = {}      # sid_hash -> {"row": dict, "cached_at": datetime}


def _h(sid):
    return hashlib.sha256(sid.encode()).hexdigest()


def _cfg_int(key, default):
    try:
        from db_manager import get_config
        v = get_config(key)
        return int(v) if v not in (None, "") else default
    except Exception:
        return default


def idle_seconds():
    return _cfg_int("auth.idle_minutes", DEFAULT_IDLE_MINUTES) * 60


def absolute_seconds():
    return _cfg_int("auth.absolute_hours", DEFAULT_ABSOLUTE_HOURS) * 3600


def seed_config():
    """Make the auth settings visible/editable in Settings without changing them."""
    defaults = (
        ("auth.idle_minutes", str(DEFAULT_IDLE_MINUTES),
         "Lock after this many minutes without a request (PIN again)"),
        ("auth.absolute_hours", str(DEFAULT_ABSOLUTE_HOURS),
         "Lock this many hours after unlock regardless of activity (PIN again)"),
        # The front door. Off: "/" is the dashboard, as always. On: "/" shows
        # the landing page to anyone without a live session and sends everyone
        # else to /app. Leave off until at least one sign-in provider below is
        # on, or a browser without a cookie has no way in.
        ("auth.landing_enabled", "false",
         "Serve the landing page at / for visitors without a session (true/false)"),
        ("auth.provider.google", "false",
         "Landing page: Continue with Google is live (true/false) — needs the Google sign-in server side"),
        ("auth.provider.apple", "false",
         "Landing page: Continue with Apple is live (true/false) — needs the domain and Apple developer setup"),
        ("auth.provider.email", "false",
         "Landing page: email + password sign-in and sign-up are live (true/false)"),
    )
    try:
        from db_manager import get_config, set_config
        for key, value, description in defaults:
            if get_config(key) in (None, ""):
                set_config(key, value, description=description)
    except Exception as e:
        logger.warning("auth config seed failed: %s", e)


# ── lifecycle ────────────────────────────────────────────────────────────────

def create(user_id, ip=None, user_agent=None):
    """New session. Returns the raw ID (for the cookie) - the only time it exists in full."""
    from db_manager import get_db, AuthSession
    sid = secrets.token_urlsafe(32)          # 256 bits
    now = datetime.utcnow()
    with get_db().Session() as s:
        s.add(AuthSession(sid_hash=_h(sid), user_id=int(user_id), created_at=now, last_seen_at=now,
                          expires_at=now + timedelta(seconds=absolute_seconds()),
                          ip=(ip or "")[:64], user_agent=(user_agent or "")[:300]))
        s.commit()
    return sid


def _row_to_dict(r):
    return {"id": r.id, "sid_hash": r.sid_hash, "user_id": r.user_id, "created_at": r.created_at,
            "last_seen_at": r.last_seen_at, "expires_at": r.expires_at, "revoked_at": r.revoked_at,
            "sudo_until": r.sudo_until}


def load(sid):
    """
    The live session for this ID, or None. None means: no such session,
    revoked, past its absolute expiry, or idle too long. Never raises - a DB
    hiccup reads as "locked", which is the safe side.
    """
    if not sid or len(sid) > 200:
        return None
    key = _h(sid)
    now = datetime.utcnow()
    try:
        with _lock:
            hit = _cache.get(key)
        if hit and (now - hit["cached_at"]).total_seconds() < CACHE_SECONDS:
            row = hit["row"]
        else:
            from db_manager import get_db, AuthSession
            with get_db().Session() as s:
                r = s.query(AuthSession).filter_by(sid_hash=key).first()
                row = _row_to_dict(r) if r else None
            with _lock:
                if row:
                    _cache[key] = {"row": row, "cached_at": now}
                else:
                    _cache.pop(key, None)
        if not row or row["revoked_at"] is not None:
            return None
        if now >= row["expires_at"]:
            return None
        if (now - row["last_seen_at"]).total_seconds() > idle_seconds():
            return None
        if (now - row["last_seen_at"]).total_seconds() >= TOUCH_SECONDS:
            _touch(key, now)
            row["last_seen_at"] = now
        return row
    except Exception as e:
        logger.warning("session load failed (treated as locked): %s", e)
        return None


def _touch(key, now):
    try:
        from db_manager import get_db, AuthSession
        with get_db().Session() as s:
            s.query(AuthSession).filter_by(sid_hash=key).update({"last_seen_at": now})
            s.commit()
    except Exception as e:
        logger.debug("session touch failed: %s", e)


def revoke(sid):
    """Logout: the row is marked revoked and the cache entry dropped, so the
    very next request with this cookie is refused."""
    if not sid:
        return
    key = _h(sid)
    with _lock:
        _cache.pop(key, None)
    try:
        from db_manager import get_db, AuthSession
        with get_db().Session() as s:
            s.query(AuthSession).filter_by(sid_hash=key, revoked_at=None).update({"revoked_at": datetime.utcnow()})
            s.commit()
    except Exception as e:
        logger.warning("session revoke failed: %s", e)


def purge_expired(days=7):
    """Housekeeping at startup: rows dead for more than `days` are deleted."""
    try:
        from db_manager import get_db, AuthSession
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_db().Session() as s:
            n = s.query(AuthSession).filter((AuthSession.expires_at < cutoff) | (AuthSession.revoked_at < cutoff)).delete(synchronize_session=False)
            s.commit()
        if n:
            logger.info("auth_sessions: purged %d expired rows", n)
    except Exception as e:
        logger.debug("session purge skipped: %s", e)


# ── request helpers ──────────────────────────────────────────────────────────

def request_is_secure(request):
    return bool(request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https")


def set_cookie(response, sid, secure):
    # No max_age: the cookie dies with the browser; the server clocks are the
    # real limit either way.
    response.set_cookie(COOKIE, sid, httponly=True, secure=secure, samesite="Lax", path="/")


def clear_cookie(response, secure):
    response.set_cookie(COOKIE, "", max_age=0, expires=0, httponly=True, secure=secure, samesite="Lax", path="/")


def is_service_call(request):
    """A scheduler task calling this same process over loopback."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return False
    return secrets.compare_digest(request.headers.get("X-Service-Token", ""), SERVICE_TOKEN)
