-- ============================================================================
-- ENABLE ROW-LEVEL SECURITY (RLS) - PRODUCTION SECURITY
-- ============================================================================
-- This script enables RLS for all tables in the Grow database
-- Matches actual schema from SUPABASE_INIT.sql
-- ============================================================================

-- Helper function to check if user is admin
CREATE OR REPLACE FUNCTION public.is_admin(user_id UUID DEFAULT NULL)
RETURNS BOOLEAN AS $$
  SELECT COALESCE(
    EXISTS (
      SELECT 1 FROM users 
      WHERE id = COALESCE(user_id, auth.uid()) AND is_admin = TRUE
    ),
    FALSE
  )
$$ LANGUAGE sql STABLE;

-- ============================================================================
-- USERS TABLE
-- ============================================================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_select_own"
  ON users FOR SELECT
  USING (id = auth.uid() OR public.is_admin(auth.uid()));

CREATE POLICY "users_update_own"
  ON users FOR UPDATE
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

CREATE POLICY "admin_update_users"
  ON users FOR UPDATE
  USING (public.is_admin(auth.uid()))
  WITH CHECK (public.is_admin(auth.uid()));

-- ============================================================================
-- API CREDENTIALS - Strictly isolated per user
-- ============================================================================
ALTER TABLE api_credentials ENABLE ROW LEVEL SECURITY;

CREATE POLICY "api_creds_select_own"
  ON api_credentials FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "api_creds_update_own"
  ON api_credentials FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "api_creds_insert_own"
  ON api_credentials FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "api_creds_delete_own"
  ON api_credentials FOR DELETE
  USING (user_id = auth.uid());

-- ============================================================================
-- USER SETTINGS
-- ============================================================================
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_settings_select_own"
  ON user_settings FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "user_settings_update_own"
  ON user_settings FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "user_settings_insert_own"
  ON user_settings FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- ADMIN LOGS - Only admins (uses admin_id, not user_id)
-- ============================================================================
ALTER TABLE admin_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "admin_logs_select"
  ON admin_logs FOR SELECT
  USING (public.is_admin(auth.uid()));

CREATE POLICY "admin_logs_insert"
  ON admin_logs FOR INSERT
  WITH CHECK (admin_id = auth.uid() AND public.is_admin(auth.uid()));

-- ============================================================================
-- MARKET DATA - Public read only
-- ============================================================================
ALTER TABLE stocks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "stocks_select_public"
  ON stocks FOR SELECT
  USING (true);

ALTER TABLE candles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "candles_select_public"
  ON candles FOR SELECT
  USING (true);

ALTER TABLE intraday_candles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "intraday_candles_select_public"
  ON intraday_candles FOR SELECT
  USING (true);

ALTER TABLE commodity_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "commodity_snapshots_select_public"
  ON commodity_snapshots FOR SELECT
  USING (true);

-- ============================================================================
-- TRADE DATA - User isolated
-- ============================================================================
ALTER TABLE trade_journal ENABLE ROW LEVEL SECURITY;

CREATE POLICY "trade_journal_select_own"
  ON trade_journal FOR SELECT
  USING (user_id = auth.uid() OR public.is_admin(auth.uid()));

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

-- ============================================================================
-- TRADE LOG
-- ============================================================================
ALTER TABLE trade_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "trade_log_select_own"
  ON trade_log FOR SELECT
  USING (user_id = auth.uid() OR public.is_admin(auth.uid()));

CREATE POLICY "trade_log_insert_own"
  ON trade_log FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- PAPER TRADES
-- ============================================================================
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

-- ============================================================================
-- FNO POSITIONS
-- ============================================================================
ALTER TABLE fno_positions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "fno_positions_select_own"
  ON fno_positions FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "fno_positions_insert_own"
  ON fno_positions FOR INSERT
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "fno_positions_update_own"
  ON fno_positions FOR UPDATE
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- PNL SNAPSHOTS
-- ============================================================================
ALTER TABLE pnl_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pnl_snapshots_select_own"
  ON pnl_snapshots FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "pnl_snapshots_insert_own"
  ON pnl_snapshots FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- TRADE SNAPSHOTS
-- ============================================================================
ALTER TABLE trade_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "trade_snapshots_select_own"
  ON trade_snapshots FOR SELECT
  USING (user_id = auth.uid());

CREATE POLICY "trade_snapshots_insert_own"
  ON trade_snapshots FOR INSERT
  WITH CHECK (user_id = auth.uid());

-- ============================================================================
-- STOCK THESES
-- ============================================================================
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

-- ============================================================================
-- WATCHLIST NOTES
-- ============================================================================
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

-- ============================================================================
-- ANALYSIS CACHE - PUBLIC (no user_id column, shared cache)
-- ============================================================================
ALTER TABLE analysis_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analysis_cache_select_public"
  ON analysis_cache FOR SELECT
  USING (true);

-- ============================================================================
-- PEERS & ANALYSIS - Public read only
-- ============================================================================
ALTER TABLE peers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "peers_select_public"
  ON peers FOR SELECT
  USING (true);

ALTER TABLE peer_prices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "peer_prices_select_public"
  ON peer_prices FOR SELECT
  USING (true);

ALTER TABLE peer_analysis ENABLE ROW LEVEL SECURITY;
CREATE POLICY "peer_analysis_select_public"
  ON peer_analysis FOR SELECT
  USING (true);

-- ============================================================================
-- NEWS - Public read only
-- ============================================================================
ALTER TABLE news_articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "news_articles_select_public"
  ON news_articles FOR SELECT
  USING (true);

ALTER TABLE global_news ENABLE ROW LEVEL SECURITY;
CREATE POLICY "global_news_select_public"
  ON global_news FOR SELECT
  USING (true);

-- ============================================================================
-- DISRUPTION EVENTS - Public read only
-- ============================================================================
ALTER TABLE disruption_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "disruption_events_select_public"
  ON disruption_events FOR SELECT
  USING (true);

-- ============================================================================
-- CONFIG - Admin only
-- ============================================================================
ALTER TABLE config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "config_select_admin"
  ON config FOR SELECT
  USING (public.is_admin(auth.uid()));

CREATE POLICY "config_update_admin"
  ON config FOR UPDATE
  USING (public.is_admin(auth.uid()))
  WITH CHECK (public.is_admin(auth.uid()));

-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- Run this to verify all tables have RLS enabled:
-- SELECT tablename, rowsecurity FROM pg_tables 
-- WHERE schemaname = 'public' AND tablename NOT LIKE 'pg_%'
-- ORDER BY tablename;
--
-- All should show: rowsecurity = true
