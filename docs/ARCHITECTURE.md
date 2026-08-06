# 🏗️ Groww Trading System - Architecture

## System Overview

The Groww Trading System is a comprehensive, integrated platform consisting of **three core services** working together:

```
┌─────────────────────────────────────────────────────────────┐
│              Groww Trading System (Port 8000+3000)           │
└─────────────────────────────────────────────────────────────┘
         ↑                    ↓                    ↓
    Browser            HTTP/JSON            Knowledge
   (Port 3000)        Communication         Graph Index
                                           (Graphify)
```

---

## Service 1: Flask Backend 🐍

**Purpose:** Core business logic, API server, and data management

### Details
- **Language:** Python 3.8+
- **Framework:** Flask (Micro web framework)
- **Port:** 8000
- **Entry Point:** `app.py`
- **Environment:** `.venv/` (Python virtual environment)
- **Dependencies:** `requirements.txt`
- **Logs:** `server.log`

### Responsibilities
```
Flask Backend (app.py)
├── API Server
│   ├── REST endpoints for frontend
│   ├── Authentication & authorization
│   └── Data serialization (JSON)
├── Trading Logic
│   ├── Paper trading simulation
│   ├── Real market trading
│   ├── Order execution
│   └── Risk management
├── Data Management
│   ├── Portfolio tracking
│   ├── Trade journaling
│   ├── Holdings management
│   └── Transaction history
├── Analysis Engines
│   ├── Technical analysis (TA)
│   ├── Fundamental analysis
│   ├── Machine learning predictions
│   └── Market intelligence
├── Data Collection
│   ├── Price fetching
│   ├── News aggregation
│   ├── Sentiment analysis
│   └── Commodity tracking
├── External Integrations
│   ├── Groww API (stock data)
│   ├── News APIs (sentiment)
│   ├── Telegram alerts
│   └── Database (SQLite)
└── Utilities
    ├── Caching (prices, charts)
    ├── Scheduling (periodic tasks)
    └── Token management
```

### Key Modules
| Module | Purpose |
|--------|---------|
| `app.py` | Main Flask application & routes |
| `bot.py` | Trading bot implementation |
| `paper_trader.py` | Paper trading engine |
| `fno_trader.py` | Futures & Options trader |
| `db_manager.py` | Database operations |
| `price_fetcher.py` | Real-time price data |
| `portfolio_analyzer.py` | Portfolio analysis |
| `market_intelligence.py` | Market signals |
| `news_sentiment.py` | News analysis |
| `trade_journal.py` | Trade tracking |
| `auth_manager.py` | Authentication |
| `telegram_alerts.py` | Notifications |

### Startup
```bash
./start-all.sh                    # Starts Flask backend
./start-all.sh --dashboard-only   # Flask only
```

### Access
- **URL:** http://localhost:8000
- **API Base:** http://localhost:8000/api
- **Health:** http://localhost:8000/health

---

## Service 2: Next.js Frontend ⚛️

**Purpose:** Web UI, data visualization, user interaction

### Details
- **Language:** JavaScript/TypeScript
- **Framework:** Next.js 14+ (React framework)
- **Port:** 3000
- **Directory:** `frontend/`
- **Dependencies:** `frontend/package.json`
- **Build Output:** `frontend/.next/`
- **Logs:** `frontend/nextjs.log`

### Responsibilities
```
Next.js Frontend (frontend/)
├── User Interface
│   ├── Dashboard layout
│   ├── Navigation
│   ├── Forms & inputs
│   └── Modal dialogs
├── Pages
│   ├── Dashboard (home)
│   ├── Portfolio view
│   ├── Trade history
│   ├── Market analysis
│   ├── Settings
│   └── Authentication
├── Components
│   ├── Stock tables
│   ├── Chart displays
│   ├── Price tickers
│   ├── Portfolio summaries
│   ├── Trade forms
│   └── Navigation bars
├── Real-time Updates
│   ├── WebSocket connections
│   ├── Live price updates
│   ├── Portfolio refreshes
│   └── Trade notifications
├── Data Visualization
│   ├── Candlestick charts
│   ├── Technical indicators
│   ├── Portfolio charts
│   ├── Performance graphs
│   └── Market heatmaps
├── API Integration
│   ├── Fetch data from Flask
│   ├── Send trade requests
│   ├── User authentication
│   └── Settings management
└── Utilities
    ├── State management (React hooks)
    ├── Local storage
    ├── Error handling
    └── Loading states
```

