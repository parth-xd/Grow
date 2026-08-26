"""
Cash-equity single-trade backtester — the cash counterpart to
fno_backtester.run_fno_backtest().

Answers ONE question: "on date X, what did the bot decide about this stock,
and was it right?" — the same question the F&O swing backtester answers, so
the two render through the same frontend.

WHAT THIS DELIBERATELY DOES DIFFERENTLY FROM THE F&O BACKTESTER
───────────────────────────────────────────────────────────────
The F&O backtester loads one XGBoost artifact trained over ALL history and
uses it to "predict" a past date. The model has therefore already seen the
outcome it is being graded on, so its CORRECT/WRONG verdict is optimistically
biased. The same trap was waiting here: every models/gbc_cash/*.joblib is
retrained nightly, so grading 2026-05-13 with today's artifact would leak
three months of price action into the heaviest-weighted source.

This module trains WALK-FORWARD instead: the model is fitted only on candles
strictly before the entry bar, then discarded. It is slower, and it is the
only version of this number that means anything.

Every data read is bounded by `as_of` for the same reason — candles, news,
market context and the long-term trend are all reconstructed as of the
decision instant, never as of today.

OUTPUT CONTRACT
───────────────
Byte-identical key sets to run_fno_backtest()'s three shapes (error /
no-entry / entry-found) so fbtRenderResult() consumes it unchanged, plus two
additive keys the F&O producer does not send:

  segment      "cash"  — absent means "fno", so F&O needs no change at all
  signal_meta  {key: {label, weight}} — lets the renderer label the cash
               signal grid honestly instead of reusing the F&O legend

WHY signal_meta EXISTS: the F&O grid shows 7 cells, but 5 of them
(news / x_social / oi_pcr / geopolitical / global) are filled with the SAME
number — p_long - p_short — under five legacy names. Cash has four genuinely
independent sources, so it emits four real cells plus technicals rather than
padding to seven fake ones.
"""

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Reuse the F&O module's indicator + level maths verbatim. These are pure
# functions over price arrays with no F&O assumptions in them, and sharing
# them means the two backtesters cannot drift apart on what "RSI is
# overbought" or "the stop sits at 1.5 ATR" means.
from fno_backtester import (
    _analyze_technicals_pure,
    _calculate_trade_levels,
    _extract_technicals,
    _fetch_candles_from_db,
    _get_unique_dates,
    _score_technicals,
    BACKTEST_INSTRUMENTS,
    MIN_BASELINE_CANDLES,
)

MODEL_GBC = "gbc"
MODEL_XGB = "xgb"

# Bars per session (375 min / 5 min). Used for hold limits and the ATR scale.
BARS_PER_SESSION = 75

# How long a cash swing may be held before a forced exit, in bars.
MAX_HOLD_BARS = int(os.getenv("CASH_BT_MAX_HOLD_BARS", str(7 * BARS_PER_SESSION)))

# Training window for the walk-forward fit, in calendar days ending at the
# entry bar. 180 matches FNO_TRAIN_DAYS so the two models get a comparable
# data budget and the comparison isolates the algorithm.
CASH_TRAIN_DAYS = int(os.getenv("CASH_BT_TRAIN_DAYS", "180"))

# Notional capital the simulated trade deploys. The real sizing logic lives
# in auto_trade() and depends on live account state that cannot be
# reconstructed for a past date, so the backtest uses a fixed, declared
# figure — a stated assumption rather than a fabricated account balance.
CASH_BT_CAPITAL = float(os.getenv("CASH_BT_CAPITAL", "50000"))

# Entry gate. Mirrors the live combined-score threshold in get_prediction.
ENTRY_SCORE_THRESHOLD = float(os.getenv("CASH_BT_ENTRY_THRESHOLD", "0.15"))

# The four live blend weights, read from config_settings so the backtest
# grades the same formula the trader uses. Falls back to the documented
# defaults if the table is unreachable.
_DEFAULT_WEIGHTS = {"ml": 0.40, "trend": 0.15, "news": 0.20, "context": 0.25}


def _blend_weights():
    try:
        from db_manager import get_configs_prefix
        cfg = get_configs_prefix("prediction.weight.") or {}
        out = {}
        for k, default in _DEFAULT_WEIGHTS.items():
            raw = cfg.get(f"prediction.weight.{k}")
            out[k] = float(raw) if raw not in (None, "") else default
        total = sum(out.values())
        # Renormalise rather than trust the table to sum to 1 — a stale or
        # partially-edited config must not silently rescale every score.
        return {k: v / total for k, v in out.items()} if total > 0 else dict(_DEFAULT_WEIGHTS)
    except Exception as e:
        logger.debug("Falling back to default blend weights: %s", e)
        return dict(_DEFAULT_WEIGHTS)


