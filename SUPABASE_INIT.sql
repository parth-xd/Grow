-- ============================================================================
-- SUPABASE DATABASE INITIALIZATION SCRIPT
-- ============================================================================
-- Run this SQL in Supabase SQL Editor to set up all tables
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- 1. USER MANAGEMENT TABLES
-- ============================================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    google_id VARCHAR(255) UNIQUE,
    profile_picture_url TEXT,
    is_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);

-- API credentials (encrypted)
CREATE TABLE IF NOT EXISTS api_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    encrypted_groww_api_key TEXT NOT NULL,
    encrypted_groww_secret TEXT NOT NULL,
    is_live_trading BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_creds_user ON api_credentials(user_id);

-- User settings
CREATE TABLE IF NOT EXISTS user_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    paper_trading_enabled BOOLEAN DEFAULT TRUE,
    real_trading_enabled BOOLEAN DEFAULT FALSE,
    max_risk_per_trade FLOAT DEFAULT 2.0,
    backtesting_enabled BOOLEAN DEFAULT TRUE,
    notifications_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_settings_user ON user_settings(user_id);

-- Admin logs
CREATE TABLE IF NOT EXISTS admin_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES users(id),
    action_type VARCHAR(50),
    action_description TEXT,
    affected_user_id UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_logs_created ON admin_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_admin_logs_admin ON admin_logs(admin_id);
CREATE INDEX IF NOT EXISTS idx_admin_logs_affected ON admin_logs(affected_user_id);

-- ============================================================================
-- 2. MARKET DATA TABLES
-- ============================================================================

