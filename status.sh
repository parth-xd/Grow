#!/bin/bash

################################################################################
# 📊 Groww Trading System - Service Status
################################################################################
# Shows the status of all running services
#
# Usage:
#   ./status.sh         # Show status
#   ./status.sh -w      # Watch mode (updates every 2 seconds)
#
################################################################################

WATCH_MODE=${1:-}
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_ROOT/.groww-pids"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

check_service() {
  local port=$1
  local name=$2
  local pid=$3
  
  # Check if process is running
  local running=false
  if [ -n "$pid" ] && kill -0 $pid 2>/dev/null; then
    running=true
  elif nc -z localhost $port 2>/dev/null; then
    running=true
  fi
  
  if [ "$running" = true ]; then
    echo -e "  ${GREEN}✓${NC} ${name} on port ${port}"
    [ -n "$pid" ] && echo -e "     PID: $pid"
  else
    echo -e "  ${RED}✗${NC} ${name} on port ${port} (${YELLOW}not running${NC})"
  fi
}

show_status() {
  clear
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}📊 Groww Trading System - Status${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  
  if [ -f "$PID_FILE" ]; then
    echo "Services:"
    FLASK_PID=$(grep "FLASK_PID=" "$PID_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
    NEXTJS_PID=$(grep "NEXTJS_PID=" "$PID_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
    GRAPHIFY_PID=$(grep "GRAPHIFY_PID=" "$PID_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
    
    check_service 8000 "Flask Backend" "$FLASK_PID"
    check_service 3000 "Next.js Frontend" "$NEXTJS_PID"
    
    if [ -n "$GRAPHIFY_PID" ]; then
      if kill -0 $GRAPHIFY_PID 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Graphify (Knowledge Graph)"
        echo -e "     PID: $GRAPHIFY_PID"
      else
        echo -e "  ${RED}✗${NC} Graphify (Knowledge Graph) (${YELLOW}not running${NC})"
      fi
    fi
  else
    echo "No PID file found. Checking ports directly..."
    echo ""
    
    # Direct port checks
    if nc -z localhost 8000 2>/dev/null; then
      echo -e "  ${GREEN}✓${NC} Flask Backend on port 8000"
    else
      echo -e "  ${RED}✗${NC} Flask Backend on port 8000 (${YELLOW}not running${NC})"
    fi
    
    if nc -z localhost 3000 2>/dev/null; then
      echo -e "  ${GREEN}✓${NC} Next.js Frontend on port 3000"
    else
      echo -e "  ${RED}✗${NC} Next.js Frontend on port 3000 (${YELLOW}not running${NC})"
    fi
  fi
  
  echo ""
  echo "Logs:"
  for log in server.log frontend/nextjs.log graphify.log; do
    if [ -f "$PROJECT_ROOT/$log" ]; then
      local lines=$(wc -l < "$PROJECT_ROOT/$log" 2>/dev/null || echo 0)
      echo "  📄 $log ($lines lines)"
    fi
  done
  
  echo ""
  echo "Commands:"
  echo "  Start all:     ./start-all.sh"
  echo "  Stop all:      ./stop-all.sh"
  echo "  View logs:     tail -f server.log"
  echo ""
  
  if [ "$WATCH_MODE" ]; then
    echo "Refreshing in 2 seconds... (Ctrl+C to exit)"
    sleep 2
  else
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  fi
}

# Main loop
while true; do
  show_status
  [ -z "$WATCH_MODE" ] && break
done
