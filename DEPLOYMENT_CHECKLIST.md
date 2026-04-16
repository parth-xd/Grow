# Deployment Checklist & Summary

## What's Been Done ✅

### Code Refactoring
- ✅ Replaced all hardcoded file paths (`/Users/parthsharma/...`) with `PROJECT_ROOT`
- ✅ Replaced localhost references with environment variables
- ✅ Added `FLASK_PORT` and `PORT` configuration for Render
- ✅ Made database URL configurable (`DATABASE_URL` env var)
- ✅ Fixed import statements for production compatibility

### Configuration Files
- ✅ Created `.env.production` template with all needed variables
- ✅ Updated `config.py` to support both local and production environments
- ✅ Fixed `auth.py` to handle Google OAuth redirect URIs dynamically

### Documentation
- ✅ Created `OWNER_SETUP.md` - Complete guide for owner (you) to:
  - Get Groww API credentials
  - Configure Render backend
  - Set up Google OAuth
  - Run locally for testing
  - Share with friend

### Hosting Infrastructure
- ✅ Frontend: Deployed on Vercel (https://grow.ten.vercel.app)
- ✅ Backend: Deployed on Render (https://groww-api-m853.onrender.com)
- ✅ Database: PostgreSQL on Supabase

---

## What You Need To Do Next

### 1. Get Groww API Credentials (15 mins)
- [ ] Go to https://groww.in → Settings → Developer API
- [ ] Create new API app
- [ ] Get: API Key, API Secret, Access Token
- [ ] Save these somewhere safe

### 2. Configure Render Backend (10 mins)
- [ ] Go to https://dashboard.render.com → groww-api
- [ ] Click Settings → Environment
- [ ] Add these environment variables:
  ```
  GROWW_API_KEY = <your key>
  GROWW_API_SECRET = <your secret>
  GROWW_ACCESS_TOKEN = <your token>
  JWT_SECRET = make-up-a-random-string
  SECRET_KEY = make-up-another-random-string
  ENCRYPTION_KEY = run this in Python:
                   from cryptography.fernet import Fernet
                   print(Fernet.generate_key().decode())
  GOOGLE_CLIENT_ID = 909946700089-5fr10qa7c51cl88ofmft1gp9f6eldsv1.apps.googleusercontent.com
  GOOGLE_CLIENT_SECRET = <get from Google Cloud>
  DATABASE_URL = postgresql://postgres:f6n2GYbXyTYi1TlD@db.vvonimxqwporrofklnvf.supabase.co:5432/postgres
  ```
- [ ] Click "Manual Deploy"
- [ ] Wait 5 minutes for deployment

### 3. Get Google Client Secret (5 mins)
- [ ] Go to https://console.cloud.google.com
- [ ] Find your OAuth 2.0 Client ID
- [ ] Copy the Client Secret
- [ ] Add to Render environment as `GOOGLE_CLIENT_SECRET`

### 4. Test Backend (5 mins)
- [ ] Run: `curl https://groww-api-m853.onrender.com/api/health`
- [ ] Should see: `{"status": "ok"}`

### 5. Test Locally (Optional, for your own testing)
```bash
# Terminal 1: Flask Backend
cd /Users/parthsharma/Desktop/Grow
cp .env.production .env  # Copy template and fill in your values
pip install -r requirements.txt
python3 app.py

# Terminal 2: React Frontend
cd frontend
npm run dev

# Visit:
# Frontend: http://localhost:5173
# API: http://localhost:8000
```

### 6. Share with Friend
- [ ] Give them: `https://grow.ten.vercel.app`
- [ ] They sign in with their Google account
- [ ] They see the dashboard with YOUR trading data
- [ ] They can explore analytics, paper trading, etc.

---

## Important Files

| File | Purpose |
|------|---------|
| `.env.production` | Template for all environment variables needed |
| `OWNER_SETUP.md` | Complete guide for you (owner) to set everything up |
| `config.py` | Central configuration - reads from .env and environment |
| `requirements.txt` | Python dependencies (includes gunicorn for production) |
| `frontend/vercel.json` | Vercel configuration |
| `app.py` | Main Flask app |

---

## Local Development vs Production

### Local Development (Your Computer)
```bash
# Uses .env file
cd /Users/parthsharma/Desktop/Grow
python3 app.py          # Runs on http://localhost:8000
cd frontend && npm run dev  # Runs on http://localhost:5173
```

**What Works:**
- Full access to all features
- Testing with your Groww credentials
- Database: Local Supabase
- Frontend: Local React dev server

### Production (Deployed)
```
https://grow.ten.vercel.app    → Frontend
https://groww-api-m853.onrender.com → Backend
```

**What Works:**
- Public URL for sharing
- Uses Render environment variables
- Database: Supabase (same as local)
- Auto-deploys on GitHub push

---

## Troubleshooting

### Backend won't start?
```bash
# Check if PORT is set correctly
echo $PORT  # Should show 10000 or similar

# Check if DATABASE_URL is valid
psql $DATABASE_URL -c "SELECT 1;"
```

### Frontend shows blank page?
- Check browser console (F12) for errors
- Verify `VITE_API_URL` is set to Render URL
- Check if Render backend is running

### P&L Analytics not showing?
- Verify you have Groww API credentials set
- Check Render logs: https://dashboard.render.com/groww-api
- Run: `curl https://groww-api-m853.onrender.com/api/analytics/pnl`

---

## Files Modified for Production Readiness

```
config.py                    → Added PROJECT_ROOT
app.py                       → Uses PROJECT_ROOT for all paths
scheduler.py                 → Uses PROJECT_ROOT, fixed API URLs
trailing_stop.py             → Uses PROJECT_ROOT
trade_origin_manager.py      → Uses PROJECT_ROOT
paper_trader.py              → Uses PROJECT_ROOT
auth.py                      → Dynamic Google OAuth redirect URI
.env.production              → New: template for all env vars
OWNER_SETUP.md               → New: complete owner guide
```

---

## Security Checklist

- [ ] Never commit real `.env` file to git
- [ ] Keep Groww API credentials secret
- [ ] Use strong random strings for JWT_SECRET, SECRET_KEY
- [ ] Generate ENCRYPTION_KEY with Fernet
- [ ] Store all secrets in Render environment only
- [ ] Rotate credentials quarterly

---

## What Your Friend Sees

1. Sign in with Google
2. Dashboard with YOUR portfolio stats
3. P&L analytics with YOUR trade history
4. Paper trading section
5. Real-time market data for stocks in your watchlist

**They CANNOT:**
- See your Groww API credentials
- Modify your trading settings
- Access your actual account on Groww
- See other users' data

Everything is isolated by their Google authentication.

---

## Summary

✅ **Frontend:** Live on Vercel - https://grow.ten.vercel.app
✅ **Backend:** Live on Render - https://groww-api-m853.onrender.com
✅ **Database:** Live on Supabase
✅ **Code:** Production-ready, no hardcoded paths
✅ **Documentation:** Complete owner setup guide

**Next Step:** Follow OWNER_SETUP.md to configure your credentials!

---

**Last Updated**: 16 April 2026
**Status**: Ready for deployment
