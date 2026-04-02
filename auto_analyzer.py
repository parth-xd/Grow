"""
Auto Analyzer — Automatically analyze all stocks with live market data
and provide recommendations based on ongoing trends.
"""

import logging
import threading
import time
from datetime import datetime
import json
import hashlib

import bot

logger = logging.getLogger(__name__)

# Storage for latest auto-analysis results
_latest_analysis = {
    "timestamp": None,
    "predictions": [],
    "summary": {},
}

# Track previous state for change detection
_previous_state_hash = None
_state_change_summary = {}


def _load_latest_from_db():
    """Try to load the last auto-analysis from DB cache."""
    global _latest_analysis
    try:
        from db_manager import get_cached
        cached = get_cached("auto_analysis_latest", ttl_seconds=86400)
        if cached and cached.get("timestamp"):
            _latest_analysis = cached
            return True
    except Exception:
        pass
    return False


def _save_latest_to_db():
    """Persist the latest analysis to DB cache."""
    try:
        from db_manager import set_cached
        set_cached("auto_analysis_latest", _latest_analysis, cache_type="auto_analysis")
    except Exception:
        pass


# Load last analysis from DB on startup
_load_latest_from_db()


def _calculate_state_hash(predictions):
    """Calculate a hash of the current prediction state for change detection."""
    # Create a hashable representation of key prediction data
    key_data = []
    for p in predictions:
        key_data.append({
            "symbol": p.get("symbol"),
            "signal": p.get("signal"),
            "confidence": round(p.get("confidence", 0), 2),
            "price": round(p.get("indicators", {}).get("price", 0), 2),
        })
    state_str = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(state_str.encode()).hexdigest()


def _detect_changes(old_predictions, new_predictions, portfolio_symbols=None):
    """
    Detect what changed between old and new predictions.
    Categorizes changes as portfolio vs watchlist.
    
    Args:
        old_predictions: Previous predictions
        new_predictions: Current predictions
        portfolio_symbols: Set of symbols in user's portfolio (for categorization)
    """
    if not portfolio_symbols:
        portfolio_symbols = set()
    
    if not old_predictions:
        return {"type": "initial", "changed_symbols": [p.get("symbol") for p in new_predictions]}
    
    changes = {
        "portfolio": {
            "signal_changes": [],
            "new_signals": [],
            "price_moves": [],
            "confidence_increases": [],
        },
        "watchlist": {
            "signal_changes": [],
            "new_signals": [],
            "price_moves": [],
            "confidence_increases": [],
        },
    }
    
    old_map = {p.get("symbol"): p for p in old_predictions}
    new_map = {p.get("symbol"): p for p in new_predictions}
    
    for symbol, new_pred in new_map.items():
        old_pred = old_map.get(symbol)
        if not old_pred:
            continue
        
        category = "portfolio" if symbol in portfolio_symbols else "watchlist"
        new_signal = new_pred.get("signal")
        old_signal = old_pred.get("signal")
        
        # Signal changed
        if new_signal != old_signal:
            changes[category]["signal_changes"].append({
                "symbol": symbol,
                "old": old_signal,
                "new": new_signal,
            })
        
        # Significant confidence increase
        old_conf = old_pred.get("confidence", 0)
        new_conf = new_pred.get("confidence", 0)
        if new_conf - old_conf >= 0.15:  # 15% increase
            changes[category]["confidence_increases"].append({
                "symbol": symbol,
                "old_confidence": round(old_conf, 3),
                "new_confidence": round(new_conf, 3),
            })
        
        # New BUY signal
        if old_signal != "BUY" and new_signal == "BUY":
            changes[category]["new_signals"].append({
                "symbol": symbol,
                "signal": "BUY",
                "confidence": round(new_conf, 3),
            })
        
        # Significant price move
        old_price = old_pred.get("indicators", {}).get("price", 0)
        new_price = new_pred.get("indicators", {}).get("price", 0)
        if old_price > 0:
            pct_change = abs((new_price - old_price) / old_price * 100)
            if pct_change >= 1:  # 1% move
                changes[category]["price_moves"].append({
                    "symbol": symbol,
                    "old_price": round(old_price, 2),
                    "new_price": round(new_price, 2),
                    "pct_change": round(pct_change, 2),
                })
    
    # Filter out empty subcategories
    filtered = {}
    for cat in ["portfolio", "watchlist"]:
        filtered[cat] = {k: v for k, v in changes[cat].items() if v}
    
    return {k: v for k, v in filtered.items() if v}


