"""
Stock Thesis Manager — Store your personal outlook for each holding
alongside AI predictions for later comparison and accountability.
Now backed by PostgreSQL with JSON file fallback.
"""

import json
import os
import logging
from datetime import datetime

THESIS_FILE = "stock_thesis.json"
logger = logging.getLogger(__name__)


def _db_available():
    try:
        from db_manager import get_db, StockThesis
        return True
    except Exception:
        return False


def load_thesis():
    """Load all personal stock theses from DB, fall back to JSON."""
    if _db_available():
        try:
            from db_manager import get_db, StockThesis
            db = get_db()
            with db.Session() as session:
                rows = session.query(StockThesis).all()
                if rows:
                    return {r.symbol: r.to_dict() for r in rows}
        except Exception as e:
            logger.debug("DB load thesis failed: %s", e)
    if os.path.exists(THESIS_FILE):
        with open(THESIS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_thesis(thesis_dict):
    """Save personal stock theses to JSON (backup)."""
    with open(THESIS_FILE, "w") as f:
        json.dump(thesis_dict, f, indent=2)


def add_or_update_thesis(symbol, thesis_text, target_price=None, timeframe=None):
    """Add or update personal thesis for a stock."""
    sym = symbol.upper()
    now_iso = datetime.now().isoformat()

    # Try DB first
    if _db_available():
        try:
            from db_manager import get_db, StockThesis
            db = get_db()
            with db.Session() as session:
                existing = session.query(StockThesis).filter_by(symbol=sym).first()
                if existing:
                    existing.thesis_text = thesis_text
                    existing.target_price = float(target_price) if target_price else None
                    existing.timeframe = timeframe
                else:
                    session.add(StockThesis(
                        symbol=sym,
                        thesis_text=thesis_text,
                        target_price=float(target_price) if target_price else None,
                        timeframe=timeframe,
                    ))
                session.commit()
                row = session.query(StockThesis).filter_by(symbol=sym).first()
                entry = row.to_dict() if row else {}
                # Also save to JSON as backup
                try:
                    thesis = load_thesis()
                    thesis[sym] = entry
                    save_thesis(thesis)
                except Exception:
                    pass
                return entry
        except Exception as e:
            logger.debug("DB save thesis failed, using JSON: %s", e)

    # Fallback to JSON
    thesis = load_thesis()
    entry = {
        "symbol": sym,
        "thesis": thesis_text,
        "target_price": target_price,
        "timeframe": timeframe,
        "created_at": thesis.get(sym, {}).get("created_at", now_iso),
        "updated_at": now_iso,
    }
    thesis[sym] = entry
    save_thesis(thesis)
    return entry


def get_thesis(symbol):
    """Get personal thesis for a specific stock."""
    thesis = load_thesis()
    return thesis.get(symbol.upper())


def delete_thesis(symbol):
    """Delete personal thesis for a stock."""
    sym = symbol.upper()
    if _db_available():
        try:
            from db_manager import get_db, StockThesis
            db = get_db()
            with db.Session() as session:
                row = session.query(StockThesis).filter_by(symbol=sym).first()
                if row:
                    session.delete(row)
                    session.commit()
        except Exception:
            pass
    thesis = load_thesis()
    if sym in thesis:
        del thesis[sym]
        save_thesis(thesis)
        return True
    return False


def get_all_thesis():
    """Get all personal theses."""
    return load_thesis()
