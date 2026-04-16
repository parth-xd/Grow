-- ============================================================================
-- ENABLE ROW-LEVEL SECURITY (RLS) - PRODUCTION SECURITY
-- ============================================================================
-- This script enables RLS with proper policies for multi-user SaaS
-- Run this after enabling auth in your Supabase project
-- ============================================================================

-- Helper function to get current user ID from JWT
CREATE OR REPLACE FUNCTION auth.user_id()
RETURNS UUID AS $$
  SELECT auth.uid()
$$ LANGUAGE sql STABLE;

-- Helper function to check if user is admin
CREATE OR REPLACE FUNCTION is_admin()
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM users 
    WHERE id = auth.uid() AND is_admin = TRUE
  )
$$ LANGUAGE sql STABLE;

-- ============================================================================
-- 1. USERS TABLE - Only users can see their own profile, admins see all
-- ============================================================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Users can view their own profile
CREATE POLICY "users_select_own"
  ON users FOR SELECT
  USING (id = auth.uid() OR is_admin(auth.uid()));

-- Users can update their own profile
CREATE POLICY "users_update_own"
  ON users FOR UPDATE
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

-- Admin can update any user
CREATE POLICY "admin_update_users"
  ON users FOR UPDATE
  USING (is_admin(auth.uid()))
  WITH CHECK (is_admin(auth.uid()));

-- Only service role can insert users (during OAuth registration)
-- No policy needed - insert happens server-side via JWT

-- ============================================================================
-- 2. API CREDENTIALS - Strictly isolated per user
-- ============================================================================
ALTER TABLE api_credentials ENABLE ROW LEVEL SECURITY;

-- Users can only see their own credentials
CREATE POLICY "api_creds_select_own"
  ON api_credentials FOR SELECT
  USING (user_id = auth.uid());

-- Users can only update their own credentials
CREATE POLICY "api_creds_update_own"
  ON api_credentials FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- Users can insert their own credentials
CREATE POLICY "api_creds_insert_own"
  ON api_credentials FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- Users can delete their own credentials
CREATE POLICY "api_creds_delete_own"
  ON api_credentials FOR DELETE
  USING (user_id = auth.uid());

-- ============================================================================
-- 3. USER SETTINGS - Per-user settings
-- ============================================================================
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

-- Users can only see their own settings
CREATE POLICY "user_settings_select_own"
  ON user_settings FOR SELECT
  USING (user_id = auth.uid());

-- Users can only update their own settings
CREATE POLICY "user_settings_update_own"
  ON user_settings FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- Users can insert their own settings
CREATE POLICY "user_settings_insert_own"
  ON user_settings FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- 4. ADMIN LOGS - Only admins can view
-- ============================================================================
ALTER TABLE admin_logs ENABLE ROW LEVEL SECURITY;

-- Only admins can view logs
CREATE POLICY "admin_logs_select_admin"
  ON admin_logs FOR SELECT
  USING (is_admin(auth.uid()));

-- Only admins can insert logs (from app)
CREATE POLICY "admin_logs_insert_admin"
  ON admin_logs FOR INSERT
  WITH CHECK (is_admin(auth.uid()));

-- ============================================================================
-- 5. MARKET DATA - Public read, authenticated write (system only)
-- ============================================================================

-- STOCKS TABLE
ALTER TABLE stocks ENABLE ROW LEVEL SECURITY;

-- Everyone can read stocks (public market data)
CREATE POLICY "stocks_select_public"
  ON stocks FOR SELECT
  USING (true);

-- Only service role can write stocks (via backend)
-- No policy - handled server-side

-- CANDLES TABLE
ALTER TABLE candles ENABLE ROW LEVEL SECURITY;

-- Everyone can read candles (public market data)
CREATE POLICY "candles_select_public"
  ON candles FOR SELECT
  USING (true);

-- INTRADAY CANDLES
ALTER TABLE intraday_candles ENABLE ROW LEVEL SECURITY;

-- Everyone can read intraday data
CREATE POLICY "intraday_candles_select_public"
  ON intraday_candles FOR SELECT
  USING (true);

-- COMMODITY SNAPSHOTS
ALTER TABLE commodity_snapshots ENABLE ROW LEVEL SECURITY;

-- Everyone can read commodity data
CREATE POLICY "commodity_snapshots_select_public"
  ON commodity_snapshots FOR SELECT
  USING (true);

-- ============================================================================
-- 6. USER TRADE DATA - Isolated per user
-- ============================================================================

-- TRADE JOURNAL
ALTER TABLE trade_journal ENABLE ROW LEVEL SECURITY;