# Labels + weights for the cash signal grid. Technicals carries no weight of
# its own: it is an INPUT to the ML model, not a fifth voter. Showing it with
# a percentage would double-count it.
_CASH_SIGNAL_META = {
    "technicals": {"label": "Technicals", "weight": None},
    "ml": {"label": "ML Model", "weight": 40},
    "context": {"label": "Market Context", "weight": 25},
    "news": {"label": "News Sentiment", "weight": 20},
    "trend": {"label": "Long-term Trend", "weight": 15},
}


# Date the market-data source switched from the legacy Groww `candles` table
# to fyers_candles. Before this, the live system's daily series came from a
# Groww API response that was never persisted, so one component of market
# context (multi-timeframe alignment) cannot be reconstructed exactly.
FYERS_MIGRATION_DATE = datetime(2026, 8, 17)


def _fidelity_notes(symbol, as_of, sources):
    """
    What this replay could NOT reconstruct faithfully.

    Surfaced in the payload and rendered in the UI rather than left implicit.
    A backtest that hides its own blind spots is worse than one that has
    none, because the reader has no way to discount the number — this is
    standard #7 ("missing data must be visible") applied to a measurement
    rather than to a dataset.
    """
    notes = []

    notes.append({
        "source": "ML Model",
        "severity": "high",
        "text": "Walk-forward retrained on data before this date. This is NOT the "
                "model that actually traded — models/gbc_cash artifacts are "
                "overwritten on every nightly retrain with no dated copies, so the "
                "original is gone. Read this as 'what a correctly-trained model "
                "would have decided', not 'what the bot decided'.",
    })

    if not sources.get("news_available"):
        notes.append({
            "source": "News Sentiment",
            "severity": "high",
            "text": f"No articles had been collected for {symbol} by this date, so "
                    f"the 20% news weight was redistributed across the other three "
                    f"sources rather than counted as a neutral zero. Continuous news "
                    f"history exists only for the 10 config.WATCHLIST symbols; "
                    f"nothing at all exists before 2026-03-30.",
        })

    if as_of and as_of < FYERS_MIGRATION_DATE:
        notes.append({
            "source": "Market Context",
            "severity": "low",
            "text": "Multi-timeframe alignment used a live Groww API response that was "
                    "never stored, so it is reconstructed from fyers_candles daily bars "
                    "instead. Bounded effect: it can shift context_score by at most "
                    "0.1, i.e. 0.025 of the final blended score. Market trend, sector "
                    "strength and volatility regime all reconstruct exactly.",
        })

    return notes


def _signal_word(score, threshold=0.08):
    if score > threshold:
        return "BULLISH"
    if score < -threshold:
        return "BEARISH"
    return "NEUTRAL"


