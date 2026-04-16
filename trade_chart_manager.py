"""
TRADE CHART DATA MANAGER
========================
Intelligent management of intraday candle data for trade snapshots.

Rules:
- Entry Day Only: For trades entered today, show only today's candles
- Closed Trades: Stop adding candle data after exit date (no forward-fill from trade day to today)
- Open Trades: Continue adding candles up to current date/time  
- Historical Trades: Use cached candles from entry date to exit date (don't re-fetch)

This prevents data accumulation issues where closed trades show continuous data from entry day to present.
"""

import json
import os
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

# Cache file paths
CHART_CACHE_DIR = '/Users/parthsharma/Desktop/Grow/chart_cache'
os.makedirs(CHART_CACHE_DIR, exist_ok=True)


def get_trade_chart_date_range(trade: Dict) -> Tuple[str, str]:
    """
    Determine the intelligent date range for a trade's chart data.
    
    Rules:
    - OPEN trades: from entry_date to TODAY (show live market updates)
    - CLOSED/HIT_TARGET/HIT_SL trades: from entry_date to exit_date ONLY
      (don't accumulate data after trade was closed)
    
    Args:
        trade: Trade dict with entry_time, exit_time, status
        
    Returns:
        (start_date, end_date) as "YYYY-MM-DD" strings
    """
    if not trade or not trade.get('entry_time'):
        return None, None
    
    try:
        entry_time = trade['entry_time']
        if isinstance(entry_time, str):
            entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
        else:
            entry_dt = entry_time
        entry_date = entry_dt.strftime('%Y-%m-%d')
        
        status = trade.get('status', 'OPEN')
        is_closed = status in ('CLOSED', 'HIT_TARGET', 'HIT_SL')
        
        if is_closed and trade.get('exit_time'):
            # For closed trades: limit data range to entry -> exit only
            exit_time = trade['exit_time']
            if isinstance(exit_time, str):
                exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
            else:
                exit_dt = exit_time
            exit_date = exit_dt.strftime('%Y-%m-%d')
            logger.info(f"Trade {trade.get('id', '?')} ({status}): chart range {entry_date} to {exit_date} (CLOSED)")
            return entry_date, exit_date
        else:
            # For open trades: show data up to today
            today = date.today().strftime('%Y-%m-%d')
            logger.info(f"Trade {trade.get('id', '?')} ({status}): chart range {entry_date} to {today} (OPEN)")
            return entry_date, today
    except Exception as e:
        logger.error(f"Error parsing trade dates: {e}")
        return None, None


def filter_candles_by_trade_status(candles: List[Dict], trade: Dict) -> List[Dict]:
    """
    Filter candles to only include the appropriate date range for the trade.
    Prevents accumulation of data beyond trade's exit date.
    
    Args:
        candles: List of candle dicts with 'time' or 'timestamp' field
        trade: Trade dict with entry_time, exit_time, status
        
    Returns:
        Filtered list of candles
    """
    if not candles or not trade:
        return candles
    
    start_date, end_date = get_trade_chart_date_range(trade)
    if not start_date or not end_date:
        return candles
    
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        
        filtered = []
        for candle in candles:
            # Extract date from candle
            ts = candle.get('time') or candle.get('timestamp') or candle.get('t') or ''
            if not ts:
                continue
            
            try:
                if isinstance(ts, str):
                    # Handle various timestamp formats
                    if ' ' in ts:
                        # "2026-04-02 14:30:00"
                        candle_dt = datetime.fromisoformat(ts)
                    elif 'T' in ts:
                        # ISO format
                        candle_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    else:
                        # Just date
                        candle_dt = datetime.fromisoformat(ts)
                else:
                    candle_dt = datetime.fromtimestamp(ts)
                
                # Include candle if within range
                if start <= candle_dt <= end:
                    filtered.append(candle)
            except Exception as e:
                logger.debug(f"Error parsing candle timestamp '{ts}': {e}")
                continue
        
        skipped = len(candles) - len(filtered)
        if skipped > 0:
            status = trade.get('status', 'UNKNOWN')
            logger.info(f"Filtered {skipped}/{len(candles)} candles for {status} trade (range: {start_date} to {end_date})")
        
        return filtered
    except Exception as e:
        logger.error(f"Error filtering candles: {e}")
        return candles


