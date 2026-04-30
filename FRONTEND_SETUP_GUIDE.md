# 🚀 Complete Setup Instructions - Next.js Frontend with Google OAuth

## Overview

Your project now has:
```
/Grow
├── frontend/                 # NEW - Next.js React frontend
│   ├── app/
│   │   ├── login/           # Google OAuth login page
│   │   ├── setup/           # API credentials setup page
│   │   ├── api/auth/        # NextAuth endpoints
│   │   ├── layout.tsx       # Root layout
│   │   └── globals.css
│   ├── components/ui/
│   │   └── container-scroll-animation.tsx  # Animated component
│   ├── lib/auth.ts          # OAuth config
│   ├── package.json
│   ├── tailwind.config.ts
│   └── README.md
├── app.py                   # Your existing Flask backend (unchanged)
├── setup.html               # OLD - Will be replaced by Next.js /setup page
├── login.html               # OLD - Will be replaced by Next.js /login page
└── index.html               # OLD - Existing dashboard (unchanged)
```

---

## Step-by-Step Setup

### Step 1: Install Node Dependencies

```bash
cd /Users/parthsharma/Desktop/Grow/frontend
npm install
```

This will install:
- ✅ Next.js 14
- ✅ React 18
- ✅ TypeScript
- ✅ Tailwind CSS
- ✅ Framer Motion (for scroll animations)
- ✅ NextAuth.js (for Google OAuth)

### Step 2: Create Google OAuth Credentials

#### 2.1 Go to Google Cloud Console
1. Visit: https://console.cloud.google.com/
2. **Create a new project** named "Groww"
3. Click on the project name to open it

#### 2.2 Enable Google+ API
1. Go to **APIs & Services** → **Library**
2. Search for "Google+ API"
3. Click it and press **ENABLE**

#### 2.3 Create OAuth 2.0 Credentials
1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. You'll be prompted to configure the OAuth consent screen first:
   - User Type: **External**
   - App name: **Groww**
   - User support email: Your email
   - Developer contact: Your email
   - Click **Save and Continue** through all steps

4. Back to credentials, create **OAuth client ID**:
   - Application type: **Web application**
   - Name: **Groww Next.js Frontend**

5. Add **Authorized JavaScript origins:**
   - `http://localhost:8000` (development)
   - `http://127.0.0.1:8000` (local)

6. Add **Authorized redirect URIs:**
   - `http://localhost:8000/api/auth/callback/google`
   - `http://127.0.0.1:8000/api/auth/callback/google`

7. **Copy your credentials:**
   - Client ID (looks like: `xxx.apps.googleusercontent.com`)
   - Client Secret (looks like: random string)

### Step 3: Configure Environment Variables

```bash
cd /Users/parthsharma/Desktop/Grow/frontend

# Copy the example file
cp .env.local.example .env.local

# Edit the file
nano .env.local  # or use VS Code to open it
```

Add your credentials:
```env
GOOGLE_CLIENT_ID=your_client_id_here.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret_here
NEXTAUTH_SECRET=any_random_string_here_can_be_anything
NEXTAUTH_URL=http://localhost:8000
```

**Example:**
```env
GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-abcdefghijk
NEXTAUTH_SECRET=mysecuretoken12345
NEXTAUTH_URL=http://localhost:8000
```

### Step 4: Run the Development Server

```bash
cd /Users/parthsharma/Desktop/Grow/frontend
npm run dev -- -p 8000
```

You should see:
```
▲ Next.js 14.0.0
  - Local:        http://localhost:8000
  - Environments: .env.local
```

### Step 5: Test the Flow

1. **Open browser:** http://localhost:8000/login
2. **Click:** "Continue with Google"
3. **Sign in** with your Google account
4. **You'll be redirected to:** http://localhost:8000/setup
5. **Enter dummy API credentials** and submit
6. You'll be redirected to your dashboard

---

## Running Together

```bash
# Terminal 1 - Run Flask backend on port 5000
cd /Users/parthsharma/Desktop/Grow
python app.py  # Make sure it's on port 5000

# Terminal 2 - Run Next.js frontend on port 8000
cd /Users/parthsharma/Desktop/Grow/frontend
npm run dev -- -p 8000
```

## Integration with Your Flask Backend

### Option 1: Local Testing (No Backend Integration)
If you just want to test the UI, the setup page will work without a backend.

### Option 2: Full Integration (Recommended)

Your Flask app needs to handle the `/api/setup` endpoint.

#### 2.1 Update your Flask app

Add this to your `app.py`:

