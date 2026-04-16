-- ============================================================================
-- FIX: Add fixed search_path to is_admin function (Security Advisor fix)
-- ============================================================================
-- This fixes the Supabase Security Advisor warning about the is_admin function
-- not having a fixed search_path. SECURITY DEFINER + search_path prevents SQL injection.

DROP FUNCTION IF EXISTS public.is_admin(UUID);

CREATE OR REPLACE FUNCTION public.is_admin(user_id UUID DEFAULT NULL)
RETURNS BOOLEAN AS $$
  SELECT COALESCE(
    EXISTS (
      SELECT 1 FROM users 
      WHERE id = COALESCE(user_id, auth.uid()) AND is_admin = TRUE
    ),
    FALSE
  )
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public;

-- Verify the function works correctly
-- Test: SELECT public.is_admin(); -- should return true if admin, false otherwise
