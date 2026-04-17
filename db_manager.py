"""
PostgreSQL database manager — unified ORM for all persistent data.
Models: Candle, CommoditySnapshot, DisruptionEvent, NewsArticle, GlobalNews,
        Stock, TradeJournalEntry, TradeLogEntry, StockThesis, AnalysisCache,
        WatchlistNote, ConfigSetting.
"""

import json
import logging
import os
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Index, Text, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

logger = logging.getLogger(__name__)

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
    
    user_id = Column(String(36), index=True)  # UUID of the user who owns this trade

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
            "pre_trade": pre,
            "post_trade": post,
        }
        return result

    __table_args__ = (
        Index("idx_journal_symbol_status", "symbol", "status"),
        Index("idx_journal_is_paper", "is_paper"),
        Index("idx_journal_user_id", "user_id"),
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


class CandleDatabase:
    """Database manager for candle storage and retrieval."""

    def __init__(self, db_url=None):
        """Initialize database connection."""
        if db_url is None:
            # Priority: DATABASE_URL (Render) > DB_URL (local .env) > Build from individual vars
            db_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
            
            if db_url is None:
                # Only build from individual vars if no full connection string provided
                db_user = os.getenv("DB_USER", "postgres")
                db_pass = os.getenv("DB_PASSWORD", "postgres")
                db_host = os.getenv("DB_HOST", "localhost")
                db_port = os.getenv("DB_PORT", "5432")
                db_name = os.getenv("DB_NAME", "grow_trading_bot")
                
                db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

        # Ensure Supabase URLs have SSL mode (required for production)
        if db_url and "supabase" in db_url and "sslmode" not in db_url:
            db_url = db_url + "?sslmode=require"

        self.engine = create_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            echo=False,
            pool_pre_ping=True,  # Verify connections before using
            connect_args={"connect_timeout": 10},
            pool_timeout=10,
        )
        Session = scoped_session(sessionmaker(bind=self.engine, expire_on_commit=False))
        self.Session = Session

    @property
    def session(self):
        """Get a database session (for backward compatibility with auth.py)"""
        return self.Session()

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
            for candle_data in candles_list:
                # Handle timestamp
                if isinstance(candle_data["timestamp"], str):
                    ts = datetime.fromisoformat(candle_data["timestamp"])
                elif isinstance(candle_data["timestamp"], (int, float)):
                    ts = datetime.fromtimestamp(candle_data["timestamp"])
                else:
                    ts = candle_data["timestamp"]

                # Use insert_or_ignore logic (update if exists, insert if not)
                existing = session.query(Candle).filter_by(
                    symbol=symbol,
                    timestamp=ts
                ).first()

                if not existing:
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

    def get_candles(self, symbol, days=None, interval_minutes=5):
        """
        Retrieve candles from database using raw SQL for speed.
        
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

def get_config(key, default=None, db=None):
    """Get a config value from DB."""
    db = db or get_db()
    session = db.Session()
    try:
        entry = session.query(ConfigSetting).filter_by(key=key).first()
        return entry.value if entry else default
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
    except Exception as e:
        session.rollback()
        logger.error(f"Error setting config: {e}")
    finally:
        session.close()


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
            {"symbol": "COALINDIA", "company_name": "Coal India", "sector": "METALS", "sector_display": "Coal", "commodity": "Coal", "commodity_ticker": "MTF=F", "commodity_relationship": "direct", "commodity_weight": 0.50},
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