def _session_close(date_str):
    """The 15:30 IST ceiling for a trading date — the latest instant a
    decision made on that date could legitimately have seen."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.replace(hour=15, minute=30)


# ═══════════════════════════════════════════════════════════════════════════
# WALK-FORWARD MODEL
# ═══════════════════════════════════════════════════════════════════════════

# Walk-forward models are cached here — NEVER in models/gbc_cash/, which is
# the live trading directory. A date-truncated backtest model landing there
# would silently downgrade the model that places real orders.
_BT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "models", "backtest_cache")


def _cache_path(symbol, model, as_of, n_rows):
    # Row count is part of the key so a later backfill of that window
    # invalidates the entry automatically rather than serving a model fitted
    # on data we have since corrected.
    return os.path.join(_BT_CACHE_DIR, f"{symbol}_{model}_{as_of:%Y%m%d}_{n_rows}.joblib")


def _train_walk_forward(symbol, model, as_of, use_cache=True):
    """
    Fit a fresh predictor on data STRICTLY BEFORE as_of.

    Returns (predictor, df, error). df is the frame the predictor was trained
    on, reused for inference so train and serve cannot land on different
    resolutions.

    The model is cached on disk, because this is 55s of the ~64s a backtest
    costs and history does not change: re-running the same (symbol, date,
    model) — which is exactly what a user does when flipping between the two
    cash models — should be instant the second time.

    It is never written to the live model directory. Persisting it there
    would overwrite the trading artifact with a deliberately handicapped,
    date-truncated version.
    """
    from db_manager import CandleDatabase
    db = CandleDatabase()

    if model == MODEL_XGB:
        from xgb_predictor import XGBPricePredictor
        df = db.get_fyers_1min(symbol, days=CASH_TRAIN_DAYS, as_of=as_of)
        factory = XGBPricePredictor
    else:
        from predictor import PricePredictor
        df = db.get_fyers_candles_as_5min(symbol, days=CASH_TRAIN_DAYS, as_of=as_of)
        factory = PricePredictor

    if df is None or df.empty or len(df) < 250:
        return None, None, f"Not enough pre-{as_of:%Y-%m-%d} data to train ({0 if df is None else len(df)} bars)"

    path = _cache_path(symbol, model, as_of, len(df))
    if use_cache and os.path.exists(path):
        try:
            import joblib
            return joblib.load(path), df, None
        except Exception as e:
            logger.debug("Backtest model cache miss (%s): %s", path, e)

    predictor = factory()
    try:
        result = predictor.train(df)
    except Exception as e:
        return None, None, f"Walk-forward training failed: {e}"

    if not result or not result.get("success"):
        return None, None, (result or {}).get("message", "Walk-forward training failed")

    if use_cache:
        # Atomic write — a truncated cache file would load as a corrupt model
        # rather than as a miss, and then quietly produce garbage predictions.
        try:
            import joblib
            import tempfile
            os.makedirs(_BT_CACHE_DIR, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=_BT_CACHE_DIR, suffix=".joblib")
            os.close(fd)
            joblib.dump(predictor, tmp)
            os.replace(tmp, path)
        except Exception as e:
            logger.debug("Could not cache backtest model: %s", e)

    return predictor, df, None


# ═══════════════════════════════════════════════════════════════════════════
# FOUR-SOURCE ANALYSIS, RECONSTRUCTED AS OF A PAST INSTANT
# ═══════════════════════════════════════════════════════════════════════════

def _load_slow_sources(symbol, as_of):
    """
    Fetch the three DB-backed sources ONCE per backtest.

    These were originally computed inside the bar scan, which made them run
    up to 75 times per backtest for identical answers — a straight N+1 (~10s
    measured) and a violation of standard #1.

    Recomputing them per bar buys nothing: news uses a 7-day window, market
    context a 7-day trend, and the long-term trend a multi-year daily series.
    None of them moves measurably between 09:15 and 15:30, so they are
    anchored once at the session's decision instant.
    """
    out = {"trend_score": 0.0, "trend_reason": None,
           "news_score": 0.0, "news_available": False, "news_reason": None,
           "ctx_score": 0.0, "ctx_reason": None}

    try:
        import bot
        lt = bot.analyze_long_term_trend(symbol, as_of=as_of.date())
        if lt:
            tp = lt["trend_pct"]
            s = 0.0
            if tp > 20:
                s += 0.3
            elif tp < -20:
                s -= 0.3
            if 0 < lt["distance_from_support_pct"] < 5:
                s += 0.15
            if -5 < lt["distance_from_resistance_pct"] < 0:
                s -= 0.15
            out["trend_score"] = s
            out["trend_reason"] = f"Long-term trend: {tp:+.1f}% over history"
        else:
            out["trend_reason"] = "Long-term trend: insufficient daily history"
    except Exception as e:
        logger.debug("Long-term trend replay failed for %s: %s", symbol, e)
        out["trend_reason"] = "Long-term trend: unavailable"

    try:
        import news_sentiment
        news = news_sentiment.get_news_sentiment(symbol, as_of=as_of)
        if news.articles:
            out["news_score"] = news.avg_score
            out["news_available"] = True
            out["news_reason"] = (f"News: {news.signal} from {len(news.articles)} "
                                  f"articles known by {as_of:%Y-%m-%d}")
        else:
            out["news_reason"] = f"News: no articles collected for {symbol} by {as_of:%Y-%m-%d}"
    except Exception as e:
        logger.debug("News replay failed for %s: %s", symbol, e)
        out["news_reason"] = "News: reconstruction failed"

    try:
        import market_context
        ctx = market_context.analyze_market_context(None, symbol, as_of=as_of)
        out["ctx_score"] = ctx.get("context_score", 0.0)
        out["ctx_reason"] = (f"Market context: {ctx.get('market_signal', 'NEUTRAL')} market, "
                             f"{ctx.get('volatility_regime', 'NORMAL')} volatility")
    except Exception as e:
        logger.debug("Market context replay failed for %s: %s", symbol, e)
        out["ctx_reason"] = "Market context: unavailable"

    return out


def _build_analysis(symbol, tech, change_pct, ml_score, ml_signal, ml_conf, as_of,
                    sources=None):
    """
    Reconstruct the same weighted consensus get_prediction() computes live —
    ML 40% / context 25% / news 20% / trend 15% — using only information
    available at `as_of`.

    sources: prefetched _load_slow_sources() result. Passed in by the scan
    loop so the three DB-backed sources are not refetched per bar.

    Returns the F&O-compatible analysis dict.
    """
    if sources is None:
        sources = _load_slow_sources(symbol, as_of)
    weights = _blend_weights()
    signals = {}
    reasons = []

    # ── Technicals (shown for context; already inside the ML features) ──
    tech_result = _score_technicals(tech)
    signals["technicals"] = tech_result
    reasons.append(
        f"Technicals: {tech_result['signal']} (RSI={tech.get('rsi', '?')}, "
        f"MACD={tech_result['macd_direction']}, EMA={tech_result['ema_signal']})"
    )

    # ── Source 1: ML model (40%) ────────────────────────────────────────
    signals["ml"] = {
        "signal": _signal_word(ml_score),
        "score": round(ml_score, 3),
        "model": True,
    }
    reasons.append(f"ML Model: {ml_signal} @ {ml_conf * 100:.0f}% confidence")

    # ── Source 2: Long-term trend (15%) ─────────────────────────────────
    trend_score = sources["trend_score"]
    if sources["trend_reason"]:
        reasons.append(sources["trend_reason"])
    signals["trend"] = {
        "signal": _signal_word(trend_score),
        "score": round(trend_score, 3),
        "change_pct": round(change_pct, 2),
    }

    # ── Source 3: News sentiment (20%) ──────────────────────────────────
    # Coverage is genuinely uneven: only ~11 symbols were fetched
    # continuously, and nothing at all exists before 2026-03-30. Where there
    # is no news, this must SAY SO rather than pass a silent 0.0 — a zero is
    # not neutral here, it drags the blend toward HOLD and would quietly
    # explain away a wrong call as "no signal".
    news_score = sources["news_score"]
    news_available = sources["news_available"]
    if sources["news_reason"]:
        reasons.append(sources["news_reason"])
    signals["news"] = {
        "signal": _signal_word(news_score) if news_available else "NO DATA",
        "score": round(news_score, 3),
        "no_data": not news_available,
    }

    # ── Source 4: Market context (25%) ──────────────────────────────────
    ctx_score = sources["ctx_score"]
    if sources["ctx_reason"]:
        reasons.append(sources["ctx_reason"])
    signals["context"] = {
        "signal": _signal_word(ctx_score),
        "score": round(ctx_score, 3),
    }

    # ── Weighted consensus ──────────────────────────────────────────────
    # When news is missing its weight is REDISTRIBUTED across the surviving
    # sources rather than counted as a zero vote. Counting it as zero would
    # systematically shrink every score toward the HOLD band and bias the
    # whole backtest for the ~62 symbols without news history.
    parts = {
        "ml": ml_score,
        "trend": trend_score,
        "context": ctx_score,
    }
    if news_available:
        parts["news"] = news_score
    live_weight = sum(weights[k] for k in parts)
    combined = sum(weights[k] * v for k, v in parts.items()) / live_weight if live_weight else 0.0

    direction = _signal_word(combined, ENTRY_SCORE_THRESHOLD)
    if direction == "BULLISH":
        recommendation = "BUY"
    elif direction == "BEARISH":
        recommendation = "AVOID / EXIT"
    else:
        recommendation = "WAIT"

    confidence = min(abs(combined) * 2, 1.0)
    if confidence > 0.65:
        strength = "strong"
    elif confidence > 0.40:
        strength = "moderate"
    elif confidence > 0.20:
        strength = "weak"
    else:
        strength = "none"

    meta = {k: dict(v) for k, v in _CASH_SIGNAL_META.items()}
    if not news_available:
        meta["news"]["weight"] = None
        meta["news"]["note"] = "excluded — no news collected by this date"

    return {
        "direction": direction,
        "recommendation": recommendation,
        "weighted_score": round(combined, 4),
        "confidence": round(confidence, 4),
        "strength": strength,
        "signals": signals,
        "signal_meta": meta,
        "reasons": reasons,
        "news_available": news_available,
    }


# ═══════════════════════════════════════════════════════════════════════════
# TRADE SIMULATION — real cash charges, not an options premium model
# ═══════════════════════════════════════════════════════════════════════════

def _simulate_cash_trade(candles, entry_idx, entry_price, quantity, trade_levels):
    """
    Walk forward bar by bar from entry, exiting on stop-loss, target, or the
    hold limit. Long-only, matching the live cash system.

    Charges come from costs.calculate_costs() — the same STT / brokerage /
    GST / stamp-duty model the real trader uses — rather than the flat
    ₹40 + option-STT formula the F&O simulator applies to a premium.
    """
    import costs

    import trailing_strategy

    # RULE 1 caps the initial hard stop at 1% from entry; build_trade() applies
    # it, so an ATR-derived level wider than that is tightened here exactly as
    # it would be live.
    _tstate = trailing_strategy.build_trade(entry_price, quantity, "BUY")
    stop_loss = max(trade_levels["stop_loss"], _tstate["stop_loss"])
    _tstate["stop_loss"] = stop_loss
    take_profit = trade_levels["take_profit"]

    timeline = []
    exit_idx = None
    exit_price = None
    exit_reason = None
    sl_hit = False
    tp_hit = False
    peak_price = entry_price
    entry_date = candles[entry_idx]["date"]

    last = min(len(candles) - 1, entry_idx + MAX_HOLD_BARS)
    for i in range(entry_idx + 1, last + 1):
        c = candles[i]
        days_held = len({x["date"] for x in candles[entry_idx:i + 1]}) - 1
        pnl_pct = ((c["close"] - entry_price) / entry_price) * 100 if entry_price else 0

        event = {
            "candle_idx": i,
            "timestamp": c.get("timestamp", ""),
            "date": c.get("date", ""),
            "time": c.get("time", ""),
            "datetime_label": c.get("datetime_label", ""),
            "spot_price": round(c["close"], 2),
            "spot_change_pct": round(((c["close"] - entry_price) / entry_price) * 100, 2),
            "premium": round(c["close"], 2),   # cash: "premium" IS the share price
            "pnl_pct": round(pnl_pct, 2),
            "peak_premium": round(peak_price, 2),
            "days_held": days_held,
        }

        # TRAILING STOP — evaluated against this bar's LOW while the peak is
        # still the PREVIOUS bar's. The peak is only advanced afterwards, with
        # this bar's high. The reverse order would let the stop ratchet up on
        # the very bar it is tested against, i.e. silently assume the high
        # printed before the low — an intra-bar look-ahead that manufactures
        # free money, which is the same failure the SL-before-TP tie-break
        # below already guards against.
        #
        # confidence_fn is None on purpose: the ML reprieve needs a
        # point-in-time model call, and querying today's model about a past bar
        # would be look-ahead. evaluate() fails CLOSED without it, so the
        # backtest models the reprieve-denied path — the conservative one.
        _r = trailing_strategy.evaluate(_tstate, c["low"], confidence_fn=None)
        _tstate.update(_r["state"])
        if _r["action"] == trailing_strategy.ACTION_CLOSE:
            _tp = _tstate.get("trailing_stop") or stop_loss
            _fill = min(max(_tp, c["low"]), c["high"])   # fill within the bar
            exit_idx, exit_price, exit_reason, sl_hit = i, _fill, "TRAILING_STOP_HIT", True
            event["action"] = "TRAILING_STOP_HIT"
            event["peak_premium"] = round(peak_price, 2)
            timeline.append(event)
            break

        # Now advance the peak with this bar's high, for the NEXT bar.
        peak_price = max(peak_price, c["high"])
        _tstate.update(trailing_strategy.evaluate(_tstate, c["high"], confidence_fn=None)["state"])

        # Stop-loss is checked before target: within a single bar we cannot
        # know which came first, so we assume the worse fill. An optimistic
        # tie-break here is the classic way a backtest invents free money.
        if c["low"] <= stop_loss:
            exit_idx, exit_price, exit_reason, sl_hit = i, stop_loss, "STOP_LOSS_HIT", True
            event["action"] = "STOP_LOSS_HIT"
            timeline.append(event)
            break
        if c["high"] >= take_profit:
            exit_idx, exit_price, exit_reason, tp_hit = i, take_profit, "TARGET_HIT", True
            event["action"] = "TARGET_HIT"
            timeline.append(event)
            break
        if i == last:
            exit_idx, exit_price, exit_reason = i, c["close"], "MAX_HOLD_EXIT"
            event["action"] = "MAX_HOLD_EXIT"
            timeline.append(event)
            break
        timeline.append(event)

    if exit_idx is None:
        exit_idx = last
        exit_price = candles[last]["close"]
        exit_reason = "DATA_END_EXIT"

    gross = (exit_price - entry_price) * quantity
    try:
        charge = costs.calculate_costs(entry_price, quantity, sell_price=exit_price,
                                       product="CNC", exchange="NSE").total
    except Exception as e:
        logger.debug("Cost model failed, falling back to 0: %s", e)
        charge = 0.0
    net = gross - charge
    entry_cost = round(entry_price * quantity, 2)
    days_held = len({x["date"] for x in candles[entry_idx:exit_idx + 1]}) - 1

    return {
        "timeline": timeline,
        "entry_premium": round(entry_price, 2),
        "exit_premium": round(exit_price, 2),
        "exit_reason": exit_reason,
        "exit_candle_idx": exit_idx,
        "exit_spot": round(exit_price, 2),
        "sl_hit": sl_hit,
        "tp_hit": tp_hit,
        "days_held": days_held,
        "pnl_per_unit": round(exit_price - entry_price, 2),
        "total_pnl": round(net, 2),
        "total_pnl_pct": round((net / entry_cost * 100) if entry_cost else 0, 2),
        "total_charges": round(charge, 2),
        "peak_premium": round(peak_price, 2),
        "lot_size": quantity,
        "entry_date": entry_date,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def run_cash_backtest(symbol=None, target_date=None, model=MODEL_GBC):
    """
    Replay one cash decision.

    Args:
        symbol:      e.g. "RELIANCE". Defaults to the first known instrument.
        target_date: "YYYY-MM-DD" — the session to scan.
        model:       "gbc" (GradientBoosting) or "xgb" (XGBoost).

    Returns a dict matching run_fno_backtest()'s contract, plus `segment`.
    """
    if not symbol:
        symbol = list(BACKTEST_INSTRUMENTS.keys())[0]
    symbol = symbol.upper().strip()
    model = (model or MODEL_GBC).lower()
    if model not in (MODEL_GBC, MODEL_XGB):
        return {"error": f"Unknown model '{model}' (expected 'gbc' or 'xgb')"}

    label = (BACKTEST_INSTRUMENTS.get(symbol) or {}).get("label", symbol)
    model_name = "XGBoost" if model == MODEL_XGB else "GradientBoosting"

    # ── Resolve the decision instant ────────────────────────────────────
    if target_date:
        try:
            as_of = _session_close(target_date)
        except ValueError:
            return {"error": f"Invalid date '{target_date}' (expected YYYY-MM-DD)"}
    else:
        as_of = None

    # ── Candles ─────────────────────────────────────────────────────────
    # TWO DIFFERENT HORIZONS, and conflating them is the whole game:
    #
    #   DECISION data must end at the bar being decided on. That is enforced
    #   below on infer_df and on every source in _load_slow_sources.
    #
    #   OUTCOME data must extend PAST as_of, because the future is precisely
    #   what we are grading the decision against. A trade may be held up to
    #   MAX_HOLD_BARS (7 sessions); bounding this series at as_of would make
    #   every trade exit at the close of the entry day and silently turn a
    #   swing backtester into an intraday one.
    #
    # Nothing from after as_of is ever fed to the model or to a signal — it
    # is used only for the SL/TP walk, the chart, and the verdict.
    outcome_horizon = as_of + timedelta(days=21) if as_of else None
    candles = _fetch_candles_from_db(
        symbol, days=CASH_TRAIN_DAYS + 21, as_of=outcome_horizon)
    if len(candles) < MIN_BASELINE_CANDLES + 7:
        return {"error": f"Insufficient data for {symbol}: only {len(candles)} candles "
                         f"(need ≥{MIN_BASELINE_CANDLES + 7})"}

    dates = _get_unique_dates(candles)
    if target_date:
        scan_start = None
        for i, c in enumerate(candles):
            if c["date"] == target_date:
                scan_start = max(MIN_BASELINE_CANDLES, i)
                break
        if scan_start is None:
            return {"error": f"Date {target_date} not found. Available: {', '.join(dates[-5:])}"}
    else:
        as_of = _session_close(dates[-1])
        scan_start = max(MIN_BASELINE_CANDLES, len(candles) - BARS_PER_SESSION)
        target_date = candles[scan_start]["date"]

    # ── Walk-forward fit on pre-decision data only ──────────────────────
    session_open = datetime.strptime(target_date, "%Y-%m-%d").replace(hour=9, minute=15)
    # The reader's ceiling is inclusive (ts <= as_of), so passing session_open
    # would put the 09:15 opening bar of the session being graded INTO the
    # training set. One bar, but it is the first bar of the day whose outcome
    # the model is about to be scored on. Step back so the fit sees only
    # completed prior sessions.
    predictor, train_df, err = _train_walk_forward(
        symbol, model, session_open - timedelta(minutes=1))
    if err:
        return {"error": f"{err} [{model_name}]"}

    # Inference frame is SEPARATE from the training frame and deliberately
    # extends further: the model must be FITTED only on data before the
    # session (no leak), but at 10:25 it must be able to SEE the bars from
    # 09:15 to 10:25 — that is what the live model gets. Reusing train_df for
    # inference would silently handicap the model by hiding the intraday
    # move it is supposed to be reacting to.
    from db_manager import CandleDatabase
    _db = CandleDatabase()
    if model == MODEL_XGB:
        infer_df = _db.get_fyers_1min(symbol, days=CASH_TRAIN_DAYS, as_of=as_of)
    else:
        infer_df = _db.get_fyers_candles_as_5min(symbol, days=CASH_TRAIN_DAYS, as_of=as_of)
    if infer_df is None or infer_df.empty:
        return {"error": f"No inference candles for {symbol} up to {target_date}"}

    # ── Scan the session for an entry ───────────────────────────────────
    scan_end = min(len(candles) - 1, scan_start + BARS_PER_SESSION)
    entry_idx = None
    tech = None
    analysis = None

    # Fetched once for the whole session — see _load_slow_sources.
    #
    # Anchored at the OPEN, not the close. Anchoring at as_of (15:30) would
    # let a 10:25 entry decision read news and context from later that same
    # afternoon — a look-ahead inside the session, small enough to be
    # invisible but large enough to flip a marginal signal (it flipped this
    # exact RELIANCE case from a +0.155 entry to no-entry).
    slow = _load_slow_sources(symbol, session_open)

    for i in range(scan_start, scan_end):
        window = candles[max(0, i - MIN_BASELINE_CANDLES):i + 1]
        closes = [c["close"] for c in window]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        volumes = [c.get("volume", 0) for c in window]
        t = _analyze_technicals_pure(closes, highs, lows, volumes, candles[i]["close"])

        bar_time = datetime.strptime(f"{candles[i]['date']} {candles[i]['time']}", "%Y-%m-%d %H:%M")
        # A ROLLING 1-DAY WINDOW, matching what the live path actually feeds
        # the model: bot.fetch_historical() calls get_fyers_candles_as_5min(
        # symbol, days=1). Frame length is not cosmetic here — build_features'
        # compute_vwap() is a cumsum over the whole frame, so vwap_distance
        # depends on where the slice STARTS as well as where it ends. Feeding
        # 180 days would compute a feature the live model never sees.
        # (It is also ~75 rows instead of ~9,000, which is most of the
        # remaining runtime.)
        ml_df = infer_df[(infer_df["datetime"] <= bar_time) &
                         (infer_df["datetime"] > bar_time - timedelta(days=1))]
        if len(ml_df) < 60:
            continue
        try:
            ml = predictor.predict(ml_df)
        except Exception as e:
            logger.debug("Predict failed at bar %d: %s", i, e)
            continue

        ml_signal = ml.get("signal", "HOLD")
        ml_conf = ml.get("confidence", 0) or 0
        ml_score = {"BUY": 1.0, "SELL": -1.0, "HOLD": 0.0}.get(ml_signal, 0.0) * ml_conf

        change_pct = ((candles[i]["close"] - closes[0]) / closes[0] * 100) if closes[0] else 0
        a = _build_analysis(symbol, t, change_pct, ml_score, ml_signal, ml_conf, bar_time,
                            sources=slow)

        if a["direction"] != "NEUTRAL":
            entry_idx, tech, analysis = i, t, a
            break

    # ── No actionable signal all session ────────────────────────────────
    if entry_idx is None:
        mid = min(scan_start + 20, len(candles) - 1)
        w0, w1 = max(0, mid - 30), min(len(candles), mid + 30)
        window = candles[w0:w1]
        closes = [c["close"] for c in candles[:mid + 1]]
        highs = [c["high"] for c in candles[:mid + 1]]
        lows = [c["low"] for c in candles[:mid + 1]]
        volumes = [c.get("volume", 0) for c in candles[:mid + 1]]
        tech = _analyze_technicals_pure(closes, highs, lows, volumes, candles[mid]["close"])
        analysis = _build_analysis(symbol, tech, 0, 0.0, "HOLD", 0.0, as_of, sources=slow)

        return {
            "segment": "cash",
            "model": model_name,
            "fidelity": _fidelity_notes(symbol, as_of, slow),
            "instrument": symbol,
            "label": label,
            "lot_size": 1,
            "target_date": target_date,
            "total_candles": len(candles),
            "entry_time": None,
            "entry_candle_idx": None,
            "analysis": analysis,
            "chart": {
                "labels": [c["datetime_label"] for c in window],
                "prices": [round(c["close"], 2) for c in window],
                "predicted": None,
            },
            "discrepancy": None,
            "trade_simulation": {
                "would_trade": False,
                "reason": "No actionable signal — combined score stayed inside the neutral band all session",
                "direction": analysis["direction"],
                "strength": analysis["strength"],
                "trade_levels": None,
            },
            "technicals": _extract_technicals(tech),
        }

    entry_price = candles[entry_idx]["close"]
    entry_date = candles[entry_idx]["date"]
    entry_time = candles[entry_idx]["time"]
    entry_label = candles[entry_idx]["datetime_label"]
    direction = analysis["direction"]

    # How the call actually resolved, whether or not a trade was taken.
    horizon = min(len(candles) - 1, entry_idx + MAX_HOLD_BARS)
    resolved_price = candles[horizon]["close"]
    actual_change = ((resolved_price - entry_price) / entry_price * 100) if entry_price else 0
    direction_correct = (
        (direction == "BULLISH" and actual_change > 0) or
        (direction == "BEARISH" and actual_change < 0)
    )

    # ── Bearish: the live cash system is long-only, so it stays out ─────
    # This is a real, correct outcome — not a failure — and the verdict on
    # the CALL is still meaningful, so discrepancy is populated.
    if direction == "BEARISH":
        w0, w1 = max(0, entry_idx - 30), min(len(candles), horizon + 4)
        window = candles[w0:w1]
        return {
            "segment": "cash",
            "model": model_name,
            "fidelity": _fidelity_notes(symbol, as_of, slow),
            "instrument": symbol,
            "label": label,
            "lot_size": 1,
            "target_date": entry_date,
            "entry_time": None,
            "entry_candle_idx": None,
            "total_candles": len(candles),
            "analysis": analysis,
            "chart": {
                "labels": [c["datetime_label"] for c in window],
                "prices": [round(c["close"], 2) for c in window],
                "predicted": None,
            },
            "discrepancy": {
                "predicted_end": round(entry_price, 2),
                "actual_end": round(resolved_price, 2),
                "predicted_change_pct": round(-abs(analysis["weighted_score"]) * 100, 2),
                "actual_change_pct": round(actual_change, 2),
                "difference_pct": 0.0,
                "direction_correct": direction_correct,
                "avg_deviation_pct": round(abs(actual_change), 2),
            },
            "trade_simulation": {
                "would_trade": False,
                "reason": f"Bearish call at ₹{entry_price:,.2f} — cash trading is long-only, "
                          f"so the system correctly stayed out. Price then moved {actual_change:+.2f}%.",
                "direction": direction,
                "strength": analysis["strength"],
                "trade_levels": None,
            },
            "technicals": _extract_technicals(tech),
        }

    # ── Bullish: size, level, simulate ──────────────────────────────────
    quantity = max(int(CASH_BT_CAPITAL // entry_price), 1)
    trade_levels = _calculate_trade_levels(tech, entry_price, direction, candles[:entry_idx + 1])
    sim = _simulate_cash_trade(candles, entry_idx, entry_price, quantity, trade_levels)
    exit_idx = sim["exit_candle_idx"]

    # Chart window: one day before entry through exit + padding.
    chart_start = entry_idx
    for i in range(entry_idx - 1, -1, -1):
        if candles[i]["date"] != entry_date:
            chart_start = i
            break
    chart_start = max(0, chart_start)
    chart_end = min(len(candles), exit_idx + 4)
    chart_window = candles[chart_start:chart_end]

    entry_chart_idx = entry_idx - chart_start
    exit_chart_idx = exit_idx - chart_start

    # Predicted path: straight line from entry to the target the model
    # implied, so the chart shows expectation vs reality.
    n = (exit_idx - entry_idx) + 1
    target = trade_levels["take_profit"]
    pred_data = [None] * len(chart_window)
    for k in range(n):
        ci = entry_chart_idx + k
        if 0 <= ci < len(pred_data):
            frac = k / max(n - 1, 1)
            pred_data[ci] = round(entry_price + (target - entry_price) * frac, 2)

    predicted_end = target
    actual_end = candles[exit_idx]["close"]
    predicted_change = ((predicted_end - entry_price) / entry_price * 100) if entry_price else 0
    actual_change_trade = ((actual_end - entry_price) / entry_price * 100) if entry_price else 0
    direction_correct = actual_change_trade > 0

    deviations = []
    for k in range(n):
        ci = entry_chart_idx + k
        if 0 <= ci < len(chart_window) and pred_data[ci] is not None:
            actual = chart_window[ci]["close"]
            if actual:
                deviations.append(abs(pred_data[ci] - actual) / actual * 100)
    avg_deviation = sum(deviations) / len(deviations) if deviations else 0

    return {
        "segment": "cash",
        "model": model_name,
        "fidelity": _fidelity_notes(symbol, as_of, slow),
        "instrument": symbol,
        "label": label,
        "lot_size": quantity,
        "target_date": entry_date,
        "entry_time": entry_time,
        "entry_label": entry_label,
        "entry_price": round(entry_price, 2),
        "entry_candle_idx": entry_chart_idx,
        "exit_candle_idx": exit_chart_idx,
        "total_candles": len(candles),
        "days_held": sim["days_held"],
        "analysis": analysis,
        "chart": {
            "labels": [c["datetime_label"] for c in chart_window],
            "prices": [round(c["close"], 2) for c in chart_window],
            "predicted": pred_data,
        },
        "discrepancy": {
            "predicted_end": round(predicted_end, 2),
            "actual_end": round(actual_end, 2),
            "predicted_change_pct": round(predicted_change, 2),
            "actual_change_pct": round(actual_change_trade, 2),
            "difference_pct": round(predicted_change - actual_change_trade, 2),
            "direction_correct": direction_correct,
            "avg_deviation_pct": round(avg_deviation, 2),
        },
        "trade_simulation": {
            "would_trade": True,
            "option_type": "EQ",          # cash equity, not CE/PE
            "direction": direction,
            "entry_cost": round(entry_price * quantity, 2),
            "trade_levels": trade_levels,
            **sim,
        },
        "technicals": _extract_technicals(tech),
    }


def get_available_dates(symbol, limit=60):
    """Recent sessions with candle coverage, newest first — for the picker."""
    candles = _fetch_candles_from_db(symbol, days=180)
    if not candles:
        return []
    return list(reversed(_get_unique_dates(candles)))[:limit]
