# 🚀 QUICK START FOR OWNER

## You have 3 things to do:

### 1️⃣ Get Your Groww Credentials (5 mins)
```
1. Go to https://groww.in
2. Login
3. Settings → Developer API
4. Create API app, copy:
   - API Key
   - API Secret  
   - Access Token
```

### 2️⃣ Add to Render (5 mins)
```
1. Go to https://dashboard.render.com/services/groww-api
2. Settings → Environment Variables
3. Paste this (replace <values>):

GROWW_API_KEY=<your key>
GROWW_API_SECRET=<your secret>
GROWW_ACCESS_TOKEN=<your token>
JWT_SECRET=randomstring123
SECRET_KEY=randomstring456
ENCRYPTION_KEY=<run Python code below>
GOOGLE_CLIENT_ID=909946700089-5fr10qa7c51cl88ofmft1gp9f6eldsv1.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=<from Google Cloud>
DATABASE_URL=postgresql://postgres:f6n2GYbXyTYi1TlD@db.vvonimxqwporrofklnvf.supabase.co:5432/postgres

4. "Manual Deploy"
5. Wait 5 mins
```

**Generate ENCRYPTION_KEY:**
```python
# Run in Python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

### 3️⃣ Get Google Client Secret (5 mins)
```
1. Go to https://console.cloud.google.com
2. Find "Groww AI Trading" project
3. Credentials → OAuth 2.0 Client ID
4. Copy "Client Secret"
5. Add to Render as GOOGLE_CLIENT_SECRET
6. "Manual Deploy" again
```

---

## Done! Share this link:
```
https://grow.ten.vercel.app
```

Your friend signs in with Google, sees YOUR portfolio.

---

## Test It:
```bash
curl https://groww-api-m853.onrender.com/api/health
```

Should return:
```json
{"status": "ok"}
```

---

## For Your Own Testing Locally:
```bash
cd /Users/parthsharma/Desktop/Grow
cp .env.production .env
# Edit .env with your credentials
pip install -r requirements.txt
python3 app.py  # http://localhost:8000

# Terminal 2:
cd frontend && npm run dev  # http://localhost:5173
```

---

**Full guide:** Read `OWNER_SETUP.md`
**Troubleshooting:** Read `DEPLOYMENT_CHECKLIST.md`
