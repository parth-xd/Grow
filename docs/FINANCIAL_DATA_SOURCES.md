# Financial Data Sources — Dashboard Deep Dive

## WHERE YOUR CURRENT DATA COMES FROM (Before Tijori)

### 1. **Screener.in** (Public web scraping)
**What:** The backbone of your fundamentals module. Publicly available financial statements.

**Data extracted:**
- **Key Ratios:** PE, PB, ROE, ROCE, Debt/Equity, Promoter holding %, Dividend yield
- **Trends:** Revenue (last 5 years), Net profit (last 5 years), EPS
- **Position:** 52-week high/low, current price position %
- **Cash Flow:** Operating cash flow, Free cash flow
- **Growth rates:** YoY revenue growth, profit growth

**Refreshed:** When `/api/fundamentals/<symbol>` is called (cached 6 hours)

**Problem with this source (why "dicey" before):**
- Only refreshes when explicitly requested via API call
- No automatic daily/weekly collection
- When you open "fundamentals" on a stock, it scrapes fresh (adds latency to dashboard)
- No version history — you only see current values, not changes
- If Screener.in changes their website format, scraper breaks silently

**Where used:**
- `/api/fundamentals/<symbol>` endpoint → Dashboard "Fundamentals" tab
- `deep_analysis.py` pulls it for View Analysis narrative
- `research_engine.py` uses it for scoring

---

### 2. **Groww API** (Your brokerage account)
**What:** Live quote data and your portfolio holdings.

**Data extracted:**
- **Quote:** LTP (last traded price), open, high, low, volume, avg volume
- **Volume spike detection:** Volume ratio vs average
- **Portfolio:** Holdings list, quantity, entry price, P&L
- **Circuit limits:** Upper/lower circuit breakers

**Problem with this source:**
- Groww API currently returning "Access forbidden" (auth issue)
- Only gives you YOUR holdings, not peer/competitor fundamentals
- No supply chain or supplier/customer data

**Where used:**
- `portfolio_analyzer.py` fetches holdings
- Quote endpoints return real-time prices
- P&L calculations

---

### 3. **Hardcoded sector/competitor mappings** (Fallback)
**What:** When DB lookups fail, falls back to hardcoded competitor lists.

**Problem:**
- Stale — only 20-30 companies listed
- Not scalable — new competitors in your watchlist = no peer comparison
- Competitors list never updates even if market changes

**Example:**
```python
_FALLBACK_COMPETITORS = {
    "ASIANPAINT": ["BERGEPAINT", "NEROLAC", "INDIGO", "AKZONOBEL"],
    "RELIANCE": ["TCS", "INFY", "HDFCBANK", "ICICIBANK"],  # ← these aren't competitors!
}
```

---

## WHAT'S MISSING / THE "DICEY" PROBLEM

### ❌ **No supplier/customer visibility**
You analyze a stock like RELIANCE in isolation. You don't know:
- Its 67 suppliers and their health
- Who buys from it (customers)
- If key suppliers are struggling (early signal for supply chain disruption)

### ❌ **No forensic accounting checks**
Screener.in ratios are surface-level. You don't see:
- "Is depreciation being played with to inflate profits?" (6 red flags on RELIANCE)
- "Are promoters pledging their shares?" (financial distress signal)
- "Is profit actually converting to cash, or is it accounting magic?"
- "Is the company paying its suppliers?" (balance sheet strength check)

### ❌ **No competitor list updates**
Your peer comparison is static. When a new competitor enters the market or a competitor pivots, your analysis doesn't know.

### ❌ **No change tracking**
You see PE = 55.3 today. But you have no idea:
- Was it 50 last month? (improving valuation)
- Was it 60? (deteriorating)
- Did a forensic check flip from green to red?

---

## WHAT TIJORI NOW PROVIDES (Starting today)

### ✅ **Company supply chain graph**
- **Suppliers:** 67 for RELIANCE, automatically resolved to NSE symbols
- **Customers:** Companies that buy from this one
- **Competitors:** Automatically pulled from Tijori's peer table

**Data persisted in:**
- `company_connections` table (who supplies whom, when relationship started/ended)
- Each connection tracked with `is_active` flag (detects when a supplier is dropped)

