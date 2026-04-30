"""
Trade Journal — Full pre-trade and post-trade reporting system.

Every trade gets:
  PRE-TRADE REPORT:  Why the trade was made, all sources, signals, indicators,
                     confidence, expected outcome, risk/reward, timing rationale.
  POST-TRADE REPORT: What actually happened — actual P&L, whether prediction was
                     correct, why it matched or didn't, lessons learned.

Reports are stored in-memory and persisted to a JSON file for history.
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional

import costs
from config import TARGET_PCT

logger = logging.getLogger(__name__)

JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "trade_journal.json")

# ── In-memory store ──────────────────────────────────────────────────────────

_journal: list = []  # list of TradeReport dicts
_loaded = False


def _load():
    """Load journal from DB first, fall back to disk."""
    global _journal, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from db_manager import get_db, TradeJournalEntry
        db = get_db()
        with db.Session() as session:
            rows = session.query(TradeJournalEntry).order_by(TradeJournalEntry.created_at).all()
            if rows:
                _journal = [r.to_dict() for r in rows]
                logger.info(f"Loaded {len(_journal)} trades from database")
                return
    except Exception as e:
        logger.debug(f"Failed to load from DB, falling back to JSON: {e}")
    # Fallback to JSON file
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f:
                _journal = json.load(f)
                logger.info(f"Loaded {len(_journal)} trades from JSON file")
        except Exception as e:
            logger.warning(f"Failed to load trade journal: {e}")
            _journal = []
    else:
        _journal = []


def _save():
    """Persist journal to DB and disk."""
    # Always save to disk as backup
    try:
        with open(JOURNAL_FILE, "w") as f:
            json.dump(_journal, f, indent=2, default=str)
        logger.info(f"Trade journal saved to disk ({len(_journal)} trades)")
    except Exception as e:
        logger.warning("Failed to save trade journal to file: %s", e)
    # Persist ALL trades to DB (not just latest) to avoid status loss on restart
    if not _journal:
        return
    try:
        from db_manager import get_db, TradeJournalEntry
        db = get_db()
        with db.Session() as session:
            saved_count = 0
            for trade in _journal:
                existing = session.query(TradeJournalEntry).filter_by(trade_id=trade["trade_id"]).first()
                if existing:
                    # Keep the DB row aligned with the latest in-memory trade state.
                    existing.status = trade.get("status", "OPEN")
                    existing.symbol = trade.get("symbol", existing.symbol)
                    existing.side = trade.get("side", existing.side)
                    existing.quantity = trade.get("quantity", existing.quantity)
                    existing.trigger = trade.get("trigger", existing.trigger)
                    existing.is_paper = trade.get("is_paper", existing.is_paper)
                    existing.entry_time = datetime.fromisoformat(trade["entry_time"]) if trade.get("entry_time") else existing.entry_time
                    existing.entry_price = trade.get("entry_price", existing.entry_price)
                    existing.exit_price = trade.get("exit_price")
                    existing.exit_time = datetime.fromisoformat(trade["exit_time"]) if trade.get("exit_time") else None
                    existing.exit_reason = trade.get("exit_reason")
                    existing.signal = trade.get("signal") or trade.get("side")
                    existing.confidence = trade.get("confidence")
                    existing.stop_loss = trade.get("stop_loss")
                    existing.projected_exit = trade.get("projected_exit")
                    existing.peak_pnl = trade.get("peak_pnl")
                    existing.actual_profit_pct = trade.get("actual_profit_pct")
                    existing.breakeven_price = trade.get("breakeven_price")
                    existing.pre_trade_json = json.dumps(trade.get("pre_trade")) if trade.get("pre_trade") else existing.pre_trade_json
                    existing.post_trade_json = json.dumps(trade.get("post_trade")) if trade.get("post_trade") else None
                    saved_count += 1
                else:
                    # Create new DB entry if it doesn't exist
                    entry = TradeJournalEntry(
                        trade_id=trade["trade_id"],
                        status=trade.get("status", "OPEN"),
                        symbol=trade.get("symbol", ""),
                        side=trade.get("side", ""),
                        quantity=trade.get("quantity", 0),
                        trigger=trade.get("trigger", "auto"),
                        entry_time=datetime.fromisoformat(trade["entry_time"]) if trade.get("entry_time") else datetime.now(),
                        entry_price=trade.get("entry_price", 0),
                        exit_price=trade.get("exit_price"),
                        exit_time=datetime.fromisoformat(trade["exit_time"]) if trade.get("exit_time") else None,
                        exit_reason=trade.get("exit_reason"),
                        signal=trade.get("signal") or trade.get("side"),
                        confidence=trade.get("confidence"),
                        stop_loss=trade.get("stop_loss"),
                        projected_exit=trade.get("projected_exit"),
                        peak_pnl=trade.get("peak_pnl"),
                        actual_profit_pct=trade.get("actual_profit_pct"),
                        breakeven_price=trade.get("breakeven_price"),
                        pre_trade_json=json.dumps(trade.get("pre_trade")),
                        post_trade_json=json.dumps(trade.get("post_trade")) if trade.get("post_trade") else None,
                    )
                    session.add(entry)
                    saved_count += 1
            session.commit()
            logger.info(f"Trade journal saved to database ({saved_count} trades)")
    except Exception as e:
        logger.error("DB save for trade journal failed: %s", e)


# ── Pre-Trade Report ─────────────────────────────────────────────────────────

def create_pre_trade_report(
    symbol: str,
    side: str,
    quantity: int,
    entry_price: float,
    prediction: dict,
    trigger: str = "auto",
    is_paper: bool = False,
    trade_id: Optional[str] = None,
    entry_time: Optional[str] = None,
) -> dict:
    """
    Generate a comprehensive pre-trade report capturing the full reasoning
    behind a trade decision at the moment it's made.

    Args:
        symbol:     Trading symbol
        side:       BUY or SELL
        quantity:   Shares being traded
        entry_price: Price at which the order was placed
        prediction: Full prediction dict from get_prediction()
        trigger:    "auto" (bot), "manual" (user click), "gtt" (stop-loss hit)

    Returns:
        A report dict with a unique trade_id.
    """
    _load()

    now = datetime.now()
    if entry_time:
        try:
            now = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
        except ValueError:
            pass
    trade_id = trade_id or f"{symbol}-{side[0]}-{now.strftime('%Y%m%d%H%M%S%f')}"

    existing = next((report for report in _journal if report["trade_id"] == trade_id), None)
    if existing:
        logger.info("Trade journal entry %s already exists, reusing current report", trade_id)
        return existing

    # Extract all source details
    sources = prediction.get("sources", {})
    ml = sources.get("ml", {})
    news = sources.get("news", {})
    ctx = sources.get("market_context", {})
    cost_data = prediction.get("costs", {})
    indicators = prediction.get("indicators", {})

    # Calculate risk/reward
    from config import STOP_LOSS_PCT, TARGET_PCT
    if side == "BUY":
        stop_loss_price = round(entry_price * (1 - STOP_LOSS_PCT / 100), 2)
        target_price = round(entry_price * (1 + TARGET_PCT / 100), 2)
        risk_per_share = round(entry_price - stop_loss_price, 2)
        reward_per_share = round(target_price - entry_price, 2)
        risk_reward_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0
    else:
        stop_loss_price = None
        target_price = None
        risk_per_share = 0
        reward_per_share = 0
        risk_reward_ratio = 0

    # Build the human-readable reasoning narrative
    reasoning = _build_reasoning_narrative(
        symbol, side, entry_price, prediction, ml, news, ctx, indicators, cost_data
    )

    # Estimate expected outcome
    expected_move_pct = prediction.get("confidence", 0) * TARGET_PCT if side == "BUY" else 0
    breakeven_pct = cost_data.get("breakeven_pct", 0) if cost_data else 0

    report = {
        "trade_id": trade_id,
        "status": "OPEN",  # OPEN → CLOSED
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "trigger": trigger,
        "is_paper": is_paper,

        # ── Timing ────────────────────────────────
        "entry_time": entry_time or now.isoformat(),
        "entry_price": entry_price,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "signal": side,
        "confidence": prediction.get("confidence"),
        "stop_loss": stop_loss_price,
        "projected_exit": target_price,
        "peak_pnl": None,
        "actual_profit_pct": None,
        "breakeven_price": cost_data.get("breakeven_price") if cost_data else None,

        # ── Pre-Trade Analysis ────────────────────
        "pre_trade": {
            "signal": prediction.get("signal"),
            "confidence": prediction.get("confidence"),
            "combined_score": prediction.get("combined_score"),
            "reasoning": reasoning,
            "reason_summary": prediction.get("reason", ""),

            # Source breakdown
            "ml_signal": ml.get("signal"),
            "ml_confidence": ml.get("confidence"),
            "ml_score": ml.get("score"),

            "news_signal": news.get("signal") if news else None,
            "news_score": news.get("avg_score") if news else None,
            "news_articles_count": news.get("total_articles", 0) if news else 0,
            "news_bullish": news.get("bullish_count", 0) if news else 0,
            "news_bearish": news.get("bearish_count", 0) if news else 0,
            "top_headlines": [a.get("title", "") for a in (news.get("articles", []) if news else [])[:5]],

            "market_signal": ctx.get("market_signal"),
            "market_trend": ctx.get("market_trend"),
            "sector": ctx.get("sector"),
            "sector_signal": ctx.get("sector_signal"),
            "multi_tf_aligned": ctx.get("multi_tf_aligned"),
            "volatility_regime": ctx.get("volatility_regime"),
            "context_score": ctx.get("context_score"),

            # Technical indicators snapshot
            "rsi": indicators.get("rsi"),
            "macd": indicators.get("macd"),
            "macd_signal": indicators.get("macd_signal"),
            "stoch_k": indicators.get("stoch_k"),
            "stoch_d": indicators.get("stoch_d"),
            "sma_20": indicators.get("sma_20"),
            "sma_50": indicators.get("sma_50"),
            "ema_crossover": indicators.get("ema_crossover"),
            "trend": indicators.get("trend"),
            "candle_patterns": indicators.get("candle_patterns", []),

            # Risk management
            "stop_loss_price": stop_loss_price,
            "target_price": target_price,
            "risk_per_share": risk_per_share,
            "reward_per_share": reward_per_share,
            "risk_reward_ratio": risk_reward_ratio,

            # Cost analysis
            "breakeven_price": cost_data.get("breakeven_price") if cost_data else None,
            "breakeven_pct": breakeven_pct,
            "est_total_charges": cost_data.get("total_charges") if cost_data else None,
            "expected_move_pct": round(expected_move_pct, 2),

            # Target profit & stop-loss loss (in rupees)
            "expected_profit": round(reward_per_share * quantity, 2) if side == "BUY" else 0,
            "expected_loss": round(risk_per_share * quantity, 2) if side == "BUY" else 0,

            # Entry profit target (e.g., 2% for BUY, -2% for SELL)
            "entry_profit_target": TARGET_PCT if side == "BUY" else -TARGET_PCT,
        },

        # ── Post-Trade (filled later) ────────────
        "post_trade": None,
    }

    _journal.append(report)
    _save()

    return report


def _build_reasoning_narrative(symbol, side, price, prediction, ml, news, ctx, indicators, cost_data):
    """Build a plain-English explanation of why a trade was made."""
    lines = []
    now = datetime.now()
    lines.append(f"Trade Decision: {side} {symbol} at ₹{price}")
    lines.append(f"Time: {now.strftime('%d %b %Y, %I:%M %p')} IST")
    lines.append("")

    # Overall verdict
    conf = prediction.get("confidence", 0)
    score = prediction.get("combined_score", 0)
    lines.append(f"Combined Score: {score:.3f} | Confidence: {conf*100:.1f}%")
    lines.append("")

    # ML reasoning
    lines.append("--- TECHNICAL ANALYSIS (50% weight) ---")
    lines.append(f"ML Signal: {ml.get('signal', 'N/A')} (confidence {(ml.get('confidence',0))*100:.1f}%)")
    if indicators.get("rsi"):
        rsi = indicators["rsi"]
        rsi_note = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral zone"
        lines.append(f"RSI(14): {rsi} — {rsi_note}")
    if indicators.get("trend"):
        lines.append(f"Trend (SMA20 vs SMA50): {indicators['trend']}")
    if indicators.get("ema_crossover"):
        lines.append(f"EMA Crossover (9/21): {indicators['ema_crossover']}")
    if indicators.get("macd") is not None:
        macd_rel = "above" if indicators["macd"] > (indicators.get("macd_signal") or 0) else "below"
        lines.append(f"MACD: {indicators['macd']:.4f} ({macd_rel} signal line)")
    if indicators.get("stoch_k") is not None:
        sk = indicators["stoch_k"]
        sk_note = "overbought" if sk > 80 else "oversold" if sk < 20 else "mid-range"
        lines.append(f"Stochastic %K: {sk} — {sk_note}")
    patterns = indicators.get("candle_patterns", [])
    if patterns:
        lines.append(f"Active Candlestick Patterns: {', '.join(p.replace('_',' ').title() for p in patterns)}")
    lines.append("")

    # News reasoning
    lines.append("--- NEWS SENTIMENT (25% weight) ---")
    if news and news.get("total_articles"):
        lines.append(f"Signal: {news.get('signal')} (score {news.get('avg_score',0):.3f})")
        lines.append(f"Articles analysed: {news['total_articles']} — {news.get('bullish_count',0)} bullish, {news.get('bearish_count',0)} bearish, {news.get('neutral_count',0)} neutral")
        headlines = [a.get("title", "") for a in news.get("articles", [])[:3]]
        for i, h in enumerate(headlines, 1):
            lines.append(f"  {i}. {h}")
    else:
        lines.append("No news data available")
    lines.append("")

    # Market context reasoning
    lines.append("--- MARKET CONTEXT (25% weight) ---")
    lines.append(f"Nifty Trend: {ctx.get('market_signal', 'N/A')} (score {ctx.get('market_trend', 0):.3f})")
    if ctx.get("sector") and ctx["sector"] != "UNKNOWN":
        lines.append(f"Sector ({ctx['sector']}): {ctx.get('sector_signal', 'N/A')} (score {ctx.get('sector_trend', 0):.3f})")
    lines.append(f"Multi-Timeframe Aligned: {'Yes' if ctx.get('multi_tf_aligned') else 'No'}")
    lines.append(f"Volatility Regime: {ctx.get('volatility_regime', 'NORMAL')}")
    lines.append(f"Context Score: {ctx.get('context_score', 0):.3f}")
    lines.append("")

    # Cost / risk analysis
    lines.append("--- COST & RISK ANALYSIS ---")
    if cost_data:
        lines.append(f"Breakeven Price: ₹{cost_data.get('breakeven_price', 'N/A')}")
        lines.append(f"Breakeven Move: {cost_data.get('breakeven_pct', 0):.2f}%")
        lines.append(f"Est. Total Charges: ₹{cost_data.get('total_charges', 'N/A')}")
    if side == "BUY":
        from config import STOP_LOSS_PCT, TARGET_PCT
        sl = round(price * (1 - STOP_LOSS_PCT / 100), 2)
        tgt = round(price * (1 + TARGET_PCT / 100), 2)
        lines.append(f"Stop Loss: ₹{sl} ({STOP_LOSS_PCT}% below entry)")
        lines.append(f"Target: ₹{tgt} ({TARGET_PCT}% above entry)")
        risk = price - sl
        reward = tgt - price
        rr = round(reward / risk, 2) if risk > 0 else 0
        lines.append(f"Risk:Reward = 1:{rr}")
        from config import MAX_TRADE_QUANTITY, MAX_TRADE_VALUE
        qty = min(MAX_TRADE_QUANTITY, int(MAX_TRADE_VALUE / price)) if price > 0 else 1
        lines.append(f"Expected Profit (if target hit): ₹{round(reward * qty, 2)}")
        lines.append(f"Max Loss (if SL hit): ₹{round(risk * qty, 2)}")

    return "\n".join(lines)


# ── Post-Trade Report ────────────────────────────────────────────────────────

def close_trade_report(
    trade_id: str,
    exit_price: float,
    exit_reason: str = "manual",
    current_indicators: Optional[dict] = None,
) -> Optional[dict]:
    """
    Complete a trade report with post-trade analysis.

    Args:
        trade_id:    The trade_id from the pre-trade report
        exit_price:  Actual exit price
        exit_reason: "target_hit", "stop_loss_hit", "manual", "signal_reversed", "auto"
        current_indicators: Latest indicator snapshot for comparison
    """
    _load()

    report = None
    for r in _journal:
        if r["trade_id"] == trade_id and r["status"] == "OPEN":
            report = r
            break

    if report is None:
        logger.warning("Trade %s not found or already closed", trade_id)
        return None

    now = datetime.now()
    pre = report["pre_trade"]
    entry_price = report["entry_price"]
    quantity = report["quantity"]
    side = report["side"]

    # Calculate actual P&L
    if side == "BUY":
        gross_pnl = (exit_price - entry_price) * quantity
        pnl_info = costs.net_profit(entry_price, exit_price, quantity)
    else:
        gross_pnl = (entry_price - exit_price) * quantity
        pnl_info = costs.net_profit(exit_price, entry_price, quantity)

    net_pnl = pnl_info["net_profit"]
    total_charges = pnl_info["total_charges"]
    move_pct = round((exit_price - entry_price) / entry_price * 100, 4) if entry_price > 0 else 0
    profit_pct = move_pct if side == "BUY" else round((entry_price - exit_price) / entry_price * 100, 4) if entry_price > 0 else 0

    # Did the prediction match?
    predicted_signal = pre.get("signal")
    if side == "BUY":
        prediction_correct = exit_price > entry_price
    else:
        prediction_correct = exit_price < entry_price

    # Accuracy of each source
    ml_correct = _source_was_correct(pre.get("ml_signal"), side, prediction_correct)
    news_correct = _source_was_correct(pre.get("news_signal"), side, prediction_correct)
    market_correct = _source_was_correct(pre.get("market_signal"), side, prediction_correct)

    # Build match analysis
    match_analysis = _build_match_analysis(
        report, exit_price, exit_reason, move_pct, net_pnl,
        prediction_correct, ml_correct, news_correct, market_correct,
        current_indicators
    )

    # Duration
    entry_dt = datetime.fromisoformat(report["entry_time"])
    duration_minutes = round((now - entry_dt).total_seconds() / 60, 1)

    post_trade = {
        "exit_time": now.isoformat(),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "duration_minutes": duration_minutes,

        # Actual results
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "total_charges": round(total_charges, 2),
        "move_pct": move_pct,
        "profitable": net_pnl > 0,

        # Prediction accuracy
        "prediction_correct": prediction_correct,
        "ml_correct": ml_correct,
        "news_correct": news_correct,
        "market_correct": market_correct,

        # Comparison with expectations
        "expected_move_pct": pre.get("expected_move_pct", 0),
        "actual_move_pct": move_pct,
        "move_vs_expected": "EXCEEDED" if abs(move_pct) > abs(pre.get("expected_move_pct", 0)) else "FELL SHORT",
        "hit_target": exit_price >= pre.get("target_price", float("inf")) if side == "BUY" else False,
        "hit_stop_loss": exit_price <= pre.get("stop_loss_price", 0) if side == "BUY" else False,

        # Target vs actual profit comparison
        "target_price": pre.get("target_price"),
        "stop_loss_price": pre.get("stop_loss_price"),
        "expected_profit": pre.get("expected_profit", 0),
        "expected_loss": pre.get("expected_loss", 0),
        "profit_vs_target": round(net_pnl - pre.get("expected_profit", 0), 2) if pre.get("expected_profit") else 0,
        "profit_pct_of_target": round((net_pnl / pre.get("expected_profit", 1)) * 100, 1) if pre.get("expected_profit") else 0,

        # Exit indicators snapshot (for comparison)
        "exit_indicators": current_indicators,

        # Analysis narrative
        "match_analysis": match_analysis,
    }

    report["post_trade"] = post_trade
    report["exit_time"] = now.isoformat()
    report["exit_price"] = exit_price
    report["exit_reason"] = exit_reason
    report["actual_profit_pct"] = profit_pct
    
    # Determine status based on what happened
    if post_trade["hit_target"]:
        report["status"] = "HIT_TARGET"
    elif post_trade["hit_stop_loss"]:
        report["status"] = "HIT_SL"
    else:
        report["status"] = "CLOSED"

    _save()
    return report


def close_matching_paper_trade(
    trade_id: str,
    symbol: str,
    side: str,
    quantity: int,
    entry_price: float,
    entry_time: Optional[str],
    exit_price: float,
    exit_reason: str = "manual",
    current_indicators: Optional[dict] = None,
) -> Optional[dict]:
    """Close a paper trade even if a legacy journal entry used a mismatched ID."""
    report = close_trade_report(trade_id, exit_price, exit_reason, current_indicators)
    if report is not None:
        return report

    _load()

    try:
        target_entry_dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00")) if entry_time else None
    except ValueError:
        target_entry_dt = None

    price_tolerance = max(0.5, float(entry_price or 0) * 0.0005)
    candidates = []

    for report in _journal:
        if report.get("status") != "OPEN":
            continue
        if not report.get("is_paper"):
            continue
        if report.get("symbol") != symbol:
            continue
        if report.get("side") != side:
            continue
        if int(report.get("quantity") or 0) != int(quantity or 0):
            continue

        report_price = float(report.get("entry_price") or 0)
        if abs(report_price - float(entry_price or 0)) > price_tolerance:
            continue

        score = 0.0
        if target_entry_dt and report.get("entry_time"):
            try:
                report_entry_dt = datetime.fromisoformat(str(report["entry_time"]).replace("Z", "+00:00"))
                delta_seconds = abs((report_entry_dt - target_entry_dt).total_seconds())
                if delta_seconds > 5:
                    continue
                score += delta_seconds
            except ValueError:
                score += 10.0

        candidates.append((score, report["trade_id"]))

    if not candidates:
        logger.warning("Paper trade %s could not be matched to any open journal entry", trade_id)
        return None

    _, matched_trade_id = min(candidates, key=lambda item: item[0])
    logger.warning(
        "Paper trade %s not found in journal, closing legacy matched entry %s instead",
        trade_id,
        matched_trade_id,
    )
    return close_trade_report(matched_trade_id, exit_price, exit_reason, current_indicators)


def _source_was_correct(source_signal, side, trade_was_profitable):
    """Check if a source's signal aligned with the actual outcome."""
    if source_signal is None:
        return None  # no data

    buy_signals = {"BUY", "BULLISH"}
    sell_signals = {"SELL", "BEARISH"}

    if side == "BUY":
        if source_signal in buy_signals:
            return trade_was_profitable  # agreed to buy, correct if profitable
        elif source_signal in sell_signals:
            return not trade_was_profitable  # disagreed, correct if trade lost money
    return None  # HOLD/NEUTRAL — didn't commit


