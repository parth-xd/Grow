#!/usr/bin/env python3
"""
TRADE ORIGIN & POSITION MANAGEMENT

Tracks whether trades are:
- MANUAL: User initiated (system cannot touch)
- AUTO: System initiated (system manages full lifecycle)

Enforces boundaries:
- Manual trades: Can only be closed by user
- Auto trades: System manages entry-to-exit
- Manual holdings: Protected capital (not available for auto trading)
"""

import json
import os
from datetime import datetime
import pytz
from config import PROJECT_ROOT

ist = pytz.timezone('Asia/Kolkata')

# Manual holdings tracking file
MANUAL_HOLDINGS_FILE = os.path.join(PROJECT_ROOT, 'manual_holdings.json')
TRADE_ORIGINS_FILE = os.path.join(PROJECT_ROOT, 'trade_origins.json')

def register_manual_holding(symbol, quantity, entry_price, entry_date=None):
    """
    Register a manually held position (user initiated, not system).
    System will not trade these positions.
    """
    try:
        if os.path.exists(MANUAL_HOLDINGS_FILE):
            with open(MANUAL_HOLDINGS_FILE, 'r') as f:
                holdings = json.load(f)
        else:
            holdings = {}
        
        holdings[symbol] = {
            'quantity': quantity,
            'entry_price': entry_price,
            'entry_date': entry_date or datetime.now(ist).isoformat(),
            'locked': True,  # Protected from auto trading
            'registered_at': datetime.now(ist).isoformat()
        }
        
        with open(MANUAL_HOLDINGS_FILE, 'w') as f:
            json.dump(holdings, f, indent=2)
        
        print(f"✓ Registered manual holding: {symbol} x{quantity} @ ₹{entry_price}")
        return True
    except Exception as e:
        print(f"❌ Failed to register manual holding: {e}")
        return False


def get_manual_holdings():
    """Get all manually held positions."""
    try:
        if os.path.exists(MANUAL_HOLDINGS_FILE):
            with open(MANUAL_HOLDINGS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}


def is_manual_holding(symbol):
    """Check if symbol is a manually held position."""
    holdings = get_manual_holdings()
    return symbol in holdings and holdings[symbol].get('locked', False)


def track_trade_origin(trade_id, symbol, origin_type='AUTO', details=None):
    """
    Track whether trade was initiated by USER or SYSTEM.
    
    Args:
        trade_id: Unique trade identifier
        symbol: Stock symbol
        origin_type: 'MANUAL' or 'AUTO'
        details: Additional metadata
    """
    try:
        if os.path.exists(TRADE_ORIGINS_FILE):
            with open(TRADE_ORIGINS_FILE, 'r') as f:
                origins = json.load(f)
        else:
            origins = {}
        
        origins[trade_id] = {
            'symbol': symbol,
            'origin': origin_type,
            'initiated_at': datetime.now(ist).isoformat(),
            'initiated_by': details.get('by', 'unknown') if details else 'unknown',
            'details': details or {},
            'can_be_closed_by': 'USER' if origin_type == 'MANUAL' else 'SYSTEM'
        }
        
        with open(TRADE_ORIGINS_FILE, 'w') as f:
            json.dump(origins, f, indent=2)
        
        return True
    except Exception as e:
        print(f"❌ Failed to track trade origin: {e}")
        return False


def get_trade_origin(trade_id):
    """Get origin information for a specific trade."""
    try:
        if os.path.exists(TRADE_ORIGINS_FILE):
            with open(TRADE_ORIGINS_FILE, 'r') as f:
                origins = json.load(f)
            return origins.get(trade_id)
    except:
        pass
    return None


def can_system_close_trade(trade_id):
    """
    Check if system can close this trade.
    Returns False if trade is MANUAL (user must close it).
    """
    origin = get_trade_origin(trade_id)
    if not origin:
        return True  # Default: can close if no origin recorded
    
    return origin.get('origin') != 'MANUAL'


def calculate_available_capital_for_auto_trading(total_capital, manual_holdings_list=None):
    """
    Calculate capital available for automated trading.
    Excludes capital tied up in manual holdings.
    
    Args:
        total_capital: Total portfolio capital
        manual_holdings_list: List of manual holdings
    
    Returns:
        Available capital for auto trading
    """
    if not manual_holdings_list:
        manual_holdings_list = list(get_manual_holdings().values())
    
    locked_capital = sum(h['quantity'] * h['entry_price'] for h in manual_holdings_list)
    available = total_capital - locked_capital
    
    return max(0, available)


def get_protected_symbols():
    """Get list of symbols that system cannot trade (manually held)."""
    holdings = get_manual_holdings()
    return list(holdings.keys())


def log_trade_boundary_event(event_type, trade_id, symbol, message):
    """
    Log boundary enforcement events:
    - MANUAL_TRADE_PROTECTED: System tried to touch manual trade
    - MANUAL_SYMBOL_SKIPPED: System skipped trading symbol with manual holdings
    - AUTO_TRADE_CLOSED: System closed auto trade
    - USER_TRADE_UNMODIFIED: User trade unchanged
    """
    log_entry = {
        'timestamp': datetime.now(ist).isoformat(),
        'event': event_type,
        'trade_id': trade_id,
        'symbol': symbol,
        'message': message
    }
    
    log_file = os.path.join(PROJECT_ROOT, 'trade_boundary_log.json')
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = json.load(f)
        else:
            logs = []
        
        logs.append(log_entry)
        
        # Keep last 500 entries
        if len(logs) > 500:
            logs = logs[-500:]
        
        with open(log_file, 'w') as f:
            json.dump(logs, f, indent=2)
    except:
        pass
