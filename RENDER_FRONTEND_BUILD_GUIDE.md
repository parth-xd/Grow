# Render Deployment - Complete Setup Guide

## The Problem You're Experiencing

The "Loading..." screen means the **frontend app isn't being built on Render**. The Flask backend serves the React frontend from `frontend/dist/index.html`, but if the frontend hasn't been built, it's missing.

## Quick Fix for Existing Deployment

### Option 1: Update Build Command in Render Dashboard

1. Go to https://dashboard.render.com/
2. Select your **Web Service**
3. Go to **Settings** → **Build & Deploy**
4. Update the **Build Command** to:
   ```
   pip install -r requirements.txt && cd frontend && npm install --omit=dev && npm run build && cd ..
   ```
5. Click **Save Changes**
6. Render will automatically redeploy

### Option 2: Use the Build Script

1. Make the script executable:
   ```bash
   chmod +x build.sh
   ```
2. In Render Dashboard, set Build Command to:
   ```
   ./build.sh
   ```

## Detailed Setup for New Deployments

### Step 1: Create Render Service

1. Connect your GitHub repo to Render
2. Create a new **Web Service**
3. Select the repository and branch

### Step 2: Configure Build Settings

**Build Command:**
```
pip install -r requirements.txt && cd frontend && npm install --omit=dev && npm run build && cd ..
```

**Start Command:**
```
python app.py
```

### Step 3: Add Environment Variables

In Render Dashboard, add these variables:

```
DATABASE_URL=<your-postgres-url>
FLASK_HOST=0.0.0.0
FLASK_PORT=10000
JWT_SECRET=<your-secret>
ENCRYPTION_KEY=<your-key>
GOOGLE_CLIENT_ID=<your-id>
GOOGLE_CLIENT_SECRET=<your-secret>
GOOGLE_REDIRECT_URI=https://<your-render-url>/api/auth/google/callback
GROWW_API_KEY=<your-key-if-available>
GROWW_API_SECRET=<your-secret-if-available>
```

### Step 4: Set Up PostgreSQL

1. Create a PostgreSQL database on Render
2. Get the `DATABASE_URL` 
3. Add it to your web service's environment variables

## How It Works

```
Render Deploy Process:
1. Clone repository
2. Run Build Command:
   - Install Python dependencies (pip install)
   - Install Node dependencies (npm install)
   - Build frontend (npm run build)
   - Creates frontend/dist/ folder
3. Run Start Command:
   - python app.py
   - Flask serves frontend/dist/index.html
   - Frontend makes API calls to /api/* endpoints
```

## Troubleshooting

### Still Seeing "Loading..." Screen?

1. **Check Render Logs:**
   - Go to Render Dashboard
   - Select your service
   - Click **Logs**
   - Look for errors during build

2. **Verify Frontend Built:**
   - Check logs for: `Building frontend...`
   - Check logs for: `✅ Frontend built successfully` OR `✅ Build completed`

3. **Check Frontend dist Folder:**
   - The `frontend/dist/` folder must exist after build
   - It should contain `index.html` and an `assets/` folder

### Build Fails with Node Errors?

Make sure `package.json` has all dependencies. If missing packages error out, the build will fail.

### API Calls Failing?

Check browser DevTools (F12 → Network tab) to see if API calls are reaching the backend.

## File Structure After Build

```
Grow/
├── app.py              (Flask server)
├── frontend/
│   ├── src/           (React source code)
│   ├── dist/          (Built frontend - created during build)
│   │   ├── index.html
│   │   └── assets/
│   └── package.json
└── requirements.txt   (Python dependencies)
```

## Key URLs

- **Frontend:** `https://<your-service>.onrender.com/`
- **API:** `https://<your-service>.onrender.com/api/*`
- **Auth:** `https://<your-service>.onrender.com/api/auth/*`

## Next Steps After Fix

1. Clear browser cache (Ctrl+Shift+Delete)
2. Try accessing the app again
3. Check browser DevTools for any errors

If the loading screen persists, check the Render logs for the actual error message.
