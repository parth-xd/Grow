"""
Backtesting Engine — validate strategies against historical data with realistic costs.

Supports:
  • Walk-forward ML validation (GradientBoosting with rolling retrain)
  • 6 technical strategies (EMA crossover, RSI, MACD, Bollinger, Breakout, Combined)
  • Realistic Indian market costs (STT, brokerage, GST, stamp duty, SEBI)
  • Performance metrics: Sharpe, Sortino, CAGR, max drawdown, win rate, profit factor
  • Equity curve with drawdown tracking
"""

import logging
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Available Strategies ────────────────────────────────────────────────────

STRATEGIES = {
    "ema_crossover": {
        "name": "EMA Crossover",
        "desc": "EMA fast/slow crossover with volume confirmation",
        "params": {"fast": 9, "slow": 21, "volume_confirm": True},
    },
    "rsi_reversal": {
        "name": "RSI Mean Reversion",
        "desc": "Buy when RSI crosses up from oversold, sell when crosses down from overbought",
        "params": {"oversold": 30, "overbought": 70, "period": 14},
    },
    "macd_signal": {
        "name": "MACD Signal Cross",
        "desc": "Buy on MACD histogram crossing above zero, sell below",
        "params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "bollinger_bounce": {
        "name": "Bollinger Bounce",
        "desc": "Buy at lower band touch, sell at upper band",
        "params": {"period": 20, "num_std": 2.0},
    },
    "breakout_52w": {
        "name": "52-Week Breakout",
        "desc": "Buy on new 52-week high with volume surge, sell on 20-SMA break",
        "params": {"lookback": 252, "vol_mult": 1.5},
    },
    "combined": {
        "name": "Multi-Signal Consensus",
        "desc": "Buy/sell when ≥3 of (EMA, RSI, MACD, Bollinger) agree",
        "params": {"agreement_threshold": 3},
    },
    "ml_walkforward": {
        "name": "ML Walk-Forward",
        "desc": "GradientBoosting walk-forward validation (train→predict→roll)",
        "params": {"train_window": 120, "test_window": 20, "confidence": 0.6},
    },
}


def get_strategies():
    """Return available strategies for UI."""
    return {k: {"name": v["name"], "desc": v["desc"], "params": v["params"]}
            for k, v in STRATEGIES.items()}


# ─── Data Loading ────────────────────────────────────────────────────────────

