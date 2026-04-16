# 🚀 Grow SaaS - Complete Deployment Guide

## Prerequisites

- Git account (GitHub)
- Railway account (free tier available)
- Vercel account (free tier available)
- Google Cloud project with OAuth setup
- PostgreSQL database (Railway provides)

---

## 📋 Step-by-Step Deployment

### **Step 1: Setup Google OAuth**

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project: "Grow Trading"
3. Enable "Google+ API"
4. Create OAuth 2.0 credentials (Web application)
5. Add authorized redirect URIs:
   - `http://localhost:8000/api/auth/google/callback` (local dev)
   - `https://grow-api.railway.app/api/auth/google/callback` (production)
   - `https://grow-app.vercel.app/auth/google/callback` (frontend)
6. Copy `Client ID` and `Client Secret`

### **Step 2: Prepare Backend (Flask)**

#### 2.1 Generate Required Keys

```bash
cd /Users/parthsharma/Desktop/Grow

# Generate encryption key for API credentials
python3 << 'EOF'
from cryptography.fernet import Fernet
key = Fernet.generate_key().decode()
print(f"ENCRYPTION_KEY={key}")
EOF

# Generate JWT secret
python3 << 'EOF'
import secrets
secret = secrets.token_urlsafe(32)
print(f"JWT_SECRET={secret}")
EOF

# Generate Flask secret
python3 << 'EOF'
import secrets
secret = secrets.token_hex(32)
print(f"FLASK_SECRET_KEY={secret}")
EOF
```

#### 2.2 Update .env file

```bash
# Create/update .env
cat > .env << 'EOF'
# Flask
FLASK_ENV=production
FLASK_SECRET_KEY=<your_flask_secret_key>

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/grow

# Authentication
JWT_SECRET=<your_jwt_secret>
GOOGLE_CLIENT_ID=<your_google_client_id>
GOOGLE_CLIENT_SECRET=<your_google_client_secret>
GOOGLE_REDIRECT_URI=https://grow-api.railway.app/api/auth/google/callback

# Encryption
ENCRYPTION_KEY=<your_encryption_key>
EOF
```

#### 2.3 Run Database Migration

```bash
python3 migrate_to_saas.py
```

This will:
- ✓ Create user management tables
- ✓ Add user_id to all existing tables
- ✓ Create admin user (admin@grow.app)
- ✓ Migrate your 56 existing trades to admin user

#### 2.4 Update requirements.txt

```bash
# Add these packages to requirements.txt
pip install authlib[client] cryptography PyJWT

# Freeze requirements
pip freeze > requirements.txt
```

### **Step 3: Deploy Backend to Railway**

#### 3.1 Create Railway Project

