"""
Personal Stock Thesis Manager — store and manage investment theses.
Track entry price, target price, profit projections, and commentary.
Now backed by PostgreSQL StockThesis table with JSON file fallback.
"""

import logging
import json
from datetime import datetime
from pathlib import Path
import costs

logger = logging.getLogger(__name__)

# Store theses in a JSON file (backup)
THESES_FILE = Path(__file__).parent / ".theses.json"


class Thesis:
    """Individual investment thesis."""
    
    def __init__(self, symbol, target_price, entry_price=None, quantity=None, 
                 comments=None, timestamp=None):
        self.symbol = symbol.upper()
        self.target_price = float(target_price)
        self.entry_price = float(entry_price) if entry_price else None
        self.quantity = int(quantity) if quantity else None
        self.comments = comments or ""
        self.timestamp = timestamp or datetime.now().isoformat()
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "target_price": self.target_price,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "comments": self.comments,
            "timestamp": self.timestamp,
        }
    
    @staticmethod
    def from_dict(data):
        return Thesis(
            symbol=data["symbol"],
            target_price=data["target_price"],
            entry_price=data.get("entry_price"),
            quantity=data.get("quantity"),
            comments=data.get("comments", ""),
            timestamp=data.get("timestamp"),
        )
    
    def calculate_projection(self, current_price, quantity=None, product="CNC", exchange="NSE"):
        """Calculate profit/loss projection if stock moves to target."""
        qty = quantity or self.quantity or 1
        entry = self.entry_price or current_price
        
        price_diff = self.target_price - entry
        gross_profit = price_diff * qty
        gross_profit_pct = (price_diff / entry * 100) if entry > 0 else 0
        
        try:
            cost_info = costs.net_profit(
                entry, self.target_price, qty,
                product=product, exchange=exchange
            )
            net_profit = cost_info.get("net_profit", gross_profit)
            net_profit_pct = (net_profit / (entry * qty) * 100) if entry > 0 else 0
            total_charges = cost_info.get("total_charges", 0)
            taxes = cost_info.get("taxes", 0)
        except Exception as e:
            logger.warning(f"Cost calculation failed: {e}")
            net_profit = gross_profit
            net_profit_pct = gross_profit_pct
            total_charges = 0
            taxes = 0
        
        return {
            "symbol": self.symbol,
            "entry_price": entry,
            "current_price": current_price,
            "target_price": self.target_price,
            "quantity": qty,
            "investment": round(entry * qty, 2),
            "current_value": round(current_price * qty, 2),
            "value_at_target": round(self.target_price * qty, 2),
            "gross_profit_at_target": round(gross_profit, 2),
            "gross_profit_pct": round(gross_profit_pct, 2),
            "total_charges": round(total_charges, 2),
            "taxes": round(taxes, 2),
            "net_profit_at_target": round(net_profit, 2),
            "net_profit_pct": round(net_profit_pct, 2),
            "distance_to_target_pct": round((self.target_price - current_price) / current_price * 100, 2),
            "distance_to_target_rs": round(self.target_price - current_price, 2),
            "comments": self.comments,
            "created_at": self.timestamp,
        }


class ThesisManager:
    """Manage collection of investment theses — DB-backed with JSON fallback."""
    
    def __init__(self):
        self.theses = {}
        self._load()
    
    def _load(self):
        """Load theses from DB first, fall back to JSON file."""
        # Try DB
        try:
            from db_manager import get_db, StockThesis
            db = get_db()
            with db.Session() as session:
                rows = session.query(StockThesis).all()
                if rows:
                    self.theses = {}
                    for r in rows:
                        self.theses[r.symbol] = Thesis(
                            symbol=r.symbol,
                            target_price=r.target_price or 0,
                            entry_price=r.entry_price,
                            quantity=r.quantity,
                            comments=r.comments or "",
                            timestamp=r.created_at.isoformat() if r.created_at else None,
                        )
                    logger.debug(f"Loaded {len(self.theses)} theses from DB")
                    return
        except Exception as e:
            logger.debug(f"DB thesis load failed: {e}")
        # Fallback to JSON
        try:
            if THESES_FILE.exists():
                with open(THESES_FILE, 'r') as f:
                    data = json.load(f)
                    self.theses = {
                        symbol: Thesis.from_dict(thesis_data)
                        for symbol, thesis_data in data.items()
                    }
                logger.debug(f"Loaded {len(self.theses)} theses from JSON")
        except Exception as e:
            logger.error(f"Failed to load theses: {e}")
            self.theses = {}
    
    def _save(self):
        """Save theses to DB and JSON file."""
        # Save to JSON (backup)
        try:
            with open(THESES_FILE, 'w') as f:
                json.dump(
                    {symbol: thesis.to_dict() for symbol, thesis in self.theses.items()},
                    f, indent=2
                )
        except Exception as e:
            logger.error(f"Failed to save theses to file: {e}")
    
    def _save_to_db(self, thesis):
        """Persist a single thesis to DB."""
        try:
            from db_manager import get_db, StockThesis
            db = get_db()
            with db.Session() as session:
                existing = session.query(StockThesis).filter_by(symbol=thesis.symbol).first()
                if existing:
                    existing.target_price = thesis.target_price
                    existing.entry_price = thesis.entry_price
                    existing.quantity = thesis.quantity
                    existing.comments = thesis.comments
                else:
                    session.add(StockThesis(
                        symbol=thesis.symbol,
                        target_price=thesis.target_price,
                        entry_price=thesis.entry_price,
                        quantity=thesis.quantity,
                        comments=thesis.comments,
                    ))
                session.commit()
        except Exception as e:
            logger.debug(f"DB save thesis failed (non-fatal): {e}")
    
    def add_thesis(self, symbol, target_price, entry_price=None, quantity=None, comments=None):
        """Add or update a thesis."""
        thesis = Thesis(symbol, target_price, entry_price, quantity, comments)
        self.theses[symbol.upper()] = thesis
        self._save()
        self._save_to_db(thesis)
        return thesis
    
    def get_thesis(self, symbol):
        """Get a specific thesis."""
        return self.theses.get(symbol.upper())
    
    def get_all_theses(self):
        """Get all theses."""
        return list(self.theses.values())
    
    def delete_thesis(self, symbol):
        """Delete a thesis."""
        symbol_upper = symbol.upper()
        if symbol_upper in self.theses:
            del self.theses[symbol_upper]
            self._save()
            try:
                from db_manager import get_db, StockThesis
                db = get_db()
                with db.Session() as session:
                    row = session.query(StockThesis).filter_by(symbol=symbol_upper).first()
                    if row:
                        session.delete(row)
                        session.commit()
            except Exception:
                pass
            return True
        return False
    
    def get_projection(self, symbol, current_price, quantity=None, **kwargs):
        """Get profit projection for a thesis."""
        thesis = self.get_thesis(symbol)
        if not thesis:
            return None
        return thesis.calculate_projection(current_price, quantity, **kwargs)


# Global instance
_manager = None


def get_manager():
    """Get thesis manager instance."""
    global _manager
    if _manager is None:
        _manager = ThesisManager()
    return _manager