### Directory Structure
```
frontend/
├── app/                    # Next.js app directory
│   ├── layout.tsx         # Root layout
│   ├── page.tsx           # Home page
│   ├── dashboard/         # Dashboard routes
│   ├── portfolio/         # Portfolio routes
│   ├── trades/            # Trade history routes
│   └── api/               # Route handlers
├── components/             # React components
│   ├── Header.tsx
│   ├── Navigation.tsx
│   ├── StockTable.tsx
│   ├── ChartView.tsx
│   └── ...
├── pages/                  # Next.js pages (legacy)
├── public/                 # Static assets
│   ├── icons/
│   ├── images/
│   └── fonts/
├── styles/                 # CSS/SCSS
├── hooks/                  # Custom React hooks
├── lib/                    # Utility functions
├── types/                  # TypeScript types
├── package.json            # Dependencies
├── next.config.js          # Next.js configuration
├── tsconfig.json           # TypeScript configuration
└── .next/                  # Build output (generated)
```

### Startup
```bash
./start-all.sh                    # Starts Next.js frontend
./start-all.sh --frontend-only    # Next.js only
```

### Access
- **URL:** http://localhost:3000
- **Dev Mode:** `cd frontend && npm run dev` (with hot reload)
- **Production:** `npm start` (served from .next/)

---

## Service 3: Graphify Knowledge Graph 📊

**Purpose:** Real-time code indexing, semantic search, architecture analysis

### Details
- **Type:** Code Analysis & Documentation
- **Command:** `graphify watch .`
- **Language:** Detects all languages (Python, JS, TS, Markdown)
- **Output:** `graphify-out/`
- **Logs:** `graphify.log`

### Responsibilities
```
Graphify (Knowledge Graph)
├── Code Indexing
│   ├── Parse all Python files
│   ├── Parse all JavaScript/TypeScript
│   ├── Extract function definitions
│   ├── Extract class definitions
│   ├── Extract imports & dependencies
│   └── Map relationships
├── Semantic Understanding
│   ├── Understand code semantics
│   ├── Build dependency graphs
│   ├── Identify code clusters
│   ├── Detect patterns
│   └── Understand architecture
├── Knowledge Graph
│   ├── Node: Files
│   ├── Node: Functions/Classes
│   ├── Node: Modules
│   ├── Edge: Dependencies
│   ├── Edge: Imports
│   └── Edge: Relationships
├── File Watching
│   ├── Monitor for changes
│   ├── Update on file save
│   ├── Reindex modified files
│   ├── Track deletions
│   └── Real-time updates
└── Output
    ├── JSON graph representation
    ├── HTML visualization
    ├── Search index
    ├── Community detection
    └── Architecture diagrams
```

### Watches
- `*.py` - Flask backend code
- `app/*` - Main application code
- `frontend/app/*` - Frontend components
- `frontend/components/*` - React components
- `*.md` - Documentation files

### Ignores
- `.venv/` - Python dependencies
- `node_modules/` - Node dependencies
- `.git/` - Git metadata
- `__pycache__/` - Python cache
- `.next/` - Next.js build
- `chart_cache/` - Chart cache
- `archive/` - Archive files

### Startup
```bash
./start-all.sh                    # Starts Graphify
./start-all.sh --no-graphify      # Skip Graphify
```

### Output
- **Directory:** `graphify-out/`
- **Files:**
  - `.graphify_detect.json` - Language detection
  - `.graphify_chunks.json` - Code chunks
  - `.graphify_chunk_*.json` - Individual chunks
  - `.graphify_python` - Python analysis
- **Logs:** `graphify.log`

---

## How They Work Together