**Example:**
```
RELIANCE → suppliers:
  • AEGIS LOGISTICS (AEGISLOG) — 6m return: +83.3%
  • WELSPUN CORP (WELCORP) — 6m return: +124.1%
  • DEEPAK NITRITE (DEEPAKNTR) — 6m return: +4.4%
  
Health: STRONG (avg +70.6% over 6 months)
```

**Why this matters for trading:**
- If multiple suppliers start declining simultaneously = demand risk signal before revenue reports
- If a customer (e.g., Asian Paints for chemical suppliers) struggles = early demand signal
- Promoter of key supplier pledges shares = supply chain credit risk

---

### ✅ **Forensic accounting checks (17 total)**
Tijori's "quick_look" module analyzes:

**Positive checks (green flags):**
- Contingent liabilities aren't exploding (no black swan)
- Profits are converting to cash (not accounting magic)
- Depreciation accounting is normal (not inflating profits)
- Promoter hasn't dumped shares recently

**Red flags (caution signs):**
- "Company is depreciating lower percentage of assets — boosting profit artificially" (RELIANCE: flagged)
- "Retail has been buying heavily — usually marks exuberance" (RELIANCE: flagged)
- "ROE declining vs 10-year trend" (RELIANCE: flagged)
- "ROCE not consistently strong"

**Stored in:**
- `company_external_data` table (forensics snapshot every time we refresh)
- Comparison: this week vs last week shows forensic check flips

**Why this matters:**
- Catches companies using accounting tricks (before earnings miss shows up)
- Detects when retail enthusiasm peaks (historically a reversal signal)
- Tracks consistency of returns (strong ROCE that suddenly dips = warning)

---

### ✅ **Performance returns (all timeframes)**
Tijori captures returns for every company and partner:

**Data captured:**
- 1d, 1m, 6m, YTD, 1y, 3y, 5y, 10y, max returns
- Also captured for every supplier/customer's stock

**Example (from RELIANCE test):**
```
Returns: {
  "1d": 1.15%,
  "1m": -0.02%,
  "6m": -2.91%,  ← NEGATIVE (market weakness)
  "1y": -6.16%,
  "3y": 4.07%,   ← POSITIVE (long-term trend intact)
  "10y": 423.11% ← STRONG historical performer
}
```

**Why this matters:**
- 6m return = short-term trend (overbought/oversold check)
- 1y return = medium-term momentum (algo weight consideration)
- 10y return = quality check (has it been performing historically?)
- **Partner returns rolling up into health score** = supply chain momentum signal

---

### ✅ **Market share tracking (over time)**
Tijori tracks each company's market share in their key segments:

**Example (from RELIANCE test):**
```
Decorative Paints market share: 60% (Asian Paints)
Automotive Coatings: 20%
```

**Stored as:**
- Snapshots in `company_external_data` table (data_type = "market_share")
- Each refresh captures current position

**Why this matters:**
- Market share gains = pricing power increasing
- Market share loss = competition intensifying (early signal before profit margin compresses)

---

### ✅ **Corporate actions (dividends, splits, bonuses)**
- Tracking when dividends are announced and their amounts
- Bonus/split announcements = momentum shifts historically

---

## HOW THE DATA FLOWS NOW (ARCHITECTURE)

```
Your Dashboard (watchlist/portfolio)
         ↓
    New Stock Added
         ↓
    Background Job:
    ├─ Fetch 5yr price history (price_fetcher.py)
    ├─ Collect peer comparison (market_intelligence.py)
    ├─ Collect Tijori data (tijori_collector.py) ← NEW
    │   ├─ Resolve slug (company name → Tijori page)
    │   ├─ Parse all 7 data blocks
    │   ├─ Store snapshots (company_external_data)
    │   └─ Store connections (company_connections)
    └─ Done
         ↓
    Every 6 hours:
    ├─ Scheduler checks which symbols have stale Tijori data (>7 days old)
    ├─ Refreshes top 10 stale symbols per run
    ├─ Resolves supplier/customer names → NSE symbols (batch pass)
    └─ Stores their performance data too
         ↓
    View Analysis (deep_analysis.py):
    ├─ Commodity impact ✓
    ├─ Geopolitical risk ✓
    ├─ News flow ✓
    ├─ Fundamentals ✓
    └─ Supply Chain ← NEW
       ├─ Suppliers + health score
       ├─ Forensic accounting checks
       ├─ Recent changes (ratio drift, forensic flips)
       └─ Impact: risk_level, overall_sentiment
```

---

