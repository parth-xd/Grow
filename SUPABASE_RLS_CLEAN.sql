-- ============================================================================
-- CLEAN RLS SETUP FOR SUPABASE
-- ============================================================================
-- Drop all existing policies first, then create correct ones
-- This ensures we start fresh without conflicts

-- ============================================================================
-- DROP EXISTING POLICIES (if any)
-- ============================================================================

DROP POLICY IF EXISTS "users_own_record" ON users;
DROP POLICY IF EXISTS "api_credentials_own" ON api_credentials;
DROP POLICY IF EXISTS "user_settings_own" ON user_settings;
DROP POLICY IF EXISTS "admin_logs_admin_only" ON admin_logs;
DROP POLICY IF EXISTS "stocks_public_read" ON stocks;
DROP POLICY IF EXISTS "stocks_admin_write" ON stocks;
DROP POLICY IF EXISTS "stocks_admin_update" ON stocks;
DROP POLICY IF EXISTS "stocks_admin_delete" ON stocks;
DROP POLICY IF EXISTS "candles_public_read" ON candles;
DROP POLICY IF EXISTS "candles_admin_write" ON candles;
DROP POLICY IF EXISTS "candles_admin_update" ON candles;
DROP POLICY IF EXISTS "intraday_candles_public_read" ON intraday_candles;
DROP POLICY IF EXISTS "intraday_candles_admin_write" ON intraday_candles;
DROP POLICY IF EXISTS "intraday_candles_admin_update" ON intraday_candles;
DROP POLICY IF EXISTS "commodity_snapshots_public_read" ON commodity_snapshots;
DROP POLICY IF EXISTS "commodity_snapshots_admin_write" ON commodity_snapshots;
DROP POLICY IF EXISTS "trade_journal_own" ON trade_journal;
DROP POLICY IF EXISTS "trade_log_own" ON trade_log;
DROP POLICY IF EXISTS "paper_trades_own" ON paper_trades;
DROP POLICY IF EXISTS "pnl_snapshots_own" ON pnl_snapshots;
DROP POLICY IF EXISTS "trade_snapshots_own" ON trade_snapshots;
DROP POLICY IF EXISTS "stock_theses_own" ON stock_theses;
DROP POLICY IF EXISTS "watchlist_notes_own" ON watchlist_notes;
DROP POLICY IF EXISTS "analysis_cache_own" ON analysis_cache;
DROP POLICY IF EXISTS "peers_public_read" ON peers;
DROP POLICY IF EXISTS "peers_admin_write" ON peers;
DROP POLICY IF EXISTS "peer_prices_public_read" ON peer_prices;
DROP POLICY IF EXISTS "peer_prices_admin_write" ON peer_prices;
DROP POLICY IF EXISTS "peer_analysis_public_read" ON peer_analysis;
DROP POLICY IF EXISTS "peer_analysis_admin_write" ON peer_analysis;
DROP POLICY IF EXISTS "news_articles_public_read" ON news_articles;
DROP POLICY IF EXISTS "news_articles_admin_write" ON news_articles;
DROP POLICY IF EXISTS "global_news_public_read" ON global_news;
DROP POLICY IF EXISTS "global_news_admin_write" ON global_news;
DROP POLICY IF EXISTS "disruption_events_public_read" ON disruption_events;
DROP POLICY IF EXISTS "disruption_events_admin_write" ON disruption_events;
DROP POLICY IF EXISTS "fno_positions_own" ON fno_positions;
DROP POLICY IF EXISTS "config_public_read" ON config;
DROP POLICY IF EXISTS "config_admin_write" ON config;
DROP POLICY IF EXISTS "config_admin_update" ON config;

-- ============================================================================
-- ENABLE RLS ON ALL TABLES
-- ============================================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE admin_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE stocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE candles ENABLE ROW LEVEL SECURITY;
ALTER TABLE intraday_candles ENABLE ROW LEVEL SECURITY;
ALTER TABLE commodity_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_journal ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE pnl_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_theses ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE peers ENABLE ROW LEVEL SECURITY;
ALTER TABLE peer_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE peer_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE global_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE disruption_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE fno_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE config ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- CREATE NEW POLICIES
-- ============================================================================

