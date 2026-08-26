"""
FYERS API v3 authentication — market-data-only access.

Unlike Groww's key+secret model (get_token.py, token_refresher.py), FYERS uses
an OAuth-style authcode exchange: the user must log into FYERS in their own
browser (this code never sees or handles FYERS login credentials), then paste
back the auth_code (or the full redirected URL) FYERS hands back so it can be
exchanged for an access_token.

Field names and endpoints below are taken verbatim from the FYERS v3 API
reference (Authentication & Login Flow - User Apps section), not guessed.

Refresh-token renewal (refresh_access_token) requires the user's FYERS PIN on
every call — there is no fully-unattended daily refresh like Groww has.
FYERS's docs also note "Refresh token will be discontinued from 1st April"
without stating a year on that specific line; verify current behavior with an
actual API test rather than assuming it still works.
"""

import os
import re
import hashlib
import logging
import urllib.parse

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FYERS_BASE = "https://api-t1.fyers.in/api/v3"

APP_ID = os.getenv("FYER_APP_ID")
SECRET_ID = os.getenv("FYER_SECRET_ID")
REDIRECT_URL = os.getenv("FYER_Redirect_URL", "http://127.0.0.1:8000/fyers_callback")

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def get_login_url(state: str = "grow_migration") -> str:
    """Step 1: URL the user opens in their own browser and logs into FYERS with."""
    if not APP_ID:
        raise RuntimeError("FYER_APP_ID not set in .env")
    params = {
        "client_id": APP_ID,
        "redirect_uri": REDIRECT_URL,
        "response_type": "code",
        "state": state,
    }
    return f"{FYERS_BASE}/generate-authcode?{urllib.parse.urlencode(params)}"


def extract_auth_code(redirected_url_or_code: str) -> str:
    """Accepts either the raw auth_code or the full URL FYERS redirected the browser to."""
    text = redirected_url_or_code.strip()
    if "auth_code=" in text:
        parsed = urllib.parse.urlparse(text)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("auth_code", [None])[0]
        if not code:
            raise ValueError("No auth_code found in the provided URL")
        return code
    return text


def _app_id_hash() -> str:
    if not APP_ID or not SECRET_ID:
        raise RuntimeError("FYER_APP_ID / FYER_SECRET_ID not set in .env")
    return hashlib.sha256(f"{APP_ID}:{SECRET_ID}".encode()).hexdigest()


def exchange_auth_code(auth_code: str) -> dict:
    """Step 2: exchange a one-time auth_code for access_token + refresh_token."""
    resp = requests.post(
        f"{FYERS_BASE}/validate-authcode",
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "authorization_code",
            "appIdHash": _app_id_hash(),
            "code": auth_code,
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("s") != "ok":
        raise RuntimeError(f"FYERS auth exchange failed: code={data.get('code')} message={data.get('message')}")
    return data


def refresh_access_token(refresh_token: str, pin: str) -> dict:
    """
    Exchange a refresh_token (+ PIN) for a fresh access_token.

    The PIN is required by FYERS on every refresh call, but that does NOT
    make this attended-only: with the PIN stored in .env as FYER_PIN this
    runs unattended, same as Groww's key+secret refresh. See
    refresh_if_needed() below, which is what the scheduler calls.
    """
    resp = requests.post(
        f"{FYERS_BASE}/validate-refresh-token",
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "refresh_token",
            "appIdHash": _app_id_hash(),
            "refresh_token": refresh_token,
            "pin": pin,
        },
        timeout=15,
    )
    data = resp.json()
    if data.get("s") != "ok":
        raise RuntimeError(f"FYERS token refresh failed: code={data.get('code')} message={data.get('message')}")
    return data


def _update_env_file(key: str, value: str):
    """Same pattern as token_refresher.py's Groww handling — replace or append one line."""
    if not os.path.exists(_ENV_PATH):
        return
    with open(_ENV_PATH, "r") as f:
        content = f.read()
    if re.search(rf"^{key}=", content, re.MULTILINE):
        content = re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={value}\n"
    with open(_ENV_PATH, "w") as f:
        f.write(content)