## DATA QUALITY COMPARISON: BEFORE vs NOW

| Aspect | Before | Now |
|--------|--------|-----|
| **Fundamentals** | Fresh when requested, stale otherwise | Auto-refreshed weekly for all 67 stocks |
| **Supplier health** | None | 67 suppliers tracked, health scored |
| **Accounting forensics** | None | 17 checks, red flags highlighted |
| **Competitor data** | Hardcoded, stale | Auto-pulled from Tijori peer table |
| **Version history** | None (only current values) | Full snapshots stored (compare week-to-week) |
| **Market share** | None | Tracked over time per segment |
| **Change detection** | None | Automatic: ratio moves >5%, forensic flips |
| **Fallback on failure** | Hardcoded fallback, no transparency | Last-known-good snapshot never deleted |
| **Supply chain signals** | None | Supplier/customer removals flagged |

---

## CONFIGURATION (All in config_settings table)

Everything is configurable without code changes:

```
tijori.enabled                          = "true"
tijori.base_url                         = "https://www.tijorifinance.com"
tijori.refresh_interval_days            = "7"          # how often to refresh per stock
tijori.request_delay_seconds            = "2"          # politeness
tijori.timeout_seconds                  = "15"
tijori.max_symbols_per_run              = "10"         # batch size per scheduler pass
tijori.max_slug_resolutions_per_run     = "20"         # batch size for name→symbol resolution
tijori.user_agent                       = "Mozilla/5.0..."
```

Change any setting via `/api/config/<key>` endpoint and next scheduler run respects it.

---

## USAGE EXAMPLES FOR TRADERS

### **Example 1: Supply Chain Risk Check**
```
Analyst opens View Analysis for RELIANCE
Sees: "Supply-chain health: STRONG (listed partners avg +70.6% / 6m)"
+ 3 key suppliers identified and tracked
+ No recent supplier removals
→ Action: This is a tailwind (low supply chain risk)
```

### **Example 2: Forensic Red Flag Detection**
```
Analyst opens View Analysis for RELIANCE
Sees forensics section: "6 red flags"
⚠ Depreciation being played with to boost profit
⚠ Retail buying heavily (exuberance signal)
⚠ ROE declining vs 10-year trend
→ Action: Be cautious even if chart looks bullish
```

### **Example 3: Peer Comparison with Live Data**
```
Analyst adds a new competitor (e.g., JSWSTEEL)
System auto-fetches Tijori page:
- Pulls 15+ peer metrics in real-time
- Ranks JSWSTEEL vs peers (1st in ROCE, 8th in PE)
- Stores peer names for future correlation analysis
→ Much more reliable than hardcoded competitor lists
```

### **Example 4: Supply Chain Momentum**
```
Analyst sees: "Deepak Nitrite (supplier) returned +4.4% / 6m"
While: "Welspun Corp (supplier) returned +124.1% / 6m"
+ RELIANCE itself returned -2.91% / 6m
→ Insight: Supply chain is robust but buying from RELIANCE is weak?
→ Action: Check if RELIANCE is losing market share
```

---

## NEXT STEPS (Optional, When You're Ready)

1. **Assign small weight to supply-chain health in the algo** 
   - Currently it only affects risk narrative + manual trader judgment
   - Could add 1-2% weight to the 5-second trade signal (after we gather a few weeks of snapshots to build confidence)
   - This is a config setting — zero code change

2. **Add supplier credit-check automation**
   - Flag when a supplier's promoter pledges shares (financial distress)
   - Auto-notify: "Supplier Atul Ltd's promoter just pledged 30% of holdings"

3. **Sector momentum rollup**
   - Aggregate health scores by sector (e.g., "Paints sector suppliers: STRONG")
   - Use as macro context for algo

4. **Deep-link to Tijori**
   - Dashboard "View Analysis" button includes link: "See on Tijori →"
   - Traders can drill into full Tijori report for deeper due diligence

---

## BACKFILL STATUS

Running now in background: `tijori_backfill.py` is collecting all 67 stocks.

Progress: Check with `tail -f tijori_backfill.log`

ETA: ~2-3 hours for all 67 stocks (2 sec politeness delay per request).

Once done:
- All symbols will have baseline data
- Supplier/customer resolution pass will begin (3 more passes to maximize resolved symbols)
- From then on, scheduler keeps everything fresh (every 7 days per stock, ~10 stocks per 6-hour cycle)
