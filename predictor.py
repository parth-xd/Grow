"""
AI Price Prediction Engine
Uses technical indicators + ML to predict price movements and generate signals.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

from costs import min_profitable_move


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger(series, period=20, std_dev=2):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def compute_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def compute_vwap(high, low, close, volume):
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


# ── SMM Course Indicators ────────────────────────────────────────────────────

def compute_stochastic(high, low, close, k_period=14, d_period=3):
    """Stochastic Oscillator (%K and %D) — SMM Part 4: Oscillators."""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    k = 100 * (close - lowest_low) / denom
    d = k.rolling(window=d_period).mean()
    return k, d


def detect_candlestick_patterns(open_, high, low, close):
    """
    Detect candlestick patterns from SMM Part 1:
    Hammer, Inverted Hammer, Bullish/Bearish Engulfing,
    Morning/Evening Star, Doji, Bullish/Bearish Piercing.
    Returns a DataFrame of pattern signals (-1 to +1).
    """
    body = close - open_
    body_abs = body.abs()
    upper_shadow = high - pd.concat([close, open_], axis=1).max(axis=1)
    lower_shadow = pd.concat([close, open_], axis=1).min(axis=1) - low
    candle_range = (high - low).replace(0, np.nan)

    patterns = pd.DataFrame(index=close.index)

    # Doji — body is tiny relative to range (neutral, indecision)
    patterns["doji"] = (body_abs / candle_range < 0.1).astype(float)

    # Hammer — small body at top, long lower shadow (bullish reversal at bottom)
    is_hammer = (lower_shadow > 2 * body_abs) & (upper_shadow < body_abs * 0.5) & (body_abs > 0)
    patterns["hammer"] = is_hammer.astype(float)

    # Inverted Hammer / Shooting Star — small body at bottom, long upper shadow
    is_inv_hammer = (upper_shadow > 2 * body_abs) & (lower_shadow < body_abs * 0.5) & (body_abs > 0)
    patterns["inverted_hammer"] = is_inv_hammer.astype(float)

    # Bullish Engulfing — bearish candle followed by larger bullish candle
    prev_bearish = body.shift(1) < 0
    curr_bullish = body > 0
    engulfs = (open_ <= close.shift(1)) & (close >= open_.shift(1))
    patterns["bullish_engulfing"] = (prev_bearish & curr_bullish & engulfs).astype(float)

    # Bearish Engulfing — bullish candle followed by larger bearish candle
    prev_bullish = body.shift(1) > 0
    curr_bearish = body < 0
    engulfs_bear = (open_ >= close.shift(1)) & (close <= open_.shift(1))
    patterns["bearish_engulfing"] = (prev_bullish & curr_bearish & engulfs_bear).astype(float)

    # Bullish Piercing — bearish then bullish closing above midpoint of prior candle
    prior_mid = (open_.shift(1) + close.shift(1)) / 2
    patterns["bullish_piercing"] = (prev_bearish & curr_bullish & (close > prior_mid) & (open_ <= close.shift(1))).astype(float)

    # Bearish Piercing (Dark Cloud Cover)
    patterns["bearish_piercing"] = (prev_bullish & curr_bearish & (close < prior_mid) & (open_ >= close.shift(1))).astype(float)

    # Morning Star — 3-candle bullish reversal
    candle_m2_small = body_abs.shift(1) / candle_range.shift(1) < 0.3
    candle_m3_bullish = body > 0
    candle_m1_bearish = body.shift(2) < 0
    closes_above_mid = close > (open_.shift(2) + close.shift(2)) / 2
    patterns["morning_star"] = (candle_m1_bearish & candle_m2_small & candle_m3_bullish & closes_above_mid).astype(float)

    # Evening Star — 3-candle bearish reversal
    candle_e1_bullish = body.shift(2) > 0
    candle_e3_bearish = body < 0
    closes_below_mid = close < (open_.shift(2) + close.shift(2)) / 2
    patterns["evening_star"] = (candle_e1_bullish & candle_m2_small & candle_e3_bearish & closes_below_mid).astype(float)

    return patterns


def compute_fibonacci_levels(high, low, close, lookback=50):
    """
    Fibonacci Retracement levels — SMM Part 2.
    Returns distance from current price to key Fib levels as features.
    """
    rolling_high = high.rolling(window=lookback).max()
    rolling_low = low.rolling(window=lookback).min()
    fib_range = (rolling_high - rolling_low).replace(0, np.nan)

    features = pd.DataFrame(index=close.index)
    for level, ratio in [("236", 0.236), ("382", 0.382), ("500", 0.500), ("618", 0.618), ("786", 0.786)]:
        fib_price = rolling_high - fib_range * ratio
        features[f"fib_{level}_dist"] = (close - fib_price) / close
    return features


def compute_support_resistance(high, low, close, window=20):
    """
    Dynamic Support & Resistance — SMM Part 2.
    Uses rolling pivot-based levels.
    """
    pivot = (high.rolling(window).max() + low.rolling(window).min() + close) / 3
    resistance = 2 * pivot - low.rolling(window).min()
    support = 2 * pivot - high.rolling(window).max()

    features = pd.DataFrame(index=close.index)
    features["support_dist"] = (close - support) / close
    features["resistance_dist"] = (resistance - close) / close
    features["sr_position"] = (close - support) / (resistance - support).replace(0, np.nan)
    return features


def detect_divergence(close, indicator, lookback=14):
    """
    Bullish/Bearish Divergence — SMM Part 4.
    Compares price lows/highs with indicator lows/highs.
    Returns +1 (bullish divergence), -1 (bearish), 0 (none).
    """
    result = pd.Series(0.0, index=close.index)

    price_low = close.rolling(lookback).min()
    price_high = close.rolling(lookback).max()
    ind_low = indicator.rolling(lookback).min()
    ind_high = indicator.rolling(lookback).max()

    prev_price_low = price_low.shift(lookback)
    prev_ind_low = ind_low.shift(lookback)
    prev_price_high = price_high.shift(lookback)
    prev_ind_high = ind_high.shift(lookback)

    # Bullish divergence: price makes lower low, indicator makes higher low
    bullish = (price_low < prev_price_low) & (ind_low > prev_ind_low)
    # Bearish divergence: price makes higher high, indicator makes lower high
    bearish = (price_high > prev_price_high) & (ind_high < prev_ind_high)

    result[bullish] = 1.0
    result[bearish] = -1.0
    return result


def build_features(df):
    """Build feature matrix from OHLCV candle data."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    features = pd.DataFrame(index=df.index)

    # Moving averages
    for period in [5, 10, 20, 50]:
        sma = close.rolling(window=period).mean()
        features[f"sma_{period}_ratio"] = close / sma.replace(0, np.nan)

    # EMA ratios
    for period in [9, 21]:
        ema = close.ewm(span=period).mean()
        features[f"ema_{period}_ratio"] = close / ema.replace(0, np.nan)

    # RSI
    features["rsi_14"] = compute_rsi(close, 14)

    # MACD
    macd_line, signal_line, histogram = compute_macd(close)
    features["macd"] = macd_line
    features["macd_signal"] = signal_line
    features["macd_histogram"] = histogram

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = compute_bollinger(close)
    features["bb_position"] = (close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)
    features["bb_width"] = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)

    # ATR (volatility)
    features["atr_14"] = compute_atr(high, low, close, 14) / close

    # Volume features
    vol_sma = volume.rolling(window=20).mean()
    features["volume_ratio"] = volume / vol_sma.replace(0, np.nan)

    # Price momentum
    for period in [1, 3, 5, 10]:
        features[f"return_{period}"] = close.pct_change(period)

    # High-Low range
    features["hl_range"] = (high - low) / close

    # VWAP distance
    vwap = compute_vwap(high, low, close, volume)
    features["vwap_distance"] = (close - vwap) / close

    # ── SMM Course Features ──────────────────────────────────────────────

    # EMA Crossovers (SMM Part 2: positive/negative crossover signals)
    ema_9 = close.ewm(span=9).mean()
    ema_21 = close.ewm(span=21).mean()
    ema_50 = close.ewm(span=50).mean()
    ema_100 = close.ewm(span=100).mean()
    features["ema_9_21_cross"] = (ema_9 - ema_21) / close  # positive = bullish crossover zone
    features["ema_50_100_cross"] = (ema_50 - ema_100) / close  # long-term trend crossover

    # Stochastic Oscillator (SMM Part 4)
    stoch_k, stoch_d = compute_stochastic(high, low, close)
    features["stochastic_k"] = stoch_k
    features["stochastic_d"] = stoch_d
    features["stochastic_cross"] = stoch_k - stoch_d  # K above D = bullish

    # Candlestick Patterns (SMM Part 1)
    candle_patterns = detect_candlestick_patterns(df["open"], high, low, close)
    for col in candle_patterns.columns:
        features[f"candle_{col}"] = candle_patterns[col]

    # Fibonacci Retracement (SMM Part 2)
    fib_features = compute_fibonacci_levels(high, low, close)
    for col in fib_features.columns:
        features[col] = fib_features[col]

    # Support & Resistance (SMM Part 2)
    sr_features = compute_support_resistance(high, low, close)
    for col in sr_features.columns:
        features[col] = sr_features[col]

    # RSI Divergence (SMM Part 4)
    rsi = compute_rsi(close, 14)
    features["rsi_divergence"] = detect_divergence(close, rsi, lookback=14)

    # Stochastic Divergence (SMM Part 4)
    features["stoch_divergence"] = detect_divergence(close, stoch_k, lookback=14)

    # DOW Theory: Volume confirms trend (SMM Part 1)
    price_up = close.pct_change(5) > 0
    vol_up = volume.rolling(5).mean() > volume.rolling(20).mean()
    # Healthy trend = price & volume moving together
    features["dow_volume_confirm"] = (price_up & vol_up).astype(float) - (~price_up & vol_up).astype(float)

    # ── Environment / Context Features ───────────────────────────────────

    if "datetime" in df.columns:
        dt = pd.to_datetime(df["datetime"])

        # Day of week (Mon=0 .. Fri=4) — different behavior by day
        features["day_of_week"] = dt.dt.dayofweek.astype(float) / 4.0  # normalized 0-1

        # Time of day — normalized position in trading session (9:15=0, 15:25=1)
        minutes_from_open = (dt.dt.hour * 60 + dt.dt.minute) - (9 * 60 + 15)
        features["time_of_day"] = (minutes_from_open / 370.0).clip(0, 1).astype(float)

        # Session phase: opening rush (0-30min), mid-session, closing action (last 30min)
        features["is_opening"] = (minutes_from_open <= 30).astype(float)
        features["is_closing"] = (minutes_from_open >= 340).astype(float)

        # Detect session boundaries (new trading day)
        date_col = dt.dt.date
        new_session = (date_col != date_col.shift(1)).astype(bool)

        # Gap open: (first candle open - previous session last close) / prev close
        prev_close = close.shift(1)
        gap = (df["open"] - prev_close) / prev_close.replace(0, np.nan)
        # Only mark as gap on the first candle of each session
        features["gap_open"] = gap.where(new_session, 0.0).fillna(0.0)

        # Previous session return: total return of prior trading day
        session_id = new_session.cumsum()
        session_first_open = df["open"].groupby(session_id).transform("first")
        session_last_close = close.groupby(session_id).transform("last")
        session_return = (session_last_close - session_first_open) / session_first_open.replace(0, np.nan)
        features["prev_session_return"] = session_return.shift(1).fillna(0.0)
        # Forward-fill prev_session_return within each session
        features["prev_session_return"] = features["prev_session_return"].where(new_session).ffill().fillna(0.0)

        # Intraday position: how far current price is from today's open
        features["intraday_return"] = (close - session_first_open) / session_first_open.replace(0, np.nan)

        # Candles elapsed in current session (0/74 normalized)
        candle_in_session = session_id.groupby(session_id).cumcount()
        features["session_progress"] = (candle_in_session / 74.0).clip(0, 1).astype(float)
    else:
        # Fallback if no datetime (shouldn't happen but safe)
        for col in ["day_of_week", "time_of_day", "is_opening", "is_closing",
                     "gap_open", "prev_session_return", "intraday_return", "session_progress"]:
            features[col] = 0.0

    return features


