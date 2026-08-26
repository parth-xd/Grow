"""
PostgreSQL database manager — unified ORM for all persistent data.
Models: Candle, CommoditySnapshot, DisruptionEvent, NewsArticle, GlobalNews,
        Stock, NSEInstrument, MasterTicker, TradeJournalEntry, TradeLogEntry,
        StockThesis, AnalysisCache, WatchlistNote, ConfigSetting,
        CompanyConnection, CompanyExternalData, ExternalSlugMap.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Index, Text, Boolean, text, update
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import sessionmaker, scoped_session

logger = logging.getLogger(__name__)

# Indian market time. Used to normalise FYERS TIMESTAMPTZ reads, which come
# back from pandas as UTC-aware — never rely on the host machine's timezone
# for market-session logic.
_IST_NAME = "Asia/Kolkata"
_IST = timezone(timedelta(hours=5, minutes=30))

Base = declarative_base()


# ── Candle data ──────────────────────────────────────────────────────────────

class Candle(Base):
    """ORM model for OHLCV candle data."""
    __tablename__ = "candles"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_symbol_timestamp", "symbol", "timestamp", unique=True),
    )

    def __repr__(self):
        return f"<Candle {self.symbol} {self.timestamp} close={self.close}>"


class IntradayCandle(Base):
    """
    Intraday 1-minute or 5-minute candles for daily chart replay.
    Used for visualizing trade entry/exit points on real market data.
    Stored after market close, one file per trading day.
    """
    __tablename__ = "intraday_candles"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    trading_date = Column(String(10), nullable=False, index=True)  # "2026-04-02"
    time = Column(String(8), nullable=False)  # "14:30:00" or "14:30"
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, default=0)
    interval = Column(String(10), default="1min")  # "1min" or "5min"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_intraday_symbol_date", "symbol", "trading_date"),
        Index("idx_intraday_symbol_date_time", "symbol", "trading_date", "time"),
    )

    def __repr__(self):
        return f"<IntradayCandle {self.symbol} {self.trading_date} {self.time} close={self.close}>"


# ── Commodity + Supply Chain ─────────────────────────────────────────────────

class CommoditySnapshot(Base):
    """Live commodity price + trend snapshot, updated by background collector."""
    __tablename__ = "commodity_snapshots"

    id = Column(Integer, primary_key=True)
    commodity = Column(String(50), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    current_price = Column(Float)
    prev_price = Column(Float)               # price from previous refresh
    price_change_since_last = Column(Float)   # % change vs previous refresh
    prev_trend = Column(String(10))           # trend from previous refresh
    price_change_1m = Column(Float, default=0)
    price_change_3m = Column(Float, default=0)
    trend = Column(String(10), default="UNKNOWN")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_commodity_snap", "commodity", unique=True),
    )


class DisruptionEvent(Base):
    """Live disruption events scored from news sentiment."""
    __tablename__ = "disruption_events"

    id = Column(Integer, primary_key=True)
    commodity = Column(String(50), nullable=False, index=True)
    region = Column(String(100), nullable=False)
    iso_a3 = Column(String(3))
    iso_n3 = Column(String(3))
    severity = Column(String(20), default="low")
    prev_severity = Column(String(20))        # severity from previous refresh
    description = Column(String(500))
    prev_description = Column(String(500))    # description from previous refresh
    news_count = Column(Integer, default=0)
    avg_sentiment = Column(Float, default=0)
    sample_headlines = Column(String(2000), default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_disruption", "commodity", "region", unique=True),
    )


# ── News Articles (persistent) ──────────────────────────────────────────────

class NewsArticle(Base):
    """Persisted news article — never re-fetched once stored."""
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    title_hash = Column(String(64), nullable=False)          # dedup key
    title = Column(String(500), nullable=False)
    source = Column(String(100))
    url = Column(String(1000))
    published = Column(String(60))                            # raw date string
    published_at = Column(DateTime, index=True)               # parsed datetime
    sentiment_score = Column(Float, default=0)
    sentiment = Column(String(10), default="NEUTRAL")
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_news_symbol_hash", "symbol", "title_hash", unique=True),
    )


# ── Global / World News (macro, sector, geopolitical) ───────────────────────

class GlobalNews(Base):
    """World & macro news — RBI, Fed, global events, sector moves, etc."""
    __tablename__ = "global_news"

    id = Column(Integer, primary_key=True)
    title_hash = Column(String(64), nullable=False, unique=True)
    title = Column(String(500), nullable=False)
    source = Column(String(100))
    url = Column(String(1000))
    published = Column(String(60))
    published_at = Column(DateTime, index=True)
    category = Column(String(50), index=True)            # macro, sector, rbi, fed, geopolitical, market
    tags = Column(Text)                                   # JSON list of tags e.g. ["rbi","rate_cut","banking"]
    sentiment_score = Column(Float, default=0)
    sentiment = Column(String(10), default="NEUTRAL")
    summary = Column(String(500))
    fetched_at = Column(DateTime, default=datetime.utcnow)


# ── Unified Stock table — single source of truth ────────────────────────────

class Stock(Base):
    """
    Master stock table. Replaces all hardcoded dicts:
    STOCK_DIRECTORY, SYMBOL_NAMES, SECTOR_MAP, SECTOR, COMPETITORS, COMMODITY_MAP.
    """
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    company_name = Column(String(200), nullable=False)
    sector = Column(String(50))                    # e.g. "BANKING", "IT", "ENERGY"
    sector_display = Column(String(100))           # e.g. "IT Services", "Banking (PSU)"
    competitors_json = Column(Text, default="[]")  # JSON array of symbols
    # Commodity dependency
    commodity = Column(String(50))                 # e.g. "Crude Oil"
    commodity_ticker = Column(String(20))          # e.g. "CL=F"
    commodity_relationship = Column(String(10))    # "direct" or "inverse"
    commodity_weight = Column(Float, default=0)    # e.g. 0.35
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_competitors(self):
        try:
            return json.loads(self.competitors_json) if self.competitors_json else []
        except Exception:
            return []

    def set_competitors(self, lst):
        self.competitors_json = json.dumps(lst)

    def __repr__(self):
        return f"<Stock {self.symbol} ({self.company_name})>"


class NSEInstrument(Base):
    """
    Full NSE main-board equity directory (exchange=NSE, segment=CASH,
    series=EQ), sourced from Groww's instrument master. Search/autocomplete
    only — deliberately separate from `Stock`, which drives the scheduler's
    polling loop, Tijori collection, and research scoring. Adding a row here
    does not add it to any active tracking loop.
    """
    __tablename__ = "nse_instruments"

    symbol = Column(String(20), primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    isin = Column(String(20))
    series = Column(String(10))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<NSEInstrument {self.symbol} ({self.name})>"


class MasterTicker(Base):
    """
    Master ticker / security directory — the complete NSE-listed universe
    plus the identifier each data provider needs for the same security.

    This is a DIRECTORY, not a data-collection universe: adding a row here
    does not fetch prices, subscribe to any feed, or trigger Tijori
    collection. It only maps `nse_ticker` to what each provider calls that
    security, so the Watchlist add flow and search can resolve identifiers
    without guessing. `Stock` (the scheduler/Tijori/research active
    universe) and `NSEInstrument` (superseded by this table for search) are
    separate and untouched by this model.

    `tijori_ticker` is populated read-only from the existing
    `external_slug_map` cache — this table never triggers a new Tijori page
    fetch; that still only happens via the existing watchlist-add onboarding
    flow (tijori_collector.onboard_symbol).
    """
    __tablename__ = "master_ticker_table"

    nse_ticker = Column(String(20), primary_key=True)
    company_name = Column(String(200))
    isin = Column(String(20), index=True)
    exchange = Column(String(10), default="NSE")
    segment = Column(String(10))           # "CASH" (equities) or "INDEX"
    instrument_type = Column(String(10))   # "EQ" or "INDEX"

    # FYERS — historical-symbol format verified identical to the string the
    # SDK's WebSocket subscribe() call accepts (fyers_apiv3 3.1.16
    # data_ws.py:1776); kept as separate columns since the two are resolved
    # independently and could diverge for a future instrument type.
    fyers_historical_symbol = Column(String(40))
    fyers_websocket_symbol = Column(String(40))
    fyers_token = Column(String(30))
    fyers_isin = Column(String(20))        # FYERS's own ISIN, for cross-check against `isin`
    fyers_resolution_status = Column(String(20), default="unresolved")  # resolved/unresolved
    fyers_unresolved_reason = Column(Text)

    tijori_ticker = Column(String(200))    # verified Tijori slug, read from external_slug_map only
    tijori_resolution_status = Column(String(20), default="not_attempted")  # resolved/failed/not_attempted
    tijori_unresolved_reason = Column(Text)

    is_active = Column(Boolean, default=True)  # False = no longer in the current NSE universe pull; never deleted
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<MasterTicker {self.nse_ticker} fyers={self.fyers_resolution_status} tijori={self.tijori_resolution_status}>"


# ── Trade Journal (replaces trade_journal.json) ─────────────────────────────

class TradeJournalEntry(Base):
    """Unified trade journal — all trades (actual + paper) with full pre/post analysis."""
    __tablename__ = "trade_journal"

    id = Column(Integer, primary_key=True)
    trade_id = Column(String(50), nullable=False, unique=True, index=True)
    status = Column(String(10), default="OPEN")  # OPEN / CLOSED
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(4), nullable=False)      # BUY / SELL
    quantity = Column(Integer, nullable=False)
    trigger = Column(String(20), default="auto")  # auto / manual
    # Which model produced the signal: 'GradientBoosting' or 'XGBoost'.
    # Nullable because rows written before the cash-XGBoost addition have no
    # attribution; those predate any model other than GradientBoosting.
    model_source = Column(String(20), index=True)
    is_paper = Column(Boolean, default=True)      # True for paper trades, False for actual
    
    # Entry details
    entry_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    
    # Exit details
    exit_time = Column(DateTime)
    exit_price = Column(Float)
    exit_reason = Column(String(100))  # TARGET_HIT, STOP_LOSS, MANUAL, etc.
    
    # Paper trading specific fields
    signal = Column(String(20))        # BUY / SELL
    confidence = Column(Float)          # ML confidence 0-1
    stop_loss = Column(Float)
    projected_exit = Column(Float)
    peak_pnl = Column(Float)            # Best P&L during trade
    actual_profit_pct = Column(Float)   # Final P&L %
    breakeven_price = Column(Float)
    
    # Analysis documents (JSON format)
    pre_trade_json = Column(Text, default="{}")   # Full pre-trade report
    post_trade_json = Column(Text)                # Full post-trade report
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert ORM object to dictionary matching JSON format."""
        pre = {}
        post = None
        try:
            pre = json.loads(self.pre_trade_json) if self.pre_trade_json else {}
        except Exception:
            pass
        try:
            post = json.loads(self.post_trade_json) if self.post_trade_json else None
        except Exception:
            pass
        
        result = {
            "trade_id": self.trade_id,
            "status": self.status,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "trigger": self.trigger,
            "is_paper": self.is_paper,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "entry_price": self.entry_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "signal": self.signal,
            "confidence": self.confidence,
            "stop_loss": self.stop_loss,
            "projected_exit": self.projected_exit,
            "peak_pnl": self.peak_pnl,
            "actual_profit_pct": self.actual_profit_pct,
            "breakeven_price": self.breakeven_price,
            # Which model decided this trade. The column was added and is
            # populated on write, but was missing here — so every API response
            # and the whole dashboard dropped it silently, and a filled trade
            # looked like it came from nowhere. Attribution that exists in the
            # DB but never reaches the screen is the same as no attribution.
            "model_source": self.model_source,
            "pre_trade": pre,
            "post_trade": post,
        }
        return result

    __table_args__ = (
        Index("idx_journal_symbol_status", "symbol", "status"),
        Index("idx_journal_is_paper", "is_paper"),
    )


