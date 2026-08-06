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
├── Data Pipelines
│   ├── Commodity snapshot refresh
│   ├── Supply-chain disruption scoring
│   ├── Screener-based metadata refresh
│   └── Trailing-stop + paper-trade sync
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
| `commodity_tracker.py` | Commodity pricing and stock-commodity mapping |
| `supply_chain_collector.py` | Commodity disruption scoring and persistence |
| `tijori_collector.py` | Company supply-chain graph: suppliers, customers, peers, ratios, forensics, market share |
| `deep_analysis.py` | Narrative "why is this moving" analysis per stock |
| `auto_metadata.py` | Screener.in metadata + peer discovery |
| `trailing_stop.py` | Breakeven and trailing-stop logic |
| `price_fetcher.py` | Real-time price data |
| `portfolio_analyzer.py` | Portfolio analysis |
| `market_intelligence.py` | Market signals |
| `news_sentiment.py` | News analysis |
| `trade_journal.py` | Trade tracking |
| `auth_manager.py` | Authentication |
| `telegram_alerts.py` | Notifications |

### Supply-Chain Intelligence Flow

Company-level supply-chain data (who supplies a company, who buys from it, how
those partners are performing) flows through one collector and one read API:

```
tijori_collector.collect_for_symbol(symbol)
  ├─ resolve_slug()            name → verified source URL (cached in external_slug_map)
  ├─ parse_company_page()      7 independent blocks; one failing doesn't block the rest
  ├─ _store_snapshots()        append-only rows in company_external_data
  └─ _store_connections()      supplier/customer/competitor rows in company_connections

tijori_collector.resolve_pending_connections()
  └─ partner company name → NSE symbol, so partner performance can be tracked

tijori_collector.get_supply_chain_intel(symbol)   ← single read API, 3 queries
  ├─ active + recently-removed connections
  ├─ _load_snapshots_bulk()    ONE query covering the company AND every partner
  ├─ per-partner enrichment    returns ladder, PE/ROE/ROCE/mcap, forensic counts
  ├─ _compute_health()         weighted partner 6-month performance → STRONG/MIXED/WEAK
  └─ _impact_narrative()       plain-English read on effect on the principal company
```

**Consumers** (all three surface the same block via `renderSupplyChainBlock`):

| Surface | Endpoint |
|---|---|
| Watchlist → View Analysis | `GET /api/watchlist/<symbol>/analysis` → `supply_chain` |
| Portfolio Analysis → expand holding | `GET /api/supply-chain-intel/<symbol>` (lazy) |
| Deep Analysis | `GET /api/deep-analysis/<symbol>` → `sections.supply_chain` + `supply_chain` |

**Refresh:** the `tijori_refresh` scheduler task (6h) re-collects symbols older
than `tijori.refresh_interval_days` and resolves pending partner names. New
quarterly results detected by `_detect_new_quarter` mark a symbol stale so fresh
numbers flow in within hours. All behaviour is config-driven via `tijori.*` keys
in `config_settings` — nothing is hardcoded.

### Performance Notes

- **`get_config` is memoized** (30s TTL, write-through invalidation). Hot loops
  should use `get_configs()` / `get_configs_prefix()` for a single batched read.
- **Snapshot reads are batched.** `_load_snapshots_bulk` replaced per-partner
  queries; `get_supply_chain_intel` went from `7 + 3P` queries (151 for 48
  partners) to a flat **3**.
- **Independent providers run concurrently.** `_do_watchlist_analysis` fans out
  its six providers (fundamentals, annual financials, FII, commodity,
  geopolitical, news) across a `ThreadPoolExecutor` rather than paying the sum
  of their network latencies. `news_sentiment.get_news_sentiment` does the same
  across its six sources.
- **Existing concurrency idioms to match:** `research_engine.py` (7 loaders,
  `max_workers=6`), `fno_trader.py` (yfinance fan-out), `deep_analysis.py`
  (per-symbol executor).

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

## REST API Endpoints (Flask Backend)

