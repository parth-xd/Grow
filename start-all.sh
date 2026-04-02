#!/bin/bash
# One-command startup for Groww Trading Bot + Dashboard
# Usage: ./start-all.sh

cd "$(dirname "$0")"

echo "🚀 Starting Groww Trading Bot..."

# Kill any existing processes on ports 8000
lsof -ti:8000 | xargs kill -9 2>/dev/null

# Activate virtual environment
source .venv/bin/activate

# Start Flask server in background
echo "📡 Starting Flask server on http://localhost:8000..."
nohup python3 app.py > server.log 2>&1 &
FLASK_PID=$!
echo "✓ Flask server started (PID: $FLASK_PID)"

# Wait for server to be ready
sleep 3

# Start paper trading bot in background
echo "📊 Starting paper trading bot..."
nohup python3 paper_trader.py > paper_trader.log 2>&1 &
TRADER_PID=$!
echo "✓ Paper trading bot started (PID: $TRADER_PID)"

# Open dashboard in browser
echo "🌐 Opening dashboard..."
sleep 2
open "http://localhost:8000" 2>/dev/null || echo "Please open http://localhost:8000 in your browser"

echo ""
echo "✅ All systems running!"
echo ""
echo "Logs:"
echo "  - Flask:  server.log"
echo "  - Trader: paper_trader.log"
echo ""
echo "To stop everything, run: pkill -f 'python3 app.py\|python3 paper_trader.py'"
echo ""
