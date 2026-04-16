"""
Peer Data Manager — Collect, store, and analyze peer company data.

Functions:
  - collect_peers_for_stock(symbol) — Fetch competitors and store in database
  - get_peers_from_database(symbol) — Query stored peer data
  - update_peer_prices() — Refresh all peer prices daily
  - delete_peers_for_stock(symbol) — Clean up when stock is removed
"""

import logging
import os
from datetime import datetime
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


def _get_db_connection():
    """Get PostgreSQL connection if available."""
    try:
        import psycopg2
        db_url = os.getenv("DB_URL")
        if not db_url:
            return None
        return psycopg2.connect(db_url, connect_timeout=3)
    except Exception as e:
        logger.debug("Database unavailable: %s", e)
        return None


def _ensure_peer_tables():
    """Create necessary tables for peer data if they don't exist."""
    conn = _get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # Table for peer company info
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS peers (
                id SERIAL PRIMARY KEY,
                parent_symbol VARCHAR(20) NOT NULL,
                peer_symbol VARCHAR(20) NOT NULL,
                peer_name VARCHAR(255),
                sector VARCHAR(100),
                added_date TIMESTAMP DEFAULT NOW(),
                UNIQUE(parent_symbol, peer_symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_peers_parent ON peers(parent_symbol);
            CREATE INDEX IF NOT EXISTS idx_peers_symbol ON peers(peer_symbol);
        """)
        
        # Table for peer price history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS peer_prices (
                id SERIAL PRIMARY KEY,
                peer_symbol VARCHAR(20) NOT NULL,
                date DATE NOT NULL,
                ltp DECIMAL(10, 2),
                prev_close DECIMAL(10, 2),
                change_pct DECIMAL(8, 2),
                volume BIGINT,
                recorded_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(peer_symbol, date)
            );
            CREATE INDEX IF NOT EXISTS idx_peer_prices_symbol_date ON peer_prices(peer_symbol, date);
        """)
        
        # Table for peer comparison analysis results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS peer_analysis (
                id SERIAL PRIMARY KEY,
                parent_symbol VARCHAR(20) NOT NULL,
                analysis_date DATE NOT NULL,
                outperformers TEXT,
                underperformers TEXT,
                peers_at_parity TEXT,
                avg_peer_change DECIMAL(8, 2),
                best_peer VARCHAR(20),
                worst_peer VARCHAR(20),
                analysis_json TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(parent_symbol, analysis_date)
            );
            CREATE INDEX IF NOT EXISTS idx_peer_analysis_parent_date ON peer_analysis(parent_symbol, analysis_date);
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✓ Peer tables initialized")
        return True
    except Exception as e:
        logger.warning("Failed to create peer tables: %s", e)
        return False


def collect_peers_for_stock(symbol):
    """
    Fetch competitors for a stock and store in database.
    Called when stock is added to watchlist.
    """
    try:
        if not _ensure_peer_tables():
            logger.warning("Cannot collect peers: database unavailable")
            return {"success": False, "message": "Database unavailable"}
        
        # Fetch peers using fundamental analysis module
        from fundamental_analysis import _get_competitors
        
        peers = _get_competitors(symbol)
        if not peers:
            logger.info(f"No peers found for {symbol}")
            return {"success": True, "peers_count": 0}
        
        conn = _get_db_connection()
        if not conn:
            return {"success": False, "message": "Database unavailable"}
        
        cursor = conn.cursor()
        
        # Store peer info in database
        for peer in peers[:10]:  # Store up to 10 peers
            try:
                cursor.execute("""
                    INSERT INTO peers (parent_symbol, peer_symbol, peer_name, sector)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (parent_symbol, peer_symbol) DO UPDATE
                    SET added_date = NOW()
                """, (symbol.upper(), peer.upper(), peer, "Unknown"))
            except Exception as e:
                logger.debug(f"Failed to store peer {peer}: {e}")
                continue
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"✓ Collected {len(peers)} peers for {symbol}")
        return {"success": True, "peers_count": len(peers), "peers": peers}
    
    except Exception as e:
        logger.error("Failed to collect peers for %s: %s", symbol, e)
        return {"success": False, "message": str(e)}


def delete_peers_for_stock(symbol):
    """
    Delete all peer data for a stock when it's removed from watchlist.
    """
    try:
        conn = _get_db_connection()
        if not conn:
            logger.debug("Cannot delete peers: database unavailable")
            return False
        
        cursor = conn.cursor()
        
        # Delete peer records
        cursor.execute("DELETE FROM peers WHERE parent_symbol = %s", (symbol.upper(),))
        
        # Delete peer analysis records
        cursor.execute("DELETE FROM peer_analysis WHERE parent_symbol = %s", (symbol.upper(),))
        
        deleted_count = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"✓ Deleted peer data for {symbol}")
        return True
    
    except Exception as e:
        logger.warning("Failed to delete peers for %s: %s", symbol, e)
        return False


