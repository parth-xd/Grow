# Supabase IP Whitelist Check & Fix Guide

## ✅ Render Environment: GOOD ✓

Since you confirmed Render env is perfect, the issue is **likely Supabase IP whitelist blocking Render**.

---

## 🔐 How to Check Supabase IP Whitelist

### Step 1: Go to Supabase Dashboard
**URL**: https://app.supabase.com/projects

### Step 2: Select Your Project
Click on your Grow project

### Step 3: Navigate to Database Settings
```
Left sidebar → Settings → Database
```

### Step 4: Find "Network" or "Firewall Rules"
Scroll down the Database page. You'll see:
- **"Firewall" tab** (for newer Supabase UI), OR
- **"Network"** section (for older UI), OR  
- **"IP Whitelist"** checkbox

### Step 5: Check Current Status

You'll see something like:

#### ❌ IF YOU SEE THIS:
```
🔴 Firewall: ENABLED

Whitelisted IPs:
- 192.168.1.100
- 10.0.0.0/8
[Other specific IPs...]
```
👉 **This is blocking Render!**

#### ✅ IF YOU SEE THIS:
```
🟢 Firewall: DISABLED
All IPs allowed to connect
```
👉 **This is NOT the problem**

---

## 🔧 How to Fix: 2 Options

### OPTION 1: DISABLE IP WHITELIST (Easiest - Development)

**Steps:**
1. Find "Firewall" toggle or "IP Whitelist" checkbox
2. **TURN IT OFF** / **DISABLE** it
3. Click **"Apply"** or **"Save"**
4. Wait 10-20 seconds for changes to apply
5. Test sign-in again

**Pros**: Simplest, works immediately  
**Cons**: Less secure (any IP can access)  
**When to use**: Development/testing

---

### OPTION 2: ADD RENDER IPs TO WHITELIST (Recommended for Production)

**Render's IP Ranges:**
```
52.0.0.0/8          (Main AWS US region)
44.55.243.0/24      (Backup)
44.55.242.0/24      (Backup)
```

**Steps:**
1. Find the "Add IP" or "Whitelist" button
2. Add each IP range:
   - `52.0.0.0/8`
   - `44.55.243.0/24`
   - `44.55.242.0/24`
3. (Optional) Add your local development IP if testing locally
4. Click **"Apply"** or **"Save"**
5. Wait 10-20 seconds
6. Test sign-in again

**Pros**: More secure, only Render can access  
**Cons**: Takes a bit longer to set up  
**When to use**: Production

---

## 🧪 After Making Changes: Test Sign-In

1. Go to **https://grow-ten.vercel.app/login**
2. Click **"Sign in with Google"**
3. Complete Google OAuth
4. If it works: 🎉 **SUCCESS!**
5. If still 503: Check browser console for new error message

---

## ⚡ Quick Checklist

- [ ] Logged into Supabase dashboard
- [ ] Found Settings → Database → Firewall/Network section
- [ ] Checked current IP whitelist status
- [ ] Either:
  - [ ] Disabled IP whitelist, OR
  - [ ] Added Render IPs (52.0.0.0/8, 44.55.243.0/24, 44.55.242.0/24)
- [ ] Clicked "Apply" / "Save"
- [ ] Waited 10-20 seconds for changes
- [ ] Tested sign-in at https://grow-ten.vercel.app/login

---

## 📊 Expected Result After Fix

When you try signing in again:
- ✅ Google popup works
- ✅ No 503 error
- ✅ Redirects to dashboard
- ✅ "Welcome to Grow!" message

---

## 🆘 Still Getting 503?

If IP whitelist wasn't the issue, it might be:

1. **Wrong DATABASE_URL** in Render
   - Check it has `?sslmode=require` at end
   - Should start with `postgresql://`

2. **Supabase database not running**
   - Check Supabase project is active (should show green status)

3. **Tables don't exist**
   - Run migrations manually:
     ```bash
     python3 migrate_refresh_tokens.py
     ```

4. **Connection string format issue**
   - Ensure no spaces or special characters
   - Should be exactly: `postgresql://user:password@host:5432/database?sslmode=require`

---

## 🔍 Debug Resources

- Render logs: https://dashboard.render.com → Grow API service → Logs
- Supabase project status: https://app.supabase.com/projects
- Health endpoint: https://groww-api-m853.onrender.com/api/health
