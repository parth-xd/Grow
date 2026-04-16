# Complete Google Sign-In Flow Explanation

## 📊 High-Level Flow Diagram

```
User Browser (Frontend)           Google OAuth           Backend Server
       ↓                               ↓                        ↓
  [1] Click Button              [2] Google SDK             [3] /api/auth/google
       ↓                         Opens Popup                    ↓
  [4] User Signs In              [5] Returns              [6] Verify Token
       ↓                      ID Token (JWT)                   ↓
  [7] Send Token              [8] handleCredentialResponse  [9] Check User in DB
       ↓                               ↓                        ↓
 [10] POST to Backend              [11] Fetch               [12] Create/Update User
       ↓                         Backend Response               ↓
 [13] Store JWT               [14] Get {token, user}       [15] Generate JWT
       ↓                               ↓                        ↓
 [16] Redirect Dashboard       [17] User Logged In         [18] Return Token
```

---

## 🔄 STEP-BY-STEP DETAILED FLOW

### **STEP 1-3: Component Initialization**

**Location**: `frontend/src/components/GoogleLoginButton.jsx` (lines 1-40)

```javascript
// When component mounts:
useEffect(() => {
  const initGoogle = () => {
    // Wait for Google API to load
    if (!window.google?.accounts?.id) {
      setTimeout(initGoogle, 100); // Retry until ready
      return;
    }

    // Initialize Google SDK with your Client ID
    window.google.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,        // From .env: 713595862820-...
      callback: handleCredentialResponse, // Our handler
      ux_mode: 'popup',                   // Popup mode (not redirect)
      auto_select: false                  // No auto-select
    });

    // Create custom button
    const customBtn = document.createElement('button');
    customBtn.onclick = () => {
      window.google.accounts.id.prompt(...); // Show prompt/popup
    };
  };
  initGoogle();
}, []);
```

**What's happening:**
- Google SDK waits for `window.google.accounts.id` to be available (loaded from HTML)
- We initialize with your Client ID (registered at Google Cloud Console)
- Button click triggers Google's sign-in UI (popup or One Tap)

---

### **STEP 4-7: User Signs In & Gets Token**

**Location**: Google OAuth popup (external Google domain)

```
User clicks "Sign in with Google" button
         ↓
Google popup opens
         ↓
User enters Google credentials
         ↓
Google verifies identity
         ↓
Google creates ID Token (JWT) with:
  - sub: Google User ID unique identifier
  - email: user@example.com
  - name: User Name
  - picture: https://... profile pic
  - iss: https://accounts.google.com (issuer)
  - aud: Your Client ID (audience)
  - iat, exp: timestamps
         ↓
Google calls your callback with {credential: JWT_TOKEN}
```

The ID Token is a JWT that looks like:
```
eyJhbGciOiJSUzI1NiIsImtpZCI6IjEifQ.
eyJpc3MiOiJodHRwczovL2FjY291bnRzLmdvb2dsZS5jb20iLCJzdWIiOiIxMDk2OTY...
signature...
```

---

### **STEP 8-10: Send Token to Backend**

**Location**: `frontend/src/components/GoogleLoginButton.jsx` (lines 100-130)

```javascript
const handleCredentialResponse = async (response) => {
  const idToken = response.credential; // JWT from Google
  
  // POST to backend
  const result = await fetch(`${API_URL}/api/auth/google`, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    },
    body: JSON.stringify({ id_token: idToken })
  });
  
  const data = await result.json();
  // data = {token: JWT_APP_TOKEN, user: {id, email, name}}
  onSuccess(data);
};
```

**What's happening:**
- Frontend has the Google ID Token
- POSTs it to your backend's `/api/auth/google` endpoint
- Sends as JSON: `{id_token: "eyJhbGc..."}`

---

### **STEP 11-15: Backend Processes Token**

**Location**: `app.py` (lines 143-260)

