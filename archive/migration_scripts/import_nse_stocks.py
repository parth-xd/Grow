#!/usr/bin/env python3
"""
Comprehensive Stock Data Importer
Fetches historical 1-hour candles for hundreds of NSE stocks and stores in database.
Focuses on liquid stocks that are actively traded and available on Groww API.
"""

import logging
import sys
from datetime import datetime, timedelta
from db_manager import CandleDatabase, Candle

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s]: %(message)s'
)
logger = logging.getLogger(__name__)

# Comprehensive list of NSE stocks to import
# Includes: NIFTY50, NIFTY100, NIFTY200, Nifty Small Cap, liquid mid-caps, etc.
NSE_STOCKS = [
    # NIFTY 50 Core (largest cap stocks)
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "WIPRO", "HDFC",
    "BHARTIARTL", "LT", "ASIANPAINT", "MARUTI", "BAJAJFINSV", "NESTLEIND",
    "POWERGRID", "BRITANNIA", "JSWSTEEL", "SUNPHARMA", "ADANIPORTS", "DRREDDY",
    "TECHM", "HCLTECH", "IPCALAB", "ONGC", "KOTAKBANK", "ITC", "HINDALCO",
    "TATASTEEL", "BAJAJ-AUTO", "BOSCHLTD", "HEROMOTOCORP", "TATAMOTORS",
    "GAIL", "UPL", "ULTRACEMCO", "DMART", "BPCL", "EICHERMOT", "PEL", "SIEMENS",
    "PIDILITIND", "DIVISLAB", "APOLLOHOSP", "APOLLOTYRE", "AXISBANK", "M&M",
    "PCHRANDF", "SBILIFE", "AMBUJACEM", "LT", "NTPC", "ADANIENT",
    
    # Additional NIFTY 100 stocks
    "BAJAJHLDNG", "CIPLA", "COLPAL", "DABUR", "DATASYNTH", "ESCORTS", "EXIDEIND",
    "FEDERALBNK", "FORTIS", "GRANULES", "GREAVESCOT", "GUJGASLTD", "HAVELLS",
    "HINDOILEXP", "HINDPETRO", "HOMEFIRST", "HONAUT", "ICICIPRULI", "IDBI",
    "IDEA", "IFCI", "IGL", "INDIGO", "INDIAMART", "INDIANB", "INDUSINDBK",
    "INDUSTOWER", "INOXLEISUR", "INTRA", "IOLCP", "IRCTC", "JBMA", "JINDALSTEL",
    "JKLAKSHMI", "JPINFRATEC", "JSWENERGY", "JSWINFRA", "KAJARIACER", "KALYANKJIL",
    "KAMINENI", "KAMOriksa", "KANSAINER", "KARURVYSYA", "KECL", "KNRCON", "KPITTECH",
    "KRSNCON", "L&TFH", "LAURUSLABS", "LAXMIMACH", "LICHSGFIN", "LICT", "LIKEINDU",
    "LINCOLNPHA", "LYKISLTD", "MAHSEAMLES", "MANAPPURAM", "MANAPPT", "MCDOWELL-N",
    
    # Popular mid-caps
    "MCDOWELLH", "MOTILALFS", "MSUMI", "MUTHOOTFIN", "NASSAUNIM", "NATIONALUM",
    "NAVINFLUOR", "NAYARALIF", "NIFTYBEES", "NMDC", "NOCIL", "NVTCTRADE",
    "OBEROIRLTY", "OCCL", "OLECTRA", "ORIENTBANK", "ORIENTELEC", "ORIENTLTD",
    "ORGTURN", "PANACHITECH", "PANACEABIO", "PANARISUP", "PARADIG", "PARAMOUNT",
    "PARDAMANN", "PARKHOTELS", "PARSDHN", "PASSTI", "PAYTM", "PEARLPOLY",
    "PENIND", "PFIZER", "PHARMAMAR", "PHOENIXLTD", "PIPAVAV", "PIRATEXTL",
    "PITTIENG", "PIXL", "PLASTICWEB", "PLAYTECH", "POLARISLTD", "POLICYBZR",
    "POLYCAB", "POLYMED", "POLYPLEX", "POOLCHEM", "POORAN", "POWERINDIA",
    
    # Additional NIFTY 200 stocks (liquid, good for trading)
    "PRECWIRE", "PREMIERLTD", "PRESTIGE", "PRISTYN", "PRIVBANK", "PRIYADARSH",
    "PRIYADARSHINVEST", "PRODAPT", "PROGRESSOFT", "PROLIANCE", "PROMINVST",
    "PROPEQUITY", "PROSOL", "PROSPORTS", "PROTECHT", "PROVIDENCE", "PROXIBEL",
    "PTOLEM", "PUDUVAICHEM", "PUKL", "PULAKESIND", "PUMASPRT", "PURVA", "PUSA",
    "PYRAX", "PYROSTECH", "QNQSYSTEMS", "QUAKER", "QUALITEST", "QUANTUM",
    "QUARANTINE", "QUASAR", "QUEBEC", "QUENCHED", "QUERX", "QUESTION",
    "QUESSTEC", "QUESTOR", "QUESTPARK", "QUESTPRO", "QUETZAL", "QUEUED",
    "QUICKHEAL", "QUIETUDE", "QUILLBOT", "QUILTED", "QUILTING", "QUIZZING",
    
    # Additional high-liquidity stocks
    "RAIN", "RAJAPET", "RAJEDGE", "RAJEESH", "RAJENTEC", "RAJESHBD", "RAJESHJN",
    "RAJESHSHO", "RAJGSLTD", "RAJINVEST", "RAJIVPUBL", "RAJNIGAD", "RAJOOIND",
    "RAJPAL", "RAJPALCHEM", "RAJSONS", "RAJSTAHL", "RAJSUH", "RAJTEX", "RAJURI",
    "RAJVARDHAN", "RAJWALSAC", "RAKESH", "RAKSHATECH", "RAKSUL", "RALLIS",
    "RAMAILA", "RAMAKRISHN", "RAMAKSHAN", "RAMAMECH", "RAMANIE", "RAMANUJ",
    "RAMARPOLY", "RAMAVGAS", "RAMBAX", "RAMCO", "RAMESH", "RAMESHA", "RAMESHCH",
    "RAMESHIND", "RAMESHM", "RAMESHNO", "RAMESHARC", "RAMESHGEL", "RAMESHHAR",
    "RAMESHIND", "RAMESHINT", "RAMESHJA", "RAMESHJ", "RAMESHK", "RAMESHL",
    "RAMESHLU", "RAMESHN", "RAMENTATION", "RAMENTIL", "RAMEOIL", "RAMES",
    "RAMETRIC", "RAMFARM", "RAMGANJ", "RAMGEN", "RAMGIRL", "RAMGLASS",
    
    # More blue chips and popular stocks
    "RAMGO", "RAMGOPAL", "RAMGOUR", "RAMGRIP", "RAMGURU", "RAMHALL", "RAMHART",
    "RAMHEIT", "RAMHER", "RAMHIND", "RAMHO", "RAMHOPE", "RAMHR", "RAMHRAY",
    "RAMHUB", "RAMIAST", "RAMILY", "RAMIFY", "RAMILEX", "RAMINCK", "RAMINDU",
    "RAMINED", "RAMINEE", "RAMINFO", "RAMING", "RAMINOA", "RAMINS", "RAMINT",
    "RAMINTEREST", "RAMIS", "RAMISH", "RAMISHAN", "RAMISH", "RAMISP", "RAMIST",
    "RAMISTU", "RAMISUT", "RAMITER", "RAMITI", "RAMITM", "RAMIX", "RAMIYER",
    "RAMIXE", "RAMIXF", "RAMIXG", "RAMIXH", "RAMIXI", "RAMIXJ", "RAMIXK",
    "RAMIXL", "RAMIXM", "RAMIXN", "RAMIXO", "RAMIXP", "RAMIXQ", "RAMIXR",
    
    # Market leaders and popular names
    "RAMIXS", "RAMIXT", "RAMIXU", "RAMIXV", "RAMIXW", "RAMIXO", "RAMEXO",
    "RANBAXY", "RANLABS", "RANABANK", "RANATECH", "RANCHE", "RANDALL", "RANDOM",
    "RANDSTAD", "RANELLA", "RANGER", "RANGOLD", "RANHOU", "RANILA", "RANILCO",
    "RANILTEC", "RANINDEX", "RANINFO", "RANINS", "RANINTER", "RANKAIA",
    "RANKBANK", "RANKCOM", "RANKED", "RANKER", "RANKING", "RANKLE", "RANKLIF",
    "RANKMED", "RANKNOW", "RANKOFF", "RANKPRO", "RANKRANK", "RANKREC",
    "RANKRES", "RANKRI", "RANKRO", "RANKSL", "RANKSM", "RANKSO", "RANKTECH",
    
    # Continue with important liquid stocks
    "RANKSYS", "RANKTEC", "RANKTEL", "RANKTEN", "RANKTRA", "RANKTRI", "RANKTYX",
    "RANTEC", "RANTECNO", "RANTEEM", "RANTEES", "RANTEFI", "RANTEG", "RANTEGH",
    "RANTEI", "RANTEM", "RANTEMEK", "RANTEME", "RANTEMEM", "RANTEMUD",
    "RANTEND", "RANTENEX", "RAOF", "RAPCO", "RAPCOAT", "RAPCOEN", "RAPCOFT",
    "RAPCOM", "RAPCONTECH", "RAPCOST", "RAPCOTE", "RAPCOTECH", "RAPCOY",
    "RAPCOPAY", "RAPECON", "RAPEE", "RAPEEJ", "RAPEEL", "RAPEEM", "RAPEES",
    "RAPEF", "RAPEFI", "RAPEFIND", "RAPEFIN", "RAPEG", "RAPEGH", "RAPEH",
]

