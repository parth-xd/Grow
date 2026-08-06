# 🚀 Groww Trading System - Startup Guide

Complete startup management system for the Groww Trading Platform, which consists of three integrated services:

- **Flask Backend** (Python) - Trading logic & API server
- **Next.js Frontend** (Node.js) - Web dashboard UI  
- **Graphify** (Optional) - Real-time knowledge graph visualization

## Quick Start

### One-Command Startup (All Services)

```bash
./start-all.sh
```

This will:
1. ✓ Create Python virtual environment (if needed)
2. ✓ Install Python dependencies
3. ✓ Install Node.js dependencies
4. ✓ Start Flask backend on http://localhost:8000
5. ✓ Build & start Next.js frontend on http://localhost:3000
6. ✓ Start Graphify knowledge graph watcher (if installed)
7. ✓ Save process IDs for management

### Stop All Services

```bash
./stop-all.sh
```

Cleanly shuts down all running services.

### Check Service Status

```bash
./status.sh              # Show status once
./status.sh -w           # Watch mode (updates every 2 seconds)
```

---

## Available Scripts

### `start-all.sh` - Start Everything

**Usage:**
```bash
./start-all.sh                    # Start all 3 services
./start-all.sh --dashboard-only   # Flask only (no frontend)
./start-all.sh --frontend-only    # Next.js only (no Flask)
./start-all.sh --no-graphify      # Skip Graphify
./start-all.sh --stop             # Stop all services
```

**What it does:**
- Clears existing processes on ports 8000, 3000
- Sets up Python virtual environment
- Installs/updates all dependencies
- Starts all services in background
- Saves PIDs for cleanup
- Displays running services & logs

**Key Features:**
- ✓ Automatic dependency installation
- ✓ Graceful shutdown with signal trapping
- ✓ Service health checks
- ✓ Colored output for easy reading
- ✓ Automatic port cleanup
- ✓ Persistent PID tracking

### `stop-all.sh` - Stop Everything

**Usage:**
```bash
./stop-all.sh        # Stop all services
./stop-all.sh -v     # Verbose output
```

**What it does:**
- Gracefully terminates each service
- Waits up to 5 seconds for clean shutdown
- Force kills if needed
- Cleans up PID file

### `status.sh` - Service Status

**Usage:**
```bash
./status.sh          # Show status once
./status.sh -w       # Watch mode
```

**What it shows:**
- Running services and ports
- Process IDs
- Log file status
- Quick command reference

---

## Architecture Overview

```
Groww Trading System
│
├── 📊 Flask Backend (Port 8000)
│   ├── Python 3.x
│   ├── app.py (main server)
│   ├── requirements.txt (dependencies)
│   └── Virtual Environment (.venv/)
│
├── ⚛️  Next.js Frontend (Port 3000)
│   ├── Node.js
│   ├── frontend/ (Next.js project)
│   ├── package.json (dependencies)
│   ├── .next/ (build output)
│   └── node_modules/
│
├── 📈 Graphify (Optional)
│   └── Knowledge graph watcher
│       Watches current directory for changes
│
└── 🛠️  Management Scripts
    ├── start-all.sh (orchestrator)
    ├── stop-all.sh (cleanup)
    ├── status.sh (monitoring)
    ├── .groww-pids (process tracking)
    └── *.log (service logs)
```

---

## Prerequisites

### System Requirements
- macOS (or Linux with bash 4+)
- Python 3.8+
- Node.js 16+ (with npm)

### Optional
- Graphify (for knowledge graph): `brew install graphify` or `pip install graphify-cli`

### Setup (One-time)

```bash
# 1. Clone/navigate to project
cd ~/Desktop/Grow

# 2. Check Python
python3 --version  # Should be 3.8+

# 3. Check Node
node --version     # Should be 16+
npm --version      # Should be 8+

# 4. Make scripts executable
chmod +x *.sh
```

---

## Service Details

