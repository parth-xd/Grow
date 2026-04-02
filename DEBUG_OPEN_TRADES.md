# Debug Guide: Why OPEN Trades Don't Show P&L Data

## Quick Diagnosis

To see live P&L data for OPEN trades, follow these steps:

### Step 1: Verify Flask Server is Running
```bash
ps aux | grep "python.*app.py" | grep -v grep
```

If nothing shows, the server isn't running. Start it:
```bash
cd /Users/parthsharma/Desktop/Grow
.venv/bin/python3 app.py
```

### Step 2: Check Browser Console
1. Open your dashboard in browser
2. Press `F12` to open Developer Tools
3. Go to **Console** tab
4. Click **Refresh** button on dashboard
5. Look for messages like:
   - `Getting live prices for OPEN trades: ['TCS', 'INFY', 'ICICIBANK']`
   - `Fetching from /api/live-prices...`
   - `Batch fetch successful, prices: {TCS: 2411.50, ...}`

### Step 3: Test API Directly
```bash
curl -s -X POST http://localhost:5000/api/live-prices \
  -H "Content-Type: application/json" \
  -d '{"symbols":["TCS","INFY","ICICIBANK"]}'
```

Expected response:
```json
{"prices": {"TCS": 2411.50, "INFY": 1278.75, "ICICIBANK": 1213.20}}
```

---

## Expected Behavior

### For OPEN Trades with Live Prices:
```
Invested: ₹2411.00
Current: ₹2393.16
P&L: -₹17.84 (-0.74%)
```

### For OPEN Trades WITHOUT Live Prices:
```
-
```

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| All OPEN trades show `-` in P&L | Flask server not running OR API failing | Start server: `.venv/bin/python3 app.py` |
| Console shows "Batch fetch failed" | Server connection issue | Check if Flask is listening on localhost:5000 |
| Prices fetched but P&L still shows `-` | Bug in display logic | Check browser console for JavaScript errors |
| Some symbols fetch, others show `-` | Individual symbol fetch failing | Check if symbols are tradeable on Groww |

---

## Debug Console Messages

When working correctly, you should see:
```
Getting live prices for OPEN trades: ['TCS', 'INFY', 'ICICIBANK'] (3 trades)
getLivePrices called with: ['TCS', 'INFY', 'ICICIBANK']
Fetching from /api/live-prices...
Batch fetch successful, prices: {TCS: 2411.50, INFY: 1278.75, ICICIBANK: 1213.20}
Live prices received: {TCS: 2411.50, INFY: 1278.75, ICICIBANK: 1213.20}
```

---

## Verify Trades Data

Check if trades are being loaded:
```javascript
// Run this in browser console:
fetch('paper_trades.json')
  .then(r => r.json())
  .then(trades => {
    const open = trades.filter(t => t.status === 'OPEN');
    console.log('OPEN trades:', open);
    console.log('Symbols:', open.map(t => t.symbol));
  });
```

---

## More Info

- **API Endpoint (Batch)**: `POST /api/live-prices` → Returns `{prices: {...}}`
- **API Endpoint (Single)**: `GET /api/price/<symbol>` → Returns `{price: X.XX, symbol: 'TCS'}`
- **Data Source**: `paper_trader.get_live_price()` → Fetches 1-min candles from Groww API
- **Refresh Rate**: Dashboard auto-refreshes every 5 seconds
