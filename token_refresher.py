"""
Groww API Token Auto-Refresher

The Groww access token expires daily at ~6 AM IST.
This module auto-refreshes it using the API key + secret,
updates os.environ, config, .env file, and resets cached clients.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def refresh_token():
    """
    Call Groww API to get a fresh access token.
    Updates: os.environ, config module, .env file, and resets cached clients.
    Returns the new token string, or None on failure.
    """
    from growwapi import GrowwAPI

    api_key = os.getenv("GROWW_API_KEY", "")
    secret = os.getenv("GROWW_API_SECRET", "")

    if not api_key or not secret:
        logger.error("Cannot refresh token: GROWW_API_KEY or GROWW_API_SECRET missing")
        return None

    try:
        new_token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
        if not new_token:
            logger.error("Token refresh returned empty token")
            return None

        # If it's a dict, extract the token string
        if isinstance(new_token, dict):
            new_token = new_token.get("token") or new_token.get("access_token") or str(new_token)

        logger.info("✓ Groww access token refreshed successfully")

        # 1. Update os.environ so any os.getenv() calls pick it up
        os.environ["GROWW_ACCESS_TOKEN"] = new_token

        # 2. Update config module
        try:
            import config
            config.GROWW_ACCESS_TOKEN = new_token
        except Exception:
            pass

        # 3. Update .env file
        _update_env_file(new_token)

        # 4. Reset cached GrowwAPI clients in bot.py
        try:
            import bot
            bot._groww = None
            bot.GROWW_ACCESS_TOKEN = new_token
        except Exception:
            pass

        # 5. Reset price_fetcher module-level token
        try:
            import price_fetcher
            price_fetcher.GROWW_ACCESS_TOKEN = new_token
        except Exception:
            pass

        # 6. fno_trader reads os.getenv each time, so it's already handled

        return new_token

    except Exception as e:
        logger.error("Token refresh failed: %s", e)
        return None


def _update_env_file(new_token):
    """Update GROWW_ACCESS_TOKEN in the .env file."""
    try:
        if not os.path.exists(_ENV_PATH):
            return

        with open(_ENV_PATH, "r") as f:
            content = f.read()

        # Replace existing token line
        if re.search(r"^GROWW_ACCESS_TOKEN=", content, re.MULTILINE):
            content = re.sub(
                r"^GROWW_ACCESS_TOKEN=.*$",
                f"GROWW_ACCESS_TOKEN={new_token}",
                content,
                flags=re.MULTILINE,
            )
        else:
            content += f"\nGROWW_ACCESS_TOKEN={new_token}\n"

        with open(_ENV_PATH, "w") as f:
            f.write(content)

        logger.debug("✓ .env file updated with new token")
    except Exception as e:
        logger.warning("Failed to update .env file: %s", e)


def check_and_refresh():
    """
    Test current token with a lightweight API call.
    If it fails with auth error, refresh it.
    Returns True if token is valid (either already or after refresh).
    """
    from growwapi import GrowwAPI

    token = os.getenv("GROWW_ACCESS_TOKEN", "")
    if not token:
        logger.warning("No access token set, attempting refresh...")
        return refresh_token() is not None

    # Quick test — try fetching user profile (lightweight call)
    try:
        client = GrowwAPI(token)
        client.get_user_profile()
        logger.info("✓ Groww token is valid")
        return True
    except Exception as e:
        err = str(e).lower()
        if "auth" in err or "expired" in err or "invalid" in err or "401" in err:
            logger.warning("Token expired, auto-refreshing...")
            return refresh_token() is not None
        else:
            # Some other error (network, etc.) — token might be fine
            logger.warning("Token check got non-auth error: %s (assuming valid)", e)
            return True
