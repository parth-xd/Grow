#!/bin/bash

################################################################################
# 📋 Groww Trading System - Quick Reference
################################################################################
# Common commands and workflows for Groww development
#
# Source this file in your shell for quick access to functions:
#   source groww-commands.sh
#
# Then use shortcuts like:
#   groww-start        # Start all services
#   groww-stop         # Stop all services
#   groww-status       # Check status
#   groww-logs         # Tail all logs
#
################################################################################

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}📋 Groww Trading System - Quick Reference${NC}"
echo ""
echo "🚀 STARTUP & SHUTDOWN"
echo "  ./start-all.sh              Start all services"
echo "  ./start-all.sh --dashboard-only  Start Flask only"
echo "  ./start-all.sh --frontend-only   Start Next.js only"
echo "  ./stop-all.sh               Stop all services"
echo ""
echo "📊 MONITORING"
echo "  ./status.sh                 Check service status"
echo "  ./status.sh -w              Watch mode (auto-refresh)"
echo ""
echo "📝 LOGS"
echo "  tail -f server.log          Flask server log"
echo "  tail -f frontend/nextjs.log Next.js server log"
echo "  tail -f graphify.log        Graphify watch log"
echo ""
echo "🐍 FLASK BACKEND"
echo "  source .venv/bin/activate   Activate Python environment"
echo "  pip install -r requirements.txt  Install Python packages"
echo "  python3 app.py              Run Flask manually"
echo "  deactivate                  Exit Python environment"
echo ""
echo "⚛️  NEXT.JS FRONTEND"
echo "  cd frontend                 Enter frontend directory"
echo "  npm install                 Install Node packages"
echo "  npm run dev                 Development mode (hot reload)"
echo "  npm run build               Build for production"
echo "  npm start                   Start production server"
echo "  cd ..                       Back to project root"
echo ""
echo "🔧 UTILITY"
echo "  lsof -i :8000               Check port 8000 (Flask)"
echo "  lsof -i :3000               Check port 3000 (Next.js)"
echo "  lsof -ti:8000 | xargs kill -9    Force kill Flask"
echo "  lsof -ti:3000 | xargs kill -9    Force kill Next.js"
echo ""
echo "📱 BROWSER SHORTCUTS"
echo "  http://localhost:8000       Flask Dashboard"
echo "  http://localhost:3000       Next.js Frontend"
echo ""
echo "🆘 TROUBLESHOOTING"
echo "  ./stop-all.sh && ./start-all.sh  Full restart"
echo "  rm -rf .venv && ./start-all.sh   Rebuild Python env"
echo "  rm -rf frontend/node_modules && ./start-all.sh  Rebuild Node env"
echo ""
