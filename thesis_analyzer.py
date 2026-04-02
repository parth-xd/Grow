"""
Thesis analyzer — Link personal theses with historical price data to show performance.
"""

import logging
import os
from datetime import datetime, date
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DB_URL")


class ThesisAnalyzer:
    """Analyze personal investment theses using historical price data."""
    
    def __init__(self, db_url=None):
        self.db_url = db_url or DB_URL
    
    def analyze_thesis_performance(self, thesis_id):
        """
        Analyze how a thesis has performed since entry.
        
        Args:
            thesis_id: ID of thesis to analyze
            
        Returns:
            Analysis dict with current return, max price, min price, etc.
        """
        try:
            conn = psycopg2.connect(self.db_url, connect_timeout=3)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get thesis details
            cursor.execute("""
                SELECT id, symbol, entry_price, target_price, quantity, created_date 
                FROM theses WHERE id = %s
            """, (thesis_id,))
            
            thesis = cursor.fetchone()
            if not thesis:
                logger.warning(f"Thesis {thesis_id} not found")
                return None
            
            symbol = thesis["symbol"]
            entry_price = thesis["entry_price"]
            entry_date = thesis["created_date"]
            
            # Get historical prices since entry
            cursor.execute("""
                SELECT date, close, high, low, volume 
                FROM stock_prices 
                WHERE symbol = %s AND date >= %s
                ORDER BY date ASC
            """, (symbol, entry_date))
            
            prices = cursor.fetchall()
            
            if not prices:
                logger.warning(f"No price data for {symbol} since {entry_date}")
                cursor.close()
                conn.close()
                return {
                    "symbol": symbol,
                    "status": "No price data available",
                    "entry_price": entry_price,
                    "target_price": thesis["target_price"],
                }
            
            # Calculate performance metrics
            current_price = prices[-1]["close"]
            max_price = max(p["close"] for p in prices)
            min_price = min(p["close"] for p in prices)
            
            days_held = (date.today() - entry_date).days
            
            current_return_pct = ((current_price - entry_price) / entry_price) * 100
            max_return_pct = ((max_price - entry_price) / entry_price) * 100
            target_return_pct = ((thesis["target_price"] - entry_price) / entry_price) * 100
            
            # Progress to target
            if target_return_pct != 0:
                progress_to_target = (current_return_pct / target_return_pct) * 100
            else:
                progress_to_target = 0
            
            analysis = {
                "thesis_id": thesis_id,
                "symbol": symbol,
                "entry_price": entry_price,
                "current_price": current_price,
                "target_price": thesis["target_price"],
                "entry_date": str(entry_date),
                "current_return_pct": round(current_return_pct, 2),
                "target_return_pct": round(target_return_pct, 2),
                "progress_to_target_pct": round(progress_to_target, 2),
                "days_held": days_held,
                "max_price": max_price,
                "max_return_pct": round(max_return_pct, 2),
                "min_price": min_price,
                "quantity": thesis["quantity"],
                "current_value": current_price * thesis["quantity"],
                "invested_value": entry_price * thesis["quantity"],
                "unrealised_pnl": (current_price - entry_price) * thesis["quantity"],
            }
            
            # Update thesis_analysis table
            cursor.execute("""
                INSERT INTO thesis_analysis 
                (thesis_id, symbol, entry_date, entry_price, target_price, 
                 current_price, days_held, current_return_pct, max_price, min_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (thesis_id) DO UPDATE SET
                    current_price = EXCLUDED.current_price,
                    current_return_pct = EXCLUDED.current_return_pct,
                    max_price = EXCLUDED.max_price,
                    min_price = EXCLUDED.min_price,
                    days_held = EXCLUDED.days_held,
                    last_updated = CURRENT_TIMESTAMP
            """, (
                thesis_id, symbol, entry_date, entry_price, thesis["target_price"],
                current_price, days_held, current_return_pct, max_price, min_price
            ))
            
            conn.commit()
            
            cursor.close()
            conn.close()
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing thesis: {e}")
            return None
    
    def update_current_price(self, symbol):
        """Update current price for a symbol from latest data."""
        try:
            conn = psycopg2.connect(self.db_url, connect_timeout=3)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT close FROM stock_prices 
                WHERE symbol = %s 
                ORDER BY date DESC 
                LIMIT 1
            """, (symbol,))
            
            result = cursor.fetchone()
            if result:
                current_price = result[0]
                
                # Update all theses for this symbol
                cursor.execute("""
                    UPDATE theses 
                    SET current_price = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE symbol = %s
                """, (current_price, symbol))
                
                conn.commit()
                logger.info(f"Updated {symbol} current price to ₹{current_price}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error updating price: {e}")
    
    def get_all_theses_with_performance(self):
        """Get all theses with their current performance."""
        try:
            conn = psycopg2.connect(self.db_url, connect_timeout=3)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT t.*, ta.current_price, ta.current_return_pct, ta.max_price
                FROM theses t
                LEFT JOIN thesis_analysis ta ON t.id = ta.thesis_id
                ORDER BY t.created_date DESC
            """)
            
            results = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return results
            
        except Exception as e:
            logger.error(f"Error fetching theses: {e}")
            return []


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    analyzer = ThesisAnalyzer()
    
    # Analyze a thesis (example)
    # result = analyzer.analyze_thesis_performance(1)
    # print(result)
    
    logger.info("ThesisAnalyzer ready to use")
