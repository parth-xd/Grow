import os
from dotenv import load_dotenv

load_dotenv(override=True)  # Override existing env vars with .env file (handles token refresh)

# Groww API credentials
GROWW_API_KEY = os.getenv("GROWW_API_KEY", "")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET", "")
GROWW_ACCESS_TOKEN = os.getenv("GROWW_ACCESS_TOKEN", "")

# Trading settings
DEFAULT_EXCHANGE = "NSE"
DEFAULT_SEGMENT = "CASH"
DEFAULT_PRODUCT = "CNC"
DEFAULT_VALIDITY = "DAY"
MAX_TRADE_QUANTITY = int(os.getenv("MAX_TRADE_QUANTITY", "1000"))  # Increased: no hard quantity limit
MAX_TRADE_VALUE = float(os.getenv("MAX_TRADE_VALUE", "999999999"))  # Increased: no hard value limit (uses available capital instead)

# AI model settings
PREDICTION_LOOKBACK_DAYS = 30  # 30 days of 5-min candles = ~2250 candles (good for ML training)
CANDLE_INTERVAL_MINUTES = 5   # 5-minute candles (75 candles/day)
CONFIDENCE_THRESHOLD = 0.65

# Watchlist (symbols to track)
WATCHLIST = os.getenv(
    "WATCHLIST",
    "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,WIPRO,BHARTIARTL,ITC,SBIN,LT"
).split(",")

# Risk management
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "2.0"))
TARGET_PCT = float(os.getenv("TARGET_PCT", "4.0"))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "5"))

# Server
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# Database settings
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "grow_trading_bot")
DB_URL = os.getenv("DB_URL", f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# News API (optional — get free key at https://newsapi.org)
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
