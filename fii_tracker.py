"""
FII & Mutual Fund Holdings Tracker
Fetch data on institutional holdings from Groww API and other sources
"""

import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def get_fii_holdings(symbol):
    """
    Get FII and Mutual Fund holdings for a stock.
    Returns dict with fiis and mutual_funds data.
    """
    try:
        from growwapi import GrowwAPI
        
        token = os.getenv("GROWW_ACCESS_TOKEN")
        if not token:
            return {"fiis": {}, "mutual_funds": {}}
        
        groww = GrowwAPI(token)
        
        # Fetch quote/company data which includes shareholding info
        quote = groww.get_quote(
            trading_symbol=symbol,
            exchange="NSE",
            segment="CASH"
        )
        
        if not quote or "quote" not in quote:
            return {"fiis": {}, "mutual_funds": {}}
        
        quote_data = quote.get("quote", {})
        
        # Try to extract shareholding info
        fiis = {}
        mutual_funds = {}
        
        # Some APIs return shareholding breakdown
        if "shareholding" in quote_data:
            shareholding = quote_data["shareholding"]
            if isinstance(shareholding, dict):
                fiis = shareholding.get("fiis", {})
                mutual_funds = shareholding.get("mutual_funds", {})
        
        return {
            "fiis": fiis,
            "mutual_funds": mutual_funds,
            "promoters": quote_data.get("promoter_holding"),
            "retail": quote_data.get("retail_holding"),
            "source": "groww_api"
        }
        
    except Exception as e:
        logger.warning(f"Failed to fetch FII holdings for {symbol}: {e}")
        return {"fiis": {}, "mutual_funds": {}}


def get_shareholding_breakdown(symbol):
    """
    Get complete shareholding breakdown: Promoters, FIIs, Mutual Funds, Retail, etc.
    Returns dict with all categories.
    """
    try:
        from growwapi import GrowwAPI
        
        token = os.getenv("GROWW_ACCESS_TOKEN")
        if not token:
            return {}
        
        groww = GrowwAPI(token)
        
        # Try to get shareholding data
        try:
            # Different API endpoints might have this
            quote = groww.get_quote(
                trading_symbol=symbol,
                exchange="NSE",
                segment="CASH"
            )
            
            if quote and "quote" in quote:
                quote_data = quote["quote"]
                breakdown = {}
                
                # Try various field names for shareholding
                if "promoter_holding" in quote_data:
                    breakdown["promoters"] = quote_data.get("promoter_holding", 0)
                if "fii_holding" in quote_data:
                    breakdown["fiis"] = quote_data.get("fii_holding", 0)
                if "mf_holding" in quote_data:
                    breakdown["mutual_funds"] = quote_data.get("mf_holding", 0)
                if "retail_holding" in quote_data:
                    breakdown["retail"] = quote_data.get("retail_holding", 0)
                
                if breakdown:
                    breakdown["source"] = "groww_quote"
                    return breakdown
        except:
            pass
        
        # If no real data available, return empty
        return {}
        
    except Exception as e:
        logger.warning(f"Failed to get shareholding for {symbol}: {e}")
        return {}



def format_institutional_holdings(symbol, analysis_dict):
    """
    Enrich analysis dict with institutional holdings data.
    Adds FII, MF, and shareholding breakdown.
    """
    try:
        shareholding = get_shareholding_breakdown(symbol)
        
        if shareholding:
            analysis_dict["fii_holdings"] = shareholding
            
            # Add formatted strings for display
            fii_pct = shareholding.get("fiis", 0)
            mf_pct = shareholding.get("mutual_funds", 0)
            promoter_pct = shareholding.get("promoters", 0)
            retail_pct = shareholding.get("retail", 0)
            
            holdings_summary = []
            if promoter_pct > 0:
                holdings_summary.append(f"Promoters: {promoter_pct:.1f}%")
            if fii_pct > 0:
                holdings_summary.append(f"FIIs: {fii_pct:.1f}%")
            if mf_pct > 0:
                holdings_summary.append(f"Mutual Funds: {mf_pct:.1f}%")
            if retail_pct > 0:
                holdings_summary.append(f"Retail: {retail_pct:.1f}%")
            
            if holdings_summary:
                analysis_dict["shareholding_summary"] = " | ".join(holdings_summary)
                
                # Add insights
                if fii_pct > 15:
                    analysis_dict["fii_signal"] = "STRONG_BUY"  # FIIs are bullish on this
                elif fii_pct > 8:
                    analysis_dict["fii_signal"] = "BUY"
                elif fii_pct < 3:
                    analysis_dict["fii_signal"] = "SELL"  # FIIs are bearish
                else:
                    analysis_dict["fii_signal"] = "NEUTRAL"
                
                if mf_pct > 12:
                    analysis_dict["mf_signal"] = "STRONG_BUY"  # MFs are bullish
                elif mf_pct > 6:
                    analysis_dict["mf_signal"] = "BUY"
                else:
                    analysis_dict["mf_signal"] = "NEUTRAL"
        
        return analysis_dict
        
    except Exception as e:
        logger.error(f"Error enriching holdings for {symbol}: {e}")
        return analysis_dict
