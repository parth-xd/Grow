# 📱 Grow ML Trading Platform - SaaS Implementation Guide

## Overview
Converting the existing Grow trading app into a multi-user SaaS platform with Google OAuth, secure API key storage, and per-user dashboards.

---

## 📋 Architecture

### System Components
```
┌──────────────────────────────────────────────────────────┐
│                 USER (Browser)                           │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTPS
         ┌───────────────▼───────────────┐
         │   FRONTEND (React/Vercel)     │
         │  ┌─────────────────────────┐  │
         │  │ Landing Page            │  │
         │  │ Google OAuth Login      │  │
         │  │ Dashboard               │  │
         │  │ Settings (API Key)      │  │
         │  │ Trading Interface       │  │
         │  │ Backtesting             │  │
         │  │ Admin Dashboard         │  │
         │  └─────────────────────────┘  │
         └───────────────┬────────────────┘
                         │ REST API
         ┌───────────────▼──────────────────┐
         │  BACKEND (Flask/Railway)         │
         │  ┌──────────────────────────┐    │
         │  │ Auth Endpoints           │    │
         │  │ User Management          │    │
         │  │ Trading APIs             │    │
         │  │ ML Prediction            │    │
         │  │ Backtest Engine          │    │
         │  │ Real Trading Execution   │    │
         │  │ Admin APIs               │    │
         │  └──────────────────────────┘    │
         └───────────────┬──────────────────┘
                         │ SQL
         ┌───────────────▼──────────────────┐
         │  DATABASE (PostgreSQL/Railway)   │
         │  ┌──────────────────────────┐    │
         │  │ users                    │    │
         │  │ api_credentials          │    │
         │  │ trade_journal (per user) │    │
         │  │ pnl_snapshots (per user) │    │
         │  │ paper_trades (per user)  │    │
         │  │ user_settings            │    │
         │  │ admin_logs               │    │
         │  └──────────────────────────┘    │
         └────────────────────────────────┘
```

---

## 🗄️ Database Schema Changes

### New Tables (User Management)

#### `users` table
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    google_id VARCHAR(255) UNIQUE,
    profile_picture_url TEXT,
    is_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);
```

#### `api_credentials` table
```sql
CREATE TABLE api_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    encrypted_groww_api_key TEXT NOT NULL,
    encrypted_groww_secret TEXT NOT NULL,
    is_live_trading BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id)
);
```

#### `user_settings` table
```sql
CREATE TABLE user_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    paper_trading_enabled BOOLEAN DEFAULT TRUE,
    real_trading_enabled BOOLEAN DEFAULT FALSE,
    max_risk_per_trade FLOAT DEFAULT 2.0,
    backtesting_enabled BOOLEAN DEFAULT TRUE,
    notifications_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `admin_logs` table
```sql
CREATE TABLE admin_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES users(id),
    action_type VARCHAR(50),
    action_description TEXT,
    affected_user_id UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Modified Tables (Add user_id)

All existing tables get `user_id`:
- `trade_journal` → includes `user_id`
- `trade_log` → includes `user_id`
- `trade_snapshots` → includes `user_id`
- `pnl_snapshots` → includes `user_id`
- `paper_trades` → includes `user_id`
- `stock_theses` → includes `user_id`
- `watchlist_notes` → includes `user_id`
- `news_articles` → shared (no user_id)
- `global_news` → shared (no user_id)
- `candles` → shared (no user_id)
- `intraday_candles` → shared (no user_id)
- etc.

---

## 🔐 Security Implementation

### API Key Encryption
```python
from cryptography.fernet import Fernet

# Keys stored encrypted in database
encrypted_key = cipher.encrypt(groww_api_key.encode())

# Keys decrypted only when needed
decrypted_key = cipher.decrypt(encrypted_key).decode()
```

### JWT Authentication
```python
# Every request includes JWT token
Authorization: Bearer <jwt_token>

# Token payload includes user_id
{
    "user_id": "uuid",
    "email": "user@example.com",
    "exp": 1234567890
}
```

### Google OAuth Flow
```
1. User clicks "Login with Google"
   ↓
2. Redirects to Google OAuth consent screen
   ↓
3. User approves → Google redirects to /auth/google/callback
   ↓
4. Backend exchanges auth code for ID token
   ↓
5. Creates/updates user in database
   ↓
6. Issues JWT token
   ↓
