"""
Daily Market Summary — generates a comprehensive end-of-day report
covering last trading day performance, market environment, and next-day outlook.
Sends the summary via Telegram.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _safe(fn, default=None):
    """Run fn() and return default on any error."""
    try:
        return fn()
    except Exception as e:
        logger.debug("daily_summary helper failed: %s", e)
        return default


def generate_daily_summary():
    """Build the full daily summary dict with all available data."""
    now_ist = datetime.now(IST)
    today = now_ist.date()

    summary = {
        "date": today.strftime("%d %b %Y (%A)"),
        "generated_at": now_ist.strftime("%H:%M IST"),
    }

    # ── 1. Global Indices ─────────────────────────────────────────────────
    indices = _safe(lambda: _get_indices(), {})
    summary["indices"] = indices

    # ── 2. Market Sentiment (news) ────────────────────────────────────────
    sentiment = _safe(lambda: _get_market_sentiment(), {})
    summary["sentiment"] = sentiment

    # ── 3. Top Signals / Research Leaderboard ─────────────────────────────
    signals = _safe(lambda: _get_top_signals(), [])
    summary["top_signals"] = signals

    # ── 4. Portfolio Snapshot ─────────────────────────────────────────────
    portfolio = _safe(lambda: _get_portfolio_snapshot(), {})
    summary["portfolio"] = portfolio

    # ── 5. Watchlist Predictions for Tomorrow ─────────────────────────────
    predictions = _safe(lambda: _get_watchlist_predictions(), [])
    summary["predictions"] = predictions

    # ── 6. Key News Headlines ─────────────────────────────────────────────
    news = _safe(lambda: _get_key_news(), [])
    summary["news"] = news

    # ── 7. Candle Stats (last trading day) ────────────────────────────────
    candle_stats = _safe(lambda: _get_last_day_candle_stats(), {})
    summary["candle_stats"] = candle_stats

    return summary


# ── Data Gatherers ────────────────────────────────────────────────────────────


def _get_indices():
    """Fetch global and Indian indices with timeout."""
    import concurrent.futures
    def _fetch():
        from fno_trader import fetch_global_indices
        raw = fetch_global_indices()
        if not raw:
            return {}
        result = {}
        for key, val in raw.items():
            if isinstance(val, dict):
                price = val.get("close") or val.get("price") or val.get("ltp")
                chg = val.get("change_pct") or val.get("dayChangePerc")
                result[key] = {"price": price, "change_pct": chg}
            elif isinstance(val, (int, float)):
                result[key] = {"price": val}
        return result
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_fetch)
            return future.result(timeout=15)  # 15s max
    except Exception:
        return {}


def _get_market_sentiment():
    """Get overall market news sentiment."""
    try:
        from news_sentiment import get_market_sentiment
        s = get_market_sentiment()
        if not s:
            return {}
        return {
            "score": getattr(s, "avg_score", 0),
            "label": "Bullish" if getattr(s, "avg_score", 0) > 0.1 else
                     "Bearish" if getattr(s, "avg_score", 0) < -0.1 else "Neutral",
            "articles_count": getattr(s, "article_count", 0),
        }
    except Exception:
        return {}


def _get_top_signals():
    """Get top research signals."""
    try:
        from research_engine import get_cached_leaderboard
        lb = get_cached_leaderboard()
        if not lb:
            return []
        result = []
        items = lb if isinstance(lb, list) else lb.get("stocks", [])
        for s in items[:8]:
            if not isinstance(s, dict):
                continue
            verdict = s.get("verdict", {})
            stance = verdict.get("stance", "HOLD") if isinstance(verdict, dict) else str(verdict)
            result.append({
                "symbol": s.get("symbol", "?"),
                "signal": stance,
                "alpha": s.get("alpha_score", 0),
                "confidence": s.get("confidence", 0),
            })
        return result
    except Exception:
        return []


def _get_portfolio_snapshot():
    """Get current portfolio holdings summary."""
    try:
        from bot import get_holdings
        holdings = get_holdings()
        if not holdings:
            return {"count": 0, "total_value": 0, "total_pnl": 0}
        total_val = sum(h.get("current_value", 0) for h in holdings)
        total_pnl = sum(h.get("pnl", 0) for h in holdings)
        top = sorted(holdings, key=lambda h: abs(h.get("pnl", 0)), reverse=True)[:5]
        return {
            "count": len(holdings),
            "total_value": round(total_val, 2),
            "total_pnl": round(total_pnl, 2),
            "top_movers": [
                {"symbol": h.get("symbol", "?"), "pnl": round(h.get("pnl", 0), 2),
                 "pnl_pct": round(h.get("pnl_pct", 0), 2)}
                for h in top
            ],
        }
    except Exception:
        return {}


def _get_watchlist_predictions():
    """Get ML predictions for each watchlist stock using DB candles only (no live API calls)."""
    try:
        from config import WATCHLIST
        from db_manager import CandleDatabase, Candle
        from predictor import StockPredictor
        from sqlalchemy import text
        import pandas as pd

        db = CandleDatabase()
        preds = []
        for sym in WATCHLIST:
            try:
                # Read last 200 5-min candles from DB directly (fast, no API)
                with db.engine.connect() as conn:
                    rows = conn.execute(text(
                        "SELECT timestamp, open, high, low, close, volume "
                        "FROM candles WHERE symbol=:sym ORDER BY timestamp DESC LIMIT 200"
                    ), {"sym": sym}).fetchall()
                if not rows or len(rows) < 30:
                    continue
                df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df = df.sort_values("timestamp").reset_index(drop=True)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                predictor = StockPredictor()
                result = predictor.predict(df)
                if result and isinstance(result, dict):
                    preds.append({
                        "symbol": sym,
                        "signal": result.get("signal", "HOLD"),
                        "confidence": round(result.get("confidence", 0) * 100, 1)
                              if result.get("confidence", 0) <= 1
                              else round(result.get("confidence", 0), 1),
                        "reason": (result.get("reason", "") or "")[:80],
                    })
            except Exception:
                pass
        return sorted(preds, key=lambda x: x.get("confidence", 0), reverse=True)
    except Exception:
        return []


def _get_key_news():
    """Get top recent news headlines."""
    try:
        from world_news_collector import get_recent_news
        articles = get_recent_news(limit=10, days=1)
        if not articles:
            return []
        return [
            {"title": a.get("title", "")[:100], "sentiment": a.get("sentiment", "neutral")}
            for a in articles[:6] if isinstance(a, dict)
        ]
    except Exception:
        return []


def _get_last_day_candle_stats():
    """Get last trading day's candle summary for key indices."""
    try:
        from db_manager import CandleDatabase, Candle
        from sqlalchemy import func, text
        db = CandleDatabase()
        with db.engine.connect() as conn:
            # Get the most recent trading date in DB
            row = conn.execute(text(
                "SELECT MAX(DATE(timestamp)) FROM candles"
            )).scalar()
            if not row:
                return {}
            last_date = row

            # Get open/close/high/low for key symbols on that date
            stats = {}
            for sym in ["NIFTY", "BANKNIFTY", "RELIANCE", "TCS", "HDFCBANK"]:
                r = conn.execute(text("""
                    SELECT
                        (SELECT open FROM candles WHERE symbol=:sym AND DATE(timestamp)=:dt ORDER BY timestamp ASC LIMIT 1) as day_open,
                        (SELECT close FROM candles WHERE symbol=:sym AND DATE(timestamp)=:dt ORDER BY timestamp DESC LIMIT 1) as day_close,
                        MAX(high) as day_high, MIN(low) as day_low, SUM(volume) as day_vol
                    FROM candles WHERE symbol=:sym AND DATE(timestamp)=:dt
                """), {"sym": sym, "dt": last_date}).fetchone()
                if r and r[0] is not None:
                    day_open, day_close = float(r[0]), float(r[1])
                    change_pct = ((day_close - day_open) / day_open * 100) if day_open else 0
                    stats[sym] = {
                        "open": round(day_open, 2),
                        "close": round(day_close, 2),
                        "high": round(float(r[2]), 2),
                        "low": round(float(r[3]), 2),
                        "volume": int(r[4] or 0),
                        "change_pct": round(change_pct, 2),
                    }
            stats["_date"] = str(last_date)
            return stats
    except Exception as e:
        logger.debug("Candle stats failed: %s", e)
        return {}


