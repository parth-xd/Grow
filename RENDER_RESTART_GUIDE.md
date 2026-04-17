# Render Manual Restart Guide

## Issue:
- Render environment variable `DATABASE_URL` is SET ✅
- But code is connecting to localhost ❌
- This means Render hasn't deployed the latest code yet

## Solution: Force Render to Restart

### Option 1: Auto-Restart (WAIT 5-10 minutes)
Render should auto-deploy within 5-10 minutes. Then:
1. Test: https://grow-ten.vercel.app/login
2. Try signing in again

### Option 2: Manual Restart (IMMEDIATE)
1. Go to: https://dashboard.render.com
2. Click **"Grow API"** (groww-api service)
3. Scroll to top-right, click **"Restart"** button
4. Wait for it to redeploy (2-3 minutes)
5. Once status = **"Live"**, test sign-in

### Option 3: Check Auto-Deploy Status
1. Go to: https://dashboard.render.com
2. Click **"Grow API"** service
3. Look for "Recent Deploys" section
4. Check if `abb6e8a` deployment is "Building" or "Live"
   - Building = wait, it's deploying
   - Live = restart complete, test sign-in

## After Restart:
```bash
# Health endpoint should show url_preview field:
curl https://groww-api-m853.onrender.com/api/health | jq .database

# Should show: url_preview: "postgresql://postgres:***@db.xxx.supabase.co:5432..."
```

## Then Test Sign-In:
1. https://grow-ten.vercel.app/login
2. Click "Sign in with Google"
3. Should work! ✅
