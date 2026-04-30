#!/bin/bash

################################################################################
# 🚀 Groww Trading System - Complete Startup Script
################################################################################
# Manages 3 services:
#   1. Flask Backend (Python) - localhost:8000
#   2. Next.js Frontend (Node.js) - localhost:3000  
#   3. Graphify (Knowledge Graph) - File watching
#
# Usage:
#   ./start-all.sh                    # Start all 3 services
#   ./start-all.sh --dashboard-only   # Flask Backend only
#   ./start-all.sh --frontend-only    # Next.js Frontend only
#   ./start-all.sh --graphify-only    # Graphify Knowledge Graph only
#   ./start-all.sh --no-graphify      # All except Graphify
#   ./start-all.sh --stop             # Stop all services
#
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
FLASK_PORT=8000
NEXTJS_PORT=3000
FLASK_LOG="$PROJECT_ROOT/server.log"
NEXTJS_LOG="$PROJECT_ROOT/frontend/nextjs.log"
GRAPHIFY_LOG="$PROJECT_ROOT/graphify.log"
PID_FILE="$PROJECT_ROOT/.groww-pids"

# Parse arguments
START_DASHBOARD=true
START_FRONTEND=true
START_GRAPHIFY=true
STOP_MODE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --dashboard-only) START_FRONTEND=false; START_GRAPHIFY=false ;;
    --frontend-only) START_DASHBOARD=false; START_GRAPHIFY=false ;;
    --graphify-only) START_DASHBOARD=false; START_FRONTEND=false ;;
    --no-graphify) START_GRAPHIFY=false ;;
    --stop) STOP_MODE=true ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

################################################################################
# Helper Functions
################################################################################

log_section() {
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}$1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_info() {
  echo -e "${GREEN}✓${NC} $1"
}

log_error() {
  echo -e "${RED}✗${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}⚠${NC} $1"
}

log_status() {
  echo -e "${CYAN}ℹ${NC} $1"
}

# Kill process by PID and wait
kill_process() {
  local pid=$1
  local name=$2
  
  if kill -0 $pid 2>/dev/null; then
    echo -n "  Stopping $name (PID: $pid)... "
    kill -TERM $pid 2>/dev/null || true
    
    # Wait up to 5 seconds for graceful shutdown
    local count=0
    while kill -0 $pid 2>/dev/null && [ $count -lt 50 ]; do
      sleep 0.1
      count=$((count + 1))
    done
    
    # Force kill if still running
    if kill -0 $pid 2>/dev/null; then
      kill -9 $pid 2>/dev/null || true
    fi
    echo "done"
  fi
}

# Kill port by port number
kill_port() {
  local port=$1
  local pids=$(lsof -ti:$port 2>/dev/null || true)
  
  if [ -n "$pids" ]; then
    echo "Killing existing processes on port $port..."
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
}

# Check if port is available
wait_for_port() {
  local port=$1
  local name=$2
  local max_attempts=30
  local attempt=0
  
  echo -n "  Waiting for $name on port $port... "
  while [ $attempt -lt $max_attempts ]; do
    if nc -z localhost $port 2>/dev/null; then
      echo "ready!"
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  
  echo "timeout!"
  return 1
}

# Wait for service to start by checking log
wait_for_service() {
  local log_file=$1
  local pattern=$2
  local name=$3
  local max_attempts=30
  local attempt=0
  
  echo -n "  Checking $name... "
  while [ $attempt -lt $max_attempts ]; do
    if [ -f "$log_file" ] && grep -q "$pattern" "$log_file" 2>/dev/null; then
      echo "running!"
      return 0
    fi
    sleep 0.5
    attempt=$((attempt + 1))
  done
  
  echo "check logs"
  return 1
}

################################################################################
# STOP MODE
################################################################################

if [ "$STOP_MODE" = true ]; then
  log_section "Stopping All Services"
  
  if [ -f "$PID_FILE" ]; then
    # Read PIDs from file
    FLASK_PID=$(grep "FLASK_PID=" "$PID_FILE" | cut -d= -f2)
    NEXTJS_PID=$(grep "NEXTJS_PID=" "$PID_FILE" | cut -d= -f2)
    GRAPHIFY_PID=$(grep "GRAPHIFY_PID=" "$PID_FILE" | cut -d= -f2)
    
    [ -n "$FLASK_PID" ] && kill_process "$FLASK_PID" "Flask Backend"
    [ -n "$NEXTJS_PID" ] && kill_process "$NEXTJS_PID" "Next.js Frontend"
    [ -n "$GRAPHIFY_PID" ] && kill_process "$GRAPHIFY_PID" "Graphify"
    
    rm -f "$PID_FILE"
    log_info "All services stopped"
  else
    log_warn "No PID file found. Trying to kill by port..."
    kill_port 8000
    kill_port 3000
    log_info "Ports cleared"
  fi
  
  echo ""
  exit 0