def auto_analyze_watchlist():
    """
    Automatically analyze all watchlist stocks with live data.
    Runs in a background thread.
    """
    global _latest_analysis, _previous_state_hash, _state_change_summary
    
    try:
        logger.info("Starting auto-analysis of watchlist...")
        
        # Get all predictions
        predictions = bot.scan_watchlist()
        
        # Count signals
        buy_count = sum(1 for p in predictions if p.get("signal") == "BUY")
        sell_count = sum(1 for p in predictions if p.get("signal") == "SELL")
        hold_count = sum(1 for p in predictions if p.get("signal") == "HOLD")
        
        # Find highest confidence
        best_buy = next((p for p in predictions if p.get("signal") == "BUY"), None)
        if best_buy:
            best_buy = max([p for p in predictions if p.get("signal") == "BUY"], 
                          key=lambda x: x.get("confidence", 0))
        
        # Calculate state hash and detect changes
        current_hash = _calculate_state_hash(predictions)
        has_update = current_hash != _previous_state_hash
        
        # Get portfolio holdings for categorization
        portfolio_symbols = set()
        try:
            holdings = bot.get_holdings()
            portfolio_symbols = set(h.get("trading_symbol", "") for h in (holdings or []))
        except Exception as e:
            logger.debug(f"Could not get portfolio holdings: {e}")
        
        if has_update and _latest_analysis.get("predictions"):
            _state_change_summary = _detect_changes(
                _latest_analysis.get("predictions", []),
                predictions,
                portfolio_symbols
            )
        else:
            _state_change_summary = {}
        
        _latest_analysis = {
            "timestamp": datetime.now().isoformat(),
            "predictions": predictions,
            "summary": {
                "total_stocks": len(predictions),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "hold_count": hold_count,
                "best_buy": best_buy["symbol"] if best_buy else None,
                "best_buy_confidence": (best_buy.get("confidence", 0) if best_buy else 0),
            },
            "status": "complete",
            "has_update": has_update,
        }
        
        _previous_state_hash = current_hash
        
        # Persist to DB
        _save_latest_to_db()
        
        if has_update and _state_change_summary:
            logger.info(f"✓ Auto-analysis complete with UPDATES: {_state_change_summary}")
        else:
            logger.info(f"✓ Auto-analysis complete (no changes): {buy_count} BUY, {sell_count} SELL, {hold_count} HOLD")
        
    except Exception as e:
        logger.error(f"Auto-analysis failed: {e}")
        _latest_analysis["status"] = "error"
        _latest_analysis["error"] = str(e)


def get_latest_analysis():
    """Get the most recent auto-analysis results."""
    return _latest_analysis


def check_for_updates():
    """
    Check if there are updates since the last check.
    Returns lightweight info about what changed (doesn't send full data).
    """
    return {
        "has_update": _latest_analysis.get("has_update", False),
        "timestamp": _latest_analysis.get("timestamp"),
        "summary": _latest_analysis.get("summary", {}),
        "changes": _state_change_summary,
    }


def start_auto_analyzer(interval_seconds=60):
    """
    Start background auto-analyzer thread with smart update detection.
    Startups immediately as daemon without blocking server startup.
    
    Args:
        interval_seconds: How often to analyze (default 1 minute).
                         Only fetches platform data and notifies on actual changes.
    """
    def background_loop():
        logger.info(f"Auto-analyzer thread started (polling every {interval_seconds}s for changes)")
        # Wait before first run so server stabilizes
        time.sleep(10)  # Reduced from 30s to 10s
        while True:
            try:
                auto_analyze_watchlist()
            except Exception as e:
                logger.error(f"Auto-analyzer error: {e}")
            time.sleep(interval_seconds)
    
    # Start as daemon thread (exits when main program exits)
    # setDaemon(True) ensures thread doesn't block shutdown
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()
    logger.info("✓ Auto-analyzer thread running in background (non-blocking)")
    return thread
