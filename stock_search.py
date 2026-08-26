"""
Stock search and autocomplete service.
Reads from DB `stocks` table. Falls back to hardcoded directory if DB unavailable.
"""

import logging

logger = logging.getLogger(__name__)

# Fallback directory (used only if DB is unavailable)
_FALLBACK_DIRECTORY = {
    "RELIANCE": "Reliance Industries", "TCS": "Tata Consultancy Services",
    "INFY": "Infosys", "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank",
    "WIPRO": "Wipro", "BHARTIARTL": "Bharti Airtel", "ITC": "ITC",
    "SBIN": "State Bank of India", "LT": "Larsen & Toubro",
    "ASIANPAINT": "Asian Paints", "SUZLON": "Suzlon Energy",
    "GEMAROMA": "Gemaroma", "AXISBANK": "Axis Bank",
    "KOTAKBANK": "Kotak Mahindra Bank", "HINDUNILVR": "Hindustan Unilever",
    "DABUR": "Dabur India", "MARICO": "Marico",
    "GODREJCP": "Godrej Consumer Products", "TATAPOWER": "Tata Power",
    "ADANIGREEN": "Adani Green Energy", "INOXWIND": "Inox Wind",
    "JSWEN": "JSW Energy", "TECHM": "Tech Mahindra",
    "HCLTECH": "HCL Technologies", "LTI": "LTIMindtree",
    "AKZONOBEL": "Akzo Nobel India", "BERGEPAINT": "Berger Paints",
    "NEROLAC": "Nerolac Paints", "INDIGO": "Indigo Paints",
    "SIEMENS": "Siemens", "ABB": "ABB India", "BHEL": "BHEL",
    "THERMAX": "Thermax", "TATACOMM": "Tata Communications",
    "VODAFONEIDEA": "Vodafone Idea",
}


def _get_stock_directory():
    """Get stock directory from DB, falling back to hardcoded."""
    try:
        from db_manager import get_all_stocks
        stocks = get_all_stocks()
        if stocks:
            return {s.symbol: s.company_name for s in stocks}
    except Exception:
        pass
    return _FALLBACK_DIRECTORY


def _search_nse_instruments(query_upper, query_lower, seen, limit):
    """
    Search the master ticker table (the complete NSE directory) — search-only,
    not the active-tracking `stocks` table. Only active tickers are offered;
    an inactive/delisted ticker can still be reached by typing its exact
    symbol, since /api/watchlist/add never validates against this list.
    """
    if len(seen) >= limit:
        return []
    try:
        from db_manager import get_db, MasterTicker
        db = get_db()
        session = db.Session()
        try:
            rows = (
                session.query(MasterTicker.nse_ticker, MasterTicker.company_name)
                .filter(MasterTicker.is_active.is_(True))
                .filter(MasterTicker.nse_ticker.startswith(query_upper))
                .limit(limit)
                .all()
            )
            extra = []
            for symbol, name in rows:
                if symbol not in seen:
                    extra.append({"symbol": symbol, "name": name, "match_type": "symbol"})
                    seen.add(symbol)

            if len(seen) < limit:
                rows = (
                    session.query(MasterTicker.nse_ticker, MasterTicker.company_name)
                    .filter(MasterTicker.is_active.is_(True))
                    .filter(MasterTicker.company_name.ilike(f"%{query_lower}%"))
                    .limit(limit)
                    .all()
                )
                for symbol, name in rows:
                    if symbol not in seen:
                        extra.append({"symbol": symbol, "name": name, "match_type": "name"})
                        seen.add(symbol)
            return extra
        finally:
            session.close()
    except Exception:
        logger.debug("Master ticker table search unavailable", exc_info=True)
        return []


def search_stocks(query):
    if not query or len(query.strip()) < 1:
        return []

    directory = _get_stock_directory()
    query_upper = query.upper().strip()
    query_lower = query.lower()
    results = []
    seen = set()

    for symbol, name in directory.items():
        if symbol.startswith(query_upper):
            if symbol not in seen:
                results.append({"symbol": symbol, "name": name, "match_type": "symbol"})
                seen.add(symbol)

    for symbol, name in directory.items():
        if symbol not in seen and query_lower in name.lower():
            results.append({"symbol": symbol, "name": name, "match_type": "name"})
            seen.add(symbol)

    if len(results) < 20:
        results.extend(_search_nse_instruments(query_upper, query_lower, seen, 20 - len(results)))

    return results[:20]


def get_all_stocks():
    """Get all available stocks."""
    directory = _get_stock_directory()
    return [{"symbol": s, "name": n} for s, n in directory.items()]


def get_stock_name(symbol):
    """Get company name for a symbol."""
    try:
        from db_manager import get_stock_name as db_get_name
        return db_get_name(symbol)
    except Exception:
        return _FALLBACK_DIRECTORY.get(symbol.upper(), symbol.upper())


def validate_symbol(symbol):
    """Check if symbol exists."""
    directory = _get_stock_directory()
    return symbol.upper() in directory
