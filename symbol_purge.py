"""
Symbol purge — everything the system holds *about* a stock, removed in one
transaction when the stock leaves the watchlist.

Why this exists: "Remove from watchlist" deleted price rows and nothing else.
The `stocks` row stayed active, so the scan, the research batch, Tijori and
FYERS kept working on a symbol with no data — six such ghosts were found on
2026-09-12 (VODAFONEIDEA, NEROLAC, TATAMOTORS, AKZONOBEL, JSWEN, LTI), each
costing failed FYERS lookups every scan and a "HOLD — no historical data" row
on the dashboard. Membership and cleanup now happen in one place.

What is deleted: data ABOUT the stock — prices and candles, fundamentals,
Tijori snapshots and slug cache, shareholding, peers, news fetched for it,
predictions, notes, cached analyses, its model files, and the `stocks` row.

What is kept, on purpose, and reported back:
  - records of what HAPPENED (trade_journal, paper_trades, trade_log,
    trade_snapshots): financial history is never deleted by a UI action;
  - what the USER WROTE (theses, stock_theses);
  - the exchange universe (master_ticker_table, nse_instruments);
  - other companies' supply-chain rows that merely name this stock as their
    partner (company_connections.related_symbol) — that is their data.

Safety net: every table with a symbol-like column is checked at purge time.
One that is in neither list is NOT touched, and its row count is reported
under `unclassified`, so a new table can never be silently skipped.

Refuses when the stock has an OPEN paper position: closing it is a money
action and belongs to the trade flow, not to a watchlist button.
"""
import glob
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))

# table -> columns to match the symbol on. Deletes go through the parent
# `fyers_candles`, which fans out to every partition.
PURGE_TABLES = {
    "stocks": ["symbol"],
    "stock_prices": ["symbol"],
    "fyers_candles": ["symbol"],
    "candles": ["symbol"],
    "intraday_candles": ["symbol"],
    "predictions": ["symbol"],
    "news_articles": ["symbol"],
    "shareholding_patterns": ["symbol"],
    "peer_comparisons": ["symbol"],
    "company_external_data": ["symbol"],
    "external_slug_map": ["symbol"],
    "company_connections": ["symbol"],
    "thesis_analysis": ["symbol"],
    "watchlist_notes": ["symbol"],
}

# Kept. Financial records, the user's own writing, reference data, and
# columns that belong to another company's row.
KEEP_TABLES = {
    "trade_journal", "paper_trades", "trade_log", "trade_snapshots",
    "theses", "stock_theses",
    "master_ticker_table", "nse_instruments", "commodity_snapshots",
}
KEEP_COLUMNS = {("company_connections", "related_symbol")}

# analysis_cache keys that are about one symbol: three exact keys plus the
# backtest family. Matched with = ANY and a regex, never LIKE — in LIKE the
# underscore is a wildcard, so 'backtest_LT_%' would also match LTI's keys.
_CACHE_KEYS = ["research_{s}", "fundamentals_{s}", "fundamentals_v2_{s}"]
_CACHE_KEY_REGEX = "^backtest_{s}_"
_CACHE_WHERE = "cache_key = ANY(%s) OR cache_key ~ %s"


def _cache_params(symbol):
    import re
    return ([k.format(s=symbol) for k in _CACHE_KEYS], _CACHE_KEY_REGEX.format(s=re.escape(symbol)))
# cached JSON blobs that list many symbols; the symbol's entry is cut out.
_CACHE_LISTS = {"research_leaderboard": "list", "auto_analysis_latest": "predictions"}

# files named after the symbol. Exact stem so LT never matches LTI.
_FILE_PATTERNS = [
    "models/gbc_cash/{s}.joblib", "models/xgb_cash/{s}.joblib", "models/{s}.joblib",
    "models/backtest_cache/{s}_*.joblib", "chart_cache/{s}.*", "chart_cache/{s}_*",
]

# Trades that are still open. Journal statuses that mean "not open" live in
# app.CLOSED_TRADE_STATUSES; anything else with money at risk blocks the purge.
_OPEN = ("OPEN",)


def _symbol_columns(cur):
    """Every (table, column) in public that looks like a symbol reference."""
    cur.execute("""
        SELECT c.table_name, c.column_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_name = c.table_name AND t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
        WHERE c.table_schema = 'public'
          AND (c.column_name ILIKE '%symbol%' OR c.column_name IN ('stock', 'ticker'))
          AND c.table_name NOT LIKE 'fyers\\_candles\\_%'      -- partitions: covered by the parent
        ORDER BY 1, 2""")
    return cur.fetchall()