-- USERS TABLE - Users see own record, admins see all
CREATE POLICY "users_own_record" ON users
FOR ALL USING (auth.uid() = id OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (auth.uid() = id OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- API_CREDENTIALS - Users see own, admins see all
CREATE POLICY "api_credentials_own" ON api_credentials
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- USER_SETTINGS - Users see own, admins see all
CREATE POLICY "user_settings_own" ON user_settings
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- ADMIN_LOGS - Admins only
CREATE POLICY "admin_logs_admin_only" ON admin_logs
FOR ALL USING ((SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- STOCKS - Public read, admin write
CREATE POLICY "stocks_public_read" ON stocks FOR SELECT USING (true);
CREATE POLICY "stocks_admin_write" ON stocks FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);
CREATE POLICY "stocks_admin_update" ON stocks FOR UPDATE USING ((SELECT is_admin FROM users WHERE id = auth.uid()) = true) WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);
CREATE POLICY "stocks_admin_delete" ON stocks FOR DELETE USING ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- CANDLES - Public read, admin write
CREATE POLICY "candles_public_read" ON candles FOR SELECT USING (true);
CREATE POLICY "candles_admin_write" ON candles FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);
CREATE POLICY "candles_admin_update" ON candles FOR UPDATE USING ((SELECT is_admin FROM users WHERE id = auth.uid()) = true) WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- INTRADAY_CANDLES - Public read, admin write
CREATE POLICY "intraday_candles_public_read" ON intraday_candles FOR SELECT USING (true);
CREATE POLICY "intraday_candles_admin_write" ON intraday_candles FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);
CREATE POLICY "intraday_candles_admin_update" ON intraday_candles FOR UPDATE USING ((SELECT is_admin FROM users WHERE id = auth.uid()) = true) WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- COMMODITY_SNAPSHOTS - Public read, admin write
CREATE POLICY "commodity_snapshots_public_read" ON commodity_snapshots FOR SELECT USING (true);
CREATE POLICY "commodity_snapshots_admin_write" ON commodity_snapshots FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- TRADE_JOURNAL - Users see own, admins see all
CREATE POLICY "trade_journal_own" ON trade_journal
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- TRADE_LOG - Users see own, admins see all
CREATE POLICY "trade_log_own" ON trade_log
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- PAPER_TRADES - Users see own, admins see all
CREATE POLICY "paper_trades_own" ON paper_trades
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- PNL_SNAPSHOTS - Users see own, admins see all
CREATE POLICY "pnl_snapshots_own" ON pnl_snapshots
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- TRADE_SNAPSHOTS - Users see own, admins see all
CREATE POLICY "trade_snapshots_own" ON trade_snapshots
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- STOCK_THESES - Users see own, admins see all
CREATE POLICY "stock_theses_own" ON stock_theses
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- WATCHLIST_NOTES - Users see own, admins see all
CREATE POLICY "watchlist_notes_own" ON watchlist_notes
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- ANALYSIS_CACHE - Users see own, admins see all
CREATE POLICY "analysis_cache_own" ON analysis_cache
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- PEERS - Public read, admin write
CREATE POLICY "peers_public_read" ON peers FOR SELECT USING (true);
CREATE POLICY "peers_admin_write" ON peers FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- PEER_PRICES - Public read, admin write
CREATE POLICY "peer_prices_public_read" ON peer_prices FOR SELECT USING (true);
CREATE POLICY "peer_prices_admin_write" ON peer_prices FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- PEER_ANALYSIS - Public read, admin write
CREATE POLICY "peer_analysis_public_read" ON peer_analysis FOR SELECT USING (true);
CREATE POLICY "peer_analysis_admin_write" ON peer_analysis FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- NEWS_ARTICLES - Public read, admin write
CREATE POLICY "news_articles_public_read" ON news_articles FOR SELECT USING (true);
CREATE POLICY "news_articles_admin_write" ON news_articles FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- GLOBAL_NEWS - Public read, admin write
CREATE POLICY "global_news_public_read" ON global_news FOR SELECT USING (true);
CREATE POLICY "global_news_admin_write" ON global_news FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- DISRUPTION_EVENTS - Public read, admin write
CREATE POLICY "disruption_events_public_read" ON disruption_events FOR SELECT USING (true);
CREATE POLICY "disruption_events_admin_write" ON disruption_events FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- FNO_POSITIONS - Users see own, admins see all
CREATE POLICY "fno_positions_own" ON fno_positions
FOR ALL USING (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true)
WITH CHECK (user_id = auth.uid() OR (SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- CONFIG - Public read, admin write
CREATE POLICY "config_public_read" ON config FOR SELECT USING (true);
CREATE POLICY "config_admin_write" ON config FOR INSERT WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);
CREATE POLICY "config_admin_update" ON config FOR UPDATE USING ((SELECT is_admin FROM users WHERE id = auth.uid()) = true) WITH CHECK ((SELECT is_admin FROM users WHERE id = auth.uid()) = true);

-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- Run this to verify all policies are created:
-- SELECT tablename, COUNT(*) as policy_count FROM pg_policies WHERE schemaname = 'public' GROUP BY tablename ORDER BY tablename;