def create_labels(close, forward_periods=5, threshold=None, quantity=10, product="CNC"):
    """
    Create classification labels using cost-aware thresholds.
    The threshold is dynamically set to the breakeven % so the model
    only learns to signal trades that would be profitable after all charges.
    1 = BUY  (price goes up enough to cover costs + buffer)
    0 = HOLD (move too small to profit after charges)
    -1 = SELL (price drops enough to warrant exit)
    """
    if threshold is None:
        # Use median price to estimate breakeven cost %
        median_price = float(close.median())
        if median_price > 0:
            info = min_profitable_move(median_price, quantity, product=product)
            # Require 1.5x the breakeven to have a real profit margin
            threshold = info["min_move_pct"] / 100 * 1.5
        else:
            threshold = 0.01  # fallback
        # Ensure a minimum floor
        threshold = max(threshold, 0.005)

    future_return = close.shift(-forward_periods) / close - 1
    labels = pd.Series(0, index=close.index)
    labels[future_return > threshold] = 1
    labels[future_return < -threshold] = -1
    return labels


class PricePredictor:
    def __init__(self):
        self.model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
        )
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_columns = None

    def train(self, df):
        """
        Train model on historical OHLCV data.
        df must have columns: open, high, low, close, volume
        """
        if len(df) < 100:
            return {"success": False, "message": "Not enough data (need at least 100 candles)"}

        features = build_features(df)
        labels = create_labels(df["close"])

        # Align and drop NaN rows
        combined = pd.concat([features, labels.rename("label")], axis=1).dropna()
        if len(combined) < 50:
            return {"success": False, "message": "Not enough valid data after feature computation"}

        X = combined.drop("label", axis=1)
        y = combined["label"]

        self.feature_columns = X.columns.tolist()
        X_scaled = self.scaler.fit_transform(X)

        self.model.fit(X_scaled, y)
        self.is_trained = True

        train_accuracy = self.model.score(X_scaled, y)
        return {
            "success": True,
            "message": f"Model trained on {len(X)} samples",
            "accuracy": round(train_accuracy, 4),
        }

    def predict(self, df):
        """
        Generate prediction for the latest data point.
        Returns signal, confidence, and predicted direction.
        """
        if not self.is_trained:
            return {"signal": "HOLD", "confidence": 0, "reason": "Model not trained"}

        features = build_features(df)
        latest = features.iloc[[-1]].dropna(axis=1)

        # Ensure columns match training
        missing = set(self.feature_columns) - set(latest.columns)
        for col in missing:
            latest[col] = 0
        latest = latest[self.feature_columns]

        if latest.isna().any().any():
            return {"signal": "HOLD", "confidence": 0, "reason": "Insufficient data"}

        X_scaled = self.scaler.transform(latest)
        prediction = self.model.predict(X_scaled)[0]
        probabilities = self.model.predict_proba(X_scaled)[0]
        confidence = float(max(probabilities))

        signal_map = {1: "BUY", 0: "HOLD", -1: "SELL"}
        signal = signal_map.get(prediction, "HOLD")

        # Technical analysis summary
        close = df["close"].iloc[-1]
        rsi = compute_rsi(df["close"], 14).iloc[-1]
        macd_line, signal_line, _ = compute_macd(df["close"])
        sma_20 = df["close"].rolling(20).mean().iloc[-1]
        sma_50 = df["close"].rolling(50).mean().iloc[-1]

        # SMM indicators
        stoch_k, stoch_d = compute_stochastic(df["high"], df["low"], df["close"])
        ema_9 = df["close"].ewm(span=9).mean()
        ema_21 = df["close"].ewm(span=21).mean()
        candle_patterns = detect_candlestick_patterns(df["open"], df["high"], df["low"], df["close"])
        rsi_div = detect_divergence(df["close"], compute_rsi(df["close"], 14))

        # Active candlestick patterns on the latest bar
        active_patterns = [col for col in candle_patterns.columns if candle_patterns[col].iloc[-1] > 0]

        indicators = {
            "rsi": round(float(rsi), 2) if not np.isnan(rsi) else None,
            "macd": round(float(macd_line.iloc[-1]), 4) if not np.isnan(macd_line.iloc[-1]) else None,
            "macd_signal": round(float(signal_line.iloc[-1]), 4) if not np.isnan(signal_line.iloc[-1]) else None,
            "sma_20": round(float(sma_20), 2) if not np.isnan(sma_20) else None,
            "sma_50": round(float(sma_50), 2) if not np.isnan(sma_50) else None,
            "price": round(float(close), 2),
            "trend": "BULLISH" if sma_20 > sma_50 else "BEARISH",
            "stoch_k": round(float(stoch_k.iloc[-1]), 2) if not np.isnan(stoch_k.iloc[-1]) else None,
            "stoch_d": round(float(stoch_d.iloc[-1]), 2) if not np.isnan(stoch_d.iloc[-1]) else None,
            "ema_crossover": "BULLISH" if float(ema_9.iloc[-1]) > float(ema_21.iloc[-1]) else "BEARISH",
            "candle_patterns": active_patterns,
        }

        # Build reason string from SMM concepts
        reason_parts = []
        if rsi and not np.isnan(rsi):
            if rsi > 70:
                reason_parts.append("RSI overbought")
            elif rsi < 30:
                reason_parts.append("RSI oversold")
        if sma_20 and sma_50 and not np.isnan(sma_20) and not np.isnan(sma_50):
            if sma_20 > sma_50:
                reason_parts.append("SMA bullish crossover")
            else:
                reason_parts.append("SMA bearish crossover")

        # EMA crossover signals (SMM Part 2)
        if float(ema_9.iloc[-1]) > float(ema_21.iloc[-1]) and float(ema_9.iloc[-2]) <= float(ema_21.iloc[-2]):
            reason_parts.append("EMA positive crossover (buy)")
        elif float(ema_9.iloc[-1]) < float(ema_21.iloc[-1]) and float(ema_9.iloc[-2]) >= float(ema_21.iloc[-2]):
            reason_parts.append("EMA negative crossover (sell)")

        # Stochastic (SMM Part 4)
        sk = float(stoch_k.iloc[-1]) if not np.isnan(stoch_k.iloc[-1]) else None
        if sk is not None:
            if sk > 80:
                reason_parts.append("Stochastic overbought")
            elif sk < 20:
                reason_parts.append("Stochastic oversold")

        # Divergence (SMM Part 4)
        div_val = float(rsi_div.iloc[-1])
        if div_val > 0:
            reason_parts.append("Bullish divergence")
        elif div_val < 0:
            reason_parts.append("Bearish divergence")

        # Candlestick patterns (SMM Part 1)
        pattern_labels = {
            "hammer": "Hammer (bullish)", "inverted_hammer": "Shooting Star",
            "bullish_engulfing": "Bullish Engulfing", "bearish_engulfing": "Bearish Engulfing",
            "bullish_piercing": "Bullish Piercing", "bearish_piercing": "Dark Cloud Cover",
            "morning_star": "Morning Star (bullish)", "evening_star": "Evening Star (bearish)",
            "doji": "Doji (indecision)",
        }
        for p in active_patterns:
            if p in pattern_labels:
                reason_parts.append(pattern_labels[p])

        return {
            "signal": signal,
            "confidence": round(confidence, 4),
            "indicators": indicators,
            "reason": "; ".join(reason_parts) if reason_parts else "ML model consensus",
        }

    def get_feature_importance(self):
        if not self.is_trained:
            return {}
        importances = self.model.feature_importances_
        return dict(
            sorted(
                zip(self.feature_columns, [round(float(x), 4) for x in importances]),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
        )
