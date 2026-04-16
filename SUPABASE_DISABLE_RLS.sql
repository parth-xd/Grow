-- ============================================================================
-- DISABLE ALL RLS - SIMPLE SOLUTION
-- ============================================================================
-- For MVP/testing, we'll disable RLS to focus on core functionality
-- Security policies can be added later once the app is stable

-- ============================================================================
-- STEP 1: DROP ALL EXISTING POLICIES
-- ============================================================================

DROP POLICY IF EXISTS "users_own" ON users;
DROP POLICY IF EXISTS "api_credentials_own" ON api_credentials;
DROP POLICY IF EXISTS "user_settings_own" ON user_settings;
DROP POLICY IF EXISTS "admin_logs_admin_only" ON admin_logs;
DROP POLICY IF EXISTS "stocks_public_read" ON stocks;
DROP POLICY IF EXISTS "stocks_admin_write" ON stocks;
DROP POLICY IF EXISTS "stocks_admin_update" ON stocks;
DROP POLICY IF EXISTS "stocks_admin_delete" ON stocks;
DROP POLICY IF EXISTS "stocks_read" ON stocks;
DROP POLICY IF EXISTS "candles_public_read" ON candles;
DROP POLICY IF EXISTS "candles_admin_write" ON candles;
DROP POLICY IF EXISTS "candles_admin_update" ON candles;
DROP POLICY IF EXISTS "candles_read" ON candles;
DROP POLICY IF EXISTS "intraday_candles_public_read" ON intraday_candles;
DROP POLICY IF EXISTS "intraday_candles_admin_write" ON intraday_candles;
DROP POLICY IF EXISTS "intraday_candles_admin_update" ON intraday_candles;
DROP POLICY IF EXISTS "intraday_candles_read" ON intraday_candles;
DROP POLICY IF EXISTS "commodity_snapshots_public_read" ON commodity_snapshots;
DROP POLICY IF EXISTS "commodity_snapshots_admin_write" ON commodity_snapshots;
DROP POLICY IF EXISTS "commodity_snapshots_read" ON commodity_snapshots;
DROP POLICY IF EXISTS "trade_journal_own" ON trade_journal;
DROP POLICY IF EXISTS "trade_log_own" ON trade_log;
DROP POLICY IF EXISTS "paper_trades_own" ON paper_trades;
DROP POLICY IF EXISTS "pnl_snapshots_own" ON pnl_snapshots;
DROP POLICY IF EXISTS "trade_snapshots_own" ON trade_snapshots;
DROP POLICY IF EXISTS "stock_theses_own" ON stock_theses;
DROP POLICY IF EXISTS "watchlist_notes_own" ON watchlist_notes;
DROP POLICY IF EXISTS "analysis_cache_own" ON analysis_cache;
DROP POLICY IF EXISTS "analysis_cache_read" ON analysis_cache;
DROP POLICY IF EXISTS "peers_public_read" ON peers;
DROP POLICY IF EXISTS "peers_admin_write" ON peers;
DROP POLICY IF EXISTS "peers_read" ON peers;
DROP POLICY IF EXISTS "peer_prices_public_read" ON peer_prices;
DROP POLICY IF EXISTS "peer_prices_admin_write" ON peer_prices;
DROP POLICY IF EXISTS "peer_prices_read" ON peer_prices;
DROP POLICY IF EXISTS "peer_analysis_public_read" ON peer_analysis;
DROP POLICY IF EXISTS "peer_analysis_admin_write" ON peer_analysis;
DROP POLICY IF EXISTS "peer_analysis_read" ON peer_analysis;
DROP POLICY IF EXISTS "news_articles_public_read" ON news_articles;
DROP POLICY IF EXISTS "news_articles_admin_write" ON news_articles;
DROP POLICY IF EXISTS "news_articles_read" ON news_articles;
DROP POLICY IF EXISTS "global_news_public_read" ON global_news;
DROP POLICY IF EXISTS "global_news_admin_write" ON global_news;
DROP POLICY IF EXISTS "global_news_read" ON global_news;
DROP POLICY IF EXISTS "disruption_events_public_read" ON disruption_events;
DROP POLICY IF EXISTS "disruption_events_admin_write" ON disruption_events;
DROP POLICY IF EXISTS "disruption_events_read" ON disruption_events;
DROP POLICY IF EXISTS "fno_positions_own" ON fno_positions;
DROP POLICY IF EXISTS "config_public_read" ON config;
DROP POLICY IF EXISTS "config_admin_write" ON config;
DROP POLICY IF EXISTS "config_admin_update" ON config;
DROP POLICY IF EXISTS "config_read" ON config;
DROP POLICY IF EXISTS "users_own_record" ON users;

-- ============================================================================
-- STEP 2: DISABLE RLS ON ALL TABLES
-- ============================================================================
-- This allows unrestricted access for MVP testing
-- RLS can be re-enabled later with proper policies

ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE api_credentials DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings DISABLE ROW LEVEL SECURITY;
ALTER TABLE admin_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE stocks DISABLE ROW LEVEL SECURITY;
ALTER TABLE candles DISABLE ROW LEVEL SECURITY;
ALTER TABLE intraday_candles DISABLE ROW LEVEL SECURITY;
ALTER TABLE commodity_snapshots DISABLE ROW LEVEL SECURITY;
ALTER TABLE trade_journal DISABLE ROW LEVEL SECURITY;
ALTER TABLE trade_log DISABLE ROW LEVEL SECURITY;
ALTER TABLE paper_trades DISABLE ROW LEVEL SECURITY;
ALTER TABLE pnl_snapshots DISABLE ROW LEVEL SECURITY;
ALTER TABLE trade_snapshots DISABLE ROW LEVEL SECURITY;
ALTER TABLE stock_theses DISABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist_notes DISABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_cache DISABLE ROW LEVEL SECURITY;
ALTER TABLE peers DISABLE ROW LEVEL SECURITY;
ALTER TABLE peer_prices DISABLE ROW LEVEL SECURITY;
ALTER TABLE peer_analysis DISABLE ROW LEVEL SECURITY;
ALTER TABLE news_articles DISABLE ROW LEVEL SECURITY;
ALTER TABLE global_news DISABLE ROW LEVEL SECURITY;
ALTER TABLE disruption_events DISABLE ROW LEVEL SECURITY;
ALTER TABLE fno_positions DISABLE ROW LEVEL SECURITY;
ALTER TABLE config DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- DONE - RLS DISABLED FOR MVP TESTING
-- ============================================================================
-- All tables are now accessible without RLS restrictions
-- This allows the app to work without security policies blocking queries
-- 
-- IMPORTANT: For production, enable RLS and add proper policies
-- Run this later to re-enable:
-- ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
-- Then add appropriate CREATE POLICY statements