def _build_match_analysis(report, exit_price, exit_reason, move_pct, net_pnl,
                          prediction_correct, ml_correct, news_correct, market_correct,
                          current_indicators):
    """Build a plain-English post-trade analysis comparing expectation vs reality."""
    pre = report["pre_trade"]
    entry = report["entry_price"]
    side = report["side"]
    lines = []

    lines.append("═══════════════════════════════════════════")
    lines.append(f"POST-TRADE ANALYSIS: {report['symbol']} ({side})")
    lines.append(f"Exit Time: {datetime.now().strftime('%d %b %Y, %I:%M %p')} IST")
    lines.append("═══════════════════════════════════════════")
    lines.append("")

    # Result summary
    result_emoji = "PROFIT" if net_pnl > 0 else "LOSS"
    lines.append(f"Result: {result_emoji}")
    lines.append(f"Entry: ₹{entry} → Exit: ₹{exit_price} ({'+' if move_pct > 0 else ''}{move_pct:.2f}%)")
    lines.append(f"Gross P&L: ₹{(exit_price - entry) * report['quantity']:.2f}")
    lines.append(f"Charges: ₹{pre.get('est_total_charges', 0):.2f}")
    lines.append(f"Net P&L: ₹{net_pnl:.2f}")
    lines.append(f"Exit Reason: {exit_reason}")
    lines.append("")

    # Prediction match
    lines.append("--- DID THE PREDICTION MATCH? ---")
    verdict = "YES — Prediction was correct" if prediction_correct else "NO — Prediction was wrong"
    lines.append(f"Overall: {verdict}")
    lines.append(f"  Predicted: {pre.get('signal')} with {(pre.get('confidence',0))*100:.1f}% confidence")
    lines.append(f"  Actual Move: {'+' if move_pct > 0 else ''}{move_pct:.2f}%")
    lines.append(f"  Expected Move: {pre.get('expected_move_pct', 0):.2f}%")
    lines.append("")

    # Target / Stop Loss check
    if side == "BUY":
        tgt = pre.get("target_price")
        sl = pre.get("stop_loss_price")
        if tgt and exit_price >= tgt:
            lines.append(f"TARGET HIT: Price reached ₹{exit_price} (target was ₹{tgt})")
        elif sl and exit_price <= sl:
            lines.append(f"STOP LOSS HIT: Price fell to ₹{exit_price} (stop was ₹{sl})")
        else:
            lines.append(f"Exited between SL (₹{sl}) and Target (₹{tgt})")
    lines.append("")

    # Source-by-source accuracy
    lines.append("--- SOURCE ACCURACY BREAKDOWN ---")
    for name, was_correct, signal in [
        ("ML/Technical", ml_correct, pre.get("ml_signal")),
        ("News Sentiment", news_correct, pre.get("news_signal")),
        ("Market Context", market_correct, pre.get("market_signal")),
    ]:
        if was_correct is None:
            status = "N/A (no signal)"
        elif was_correct:
            status = "CORRECT"
        else:
            status = "WRONG"
        lines.append(f"  {name}: {signal or 'N/A'} → {status}")
    lines.append("")

    # Why it didn't match (if prediction was wrong)
    if not prediction_correct:
        lines.append("--- WHY THE PREDICTION FAILED ---")
        reasons = []

        # Check if news sentiment shifted
        if news_correct is False:
            reasons.append("News sentiment was misleading or changed after entry")

        # Check if market context shifted
        if market_correct is False:
            reasons.append("Broader market moved against the position")

        # Check volatility
        vol = pre.get("volatility_regime")
        if vol == "HIGH":
            reasons.append("High volatility regime — signals are less reliable")

        # Check if multi-TF was not aligned
        if not pre.get("multi_tf_aligned"):
            reasons.append("Daily and intraday trends were not aligned at entry")

        # Check if cost drag was the issue
        if net_pnl < 0 and (exit_price - entry) * report["quantity"] > 0:
            reasons.append("Trade was profitable in price terms but charges made it a net loss")

        # Check RSI extremes
        rsi = pre.get("rsi")
        if rsi and side == "BUY" and rsi > 65:
            reasons.append(f"RSI was already at {rsi} — may have bought near a local top")
        if rsi and side == "SELL" and rsi < 35:
            reasons.append(f"RSI was at {rsi} — may have sold near a local bottom")

        # Low confidence
        conf = pre.get("confidence", 0)
        if conf < 0.7:
            reasons.append(f"Confidence was only {conf*100:.0f}% — below ideal threshold")

        if not reasons:
            reasons.append("Market moved in an unexpected direction — no clear single cause")

        for r in reasons:
            lines.append(f"  • {r}")
        lines.append("")

    # Lessons
    lines.append("--- KEY TAKEAWAY ---")
    if prediction_correct and net_pnl > 0:
        lines.append("All sources aligned and the trade was profitable. System worked as designed.")
    elif prediction_correct and net_pnl <= 0:
        lines.append("Direction was correct but charges ate into profits. Consider larger position sizes or longer holds.")
    elif not prediction_correct and abs(move_pct) < 1:
        lines.append("Small adverse move. The market was choppy — HOLD would have been safer.")
    elif not prediction_correct:
        # Find the source that was right
        correct_sources = []
        if ml_correct: correct_sources.append("ML")
        if news_correct: correct_sources.append("News")
        if market_correct: correct_sources.append("Market")
        if correct_sources:
            lines.append(f"Sources that were correct: {', '.join(correct_sources)}. Consider increasing their weight.")
        else:
            lines.append("All sources were wrong. This was an unusual market event — reduce position sizing in similar conditions.")

    return "\n".join(lines)