```python
from flask import request, jsonify
from flask_cors import CORS
import json
import os
from datetime import datetime

# Enable CORS
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:8000"],
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

@app.route('/api/setup', methods=['POST'])
def setup_api():
    """Receive and store Groww API credentials"""
    try:
        data = request.json
        api_key = data.get('apiKey')
        api_secret = data.get('apiSecret')
        user_email = data.get('userEmail')
        
        if not all([api_key, api_secret, user_email]):
            return jsonify({"error": "Missing credentials"}), 400
        
        # Store in database or file
        user_data = {
            "email": user_email,
            "api_key": api_key,
            "api_secret": api_secret,
            "created_at": datetime.now().isoformat()
        }
        
        # Save to JSON file
        os.makedirs("user_data", exist_ok=True)
        with open(f"user_data/{user_email}.json", 'w') as f:
            json.dump(user_data, f)
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

#### 2.2 Install flask-cors

```bash
pip install flask-cors
```

#### 2.3 Run on Different Ports

```bash
# Terminal 1 - Run Flask on port 5000
cd /Users/parthsharma/Desktop/Grow
python app.py  # Make sure it runs on port 5000

# Terminal 2 - Run Next.js on port 8000
cd /Users/parthsharma/Desktop/Grow/frontend
npm run dev -- -p 8000
```

---

## Directory Structure Explanation

### `/frontend/app/` - Next.js App Router
- **`layout.tsx`** - Root layout with SessionProvider
- **`login/page.tsx`** - Login page with Google OAuth button
- **`setup/page.tsx`** - Setup page for API credentials
- **`api/auth/[...nextauth]/route.ts`** - OAuth endpoint

### `/frontend/components/ui/`
- **`container-scroll-animation.tsx`** - The animated component used on both login and setup pages

### Key Features on Each Page

**Login Page** (`/login`):
- ✅ ContainerScroll animation
- ✅ Google OAuth button
- ✅ Beautiful gradient background
- ✅ Auto-redirects to setup after login

**Setup Page** (`/setup`):
- ✅ ContainerScroll animation
- ✅ API key input fields
- ✅ Form submission to backend
- ✅ Sign out button
- ✅ Shows logged-in user name/email

---

## Troubleshooting

### "Module not found: next-auth"
```bash
cd frontend
npm install next-auth
```

### "GOOGLE_CLIENT_ID is undefined"
- Check `.env.local` file exists
- Verify you copied the correct Client ID
- Restart dev server after creating `.env.local`

### "Callback URL mismatch" error
- Go back to Google Cloud Console
- Check Authorized redirect URIs includes:
  - `http://localhost:3000/api/auth/callback/google`

### "Cannot GET /login"
- Make sure you're accessing: `http://localhost:3000/login`
- Not `http://localhost:5000/login`
- Next.js runs on port 3000 by default

### Frontend connects but API fails
- Check Flask is running: `python app.py`
- Verify Flask CORS is enabled
- Check Flask is on port 5000
- Next.js on port 3000

---

## Production Deployment

When you're ready to deploy:

1. **Update Google OAuth credentials** with production URLs
2. **Update `.env.local`** with production URLs
3. **Set `NEXTAUTH_URL`** to your production domain
4. **Deploy to Vercel, Netlify, or your server**

### Local Deployment on Port 8000
```bash
npm run build
npm start -- -p 8000
```

### Vercel Deployment (Recommended for Next.js)
```bash
npm install -g vercel
vercel login
vercel
```

Follow the prompts and set environment variables in Vercel dashboard.

---

## File Summary

| File | Purpose |
|------|---------|
| `package.json` | Dependencies and scripts |
| `tsconfig.json` | TypeScript configuration |
| `tailwind.config.ts` | Tailwind CSS configuration |
| `next.config.js` | Next.js configuration |
| `app/layout.tsx` | Root layout with session |
| `app/login/page.tsx` | Login page with OAuth |
| `app/setup/page.tsx` | Setup page with form |
| `components/ui/container-scroll-animation.tsx` | Scroll animation component |
| `lib/auth.ts` | NextAuth config |
| `app/api/auth/[...nextauth]/route.ts` | OAuth API endpoint |

---

## Next Steps

1. ✅ **Install dependencies:** `npm install`
2. ✅ **Create Google OAuth credentials**
3. ✅ **Create `.env.local` file with credentials**
4. ✅ **Run `npm run dev`**
5. ✅ **Test at `http://localhost:3000/login`**
6. ✅ **(Optional) Integrate with Flask backend**

---

## Questions?

- **Next.js Docs:** https://nextjs.org/docs
- **NextAuth.js Docs:** https://next-auth.js.org/
- **Tailwind CSS:** https://tailwindcss.com/docs
- **Framer Motion:** https://www.framer.com/motion/

Good luck! 🎉