CREATE POLICY "trade_journal_select_own"
  ON trade_journal FOR SELECT
  USING (user_id = auth.uid() OR EXISTS(SELECT 1 FROM users WHERE id = auth.uid() AND is_admin = TRUE));

CREATE POLICY "trade_journal_insert_own"
  ON trade_journal FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "trade_journal_update_own"
  ON trade_journal FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "trade_journal_delete_own"
  ON trade_journal FOR DELETE
  USING (user_id = auth.uid());

-- TRADE LOG
ALTER TABLE trade_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "trade_log_select_own"
  ON trade_log FOR SELECT
  USING (user_id = auth.uid() OR EXISTS(SELECT 1 FROM users WHERE id = auth.uid() AND is_admin = TRUE));

CREATE POLICY "trade_log_insert_own"
  ON trade_log FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- PAPER TRADES
ALTER TABLE paper_trades ENABLE ROW LEVEL SECURITY;

CREATE POLICY "paper_trades_select_own"
  ON paper_trades FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "paper_trades_insert_own"
  ON paper_trades FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "paper_trades_update_own"
  ON paper_trades FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- PNL SNAPSHOTS
ALTER TABLE pnl_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pnl_snapshots_select_own"
  ON pnl_snapshots FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "pnl_snapshots_insert_own"
  ON pnl_snapshots FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- TRADE SNAPSHOTS
ALTER TABLE trade_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "trade_snapshots_select_own"
  ON trade_snapshots FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "trade_snapshots_insert_own"
  ON trade_snapshots FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- STOCK THESES
ALTER TABLE stock_theses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "stock_theses_select_own"
  ON stock_theses FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "stock_theses_insert_own"
  ON stock_theses FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "stock_theses_update_own"
  ON stock_theses FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- WATCHLIST NOTES
ALTER TABLE watchlist_notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "watchlist_notes_select_own"
  ON watchlist_notes FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "watchlist_notes_insert_own"
  ON watchlist_notes FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "watchlist_notes_update_own"
  ON watchlist_notes FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- ANALYSIS CACHE
ALTER TABLE analysis_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analysis_cache_select_own"
  ON analysis_cache FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "analysis_cache_insert_own"
  ON analysis_cache FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- 7. PEERS AND ANALYSIS (Public read)
-- ============================================================================

-- PEERS
ALTER TABLE peers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "peers_select_public"
  ON peers FOR SELECT
  USING (true);

-- PEER PRICES
ALTER TABLE peer_prices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "peer_prices_select_public"
  ON peer_prices FOR SELECT
  USING (true);

-- PEER ANALYSIS
ALTER TABLE peer_analysis ENABLE ROW LEVEL SECURITY;
CREATE POLICY "peer_analysis_select_public"
  ON peer_analysis FOR SELECT
  USING (true);

-- ============================================================================
-- 8. NEWS AND ARTICLES (Public read)
-- ============================================================================

-- NEWS ARTICLES
ALTER TABLE news_articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "news_articles_select_public"
  ON news_articles FOR SELECT
  USING (true);

-- GLOBAL NEWS
ALTER TABLE global_news ENABLE ROW LEVEL SECURITY;
CREATE POLICY "global_news_select_public"
  ON global_news FOR SELECT
  USING (true);

-- ============================================================================
-- 9. DISRUPTION EVENTS (Public read)
-- ============================================================================

ALTER TABLE disruption_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "disruption_events_select_public"
  ON disruption_events FOR SELECT
  USING (true);

-- ============================================================================
-- 10. CONFIGURATION (Only admins)
-- ============================================================================

ALTER TABLE config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "config_select_admin"
  ON config FOR SELECT
  USING (is_admin(auth.uid()));

CREATE POLICY "config_update_admin"
  ON config FOR UPDATE
  USING (is_admin(auth.uid()))
  WITH CHECK (is_admin(auth.uid()));

-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- Run this query to verify RLS is enabled on all tables:
-- SELECT tablename FROM pg_tables 
-- WHERE schemaname = 'public' 
-- AND tablename NOT LIKE 'pg_%';
-- 
-- Then check each table:
-- SELECT tablename, rowsecurity FROM pg_tables 
-- WHERE schemaname = 'public' AND tablename NOT LIKE 'pg_%'
-- ORDER BY tablename;

-- ============================================================================
-- IMPORTANT NOTES
-- ============================================================================
-- 1. This setup assumes authenticated requests include JWT with user ID
-- 2. Service role (backend) bypasses all RLS policies
-- 3. Users can only see/modify their own data (except for public market data)
-- 4. Admins can see all user data and logs
-- 5. API credentials are strictly isolated per user
-- 6. Market data (stocks, candles, news) is public read-only
-- ============================================================================