# ── Telegram Formatter ────────────────────────────────────────────────────────


def format_telegram_summary(summary):
    """Convert summary dict into a Telegram HTML message."""
    lines = []
    lines.append(f"<b>📊 Daily Market Summary</b>")
    lines.append(f"{summary.get('date', '')}  •  {summary.get('generated_at', '')}")
    lines.append("")

    # ── Indices ────────────────────────
    indices = summary.get("indices", {})
    if indices:
        lines.append("<b>🌐 Market Indices</b>")
        for name, data in list(indices.items())[:8]:
            if not isinstance(data, dict):
                continue
            price = data.get("price")
            chg = data.get("change_pct")
            if price:
                emoji = "🟢" if (chg or 0) >= 0 else "🔴"
                chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
                lines.append(f"  {emoji} {name}: {price:,.2f}{chg_str}" if isinstance(price, (int, float))
                             else f"  {emoji} {name}: {price}{chg_str}")
        lines.append("")

    # ── Last Day Candle Stats ─────────
    cs = summary.get("candle_stats", {})
    last_date = cs.pop("_date", None)
    if cs:
        lines.append(f"<b>📈 Last Trading Day</b>" + (f" ({last_date})" if last_date else ""))
        for sym, data in cs.items():
            chg = data.get("change_pct", 0)
            emoji = "🟢" if chg >= 0 else "🔴"
            lines.append(f"  {emoji} <b>{sym}</b>: {data['close']:,.2f} ({chg:+.2f}%)  "
                         f"H:{data['high']:,.2f} L:{data['low']:,.2f}")
        lines.append("")

    # ── Sentiment ─────────────────────
    sent = summary.get("sentiment", {})
    if sent:
        label = sent.get("label", "Neutral")
        emoji = "🟢" if label == "Bullish" else "🔴" if label == "Bearish" else "🟡"
        lines.append(f"<b>🧠 Market Sentiment</b>: {emoji} {label} "
                     f"(score: {sent.get('score', 0):.2f}, {sent.get('articles_count', 0)} articles)")
        lines.append("")

    # ── Portfolio ─────────────────────
    pf = summary.get("portfolio", {})
    if pf.get("count", 0) > 0:
        pnl = pf.get("total_pnl", 0)
        emoji = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"<b>💼 Portfolio</b>: {pf['count']} holdings  •  "
                     f"₹{pf.get('total_value', 0):,.0f}  •  "
                     f"{emoji} P&L: ₹{pnl:+,.0f}")
        for m in pf.get("top_movers", [])[:3]:
            me = "🟢" if m["pnl"] >= 0 else "🔴"
            lines.append(f"  {me} {m['symbol']}: ₹{m['pnl']:+,.0f} ({m['pnl_pct']:+.1f}%)")
        lines.append("")

    # ── Tomorrow's Signals ────────────
    preds = summary.get("predictions", [])
    if preds:
        lines.append("<b>🔮 Tomorrow's Outlook</b>")
        for p in preds[:8]:
            sig = p.get("signal", "HOLD")
            emoji = "🟢" if sig == "BUY" else "🔴" if sig == "SELL" else "🟡"
            conf = p.get("confidence", 0)
            reason = p.get("reason", "")
            lines.append(f"  {emoji} <b>{p['symbol']}</b>: {sig} ({conf}%)"
                         + (f" — {reason}" if reason else ""))
        lines.append("")

    # ── Top Research Signals ──────────
    sigs = summary.get("top_signals", [])
    if sigs:
        lines.append("<b>🏆 Research Leaderboard</b>")
        for s in sigs[:5]:
            sig = s.get("signal", "HOLD")
            emoji = "🟢" if sig in ("BUY", "STRONG_BUY") else "🔴" if sig in ("SELL", "STRONG_SELL") else "🟡"
            lines.append(f"  {emoji} <b>{s['symbol']}</b>: {sig} (α={s.get('alpha', 0):.1f})")
        lines.append("")

    # ── Key News ──────────────────────
    news = summary.get("news", [])
    if news:
        lines.append("<b>📰 Key News</b>")
        for n in news[:4]:
            se = "🟢" if n.get("sentiment") == "positive" else "🔴" if n.get("sentiment") == "negative" else "•"
            lines.append(f"  {se} {n.get('title', '')}")
        lines.append("")

    lines.append("—")
    lines.append("<i>Groww AI Bot • Auto-generated</i>")

    return "\n".join(lines)


def send_daily_summary():
    """Generate and send the full daily summary via Telegram."""
    try:
        import telegram_alerts
        if not telegram_alerts.is_enabled():
            logger.debug("Telegram not enabled — skipping daily summary")
            return {"sent": False, "reason": "telegram_disabled"}

        summary = generate_daily_summary()
        msg = format_telegram_summary(summary)

        # Telegram has a 4096 char limit per message
        if len(msg) > 4000:
            # Split at double newline closest to midpoint
            mid = len(msg) // 2
            split_idx = msg.rfind("\n\n", 0, mid + 500)
            if split_idx == -1:
                split_idx = mid
            part1 = msg[:split_idx]
            part2 = msg[split_idx:].lstrip("\n")
            telegram_alerts.send_message(part1)
            telegram_alerts.send_message(part2)
        else:
            telegram_alerts.send_message(msg)

        logger.info("✅ Daily summary sent to Telegram (%d chars)", len(msg))
        return {"sent": True, "chars": len(msg)}
    except Exception as e:
        logger.error("Failed to send daily summary: %s", e)
        return {"sent": False, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    s = generate_daily_summary()
    msg = format_telegram_summary(s)
    print(msg)
    print(f"\n--- {len(msg)} chars ---")