7. Frontend stores JWT in localStorage
```

---

## 🚀 Deployment Architecture

### Railway (Backend + Database)
- Flask API server
- PostgreSQL database
- Scheduled jobs (every 5s P&L update, etc.)

### Vercel (Frontend)
- React/Next.js app
- Auto-deploy from GitHub
- Serverless functions (optional)

### Environment Variables

**Railway Backend:**
```env
DATABASE_URL=postgresql://...
FLASK_SECRET_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GROWW_API_URL=https://api.groww.in
ENCRYPTION_KEY=...
JWT_SECRET=...
```

**Vercel Frontend:**
```env
REACT_APP_API_URL=https://backend.railway.app
REACT_APP_GOOGLE_CLIENT_ID=...
```

---

## 📊 Data Migration Plan

### Phase 1: Preparation
- [ ] Create new user tables
- [ ] Add user_id columns to existing tables
- [ ] Create encryption keys

### Phase 2: Migration
- [ ] Create admin user account
- [ ] Migrate existing 56 trades → admin user
- [ ] Verify data integrity
- [ ] Create backups

### Phase 3: Deployment
- [ ] Deploy updated backend
- [ ] Deploy new frontend
- [ ] Enable Google OAuth
- [ ] Test entire flow

---

## 🔄 API Endpoint Structure

### Authentication
```
POST /api/auth/google
POST /api/auth/logout
GET  /api/auth/verify
```

### User Management
```
GET  /api/users/profile
PUT  /api/users/profile
POST /api/users/api-credentials
GET  /api/users/settings
PUT  /api/users/settings
```

### Trading (All require user_id)
```
GET  /api/trades/journal
POST /api/trades/execute
GET  /api/trades/{id}
PUT  /api/trades/{id}/close

GET  /api/paper-trading/status
POST /api/paper-trading/execute
GET  /api/backtesting/results
```

### Admin Only
```
GET  /api/admin/users
GET  /api/admin/users/{id}/trades
GET  /api/admin/system-health
GET  /api/admin/logs
```

---

## 🎨 Frontend Pages

```
pages/
├── LandingPage.jsx         # Marketing page
├── LoginPage.jsx           # Google OAuth flow
├── DashboardPage.jsx       # Main dashboard
├── TradingPage.jsx         # Execute trades
├── BacktestingPage.jsx     # Run backtests
├── SettingsPage.jsx        # API key, preferences
├── AnalyticsPage.jsx       # P&L charts, stats
├── AdminPage.jsx           # User management
└── NotFoundPage.jsx

components/
├── Navbar.jsx
├── TradeCard.jsx
├── SignalChart.jsx
├── WinrateStats.jsx
├── PnLChart.jsx
├── UsersList.jsx
└── ...
```

---

## 📈 Implementation Timeline

**Week 1:** Backend infrastructure
- Database schema ✓
- User auth system ✓
- API key encryption ✓
- Migration scripts ✓

**Week 2:** Frontend basics
- React scaffolding ✓
- Google OAuth UI ✓
- Dashboard layout ✓
- API integration ✓

**Week 3:** Full features
- Trading interface ✓
- Backtesting ✓
- Admin dashboard ✓
- Analytics pages ✓

**Week 4:** Deployment
- Railway setup ✓
- Vercel setup ✓
- Testing ✓
- Launch ✓

---

## ✅ Quality Checklist

### Security
- [ ] API keys encrypted in DB
- [ ] JWT tokens validated on every request
- [ ] User can only see their own data
- [ ] Admin has full visibility (with audit logs)
- [ ] HTTPS enforced

### Functionality
- [ ] Google OAuth login working
- [ ] Users can add Groww API credentials
- [ ] Paper trading per-user
- [ ] Real trading per-user (if enabled)
- [ ] Backtesting per-user
- [ ] Admin dashboard complete

### Performance
- [ ] API response <100ms
- [ ] Database queries optimized (user_id indexes)
- [ ] Frontend loads <3 seconds
- [ ] Real-time P&L updates (WebSocket or polling)

### Testing
- [ ] Unit tests for auth
- [ ] Integration tests for API
- [ ] E2E tests for main flows
- [ ] Load testing (100+ concurrent users)

---

## 🆘 Support & Monitoring

### Health Checks
```
GET /api/health → returns system status
GET /api/admin/database → returns DB metrics
GET /api/admin/jobs → returns scheduler status
```

### Error Handling
- User-friendly error messages
- Detailed server logs
- Error tracking (Sentry integration)
- Admin notifications for critical errors

### User Support
- In-app documentation
- API key validation helper
- Test mode before real trading
- Email support channel

---

## Next Steps

1. **Backend Setup** → Start with database schema migration
2. **Authentication** → Implement Google OAuth
3. **Frontend Setup** → Create React scaffolding
4. **Integration** → Connect frontend to backend
5. **Deployment** → Launch on Railway + Vercel