# ── Trade Log (replaces in-memory _trade_log) ───────────────────────────────

class TradeLogEntry(Base):
    """Persistent trade log — every order placed."""
    __tablename__ = "trade_log"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(4), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    order_id = Column(String(100))
    order_status = Column(String(50))
    remark = Column(Text)
    breakeven_price = Column(Float)
    est_charges = Column(Float)
    trade_id = Column(String(50))  # links to TradeJournalEntry
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "time": self.created_at.isoformat() if self.created_at else None,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "order_id": self.order_id,
            "status": self.order_status,
            "remark": self.remark,
            "breakeven_price": self.breakeven_price,
            "est_charges": self.est_charges,
            "trade_id": self.trade_id,
        }


# ── Unified Stock Thesis (replaces stock_thesis.json + .theses.json) ────────

class StockThesis(Base):
    """Unified thesis table — personal outlook + investment projection."""
    __tablename__ = "stock_theses"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    thesis_text = Column(Text)              # personal outlook narrative
    target_price = Column(Float)
    entry_price = Column(Float)
    quantity = Column(Integer)
    timeframe = Column(String(50))          # e.g. "Sep-Nov", "1-2 years"
    comments = Column(Text)                 # thesis_manager comments field
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "thesis": self.thesis_text,
            "target_price": self.target_price,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "timeframe": self.timeframe,
            "comments": self.comments,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Analysis Cache (replaces in-memory _cache dicts) ────────────────────────

class AnalysisCache(Base):
    """DB-backed cache for news, fundamentals, auto-analysis results."""
    __tablename__ = "analysis_cache"

    id = Column(Integer, primary_key=True)
    cache_key = Column(String(100), nullable=False, unique=True, index=True)
    cache_type = Column(String(30), nullable=False)  # "news", "fundamentals", "auto_analysis", "geopolitical"
    data_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_cache_type", "cache_type"),
    )


# ── Watchlist Notes (replaces watchlist_notes.json) ──────────────────────────

class WatchlistNote(Base):
    """Persistent watchlist notes — why a stock is being tracked."""
    __tablename__ = "watchlist_notes"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    note = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Paper Trades ─────────────────────────────────────────────────────────────

class PaperTrade(Base):
    """Simulated trades for paper trading mode."""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(4), nullable=False)           # BUY / SELL
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    segment = Column(String(20), default="CASH")       # CASH / FNO / COMMODITY
    product = Column(String(10), default="CNC")
    order_type = Column(String(20), default="MARKET")
    status = Column(String(20), default="FILLED")
    paper_order_id = Column(String(50))
    # Which model produced the signal — see TradeJournalEntry.model_source.
    model_source = Column(String(20), index=True)
    charges = Column(Float, default=0)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Trade Snapshots (full context saved at trade time for chart replay) ──────

class TradeSnapshot(Base):
    """Complete trade context — candles, indicators, news — for chart replay."""
    __tablename__ = "trade_snapshots"

    id = Column(Integer, primary_key=True)
    paper_order_id = Column(String(50), index=True)    # links to PaperTrade
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(4), nullable=False)            # BUY / SELL
    price = Column(Float, nullable=False)
    quantity = Column(Integer)
    segment = Column(String(20), default="CASH")

    # Candle data (OHLCV list — ~60 days around trade)
    candles_json = Column(Text)          # [{t,o,h,l,c,v}, ...]

    # Technical indicators at trade time
    indicators_json = Column(Text)       # {rsi, macd, sma_20, stoch_k, ...}

    # News headlines + sentiment at trade time
    news_json = Column(Text)             # [{title, sentiment, source, date}, ...]

    # AI reasoning / signal breakdown
    reasoning = Column(Text)
    signal = Column(String(10))          # BUY / SELL / HOLD
    confidence = Column(Float)
    combined_score = Column(Float)

    # Source scores breakdown
    sources_json = Column(Text)          # {ml, news, context, long_term}

    # Market context at trade time
    market_context_json = Column(Text)   # {nifty_trend, sector, volatility, ...}

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_snapshot_symbol_created", "symbol", "created_at"),
    )

    def to_dict(self):
        import json as _json
        def _parse(txt):
            if not txt:
                return None
            try:
                return _json.loads(txt)
            except Exception:
                return txt
        return {
            "id": self.id,
            "paper_order_id": self.paper_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "quantity": self.quantity,
            "segment": self.segment,
            "candles": _parse(self.candles_json),
            "indicators": _parse(self.indicators_json),
            "news": _parse(self.news_json),
            "reasoning": self.reasoning,
            "signal": self.signal,
            "confidence": self.confidence,
            "combined_score": self.combined_score,
            "sources": _parse(self.sources_json),
            "market_context": _parse(self.market_context_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── P&L Snapshots (track unrealised profit over time) ────────────────────────

class PnLSnapshot(Base):
    """Record unrealised P&L at regular intervals (every 5 seconds during market)."""
    __tablename__ = "pnl_snapshots"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=datetime.utcnow)
    total_pnl = Column(Float, nullable=False)           # Total unrealised P&L (₹)
    total_pnl_pct = Column(Float, nullable=False)       # Total unrealised P&L (%)
    trades_count = Column(Integer, default=0)           # Number of open trades
    peak_pnl = Column(Float, default=0)                 # Peak P&L reached in this session
    peak_pnl_pct = Column(Float, default=0)             # Peak P&L % 
    profit_trades = Column(Integer, default=0)          # Count of profitable trades
    loss_trades = Column(Integer, default=0)            # Count of losing trades
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_pnl_timestamp", "timestamp"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "trades_count": self.trades_count,
            "peak_pnl": self.peak_pnl,
            "peak_pnl_pct": self.peak_pnl_pct,
            "profit_trades": self.profit_trades,
            "loss_trades": self.loss_trades,
        }


# ── Config Settings (replaces hardcoded rates) ──────────────────────────────