def open_positions(symbol):
    """Open paper positions for the symbol, from both stores. Empty list = safe."""
    found = []
    try:
        from paper_trader import PaperTradeTracker
        for t in PaperTradeTracker().trades:
            if str(t.get("symbol", "")).upper() == symbol and str(t.get("status", "")).upper() in _OPEN:
                found.append(f"paper trade {t.get('id')}")
    except Exception as e:
        logger.warning("purge %s: could not read the paper tracker (%s) — treating as unknown", symbol, e)
        found.append("paper tracker unreadable")
    try:
        from db_manager import get_db, TradeJournalEntry
        with get_db().Session() as s:
            n = s.query(TradeJournalEntry).filter(TradeJournalEntry.symbol == symbol,
                                                  TradeJournalEntry.status.in_(_OPEN)).count()
        if n:
            found.append(f"{n} open journal entr{'y' if n == 1 else 'ies'}")
    except Exception as e:
        logger.warning("purge %s: could not read the journal (%s) — treating as unknown", symbol, e)
        found.append("journal unreadable")
    return found


def footprint(symbol):
    """
    Read-only: what a purge of `symbol` would delete, keep and leave
    unclassified. Same classification as purge_symbol(), so the confirm
    dialog shows exactly what will happen.
    """
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol required")
    import psycopg2
    out = {"symbol": symbol, "delete": {}, "keep": {}, "unclassified": {}, "files": [], "open_positions": open_positions(symbol)}
    conn = psycopg2.connect(os.getenv("DB_URL"), connect_timeout=5)
    try:
        cur = conn.cursor()
        cur.execute("""SELECT count(*) FROM external_slug_map WHERE symbol IS NULL AND company_name IN
                       (SELECT company_name FROM stocks WHERE symbol = %s)""", (symbol,))
        n = cur.fetchone()[0]
        if n:
            out["delete"]["external_slug_map.company_name"] = n
        for table, col in _symbol_columns(cur):
            cur.execute(f'SELECT count(*) FROM "{table}" WHERE "{col}" = %s', (symbol,))
            n = cur.fetchone()[0]
            if not n:
                continue
            key = f"{table}.{col}" if col != "symbol" else table
            if table in PURGE_TABLES and col in PURGE_TABLES[table]:
                out["delete"][key] = n
            elif table in KEEP_TABLES or (table, col) in KEEP_COLUMNS:
                out["keep"][key] = n
            else:
                out["unclassified"][key] = n
        cur.execute("SELECT count(*) FROM analysis_cache WHERE " + _CACHE_WHERE, _cache_params(symbol))
        n = cur.fetchone()[0]
        if n:
            out["delete"]["analysis_cache"] = n
        cur.execute("SELECT count(*) FROM config_settings WHERE key = %s", (f"tijori.last_collected.{symbol}",))
        if cur.fetchone()[0]:
            out["delete"]["config_settings"] = 1
    finally:
        conn.close()
    for pat in _FILE_PATTERNS:
        out["files"] += sorted(os.path.relpath(p, _HERE) for p in glob.glob(os.path.join(_HERE, pat.format(s=symbol))))
    return out