-- Stock master data
CREATE TABLE IF NOT EXISTS stocks (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    sector VARCHAR(100),
    market_cap_cr FLOAT,
    dividend_yield FLOAT,
    pe_ratio FLOAT,
    book_value FLOAT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stocks_symbol ON stocks(symbol);

-- Candle data (OHLCV)
CREATE TABLE IF NOT EXISTS candles (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    open FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    close FLOAT NOT NULL,
    volume FLOAT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_timestamp ON candles(symbol, timestamp);

-- Intraday candles (1min/5min)
CREATE TABLE IF NOT EXISTS intraday_candles (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    trading_date VARCHAR(10) NOT NULL,
    time VARCHAR(8) NOT NULL,
    open FLOAT NOT NULL,
    high FLOAT NOT NULL,
    low FLOAT NOT NULL,
    close FLOAT NOT NULL,
    volume INTEGER DEFAULT 0,
    interval VARCHAR(10) DEFAULT '1min',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_intraday_symbol_date ON intraday_candles(symbol, trading_date);
CREATE INDEX IF NOT EXISTS idx_intraday_symbol_date_time ON intraday_candles(symbol, trading_date, time);

-- ============================================================================
-- 3. TRADING DATA TABLES
-- ============================================================================

-- Trade journal entries
CREATE TABLE IF NOT EXISTS trade_journal (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT,
    entry_date TIMESTAMP NOT NULL,
    exit_date TIMESTAMP,
    quantity FLOAT NOT NULL,
    trade_type VARCHAR(20),
    status VARCHAR(50),
    profit_loss FLOAT,
    profit_loss_pct FLOAT,
    thesis TEXT,
    learning_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trade_journal_user ON trade_journal(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_journal_date ON trade_journal(entry_date);

-- Trade log (detailed transaction log)
CREATE TABLE IF NOT EXISTS trade_log (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    action VARCHAR(50),
    quantity FLOAT,
    price FLOAT,
    timestamp TIMESTAMP NOT NULL,
    broker_ref_id VARCHAR(100),
    status VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trade_log_user ON trade_log(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_log_symbol ON trade_log(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_log_timestamp ON trade_log(timestamp);

-- Paper trades (simulated trades)
CREATE TABLE IF NOT EXISTS paper_trades (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    entry_price FLOAT NOT NULL,
    entry_date TIMESTAMP NOT NULL,
    quantity FLOAT NOT NULL,
    is_closed BOOLEAN DEFAULT FALSE,
    exit_price FLOAT,
    exit_date TIMESTAMP,
    profit_loss FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_user ON paper_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol);

-- PnL snapshots (daily portfolio snapshots)
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    total_value FLOAT,
    total_invested FLOAT,
    cumulative_pnl FLOAT,
    cumulative_roi_pct FLOAT,
    daily_pnl FLOAT,
    daily_roi_pct FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_user_date ON pnl_snapshots(user_id, snapshot_date);

-- Trade snapshots (position snapshots)
CREATE TABLE IF NOT EXISTS trade_snapshots (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    quantity FLOAT,
    avg_cost FLOAT,
    current_price FLOAT,
    total_value FLOAT,
    unrealized_pnl FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trade_snapshots_user_date ON trade_snapshots(user_id, snapshot_date);

-- ============================================================================
-- 4. ANALYSIS & RESEARCH TABLES
-- ============================================================================

-- Stock theses
CREATE TABLE IF NOT EXISTS stock_theses (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    thesis TEXT,
    conviction_level VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_theses_user ON stock_theses(user_id);
CREATE INDEX IF NOT EXISTS idx_stock_theses_symbol ON stock_theses(symbol);

-- Watchlist notes
CREATE TABLE IF NOT EXISTS watchlist_notes (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_watchlist_notes_user ON watchlist_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_notes_symbol ON watchlist_notes(symbol);

-- Analysis cache
CREATE TABLE IF NOT EXISTS analysis_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    analysis_type VARCHAR(100) NOT NULL,
    data TEXT,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_analysis_cache_symbol ON analysis_cache(symbol);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_expires ON analysis_cache(expires_at);

-- ============================================================================
-- 5. NEWS & MARKET CONTEXT TABLES
-- ============================================================================

-- News articles
CREATE TABLE IF NOT EXISTS news_articles (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    headline TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    source VARCHAR(100),
    sentiment VARCHAR(20),
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_news_articles_symbol ON news_articles(symbol);
CREATE INDEX IF NOT EXISTS idx_news_articles_published ON news_articles(published_at);

-- Global news
CREATE TABLE IF NOT EXISTS global_news (
    id SERIAL PRIMARY KEY,
    headline TEXT NOT NULL,
    summary TEXT,
    category VARCHAR(100),
    url TEXT,
    source VARCHAR(100),
    impact_level VARCHAR(20),
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_global_news_published ON global_news(published_at);

-- Disruption events
CREATE TABLE IF NOT EXISTS disruption_events (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20),
    event_type VARCHAR(100) NOT NULL,
    description TEXT,
    severity VARCHAR(20),
    event_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_disruption_events_symbol ON disruption_events(symbol);
CREATE INDEX IF NOT EXISTS idx_disruption_events_date ON disruption_events(event_date);

-- Commodity snapshots
CREATE TABLE IF NOT EXISTS commodity_snapshots (
    id SERIAL PRIMARY KEY,
    commodity VARCHAR(50) NOT NULL UNIQUE,
    ticker VARCHAR(20),
    current_price FLOAT,
    prev_price FLOAT,
    price_change_since_last FLOAT,
    prev_trend VARCHAR(10),
    price_change_1m FLOAT DEFAULT 0,
    price_change_3m FLOAT DEFAULT 0,
    trend VARCHAR(10) DEFAULT 'UNKNOWN',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 6. CONFIGURATION TABLES
-- ============================================================================

-- Config settings (app configuration, cost rates, etc.)
CREATE TABLE IF NOT EXISTS config (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) UNIQUE NOT NULL,
    value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_config_key ON config(key);

-- ============================================================================
-- 7. PEER ANALYSIS TABLES
-- ============================================================================

-- Peer companies
CREATE TABLE IF NOT EXISTS peers (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255),
    sector VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Peer prices
CREATE TABLE IF NOT EXISTS peer_prices (
    id SERIAL PRIMARY KEY,
    peer_id INTEGER REFERENCES peers(id) ON DELETE CASCADE,
    symbol VARCHAR(20),
    price FLOAT,
    date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_peer_prices_symbol_date ON peer_prices(symbol, date);

-- Peer analysis results
CREATE TABLE IF NOT EXISTS peer_analysis (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    peer_symbol VARCHAR(20) NOT NULL,
    metric VARCHAR(50),
    relative_value FLOAT,
    analysis_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 8. FNO & ADVANCED TABLES
-- ============================================================================

-- F&O positions
CREATE TABLE IF NOT EXISTS fno_positions (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    contract_type VARCHAR(20),
    strike_price FLOAT,
    expiry_date DATE,
    quantity FLOAT,
    entry_price FLOAT,
    current_price FLOAT,
    entry_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fno_positions_user ON fno_positions(user_id);

-- ============================================================================
-- ALL TABLES CREATED SUCCESSFULLY
-- ============================================================================

-- RUN THIS TO TEST:
-- SELECT * FROM users LIMIT 1;
-- SELECT table_name FROM information_schema.tables WHERE table_schema='public';