# ── Auto-close open trades ──────────────────────────────────────────────────

def check_and_close_trades(current_prices: dict, current_indicators: Optional[dict] = None):
    """
    Check all open trades and auto-close those that have hit target or stop-loss.
    current_prices: {symbol: price}
    """
    _load()
    closed = []
    for report in _journal:
        if report["status"] != "OPEN":
            continue
        symbol = report["symbol"]
        if symbol not in current_prices:
            continue

        price = current_prices[symbol]
        pre = report["pre_trade"]
        side = report["side"]

        reason = None
        if side == "BUY":
            if pre.get("target_price") and price >= pre["target_price"]:
                reason = "target_hit"
            elif pre.get("stop_loss_price") and price <= pre["stop_loss_price"]:
                reason = "stop_loss_hit"

        if reason:
            result = close_trade_report(report["trade_id"], price, reason, current_indicators)
            if result:
                closed.append(result)

    return closed


# ── Query helpers ────────────────────────────────────────────────────────────

def get_all_reports():
    """Get all trade journal entries."""
    _load()
    return list(reversed(_journal))


def get_open_reports():
    """Get only open (active) trades."""
    _load()
    return [r for r in _journal if r["status"] == "OPEN"]


def get_closed_reports():
    """Get only closed trades."""
    _load()
    return [r for r in reversed(_journal) if r["status"] in ("CLOSED", "HIT_TARGET", "HIT_SL")]