def purge_symbol(symbol):
    """
    Delete everything about `symbol` (see module docstring). All database
    work is one transaction: either every row goes or none does. Files and
    in-memory caches are cleared only after the commit.

    Returns the report; raises PermissionError when a position is open,
    ValueError on a bad symbol. Any other failure rolls back and re-raises.
    """
    symbol = str(symbol or "").strip().upper()
    if not symbol or not symbol.replace("-", "").replace("&", "").isalnum():
        raise ValueError("symbol required")

    blockers = open_positions(symbol)
    if blockers:
        raise PermissionError(f"{symbol} still has an open position ({', '.join(blockers)}). Close it first.")

    import psycopg2
    report = {"symbol": symbol, "deleted": {}, "kept": {}, "unclassified": {}, "files": [], "started_at": datetime.utcnow().isoformat()}
    conn = psycopg2.connect(os.getenv("DB_URL"), connect_timeout=5)
    try:
        cur = conn.cursor()

        # The slug cache can hold a failure under our company name with no
        # symbol; read the name now, before the stocks row goes.
        cur.execute("SELECT company_name FROM stocks WHERE symbol = %s", (symbol,))
        names = [r[0] for r in cur.fetchall() if r[0]]

        # 1. Rows. Membership first (stocks) so a crash after commit can never
        #    leave an active stock with half its data.
        for table, col in _symbol_columns(cur):
            key = f"{table}.{col}" if col != "symbol" else table
            if table in PURGE_TABLES and col in PURGE_TABLES[table]:
                cur.execute(f'DELETE FROM "{table}" WHERE "{col}" = %s', (symbol,))
                if cur.rowcount:
                    report["deleted"][key] = cur.rowcount
            else:
                cur.execute(f'SELECT count(*) FROM "{table}" WHERE "{col}" = %s', (symbol,))
                n = cur.fetchone()[0]
                if n:
                    bucket = "kept" if (table in KEEP_TABLES or (table, col) in KEEP_COLUMNS) else "unclassified"
                    report[bucket][key] = n

        # A slug-map failure recorded under the company name, with no symbol.
        if names:
            cur.execute("DELETE FROM external_slug_map WHERE symbol IS NULL AND company_name = ANY(%s)", (names,))
            if cur.rowcount:
                report["deleted"]["external_slug_map.company_name"] = cur.rowcount

        # 2. Cached analyses about the symbol.
        cur.execute("DELETE FROM analysis_cache WHERE " + _CACHE_WHERE, _cache_params(symbol))
        if cur.rowcount:
            report["deleted"]["analysis_cache"] = cur.rowcount

        # 3. Cached lists that mention it (leaderboard, latest scan): cut the
        #    entry rather than wait for the next batch to rebuild the list.
        for key, shape in _CACHE_LISTS.items():
            cur.execute("SELECT data_json FROM analysis_cache WHERE cache_key = %s FOR UPDATE", (key,))
            row = cur.fetchone()
            if not row or not row[0]:
                continue
            try:
                data = json.loads(row[0])
            except Exception:
                continue
            changed = False
            if shape == "list" and isinstance(data, list):
                kept = [r for r in data if str(r.get("symbol", "")).upper() != symbol]
                changed = len(kept) != len(data); data = kept
            elif isinstance(data, dict) and isinstance(data.get(shape), list):
                kept = [r for r in data[shape] if str(r.get("symbol", "")).upper() != symbol]
                changed = len(kept) != len(data[shape]); data[shape] = kept
            if changed:
                cur.execute("UPDATE analysis_cache SET data_json = %s WHERE cache_key = %s", (json.dumps(data, default=str), key))
                report["deleted"][f"analysis_cache:{key}"] = 1

        # 4. Per-symbol config.
        cur.execute("DELETE FROM config_settings WHERE key = %s", (f"tijori.last_collected.{symbol}",))
        if cur.rowcount:
            report["deleted"]["config_settings"] = cur.rowcount

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 5. Files — after the commit, so a failed transaction deletes nothing.
    for pat in _FILE_PATTERNS:
        for path in glob.glob(os.path.join(_HERE, pat.format(s=symbol))):
            try:
                os.remove(path)
                report["files"].append(os.path.relpath(path, _HERE))
            except OSError as e:
                logger.warning("purge %s: could not remove %s: %s", symbol, path, e)

    # 6. In-process caches that would otherwise serve the stock until restart.
    _forget_in_memory(symbol)

    # 7. The notes file mirror (the DB row went with watchlist_notes). Edited
    #    directly rather than via app._save_watchlist_note so this module
    #    never imports app.py (which builds the Flask app on import).
    notes_path = os.path.join(_HERE, "watchlist_notes.json")
    try:
        with open(notes_path) as f:
            notes = json.load(f)
        if isinstance(notes, dict) and symbol in notes:
            notes.pop(symbol)
            with open(notes_path, "w") as f:
                json.dump(notes, f, indent=2)
            report["files"].append("watchlist_notes.json (entry)")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("purge %s: notes file not updated: %s", symbol, e)

    report["finished_at"] = datetime.utcnow().isoformat()
    logger.info("Purged %s: %s; kept %s; files %s%s", symbol, report["deleted"], report["kept"], report["files"],
                f"; UNCLASSIFIED {report['unclassified']}" if report["unclassified"] else "")
    try:
        import change_feed
        change_feed.notify("watchlist", symbol=symbol, action="removed")
    except Exception:
        pass
    return report


def _forget_in_memory(symbol):
    """Drop the symbol from every module-level cache that is keyed by it."""
    steps = []
    try:
        import bot
        bot._predictors.pop(symbol, None); steps.append("bot._predictors")
    except Exception: pass
    try:
        import fundamental_analysis as fa
        with fa._cache_lock:
            fa._cache.pop(symbol, None)
        steps.append("fundamental_analysis._cache")
    except Exception: pass
    try:
        import news_sentiment as ns
        ns._cache.pop(symbol, None); steps.append("news_sentiment._cache")
    except Exception: pass
    try:
        import commodity_tracker as ct
        ct._commodity_map_cache = None; steps.append("commodity_tracker map")
    except Exception: pass
    try:
        import tijori_collector as tc
        tc._LOCAL_INDEX["map"] = None; steps.append("tijori local index")
    except Exception: pass
    try:
        import auto_analyzer as aa
        preds = aa._latest_analysis.get("predictions")
        if isinstance(preds, list):
            aa._latest_analysis["predictions"] = [p for p in preds if str(p.get("symbol", "")).upper() != symbol]
        steps.append("auto_analyzer latest")
    except Exception: pass
    try:
        from db_manager import invalidate_config_cache
        invalidate_config_cache(f"tijori.last_collected.{symbol}")
    except Exception: pass
    logger.debug("purge %s: cleared %s", symbol, steps)