def _load_candles(symbol, start_date=None, end_date=None):
    """Load daily OHLCV from candles table."""
    from db_manager import get_db, Candle
    db = get_db()
    session = db.Session()
    try:
        q = session.query(Candle).filter(Candle.symbol == symbol)
        if start_date:
            q = q.filter(Candle.timestamp >= start_date)
        if end_date:
            q = q.filter(Candle.timestamp <= end_date)
        q = q.order_by(Candle.timestamp)
        rows = q.all()
        if not rows:
            return pd.DataFrame()
        data = [{"date": r.timestamp, "open": r.open, "high": r.high,
                 "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
        df = pd.DataFrame(data)
        df.set_index("date", inplace=True)
        df.index = pd.to_datetime(df.index)
        return df
    finally:
        session.close()


def _load_weekly(symbol, start_date=None, end_date=None):
    """Load from stock_prices table (weekly, up to 5Y)."""
    import psycopg2
    from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
    try:
        conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, user=DB_USER,
                                password=DB_PASSWORD, dbname=DB_NAME)
        sql = "SELECT date, open, high, low, close, volume FROM stock_prices WHERE symbol = %s"
        params = [symbol]
        if start_date:
            sql += " AND date >= %s"
            params.append(start_date)
        if end_date:
            sql += " AND date <= %s"
            params.append(end_date)
        sql += " ORDER BY date"
        df = pd.read_sql(sql, conn, params=params, parse_dates=["date"])
        conn.close()
        if not df.empty:
            df.set_index("date", inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


def _load_data(symbol, start_date=None, end_date=None):
    """Load best available data — daily candles preferred, fall back to weekly."""
    df = _load_candles(symbol, start_date, end_date)
    timeframe = "daily"
    if len(df) < 100:
        weekly = _load_weekly(symbol, start_date, end_date)
        if len(weekly) > len(df):
            df = weekly
            timeframe = "weekly"
    return df, timeframe


# ─── Technical Indicators ────────────────────────────────────────────────────

def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def _sma(s, p):
    return s.rolling(window=p).mean()

def _rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _macd(close, fast=12, slow=26, signal=9):
    ef = _ema(close, fast)
    es = _ema(close, slow)
    ml = ef - es
    sl = _ema(ml, signal)
    return ml, sl, ml - sl

def _bollinger(close, period=20, num_std=2.0):
    mid = _sma(close, period)
    std = close.rolling(window=period).std()
    return mid + num_std * std, mid, mid - num_std * std


# ─── Signal Generators ───────────────────────────────────────────────────────

def _sig_ema(df, p):
    ef = _ema(df["close"], p.get("fast", 9))
    es = _ema(df["close"], p.get("slow", 21))
    sig = pd.Series(0, index=df.index)
    cup = (ef > es) & (ef.shift(1) <= es.shift(1))
    cdn = (ef < es) & (ef.shift(1) >= es.shift(1))
    if p.get("volume_confirm", True):
        vs = _sma(df["volume"], 20)
        cup = cup & (df["volume"] > vs)
    sig[cup] = 1
    sig[cdn] = -1
    return sig


def _sig_rsi(df, p):
    rsi = _rsi(df["close"], p.get("period", 14))
    sig = pd.Series(0, index=df.index)
    sig[(rsi > p.get("oversold", 30)) & (rsi.shift(1) <= p.get("oversold", 30))] = 1
    sig[(rsi < p.get("overbought", 70)) & (rsi.shift(1) >= p.get("overbought", 70))] = -1
    return sig


def _sig_macd(df, p):
    _, _, hist = _macd(df["close"], p.get("fast", 12), p.get("slow", 26), p.get("signal", 9))
    sig = pd.Series(0, index=df.index)
    sig[(hist > 0) & (hist.shift(1) <= 0)] = 1
    sig[(hist < 0) & (hist.shift(1) >= 0)] = -1
    return sig


def _sig_bollinger(df, p):
    upper, _, lower = _bollinger(df["close"], p.get("period", 20), p.get("num_std", 2.0))
    sig = pd.Series(0, index=df.index)
    sig[df["close"] <= lower] = 1
    sig[df["close"] >= upper] = -1
    return sig


def _sig_breakout(df, p):
    lb = p.get("lookback", 252)
    vm = p.get("vol_mult", 1.5)
    sig = pd.Series(0, index=df.index)
    hmax = df["high"].rolling(window=min(lb, len(df) - 1)).max()
    vs = _sma(df["volume"], 20)
    sig[(df["close"] > hmax.shift(1)) & (df["volume"] > vs * vm)] = 1
    sma20 = _sma(df["close"], 20)
    sig[df["close"] < sma20] = -1
    return sig


def _sig_combined(df, p):
    threshold = p.get("agreement_threshold", 3)
    sigs = [
        _sig_ema(df, {"fast": 9, "slow": 21, "volume_confirm": False}),
        _sig_rsi(df, {"period": 14, "oversold": 30, "overbought": 70}),
        _sig_macd(df, {"fast": 12, "slow": 26, "signal": 9}),
        _sig_bollinger(df, {"period": 20, "num_std": 2}),
    ]
    buy_ct = sum((s == 1).astype(int) for s in sigs)
    sell_ct = sum((s == -1).astype(int) for s in sigs)
    sig = pd.Series(0, index=df.index)
    sig[buy_ct >= threshold] = 1
    sig[sell_ct >= threshold] = -1
    return sig


def _sig_ml(df, p):
    """Walk-forward ML signal generation."""
    from predictor import build_features, create_labels, PricePredictor

    tw = p.get("train_window", 120)
    tst = p.get("test_window", 20)
    conf = p.get("confidence", 0.6)
    sig = pd.Series(0, index=df.index)
    n = len(df)

    if n < tw + tst:
        logger.warning("ML walk-forward: need %d bars, have %d", tw + tst, n)
        return sig

    cursor = tw
    while cursor < n:
        end = min(cursor + tst, n)
        train_df = df.iloc[cursor - tw:cursor].copy()
        try:
            pred = PricePredictor()
            res = pred.train(train_df)
            if not res.get("success"):
                cursor = end
                continue
            for i in range(cursor, end):
                ctx = df.iloc[max(0, i - tw):i + 1].copy()
                if len(ctx) < 50:
                    continue
                out = pred.predict(ctx)
                if out["confidence"] >= conf:
                    if out["signal"] == "BUY":
                        sig.iloc[i] = 1
                    elif out["signal"] == "SELL":
                        sig.iloc[i] = -1
        except Exception as e:
            logger.debug("ML walk-forward chunk failed: %s", e)
        cursor = end

    return sig


_GENERATORS = {
    "ema_crossover": _sig_ema,
    "rsi_reversal": _sig_rsi,
    "macd_signal": _sig_macd,
    "bollinger_bounce": _sig_bollinger,
    "breakout_52w": _sig_breakout,
    "combined": _sig_combined,
    "ml_walkforward": _sig_ml,
}


# ─── Trade Simulation ────────────────────────────────────────────────────────

def _simulate(df, signals, symbol, initial_capital, sl_pct, tp_pct, slippage=0.05):
    """Simulate trades with costs, stop-loss, target, slippage."""
    import costs as cost_mod

    capital = initial_capital
    position = None
    trades = []
    equity = []

    for i in range(1, len(df)):
        date = df.index[i]
        prev_sig = signals.iloc[i - 1]
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        bp = o * (1 + slippage / 100)
        sp = o * (1 - slippage / 100)

        # Check exits for open position
        if position is not None:
            ep = position["entry_price"]
            sl = ep * (1 - sl_pct / 100)
            tp = ep * (1 + tp_pct / 100)
            exit_p = exit_r = None

            if l <= sl:
                exit_p, exit_r = sl, "stop_loss"
            elif h >= tp:
                exit_p, exit_r = tp, "target"
            elif prev_sig == -1:
                exit_p, exit_r = sp, "signal"

            if exit_p:
                qty = position["quantity"]
                ci = cost_mod.calculate_costs(ep, qty, exit_p, product="CNC")
                gross = (exit_p - ep) * qty
                net = gross - ci.total
                capital += net + ep * qty
                hd = max((date - position["entry_date"]).days, 1)
                trades.append({
                    "entry_date": str(position["entry_date"].date()) if hasattr(position["entry_date"], 'date') else str(position["entry_date"]),
                    "exit_date": str(date.date()) if hasattr(date, 'date') else str(date),
                    "symbol": symbol, "side": "BUY",
                    "entry_price": round(ep, 2), "exit_price": round(exit_p, 2),
                    "quantity": qty, "gross_pnl": round(gross, 2),
                    "charges": round(ci.total, 2), "net_pnl": round(net, 2),
                    "return_pct": round(net / (ep * qty) * 100, 2),
                    "holding_days": hd, "exit_reason": exit_r,
                })
                position = None

        # New entry
        if position is None and prev_sig == 1 and capital > 100:
            qty = max(1, int(capital * 0.95 / bp))
            preview = cost_mod.calculate_costs(bp, qty, bp, product="CNC")
            if bp * qty + preview.total <= capital:
                capital -= bp * qty
                position = {"entry_date": date, "entry_price": bp, "quantity": qty}

        # Equity curve
        unr = 0
        held = 0
        if position:
            unr = (c - position["entry_price"]) * position["quantity"]
            held = position["entry_price"] * position["quantity"]
        equity.append({
            "date": str(date.date()) if hasattr(date, 'date') else str(date),
            "equity": round(capital + held + unr, 2),
        })

    # Close remaining
    if position:
        lc = df["close"].iloc[-1]
        qty = position["quantity"]
        ci = cost_mod.calculate_costs(position["entry_price"], qty, lc, product="CNC")
        gross = (lc - position["entry_price"]) * qty
        net = gross - ci.total
        hd = max((df.index[-1] - position["entry_date"]).days, 1)
        trades.append({
            "entry_date": str(position["entry_date"].date()) if hasattr(position["entry_date"], 'date') else str(position["entry_date"]),
            "exit_date": str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1]),
            "symbol": symbol, "side": "BUY",
            "entry_price": round(position["entry_price"], 2),
            "exit_price": round(lc, 2), "quantity": qty,
            "gross_pnl": round(gross, 2), "charges": round(ci.total, 2),
            "net_pnl": round(net, 2),
            "return_pct": round(net / (position["entry_price"] * qty) * 100, 2),
            "holding_days": hd, "exit_reason": "end_of_data",
        })

    # Drawdown calculation
    if equity:
        peak = equity[0]["equity"]
        for pt in equity:
            if pt["equity"] > peak:
                peak = pt["equity"]
            pt["drawdown"] = round((peak - pt["equity"]) / peak * 100, 2) if peak > 0 else 0

    return trades, equity


