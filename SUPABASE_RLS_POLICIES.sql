-- ============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES FOR SUPABASE
-- ============================================================================
-- Enable RLS on all tables and create user-isolation policies

-- ============================================================================
-- 1. ENABLE RLS ON ALL TABLES
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
-- 2. USERS TABLE
-- ============================================================================
-- Users can see/edit their own row
-- Admins (is_admin=true) can see all users

CREATE POLICY "users_own_record" ON users
FOR ALL USING (auth.uid() = id OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (auth.uid() = id OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 3. API_CREDENTIALS TABLE
-- ============================================================================
-- Users can only see/edit their own credentials
-- Admins can see all

CREATE POLICY "api_credentials_own" ON api_credentials
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 4. USER_SETTINGS TABLE
-- ============================================================================
-- Users can only see/edit their own settings

CREATE POLICY "user_settings_own" ON user_settings
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 5. ADMIN_LOGS TABLE
-- ============================================================================
-- Only admins can view/create admin logs

CREATE POLICY "admin_logs_admin_only" ON admin_logs
FOR ALL USING ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 6. STOCKS TABLE
-- ============================================================================
-- Stocks are public reference data - anyone can read, only admins can modify

CREATE POLICY "stocks_public_read" ON stocks
FOR SELECT USING (true);

CREATE POLICY "stocks_admin_write" ON stocks
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

CREATE POLICY "stocks_admin_update" ON stocks
FOR UPDATE USING ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

CREATE POLICY "stocks_admin_delete" ON stocks
FOR DELETE USING ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 7. CANDLES TABLE
-- ============================================================================
-- Candles are public market data - anyone can read, only admins can modify

CREATE POLICY "candles_public_read" ON candles
FOR SELECT USING (true);

CREATE POLICY "candles_admin_write" ON candles
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

CREATE POLICY "candles_admin_update" ON candles
FOR UPDATE USING ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 8. INTRADAY_CANDLES TABLE
-- ============================================================================
-- Intraday candles are public market data

CREATE POLICY "intraday_candles_public_read" ON intraday_candles
FOR SELECT USING (true);

CREATE POLICY "intraday_candles_admin_write" ON intraday_candles
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

CREATE POLICY "intraday_candles_admin_update" ON intraday_candles
FOR UPDATE USING ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 9. COMMODITY_SNAPSHOTS TABLE
-- ============================================================================
-- Public market data

CREATE POLICY "commodity_snapshots_public_read" ON commodity_snapshots
FOR SELECT USING (true);

CREATE POLICY "commodity_snapshots_admin_write" ON commodity_snapshots
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 10. TRADE_JOURNAL TABLE
-- ============================================================================
-- Users can only see/edit their own trades

CREATE POLICY "trade_journal_own" ON trade_journal
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 11. TRADE_LOG TABLE
-- ============================================================================
-- Users can only see/edit their own trade logs

CREATE POLICY "trade_log_own" ON trade_log
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 12. PAPER_TRADES TABLE
-- ============================================================================
-- Users can only see/edit their own paper trades

CREATE POLICY "paper_trades_own" ON paper_trades
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 13. PNL_SNAPSHOTS TABLE
-- ============================================================================
-- Users can only see/edit their own P&L snapshots

CREATE POLICY "pnl_snapshots_own" ON pnl_snapshots
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 14. TRADE_SNAPSHOTS TABLE
-- ============================================================================
-- Users can only see/edit their own trade snapshots

CREATE POLICY "trade_snapshots_own" ON trade_snapshots
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 15. STOCK_THESES TABLE
-- ============================================================================
-- Users can only see/edit their own theses

CREATE POLICY "stock_theses_own" ON stock_theses
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 16. WATCHLIST_NOTES TABLE
-- ============================================================================
-- Users can only see/edit their own watchlist notes

CREATE POLICY "watchlist_notes_own" ON watchlist_notes
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 17. ANALYSIS_CACHE TABLE
-- ============================================================================
-- Users can only see/edit their own analysis cache

CREATE POLICY "analysis_cache_own" ON analysis_cache
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 18. PEERS TABLE
-- ============================================================================
-- Peers are public reference data

CREATE POLICY "peers_public_read" ON peers
FOR SELECT USING (true);

CREATE POLICY "peers_admin_write" ON peers
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 19. PEER_PRICES TABLE
-- ============================================================================
-- Public reference data

CREATE POLICY "peer_prices_public_read" ON peer_prices
FOR SELECT USING (true);

CREATE POLICY "peer_prices_admin_write" ON peer_prices
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 20. PEER_ANALYSIS TABLE
-- ============================================================================
-- Public reference data

CREATE POLICY "peer_analysis_public_read" ON peer_analysis
FOR SELECT USING (true);

CREATE POLICY "peer_analysis_admin_write" ON peer_analysis
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 21. NEWS_ARTICLES TABLE
-- ============================================================================
-- Public news data - anyone can read, admins can write

CREATE POLICY "news_articles_public_read" ON news_articles
FOR SELECT USING (true);

CREATE POLICY "news_articles_admin_write" ON news_articles
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 22. GLOBAL_NEWS TABLE
-- ============================================================================
-- Public global news - anyone can read, admins can write

CREATE POLICY "global_news_public_read" ON global_news
FOR SELECT USING (true);

CREATE POLICY "global_news_admin_write" ON global_news
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 23. DISRUPTION_EVENTS TABLE
-- ============================================================================
-- Public events data

CREATE POLICY "disruption_events_public_read" ON disruption_events
FOR SELECT USING (true);

CREATE POLICY "disruption_events_admin_write" ON disruption_events
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 24. FNO_POSITIONS TABLE
-- ============================================================================
-- Users can only see/edit their own positions

CREATE POLICY "fno_positions_own" ON fno_positions
FOR ALL USING (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK (user_id = auth.uid() OR (
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- 25. CONFIG TABLE
-- ============================================================================
-- Public read for all (app configuration), admin write only

CREATE POLICY "config_public_read" ON config
FOR SELECT USING (true);

CREATE POLICY "config_admin_write" ON config
FOR INSERT WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

CREATE POLICY "config_admin_update" ON config
FOR UPDATE USING ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true)
WITH CHECK ((
  SELECT is_admin FROM users WHERE id = auth.uid()
) = true);

-- ============================================================================
-- VERIFY POLICIES ARE CREATED
-- ============================================================================

-- Run this query to verify all RLS policies:
-- SELECT tablename, policyname FROM pg_policies 
-- WHERE schemaname = 'public' 
-- ORDER BY tablename, policyname;
