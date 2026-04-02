#!/usr/bin/env python3
"""
5-year 5-minute candle data generator.
75 candles per trading day (9:15–15:25 at 5-min intervals).
Uses numpy vectorized generation + raw SQL bulk insert for speed.
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from db_manager import CandleDatabase, Candle
from sqlalchemy import func, text

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

CANDLES_PER_DAY = 75  # 9:15 to 15:25 at 5-min intervals

# 75 timestamps per day: 9:15, 9:20, 9:25, ..., 15:20, 15:25
INTRADAY_MINUTES = [(9 * 60 + 15) + i * 5 for i in range(CANDLES_PER_DAY)]  # minutes from midnight


def get_stock_price_range(symbol):
    """Get realistic price range for a stock."""
    price_ranges = {
        "NIFTY": (15000, 25000), "BANKNIFTY": (30000, 50000), "FINNIFTY": (15000, 22000),
    }
    if symbol in price_ranges:
        return price_ranges[symbol]
    return (50, 2000)


def generate_trading_dates(years=5):
    """Pre-compute all trading dates (weekdays only) for the period."""
    now = datetime.now().replace(hour=15, minute=30, second=0, microsecond=0)
    start = now - timedelta(days=365 * years)
    dates = []
    d = start
    while d <= now:
        if d.weekday() < 5:  # Mon-Fri
            dates.append(d.date())
        d += timedelta(days=1)
    return dates


def generate_symbol_data_fast(symbol, trading_dates):
    """
    Generate 5-min candle data for one symbol using numpy vectorization.
    Returns list of dicts ready for bulk insert.
    """
    price_low, price_high = get_stock_price_range(symbol)
    n_days = len(trading_dates)
    n_total = n_days * CANDLES_PER_DAY

    # Generate price path via geometric brownian motion
    initial_price = np.random.uniform(price_low, price_high)

    # Per-5-min volatility: daily vol ~2% → per-candle vol = 2% / sqrt(75) ≈ 0.23%
    daily_vol = np.random.uniform(0.015, 0.03)
    candle_vol = daily_vol / np.sqrt(CANDLES_PER_DAY)

    # Slight upward drift (market tends up over 5 years)
    daily_drift = np.random.uniform(-0.0001, 0.0003)
    candle_drift = daily_drift / CANDLES_PER_DAY

    # Generate log returns
    returns = np.random.normal(candle_drift, candle_vol, n_total)

    # Add regime changes (trend shifts every ~500 candles = ~7 trading days)
    regime_len = np.random.randint(300, 800)
    for i in range(0, n_total, regime_len):
        chunk = min(regime_len, n_total - i)
        regime_drift = np.random.normal(0, 0.0004)
        returns[i:i + chunk] += regime_drift

    # Add seasonal volatility (monsoon season = higher vol)
    for day_idx, dt in enumerate(trading_dates):
        start_idx = day_idx * CANDLES_PER_DAY
        end_idx = start_idx + CANDLES_PER_DAY
        month = dt.month
        if 6 <= month <= 9:  # Monsoon / earnings season
            returns[start_idx:end_idx] *= 1.3
        elif 3 <= month <= 5:  # Budget / year-end
            returns[start_idx:end_idx] *= 0.85

    # Add opening/closing volatility spikes
    for day_idx in range(n_days):
        start_idx = day_idx * CANDLES_PER_DAY
        # First 6 candles (30 min) — opening volatility 2x
        returns[start_idx:start_idx + 6] *= 2.0
        # Last 6 candles (30 min) — closing volatility 1.5x
        end_idx = start_idx + CANDLES_PER_DAY
        returns[end_idx - 6:end_idx] *= 1.5

    # Build close price path
    log_prices = np.log(initial_price) + np.cumsum(returns)
    closes = np.exp(log_prices)

    # Generate OHLV from close path
    # For each candle: open ≈ prev close, high/low around open-close range
    opens = np.empty(n_total)
    opens[0] = initial_price
    opens[1:] = closes[:-1]

    # Add small gap opens at day boundaries
    for day_idx in range(1, n_days):
        idx = day_idx * CANDLES_PER_DAY
        gap = np.random.normal(0, 0.003)  # ~0.3% gap
        opens[idx] = closes[idx - 1] * (1 + gap)

    # High/Low: spread around the open-close range
    oc_max = np.maximum(opens, closes)
    oc_min = np.minimum(opens, closes)
    oc_range = np.maximum(oc_max - oc_min, closes * 0.001)  # minimum range

    highs = oc_max + np.abs(np.random.normal(0, 1, n_total)) * oc_range * 0.5
    lows = oc_min - np.abs(np.random.normal(0, 1, n_total)) * oc_range * 0.5

    # Ensure OHLC consistency
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    lows = np.maximum(lows, closes * 0.9)  # prevent unrealistic drops

    # Volume: higher at open/close, random otherwise
    base_volume = np.random.lognormal(mean=12, sigma=1, size=n_total).astype(int)
    for day_idx in range(n_days):
        start_idx = day_idx * CANDLES_PER_DAY
        # Opening 30min — 2x volume
        base_volume[start_idx:start_idx + 6] = (base_volume[start_idx:start_idx + 6] * 2)
        # Closing 30min — 1.8x volume
        end_idx = start_idx + CANDLES_PER_DAY
        base_volume[end_idx - 6:end_idx] = (base_volume[end_idx - 6:end_idx] * 1.8).astype(int)

    # Build timestamp array
    timestamps = []
    for dt in trading_dates:
        for mins in INTRADAY_MINUTES:
            h, m = divmod(mins, 60)
            timestamps.append(datetime(dt.year, dt.month, dt.day, h, m, 0))

    # Build list of dicts for bulk insert
    rows = []
    for i in range(n_total):
        rows.append({
            "symbol": symbol,
            "timestamp": timestamps[i],
            "open": round(float(opens[i]), 2),
            "high": round(float(highs[i]), 2),
            "low": round(float(lows[i]), 2),
            "close": round(float(closes[i]), 2),
            "volume": int(base_volume[i]),
        })

    return rows


def main():
    logger.info("=" * 80)
    logger.info("5-YEAR 5-MINUTE CANDLE GENERATOR")
    logger.info(f"{CANDLES_PER_DAY} candles/day × ~1300 trading days × 240 symbols")
    logger.info("=" * 80)

    db = CandleDatabase()
    db.init_db()

    # Pre-compute shared trading dates
    trading_dates = generate_trading_dates(years=5)
    logger.info(f"Trading dates: {len(trading_dates)} days ({trading_dates[0]} → {trading_dates[-1]})")
    logger.info(f"Expected candles per symbol: {len(trading_dates) * CANDLES_PER_DAY:,}")

    # Get all symbols
    session = db.Session()
    symbols_in_db = session.query(Candle.symbol).distinct().all()
    all_symbols = sorted(set([s[0] for s in symbols_in_db] + ["NIFTY", "BANKNIFTY", "FINNIFTY"]))
    session.close()

    logger.info(f"Symbols to generate: {len(all_symbols)}")
    logger.info("")

    # Raw SQL for fast bulk insert
    insert_sql = text(
        "INSERT INTO candles (symbol, timestamp, open, high, low, close, volume) "
        "VALUES (:symbol, :timestamp, :open, :high, :low, :close, :volume) "
        "ON CONFLICT (symbol, timestamp) DO UPDATE SET "
        "open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
        "close=EXCLUDED.close, volume=EXCLUDED.volume"
    )

    total_candles = 0
    for idx, symbol in enumerate(all_symbols, 1):
        try:
            # Generate all candles for this symbol
            rows = generate_symbol_data_fast(symbol, trading_dates)

            # Delete old data for this symbol
            with db.engine.begin() as conn:
                conn.execute(text("DELETE FROM candles WHERE symbol = :sym"), {"sym": symbol})

                # Bulk insert in batches of 5000
                batch_size = 5000
                for batch_start in range(0, len(rows), batch_size):
                    batch = rows[batch_start:batch_start + batch_size]
                    conn.execute(insert_sql, batch)

            total_candles += len(rows)
            logger.info(
                f"[{idx}/{len(all_symbols)}] {symbol}: ✓ {len(rows):,} candles "
                f"(₹{rows[-1]['close']:,.2f}) → Total: {total_candles:,}"
            )

        except Exception as e:
            logger.error(f"[{idx}/{len(all_symbols)}] {symbol}: ✗ {e}")

    logger.info("")
    logger.info("=" * 80)
    logger.info("GENERATION COMPLETE")
    logger.info(f"Total candles generated: {total_candles:,}")
    logger.info(f"Candles per symbol: ~{total_candles // max(len(all_symbols), 1):,}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
