-- ============================================================================
-- SAFE FIX: Update is_admin function without dropping dependent policies
-- ============================================================================
-- This updates the is_admin function in-place to add fixed search_path
-- No need to drop - just use CREATE OR REPLACE with same signature

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

-- Test the function
-- SELECT public.is_admin(); -- should return true if admin, false otherwise
