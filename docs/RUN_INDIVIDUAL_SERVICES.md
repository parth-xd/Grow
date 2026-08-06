# 🎯 Run Individual Services

Choose what you want to test/observe. You can run **one service at a time** with these commands:

---

## 🐍 Backend Only (Flask)

**Watch the trading engine work:**

```bash
./start-all.sh --dashboard-only
```

**What you get:**
- Flask server on http://localhost:8000
- No frontend
- No Graphify watcher
- Logs: `tail -f server.log`

**Good for:**
- Testing APIs
- Checking trading logic
- Debugging backend code
- Verifying database operations

**Stop it:**
```bash
./stop-all.sh
```

---

## ⚛️ Frontend Only (Next.js)

**Watch the web interface work:**

```bash
./start-all.sh --frontend-only
```

**What you get:**
- Next.js server on http://localhost:3000
- No Flask backend (frontend will show empty/error for API calls)
- No Graphify watcher
- Logs: `tail -f frontend/nextjs.log`

**Good for:**
- Testing UI components
- Checking page routing
- Verifying styling
- Debugging frontend code

**Note:** API calls will fail since there's no Flask backend. For full functionality, run `./start-all.sh` instead.

**Stop it:**
```bash
./stop-all.sh
```

---

## 📊 Graphify Only (Knowledge Graph)

**Watch the code understanding system work:**

```bash
./start-all.sh --graphify-only
```

**What you get:**
- Graphify watcher monitoring all code
- Knowledge graph updating in real-time
- No Flask backend
- No Next.js frontend
- Logs: `tail -f graphify.log`
- Output: `graphify-out/`

**Good for:**
- Seeing code indexed in real-time
- Understanding system architecture
- Checking what Graphify knows
- Watching change detection

**View the knowledge graph:**
```bash
open graphify-out/graph.html              # Interactive visualization
cat graphify-out/GRAPH_REPORT.md          # Analysis report
tail -f graphify.log                      # Watch indexing in real-time
```

**Stop it:**
```bash
./stop-all.sh
```

---

## 🚀 All Three Together

**Run everything:**

```bash
./start-all.sh
```

**What you get:**
- Flask on http://localhost:8000
- Next.js on http://localhost:3000
- Graphify watching both
- All logs available
- Full system working

**Stop it:**
```bash
./stop-all.sh
```

---

## 📋 Quick Reference

| Want to Run | Command |
|-------------|---------|
| **Flask Only** | `./start-all.sh --dashboard-only` |
| **Next.js Only** | `./start-all.sh --frontend-only` |
| **Graphify Only** | `./start-all.sh --graphify-only` |
| **Everything** | `./start-all.sh` |
| **Everything Except Graphify** | `./start-all.sh --no-graphify` |
| **Stop All** | `./stop-all.sh` |
| **Check Status** | `./status.sh` |

---

## 🔍 Viewing Output

### Flask Backend Logs
```bash
tail -f server.log          # Live logs
tail -50 server.log         # Last 50 lines
```

### Next.js Frontend Logs
```bash
tail -f frontend/nextjs.log     # Live logs
tail -50 frontend/nextjs.log    # Last 50 lines
```

### Graphify Logs
```bash
tail -f graphify.log            # Live logs
tail -50 graphify.log           # Last 50 lines
```

### Graphify Knowledge Graph
```bash
open graphify-out/graph.html         # Visual (interactive)
cat graphify-out/GRAPH_REPORT.md     # Text report
cat graphify-out/graph.json | less   # JSON data
```

---

## 💡 Common Scenarios

### Scenario 1: "I'm building the backend, don't need the frontend"
```bash
./start-all.sh --dashboard-only
tail -f server.log
# Make changes to *.py files
# Watch logs for results
```

### Scenario 2: "I'm building the frontend, backend is separate"
```bash
./start-all.sh --frontend-only
tail -f frontend/nextjs.log
# Make changes to frontend/
# Watch logs and browser
```

### Scenario 3: "I want to see how Graphify understands my code"
```bash
./start-all.sh --graphify-only
tail -f graphify.log
# Make code changes
# Watch Graphify reindex in real-time
open graphify-out/graph.html
# Refresh to see updated graph
```

### Scenario 4: "I need backend + Graphify but no frontend"
```bash
./start-all.sh --no-graphify    # Oops, this skips Graphify
# Better: use combination manually
```

---

## 🛑 Stopping Services

**Stop a specific service you started:**
```bash
./stop-all.sh
```

**Or manually stop by port (if needed):**
```bash
# Kill Flask
lsof -ti:8000 | xargs kill -9

# Kill Next.js
lsof -ti:3000 | xargs kill -9

# Kill Graphify
pkill -f "graphify watch"
```

---

## 🎯 Best Practices

✅ **Do:**
- Run one service at a time when focusing on that code
- Check logs while running to see what's happening
- Use `./status.sh` to verify what's running
- Stop with `./stop-all.sh` before starting again

❌ **Don't:**
- Try to run Flask and Next.js manually if script is already running
- Leave old services running (causes port conflicts)
- Ignore error messages in logs

---

## 🔄 Switching Between Services

**Switch from Flask to Next.js:**
```bash
./stop-all.sh
./start-all.sh --frontend-only
```

**Switch from Frontend to Graphify:**
```bash
./stop-all.sh
./start-all.sh --graphify-only
```

**Go back to everything:**
```bash
./stop-all.sh
./start-all.sh
```

---

## 📊 Monitoring While Running

### Terminal 1: Run the service
```bash
./start-all.sh --backend-only
```

### Terminal 2: Watch logs
```bash
tail -f server.log
```

### Terminal 3: Check health
```bash
./status.sh -w      # Watches every 2 seconds
```

---

**Pick what you want to work on and run just that! 🎯**
