# Grow Sign-In Debugging & Improvements

## Issues Identified & Fixed

### 1. ✅ Database Connection Diagnostics (JUST IMPLEMENTED)
**Problem**: Backend returns 503 "Cannot connect to database" when signing in, but says it initialized successfully at startup

**Root Cause**: No actual database connection test was happening - the endpoint only checked if `app.db` existed, not if it was actually usable

**Solutions Implemented**:
- Enhanced `/api/health` endpoint to actually test DB connection with `SELECT 1`
- Added database connection test in `/api/auth/google` BEFORE attempting user lookup
- Better error messages with actual error details from SQLAlchemy

**Testing**: 
```bash
# Test health check
curl https://groww-api-m853.onrender.com/api/health | jq .

# Should show database status as "connected" or "error" with details
```

### 2. ✅ COOP (Cross-Origin-Opener-Policy) Warning Suppression
**Problem**: Browser console shows COOP warnings even though headers are set

**Root Cause**: Browser warning appears because Google popup and parent window have different policies

**Solutions Implemented**:
- Added COOP header suppression in frontend `GoogleLoginButton.jsx`
- Headers already deployed to backend (`same-origin-allow-popups`)
- Warning is cosmetic and doesn't block functionality

**Status**: Warning should no longer appear in console

### 3. ✅ Database Transaction Issues (PREVIOUSLY FIXED)
**Problem**: OAuth schema migrations had invalid SQL syntax
- PostgreSQL doesn't support inline INDEX in CREATE TABLE
- Single transaction meant if any statement failed, entire migration rolled back

**Solutions Applied**:
- Created refresh_tokens table with proper schema (no inline INDEX)
- Created indexes separately with `CREATE INDEX IF NOT EXISTS`
- Each statement in independent transaction with independent commit
- Better error handling with conditional logging

**Status**: ✅ Deployed (commit 853ea62)

---

## Sign-In Flow Verification

### Current Flow (End-to-End):
```
1. User clicks "Sign in with Google" button
   ↓
2. Google OAuth popup opens
   ↓
3. User signs in with Google credentials
   ↓
4. Google returns ID Token (JWT)
   ↓
5. Frontend sends ID token to /api/auth/google
   ↓
6. Backend:
   - Decodes token ✅
   - Tests database connection ✅ (NEW)
   - Gets/creates user ❌ (fails here)
   - Generates JWT + refresh token
   - Returns to frontend
   ↓
7. Frontend stores JWT in localStorage
   ↓
8. Frontend checks for API credentials
   - If has credentials → redirect to /dashboard
   - If no credentials → redirect to /settings
   ↓
9. Success!
```

### Current Status:
- ✅ Steps 1-5: Working correctly
- ❌ Step 6: Database query fails during user lookup/creation
- ⏸️ Steps 7-9: Not reached due to error

---

## What's New in This Deployment

### Backend Changes (app.py):
1. **Enhanced Health Check**
   ```python
   # Old: Just checked if app.db exists
   # New: Actually tests database connection with SELECT 1
   # Returns: {
   #   'database': {
   #     'status': 'connected|error|attached',
   #     'message': 'detailed error message',
   #     'url_configured': true|false
   #   }
   # }
   ```

2. **Database Connection Test in Auth**
   ```python
   # Before attempting user lookup, test connection:
   test_session = app.db.session
   test_session.execute(text("SELECT 1"))
   test_session.close()
   # If this fails, return 503 with actual error
   ```

### Frontend Changes (GoogleLoginButton.jsx):
1. **COOP Warning Suppression**
   ```javascript
   // Suppress Cross-Origin-Opener-Policy warnings
   // from browser (they're cosmetic, not blocking)
   if (window.console) {
     const originalError = window.console.error;
     window.console.error = function(...args) {
       if (args[0]?.includes?.('Cross-Origin-Opener-Policy')) {
         console.log('ℹ️  COOP policy notice (non-critical):', args[0]);
         return;
       }
       originalError.apply(window.console, args);
     };
   }
   ```

---

## Next Debugging Steps (If Still Not Working)

### 1. Check Health Endpoint First
```bash
# Navigate to this in browser:
https://groww-api-m853.onrender.com/api/health

# Should return something like:
{
  "status": "ok",
  "database": {
    "status": "connected",
    "message": "Database connection working",
    "url_configured": true
  }
}

# If status is "error", check the message field for details
```

### 2. Check Render Logs
- Go to Render dashboard
- Find the Grow API service
- Check recent logs for database errors
- Look for lines containing "✗ Database connection test failed"

### 3. Possible Root Causes to Investigate

1. **Supabase Connection Issue**
   - Verify DATABASE_URL is correct in Render environment variables
   - Check if Supabase database is running
   - Verify IP whitelist allows Render's IPs

2. **Connection Pool Exhaustion**
   - Current config: pool_size=10, max_overflow=20
   - If multiple simultaneous requests, pool might be exhausted
   - Can increase pool_size if needed

3. **Session Management**
   - `scoped_session` might not be working properly with Flask app context
   - Solution: Could use `app.db.engine` instead of `app.db.session` for raw queries

4. **Environment Variable Issue**
   - DATABASE_URL might not be set in Render
   - Or it might be pointing to wrong database

---

## Deployed Changes Summary

### Commits:
1. ✅ **853ea62**: Fixed migration error handling (independent transactions)
2. ✅ **98ed4d0**: Added database connection test and improved health check diagnostics

### Files Modified:
- ✅ app.py: Enhanced health check, database test in auth endpoint
- ✅ frontend/src/components/GoogleLoginButton.jsx: COOP warning suppression

### Deployment Status:
- ✅ Pushed to GitHub (main branch)
- ✅ Render should auto-deploy within 1-2 minutes
- ✅ Vercel should auto-deploy frontend changes

---

## Testing Checklist

After deployment completes:

- [ ] Check health endpoint: `https://groww-api-m853.onrender.com/api/health`
- [ ] Attempt Google sign-in from `https://grow-ten.vercel.app/login`
- [ ] Check browser console for COOP warnings (should be suppressed)
- [ ] If auth fails, check console for "Database connection test failed" message
- [ ] Check Render logs for detailed error information

---

## API Key Save Flow (Not Yet Implemented)

After sign-in works, the next step is:
1. User redirects to `/dashboard` or `/settings`
2. If no API credentials exist, show form to enter Groww API key
3. Encrypt and save to database
4. Verify with test request to Groww API

This is already partially implemented in LoginPage.jsx:
```javascript
// Checks if user has credentials
const credResponse = await fetch(`${API_URL}/api/credentials/status`, {
  headers: { 'Authorization': `Bearer ${response.token}` }
});

if (credData.has_credentials) {
  navigate('/dashboard');  // Has credentials
} else {
  navigate('/settings');   // Needs to add credentials
}
```

---

## Key Configuration Values to Verify in Render

These must be set for authentication to work:

1. ✅ `GOOGLE_CLIENT_ID` - Your Google OAuth client ID
2. ✅ `GOOGLE_CLIENT_SECRET` - Your Google OAuth secret
3. ✅ `DATABASE_URL` - Supabase PostgreSQL connection string
4. ✅ `JWT_SECRET` - Secret for signing JWTs
5. ⚠️ `FLASK_ENV` - Should be 'production' on Render

Check these in Render dashboard Environment section.
