"""
FYERSMarketDataProvider — adapter over fyers_client.py.

Symbol resolution prefers master_ticker_table.fyers_historical_symbol —
already verified this session for 2,465 equities via the historical-candle
migration — falling back to a pattern guess only for symbols the table
doesn't know about yet (new listings, or the 3 indices, which the table
does carry once backfilled: see docs/FYERS_CANDLE_MIGRATION_PLAN.md).
Do not extend _INDEX_SYMBOLS with more guessed formats; confirm each new
symbol against a real FYERS response first, same rule as before.
"""

import time
import fyers_client
from market_data_provider import MarketDataProvider

_INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    # FINNIFTY, MIDCPNIFTY, SENSEX: not yet confirmed against a real FYERS
    # response in this session — add only after testing, not by guessing
    # the naming pattern from the two above.
}

# fyers_client.get_quotes documents a 50-symbol cap per request.
_QUOTES_BATCH_SIZE = 50

# Short-lived so a burst of near-simultaneous callers (a dashboard poll
# alongside an auto-trade cycle checking the same symbol) shares one FYERS
# call instead of one each, without serving prices stale enough to matter
# for a live trading decision.
_QUOTE_CACHE_TTL = 2.0
_quote_cache = {}   # fy_symbol -> (fetched_at, quote_dict)


def to_fyers_symbol(symbol: str, exchange: str = "NSE") -> str:
    """
    Resolve via master_ticker_table first — it already carries the exact
    string FYERS itself returned during historical backfill, verified per
    symbol, not guessed. Falls back to the pattern guess for anything not
    yet in the table (queries the table on every call rather than caching
    the whole thing in memory, since MasterTicker is small and this keeps
    a newly-added symbol correct immediately with no cache to invalidate).
    """
    if symbol in _INDEX_SYMBOLS:
        return _INDEX_SYMBOLS[symbol]
    try:
        from db_manager import get_db, MasterTicker
        with get_db().Session() as session:
            row = session.query(MasterTicker).filter_by(nse_ticker=symbol).first()
        if row and row.fyers_resolution_status == "resolved" and row.fyers_historical_symbol:
            return row.fyers_historical_symbol
    except Exception:
        pass
    return f"{exchange}:{symbol}-EQ"


def _get_quotes_cached(fy_symbols):
    """
    Batched, cached quote fetch. Splits into <=50-symbol chunks, serves
    anything fetched within _QUOTE_CACHE_TTL from cache, only calls FYERS
    for what's missing/stale. Returns {fy_symbol: quote_dict}.
    """
    now = time.time()
    out = {}
    missing = []
    for s in fy_symbols:
        cached = _quote_cache.get(s)
        if cached and now - cached[0] < _QUOTE_CACHE_TTL:
            out[s] = cached[1]
        else:
            missing.append(s)

    for i in range(0, len(missing), _QUOTES_BATCH_SIZE):
        chunk = missing[i:i + _QUOTES_BATCH_SIZE]
        status, data = fyers_client.get_quotes(chunk)
        if data.get("s") != "ok":
            raise RuntimeError(f"FYERS quotes failed for {chunk}: {data}")
        for d in data.get("d", []):
            sym = d.get("n")
            if sym:
                _quote_cache[sym] = (now, d)
                out[sym] = d
    return out


class FYERSMarketDataProvider(MarketDataProvider):

    def get_historical_candles(self, symbol: str, resolution: str, start: str, end: str) -> list:
        fy_symbol = to_fyers_symbol(symbol)
        status, data = fyers_client.get_historical_candles(fy_symbol, resolution, start, end, date_format=1)
        if data.get("s") not in ("ok", "no_data"):
            raise RuntimeError(f"FYERS history failed for {fy_symbol}: {data}")
        return data.get("candles", [])

    def get_ltp(self, symbol: str) -> float:
        fy_symbol = to_fyers_symbol(symbol)
        quotes = _get_quotes_cached([fy_symbol])
        d = quotes.get(fy_symbol)
        if not d:
            raise RuntimeError(f"FYERS quote failed for {fy_symbol}: no data returned")
        return d["v"]["lp"]

    def get_ltp_batch(self, symbols: list) -> dict:
        """{original_symbol: ltp} for every symbol resolvable and quoted."""
        fy_map = {s: to_fyers_symbol(s) for s in symbols}
        quotes = _get_quotes_cached(list(fy_map.values()))
        return {
            s: quotes[fy]["v"]["lp"]
            for s, fy in fy_map.items() if fy in quotes
        }

    def get_quote(self, symbol: str) -> dict:
        fy_symbol = to_fyers_symbol(symbol)
        quotes = _get_quotes_cached([fy_symbol])
        d = quotes.get(fy_symbol)
        if not d:
            raise RuntimeError(f"FYERS quote failed for {fy_symbol}: no data returned")
        return d

    def get_option_chain(self, instrument_key: str, expiry_date: str) -> dict:
        # FYERS's options-chain-v3 takes the underlying symbol and returns all
        # expiries in expiryData[]; unlike Groww it is not a per-expiry call.
        # Adapter currently returns the raw response — filtering to
        # expiry_date is left to the caller until a real consumer exists.
        fy_symbol = to_fyers_symbol(instrument_key)
        status, data = fyers_client.get_option_chain(fy_symbol, strikecount=50, greeks=1)
        return data

    def get_expiries(self, instrument_key: str) -> list:
        chain = self.get_option_chain(instrument_key, expiry_date="")
        return chain.get("data", {}).get("expiryData", [])

    def search_instruments(self, query: str) -> list:
        raise NotImplementedError(
            "FYERS has no search-by-query endpoint — only bulk Symbol Master "
            "CSV/JSON downloads per exchange-segment. A search feature would "
            "need to download and index those locally; not built in this phase."
        )