def get_report_by_id(trade_id: str):
    """Get a specific trade report."""
    _load()
    for r in _journal:
        if r["trade_id"] == trade_id:
            return r
    return None


def get_journal_stats():
    """Get aggregate stats from the trade journal."""
    _load()
    closed = [r for r in _journal if r["status"] in ("CLOSED", "HIT_TARGET", "HIT_SL") and r.get("post_trade")]

    if not closed:
        return {
            "total_trades": len(_journal),
            "open_trades": len([r for r in _journal if r["status"] == "OPEN"]),
            "closed_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "best_trade": None,
            "worst_trade": None,
            "ml_accuracy": 0,
            "news_accuracy": 0,
            "market_accuracy": 0,
        }

    pnls = [r["post_trade"]["net_pnl"] for r in closed]
    wins = [r for r in closed if r["post_trade"]["profitable"]]

    ml_calls = [r for r in closed if r["post_trade"].get("ml_correct") is not None]
    news_calls = [r for r in closed if r["post_trade"].get("news_correct") is not None]
    mkt_calls = [r for r in closed if r["post_trade"].get("market_correct") is not None]

    best = max(closed, key=lambda r: r["post_trade"]["net_pnl"])
    worst = min(closed, key=lambda r: r["post_trade"]["net_pnl"])

    return {
        "total_trades": len(_journal),
        "open_trades": len([r for r in _journal if r["status"] == "OPEN"]),
        "closed_trades": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1),
        "total_pnl": round(sum(pnls), 2),
        "avg_pnl": round(sum(pnls) / len(pnls), 2),
        "total_charges": round(sum(r["post_trade"]["total_charges"] for r in closed), 2),
        "best_trade": {"trade_id": best["trade_id"], "symbol": best["symbol"], "pnl": best["post_trade"]["net_pnl"]},
        "worst_trade": {"trade_id": worst["trade_id"], "symbol": worst["symbol"], "pnl": worst["post_trade"]["net_pnl"]},
        "prediction_accuracy": round(len([r for r in closed if r["post_trade"]["prediction_correct"]]) / len(closed) * 100, 1),
        "ml_accuracy": round(len([r for r in ml_calls if r["post_trade"]["ml_correct"]]) / len(ml_calls) * 100, 1) if ml_calls else 0,
        "news_accuracy": round(len([r for r in news_calls if r["post_trade"]["news_correct"]]) / len(news_calls) * 100, 1) if news_calls else 0,
        "market_accuracy": round(len([r for r in mkt_calls if r["post_trade"]["market_correct"]]) / len(mkt_calls) * 100, 1) if mkt_calls else 0,
    }
