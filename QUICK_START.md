# ⚡ QUICK START (30 Seconds)

## First Time?

```bash
cd ~/Desktop/Grow
./start-all.sh
```

Done! ✅

Open in browser:
- http://localhost:8000 (Flask Backend)
- http://localhost:3000 (Next.js Frontend)

Press `Ctrl+C` to stop everything.

---

## Regular Use

```bash
# Start
./start-all.sh

# Check status anytime
./status.sh

# View logs
tail -f server.log

# Stop when done
./stop-all.sh
```

---

## Common Commands

| Command | Purpose |
|---------|---------|
| `./start-all.sh` | Start all services (Flask + Next.js + Graphify) |
| `./stop-all.sh` | Stop all services cleanly |
| `./status.sh` | Check service status |
| `./status.sh -w` | Watch service status (updates every 2s) |
| `tail -f server.log` | View Flask logs |
| `tail -f frontend/nextjs.log` | View Next.js logs |

---

## Options

```bash
# Start only Flask backend
./start-all.sh --dashboard-only

# Start only Next.js frontend
./start-all.sh --frontend-only

# Start without Graphify
./start-all.sh --no-graphify

# View help
./start-all.sh --help
```

---

## Troubleshooting

**Port in use?**
```bash
./stop-all.sh
./start-all.sh
```

**Services not starting?**
```bash
tail -50 server.log
tail -50 frontend/nextjs.log
./status.sh
```

**Need to reset?**
```bash
./stop-all.sh
rm -rf .venv frontend/node_modules frontend/.next
./start-all.sh
```

---

## What's Running?

After `./start-all.sh`:

| Service | Port | Tech Stack | URL |
|---------|------|-----------|-----|
| Flask Backend | 8000 | Python 3.x | http://localhost:8000 |
| Next.js Frontend | 3000 | Node.js | http://localhost:3000 |
| Graphify | - | Knowledge Graph | (background) |

---

## Documentation

- **Full Guide:** [STARTUP_README.md](STARTUP_README.md)
- **Troubleshooting:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **Frontend Dev:** [FRONTEND_SETUP_GUIDE.md](FRONTEND_SETUP_GUIDE.md)
- **Database:** [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)

---

## Architecture

```
Browser (port 3000)
    ↓
Next.js Frontend
    ↓
Flask Backend (port 8000)
    ↓
Database
```

---

## Tips

✅ Scripts auto-install dependencies
✅ Scripts auto-build Next.js
✅ All output is logged
✅ Ctrl+C stops everything cleanly
✅ Use `./status.sh -w` to monitor

---

**Ready?** Run: `./start-all.sh` 🚀