def complete_login(redirected_url_or_code: str) -> str:
    """
    Full step-2 flow: takes what the user pasted back after logging into FYERS
    themselves, exchanges it, and persists access_token + refresh_token to .env.
    Never returns or logs the actual token values.
    """
    auth_code = extract_auth_code(redirected_url_or_code)
    data = exchange_auth_code(auth_code)
    _update_env_file("FYER_ACCESS_TOKEN", data["access_token"])
    _update_env_file("FYER_REFRESH_TOKEN", data["refresh_token"])
    os.environ["FYER_ACCESS_TOKEN"] = data["access_token"]
    os.environ["FYER_REFRESH_TOKEN"] = data["refresh_token"]
    logger.info("FYERS access token acquired and saved to .env")
    return "ok"


def token_expiry() -> "datetime | None":
    """
    Read the access token's own expiry out of its JWT payload — no API call.
    FYERS access tokens carry a fixed 06:00 IST `exp`. Returns None if the
    token is absent or not decodable.
    """
    import base64
    import json as _json
    from datetime import datetime, timezone, timedelta

    token = os.getenv("FYER_ACCESS_TOKEN")
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(payload))
        return datetime.fromtimestamp(claims["exp"], tz=timezone(timedelta(hours=5, minutes=30)))
    except Exception:
        return None


def refresh_if_needed(margin_minutes: int = 30) -> bool:
    """
    Refresh the access token if it's expired or about to expire.

    This is the unattended daily-renewal path. It needs three things already
    in .env: FYER_REFRESH_TOKEN (written by complete_login, valid ~15 days),
    FYER_APP_ID/FYER_SECRET_ID, and FYER_PIN.

    Returns True if a refresh happened, False if the current token was still
    good or the refresh could not be attempted. Never raises — an auth
    failure must not take down whatever scheduler task called this.

    Note the 15-day boundary: the refresh_token itself eventually expires,
    and at that point this starts failing and a real interactive login
    (get_login_url -> complete_login) is required. That failure is logged at
    ERROR so it's visible rather than silently leaving a dead token.
    """
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))
    exp = token_expiry()
    if exp and datetime.now(IST) < exp - timedelta(minutes=margin_minutes):
        return False  # still valid, nothing to do

    refresh_token = os.getenv("FYER_REFRESH_TOKEN")
    pin = os.getenv("FYER_PIN")
    if not refresh_token:
        logger.error("FYERS token needs refresh but FYER_REFRESH_TOKEN is missing — interactive login required")
        return False
    if not pin:
        logger.error("FYERS token needs refresh but FYER_PIN is not set in .env — cannot refresh unattended")
        return False

    try:
        data = refresh_access_token(refresh_token, pin)
        new_token = data["access_token"]
        _update_env_file("FYER_ACCESS_TOKEN", new_token)
        os.environ["FYER_ACCESS_TOKEN"] = new_token
        logger.info("FYERS access token refreshed (valid until %s)", token_expiry())
        return True
    except Exception as e:
        msg = str(e)
        if "code=-16" in msg or "currently disabled" in msg:
            # Verified live on 2026-08-16: FYERS returns
            #   code=-16 "Refresh token API is currently disabled to comply
            #   with SEBI regulations."
            # The endpoint is switched off at FYERS's end, so no amount of
            # retrying, PIN-checking or refresh-token rotation will help.
            # Unattended renewal is not currently possible for FYERS at all;
            # a human must complete the OAuth login each time the access
            # token expires (06:00 IST daily). Logged as a distinct, loud
            # message so it isn't mistaken for a credentials problem.
            logger.error(
                "FYERS refresh-token API is DISABLED by FYERS (SEBI compliance) — "
                "unattended renewal is impossible. A manual OAuth login is required "
                "each day after 06:00 IST. Run: python -c \"import fyers_auth; "
                "print(fyers_auth.get_login_url())\""
            )
        else:
            logger.error("FYERS token refresh failed — interactive re-login may be needed: %s", e)
        return False


def get_access_token() -> str:
    token = os.getenv("FYER_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("No FYER_ACCESS_TOKEN in .env — run the login flow first (see get_login_url())")
    return token


def auth_header() -> str:
    """Exact header format per FYERS docs: 'app_id:access_token'."""
    if not APP_ID:
        raise RuntimeError("FYER_APP_ID not set in .env")
    return f"{APP_ID}:{get_access_token()}"