### Authentication
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/signup` | POST | Create new user account |
| `/api/auth/login` | POST | Authenticate user |
| `/api/auth/verify` | GET | Verify token validity |
| `/api/auth/profile` | GET | Get user profile data |
| `/api/auth/set-api-key` | POST | Set Groww API credentials |
| `/api/auth/demo` | POST | Create demo account |

### Trading - Basic
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/buy` | POST | Place buy order (real or paper) |
| `/api/sell` | POST | Place sell order (real or paper) |
| `/api/auto-trade` | POST | Execute auto-trade scan |
| `/api/close-trade/<trade_id>` | POST | Close open trade |
| `/api/monitor-trailing-stops` | POST | Check & execute trailing stops |
| `/api/journal/stats` | GET | Trade statistics summary |

### Trading - Intraday Paper
| Endpoint | Method | Purpose | NEW |
|----------|--------|---------|-----|
| `/api/intraday/enter-paper` | POST | Enter intraday paper trade | ✅ |
| `/api/intraday/close-paper` | POST | Close intraday paper trade | ✅ |
| `/api/intraday/auto-trade-run-paper` | POST | Run auto-trade in paper mode | ✅ |

### Authentication & Setup
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/signup` | POST | Create a new user |
| `/api/auth/login` | POST | Authenticate user |
| `/api/auth/demo` | POST | Create a demo account |
| `/api/auth/set-api-key` | POST | Store Groww API credentials |

### Trading - F&O (Futures & Options)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/fno/dashboard` | GET | F&O trading status |
| `/api/fno/positions` | GET | Current F&O positions |
| `/api/fno/buy` | POST | Buy F&O contract |
| `/api/fno/sell` | POST | Sell F&O contract |
| `/api/fno/margin` | GET | Available margin |
| `/api/fno/global-indices` | GET | Market context indices |

### Predictions & Analysis
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/predict/<symbol>` | GET | Get ML prediction for symbol |
| `/api/scan` | GET | Scan watchlist for signals |
| `/api/train/<symbol>` | POST | Retrain ML model for symbol |
| `/api/portfolio-analysis` | GET | Analyze current portfolio |
| `/api/deep-analysis/<symbol>` | GET | Deep analysis of stock |

### Trade Journal & History
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/journal` | GET | Get all trade journal entries |
| `/api/journal/stats` | GET | Trade statistics (win rate, P&L, etc.) |
| `/api/journal/open` | GET | Get open trades |
| `/api/journal/closed` | GET | Get closed trades |
| `/api/journal/<trade_id>/close` | POST | Close & generate post-trade report |

### Watchlist Management
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/watchlist` | GET | Get current watchlist |
| `/api/watchlist/add` | POST | Add symbol to watchlist |
| `/api/watchlist/remove` | POST | Remove symbol from watchlist |
| `/api/watchlist/sync` | POST | Sync with Groww holdings |

### Scheduler & Settings
| Endpoint | Method | Purpose | NEW |
|----------|--------|---------|-----|
| `/api/scheduler/settings` | GET | Get all scheduler task intervals | ✅ |
| `/api/scheduler/settings` | POST | Update scheduler task intervals | ✅ |
| `/api/auto-trade/config` | GET | Get auto-trade configuration |
| `/api/auto-trade/config` | POST | Update auto-trade configuration |

### Commodity & Supply Chain
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/raw-materials` | GET | Commodity dashboard with price/news context |
| `/api/raw-materials/supply-chain` | GET | Supply-chain heatmap data |
| `/api/supply-chain/refresh` | POST | Trigger a live commodity refresh |

### Metadata & Research
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/metadata/status` | GET | Show metadata coverage |
| `/api/metadata/refresh` | POST | Refresh all stock metadata |
| `/api/metadata/<symbol>/refresh` | POST | Refresh one symbol |
| `/api/research/<symbol>` | GET | Generate a research report |

### Market Data
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/quote/<symbol>` | GET | Real-time stock quote |
| `/api/candles/<symbol>` | GET | Historical candle data |
| `/api/news/<symbol>` | GET | Latest news for stock |
| `/api/fno/global-indices` | GET | Global market indices |

### Backtesting
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/backtest/run` | POST | Run backtest for symbol |
| `/api/backtest/multi` | POST | Multi-symbol backtest |
| `/api/backtest/results/<id>` | GET | Get backtest results |

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