class ConfigSetting(Base):
    """Dynamic config settings — brokerage rates, thresholds, etc."""
    __tablename__ = "config_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    description = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CandleTrainingMetadata(Base):
    """Track data collection and XGBoost model training events."""
    __tablename__ = "candle_training_metadata"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False)  # "collection" or "training"
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    total_candles = Column(Integer)  # Total candles in DB at time of event
    instruments_count = Column(Integer)  # Number of unique symbols with data
    training_samples = Column(Integer)  # For training events: X sample count
    model_version = Column(String(50))  # "long" / "short" / "both"
    win_rate_long = Column(Float)  # For training events: validation metric
    win_rate_short = Column(Float)
    notes = Column(Text)  # e.g., "collected 15 new NIFTY candles", "retrained with 1,264 samples"
    
    def __repr__(self):
        return f"<CandleTrainingMetadata {self.event_type} @ {self.timestamp}>"


# ── Company Connections (suppliers / customers from external sources) ────────

class CompanyConnection(Base):
    """
    Supplier/customer relationships between companies, scraped from external
    sources (Tijori Finance etc.). Tracks when relationships appear/disappear.
    """
    __tablename__ = "company_connections"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)       # our stock (e.g. ASIANPAINT)
    relation_type = Column(String(20), nullable=False)            # "supplier" / "customer" / "competitor"
    related_name = Column(String(200), nullable=False)            # e.g. "Atul Ltd."
    related_symbol = Column(String(20), index=True)               # NSE symbol if resolved (e.g. ATUL), else NULL
    related_slug = Column(String(200))                            # source page slug if known
    source = Column(String(50), default="tijori")                 # data source
    first_seen = Column(DateTime, default=datetime.utcnow)        # when we first saw this relationship
    last_seen = Column(DateTime, default=datetime.utcnow)         # last scrape that still listed it
    is_active = Column(Boolean, default=True)                     # False if it disappeared from source
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_conn_symbol_type_name", "symbol", "relation_type", "related_name", unique=True),
    )

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "relation_type": self.relation_type,
            "related_name": self.related_name,
            "related_symbol": self.related_symbol,
            "source": self.source,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_active": self.is_active,
        }


class CompanyExternalData(Base):
    """
    Snapshots of externally-sourced company data (ratios, peers, forensics,
    returns, market share...). Append-only: every scrape adds a new snapshot so
    we can compare current vs previous and analyse changes over time.
    """
    __tablename__ = "company_external_data"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    data_type = Column(String(50), nullable=False)   # "ratios" / "peers" / "returns" / "forensics" / "market_share" / "corporate_actions" / "company_info"
    source = Column(String(50), default="tijori")
    payload_json = Column(Text, nullable=False)      # raw structured JSON as scraped
    scraped_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_ext_symbol_type_time", "symbol", "data_type", "scraped_at"),
    )

    def get_payload(self):
        try:
            return json.loads(self.payload_json) if self.payload_json else None
        except Exception:
            return None


class ExternalSlugMap(Base):
    """
    Verified mapping of company name/symbol → external source page slug.
    Avoids re-guessing slugs on every scrape; self-heals when sources change.
    """
    __tablename__ = "external_slug_map"

    id = Column(Integer, primary_key=True)
    source = Column(String(50), default="tijori", nullable=False)
    company_name = Column(String(200), nullable=False)            # name we resolved from
    symbol = Column(String(20), index=True)                       # NSE symbol (may be NULL for unlisted)
    slug = Column(String(200))                                    # verified slug, NULL if resolution failed
    external_id = Column(String(50))                              # source's internal company id if available
    resolution_status = Column(String(20), default="pending")     # "resolved" / "unlisted" / "failed" / "pending"
    verified_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_slugmap_source_name", "source", "company_name", unique=True),
    )


# ── Idempotency (duplicate-order protection) ─────────────────────────────────

class IdempotencyKey(Base):
    """
    One row per client-supplied Idempotency-Key, scoped to an endpoint.

    Protects the money paths: if a buy request is retried — because the user
    double-clicked, or because the response was lost on the way back while the
    order actually went through — the retry replays the stored response instead
    of placing a second order.

    The `state` column is what makes a mid-flight retry safe. A row is inserted
    as "in_flight" BEFORE the handler runs, so a second request arriving while
    the first is still working sees the claim and is rejected rather than
    finding no record and executing a duplicate.

    `user_id` is nullable today and unused; it is here so the multi-tenant
    migration can scope keys per user without a second schema change.
    """
    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False)             # client-supplied UUID
    scope = Column(String(100), nullable=False)           # endpoint name, e.g. "buy"
    user_id = Column(Integer, index=True)                 # reserved for multi-tenant
    state = Column(String(20), nullable=False, default="in_flight")  # in_flight/completed/failed
    request_fingerprint = Column(String(64))              # sha256 of request body
    response_json = Column(Text)                          # stored response body to replay
    status_code = Column(Integer)                         # stored HTTP status to replay
    content_type = Column(String(100))                    # so replay reproduces the original type
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    __table_args__ = (
        # The uniqueness here is the concurrency primitive: two racing requests
        # both try to INSERT, and the database guarantees exactly one wins.
        Index("idx_idem_key_scope", "key", "scope", unique=True),
        Index("idx_idem_created", "created_at"),          # for retention pruning
    )