def get_peers_from_database(symbol):
    """
    Get stored peer data for a stock from database.
    Returns peer list with latest price and change info.
    """
    try:
        conn = _get_db_connection()
        if not conn:
            return []
        
        cursor = conn.cursor()
        
        # Get peers and their latest prices
        cursor.execute("""
            SELECT 
                p.peer_symbol,
                p.peer_name,
                pp.ltp,
                pp.prev_close,
                pp.change_pct,
                pp.date as price_date
            FROM peers p
            LEFT JOIN peer_prices pp ON p.peer_symbol = pp.peer_symbol
                AND pp.date = (SELECT MAX(date) FROM peer_prices WHERE peer_symbol = p.peer_symbol)
            WHERE p.parent_symbol = %s
            ORDER BY pp.change_pct DESC NULLS LAST
        """, (symbol.upper(),))
        
        peers = []
        for row in cursor.fetchall():
            peers.append({
                "symbol": row[0],
                "name": row[1],
                "ltp": float(row[2]) if row[2] else 0,
                "prev_close": float(row[3]) if row[3] else 0,
                "change_pct": float(row[4]) if row[4] else 0,
                "price_date": str(row[5]) if row[5] else None
            })
        
        cursor.close()
        conn.close()
        
        return peers
    
    except Exception as e:
        logger.debug("Failed to get peers from database for %s: %s", symbol, e)
        return []


def update_peer_prices():
    """
    Fetch and update latest prices for all stored peers.
    Called daily by scheduler.
    """
    try:
        import bot
        from datetime import datetime
        
        conn = _get_db_connection()
        if not conn:
            logger.debug("Database unavailable for peer price update")
            return {"updated": 0, "failed": 0}
        
        cursor = conn.cursor()
        
        # Get all unique peer symbols
        cursor.execute("SELECT DISTINCT peer_symbol FROM peers")
        peer_symbols = [row[0] for row in cursor.fetchall()]
        
        updated_count = 0
        failed_count = 0
        today = datetime.now().date()
        
        for peer_symbol in peer_symbols:
            try:
                # Fetch live price
                ltp = bot.fetch_live_price(peer_symbol)
                if not ltp or ltp <= 0:
                    failed_count += 1
                    continue
                
                # Get previous close for change calculation
                quote = bot.fetch_quote(peer_symbol)
                prev_close = float(quote.get("prev_close", 0)) if quote else 0
                
                change_pct = 0
                if prev_close > 0:
                    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
                
                # Store/update price
                cursor.execute("""
                    INSERT INTO peer_prices (peer_symbol, date, ltp, prev_close, change_pct)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (peer_symbol, date) DO UPDATE
                    SET ltp = EXCLUDED.ltp, prev_close = EXCLUDED.prev_close, change_pct = EXCLUDED.change_pct
                """, (peer_symbol, today, ltp, prev_close, change_pct))
                
                updated_count += 1
            
            except Exception as e:
                failed_count += 1
                logger.debug(f"Failed to update price for peer {peer_symbol}: {e}")
                continue
        
        conn.commit()
        cursor.close()
        conn.close()
        
        if updated_count > 0:
            logger.info(f"✓ Updated {updated_count} peer prices (failed: {failed_count})")
        
        return {"updated": updated_count, "failed": failed_count}
    
    except Exception as e:
        logger.warning("Peer price update failed: %s", e)
        return {"updated": 0, "failed": 0}


def analyze_peer_comparison(symbol, stock_price, stock_change_pct):
    """
    Analyze how stock is performing relative to peers.
    Uses database peer price data.
    """
    try:
        peers = get_peers_from_database(symbol)
        if not peers:
            return None
        
        outperformers = []
        underperformers = []
        at_parity = []
        
        peer_changes = []
        for peer in peers:
            peer_change = peer.get("change_pct", 0)
            peer_changes.append(peer_change)
            
            diff = stock_change_pct - peer_change
            if diff > 2:  # Stock outperforming by >2%
                outperformers.append({
                    "symbol": peer["symbol"],
                    "change": peer_change,
                    "diff": diff
                })
            elif diff < -2:  # Stock underperforming by >2%
                underperformers.append({
                    "symbol": peer["symbol"],
                    "change": peer_change,
                    "diff": diff
                })
            else:
                at_parity.append(peer["symbol"])
        
        avg_peer_change = sum(peer_changes) / len(peer_changes) if peer_changes else 0
        
        analysis = {
            "peer_count": len(peers),
            "outperformers": outperformers,
            "underperformers": underperformers,
            "at_parity": at_parity,
            "avg_peer_change_pct": round(avg_peer_change, 2),
            "stock_vs_peers_diff": round(stock_change_pct - avg_peer_change, 2),
            "action": "BULLISH" if stock_change_pct > avg_peer_change else "BEARISH" if stock_change_pct < avg_peer_change else "NEUTRAL"
        }
        
        # Store analysis in database
        try:
            conn = _get_db_connection()
            if conn:
                import json
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO peer_analysis (parent_symbol, analysis_date, outperformers, underperformers, 
                                             peers_at_parity, avg_peer_change, analysis_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (parent_symbol, analysis_date) DO UPDATE
                    SET outperformers = EXCLUDED.outperformers, 
                        underperformers = EXCLUDED.underperformers,
                        analysis_json = EXCLUDED.analysis_json
                """, (
                    symbol.upper(),
                    datetime.now().date(),
                    ",".join([p["symbol"] for p in outperformers]),
                    ",".join([p["symbol"] for p in underperformers]),
                    ",".join(at_parity),
                    avg_peer_change,
                    json.dumps(analysis)
                ))
                conn.commit()
                cursor.close()
                conn.close()
        except Exception as e:
            logger.debug(f"Failed to store peer analysis: {e}")
        
        return analysis
    
    except Exception as e:
        logger.debug("Failed to analyze peers for %s: %s", symbol, e)
        return None
