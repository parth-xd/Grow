# Testing Google Sign-In Flow

## Quick Test (2 minutes)

1. **Go to the app:**
   ```
   https://grow-ten.vercel.app/login
   ```

2. **Open Developer Tools:**
   - Press `F12` on Windows/Linux or `Cmd + Option + I` on Mac
   - Go to **Console** tab
   - Clear any existing logs (Cmd+K or Ctrl+K)

3. **Click "Sign in with Google" button**

4. **Watch the console for these messages (in order):**

   ```
   === Google Sign-In Initialization ===
   Client ID present: true
   Initializing Google Sign-In...
   ✓ Google Sign-In initialized successfully
   
   (When you click button:)
   Prompt notification: {isNotDisplayed: false/true, isSkippedMoment: false/true, ...}
   
   (After signing in with Google:)
   🔐 Sending credential to backend...
   API URL: https://groww-api-m853.onrender.com
   Token length: 1234
   Auth URL: https://groww-api-m853.onrender.com/api/auth/google
   
   (After backend responds:)
   Backend response status: 200
   ✓ Authentication successful
   User: {id: "...", email: "user@example.com", name: "Your Name"}
   ```

---

## ✅ Success Indicators

### Frontend Console
- [ ] No red errors in console
- [ ] "✓ Authentication successful" message
- [ ] User object logged with id, email, name

### Browser
- [ ] Redirected to dashboard/home page (not stuck on login page)
- [ ] Logged in status shown somewhere (if your app displays it)

### Backend Logs (if running locally)
```bash
# In terminal running backend:
🔐 Attempting Google sign-in
✓ Google ID token decoded for: user@example.com
Creating/fetching user with Google ID: 1096961051894815233456
✓ User obtained: {id: '...', email: 'user@example.com', ...}
✓ User authenticated: user@example.com
```

### Supabase Database
1. Go to https://supabase.com
2. Select your project
3. Go to **SQL Editor** or **Table Editor**
4. Check `users` table
5. Should see new user with:
   - `google_id`: Your Google account ID
   - `email`: Your email
   - `name`: Your name
   - `is_active`: true

---

## ❌ Troubleshooting

### Error: "Configuration error: Google Client ID not set"
- Frontend can't find Client ID
- Check: Is `VITE_GOOGLE_CLIENT_ID` set in `.env`?
- Solution:
  ```bash
  echo "VITE_GOOGLE_CLIENT_ID=713595862820-jhjvl7vhg0nb7p3j31kn3bvq60u7dv2l.apps.googleusercontent.com" >> frontend/.env
  ```

### Error: "Network error: Cannot reach backend server"
- Frontend can't connect to backend
- Check: Is `VITE_API_URL` set correctly?
- Check: Is backend running on Render? → https://groww-api-m853.onrender.com/api/health
- Solution: If backend is down, it takes ~2 min to spin up on Render's free tier

### Error: "Backend service unavailable (503)"
- Backend can't connect to database
- Check: Is Supabase connection working?
- Check: Are environment variables set on Render?
  - `DATABASE_URL` 
  - `GOOGLE_CLIENT_ID`
  - `JWT_SECRET`

### No error but stuck on login page after signing in
- Backend returned 200 but something failed
- Check frontend console for any errors
- Check `onSuccess` callback - is it being called?
- Check localStorage - is token being saved?

### "FedCM get() rejects with NetworkError"
- This is a new Google deprecation warning
- It's NOT a blocking error - sign-in should still work
- We've added better fallback handling - just try signing in

### "Provided button width is invalid: 100%"
- This was a Google SDK warning
- **Fixed** by removing width parameter from renderButton
- If you still see it, hard refresh: `Cmd+Shift+R` (Mac) or `Ctrl+Shift+R` (Windows)

---

## 🔍 Manual API Test

If sign-in isn't working, test the backend directly:

### 1. Get a Google ID Token

First, manually sign in to get a token:
```bash
# Go to this URL in browser (replace CLIENT_ID)
https://accounts.google.com/o/oauth2/v2/auth?client_id=713595862820-jhjvl7vhg0nb7p3j31kn3bvq60u7dv2l.apps.googleusercontent.com&redirect_uri=http://localhost:3000&response_type=id_token&scope=openid%20email%20profile
```

Or use the frontend to get one and copy from localStorage:
```javascript
// In browser console:
localStorage.getItem('authToken')
// Or just click the button and watch the Network tab for the request body
```

### 2. Test Backend Endpoint

```bash
curl -X POST https://groww-api-m853.onrender.com/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{
    "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjEifQ..."
  }'

# Expected response (200):
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "Your Name"
  }
}

# If error (4xx/5xx):
{
  "error": "Invalid token",
  "detail": "..."
}
```

### 3. Test Backend Database Connection

```bash
curl https://groww-api-m853.onrender.com/api/health

# Expected:
{
  "status": "healthy",
  "db_connected": true,
  "server_time": "2026-04-17T04:15:30.123456"
}
```

---

## 📋 Checklist Before Reporting Issues

Before saying "sign-in doesn't work," verify:

- [ ] Frontend is deployed (check `https://grow-ten.vercel.app`)
- [ ] Backend is running (check `https://groww-api-m853.onrender.com/api/health`)
- [ ] Environment variables set:
  - [ ] `VITE_GOOGLE_CLIENT_ID` in frontend .env
  - [ ] `VITE_API_URL` in frontend .env (should be https://groww-api-m853.onrender.com)
  - [ ] `DATABASE_URL` on Render backend
  - [ ] `GOOGLE_CLIENT_ID` on Render backend
  - [ ] `JWT_SECRET` on Render backend
- [ ] Browser console is checked for actual errors (not just warnings)
- [ ] Hard refresh done: Cmd+Shift+R (Mac) or Ctrl+Shift+R (Windows)
- [ ] Private/Incognito window tested (to rule out cache issues)

---

## 🐛 Debug Mode

To see MORE detailed logs, add this to GoogleLoginButton.jsx:

```javascript
// In handleCredentialResponse, after trying the API call:
console.log('📊 Full response:', {
  status: result.status,
  statusText: result.statusText,
  headers: Object.fromEntries(result.headers.entries()),
  body: data
});
```

---

## 🎯 Expected User Journey

1. Arrive at `/login` page
2. See "Sign in with Google" button
3. Click button → Google popup appears
4. Sign in with Google account
5. Popup closes
6. Redirected to dashboard
7. Dashboard shows logged-in state (user's name, email, etc.)

---

## 📞 Getting Help

When reporting issues, include:

1. **Screenshot** of the error (or console error text)
2. **Browser**: Chrome, Firefox, Safari, etc.
3. **Console output**: Copy from F12 DevTools Console
4. **Network tab response**: The /api/auth/google response (Status + Body)
5. **Steps to reproduce**: Exactly what you did
6. **What you expected**: What should have happened
7. **What actually happened**: What did happen instead