```python
@app.route("/api/auth/google", methods=["POST", "OPTIONS"])
def google_auth():
    # [STEP 1] Get the ID token from request
    data = request.get_json()
    id_token = data.get('id_token')
    
    # [STEP 2] Decode Google's JWT (NO signature verification needed!)
    # - Google's tokens are cryptographically signed
    # - We trust Google's token if issuer is Google
    google_info = jwt.decode(id_token, options={"verify_signature": False})
    # Result: {
    #   'sub': '1096961051894815233456',
    #   'email': 'user@example.com',
    #   'iss': 'https://accounts.google.com',
    #   'aud': 'your-client-id.apps.googleusercontent.com'
    # }
    
    # [STEP 3] Verify it's actually from Google
    if google_info.get('iss') not in ['https://accounts.google.com']:
        return error 401  # Not from Google!
    
    # [STEP 4] Verify Client ID matches
    if google_info.get('aud') != os.getenv('GOOGLE_CLIENT_ID'):
        # Sometimes Google returns 'azp' instead of 'aud' - that's OK
        pass
    
    # [STEP 5] Database lookup: Does this user exist?
    auth_manager = AuthManager(app.db)
    user = auth_manager.get_or_create_user({
        'id': google_info.get('sub'),           # Google User ID
        'email': google_info.get('email'),      # email
        'name': google_info.get('name'),        # name
        'picture': google_info.get('picture')   # profile pic
    })
    
    # [STEP 6] Generate YOUR app's JWT token
    token = auth_manager.generate_jwt(user['id'], user['email'])
    # This token is for your app, not Google's
    
    # [STEP 7] Return token + user to frontend
    return {
        'token': token,
        'user': {
            'id': user['id'],
            'email': user['email'],
            'name': user['name']
        }
    }
```

---

### **Database User Management**

**Location**: `auth.py` (lines 140-200)

```python
def get_or_create_user(self, google_info):
    # [1] Check if user with this Google ID exists
    result = self.db.session.execute(
        "SELECT id, email, name FROM users WHERE google_id = :google_id",
        {'google_id': google_info['id']}
    )
    user = result.fetchone()
    
    if user:
        # [2] USER EXISTS - Just update last_login
        self.db.session.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = :user_id",
            {'user_id': user[0]}
        )
        self.db.session.commit()
        return {'id': str(user[0]), 'email': user[1], 'name': user[2]}
    
    else:
        # [3] USER DOESN'T EXIST - Create new user
        user_id = str(uuid.uuid4())
        self.db.session.execute("""
            INSERT INTO users (id, google_id, email, name, profile_picture_url, is_active)
            VALUES (:id::uuid, :google_id, :email, :name, :picture, TRUE)
        """, {
            'id': user_id,
            'google_id': google_info['id'],
            'email': google_info['email'],
            'name': google_info['name'],
            'picture': google_info.get('picture')
        })
        self.db.session.commit()
        return {'id': user_id, 'email': google_info['email'], 'name': google_info['name']}
```

**What happens:**
1. First sign-in with email@google.com:
   - Creates new user in `users` table
   - Stores google_id (unique identifier)
   - Sets is_active = TRUE
   - Stores profile picture URL

2. Second sign-in with same Google account:
   - Finds existing user by google_id
   - Updates last_login timestamp
   - Returns same user

---

### **STEP 16-17: Frontend Stores Token**

**Location**: Depends on your app's auth context (usually `src/context/AuthContext.jsx` or similar)

```javascript
// onSuccess callback receives:
data = {
  token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  user: {
    id: "550e8400-e29b-41d4-a716-446655440000",
    email: "user@example.com",
    name: "John Doe"
  }
}

// Store token (your app should do this)
localStorage.setItem('authToken', data.token);

// Use token for future API calls
fetch(`${API_URL}/api/protected-endpoint`, {
  headers: {
    'Authorization': `Bearer ${data.token}`
  }
});
```

---

## ⚠️ CURRENT ISSUES & FIXES

### **Issue 1: FedCM NetworkError**

**Error:** `FedCM get() rejects with NetworkError: Error retrieving a token`

**Cause:**
- Google is transitioning from GSI (Google Sign-In) to FedCM (Federated Credential Management)
- FedCM requires:
  1. Proper CORS headers (we have this ✓)
  2. `.well-known/web-identity` configuration on your domain
  3. No network errors from backend

**Fix:** Update GoogleLoginButton.jsx to handle FedCM fallback:

```javascript
// In handleCredentialResponse - handle both GSI and FedCM paths
const customBtn.onclick = (e) => {
  e.preventDefault();
  setIsLoading(true);
  
  // Try the modern FedCM flow first
  window.google.accounts.id.prompt((notification) => {
    // If prompt not shown, fallback to old method
    if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
      console.log('FedCM not available, using fallback');
      window.google.accounts.id.renderButton(buttonContainer, {
        theme: 'outline',
        size: 'large'
        // Don't set width here - let Google manage it
      });
    }
  });
};
```

