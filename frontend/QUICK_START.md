# 🎯 QUICK REFERENCE CARD

## 30-Second Overview

You now have a **Next.js + React + TypeScript** frontend running on **port 8000** with:
- 🔐 Google OAuth login
- 📱 Responsive UI with Tailwind CSS
- ✨ Scroll animations with Framer Motion
- ⚙️ Setup page for API credentials

## Files to Know

| File | Purpose |
|------|---------|
| `frontend/app/login/page.tsx` | 🔐 Google login page |
| `frontend/app/setup/page.tsx` | ⚙️ API setup page |
| `frontend/components/ui/container-scroll-animation.tsx` | ✨ Scroll animation |
| `frontend/.env.local` | 🔑 Your API keys (create this!) |
| `frontend/package.json` | 📦 Dependencies |

## Commands to Remember

```bash
# Navigate to frontend
cd /Users/parthsharma/Desktop/Grow/frontend

# Install dependencies (run once)
npm install

# Start development server on port 8000
npm run dev -- -p 8000

# Build for production
npm run build

# Run production build on port 8000
npm start -- -p 8000
```

## Ports

- **Next.js Frontend:** http://localhost:8000
- **Flask Backend:** http://localhost:5000 (your existing app)
- **Login page:** http://localhost:8000/login
- **Setup page:** http://localhost:8000/setup

## Google OAuth Setup (5 minutes)

1. Go to: https://console.cloud.google.com/
2. Create new project → "Groww"
3. APIs & Services → Enable Google+ API
4. Credentials → Create OAuth 2.0 credentials
5. Authorized URIs:
   - JS Origins: `http://localhost:8000`
   - Redirects: `http://localhost:8000/api/auth/callback/google`
6. Copy Client ID & Secret
7. Create `.env.local`:
   ```
   GOOGLE_CLIENT_ID=your_client_id
   GOOGLE_CLIENT_SECRET=your_secret
   NEXTAUTH_SECRET=any_random_string
   NEXTAUTH_URL=http://localhost:8000
   ```

## User Flow

```
User visits http://localhost:8000/login
    ↓
Clicks "Continue with Google"
    ↓
Signs in with Google account
    ↓
Redirected to http://localhost:8000/setup
    ↓
Enters Groww API Key & Secret
    ↓
Form posts to backend `/api/setup`
    ↓
Backend stores credentials
    ↓
Redirected to /index.html (your dashboard)
```

## What's New vs Old

| Part | Before | Now |
|------|--------|-----|
| Login Page | `login.html` | `frontend/app/login/page.tsx` |
| Setup Page | `setup.html` | `frontend/app/setup/page.tsx` |
| Dashboard | `index.html` | `index.html` (unchanged) |
| Framework | Plain HTML/JS | Next.js + React + TypeScript |
| Styling | Inline CSS | Tailwind CSS |
| Auth | Custom | Google OAuth + NextAuth.js |

## Key Features

✅ **Two-page flow:**
- Login → enter Google email/password
- Setup → enter Groww API credentials

✅ **Animations:**
- ContainerScroll component on both pages
- Smooth rotation & fade effects as users scroll

✅ **Security:**
- Google OAuth (never handle passwords)
- NextAuth.js session management
- API keys sent only to your backend

✅ **Responsive:**
- Works on mobile & desktop
- Tailwind CSS breakpoints

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| "npm: command not found" | Install Node.js from nodejs.org |
| Module errors | Run `npm install` |
| OAuth callback error | Check Google Cloud credentials |
| .env.local not working | Restart dev server after creating file |
| Port 8000 already in use | `lsof -i :8000` then kill process |

## File Locations

```
/Users/parthsharma/Desktop/Grow/
├── frontend/                          # NEW - Your React app
│   ├── app/login/page.tsx            # Login page
│   ├── app/setup/page.tsx            # Setup page
│   ├── components/ui/container-scroll-animation.tsx
│   ├── .env.local                    # CREATE THIS
│   └── package.json
├── index.html                         # Keep as-is
├── setup.html                         # OLD (can delete)
├── login.html                         # OLD (can delete)
├── app.py                             # Your Flask backend
└── FRONTEND_SETUP_GUIDE.md           # Detailed guide
```

## Next Steps

1. ✅ Read `FRONTEND_SETUP_GUIDE.md` (detailed instructions)
2. ✅ Run `npm install` in `frontend/` folder
3. ✅ Create Google OAuth credentials
4. ✅ Create `.env.local` file with credentials
5. ✅ Run `npm run dev`
6. ✅ Test at `http://localhost:3000/login`
7. ✅ (Optional) Add `/api/setup` endpoint to Flask

## Need Help?

- Detailed guide: `FRONTEND_SETUP_GUIDE.md`
- Flask integration: `frontend/PYTHON_BACKEND_INTEGRATION.md`
- General info: `frontend/README.md`
- Next.js docs: https://nextjs.org/docs
- NextAuth docs: https://next-auth.js.org/

---

**You're ready to go!** 🚀

Start with: `cd frontend && npm install && npm run dev`