# ─── Performance Metrics ─────────────────────────────────────────────────────

def _metrics(trades, equity, initial_capital):
    """Compute performance metrics from trade list and equity curve."""
    if not trades:
        return {"total_return_pct": 0, "cagr_pct": 0, "sharpe_ratio": 0,
                "sortino_ratio": 0, "max_drawdown_pct": 0, "win_rate_pct": 0,
                "profit_factor": 0, "total_trades": 0, "winning_trades": 0,
                "losing_trades": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
                "avg_holding_days": 0, "max_consec_wins": 0,
                "max_consec_losses": 0, "expectancy": 0, "calmar_ratio": 0}

    winners = [t for t in trades if t["net_pnl"] > 0]
    losers = [t for t in trades if t["net_pnl"] <= 0]
    total = len(trades)
    w = len(winners)
    l = len(losers)
    wr = w / total * 100

    avg_w = float(np.mean([t["return_pct"] for t in winners])) if winners else 0
    avg_l = float(np.mean([t["return_pct"] for t in losers])) if losers else 0
    avg_hold = float(np.mean([t["holding_days"] for t in trades]))

    # Total return + CAGR
    final = equity[-1]["equity"] if equity else initial_capital
    total_ret = (final - initial_capital) / initial_capital * 100
    if equity and len(equity) > 1:
        days = (pd.Timestamp(equity[-1]["date"]) - pd.Timestamp(equity[0]["date"])).days
        years = max(days / 365.25, 0.01)
        cagr = ((final / initial_capital) ** (1 / years) - 1) * 100 if final > 0 else 0
    else:
        cagr = 0

    # Sharpe / Sortino from equity curve daily returns
    eqs = pd.Series([e["equity"] for e in equity])
    daily_ret = eqs.pct_change().dropna()
    rf_daily = (1 + 0.06) ** (1 / 252) - 1  # 6% risk-free (India)
    if len(daily_ret) > 1:
        excess = daily_ret - rf_daily
        sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0
        downside = daily_ret[daily_ret < 0]
        sortino = float((daily_ret.mean() - rf_daily) / downside.std() * np.sqrt(252)) if len(downside) > 1 and downside.std() > 0 else 0
    else:
        sharpe = sortino = 0

    max_dd = max((e["drawdown"] for e in equity), default=0)

    gw = sum(t["net_pnl"] for t in winners)
    gl = abs(sum(t["net_pnl"] for t in losers))
    pf = gw / gl if gl > 0 else (float("inf") if gw > 0 else 0)

    # Consecutive wins/losses
    mcw = mcl = cw = cl = 0
    for t in trades:
        if t["net_pnl"] > 0:
            cw += 1; cl = 0; mcw = max(mcw, cw)
        else:
            cl += 1; cw = 0; mcl = max(mcl, cl)

    expectancy = (wr / 100 * avg_w) + ((1 - wr / 100) * avg_l)
    calmar = abs(cagr / max_dd) if max_dd > 0 else 0

    return {
        "total_return_pct": round(total_ret, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct": round(wr, 1),
        "profit_factor": round(pf, 2) if pf != float("inf") else 999,
        "total_trades": total,
        "winning_trades": w,
        "losing_trades": l,
        "avg_win_pct": round(avg_w, 2),
        "avg_loss_pct": round(avg_l, 2),
        "avg_holding_days": round(avg_hold, 1),
        "max_consec_wins": mcw,
        "max_consec_losses": mcl,
        "expectancy": round(expectancy, 2),
        "calmar_ratio": round(calmar, 2),
    }


# ─── Buy-and-Hold Benchmark ─────────────────────────────────────────────────

def _benchmark(df, initial_capital):
    """Calculate buy-and-hold benchmark for comparison."""
    if df.empty:
        return {"total_return_pct": 0, "cagr_pct": 0, "max_drawdown_pct": 0}
    first = df["close"].iloc[0]
    last = df["close"].iloc[-1]
    qty = max(1, int(initial_capital / first))
    ret = (last - first) / first * 100
    days = (df.index[-1] - df.index[0]).days
    years = max(days / 365.25, 0.01)
    cagr = ((last / first) ** (1 / years) - 1) * 100 if first > 0 else 0

    # Max drawdown
    cum = df["close"] / df["close"].cummax()
    max_dd = float((1 - cum).max() * 100)

    # Build benchmark equity curve
    eq = []
    for i in range(len(df)):
        val = initial_capital * (df["close"].iloc[i] / first)
        eq.append({
            "date": str(df.index[i].date()) if hasattr(df.index[i], 'date') else str(df.index[i]),
            "equity": round(val, 2),
        })

    return {
        "total_return_pct": round(ret, 2),
        "cagr_pct": round(cagr, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "equity_curve": eq,
    }


# ─── Main API ────────────────────────────────────────────────────────────────

def run_backtest(symbol, strategy="ema_crossover", params=None,
                 start_date=None, end_date=None,
                 initial_capital=100000, stop_loss_pct=3.0, target_pct=6.0):
    """
    Run a backtest for a single stock.

    Returns dict with: strategy info, metrics, trades, equity_curve, benchmark, data_info.
    """
    t0 = time.time()
    symbol = symbol.upper()

    strat = STRATEGIES.get(strategy)
    if not strat:
        return {"error": f"Unknown strategy: {strategy}. Available: {list(STRATEGIES.keys())}"}

    # Merge custom params over defaults
    final_params = {**strat["params"]}
    if params:
        final_params.update(params)

    # Load data
    df, timeframe = _load_data(symbol, start_date, end_date)
    if len(df) < 50:
        return {"error": f"Insufficient data for {symbol}: {len(df)} bars (need ≥50)"}

    # Generate signals
    gen = _GENERATORS.get(strategy)
    if not gen:
        return {"error": f"No signal generator for: {strategy}"}

    signals = gen(df, final_params)

    # Simulate trades
    trades, equity = _simulate(df, signals, symbol, initial_capital, stop_loss_pct, target_pct)

    # Metrics
    metrics = _metrics(trades, equity, initial_capital)

    # Benchmark
    bench = _benchmark(df, initial_capital)

    elapsed = time.time() - t0
    logger.info("📈 Backtest %s/%s: %d trades, return %.1f%%, Sharpe %.2f (%.1fs)",
                symbol, strategy, len(trades), metrics["total_return_pct"],
                metrics["sharpe_ratio"], elapsed)

    result = {
        "symbol": symbol,
        "strategy": {"key": strategy, "name": strat["name"], "params": final_params},
        "data_info": {
            "timeframe": timeframe,
            "bars": len(df),
            "start": str(df.index[0].date()) if hasattr(df.index[0], 'date') else str(df.index[0]),
            "end": str(df.index[-1].date()) if hasattr(df.index[-1], 'date') else str(df.index[-1]),
        },
        "config": {
            "initial_capital": initial_capital,
            "stop_loss_pct": stop_loss_pct,
            "target_pct": target_pct,
        },
        "metrics": metrics,
        "benchmark": bench,
        "trades": trades,
        "equity_curve": equity,
        "elapsed_s": round(elapsed, 2),
        "generated_at": datetime.utcnow().isoformat(),
    }

    # Cache the result
    _cache_result(symbol, strategy, result)
    return result


def run_multi_backtest(symbols, strategy="ema_crossover", params=None, **kwargs):
    """Run backtest across multiple stocks. Returns aggregated results."""
    results = []
    for sym in symbols:
        try:
            r = run_backtest(sym, strategy, params, **kwargs)
            if "error" not in r:
                results.append(r)
        except Exception as e:
            logger.warning("Backtest failed for %s: %s", sym, e)

    if not results:
        return {"error": "No successful backtests", "results": []}

    # Aggregate
    avg_ret = float(np.mean([r["metrics"]["total_return_pct"] for r in results]))
    avg_sharpe = float(np.mean([r["metrics"]["sharpe_ratio"] for r in results]))
    avg_wr = float(np.mean([r["metrics"]["win_rate_pct"] for r in results]))
    total_trades = sum(r["metrics"]["total_trades"] for r in results)

    summary = [
        {"symbol": r["symbol"],
         "total_return_pct": r["metrics"]["total_return_pct"],
         "sharpe_ratio": r["metrics"]["sharpe_ratio"],
         "win_rate_pct": r["metrics"]["win_rate_pct"],
         "max_drawdown_pct": r["metrics"]["max_drawdown_pct"],
         "total_trades": r["metrics"]["total_trades"],
         "profit_factor": r["metrics"]["profit_factor"]}
        for r in results
    ]
    summary.sort(key=lambda x: x["total_return_pct"], reverse=True)

    return {
        "strategy": strategy,
        "stocks_tested": len(results),
        "total_trades": total_trades,
        "avg_return_pct": round(avg_ret, 2),
        "avg_sharpe": round(avg_sharpe, 2),
        "avg_win_rate_pct": round(avg_wr, 1),
        "summary": summary,
        "generated_at": datetime.utcnow().isoformat(),
    }


def compare_strategies(symbol, strategies=None, **kwargs):
    """Compare multiple strategies on the same stock."""
    if strategies is None:
        strategies = list(STRATEGIES.keys())

    results = []
    for strat in strategies:
        try:
            r = run_backtest(symbol, strat, **kwargs)
            if "error" not in r:
                results.append({
                    "strategy": strat,
                    "name": STRATEGIES[strat]["name"],
                    "total_return_pct": r["metrics"]["total_return_pct"],
                    "cagr_pct": r["metrics"]["cagr_pct"],
                    "sharpe_ratio": r["metrics"]["sharpe_ratio"],
                    "sortino_ratio": r["metrics"]["sortino_ratio"],
                    "max_drawdown_pct": r["metrics"]["max_drawdown_pct"],
                    "win_rate_pct": r["metrics"]["win_rate_pct"],
                    "profit_factor": r["metrics"]["profit_factor"],
                    "total_trades": r["metrics"]["total_trades"],
                    "calmar_ratio": r["metrics"]["calmar_ratio"],
                })
        except Exception as e:
            logger.warning("Strategy %s failed for %s: %s", strat, symbol, e)

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
    return {
        "symbol": symbol,
        "comparison": results,
        "best_strategy": results[0]["strategy"] if results else None,
        "generated_at": datetime.utcnow().isoformat(),
    }


# ─── Cache ───────────────────────────────────────────────────────────────────

def _cache_result(symbol, strategy, result):
    try:
        from db_manager import set_cached
        set_cached(f"backtest_{symbol}_{strategy}", result, cache_type="backtest")
    except Exception:
        pass


def get_cached_backtest(symbol, strategy):
    try:
        from db_manager import get_cached
        return get_cached(f"backtest_{symbol}_{strategy}", ttl_seconds=86400)
    except Exception:
        return None