fi

################################################################################
# STARTUP MODE
################################################################################

log_section "🚀 Groww Trading System - Initializing"

cd "$PROJECT_ROOT"

# Kill existing processes
log_status "Clearing existing processes..."
kill_port 8000
kill_port 3000

################################################################################
# 1. PYTHON VIRTUAL ENVIRONMENT
################################################################################

if [ "$START_DASHBOARD" = true ]; then
  log_section "Python Environment Setup"
  
  if [ ! -d ".venv" ]; then
    log_warn "Virtual environment not found, creating..."
    python3 -m venv .venv
    log_info "Virtual environment created"
  fi
  
  source .venv/bin/activate
  log_info "Virtual environment activated"
  
  # Install/update dependencies
  if [ -f "requirements.txt" ]; then
    log_status "Checking Python dependencies..."
    pip install -q -r requirements.txt 2>/dev/null || {
      log_error "Failed to install Python dependencies"
      exit 1
    }
    log_info "Python dependencies installed"
  fi
fi

################################################################################
# 2. NODE.JS / NEXT.JS ENVIRONMENT
################################################################################

if [ "$START_FRONTEND" = true ]; then
  log_section "Node.js Environment Setup"
  
  cd "$PROJECT_ROOT/frontend"
  
  # Check if node_modules exists, install if needed
  if [ ! -d "node_modules" ]; then
    log_warn "Node modules not found, installing..."
    npm install -q 2>/dev/null || {
      log_error "Failed to install Node.js dependencies"
      exit 1
    }
    log_info "Node.js dependencies installed"
  else
    log_info "Node.js dependencies found"
  fi
  
  cd "$PROJECT_ROOT"
fi

################################################################################
# 3. START FLASK BACKEND
################################################################################

if [ "$START_DASHBOARD" = true ]; then
  log_section "Starting Flask Backend (Python)"
  
  # Clear old log
  > "$FLASK_LOG"
  
  # Start Flask
  echo "Starting Flask server on http://localhost:$FLASK_PORT..."
  nohup .venv/bin/python3 app.py > "$FLASK_LOG" 2>&1 &
  FLASK_PID=$!
  
  if wait_for_service "$FLASK_LOG" "Running on" "Flask Backend"; then
    log_info "Flask Backend started (PID: $FLASK_PID)"
    echo "  URL: http://localhost:$FLASK_PORT"
    echo "  Log: $FLASK_LOG"
  else
    log_error "Flask Backend failed to start"
    cat "$FLASK_LOG" | tail -20
    exit 1
  fi
fi

################################################################################
# 4. START NEXT.JS FRONTEND
################################################################################

if [ "$START_FRONTEND" = true ]; then
  log_section "Starting Next.js Frontend (Node.js)"
  
  # Clear old log
  > "$NEXTJS_LOG"
  
  # Check if frontend is built
  if [ ! -d "$PROJECT_ROOT/frontend/.next" ]; then
    log_warn "Next.js build not found, building..."
    cd "$PROJECT_ROOT/frontend"
    npm run build > /dev/null 2>&1 || {
      log_error "Next.js build failed"
      exit 1
    }
    log_info "Next.js built successfully"
    cd "$PROJECT_ROOT"
  fi
  
  # Start Next.js in production mode
  echo "Starting Next.js server on http://localhost:$NEXTJS_PORT..."
  cd "$PROJECT_ROOT/frontend"
  nohup npm start > "$NEXTJS_LOG" 2>&1 &
  NEXTJS_PID=$!
  cd "$PROJECT_ROOT"
  
  if wait_for_port "$NEXTJS_PORT" "Next.js Frontend"; then
    log_info "Next.js Frontend started (PID: $NEXTJS_PID)"
    echo "  URL: http://localhost:$NEXTJS_PORT"
    echo "  Log: $NEXTJS_LOG"
  else
    log_error "Next.js Frontend failed to start"
    cat "$NEXTJS_LOG" | tail -20
    exit 1
  fi
fi

################################################################################
# 5. START GRAPHIFY (OPTIONAL)
################################################################################

