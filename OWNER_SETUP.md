# Groww AI Trading Platform - Owner Setup Guide

## Overview

You are the **owner** of this AI trading platform. This guide explains how to configure it with your trading credentials and share it with your friend.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Your Friend's Browser                                   │
│ (https://grow.ten.vercel.app)                          │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP/HTTPS
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Frontend (React/Vercel)                                 │
│ - Sign in with Google                                   │
│ - Dashboard, Analytics, Trading                         │
│ - Calls API endpoints                                   │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS
                     ▼
┌─────────────────────────────────────────────────────────┐
│ Backend (Flask/Render)                                  │
│ - groww-api-m853.onrender.com                          │
│ - Processes trades, fetches data                        │
│ - Stores data in Supabase                              │
└────────────────┬──────────────────┬──────────────────────┘
                 │                  │
                 ▼                  ▼
        ┌──────────────┐   ┌─────────────────┐
        │ Groww API    │   │ Supabase DB     │
        │ (Your creds) │   │ (Trading data)  │
        └──────────────┘   └─────────────────┘
```

---

## Step 1: Get Your Groww API Credentials (One-Time Setup)

1. Go to [Groww Trading Platform](https://groww.in)
2. Log in to your account
3. Go to **Settings → Developer API** (or API Console)
4. Create a new API application:
   - **App Name**: "Groww AI Bot"
   - **Description**: "My automated trading bot"
5. You'll get:
   - `API Key`
   - `API Secret`
   - `Access Token`
6. **Save these securely** - you'll need them below

---

## Step 2: Configure on Render (Backend)

Your backend is hosted on Render at `https://groww-api-m853.onrender.com`

### Add Environment Variables:

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click on **"groww-api"** project
3. Go to **Settings → Environment**
4. Add these variables:

```
GROWW_API_KEY = <your API key from Step 1>
GROWW_API_SECRET = <your API secret from Step 1>  
GROWW_ACCESS_TOKEN = <your access token from Step 1>
JWT_SECRET = some-random-secret-key-12345
SECRET_KEY = another-random-secret-67890
ENCRYPTION_KEY = fernet-key-generated-below
GOOGLE_CLIENT_ID = 909946700089-5fr10qa7c51cl88ofmft1gp9f6eldsv1.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET = <get from Google Cloud Console>
DATABASE_URL = postgresql://postgres:f6n2GYbXyTYi1TlD@db.vvonimxqwporrofklnvf.supabase.co:5432/postgres
```

### Generate Encryption Key:

Open Python and run:
```python
from cryptography.fernet import Fernet
key = Fernet.generate_key().decode()
print(key)
```

Copy the output and paste as `ENCRYPTION_KEY` on Render.

### Redeploy:

1. Click "Manual Deploy" on Render
2. Wait 5 minutes for deployment
3. Test: `curl https://groww-api-m853.onrender.com/api/health`

---

## Step 3: Configure Google OAuth on Google Cloud

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Select your project "Groww AI Trading"
3. Go to **Credentials**
4. Click on your OAuth 2.0 Client ID
5. Add these **Authorized Redirect URIs**:
   ```
   https://grow.ten.vercel.app/callback
   http://localhost:8000/callback
   ```
6. Copy the **Client Secret** and add to Render environment (step above)
7. Save

---

## Step 4: Run Locally (For Your Testing)

```bash
# Clone the repo
cd /Users/parthsharma/Desktop/Grow

# Create .env file with your credentials
cp .env.production .env

# Install dependencies
pip install -r requirements.txt

# Start Flask backend (Terminal 1)
python3 app.py

# In another terminal, start React frontend (Terminal 2)
cd frontend
npm install
npm run dev

# Open browser
# - Frontend: http://localhost:5173
# - API: http://localhost:8000
```

---

## Step 5: Share with Your Friend

Give your friend this link:
```
https://grow.ten.vercel.app
```

### What Your Friend Can Do:

1. **Sign In**: Click "Sign in with Google" (they use their own Google account)
2. **View Dashboard**: See real-time portfolio stats
3. **View Analytics**: See P&L charts, ROI, trade history
4. **View Paper Trading**: Backtest and simulate trades
5. **Can NOT**: 
   - Access your Groww credentials (server-side only)
   - Modify trading settings (owner-only)
   - See other users' data (isolated by Google account)

---

## Step 6: Using It Yourself as Owner

### Add Your API Credentials:

After signing in on https://grow.ten.vercel.app:

1. Go to **Settings** (if exists) or via API
2. Your Groww credentials are already configured server-side from Render environment variables
3. The app will use them automatically for all API calls

### Data Flow:

```
Your Trading Activity
    ↓
Your Browser (Vercel Frontend)
    ↓
Your Authentication (Google JWT)
    ↓
Render Backend (Uses GROWW_API_KEY, etc.)
    ↓
Groww API (Fetches your real trading data)
    ↓
Supabase Database (Stores analysis, P&L, etc.)
    ↓
Your Dashboard (Shows your real P&L, trades)
```

---

## Maintenance & Troubleshooting

### Backend Logs:

Check Render logs:
```
https://dashboard.render.com → groww-api → Logs
```

Look for errors:
- Database connection issues
- Missing environment variables
- API authentication failures

### Database Issues:

Connect to Supabase:
```bash
psql postgresql://postgres:f6n2GYbXyTYi1TlD@db.vvonimxqwporrofklnvf.supabase.co:5432/postgres
```

View tables:
```sql
\dt              -- List all tables
SELECT * FROM users;  -- Check if user created
```

### API Health Check:

```bash
curl https://groww-api-m853.onrender.com/api/health
```

Should return: `{"status": "ok"}`

---

## Security Best Practices

1. **Never commit `.env` file to git**
   - `.env.production` is a template only
   - Real credentials go in Render dashboard only

2. **Rotate API Keys Quarterly**
   - Get new Groww API credentials
   - Update Render environment variables
   - Trigger redeploy

3. **Use Strong Passwords**
   - JWT_SECRET: Random 32+ characters
   - ENCRYPTION_KEY: Generated by Fernet
   - SECRET_KEY: Random 32+ characters

4. **Monitor Access**
   - Check Render logs regularly
   - Monitor Supabase for unusual queries
   - Review authentication logs

---

## Environment Variables Reference

| Variable | Purpose | Example |
|----------|---------|---------|
| `GROWW_API_KEY` | Your Groww trading API key | `abc123...` |
| `GROWW_API_SECRET` | Your Groww API secret | `xyz789...` |
| `GROWW_ACCESS_TOKEN` | Your Groww access token | `token_abc...` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://...` |
| `JWT_SECRET` | Secret for JWT tokens | `randomString123` |
| `SECRET_KEY` | Flask secret key | `randomString456` |
| `ENCRYPTION_KEY` | Fernet encryption key | `Z0FIbXd...` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | `909946...` |
| `GOOGLE_CLIENT_SECRET` | Google OAuth secret | `GOCSPX...` |
| `API_URL` | Internal API URL | `http://localhost:10000` |

---

## What's Running Where?

| Service | URL | Provider | Status |
|---------|-----|----------|--------|
| Frontend | https://grow.ten.vercel.app | Vercel | ✅ Live |
| Backend API | https://groww-api-m853.onrender.com | Render | ✅ Live |
| Database | db.vvonimxqwporrofklnvf.supabase.co | Supabase | ✅ Live |
| Auth | Google OAuth | Google Cloud | ✅ Configured |

---

## Support

For issues:
1. Check Render logs: https://dashboard.render.com
2. Check database: https://app.supabase.com
3. Test API: `curl https://groww-api-m853.onrender.com/api/health`
4. Check frontend console: Browser DevTools → Console

---

**Last Updated**: 16 April 2026