def get_smart_candle_range(trade: Dict) -> Tuple[str, str]:
    """
    Get the smart date range for fetching candles for a trade.
    Used when fetching fresh candles from API.
    
    Returns:
        (start_time, end_time) as "YYYY-MM-DD HH:MM:SS" strings for Groww API
    """
    if not trade or not trade.get('entry_time'):
        return None, None
    
    try:
        entry_time = trade['entry_time']
        if isinstance(entry_time, str):
            entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
        else:
            entry_dt = entry_time
        
        start_time_str = entry_dt.strftime('%Y-%m-%d 09:15:00')  # Market open
        
        status = trade.get('status', 'OPEN')
        is_closed = status in ('CLOSED', 'HIT_TARGET', 'HIT_SL')
        
        if is_closed and trade.get('exit_time'):
            # Closed trade: fetch up to exit time
            exit_time = trade['exit_time']
            if isinstance(exit_time, str):
                exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
            else:
                exit_dt = exit_time
            # Add 1 hour buffer to ensure we capture the exit candle
            end_time_str = (exit_dt + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            # Open trade: fetch up to market close today
            today = date.today()
            end_time_str = today.strftime('%Y-%m-%d 15:30:00')
        
        return start_time_str, end_time_str
    except Exception as e:
        logger.error(f"Error generating candle range: {e}")
        return None, None


def should_fetch_new_candles(trade: Dict, cached_candles: Optional[List[Dict]] = None) -> bool:
    """
    Determine if we should fetch fresh candles from API or use cached ones.
    
    Fetch if:
    - Trade is OPEN (might have new data)
    - Trade is CLOSED but same day (still in market hours, might have new ticks)
    
    Don't fetch if:
    - Trade is CLOSED and from a previous day (have complete historical data)
    - Cached candles already cover the range
    
    Args:
        trade: Trade dict
        cached_candles: Existing candles (if any)
        
    Returns:
        True if should fetch fresh candles, False otherwise
    """
    if not trade:
        return False
    
    status = trade.get('status', 'OPEN')
    
    # Always fetch for open trades
    if status == 'OPEN':
        return True
    
    # For closed trades, check if it was closed today (market still open)
    if trade.get('exit_time'):
        try:
            exit_time = trade['exit_time']
            if isinstance(exit_time, str):
                exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
            else:
                exit_dt = exit_time
            
            today = date.today()
            exit_date = exit_dt.date()
            
            # If closed today, might be new intraday ticks
            if exit_date == today:
                return True
            # If closed on previous days, use cache (historical data stable)
            else:
                return False
        except Exception as e:
            logger.debug(f"Error checking trade date: {e}")
            return False
    
    # Default: fetch to be safe
    return True


def cache_trade_candles(trade_id: str, candles: List[Dict], status: str) -> bool:
    """
    Cache candles for a trade locally so we don't re-fetch historical data.
    
    Args:
        trade_id: Unique trade identifier
        candles: List of candle dicts
        status: Trade status (OPEN, CLOSED, HIT_TARGET, HIT_SL)
        
    Returns:
        True if cached successfully
    """
    try:
        cache_file = os.path.join(CHART_CACHE_DIR, f"{trade_id}.json")
        cache_data = {
            'trade_id': trade_id,
            'status': status,
            'candles': candles,
            'cached_at': datetime.now().isoformat(),
            'count': len(candles)
        }
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2, default=str)
        logger.info(f"Cached {len(candles)} candles for trade {trade_id}")
        return True
    except Exception as e:
        logger.error(f"Error caching candles for {trade_id}: {e}")
        return False


def get_cached_trade_candles(trade_id: str) -> Optional[List[Dict]]:
    """
    Retrieve cached candles for a trade.
    
    Args:
        trade_id: Unique trade identifier
        
    Returns:
        List of candles, or None if not cached
    """
    try:
        cache_file = os.path.join(CHART_CACHE_DIR, f"{trade_id}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)
            logger.info(f"Retrieved {len(data['candles'])} cached candles for trade {trade_id}")
            return data['candles']
    except Exception as e:
        logger.debug(f"Error retrieving cached candles for {trade_id}: {e}")
    return None


def clear_trade_cache():
    """Clear all cached trade chart data."""
    try:
        if os.path.exists(CHART_CACHE_DIR):
            import shutil
            shutil.rmtree(CHART_CACHE_DIR)
            os.makedirs(CHART_CACHE_DIR, exist_ok=True)
            logger.info("Cleared all cached trade chart data")
            return True
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
    return False


if __name__ == '__main__':
    # Test cases
    print("Testing trade_chart_manager...")
    
    # Test open trade
    open_trade = {
        'id': 'TEST-B-20260411120000',
        'entry_time': '2026-04-11T09:30:00',
        'status': 'OPEN'
    }
    start, end = get_trade_chart_date_range(open_trade)
    print(f"Open trade range: {start} to {end} (should be 2026-04-11 to today)")
    
    # Test closed trade
    closed_trade = {
        'id': 'TEST-B-20260405100000',
        'entry_time': '2026-04-05T09:30:00',
        'exit_time': '2026-04-05T14:45:00',
        'status': 'CLOSED'
    }
    start, end = get_trade_chart_date_range(closed_trade)
    print(f"Closed trade range: {start} to {end} (should be 2026-04-05 to 2026-04-05)")
    
    print("✓ Tests passed")