if [ "$START_GRAPHIFY" = true ]; then
  log_section "Starting Graphify (Knowledge Graph)"
  
  if command -v graphify &> /dev/null; then
    # Clear old log
    > "$GRAPHIFY_LOG"
    
    echo "Starting Graphify watch on current directory..."
    nohup graphify watch . > "$GRAPHIFY_LOG" 2>&1 &
    GRAPHIFY_PID=$!
    
    sleep 2
    if ps -p $GRAPHIFY_PID > /dev/null; then
      log_info "Graphify started (PID: $GRAPHIFY_PID)"
      echo "  Log: $GRAPHIFY_LOG"
    else
      log_warn "Graphify may have failed to start"
      tail -10 "$GRAPHIFY_LOG"
    fi
  else
    log_warn "Graphify not installed (optional)"
  fi
fi

################################################################################
# 6. SAVE PID FILE
################################################################################

cat > "$PID_FILE" << EOF
# Groww Trading System - Process IDs
# Generated: $(date)
# Stop all: ./start-all.sh --stop

FLASK_PID=${FLASK_PID:-}
NEXTJS_PID=${NEXTJS_PID:-}
GRAPHIFY_PID=${GRAPHIFY_PID:-}
EOF

################################################################################
# 7. SUMMARY & CLEANUP
################################################################################

log_section "✅ All Services Started Successfully!"

echo ""
echo "📊 Running Services:"
echo ""
if [ "$START_DASHBOARD" = true ]; then
  echo "  🐍 Flask Backend"
  echo "     URL: http://localhost:$FLASK_PORT"
  echo "     Log: tail -f $FLASK_LOG"
  echo ""
fi

if [ "$START_FRONTEND" = true ]; then
  echo "  ⚛️  Next.js Frontend"
  echo "     URL: http://localhost:$NEXTJS_PORT"
  echo "     Log: tail -f $NEXTJS_LOG"
  echo ""
fi

if [ "$START_GRAPHIFY" = true ] && [ -n "${GRAPHIFY_PID:-}" ]; then
  echo "  📊 Graphify Knowledge Graph"
  echo "     Log: tail -f $GRAPHIFY_LOG"
  echo ""
fi

echo "🛠️  Commands:"
echo "  Stop all:      ./start-all.sh --stop"
echo "  View logs:     tail -f server.log"
echo "  Restart:       pkill -f 'python3 app.py'; ./start-all.sh"
echo ""

echo "📝 PID File: $PID_FILE"
echo ""

# Setup cleanup on exit
cleanup() {
  echo ""
  log_section "Shutting Down..."
  
  [ -n "${FLASK_PID:-}" ] && kill_process "$FLASK_PID" "Flask Backend"
  [ -n "${NEXTJS_PID:-}" ] && kill_process "$NEXTJS_PID" "Next.js Frontend"
  [ -n "${GRAPHIFY_PID:-}" ] && kill_process "$GRAPHIFY_PID" "Graphify"
  
  rm -f "$PID_FILE"
  log_info "All services stopped"
  echo ""
}

# Trap signals for cleanup
trap cleanup SIGINT SIGTERM

# Keep script running
echo "Press Ctrl+C to stop all services..."
waitDE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --dashboard-only) START_FRONTEND=false; START_GRAPHIFY=false ;;
    --frontend-only) START_DASHBOARD=false; START_GRAPHIFY=false ;;
    --no-graphify) START_GRAPHIFY=false ;;
    --stop) STOP_MODE=true ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

################################################################################
# Helper Functions
################################################################################

log_section() {
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}$1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

log_info() {
  echo -e "${GREEN}✓${NC} $1"
}

log_error() {
  echo -e "${RED}✗${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}⚠${NC} $1"
}

log_status() {
  echo -e "${CYAN}ℹ${NC} $1"
}

# Kill process by PID and wait
kill_process() {
  local pid=$1
  local name=$2
  
  if kill -0 $pid 2>/dev/null; then
    echo -n "  Stopping $name (PID: $pid)... "
    kill -TERM $pid 2>/dev/null || true
    
    # Wait up to 5 seconds for graceful shutdown
    local count=0
    while kill -0 $pid 2>/dev/null && [ $count -lt 50 ]; do
      sleep 0.1
      count=$((count + 1))
    done
    
    # Force kill if still running
    if kill -0 $pid 2>/dev/null; then
      kill -9 $pid 2>/dev/null || true
    fi
    echo "done"
  fi
}

# Kill port by port number
kill_port() {
  local port=$1
  local pids=$(lsof -ti:$port 2>/dev/null || true)
  
  if [ -n "$pids" ]; then
    echo "Killing existing processes on port $port..."
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
}

