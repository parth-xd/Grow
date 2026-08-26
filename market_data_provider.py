"""
Provider-neutral market-data interface.

Methods here are deliberately limited to capabilities the Groww codebase
audit (2026-08-15, see docs/FYERS_MIGRATION_PHASE1.md section A) proved are
actually used somewhere in this app. Do not add methods speculatively —
extend this only when a real caller needs them (get_market_depth was left
out for exactly this reason: no Groww call site uses depth anywhere).

Callers should depend on this interface, not on GrowwMarketDataProvider or
FYERSMarketDataProvider directly, so strategy/model code never knows which
broker's data it's looking at. Nothing in this module talks to a broker yet
— this phase only establishes the shape. No existing Groww call site has
been rewired to use it.
"""

from abc import ABC, abstractmethod


class MarketDataProvider(ABC):

    @abstractmethod
    def get_historical_candles(self, symbol: str, resolution: str, start: str, end: str) -> list:
        """
        resolution: superset vocabulary, FYERS-style strings —
          '1S'..'45S' (seconds), '1'..'240' (minutes), 'D', '1W', '1M'.
        start/end: 'YYYY-MM-DD'.
        Returns a list of [epoch_seconds, open, high, low, close, volume].
        Each adapter is responsible for translating this into whatever its
        underlying SDK expects (e.g. GrowwMarketDataProvider maps 'D'/'1W'/'1M'
        to interval_in_minutes=1440/10080/... internally).
        """

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Last traded price for a single symbol."""

    @abstractmethod
    def get_quote(self, symbol: str) -> dict:
        """Full quote (ohlc, day change, volume, circuits, ...). Shape is
        provider-specific — callers already handle this today (bot.fetch_quote
        callers read Groww's shape), so this is a pass-through, not a
        normalized schema, until a real cross-provider consumer needs one."""

    @abstractmethod
    def get_option_chain(self, instrument_key: str, expiry_date: str) -> dict:
        """Per-strike CE/PE chain. Both Groww and FYERS return Greeks + OI
        natively (confirmed this session on both sides) — pass-through shape."""

    @abstractmethod
    def get_expiries(self, instrument_key: str) -> list:
        """Available expiry dates for an F&O instrument."""

    @abstractmethod
    def search_instruments(self, query: str) -> list:
        """Instrument/company-name search, e.g. for stock-search autocomplete."""