class CandleDatabase:
    """Database manager for candle storage and retrieval."""

    def __init__(self, db_url=None):
        """Initialize database connection."""
        if db_url is None:
            # Build from environment variables
            db_user = os.getenv("DB_USER", "postgres")
            db_pass = os.getenv("DB_PASSWORD", "postgres")
            db_host = os.getenv("DB_HOST", "localhost")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "grow_trading_bot")
            
            db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

        self.engine = create_engine(
            db_url,
            pool_size=5,
            max_overflow=10,
            echo=False,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=300,    # Recycle stale connections every 5 min
            connect_args={"connect_timeout": 3},
            pool_timeout=5,
        )
        Session = scoped_session(sessionmaker(bind=self.engine, expire_on_commit=False))
        self.Session = Session

    def init_db(self):
        """Create tables if they don't exist."""
        Base.metadata.create_all(self.engine)
        logger.info("✓ Database initialized")

    def insert_candles(self, symbol, candles_list):
        """
        Insert candles into database.
        
        Args:
            symbol: Stock symbol (e.g., 'RELIANCE')
            candles_list: List of dicts with keys: timestamp, open, high, low, close, volume
                         timestamp should be datetime object or convertible
        """
        if not candles_list:
            return
        
        session = self.Session()
        try:
            # Normalise every timestamp FIRST, then ask the DB once which of
            # them already exist. This was a .filter_by(symbol, timestamp)
            # .first() inside the loop — one round-trip PER CANDLE, so a
            # 500-candle batch cost 500 queries before inserting anything.
            #
            # The preload is bounded to the batch's own [min, max] range rather
            # than reading every candle for the symbol, so it stays small no
            # matter how large the table grows (CLAUDE.md standard 2). Only the
            # timestamp column is selected — the rows themselves are never
            # needed, just their existence.
            _parsed = []
            for candle_data in candles_list:
                if isinstance(candle_data["timestamp"], str):
                    ts = datetime.fromisoformat(candle_data["timestamp"])
                elif isinstance(candle_data["timestamp"], (int, float)):
                    ts = datetime.fromtimestamp(candle_data["timestamp"])
                else:
                    ts = candle_data["timestamp"]
                _parsed.append((ts, candle_data))

            _existing_ts = set()
            if _parsed:
                _lo = min(t for t, _ in _parsed)
                _hi = max(t for t, _ in _parsed)
                _existing_ts = {
                    r[0] for r in session.query(Candle.timestamp).filter(
                        Candle.symbol == symbol,
                        Candle.timestamp >= _lo,
                        Candle.timestamp <= _hi,
                    ).all()
                }

            for ts, candle_data in _parsed:
                if ts not in _existing_ts:
                    # Mirrors the autoflush the old .first() relied on: a batch
                    # containing the same timestamp twice must insert it once.
                    _existing_ts.add(ts)
                    candle = Candle(
                        symbol=symbol,
                        timestamp=ts,
                        open=float(candle_data["open"]),
                        high=float(candle_data["high"]),
                        low=float(candle_data["low"]),
                        close=float(candle_data["close"]),
                        volume=float(candle_data["volume"]),
                    )
                    session.add(candle)

            session.commit()
            logger.debug(f"✓ Inserted {len(candles_list)} candles for {symbol}")
        except Exception as e:
            session.rollback()
            logger.error(f"✗ Error inserting candles for {symbol}: {e}")
            raise
        finally:
            session.close()

    # Resolution tiers available in fyers_candles, finest first. '5S' covers
    # roughly the last 25 trading days (FYERS seconds retention), '1' covers
    # 2017-07-03 onward.
    #
    # THEY DO OVERLAP. An earlier note here claimed they did not and unioned
    # both tiers unconditionally; measured against the live DB, 5S began
    # 2026-07-13 while 1-minute ran to 2026-08-14, giving 1,680 symbol-days
    # carrying both. Because the resample sums volume, every trade in that
    # window was counted twice - exactly 2.0x on 1,864 of 1,875 RELIANCE bars,
    # with a hard 1x->2x step at the boundary. OHLC was unaffected (first/max/
    # min/last over a superset yields the same values), but volume_ratio is a
    # live model feature, so models trained on 1x history were being served 2x
    # bars. get_fyers_candles_as_5min() now keeps one tier per bucket.
    _FYERS_INTRADAY_TIERS = ("5S", "1")

    @staticmethod
    def _resolve_window(days, as_of):
        """
        Turn (days, as_of) into the (lower, upper) ts bounds these readers use.

        All three fyers readers were lower-bound-only: `ts >= now - days`, with
        no upper bound. That is correct for live use and WRONG for replay — a
        backtest asking for "the 1-day window as of 2026-05-13" would silently
        receive candles up to today, handing the model the future.

        `as_of` supplies the missing upper bound AND re-anchors the lower one,
        so `days` keeps meaning "this much history ending at as_of" rather than
        "ending now". Passing as_of=None reproduces the previous behaviour
        exactly, so every existing caller is unaffected.

        A naive as_of is read as IST — the convention these readers already
        return — because comparing a naive value against a TIMESTAMPTZ column
        would otherwise be resolved using the server's timezone.
        """
        if as_of is not None and as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=_IST)
        anchor = as_of or datetime.now(_IST)
        lower = anchor - timedelta(days=days) if days is not None else None
        return lower, as_of

    def get_fyers_candles_as_5min(self, symbol, days=None, as_of=None):
        """
        Read fyers_candles and return 5-minute bars in the exact shape
        get_candles() returns, so existing feature engineering, labels and
        models keep working unchanged.

        Two things this must get right, both verified empirically against the
        live DB (see docs/FYERS_CANDLE_MIGRATION_PLAN.md):

        1. TIMEZONE. fyers_candles.ts is TIMESTAMPTZ, and pandas reads it back
           as UTC-aware — 09:15 IST arrives as 03:45 UTC. The legacy `candles`
           table stored naive IST. predictor.build_features() derives
           time_of_day / is_opening / is_closing from .dt.hour and assumes
           naive IST, so the UTC form silently corrupts them (09:15 would read
           as hour 3). We convert to IST and drop the tzinfo, reproducing the
           legacy representation exactly.

        2. SESSION-ALIGNED RESAMPLING. Bucketing happens after the IST
           conversion. At 5-minute width this is belt-and-braces rather than
           strictly required — IST's +5:30 offset is a multiple of 5 minutes,
           so a UTC-midnight-anchored 5-minute grid happens to coincide with
           the IST-09:15 grid too (verified empirically). It would matter for
           an hourly or daily bucket width, so converting first is kept as
           the always-correct order rather than relying on that coincidence.

        Empty buckets are dropped rather than forward-filled: no candle is
        invented for a period with no source data.

        Args:
            symbol: canonical symbol, e.g. 'RELIANCE' (same convention as
                    the legacy table — fyers_candles uses identical strings)
            days: lookback window; None = all available history. Callers on
                  a hot path should always pass a bound — unbounded reads
                  resample a symbol's entire multi-year 1-minute history
                  (measured ~5s / ~770MB peak for a liquid name).
            as_of: optional point-in-time ceiling (see _resolve_window). None
                   keeps the original live behaviour; a value makes `days`
                   count back from as_of and excludes anything after it.

        Returns:
            DataFrame with columns: timestamp, datetime, open, high, low, close, volume
            (datetime is naive IST, matching get_candles())
        """
        try:
            lower, upper = self._resolve_window(days, as_of)
            frames = []
            for tier_rank, resolution in enumerate(self._FYERS_INTRADAY_TIERS):
                params = {"sym": symbol, "res": resolution}
                cutoff_sql = ""
                if lower is not None:
                    cutoff_sql += " AND ts >= :cutoff"
                    params["cutoff"] = lower
                if upper is not None:
                    cutoff_sql += " AND ts <= :as_of"
                    params["as_of"] = upper
                sql = text(
                    "SELECT ts, open, high, low, close, volume FROM fyers_candles "
                    f"WHERE symbol = :sym AND resolution = :res {cutoff_sql} ORDER BY ts"
                )
                part = pd.read_sql(sql, self.engine, params=params)
                if not part.empty:
                    part["_tier"] = tier_rank
                    frames.append(part)

            if not frames:
                return pd.DataFrame()

            df = pd.concat(frames, ignore_index=True)

            # UTC -> IST -> naive. Must happen before resampling so buckets
            # align to the trading session, not to UTC midnight.
            ts = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(_IST_NAME).dt.tz_localize(None)
            df = df.drop(columns=["ts"]).set_index(pd.DatetimeIndex(ts)).sort_index()

            # Keep exactly ONE tier per 5-minute bucket: the finest present.
            # Without this, overlapping 5S and 1-minute rows both land in the
            # same bucket and `volume: sum` double-counts them (see the note on
            # _FYERS_INTRADAY_TIERS). Choosing per BUCKET rather than per symbol
            # means a hole in 5S coverage falls back to 1-minute for just the
            # affected buckets instead of leaving a gap. Comparison is
            # positional because the index has duplicate timestamps across
            # tiers, which would make label-aligned comparison unreliable.
            tier = df["_tier"].to_numpy()
            finest = (
                pd.Series(tier)
                .groupby(df.index.floor("5min").values)
                .transform("min")
                .to_numpy()
            )
            df = df[tier == finest].drop(columns=["_tier"])

            agg = df.resample("5min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna(subset=["open"])

            if agg.empty:
                return pd.DataFrame()

            out = agg.reset_index(names="datetime")
            out = out.drop_duplicates(subset=["datetime"], keep="last").sort_values("datetime")
            out["timestamp"] = out["datetime"].astype("int64") // 10**9
            return out[["timestamp", "datetime", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        except Exception as e:
            logger.error(f"✗ Error fetching fyers candles for {symbol}: {e}")
            return pd.DataFrame()

    def get_fyers_1min(self, symbol, days=None, as_of=None):
        """
        NATIVE 1-minute bars from fyers_candles (resolution='1'), no
        resampling. Same output shape and same naive-IST `datetime`
        convention as get_candles()/get_fyers_candles_as_5min().

        Used by the cash XGBoost model, which trains and infers on native
        1-minute data. Because both training and live inference call this
        one method, they cannot drift onto different resolutions — the
        train/serve skew risk that the tiered 5-second/1-minute split would
        otherwise create.

        IST conversion is identical to the 5-minute adapter: the TIMESTAMPTZ
        column comes back from pandas as UTC-aware, so it is converted to
        Asia/Kolkata and then made naive, reproducing exactly what
        predictor.build_features() expects when it reads .dt.hour.
        """
        try:
            lower, upper = self._resolve_window(days, as_of)
            params = {"sym": symbol}
            cutoff_sql = ""
            if lower is not None:
                cutoff_sql += " AND ts >= :cutoff"
                params["cutoff"] = lower
            if upper is not None:
                cutoff_sql += " AND ts <= :as_of"
                params["as_of"] = upper
            sql = text(
                "SELECT ts, open, high, low, close, volume FROM fyers_candles "
                f"WHERE symbol = :sym AND resolution = '1' {cutoff_sql} ORDER BY ts"
            )
            df = pd.read_sql(sql, self.engine, params=params)
            if df.empty:
                return pd.DataFrame()
            df["datetime"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(_IST_NAME).dt.tz_localize(None)
            df = df.drop(columns=["ts"]).drop_duplicates(subset=["datetime"]).sort_values("datetime")
            df["timestamp"] = df["datetime"].astype("int64") // 10**9
            return df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        except Exception as e:
            logger.error(f"✗ Error fetching fyers 1-min candles for {symbol}: {e}")
            return pd.DataFrame()

    def get_fyers_daily(self, symbol, days=None, as_of=None):
        """
        Daily bars from fyers_candles (resolution='D'), same output shape as
        get_candles(). For consumers that want true daily data rather than
        intraday — no resampling involved, but the same IST normalisation
        applies so `datetime` means the same thing everywhere.
        """
        try:
            lower, upper = self._resolve_window(days, as_of)
            params = {"sym": symbol}
            cutoff_sql = ""
            if lower is not None:
                cutoff_sql += " AND ts >= :cutoff"
                params["cutoff"] = lower
            if upper is not None:
                cutoff_sql += " AND ts <= :as_of"
                params["as_of"] = upper
            sql = text(
                "SELECT ts, open, high, low, close, volume FROM fyers_candles "
                f"WHERE symbol = :sym AND resolution = 'D' {cutoff_sql} ORDER BY ts"
            )
            df = pd.read_sql(sql, self.engine, params=params)
            if df.empty:
                return pd.DataFrame()
            df["datetime"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(_IST_NAME).dt.tz_localize(None)
            df = df.drop(columns=["ts"])
            df["timestamp"] = df["datetime"].astype("int64") // 10**9
            return df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        except Exception as e:
            logger.error(f"✗ Error fetching fyers daily candles for {symbol}: {e}")
            return pd.DataFrame()

    def get_candles(self, symbol, days=None, interval_minutes=5):
        """
        Retrieve candles from the LEGACY Groww-sourced `candles` table using
        raw SQL for speed.

        NOTE: FYERS-sourced reads should use get_fyers_candles_as_5min() /
        get_fyers_daily() instead. This method is retained unchanged for the
        consumers that still legitimately read the legacy table.

        Args:
            symbol: Stock symbol
            days: Number of days to look back (None = all available)
            interval_minutes: Expected interval (for info only, DB stores raw candles)

        Returns:
            DataFrame with columns: timestamp, datetime, open, high, low, close, volume
        """
        try:
            if days:
                cutoff_time = datetime.utcnow() - timedelta(days=days)
                sql = text(
                    "SELECT timestamp, open, high, low, close, volume "
                    "FROM candles WHERE symbol = :sym AND timestamp >= :cutoff "
                    "ORDER BY timestamp"
                )
                df = pd.read_sql(sql, self.engine, params={"sym": symbol, "cutoff": cutoff_time})
            else:
                sql = text(
                    "SELECT timestamp, open, high, low, close, volume "
                    "FROM candles WHERE symbol = :sym ORDER BY timestamp"
                )
                df = pd.read_sql(sql, self.engine, params={"sym": symbol})

            if df.empty:
                return pd.DataFrame()

            df["datetime"] = pd.to_datetime(df["timestamp"])
            df["timestamp"] = df["datetime"].astype(int) // 10**9
            return df[["timestamp", "datetime", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        except Exception as e:
            logger.error(f"✗ Error fetching candles for {symbol}: {e}")
            return pd.DataFrame()

    def get_latest_timestamp(self, symbol):
        """
        Get the most recent candle timestamp for a symbol.
        
        Returns:
            datetime object or None if no data exists
        """
        session = self.Session()
        try:
            latest = session.query(Candle).filter_by(symbol=symbol).order_by(
                Candle.timestamp.desc()
            ).first()
            result = latest.timestamp if latest else None
            session.close()
            return result
        except Exception as e:
            logger.error(f"✗ Error getting latest timestamp for {symbol}: {e}")
            session.close()
            return None

    def get_missing_dates(self, symbol, end_date=None, expected_interval_minutes=5):
        """
        Identify missing candle dates to determine what needs to be synced from API.
        
        Args:
            symbol: Stock symbol
            end_date: End date for check (default: now)
            expected_interval_minutes: Expected interval to identify gaps
        
        Returns:
            Tuple of (has_gaps, first_missing_date, latest_timestamp)
        """
        session = self.Session()
        try:
            latest = session.query(Candle).filter_by(symbol=symbol).order_by(
                Candle.timestamp.desc()
            ).first()
            session.close()

            if not latest:
                return (True, None, None)  # No data yet

            latest_ts = latest.timestamp
            now = end_date or datetime.utcnow()
            
            # Calculate expected candles since latest
            minutes_since = (now - latest_ts).total_seconds() / 60
            expected_candles = int(round(minutes_since / expected_interval_minutes))

            # If significantly fewer candles than expected, we have a gap
            if expected_candles > 5:  # More than 5 candles worth of gap
                return (True, latest_ts + timedelta(minutes=expected_interval_minutes), latest_ts)
            
            return (False, None, latest_ts)
        except Exception as e:
            logger.error(f"✗ Error checking missing dates for {symbol}: {e}")
            return (True, None, None)

    def prune_old_candles(self, symbol, keep_days=365):
        """
        Delete candles older than keep_days for a symbol (optional cleanup).
        
        Args:
            symbol: Stock symbol
            keep_days: Keep only this many days of data
        """
        session = self.Session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=keep_days)
            deleted = session.query(Candle).filter_by(symbol=symbol).filter(
                Candle.timestamp < cutoff
            ).delete()
            session.commit()
            logger.info(f"✓ Pruned {deleted} old candles for {symbol}")
        except Exception as e:
            session.rollback()
            logger.error(f"✗ Error pruning candles for {symbol}: {e}")
        finally:
            session.close()

    def get_stats(self):
        """Get database statistics."""
        session = self.Session()
        try:
            total_candles = session.query(Candle).count()
            symbols = session.query(Candle.symbol).distinct().count()
            session.close()
            return {"total_candles": total_candles, "symbols": symbols}
        except Exception as e:
            logger.error(f"✗ Error getting stats: {e}")
            session.close()
            return {}


# Global database instance
_db = None


def get_db(db_url=None):
    """Get or create global database instance."""
    global _db
    if _db is None:
        _db = CandleDatabase(db_url)
        _db.init_db()
    return _db


# ── Stock helpers ────────────────────────────────────────────────────────────

def get_all_stocks(db=None):
    """Get all active stocks from DB."""
    db = db or get_db()
    session = db.Session()
    try:
        stocks = session.query(Stock).filter_by(is_active=True).all()
        return stocks
    finally:
        session.close()


def get_stock(symbol, db=None):
    """Get a single stock by symbol."""
    db = db or get_db()
    session = db.Session()
    try:
        return session.query(Stock).filter_by(symbol=symbol.upper()).first()
    finally:
        session.close()


def get_stock_name(symbol, db=None):
    """Get company name for a symbol. Falls back to symbol itself."""
    stock = get_stock(symbol, db)
    return stock.company_name if stock else symbol.upper()


def get_sector_map(db=None):
    """Build SECTOR_MAP dict from DB: {symbol: sector}."""
    stocks = get_all_stocks(db)
    return {s.symbol: s.sector for s in stocks if s.sector}


def get_competitors(symbol, db=None):
    """Get competitors list for a symbol from DB."""
    stock = get_stock(symbol, db)
    return stock.get_competitors() if stock else []


def get_commodity_map(db=None):
    """Build COMMODITY_MAP dict from DB for stocks with commodity dependency."""
    stocks = get_all_stocks(db)
    result = {}
    for s in stocks:
        if s.commodity and s.commodity_ticker:
            result[s.symbol] = {
                "commodity": s.commodity,
                "ticker": s.commodity_ticker,
                "relationship": s.commodity_relationship or "direct",
                "weight": s.commodity_weight or 0,
            }
    return result


def get_symbol_names(db=None):
    """Build SYMBOL_NAMES dict from DB: {symbol: company_name}."""
    stocks = get_all_stocks(db)
    return {s.symbol: s.company_name for s in stocks}


# ── Watchlist Note helpers ───────────────────────────────────────────────────

def get_watchlist_note(symbol, db=None):
    """Get watchlist note for a symbol."""
    db = db or get_db()
    session = db.Session()
    try:
        note = session.query(WatchlistNote).filter_by(symbol=symbol.upper()).first()
        return note.note if note else ""
    finally:
        session.close()


def save_watchlist_note(symbol, note_text, db=None):
    """Save/update watchlist note."""
    db = db or get_db()
    session = db.Session()
    try:
        existing = session.query(WatchlistNote).filter_by(symbol=symbol.upper()).first()
        if note_text:
            if existing:
                existing.note = note_text
                existing.updated_at = datetime.utcnow()
            else:
                session.add(WatchlistNote(symbol=symbol.upper(), note=note_text))
        elif existing:
            session.delete(existing)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error saving watchlist note: {e}")
    finally:
        session.close()


# ── Analysis Cache helpers ───────────────────────────────────────────────────

def get_cached(cache_key, ttl_seconds=600, db=None):
    """Get cached data if still fresh. Returns parsed JSON or None."""
    db = db or get_db()
    session = db.Session()
    try:
        entry = session.query(AnalysisCache).filter_by(cache_key=cache_key).first()
        if entry and entry.updated_at:
            age = (datetime.utcnow() - entry.updated_at).total_seconds()
            if age < ttl_seconds:
                return json.loads(entry.data_json)
        return None
    except Exception:
        return None
    finally:
        session.close()


def set_cached(cache_key, data, cache_type="general", db=None):
    """Store data in cache."""
    db = db or get_db()
    session = db.Session()
    try:
        existing = session.query(AnalysisCache).filter_by(cache_key=cache_key).first()
        data_str = json.dumps(data, default=str)
        if existing:
            existing.data_json = data_str
            existing.cache_type = cache_type
            existing.updated_at = datetime.utcnow()
        else:
            session.add(AnalysisCache(
                cache_key=cache_key, cache_type=cache_type, data_json=data_str
            ))
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error caching data: {e}")
    finally:
        session.close()


# ── Config Setting helpers ───────────────────────────────────────────────────

# Short-lived memo so hot paths (scheduler loops, tijori HTTP helpers, the
# settings endpoints) don't open a session + SELECT for every single lookup.
# Writes through set_config invalidate immediately, so saving from the Settings
# tab still takes effect at once; the TTL only bounds staleness for values
# changed directly in the DB by another process.
_CONFIG_CACHE_TTL = 30.0
_config_cache = {}
_config_cache_lock = threading.Lock()


def invalidate_config_cache(key=None):
    """Drop one key (or the whole config memo) so the next read hits the DB."""
    with _config_cache_lock:
        if key is None:
            _config_cache.clear()
        else:
            _config_cache.pop(key, None)


def get_config(key, default=None, db=None):
    """Get a config value from DB (memoized for _CONFIG_CACHE_TTL seconds)."""
    now = time.monotonic()
    with _config_cache_lock:
        hit = _config_cache.get(key)
        if hit and hit[1] > now:
            return hit[0] if hit[0] is not None else default

    db = db or get_db()
    session = db.Session()
    try:
        entry = session.query(ConfigSetting).filter_by(key=key).first()
        value = entry.value if entry else None
    finally:
        session.close()

    with _config_cache_lock:
        _config_cache[key] = (value, time.monotonic() + _CONFIG_CACHE_TTL)
    return value if value is not None else default


def get_configs(keys, db=None):
    """Batch-read many config keys in ONE query. Returns {key: value} for keys
    that exist. Use this instead of calling get_config in a loop."""
    keys = list(keys)
    if not keys:
        return {}
    db = db or get_db()
    session = db.Session()
    try:
        rows = session.query(ConfigSetting).filter(ConfigSetting.key.in_(keys)).all()
        out = {r.key: r.value for r in rows}
    finally:
        session.close()

    expiry = time.monotonic() + _CONFIG_CACHE_TTL
    with _config_cache_lock:
        for k in keys:
            _config_cache[k] = (out.get(k), expiry)
    return out


def get_configs_prefix(prefix, db=None):
    """Batch-read every config key starting with `prefix` in ONE query."""
    db = db or get_db()
    session = db.Session()
    try:
        rows = (session.query(ConfigSetting)
                .filter(ConfigSetting.key.like(f"{prefix}%")).all())
        return {r.key: r.value for r in rows}
    finally:
        session.close()


def set_config(key, value, description=None, db=None):
    """Set a config value in DB."""
    db = db or get_db()
    session = db.Session()
    try:
        existing = session.query(ConfigSetting).filter_by(key=key).first()
        if existing:
            existing.value = str(value)
            if description:
                existing.description = description
            existing.updated_at = datetime.utcnow()
        else:
            session.add(ConfigSetting(key=key, value=str(value), description=description))
        session.commit()
        invalidate_config_cache(key)
    except Exception as e:
        session.rollback()
        logger.error(f"Error setting config: {e}")
    finally:
        session.close()


# ── Idempotency helpers ──────────────────────────────────────────────────────
# These back the @idempotent decorator in app.py. They are deliberately
# low-level and side-effect free apart from their own table, so they can be
# unit-tested without Flask.

# Outcomes of trying to claim a key:
IDEM_CLAIMED = "claimed"        # we own it — caller should run the handler
IDEM_REPLAY = "replay"          # already completed — return the stored response
IDEM_IN_FLIGHT = "in_flight"    # another request is running right now
IDEM_MISMATCH = "mismatch"      # same key, different request body
IDEM_INVALID = "invalid"        # key unusable (empty / longer than the column)

# Must match the `key` column width. A longer key would raise DataError on
# INSERT, and an error on the claim path is exactly where a silent fail-open
# would disable protection entirely — so oversize keys are rejected up front.
IDEM_KEY_MAX_LEN = 255
IDEM_SCOPE_MAX_LEN = 100


def _idem_rollback(session):
    """Roll back, swallowing a secondary failure on an already-broken session."""
    try:
        session.rollback()
    except Exception as e:
        logger.error("Idempotency rollback failed: %s", e)


def _idem_close(session):
    """
    Close, swallowing a secondary failure.

    If a broken connection made close() raise out of a finally block, the
    exception would escape the claim and 500 the request. These helpers sit on
    the money path, so cleanup must never be the thing that breaks it.
    """
    try:
        session.close()
    except Exception as e:
        logger.error("Idempotency session close failed: %s", e)


def claim_idempotency_key(key, scope, fingerprint=None, user_id=None, db=None):
    """
    Atomically claim an idempotency key before running a money-path handler.

    Returns (outcome, record_dict_or_None). The uniqueness constraint on
    (key, scope) is what makes this safe under concurrency: two racing requests
    both attempt the INSERT and the database lets exactly one through, so the
    loser gets IDEM_IN_FLIGHT instead of placing a second order.

    A previously FAILED key is re-claimable — the order did not go through, so
    letting the user retry is correct.

    Failure policy is asymmetric on purpose:
      * INSERT path fails OPEN — if the table is unreachable (not migrated yet,
        DB down), we have learned nothing about this key, so behaviour reverts
        to what it was before this feature existed.
      * Every path AFTER a duplicate has been PROVEN fails CLOSED. Once the
        unique index has told us a row exists, we know a request with this key
        is in flight or done; letting the handler run anyway would manufacture
        the exact duplicate this table exists to prevent.
    """
    # Bound the inputs before they reach the driver. Oversize values raise
    # DataError, which is a sibling of IntegrityError rather than a subclass,
    # so it would otherwise land in the fail-open branch and quietly turn
    # protection off for every request carrying that key.
    if not key or len(key) > IDEM_KEY_MAX_LEN:
        logger.warning(
            "Rejecting unusable idempotency key for %s (empty or >%d chars)",
            scope, IDEM_KEY_MAX_LEN,
        )
        return IDEM_INVALID, None
    if not scope or len(scope) > IDEM_SCOPE_MAX_LEN:
        logger.error("Idempotency scope %r is empty or too long — refusing to claim", scope)
        return IDEM_INVALID, None

    db = db or get_db()
    session = db.Session()
    try:
        # Fast path: try to take the key. If nobody holds it, we win.
        rec = IdempotencyKey(
            key=key, scope=scope, user_id=user_id,
            state="in_flight", request_fingerprint=fingerprint,
        )
        session.add(rec)
        session.commit()
        return IDEM_CLAIMED, None
    except IntegrityError:
        # Someone already holds this key — inspect what state it is in.
        _idem_rollback(session)
    except DataError as e:
        # Malformed input rather than broken infrastructure. Length is already
        # checked above, so this means something we did not anticipate — treat
        # it as a bad request, never as permission to place the order.
        _idem_rollback(session)
        logger.error("Idempotency claim rejected bad data for %s/%s: %s", scope, key, e)
        return IDEM_INVALID, None
    except Exception as e:
        _idem_rollback(session)
        logger.error("Idempotency claim failed for %s/%s: %s", scope, key, e)
        # Fail OPEN here only: nothing is known about this key yet, so this
        # restores pre-feature behaviour rather than creating a new hazard.
        return IDEM_CLAIMED, None
    finally:
        _idem_close(session)

    # ── A row exists. From here on, a duplicate is PROVEN — fail closed. ──
    session = db.Session()
    try:
        existing = session.query(IdempotencyKey).filter_by(key=key, scope=scope).first()
        if existing is None:
            # The INSERT hit the unique index, yet the row is gone — a prune or
            # a rollback landed in between. Retry the claim once; if that also
            # fails we refuse rather than run unrecorded, because a handler that
            # runs with no row leaves nothing for a retry to replay.
            logger.warning(
                "Idempotency row for %s/%s vanished after a unique-constraint "
                "hit — retrying the claim once", scope, key,
            )
            try:
                retry = IdempotencyKey(
                    key=key, scope=scope, user_id=user_id,
                    state="in_flight", request_fingerprint=fingerprint,
                )
                session.add(retry)
                session.commit()
                return IDEM_CLAIMED, None
            except Exception:
                _idem_rollback(session)
                logger.error(
                    "Idempotency re-claim for %s/%s failed — refusing to run "
                    "the handler unrecorded", scope, key,
                )
                return IDEM_IN_FLIGHT, None

        # The failed case is checked BEFORE the fingerprint comparison: a failed
        # attempt placed nothing, so there is no stored result to protect and a
        # corrected payload under the same key is legitimate.
        if existing.state == "failed":
            # Previous attempt errored out before placing anything, so a retry
            # is legitimate — but read-then-write is not safe here. Two retries
            # can both read "failed" and both proceed, and this is the one path
            # the unique index does not cover. A conditional UPDATE lets the
            # database pick the winner: exactly one gets rowcount == 1.
            #
            # created_at is deliberately NOT refreshed, so a key that keeps
            # failing still ages out of the retention window on schedule.
            result = session.execute(
                update(IdempotencyKey)
                .where(
                    IdempotencyKey.id == existing.id,
                    IdempotencyKey.state == "failed",
                )
                .values(
                    state="in_flight",
                    request_fingerprint=fingerprint,
                    completed_at=None,
                )
            )
            session.commit()
            if result.rowcount == 1:
                return IDEM_CLAIMED, None
            # Lost the race — the other retry owns it now.
            logger.warning(
                "Concurrent retry of failed key %s/%s — rejecting this one", scope, key,
            )
            return IDEM_IN_FLIGHT, None

        if fingerprint and existing.request_fingerprint and \
                existing.request_fingerprint != fingerprint:
            # Same key reused for a DIFFERENT payload — a client bug we must
            # surface loudly rather than silently replaying the wrong response.
            return IDEM_MISMATCH, None

        if existing.state == "completed":
            return IDEM_REPLAY, {
                "response_json": existing.response_json,
                "status_code": existing.status_code,
                "content_type": existing.content_type,
            }

        return IDEM_IN_FLIGHT, None
    except Exception as e:
        _idem_rollback(session)
        logger.error("Idempotency lookup failed for %s/%s: %s", scope, key, e)
        # We only get here because the INSERT proved a row exists. Failing open
        # would place a second order on a key we KNOW is already taken.
        return IDEM_IN_FLIGHT, None
    finally:
        _idem_close(session)


def complete_idempotency_key(key, scope, response_json, status_code,
                             content_type=None, db=None):
    """Record the handler's result so a later retry replays it verbatim."""
    db = db or get_db()
    session = db.Session()
    try:
        rec = session.query(IdempotencyKey).filter_by(key=key, scope=scope).first()
        if rec is None:
            # The handler ran but there is nothing to attach its result to, so a
            # retry would execute again. Never silent — this is the shape of a
            # duplicate order and an operator needs to see it.
            logger.error(
                "No idempotency row to complete for %s/%s — the handler ran but "
                "its result was NOT stored, so a retry would re-execute it",
                scope, key,
            )
            return
        rec.state = "completed"
        rec.response_json = response_json
        rec.status_code = status_code
        rec.content_type = content_type
        rec.completed_at = datetime.utcnow()
        session.commit()
    except Exception as e:
        _idem_rollback(session)
        logger.error("Idempotency completion failed for %s/%s: %s", scope, key, e)
    finally:
        _idem_close(session)


def fail_idempotency_key(key, scope, db=None):
    """
    Mark a key failed so the user can retry.

    Only call this when the handler raised BEFORE any order could have been
    placed. If we are unsure whether the broker received the order, the key
    must stay in_flight — a stuck key is far cheaper than a duplicate trade.
    """
    db = db or get_db()
    session = db.Session()
    try:
        rec = session.query(IdempotencyKey).filter_by(key=key, scope=scope).first()
        if rec is None:
            return
        rec.state = "failed"
        rec.completed_at = datetime.utcnow()
        session.commit()
    except Exception as e:
        _idem_rollback(session)
        logger.error("Idempotency failure-marking failed for %s/%s: %s", scope, key, e)
    finally:
        _idem_close(session)


def prune_idempotency_keys(retention_hours=48, db=None):
    """Delete keys older than the retention window. Returns rows removed."""
    db = db or get_db()
    session = db.Session()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=int(retention_hours))
        removed = session.query(IdempotencyKey).filter(
            IdempotencyKey.created_at < cutoff
        ).delete(synchronize_session=False)
        session.commit()
        return removed
    except Exception as e:
        _idem_rollback(session)
        logger.error("Idempotency prune failed: %s", e)
        return 0
    finally:
        _idem_close(session)


# ── Seed data — populate Stock table on first run ────────────────────────────

def seed_stocks(db=None):
    """Populate Stock table with known stocks if empty. Safe to call repeatedly."""
    db = db or get_db()
    session = db.Session()
    try:
        count = session.query(Stock).count()
        if count > 0:
            return  # already seeded

        # Merged from STOCK_DIRECTORY + SECTOR_MAP + SECTOR + COMPETITORS + COMMODITY_MAP + SYMBOL_NAMES
        SEED = [
            # Banking
            {"symbol": "HDFCBANK", "company_name": "HDFC Bank", "sector": "BANKING", "sector_display": "Banking", "competitors": ["ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"]},
            {"symbol": "ICICIBANK", "company_name": "ICICI Bank", "sector": "BANKING", "sector_display": "Banking", "competitors": ["HDFCBANK", "SBIN", "KOTAKBANK", "AXISBANK"]},
            {"symbol": "SBIN", "company_name": "State Bank of India", "sector": "BANKING", "sector_display": "Banking (PSU)", "competitors": ["HDFCBANK", "ICICIBANK", "BANKBARODA", "PNB"]},
            {"symbol": "KOTAKBANK", "company_name": "Kotak Mahindra Bank", "sector": "BANKING", "sector_display": "Banking"},
            {"symbol": "AXISBANK", "company_name": "Axis Bank", "sector": "BANKING", "sector_display": "Banking"},
            {"symbol": "BAJFINANCE", "company_name": "Bajaj Finance", "sector": "BANKING", "sector_display": "NBFC"},
            {"symbol": "INDUSINDBK", "company_name": "IndusInd Bank", "sector": "BANKING", "sector_display": "Banking"},
            {"symbol": "BANKBARODA", "company_name": "Bank of Baroda", "sector": "BANKING", "sector_display": "Banking (PSU)"},
            {"symbol": "PNB", "company_name": "Punjab National Bank", "sector": "BANKING", "sector_display": "Banking (PSU)"},
            # IT
            {"symbol": "TCS", "company_name": "Tata Consultancy Services", "sector": "IT", "sector_display": "IT Services", "competitors": ["INFY", "WIPRO", "HCLTECH", "TECHM", "LTI"], "commodity": "USD/INR", "commodity_ticker": "USDINR=X", "commodity_relationship": "direct", "commodity_weight": 0.20},
            {"symbol": "INFY", "company_name": "Infosys", "sector": "IT", "sector_display": "IT Services", "competitors": ["TCS", "WIPRO", "HCLTECH", "TECHM", "LTI"], "commodity": "USD/INR", "commodity_ticker": "USDINR=X", "commodity_relationship": "direct", "commodity_weight": 0.20},
            {"symbol": "WIPRO", "company_name": "Wipro", "sector": "IT", "sector_display": "IT Services", "competitors": ["TCS", "INFY", "HCLTECH", "TECHM"], "commodity": "USD/INR", "commodity_ticker": "USDINR=X", "commodity_relationship": "direct", "commodity_weight": 0.20},
            {"symbol": "HCLTECH", "company_name": "HCL Technologies", "sector": "IT", "sector_display": "IT Services", "commodity": "USD/INR", "commodity_ticker": "USDINR=X", "commodity_relationship": "direct", "commodity_weight": 0.20},
            {"symbol": "TECHM", "company_name": "Tech Mahindra", "sector": "IT", "sector_display": "IT Services"},
            {"symbol": "LTI", "company_name": "LTIMindtree", "sector": "IT", "sector_display": "IT Services"},
            {"symbol": "MPHASIS", "company_name": "Mphasis", "sector": "IT", "sector_display": "IT Services"},
            # Energy
            {"symbol": "RELIANCE", "company_name": "Reliance Industries", "sector": "ENERGY", "sector_display": "Conglomerate / Oil & Gas", "competitors": ["TCS", "INFY", "HDFCBANK", "ICICIBANK"], "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "direct", "commodity_weight": 0.25},
            {"symbol": "ONGC", "company_name": "ONGC", "sector": "ENERGY", "sector_display": "Oil & Gas", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "direct", "commodity_weight": 0.50},
            {"symbol": "BPCL", "company_name": "BPCL", "sector": "ENERGY", "sector_display": "Oil Marketing", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.30},
            {"symbol": "IOC", "company_name": "Indian Oil Corporation", "sector": "ENERGY", "sector_display": "Oil Marketing", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.30},
            {"symbol": "NTPC", "company_name": "NTPC", "sector": "ENERGY", "sector_display": "Power"},
            {"symbol": "POWERGRID", "company_name": "Power Grid Corporation", "sector": "ENERGY", "sector_display": "Power"},
            # FMCG
            {"symbol": "HINDUNILVR", "company_name": "Hindustan Unilever", "sector": "FMCG", "sector_display": "FMCG"},
            {"symbol": "ITC", "company_name": "ITC Limited", "sector": "FMCG", "sector_display": "FMCG / Tobacco", "competitors": ["HINDUNILVR", "DABUR", "MARICO", "GODREJCP"]},
            {"symbol": "NESTLEIND", "company_name": "Nestle India", "sector": "FMCG", "sector_display": "FMCG"},
            {"symbol": "BRITANNIA", "company_name": "Britannia Industries", "sector": "FMCG", "sector_display": "FMCG"},
            {"symbol": "DABUR", "company_name": "Dabur India", "sector": "FMCG", "sector_display": "FMCG"},
            {"symbol": "MARICO", "company_name": "Marico", "sector": "FMCG", "sector_display": "FMCG"},
            {"symbol": "GODREJCP", "company_name": "Godrej Consumer Products", "sector": "FMCG", "sector_display": "FMCG"},
            # Auto
            {"symbol": "MARUTI", "company_name": "Maruti Suzuki", "sector": "AUTO", "sector_display": "Auto"},
            {"symbol": "TATAMOTORS", "company_name": "Tata Motors", "sector": "AUTO", "sector_display": "Auto"},
            {"symbol": "M&M", "company_name": "Mahindra & Mahindra", "sector": "AUTO", "sector_display": "Auto"},
            {"symbol": "BAJAJ-AUTO", "company_name": "Bajaj Auto", "sector": "AUTO", "sector_display": "Auto"},
            {"symbol": "EICHERMOT", "company_name": "Eicher Motors", "sector": "AUTO", "sector_display": "Auto"},
            {"symbol": "HEROMOTOCO", "company_name": "Hero MotoCorp", "sector": "AUTO", "sector_display": "Auto"},
            # Pharma
            {"symbol": "SUNPHARMA", "company_name": "Sun Pharma", "sector": "PHARMA", "sector_display": "Pharma"},
            {"symbol": "DRREDDY", "company_name": "Dr. Reddy's", "sector": "PHARMA", "sector_display": "Pharma"},
            {"symbol": "CIPLA", "company_name": "Cipla", "sector": "PHARMA", "sector_display": "Pharma"},
            {"symbol": "DIVISLAB", "company_name": "Divi's Laboratories", "sector": "PHARMA", "sector_display": "Pharma"},
            {"symbol": "APOLLOHOSP", "company_name": "Apollo Hospitals", "sector": "PHARMA", "sector_display": "Healthcare"},
            # Metals
            {"symbol": "TATASTEEL", "company_name": "Tata Steel", "sector": "METALS", "sector_display": "Steel", "commodity": "Iron Ore / Steel", "commodity_ticker": "TIO=F", "commodity_relationship": "direct", "commodity_weight": 0.40},
            {"symbol": "JSWSTEEL", "company_name": "JSW Steel", "sector": "METALS", "sector_display": "Steel", "commodity": "Iron Ore / Steel", "commodity_ticker": "TIO=F", "commodity_relationship": "direct", "commodity_weight": 0.40},
            {"symbol": "HINDALCO", "company_name": "Hindalco Industries", "sector": "METALS", "sector_display": "Aluminium", "commodity": "Aluminium", "commodity_ticker": "ALI=F", "commodity_relationship": "direct", "commodity_weight": 0.45},
            {"symbol": "VEDL", "company_name": "Vedanta", "sector": "METALS", "sector_display": "Base Metals", "commodity": "Zinc / Base Metals", "commodity_ticker": "ZNC=F", "commodity_relationship": "direct", "commodity_weight": 0.35},
            {"symbol": "COALINDIA", "company_name": "Coal India", "sector": "METALS", "sector_display": "Coal", "commodity": "Coal", "commodity_ticker": "BTU", "commodity_relationship": "direct", "commodity_weight": 0.50},
            # Infra / Telecom / Cement
            {"symbol": "LT", "company_name": "Larsen & Toubro", "sector": "INFRA", "sector_display": "Engineering / Infrastructure", "competitors": ["SIEMENS", "ABB", "BHEL", "THERMAX"]},
            {"symbol": "BHARTIARTL", "company_name": "Bharti Airtel", "sector": "TELECOM", "sector_display": "Telecom", "competitors": ["JIO", "VODAFONEIDEA", "TATACOMM"]},
            {"symbol": "ULTRACEMCO", "company_name": "UltraTech Cement", "sector": "CEMENT", "sector_display": "Cement"},
            {"symbol": "GRASIM", "company_name": "Grasim Industries", "sector": "CEMENT", "sector_display": "Cement"},
            # Paints
            {"symbol": "ASIANPAINT", "company_name": "Asian Paints", "sector": "CONSUMER", "sector_display": "Paints & Coatings", "competitors": ["BERGEPAINT", "NEROLAC", "INDIGO", "AKZONOBEL"], "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.35},
            {"symbol": "BERGEPAINT", "company_name": "Berger Paints", "sector": "CONSUMER", "sector_display": "Paints & Coatings", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.35},
            {"symbol": "NEROLAC", "company_name": "Nerolac Paints", "sector": "CONSUMER", "sector_display": "Paints"},
            {"symbol": "INDIGO", "company_name": "Indigo Paints", "sector": "CONSUMER", "sector_display": "Paints"},
            {"symbol": "AKZONOBEL", "company_name": "Akzo Nobel India", "sector": "CONSUMER", "sector_display": "Paints"},
            {"symbol": "KANSAINER", "company_name": "Kansai Nerolac Paints", "sector": "CONSUMER", "sector_display": "Paints", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.30},
            # Renewable Energy
            {"symbol": "SUZLON", "company_name": "Suzlon Energy", "sector": "ENERGY", "sector_display": "Renewable Energy", "competitors": ["TATAPOWER", "ADANIGREEN", "INOXWIND", "JSWEN"]},
            {"symbol": "TATAPOWER", "company_name": "Tata Power", "sector": "ENERGY", "sector_display": "Power / Renewable"},
            {"symbol": "ADANIGREEN", "company_name": "Adani Green Energy", "sector": "ENERGY", "sector_display": "Renewable Energy"},
            {"symbol": "INOXWIND", "company_name": "Inox Wind", "sector": "ENERGY", "sector_display": "Wind Energy"},
            {"symbol": "JSWEN", "company_name": "JSW Energy", "sector": "ENERGY", "sector_display": "Energy"},
            # Others
            {"symbol": "GEMAROMA", "company_name": "Gemaroma", "sector": "CONSUMER", "sector_display": "Chemicals / Fragrances", "competitors": []},
            {"symbol": "SIEMENS", "company_name": "Siemens", "sector": "INFRA", "sector_display": "Industrial"},
            {"symbol": "ABB", "company_name": "ABB India", "sector": "INFRA", "sector_display": "Industrial"},
            {"symbol": "BHEL", "company_name": "BHEL", "sector": "INFRA", "sector_display": "Power Equipment"},
            {"symbol": "THERMAX", "company_name": "Thermax", "sector": "INFRA", "sector_display": "Industrial"},
            {"symbol": "TATACOMM", "company_name": "Tata Communications", "sector": "TELECOM", "sector_display": "Telecom"},
            {"symbol": "VODAFONEIDEA", "company_name": "Vodafone Idea", "sector": "TELECOM", "sector_display": "Telecom"},
            # Gold / Jewellers
            {"symbol": "TITAN", "company_name": "Titan Company", "sector": "CONSUMER", "sector_display": "Jewellery / Watches", "commodity": "Gold", "commodity_ticker": "GC=F", "commodity_relationship": "direct", "commodity_weight": 0.30},
            {"symbol": "KALYANKJIL", "company_name": "Kalyan Jewellers", "sector": "CONSUMER", "sector_display": "Jewellery", "commodity": "Gold", "commodity_ticker": "GC=F", "commodity_relationship": "direct", "commodity_weight": 0.40},
            # Aviation
            {"symbol": "SPICEJET", "company_name": "SpiceJet", "sector": "AUTO", "sector_display": "Aviation", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.45},
            # Tyres
            {"symbol": "APOLLOTYRE", "company_name": "Apollo Tyres", "sector": "AUTO", "sector_display": "Tyres", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.25},
            {"symbol": "MRF", "company_name": "MRF", "sector": "AUTO", "sector_display": "Tyres", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.25},
            # Chemicals
            {"symbol": "PIDILITIND", "company_name": "Pidilite Industries", "sector": "CONSUMER", "sector_display": "Adhesives / Chemicals", "commodity": "Crude Oil", "commodity_ticker": "CL=F", "commodity_relationship": "inverse", "commodity_weight": 0.20},
        ]

        for s in SEED:
            stock = Stock(
                symbol=s["symbol"],
                company_name=s["company_name"],
                sector=s.get("sector"),
                sector_display=s.get("sector_display"),
                competitors_json=json.dumps(s.get("competitors", [])),
                commodity=s.get("commodity"),
                commodity_ticker=s.get("commodity_ticker"),
                commodity_relationship=s.get("commodity_relationship"),
                commodity_weight=s.get("commodity_weight", 0),
            )
            session.add(stock)

        session.commit()
        logger.info(f"✓ Seeded {len(SEED)} stocks into DB")
    except Exception as e:
        session.rollback()
        logger.error(f"Error seeding stocks: {e}")
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE TRAINING METADATA LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

def log_candle_collection_event(collected_count, duplicate_count):
    """Log completion of hourly candle collection task."""
    db = get_db()
    session = db.Session()
    try:
        total_candles = session.query(Candle).count()
        unique_symbols = session.query(Candle.symbol).distinct().count()
        
        event = CandleTrainingMetadata(
            event_type="collection",
            total_candles=total_candles,
            instruments_count=unique_symbols,
            notes=f"Collected {collected_count} new, {duplicate_count} duplicates skipped",
        )
        session.add(event)
        session.commit()
        logger.debug(f"✓ Logged candle collection: {collected_count} new candles")
    except Exception as e:
        session.rollback()
        logger.error(f"Error logging collection event: {e}")
    finally:
        session.close()


def log_xgb_training_event(training_samples, win_rate_long, win_rate_short):
    """Log completion of daily XGBoost retraining."""
    db = get_db()
    session = db.Session()
    try:
        total_candles = session.query(Candle).count()
        unique_symbols = session.query(Candle.symbol).distinct().count()
        
        event = CandleTrainingMetadata(
            event_type="training",
            total_candles=total_candles,
            instruments_count=unique_symbols,
            training_samples=training_samples,
            model_version="both",
            win_rate_long=win_rate_long,
            win_rate_short=win_rate_short,
            notes=f"Retrained XGBoost with {training_samples} samples",
        )
        session.add(event)
        session.commit()
        logger.debug(f"✓ Logged XGBoost training: {training_samples} samples")
    except Exception as e:
        session.rollback()
        logger.error(f"Error logging training event: {e}")
    finally:
        session.close()