# Check if port is available
wait_for_port() {
  local port=$1
  local name=$2
  local max_attempts=30
  local attempt=0
  
  echo -n "  Waiting for $name on port $port... "
  while [ $attempt -lt $max_attempts ]; do
    if nc -z localhost $port 2>/dev/null; then
      echo "ready!"
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  
  echo "timeout!"
  return 1
}

# Wait for service to start by checking log
wait_for_service() {
  local log_file=$1
  local pattern=$2
  local name=$3
  local max_attempts=30
  local attempt=0
  
  echo -n "  Checking $name... "
  while [ $attempt -lt $max_attempts ]; do
    if [ -f "$log_file" ] && grep -q "$pattern" "$log_file" 2>/dev/null; then
      echo "running!"
      return 0
    fi
    sleep 0.5
    attempt=$((attempt + 1))
  done
  
  echo "check logs"
  return 1
}

################################################################################
# STOP MODE
################################################################################

if [ "$STOP_MODE" = true ]; then
  log_section "Stopping All Services"
  
  if [ -f "$PID_FILE" ]; then
    # Read PIDs from file
    FLASK_PID=$(grep "FLASK_PID=" "$PID_FILE" | cut -d= -f2)
    NEXTJS_PID=$(grep "NEXTJS_PID=" "$PID_FILE" | cut -d= -f2)
    GRAPHIFY_PID=$(grep "GRAPHIFY_PID=" "$PID_FILE" | cut -d= -f2)
    
    [ -n "$FLASK_PID" ] && kill_process "$FLASK_PID" "Flask Backend"
    [ -n "$NEXTJS_PID" ] && kill_process "$NEXTJS_PID" "Next.js Frontend"
    [ -n "$GRAPHIFY_PID" ] && kill_process "$GRAPHIFY_PID" "Graphify"
    
    rm -f "$PID_FILE"
    log_info "All services stopped"
  else
    log_warn "No PID file found. Trying to kill by port..."
    kill_port 8000
    kill_port 3000
    log_info "Ports cleared"
  fi
  
  echo ""
  exit 0
fi

################################################################################
# STARTUP MODE
################################################################################

log_section "🚀 Groww Trading System - Initializing"

cd "$PROJECT_ROOT"

# Kill existing processes
log_status "Clearing existing processes..."
kill_port 8000
kill_port 3000

################################################################################
# 1. PYTHON VIRTUAL ENVIRONMENT
################################################################################

if [ "$START_DASHBOARD" = true ]; then
  log_section "Python Environment Setup"
  
  if [ ! -d ".venv" ]; then
    log_warn "Virtual environment not found, creating..."
    python3 -m venv .venv
    log_info "Virtual environment created"
  fi
  
  source .venv/bin/activate
  log_info "Virtual environment activated"
  
  # Install/update dependencies
  if [ -f "requirements.txt" ]; then
    log_status "Checking Python dependencies..."
    pip install -q -r requirements.txt 2>/dev/null || {
      log_error "Failed to install Python dependencies"
      exit 1
    }
    log_info "Python dependencies installed"
  fi
fi

################################################################################
# 2. NODE.JS / NEXT.JS ENVIRONMENT
################################################################################

if [ "$START_FRONTEND" = true ]; then
  log_section "Node.js Environment Setup"
  
  cd "$PROJECT_ROOT/frontend"
  
  # Check if node_modules exists, install if needed
  if [ ! -d "node_modules" ]; then
    log_warn "Node modules not found, installing..."
    npm install -q 2>/dev/null || {
      log_error "Failed to install Node.js dependencies"
      exit 1
    }
    log_info "Node.js dependencies installed"
  else
    log_info "Node.js dependencies found"
  fi
  
  cd "$PROJECT_ROOT"
fi

################################################################################
# 3. START FLASK BACKEND
################################################################################

if [ "$START_DASHBOARD" = true ]; then
  log_section "Starting Flask Backend (Python)"
  
  # Clear old log
  > "$FLASK_LOG"
  
  # Start Flask
  echo "Starting Flask server on http://localhost:$FLASK_PORT..."
  nohup .venv/bin/python3 app.py > "$FLASK_LOG" 2>&1 &
  FLASK_PID=$!
  
  if wait_for_service "$FLASK_LOG" "Running on" "Flask Backend"; then
    log_info "Flask Backend started (PID: $FLASK_PID)"
    echo "  URL: http://localhost:$FLASK_PORT"
    echo "  Log: $FLASK_LOG"
  else
    log_error "Flask Backend failed to start"
    cat "$FLASK_LOG" | tail -20
    exit 1
  fi
fi

################################################################################
# 4. START NEXT.JS FRONTEND
################################################################################

