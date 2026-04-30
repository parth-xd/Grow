# 🔧 Troubleshooting Guide

## Quick Diagnostics

Before troubleshooting, run this to check your system:

```bash
./status.sh              # Check service status
tail -20 server.log      # Check Flask logs
tail -20 frontend/nextjs.log  # Check Next.js logs
```

---

## Common Issues

### ❌ "Address already in use"

**Problem:** Port 8000 or 3000 already has a running process

**Solution:**
```bash
# Check what's using the port
lsof -i :8000   # For Flask
lsof -i :3000   # For Next.js

# Force kill (be careful!)
lsof -ti:8000 | xargs kill -9
lsof -ti:3000 | xargs kill -9

# Then restart
./start-all.sh
```

---

### ❌ "No such file or directory: .venv"

**Problem:** Python virtual environment wasn't created

**Solution:**
```bash
# Create it
python3 -m venv .venv

# Or let start-all.sh do it
./start-all.sh
```

---

### ❌ "ModuleNotFoundError: No module named 'flask'"

**Problem:** Flask or other Python dependencies not installed

**Solution:**
```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Or restart everything
./stop-all.sh
./start-all.sh
```

---

### ❌ "npm ERR! ENOENT: no such file or directory"

**Problem:** Node modules not installed

**Solution:**
```bash
cd frontend
npm install
npm run build
cd ..
./start-all.sh
```

---

### ❌ Flask shows "CRITICAL: Couldn't connect to the Docker daemon"

**Problem:** Docker is not running (if your app uses Docker)

**Solution:**
```bash
# If you don't use Docker, ignore this error
# If you do use Docker, start Docker and try again
```

---

### ❌ "graphify: command not found"

**Problem:** Graphify not installed

**Solution:**
```bash
# Install Graphify
brew install graphify

# Or skip it for now
./start-all.sh --no-graphify
```

---

### ❌ Services start but immediately stop

**Problem:** Check the logs for actual errors

**Solution:**
```bash
# View Flask logs
cat server.log

# View Next.js logs
cat frontend/nextjs.log

# Look for error messages and fix the underlying issue
```

---

### ❌ Frontend (port 3000) won't start

**Problem:** Next.js build might be failing

**Solution:**
```bash
# Navigate to frontend
cd frontend

# Clean build
rm -rf node_modules .next package-lock.json

# Reinstall and build
npm install
npm run build

# Test
npm start

# If it works, go back and use start-all.sh
cd ..
./start-all.sh
```

---

### ❌ Backend (port 8000) won't start

**Problem:** Python dependencies or Flask configuration issue

**Solution:**
```bash
# Activate venv
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Test manually
python3 app.py

# If it works, use start-all.sh
./start-all.sh
```

---

### ❌ "Permission denied" when running scripts

**Problem:** Scripts don't have execute permissions

**Solution:**
```bash
chmod +x start-all.sh
chmod +x stop-all.sh
chmod +x status.sh
```

---

### ❌ Ctrl+C doesn't stop services cleanly

**Problem:** The cleanup handler might not be working

**Solution:**
```bash
# Use the stop script instead
./stop-all.sh

# Or kill by port
lsof -ti:8000 | xargs kill -9
lsof -ti:3000 | xargs kill -9
```

---

## Advanced Diagnostics

### Check Python Environment

```bash
# Which Python version
python3 --version

# Where's Python located
which python3

# List installed packages
source .venv/bin/activate
pip list

# Check specific package
pip show flask
```

### Check Node Environment

```bash
# Node version
node --version

# npm version
npm --version

# Check installed packages
cd frontend
npm list

# Check for duplicates
npm ls --depth=0
```

### Check Ports

```bash
# What's using port 8000
lsof -i :8000

# What's using port 3000
lsof -i :3000

# All Python processes
ps aux | grep python

# All Node processes
ps aux | grep node
```

### View Complete Logs

```bash
# Flask full log
cat server.log

# Next.js full log
cat frontend/nextjs.log

# Graphify full log
cat graphify.log

# System processes
ps aux | grep -E "python|node|graphify"
```

---

## Reset & Rebuild

### Soft Reset (Clear logs, keep dependencies)

```bash
./stop-all.sh
rm -f *.log frontend/*.log graphify.log
./start-all.sh
```

### Hard Reset (Full rebuild)

```bash
./stop-all.sh

# Clear everything
rm -rf .venv
rm -rf frontend/node_modules frontend/.next
rm -f *.log frontend/*.log .groww-pids

# Rebuild from scratch
./start-all.sh
```

### Nuclear Option (If nothing works)

```bash
# Stop everything
./stop-all.sh

# Kill any lingering processes
pkill -f "python3 app.py"
pkill -f "node"
pkill -f "npm"
pkill -f "next"
pkill -f "graphify"

# Clean everything
rm -rf .venv frontend/node_modules frontend/.next
rm -f *.log frontend/*.log .groww-pids

# Start fresh
./start-all.sh
```

---

## Performance Issues

### Slow Flask Startup

```bash
# Check if dependencies are missing
source .venv/bin/activate
pip list | wc -l

# Time the startup
time python3 app.py &
sleep 5
kill $!
```

### Slow Next.js Build

```bash
cd frontend

# Check what's slowing it down
npm run build

# Clear cache and rebuild
rm -rf .next node_modules
npm install
npm run build
```

### High CPU Usage

```bash
# Check what's using CPU
top -n 1 | grep -E "python|node"

# If Graphify is using too much CPU
./stop-all.sh --no-graphify
./start-all.sh
```

---

## Getting Help

1. **Check logs first:**
   ```bash
   tail -50 server.log
   tail -50 frontend/nextjs.log
   ```

2. **Verify system:**
   ```bash
   python3 --version    # Should be 3.8+
   node --version       # Should be 16+
   npm --version        # Should be 8+
   ```

3. **Check port status:**
   ```bash
   lsof -i :8000
   lsof -i :3000
   ```

4. **Try a clean restart:**
   ```bash
   ./stop-all.sh
   sleep 2
   ./start-all.sh
   ```

5. **If all else fails:**
   ```bash
   # Nuclear reset (careful!)
   rm -rf .venv frontend/node_modules frontend/.next
   ./stop-all.sh
   pkill -f python3
   pkill -f node
   ./start-all.sh
   ```

---

## Need More Help?

- Check `STARTUP_README.md` for detailed startup guide
- Check `FRONTEND_SETUP_GUIDE.md` for frontend-specific issues
- Check log files: `server.log`, `frontend/nextjs.log`
- Run `./status.sh` to check service status

---

**Updated:** 2024
**Compatibility:** macOS, Linux
