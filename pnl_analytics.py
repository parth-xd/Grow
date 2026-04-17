"""
Enhanced P&L endpoint with actual amounts and capital invested
"""

from flask import Blueprint, jsonify, current_app
from sqlalchemy import text
from datetime import datetime

pnl_bp = Blueprint('pnl', __name__)


def calculate_pnl_with_capital_session(session):
    """
    Calculate P&L with actual amounts and capital invested at each point
    Uses a SQLAlchemy session directly
    """
    query = """
    SELECT 
        DATE(entry_date) as trade_date,
        symbol,
        (entry_price * quantity) as capital_in_trade,
        actual_profit_pct,
        CASE 
            WHEN side = 'BUY' THEN (exit_price - entry_price) * quantity
            WHEN side = 'SELL' THEN (entry_price - exit_price) * quantity
            ELSE 0
        END as profit_amount
    FROM trade_journal
    WHERE status = 'CLOSED'
    ORDER BY entry_date ASC
    """
    
    result = session.execute(text(query))
    trades = result.fetchall()
    
    if not trades:
        return {
            "dates": [],
            "cumulative_pnl_amount": [],
            "peak_pnl_amount": [],
            "capital_invested": [],
            "roi_percentage": [],
            "trades": [],
            "summary": {
                "total_pnl": 0,
                "peak_pnl": 0,
                "total_capital": 0,
                "final_roi": 0,
                "total_trades": 0
            }
        }
    
    # Calculate cumulative metrics
    cumulative_pnl = 0
    peak_pnl = 0
    total_capital_invested = 0
    
    dates = []
    cumulative_pnl_amounts = []
    peak_pnl_amounts = []
    capital_invested_list = []
    roi_percentages = []
    trades_detailed = []
    
    for trade in trades:
        trade_date, symbol, capital, roi_pct, profit = trade
        
        # Handle None values
        capital = capital if capital is not None else 0
        profit = profit if profit is not None else 0
        roi_pct = roi_pct if roi_pct is not None else 0
        
        # Add to totals
        cumulative_pnl += profit
        total_capital_invested += capital
        peak_pnl = max(peak_pnl, cumulative_pnl)
        
        # Calculate current ROI
        current_roi = (cumulative_pnl / total_capital_invested * 100) if total_capital_invested > 0 else 0
        
        # Format date
        date_str = trade_date.strftime("%Y-%m-%d") if trade_date else datetime.now().strftime("%Y-%m-%d")
        
        dates.append(date_str)
        cumulative_pnl_amounts.append(round(cumulative_pnl, 2))
        peak_pnl_amounts.append(round(peak_pnl, 2))
        capital_invested_list.append(round(total_capital_invested, 2))
        roi_percentages.append(round(current_roi, 2))
        
        trades_detailed.append({
            "date": date_str,
            "symbol": symbol,
            "capital": round(capital, 2),
            "profit": round(profit, 2),
            "roi": round(roi_pct, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "capital_invested_total": round(total_capital_invested, 2)
        })
    
    return {
        "dates": dates,
        "cumulative_pnl_amount": cumulative_pnl_amounts,
        "peak_pnl_amount": peak_pnl_amounts,
        "capital_invested": capital_invested_list,
        "roi_percentage": roi_percentages,
        "trades": trades_detailed,
        "summary": {
            "total_pnl": cumulative_pnl_amounts[-1] if cumulative_pnl_amounts else 0,
            "peak_pnl": peak_pnl_amounts[-1] if peak_pnl_amounts else 0,
            "total_capital": capital_invested_list[-1] if capital_invested_list else 0,
            "final_roi": roi_percentages[-1] if roi_percentages else 0,
            "total_trades": len(trades_detailed)
        }
    }


@pnl_bp.route('/api/analytics/pnl', methods=['GET'])
def get_pnl_analytics():
    """Get P&L analytics with actual amounts and capital invested"""
    try:
        from auth import token_required
        from flask import request
        
        # Get user ID from JWT token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid authorization'}), 401
        
        token = auth_header.split(' ')[1]
        
        from auth import AuthManager
        auth_manager = AuthManager(current_app.db)
        user_info = auth_manager.verify_jwt(token)
        
        if not user_info:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        user_id = user_info['user_id']
        
        session = current_app.db.Session()
        try:
            # Query only this user's trades
            result = session.execute(text("""
                SELECT 
                    DATE(entry_date) as trade_date,
                    symbol,
                    (entry_price * quantity) as capital_in_trade,
                    actual_profit_pct,
                    CASE 
                        WHEN side = 'BUY' THEN (exit_price - entry_price) * quantity
                        WHEN side = 'SELL' THEN (entry_price - exit_price) * quantity
                        ELSE 0
                    END as profit_amount
                FROM trade_journal
                WHERE status = 'CLOSED' AND user_id = CAST(:user_id AS uuid)
                ORDER BY entry_date ASC
            """), {'user_id': user_id})
            trades = result.fetchall()
            
            if not trades:
                return jsonify({
                    "dates": [],
                    "cumulative_pnl_amount": [],
                    "peak_pnl_amount": [],
                    "capital_invested": [],
                    "roi_percentage": [],
                    "trades": [],
                    "summary": {
                        "total_pnl": 0,
                        "peak_pnl": 0,
                        "total_capital": 0,
                        "final_roi": 0,
                        "total_trades": 0
                    }
                })
            
            # Calculate cumulative metrics
            cumulative_pnl = 0
            peak_pnl = 0
            total_capital_invested = 0
            
            dates = []
            cumulative_pnl_amounts = []
            peak_pnl_amounts = []
            capital_invested_list = []
            roi_percentages = []
            trades_detailed = []
            
            for trade in trades:
                trade_date, symbol, capital, roi_pct, profit = trade
                
                # Handle None values
                capital = capital if capital is not None else 0
                profit = profit if profit is not None else 0
                roi_pct = roi_pct if roi_pct is not None else 0
                
                # Add to totals
                cumulative_pnl += profit
                total_capital_invested += capital
                peak_pnl = max(peak_pnl, cumulative_pnl)
                
                # Calculate current ROI
                current_roi = (cumulative_pnl / total_capital_invested * 100) if total_capital_invested > 0 else 0
                
                # Format date
                date_str = trade_date.strftime("%Y-%m-%d") if trade_date else datetime.now().strftime("%Y-%m-%d")
                
                dates.append(date_str)
                cumulative_pnl_amounts.append(round(cumulative_pnl, 2))
                peak_pnl_amounts.append(round(peak_pnl, 2))
                capital_invested_list.append(round(total_capital_invested, 2))
                roi_percentages.append(round(current_roi, 2))
                
                trades_detailed.append({
                    "date": date_str,
                    "symbol": symbol,
                    "capital": round(capital, 2),
                    "profit": round(profit, 2),
                    "roi": round(roi_pct, 2),
                    "cumulative_pnl": round(cumulative_pnl, 2),
                    "capital_invested_total": round(total_capital_invested, 2)
                })
            
            return jsonify({
                "dates": dates,
                "cumulative_pnl_amount": cumulative_pnl_amounts,
                "peak_pnl_amount": peak_pnl_amounts,
                "capital_invested": capital_invested_list,
                "roi_percentage": roi_percentages,
                "trades": trades_detailed,
                "summary": {
                    "total_pnl": cumulative_pnl_amounts[-1] if cumulative_pnl_amounts else 0,
                    "peak_pnl": peak_pnl_amounts[-1] if peak_pnl_amounts else 0,
                    "total_capital": capital_invested_list[-1] if capital_invested_list else 0,
                    "final_roi": roi_percentages[-1] if roi_percentages else 0,
                    "total_trades": len(trades_detailed)
                }
            })
        finally:
            session.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        current_app.logger.error(f"P&L analytics error: {e}")
        return jsonify({"error": str(e)}), 500


@pnl_bp.route('/api/analytics/pnl/summary', methods=['GET'])
def get_pnl_summary():
    """Get P&L summary statistics"""
    try:
        session = current_app.db.Session()
        try:
            data = calculate_pnl_with_capital_session(session)
            return jsonify(data["summary"])
        finally:
            session.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