### Data Flow

```
User Browser (Port 3000)
    │
    ├─→ HTTP Request
    │
    ↓
Next.js Frontend
    │
    ├─→ Processes UI
    ├─→ Makes API calls
    │
    ↓
HTTP/JSON over localhost:8000
    │
    ↓
Flask Backend
    │
    ├─→ Routes request
    ├─→ Executes business logic
    ├─→ Queries database
    ├─→ Fetches live data
    │
    ↓
Response (JSON)
    │
    ↓
Next.js Frontend
    │
    ├─→ Updates state
    ├─→ Re-renders UI
    │
    ↓
User Browser (Updated Display)
```

### Communication Layers

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Presentation** | React Components | UI rendering |
| **Framework** | Next.js | Page routing, SSR |
| **API Client** | fetch/axios | HTTP requests |
| **Network** | HTTP/JSON | Inter-service communication |
| **API Server** | Flask | Request handling |
| **Business Logic** | Python modules | Trading, analysis, data |
| **Persistence** | SQLite | Data storage |

---

## System Architecture Patterns

### REST API Pattern
```
Frontend                Backend
   │                       │
   ├─ GET /api/portfolio ─→│
   │                       ├─ Query database
   │                       ├─ Fetch prices
   │←─ JSON response ──────┤
   │                       │
```

### Real-time Updates
```
Backend             Graphify
   │                   │
   ├─ Monitor files ───→│
   │                    ├─ Index code
   │                    ├─ Build graph
   │←─ Update graph ────┤
   │                    │
```

---

## Deployment & Scaling

### Current (Single Machine)
- All 3 services on localhost
- Ports: 8000 (Flask), 3000 (Next.js), N/A (Graphify)
- One database instance
- One Python environment
- One Node.js environment

### Startup Method
```bash
./start-all.sh
```

Starts all three services in background, with Ctrl+C cleanup.

---

## Technology Stack Summary

| Aspect | Technology | Version |
|--------|-----------|---------|
| **Backend Framework** | Flask | 2.x+ |
| **Backend Language** | Python | 3.8+ |
| **Frontend Framework** | Next.js | 14+ |
| **Frontend Language** | JavaScript/TypeScript | ES2020+ |
| **UI Library** | React | 18+ |
| **Database** | SQLite | 3.x |
| **Code Analysis** | Graphify | Latest |
| **Process Manager** | Bash/Shell | zsh/bash |

---

## Configuration Files

### Core Config
- `.graphifyignore` - Patterns Graphify should ignore
- `frontend/package.json` - Frontend dependencies
- `requirements.txt` - Backend dependencies
- `.env` - Environment variables (optional)

### Build Files
- `frontend/next.config.js` - Next.js build config
- `frontend/tsconfig.json` - TypeScript config
- `frontend/tailwind.config.js` - Styling config

### Startup Scripts
- `start-all.sh` - Main orchestrator
- `stop-all.sh` - Service cleanup
- `status.sh` - Health monitor

---

## Key Design Decisions

### 1. Monolithic Backend
- Single Flask server handles all business logic
- Simpler deployment and debugging
- Easier to manage state

### 2. Separate Frontend
- Independent Next.js app for better UX
- Can be deployed separately
- Hot reload in development

### 3. Local Knowledge Graph
- Graphify watches local files
- Indexes all code in real-time
- Helps understand system architecture

### 4. REST API Communication
- Simple HTTP/JSON between services
- Stateless API design
- Easy debugging with browser dev tools

### 5. SQLite Database
- Single file database
- No separate DB server needed
- Portable and easy to backup

---

## Summary

The Groww Trading System is a **three-service architecture**:

1. **Flask Backend** (🐍 Python) - Business logic & APIs
2. **Next.js Frontend** (⚛️ React) - Web UI & visualization
3. **Graphify** (📊 Analysis) - Code indexing & understanding

All three services are **managed by a single startup script** (`start-all.sh`), work together seamlessly, and can be individually controlled with command-line options.

---

**Updated:** April 2026
**Compatibility:** macOS, Linux