if [ "$START_FRONTEND" = true ]; then
  log_section "Starting Next.js Frontend (Node.js)"
  
  # Clear old log
  > "$NEXTJS_LOG"
  
  # Check if frontend is built
  if [ ! -d "$PROJECT_ROOT/frontend/.next" ]; then
    log_warn "Next.js build not found, building..."
    cd "$PROJECT_ROOT/frontend"
    npm run build > /dev/null 2>&1 || {
      log_error "Next.js build failed"
      exit 1
    }
    log_info "Next.js built successfully"
    cd "$PROJECT_ROOT"
  fi
  
  # Start Next.js in production mode
  echo "Starting Next.js server on http://localhost:$NEXTJS_PORT..."
  cd "$PROJECT_ROOT/frontend"
  nohup npm start > "$NEXTJS_LOG" 2>&1 &
  NEXTJS_PID=$!
  cd "$PROJECT_ROOT"
  
  if wait_for_port "$NEXTJS_PORT" "Next.js Frontend"; then
    log_info "Next.js Frontend started (PID: $NEXTJS_PID)"
    echo "  URL: http://localhost:$NEXTJS_PORT"
    echo "  Log: $NEXTJS_LOG"
  else
    log_error "Next.js Frontend failed to start"
    cat "$NEXTJS_LOG" | tail -20
    exit 1
  fi
fi

################################################################################
# 5. START GRAPHIFY (OPTIONAL)
################################################################################

if [ "$START_GRAPHIFY" = true ]; then
  log_section "Starting Graphify (Knowledge Graph)"
  
  if command -v graphify &> /dev/null; then
    # Clear old log
    > "$GRAPHIFY_LOG"
    
    echo "Starting Graphify watch on current directory..."
    nohup graphify watch . > "$GRAPHIFY_LOG" 2>&1 &
    GRAPHIFY_PID=$!
    
    sleep 2
    if ps -p $GRAPHIFY_PID > /dev/null; then
      log_info "Graphify started (PID: $GRAPHIFY_PID)"
      echo "  Log: $GRAPHIFY_LOG"
    else
      log_warn "Graphify may have failed to start"
      tail -10 "$GRAPHIFY_LOG"
    fi
  else
    log_warn "Graphify not installed (optional)"
  fi
fi

################################################################################
# 6. SAVE PID FILE
################################################################################

cat > "$PID_FILE" << EOF
# Groww Trading System - Process IDs
# Generated: $(date)
# Stop all: ./start-all.sh --stop

FLASK_PID=${FLASK_PID:-}
NEXTJS_PID=${NEXTJS_PID:-}
GRAPHIFY_PID=${GRAPHIFY_PID:-}
EOF

################################################################################
# 7. SUMMARY & CLEANUP
################################################################################

log_section "✅ All Services Started Successfully!"

echo ""
echo "📊 Running Services:"
echo ""
if [ "$START_DASHBOARD" = true ]; then
  echo "  🐍 Flask Backend"
  echo "     URL: http://localhost:$FLASK_PORT"
  echo "     Log: tail -f $FLASK_LOG"
  echo ""
fi

if [ "$START_FRONTEND" = true ]; then
  echo "  ⚛️  Next.js Frontend"
  echo "     URL: http://localhost:$NEXTJS_PORT"
  echo "     Log: tail -f $NEXTJS_LOG"
  echo ""
fi

if [ "$START_GRAPHIFY" = true ] && [ -n "${GRAPHIFY_PID:-}" ]; then
  echo "  📊 Graphify Knowledge Graph"
  echo "     Log: tail -f $GRAPHIFY_LOG"
  echo ""
fi

echo "🛠️  Commands:"
echo "  Stop all:      ./start-all.sh --stop"
echo "  View logs:     tail -f server.log"
echo "  Restart:       pkill -f 'python3 app.py'; ./start-all.sh"
echo ""

echo "📝 PID File: $PID_FILE"
echo ""

# Setup cleanup on exit
cleanup() {
  echo ""
  log_section "Shutting Down..."
  
  [ -n "${FLASK_PID:-}" ] && kill_process "$FLASK_PID" "Flask Backend"
  [ -n "${NEXTJS_PID:-}" ] && kill_process "$NEXTJS_PID" "Next.js Frontend"
  [ -n "${GRAPHIFY_PID:-}" ] && kill_process "$GRAPHIFY_PID" "Graphify"
  
  rm -f "$PID_FILE"
  log_info "All services stopped"
  echo ""
}

# Trap signals for cleanup
trap cleanup SIGINT SIGTERM

# Keep script running
echo "Press Ctrl+C to stop all services..."
wait