### Flask Backend (Port 8000)

**Startup Process:**
1. Activate Python virtual environment
2. Install `requirements.txt` dependencies
3. Run `app.py`
4. Wait for "Running on http://127.0.0.1:8000" message

**Configuration:**
- File: `app.py`
- Dependencies: `requirements.txt`
- Virtual environment: `.venv/`
- Log: `server.log`
- Environment variables: `.env` (create if needed)

**API Endpoints:**
```
GET  http://localhost:8000/          # Dashboard (index.html)
GET  http://localhost:8000/api/*     # API endpoints
```

**Quick Commands:**
```bash
# Manual start
source .venv/bin/activate
python3 app.py

# View logs
tail -f server.log

# View specific lines
tail -50 server.log
```

### Next.js Frontend (Port 3000)

**Startup Process:**
1. Check/install Node dependencies (`npm install`)
2. Check for built project (`.next/` directory)
3. Build if missing (`npm run build`)
4. Start production server (`npm start`)

**Configuration:**
- Directory: `frontend/`
- Dependencies: `frontend/package.json`
- Built output: `frontend/.next/`
- Log: `frontend/nextjs.log`
- Dev mode: `npm run dev`
- Production: `npm run build && npm start`

**Quick Commands:**
```bash
cd frontend

# Development mode (hot reload)
npm run dev

# Production build
npm run build

# Start production server
npm start

# View logs
tail -f ../frontend/nextjs.log
```

### Graphify (Optional)

**Startup Process:**
1. Checks if `graphify` command is available
2. Runs `graphify watch .` in project root
3. Watches for file changes to update knowledge graph

**Configuration:**
- Command: `/opt/homebrew/bin/graphify`
- Mode: Watch directory for changes
- Log: `graphify.log`
- Output: Knowledge graph files

**Installation:**
```bash
# via Homebrew (macOS)
brew install graphify

# via pip
pip install graphify-cli
```

**Quick Commands:**
```bash
# Manual watch
graphify watch .

# View logs
tail -f graphify.log

# Generate once
graphify .
```

---

## Troubleshooting

### Issue: Port Already in Use

**Error:** `Address already in use`

**Solution:**
```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Kill process on port 3000
lsof -ti:3000 | xargs kill -9

# Or use the stop script
./stop-all.sh

# Then restart
./start-all.sh
```

### Issue: Services Not Starting

**Check logs first:**
```bash
tail -50 server.log          # Flask logs
tail -50 frontend/nextjs.log # Next.js logs
tail -50 graphify.log        # Graphify logs
```

**Common Flask Issues:**
```bash
# Missing virtual environment
rm -rf .venv/
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py

# Module import errors
pip install -q -r requirements.txt --force-reinstall
```

**Common Next.js Issues:**
```bash
# Clear build cache
cd frontend
rm -rf node_modules .next package-lock.json
npm install
npm run build
npm start
cd ..
```

### Issue: Python Virtual Environment Issues

```bash
# Recreate virtual environment
rm -rf .venv/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Issue: Node Dependencies Not Updating

```bash
# Clean reinstall
cd frontend
rm -rf node_modules package-lock.json
npm cache clean --force
npm install
npm run build
```

### Issue: Graphify Not Found

```bash
# Install Graphify
brew install graphify

# Or verify installation
which graphify
graphify --version

# Run start-all.sh with --no-graphify to skip
./start-all.sh --no-graphify
```

---

## Development Workflows

### Local Development (Hot Reload)

Instead of production mode, run frontend in development:

```bash
# Terminal 1: Flask backend
source .venv/bin/activate
python3 app.py

# Terminal 2: Next.js frontend (dev mode)
cd frontend
npm run dev

# Terminal 3: Graphify (optional)
graphify watch .
```

Then open:
- http://localhost:3000 (frontend with hot reload)
- http://localhost:8000 (Flask API)

### Docker Development (Future)

Once Docker is set up:
```bash
docker-compose up
```

### Production Deployment

```bash
# Build frontend
cd frontend
npm run build
npm start &