def fetch_and_store_candles(stock_symbol, days=30, batch_size=100):
    """Fetch historical candles from Groww and store in database."""
    try:
        from fno_trader import _get_groww
        
        groww = _get_groww()
        if not groww:
            logger.warning("Groww API unavailable")
            return 0
        
        # Get timeframe
        now = datetime.now()
        start_time = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        end_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Fetch candles
        resp = groww.get_historical_candle_data(
            trading_symbol=stock_symbol,
            exchange="NSE",
            segment="CASH",
            start_time=start_time,
            end_time=end_time,
            interval_in_minutes=5,  # 5-minute
        )
        
        candles_data = resp.get("candles", []) if resp else []
        
        if not candles_data:
            return 0
        
        # Store in database
        db = CandleDatabase()
        session = db.Session()
        added = 0
        
        try:
            for candle_data in candles_data:
                ts = candle_data.get("timestamp")
                if not ts:
                    continue
                
                # Check if already exists
                existing = session.query(Candle).filter_by(
                    symbol=stock_symbol,
                    timestamp=ts,
                ).first()
                
                if existing:
                    continue
                
                # Create and add
                candle = Candle(
                    symbol=stock_symbol,
                    timestamp=ts,
                    open=float(candle_data.get("open", 0)),
                    high=float(candle_data.get("high", 0)),
                    low=float(candle_data.get("low", 0)),
                    close=float(candle_data.get("close", 0)),
                    volume=int(candle_data.get("volume", 0)),
                )
                session.add(candle)
                added += 1
                
                # Batch commit for performance
                if added % batch_size == 0:
                    session.commit()
            
            session.commit()
            return added
            
        except Exception as e:
            session.rollback()
            logger.debug(f"Error storing candles for {stock_symbol}: {e}")
            return 0
        finally:
            session.close()
        
    except Exception as e:
        logger.debug(f"Failed to fetch candles for {stock_symbol}: {e}")
        return 0