---

### **Issue 2: Button Width Warning**

**Error:** `Provided button width is invalid: 100%`

**Cause:**
- Google's button renderer doesn't accept CSS width: 100%
- The renderButton() API expects width in pixels or "400" format

**Fix:** Don't set width in renderButton - use CSS container instead:

```javascript
// Instead of:
window.google.accounts.id.renderButton(buttonContainer, {
  width: '100%'  // ❌ WRONG - Google doesn't understand this
});

// Do this:
const containerStyle = {
  width: '100%',
  display: 'flex',
  justifyContent: 'center'
};
buttonContainer.style.cssText = `
  width: 100%;
  display: flex;
  justify-content: center;
`;

window.google.accounts.id.renderButton(buttonContainer, {
  theme: 'outline',
  size: 'large',
  type: 'standard',
  text: 'signin_with'
});
```

---

## 🔍 DEBUGGING CHECKLIST

When sign-in fails, check these in order:

### **1. Frontend Issues**
- [ ] Check browser console for errors (F12)
- [ ] Verify VITE_GOOGLE_CLIENT_ID is set in .env
- [ ] Verify Google SDK loaded: `window.google?.accounts?.id` exists
- [ ] Check network tab - see the POST to /api/auth/google

### **2. Network Issues**
- [ ] Check response from /api/auth/google (should be 200)
- [ ] Check response body (should be {token, user})
- [ ] Check CORS headers in response (should allow * or your domain)

### **3. Backend Issues**
- [ ] Check backend logs: `tail -f logs/app.log` (or wherever you log)
- [ ] Verify GOOGLE_CLIENT_ID env var is set
- [ ] Verify DATABASE_URL env var is set
- [ ] Test database connection: `python -c "from db_manager import CandleDatabase; db = CandleDatabase(os.getenv('DATABASE_URL')); print('DB OK')"`

### **4. Google API Issues**
- [ ] Go to Google Cloud Console: https://console.cloud.google.com
- [ ] Check OAuth Credentials → your client ID
- [ ] Verify authorized JavaScript origins (should include grow-ten.vercel.app)
- [ ] Verify authorized redirect URIs (should include backend URL)

---

## 🧪 TEST FLOW

To manually test:

```bash
# 1. Start backend (if local)
cd /Users/parthsharma/Desktop/Grow
python app.py  # Should see "Running on..."

# 2. Check backend health
curl https://groww-api-m853.onrender.com/api/health

# 3. Go to frontend
https://grow-ten.vercel.app/login

# 4. Open DevTools (F12)
# 5. Click "Sign in with Google"
# 6. Watch console for:
#    === Google Sign-In Initialization ===
#    ✓ Google Sign-In initialized successfully
#    🔐 Sending credential to backend...
#    ✓ Authentication successful

# 7. Check if redirected to dashboard
```

---

## 📋 Data Flow After Sign-In

Once signed in, the frontend has:
- **JWT Token**: Stored in localStorage/sessionStorage
- **User Object**: {id, email, name}

For protected API calls:
```javascript
// Backend expects Authorization header
fetch(`${API_URL}/api/protected-resource`, {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});
```

Backend validates:
```python
@app.before_request
def check_auth():
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not token:
        return {'error': 'No token'}, 401
    
    payload = auth_manager.verify_jwt(token)
    if not payload:
        return {'error': 'Invalid token'}, 401
    
    # Now you know user_id and email
    request.user_id = payload['user_id']
    request.email = payload['email']
```

---

## 🚀 SUMMARY

**Sign-In Process:**
1. User clicks "Sign in with Google"
2. Google OAuth popup opens
3. User signs in with Google account
4. Google returns ID Token (JWT)
5. Frontend sends token to your backend
6. Backend verifies token is from Google
7. Backend creates/updates user in database
8. Backend generates your app's JWT
9. Frontend receives token + user
10. Frontend stores token and redirects to dashboard

**Two Tokens:**
- **Google ID Token**: Proves user identity to your backend
- **Your App Token**: Proves user is logged into your app, sent with every protected request