# Run Flask with production server
gunicorn app:app --bind 0.0.0.0:8000 &
```

---

## File Reference

```
~/Desktop/Grow/
│
├── 📜 Scripts (Executable)
│   ├── start-all.sh           ⭐ Main startup orchestrator
│   ├── stop-all.sh            ⭐ Clean shutdown
│   ├── status.sh              ⭐ Service monitoring
│   └── STARTUP_README.md      📚 This file
│
├── 🐍 Backend (Flask)
│   ├── app.py                 Main Flask application
│   ├── requirements.txt        Python dependencies
│   ├── .venv/                 Virtual environment
│   ├── server.log             Flask output log
│   └── .env                   Configuration (optional)
│
├── ⚛️  Frontend (Next.js)
│   ├── frontend/
│   │   ├── app/               Application code
│   │   ├── components/        React components
│   │   ├── pages/             Next.js pages
│   │   ├── public/            Static files
│   │   ├── package.json       Dependencies
│   │   ├── next.config.js     Next.js config
│   │   ├── tsconfig.json      TypeScript config
│   │   ├── .next/             Build output
│   │   ├── node_modules/      Installed packages
│   │   └── nextjs.log         Next.js output log
│   └── frontend/nextjs.log    Frontend server logs
│
├── 📊 Other
│   ├── index.html             Static dashboard (optional)
│   ├── graphify.log           Graphify output log
│   ├── .groww-pids            Process ID tracking
│   └── README.md              Project README
```

---

## Advanced Usage

### Environment Variables

Create `.env` in project root for Flask configuration:

```bash
# .env
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///app.db
```

Then reload Flask:
```bash
./stop-all.sh
./start-all.sh
```

### Custom Configuration

Edit `start-all.sh` to customize:
- Ports (currently 8000, 3000)
- Log file locations
- Startup behavior
- Health checks

### Monitoring with tmux (Advanced)

```bash
# Create session
tmux new-session -d -s groww

# Flask window
tmux new-window -t groww -n flask
tmux send-keys -t groww:flask "source .venv/bin/activate && python3 app.py" Enter

# Frontend window
tmux new-window -t groww -n frontend
tmux send-keys -t groww:frontend "cd frontend && npm run dev" Enter

# Graphify window
tmux new-window -t groww -n graphify
tmux send-keys -t groww:graphify "graphify watch ." Enter

# Attach to session
tmux attach -t groww
```

---

## FAQ

**Q: Do I need to run `npm install` manually?**  
A: No! `start-all.sh` checks and installs dependencies automatically.

**Q: Can I run just Flask or just Next.js?**  
A: Yes! Use `--dashboard-only` or `--frontend-only` flags.

**Q: What if I want to modify app.py while it's running?**  
A: The app won't auto-reload in production mode. For development, use:
```bash
# Terminal 1
source .venv/bin/activate
python3 -m flask run --reload

# Terminal 2
cd frontend && npm run dev
```

**Q: How do I see real-time logs?**  
A: Use `tail -f`:
```bash
tail -f server.log               # Flask
tail -f frontend/nextjs.log      # Next.js
tail -f graphify.log             # Graphify
```

**Q: Can I customize ports?**  
A: Yes! Edit `start-all.sh` and change `FLASK_PORT=8000` and `NEXTJS_PORT=3000`.

**Q: What about background service on reboot?**  
A: Use system launch agents (macOS) or systemd (Linux). See Advanced Usage.

---

## Support

For issues:
1. Check logs: `tail -50 server.log`
2. Try stopping and restarting: `./stop-all.sh && ./start-all.sh`
3. Check ports: `lsof -i :8000 && lsof -i :3000`
4. Verify Python/Node versions

---

**Last Updated:** 2024
**Compatibility:** macOS, Linux
