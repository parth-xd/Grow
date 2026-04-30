#!/bin/bash

################################################################################
# 🛑 Groww Trading System - Stop All Services
################################################################################
# Cleanly stops all running services (Flask, Next.js, Graphify)
#
# Usage:
#   ./stop-all.sh        # Stop all services
#   ./stop-all.sh -v     # Verbose output
#
################################################################################

VERBOSE=${1:-}
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_ROOT/.groww-pids"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() {
  echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}⚠${NC} $1"
}

log_status() {
  echo -e "${CYAN}ℹ${NC} $1"
}

kill_process() {
  local pid=$1
  local name=$2
  
  if [ -z "$pid" ] || ! kill -0 $pid 2>/dev/null; then
    [ "$VERBOSE" ] && log_warn "$name (PID: $pid) not running"
    return 0
  fi
  
  echo -n "  Stopping $name (PID: $pid)... "
  kill -TERM $pid 2>/dev/null || true
  
  local count=0
  while kill -0 $pid 2>/dev/null && [ $count -lt 50 ]; do
    sleep 0.1
    count=$((count + 1))
  done
  
  if kill -0 $pid 2>/dev/null; then
    kill -9 $pid 2>/dev/null || true
  fi
  
  echo "done"
}

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}🛑 Stopping Groww Trading System${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ -f "$PID_FILE" ]; then
  [ "$VERBOSE" ] && log_status "Reading PIDs from $PID_FILE..."
  
  FLASK_PID=$(grep "FLASK_PID=" "$PID_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
  NEXTJS_PID=$(grep "NEXTJS_PID=" "$PID_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
  GRAPHIFY_PID=$(grep "GRAPHIFY_PID=" "$PID_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
  
  [ -n "$FLASK_PID" ] && kill_process "$FLASK_PID" "Flask Backend"
  [ -n "$NEXTJS_PID" ] && kill_process "$NEXTJS_PID" "Next.js Frontend"
  [ -n "$GRAPHIFY_PID" ] && kill_process "$GRAPHIFY_PID" "Graphify"
  
  rm -f "$PID_FILE"
else
  log_warn "No PID file found at $PID_FILE"
  log_status "Attempting to kill by port..."
  
  local pids=$(lsof -ti:8000 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo -n "  Killing Flask Backend (port 8000)... "
    echo "$pids" | xargs kill -9 2>/dev/null || true
    echo "done"
  fi
  
  pids=$(lsof -ti:3000 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo -n "  Killing Next.js Frontend (port 3000)... "
    echo "$pids" | xargs kill -9 2>/dev/null || true
    echo "done"
  fi
  
  pkill -f "graphify watch" 2>/dev/null || true
  echo -n "  Killing Graphify... "
  sleep 1
  echo "done"
fi

echo ""
log_info "All services stopped"
echo ""
