# Deployment Security Checklist

## Pre-Production (Before Launch)

- [ ] **Enable RLS in Supabase**
  ```sql
  -- Run SUPABASE_ENABLE_RLS.sql in Supabase Console
  ```
  See: `RLS_SETUP_GUIDE.md`

- [ ] **Verify API Credentials are Isolated**
  ```javascript
  // Test: User A should NOT see User B's credentials
  // Should return empty or 403
  ```

- [ ] **Enable HTTPS Everywhere**
  - ✅ Vercel (automatic)
  - ✅ Render backend (automatic)

- [ ] **Rotate Secrets Before Launch**
  - [ ] Update `JWT_SECRET` (app.py)
  - [ ] Update `ENCRYPTION_KEY` (app.py)
  - [ ] Update `GOOGLE_CLIENT_SECRET` (new Google OAuth credentials)
  - [ ] Update Supabase service role key

- [ ] **Set Environment Variables**
  - Vercel: Settings → Environment Variables
  - Render: Environment variables in dashboard
  - Never commit `.env` files with secrets

- [ ] **Test Authentication Flow**
  - [ ] Sign up with Google → User created
  - [ ] Add API credentials → Encrypted & stored
  - [ ] Logout → Token cleared
  - [ ] Login as different user → See only own data

- [ ] **Security Headers**
  ```python
  # app.py should include:
  # CORS: Only allow frontend domain
  # Content-Security-Policy: Strict
  # X-Frame-Options: DENY
  ```

- [ ] **Database Backups Enabled**
  - [ ] Supabase auto-backup (included)
  - [ ] Regular backup schedule
  - [ ] Test restore process

- [ ] **Rate Limiting & DDoS Protection**
  - [ ] Enable Cloudflare (free tier)
  - [ ] Or use Render's built-in protection
  - [ ] Configure on `/api/auth/google` endpoint

## Production Maintenance

- [ ] **Monitor Error Logs**
  - Render: "Logs" tab
  - Supabase: "Logs" explorer
  - Look for: RLS policy errors, database connection errors

- [ ] **Regular Security Audits**
  - [ ] Monthly: Review user access logs
  - [ ] Monthly: Check for inactive accounts
  - [ ] Quarterly: Audit RLS policies
  - [ ] Yearly: Full security review

- [ ] **Update Dependencies**
  - [ ] Flask & Python packages (monthly)
  - [ ] React & npm packages (monthly)
  - [ ] Check for security vulnerabilities

## Never In Production

❌ Disable RLS
❌ Use `SUPABASE_DISABLE_RLS.sql`
❌ Commit secrets to GitHub
❌ Use default passwords
❌ Allow public database access
❌ Skip HTTPS
❌ Use `console.log()` for sensitive data

## RLS Verification Command

Run in Supabase SQL Editor to verify production readiness:

```sql
-- Should show rowsecurity = true for all important tables
SELECT tablename, rowsecurity 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename IN (
    'users', 'api_credentials', 'user_settings', 
    'trade_journal', 'trade_log', 'paper_trades'
  )
ORDER BY tablename;

-- Expected output: All should show TRUE for rowsecurity
```

## Post-Launch Monitoring

### Daily
- [ ] Check Render error logs
- [ ] Monitor Vercel deployment health
- [ ] Check Supabase database connections

### Weekly
- [ ] Review user feedback
- [ ] Check for failed API requests
- [ ] Verify backups are running

### Monthly
- [ ] Security audit of access logs
- [ ] Review and update dependencies
- [ ] Check database performance

## Incident Response

If RLS policy blocks legitimate requests:

1. **Check logs** (Supabase SQL Editor)
   ```sql
   SELECT * FROM pg_stat_statements WHERE query LIKE '%denied%';
   ```

2. **Identify the policy** causing the issue

3. **Options:**
   - Fix the policy (correct solution)
   - Update app logic (if app logic was wrong)
   - Temporarily disable RLS in dev to debug, then fix

4. **Never** permanently disable RLS in production

## Rollback Plan

If serious issues occur:

1. **Quick fix:** Review the specific RLS policy, don't disable all
2. **If blocked:** Update the policy to be less restrictive
3. **Last resort:** Contact Supabase support
4. **Never:** Disable RLS entirely

---

**Remember:** RLS in production is non-negotiable. It's not optional - it's mandatory for data security in a multi-user SaaS app.