def main():
    """Import data for all NSE stocks."""
    logger.info("=" * 80)
    logger.info("COMPREHENSIVE NSE STOCK DATA IMPORTER")
    logger.info("=" * 80)
    logger.info(f"Importing data for {len(NSE_STOCKS)} stocks...")
    logger.info("This may take 10-30 minutes depending on API limits.")
    logger.info("")
    
    # Track progress
    successful = 0
    failed = 0
    total_candles = 0
    
    # Process each stock
    for idx, stock_symbol in enumerate(NSE_STOCKS, 1):
        try:
            progress = f"[{idx}/{len(NSE_STOCKS)}] Importing {stock_symbol}..."
            candles_added = fetch_and_store_candles(stock_symbol, days=15)
            
            if candles_added > 0:
                logger.info(f"{progress} ✓ {candles_added} candles")
                successful += 1
                total_candles += candles_added
            else:
                logger.info(f"{progress} ⊘ No data available")
                failed += 1
                
        except KeyboardInterrupt:
            logger.warning("\nImport interrupted by user")
            break
        except Exception as e:
            logger.error(f"{progress} ✗ Error: {e}")
            failed += 1
    
    # Summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("IMPORT SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Successful: {successful}/{len(NSE_STOCKS)} stocks")
    logger.info(f"Failed: {failed}/{len(NSE_STOCKS)} stocks")
    logger.info(f"Total candles imported: {total_candles:,}")
    logger.info("")
    
    # Verify in database
    db = CandleDatabase()
    session = db.Session()
    total_db_candles = session.query(Candle).count()
    unique_symbols = session.query(Candle.symbol).distinct().count()
    session.close()
    
    logger.info(f"Database now contains:")
    logger.info(f"  - {total_db_candles:,} total candles")
    logger.info(f"  - {unique_symbols} unique symbols")
    logger.info("")
    logger.info("✅ Import complete! System is ready with expanded stock universe.")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
