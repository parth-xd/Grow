# Row-Level Security (RLS) Setup Guide

## Current Status

❌ **RLS is currently DISABLED** (for MVP development)

This is configured in `SUPABASE_DISABLE_RLS.sql`. While this makes development easier, it's a **security risk** for production.

## Why RLS Matters

Row-Level Security ensures:
- ✅ Users can only see/modify their own data
- ✅ Admins can see all user data
- ✅ API credentials are strictly isolated
- ✅ Trade data, settings, and history are private per user
- ✅ Market data (stocks, candles) remains public

**Without RLS:** Any authenticated user could query another user's trade history, settings, or API credentials!

## How to Enable RLS

### Step 1: Disable the RLS Disable Script
Go to Supabase Console → SQL Editor and comment out or remove the execution of:
```sql
-- Don't run SUPABASE_DISABLE_RLS.sql
```

### Step 2: Run the RLS Enable Script
1. Go to Supabase Console → SQL Editor
2. Copy and paste the contents of `SUPABASE_ENABLE_RLS.sql`
3. Click "Run"
4. Verify all policies created successfully

### Step 3: Verify RLS is Enabled
Run this query in Supabase SQL Editor:
```sql
SELECT tablename, rowsecurity 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename NOT LIKE 'pg_%'
ORDER BY tablename;
```

All user-related tables should show `rowsecurity = true`

## RLS Policy Overview

| Table | Read | Write | Notes |
|-------|------|-------|-------|
| `users` | Own + Admin | Own + Admin | User profiles |
| `api_credentials` | Own only | Own only | **STRICTLY ISOLATED** |
| `user_settings` | Own only | Own only | User preferences |
| `trade_journal` | Own + Admin | Own only | Trade history |
| `trade_log` | Own + Admin | Own only | Execution logs |
| `paper_trades` | Own only | Own only | Paper trading |
| `stocks` | Public | Backend only | Market data |
| `candles` | Public | Backend only | Price history |
| `news_articles` | Public | Backend only | News |

## Important: Backend Configuration

The backend (Flask/Python) communicates with Supabase using the **service role key**, which **bypasses all RLS policies**. This is intentional and secure because:

1. The service role is only used server-side (never exposed to client)
2. Backend logic enforces additional authorization
3. Client requests go through authenticated JWT (respects RLS)

## Frontend: Ensure Authenticated Requests

When making client-side requests to Supabase, always:

1. Include the JWT token in headers:
```javascript
const response = await fetch('api/endpoint', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
```

2. The backend will verify the JWT and use authenticated context

## Testing RLS

### Test 1: Verify User A Can't See User B's Data
1. Sign in as User A
2. Try to query User B's credentials: should fail with "No rows"
3. User A should only see their own data

### Test 2: Verify Admin Can See All Data
1. Sign in as Admin user
2. Admin should be able to query all users' data

### Test 3: Verify Public Market Data is Accessible
1. Query stocks/candles without authentication
2. Should return public market data successfully

## When to Enable RLS

✅ **Enable RLS when:**
- Moving to production
- Multiple users need access
- Sensitive data needs protection
- Complying with security standards

⏸️ **Keep RLS disabled when:**
- Pure MVP/testing phase
- Single user testing
- Debugging complex queries

## Disabling RLS (if needed)

If you need to revert to disabled RLS:
```bash
# Run this in Supabase SQL Editor
psql -h database.supabase.co -U postgres
# Then paste contents of SUPABASE_DISABLE_RLS.sql
```

## Security Checklist

- [ ] RLS is enabled on all user-data tables
- [ ] API credentials policies are STRICTLY isolated
- [ ] Admin users can view all data
- [ ] Public market data is readable by all
- [ ] Service role key is kept secret (backend only)
- [ ] JWT tokens are validated on backend
- [ ] Frontend includes auth tokens in API requests

## Support

If RLS is causing issues:
1. Check Supabase logs for policy errors
2. Verify the user has proper auth context
3. Test with service role to isolate RLS issues
4. Check that tables have `rowsecurity = true`

---

**Recommended:** Enable RLS before moving to production. The provided `SUPABASE_ENABLE_RLS.sql` has been tested and covers all necessary policies.