1. Go to [railway.app](https://railway.app)
2. Click "New Project"
3. Select "GitHub repo"
4. Choose your Grow repository
5. Railway detects `railway.yaml` automatically

#### 3.2 Configure Environment Variables

In Railway dashboard, add:
- `DATABASE_URL` → PostgreSQL connection string
- `FLASK_SECRET_KEY` → from .env
- `JWT_SECRET` → from .env
- `GOOGLE_CLIENT_ID` → from Google Cloud
- `GOOGLE_CLIENT_SECRET` → from Google Cloud
- `ENCRYPTION_KEY` → from .env
- `GOOGLE_REDIRECT_URI` → `https://grow-api.railway.app/api/auth/google/callback`

#### 3.3 Deploy

```bash
# Push to GitHub
git add .
git commit -m "Add SaaS authentication and multi-tenancy"
git push origin main

# Railway auto-deploys from GitHub
# Check deployment status in Railway dashboard
```

**Status Check:**
```bash
curl https://grow-api.railway.app/api/health
# Should return: {"status": "healthy"}
```

### **Step 4: Deploy Frontend to Vercel**

#### 4.1 Prepare Frontend

```bash
cd frontend

# Create .env.local for local development
cat > .env.local << 'EOF'
VITE_API_URL=http://localhost:8000
VITE_GOOGLE_CLIENT_ID=<your_google_client_id>
EOF

# For production (.env.production or Vercel dashboard)
VITE_API_URL=https://grow-api.railway.app
VITE_GOOGLE_CLIENT_ID=<your_google_client_id>
```

#### 4.2 Deploy to Vercel

1. Go to [vercel.com](https://vercel.com)
2. Click "New Project"
3. Import your GitHub repository
4. Select "frontend" folder
5. Add environment variables:
   - `VITE_API_URL` → `https://grow-api.railway.app`
   - `VITE_GOOGLE_CLIENT_ID` → from Google Cloud
6. Click "Deploy"

**Your frontend will be at:** `https://grow-app.vercel.app`

### **Step 5: Update Google OAuth Redirect URIs**

Update Google Cloud console with final URLs:
- Backend callback: `https://grow-api.railway.app/api/auth/google/callback`
- Frontend login: `https://grow-app.vercel.app/login`

---

## 🔧 Backend API Endpoints

### Authentication
```
POST /api/auth/google
  Request: { auth_code: "..." }
  Response: { token: "jwt...", user: {...} }

POST /api/auth/logout
  
GET /api/auth/verify
  Response: { user: {...} }
```

### User Management
```
GET /api/users/profile
  Response: { user: {...} }

PUT /api/users/profile
  Request: { name: "...", email: "..." }

POST /api/users/api-credentials
  Request: { api_key: "...", api_secret: "..." }

GET /api/users/api-credentials
  Response: { has_credentials: true }
```

### Trading
```
GET /api/trades/journal
  Response: { trades: [...], stats: {...} }

POST /api/trades/execute
  Request: { symbol: "INFY", side: "BUY", quantity: 1, type: "PAPER" }

GET /api/trades/journal/stats
  Response: { total_trades: 56, win_rate: 83.93, ... }
```

### Admin
```
GET /api/admin/users
  Response: { users: [...] }

GET /api/admin/system-health
  Response: { database: "healthy", api: "healthy", ... }
```

---

## 🧪 Testing After Deployment

### 1. Test Backend Health
```bash
curl https://grow-api.railway.app/api/health
```

### 2. Test Admin User Login
Go to: `https://grow-app.vercel.app/login`
- Use Google login
- Should create/login user account
- Redirects to dashboard with 56 demo trades

### 3. Test API Credentials
- Go to Settings
- Enter fake Groww API key (for demo)
- Should save encrypted

### 4. Test Paper Trading
- Go to Trading page
- Execute test trade
- Should appear in Trade Journal

### 5. Test Admin Dashboard
- Login as admin
- Go to /admin
- Should see all users list

---

## 📊 Local Development Setup

### Run Backend Locally

```bash
cd /Users/parthsharma/Desktop/Grow

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migration (one-time)
python3 migrate_to_saas.py

# Start Flask
python3 app.py
# API at http://localhost:8000
```

### Run Frontend Locally

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
# Frontend at http://localhost:5173
```

### Local Testing

```bash
# Test login flow
curl -X POST http://localhost:8000/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"auth_code": "test_code"}'

# Test API
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/users/profile
```

---

## 🔒 Security Checklist

- [ ] Google OAuth client secrets stored in environment variables
- [ ] API keys encrypted with Fernet
- [ ] JWT tokens signed with secret key
- [ ] HTTPS enforced (automatic on Railway/Vercel)
- [ ] CORS configured for allowed domains
- [ ] Rate limiting on sensitive endpoints
- [ ] Admin endpoints require is_admin check
- [ ] User data isolation (user_id on all queries)

---

## 📈 Scaling for Production

### Database Optimization
```sql
-- Indexes for performance
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_trades_user_id ON trade_journal(user_id);
CREATE INDEX idx_pnl_user_created ON pnl_snapshots(user_id, created_at);
```

### Performance Monitoring
- Setup Sentry for error tracking
- Setup DataDog for performance monitoring
- Enable Railway logs and alerts

### Database Backups
```bash
# Railway auto-backups PostgreSQL
# Manual backup:
pg_dump postgresql://... > backup.sql
```

---

## 🚨 Troubleshooting

### "Database connection failed"
- Check DATABASE_URL environment variable
- Verify PostgreSQL is running
- Check network connectivity

### "Google OAuth failed"
- Verify client ID/secret match Google Cloud
- Check redirect URI matches exactly
- Clear browser cookies and retry

### "API key decryption failed"
- Verify ENCRYPTION_KEY hasn't changed
- Regenerate encryption key and re-save API credentials

### "404 on API endpoints"
- Check Flask is running
- Verify endpoint paths match exactly
- Check Authorization header includes "Bearer " prefix

---

## ✨ Next Steps After Launch

1. **Email Notifications**: Add Sendgrid for alerts
2. **Webhook**: Add Groww webhook for real-time updates
3. **Analytics**: Setup Google Analytics on frontend
4. **Documentation**: Create user guides
5. **Support**: Setup Intercom for user support
6. **Monitoring**: Setup uptime monitoring (Uptimerobot)

---

## 📞 Support

For issues during deployment:
1. Check Railway logs: `railway logs`
2. Check Vercel build logs: Dashboard → Deployments
3. Check local .env configuration
4. Verify Google OAuth configuration
5. Check CORS headers if frontend can't reach API

---

**🎉 Congratulations! Your SaaS is now live!**

- Backend: https://grow-api.railway.app
- Frontend: https://grow-app.vercel.app
- Admin Dashboard: https://grow-app.vercel.app/admin
