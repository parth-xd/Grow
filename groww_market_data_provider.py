"""
GrowwMarketDataProvider — thin adapter over the EXISTING, already-working
Groww call sites in bot.py / fno_trader.py.

Deliberately does not reimplement any Groww API call. It only wraps what's
already there so both providers can sit behind the same interface later.
Nothing currently calls this class — it's foundation for a future rewire,
not a behavior change. bot.py / fno_trader.py continue to call Groww
directly, exactly as they do today.
"""

import bot
import fno_trader
from market_data_provider import MarketDataProvider

# FYERS-style resolution -> Groww's interval_in_minutes.
# Groww has no native D/W/M candle mode; 'D' maps to the same 1440-minute
# request bot.py's own fallback path already uses, '1W' mirrors the 10080
# (=7*1440) trick price_fetcher.py uses for its 5-year weekly backfill.
# '1M' has no equivalent anywhere in this codebase today — raises rather
# than silently approximating with e.g. 43200 minutes.
_RESOLUTION_TO_GROWW_MINUTES = {
    "1": 1, "2": 2, "3": 3, "5": 5, "10": 10, "15": 15, "20": 20, "30": 30,
    "45": 45, "60": 60, "120": 120, "180": 180, "240": 240,
    "D": 1440, "1D": 1440,
    "1W": 10080,
}


class GrowwMarketDataProvider(MarketDataProvider):

    def get_historical_candles(self, symbol: str, resolution: str, start: str, end: str) -> list:
        if resolution not in _RESOLUTION_TO_GROWW_MINUTES:
            raise NotImplementedError(
                f"Groww has no equivalent for resolution={resolution!r} "
                f"(seconds candles and '1M' are not available via growwapi)"
            )
        interval = _RESOLUTION_TO_GROWW_MINUTES[resolution]
        groww = bot._get_groww()
        resp = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange=bot.DEFAULT_EXCHANGE,
            segment=bot.DEFAULT_SEGMENT,
            start_time=f"{start} 09:15:00",
            end_time=f"{end} 15:30:00",
            interval_in_minutes=interval,
        )
        return resp.get("candles", [])

    def get_ltp(self, symbol: str) -> float:
        return bot.fetch_live_price(symbol)

    def get_quote(self, symbol: str) -> dict:
        return bot.fetch_quote(symbol)

    def get_option_chain(self, instrument_key: str, expiry_date: str) -> dict:
        return fno_trader.get_option_chain(instrument_key, expiry_date)

    def get_expiries(self, instrument_key: str) -> list:
        return fno_trader.get_expiries(instrument_key)

    def search_instruments(self, query: str) -> list:
        raise NotImplementedError(
            "No existing Groww call site does a plain instrument search by "
            "query string — app.py's /api/search-stocks and /api/search use "
            "get_all_instruments() and filter client-side. Wire this up if a "
            "caller actually needs it; don't guess at the right filtering now."
        )
