"""
Telegram Alerts — push notifications for trades, signals, and daily summaries.

Uses raw Telegram Bot API via requests (no extra dependencies).
Configure: set 'telegram_bot_token' and 'telegram_chat_id' in DB config settings.

To get your bot token: message @BotFather on Telegram → /newbot
To get your chat_id: message @userinfobot on Telegram
"""

import logging
import json
import requests
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.telegram.org/bot{token}/{method}"


# ─── Core ────────────────────────────────────────────────────────────────────

def _get_config():
    """Get Telegram config from DB."""
    try:
        from db_manager import get_config
        token = get_config("telegram_bot_token")
        chat_id = get_config("telegram_chat_id")
        enabled = get_config("telegram_enabled", "false")
        return token, chat_id, enabled.lower() == "true"
    except Exception:
        return None, None, False


def is_enabled():
    """Check if Telegram alerts are configured and enabled."""
    token, chat_id, enabled = _get_config()
    return bool(token and chat_id and enabled)


def send_message(text, parse_mode="HTML", disable_preview=True, reply_markup=None):
    """Send a message via Telegram Bot API."""
    token, chat_id, enabled = _get_config()
    if not token or not chat_id or not enabled:
        return {"ok": False, "error": "Telegram not configured or disabled"}

    url = _BASE_URL.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram send failed: %s", data.get("description"))
        return data
    except Exception as e:
        logger.warning("Telegram send error: %s", e)
        return {"ok": False, "error": str(e)}


def test_connection():
    """Test Telegram bot connection by sending a test message."""
    token, chat_id, _ = _get_config()
    if not token or not chat_id:
        return {"ok": False, "error": "Bot token or chat ID not configured"}

    try:
        # Test getMe
        url = _BASE_URL.format(token=token, method="getMe")
        resp = requests.get(url, timeout=10)
        me = resp.json()
        if not me.get("ok"):
            return {"ok": False, "error": f"Invalid bot token: {me.get('description')}"}

        bot_name = me["result"]["username"]

        # Send test
        url = _BASE_URL.format(token=token, method="sendMessage")
        payload = {"chat_id": chat_id, "text": f"✅ Groww AI Bot connected!\nBot: @{bot_name}\nTime: {datetime.now().strftime('%H:%M:%S')}"}
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get("ok"):
            return {"ok": True, "bot_name": bot_name}
        return {"ok": False, "error": result.get("description", "Send failed")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Quick-Action Keyboards ──────────────────────────────────────────────────

def _trade_buttons():
    """Inline buttons shown after trade alerts."""
    return {"inline_keyboard": [
        [{"text": "Trading", "callback_data": "cmd_trading"}, {"text": "Paper", "callback_data": "cmd_paperdesk"}, {"text": "Journal", "callback_data": "cmd_journal"}],
        [{"text": "P&L", "callback_data": "cmd_pnl"}, {"text": "Holdings", "callback_data": "cmd_holdings"}, {"text": "Pause Bot", "callback_data": "cmd_stop"}],
    ]}


def _signal_buttons():
    """Inline buttons shown after signal alerts."""
    return {"inline_keyboard": [
        [{"text": "Research", "callback_data": "cmd_research"}, {"text": "Watchlist", "callback_data": "cmd_watchlist"}, {"text": "Signals", "callback_data": "cmd_signals"}],
        [{"text": "Markets", "callback_data": "cmd_market"}, {"text": "Main Menu", "callback_data": "cmd_menu"}],
    ]}


# ─── Alert Formatters ────────────────────────────────────────────────────────

def alert_trade_executed(symbol, side, quantity, price, order_id=None, charges=0, paper=False, reason=""):
    """Alert when a trade is executed."""
    text = (
        f"{'[PAPER] ' if paper else ''}<b>{side} {symbol}</b>\n"
        f"Qty: {quantity} | Price: ₹{price:,.2f}\n"
        f"Value: ₹{price * quantity:,.2f}"
    )
    if charges:
        text += f"\nCharges: ₹{charges:,.2f}"
    if order_id:
        text += f"\nOrder: {order_id}"
    if reason:
        text += f"\n\n<b>AI Reasoning:</b>\n{reason}"
    text += f"\n{datetime.now().strftime('%H:%M:%S')}"
    return send_message(text, reply_markup=_trade_buttons())


def alert_trade_closed(symbol, side, exit_price, trade_id=None):
    """Alert when a tracked trade is closed."""
    trade = None
    try:
        from paper_trader import PaperTradeTracker
        tracker = PaperTradeTracker()
        trade = next((t for t in tracker.trades if t.get("id") == trade_id), None)
    except Exception:
        trade = None

    status = (trade or {}).get("status", "CLOSED")
    entry_price = (trade or {}).get("entry_price")
    quantity = (trade or {}).get("quantity")
    net_pnl = (trade or {}).get("net_pnl")
    gross_pnl = (trade or {}).get("gross_pnl")
    charges = (trade or {}).get("total_charges")
    exit_reason = (trade or {}).get("exit_reason", "closed")
    highest_price = (trade or {}).get("highest_price_reached")
    covered = (trade or {}).get("has_covered_costs")
    post_trade = (trade or {}).get("post_trade") or {}
    duration = post_trade.get("duration_minutes")

    if net_pnl is None and entry_price is not None and quantity:
        if side == "BUY":
            gross_pnl = (exit_price - entry_price) * quantity
        else:
            gross_pnl = (entry_price - exit_price) * quantity
        charges = charges or 0
        net_pnl = gross_pnl - charges

    pnl_icon = "🟢" if (net_pnl or 0) >= 0 else "🔴"
    text = (
        f"{pnl_icon} <b>{symbol} Closed</b>\n"
        f"Status: {status} | Side: {side}\n"
    )
    if entry_price is not None:
        text += f"Entry: ₹{entry_price:,.2f}"
        if quantity:
            text += f" x {quantity}"
        text += f"\nExit: ₹{exit_price:,.2f}"
    else:
        text += f"Exit: ₹{exit_price:,.2f}"

    if gross_pnl is not None:
        text += f"\nGross P&L: ₹{gross_pnl:,.2f}"
    if charges is not None:
        text += f" | Charges: ₹{charges:,.2f}"
    if net_pnl is not None:
        text += f"\nNet P&L: ₹{net_pnl:+,.2f}"
    if highest_price is not None:
        text += f"\nBest price seen: ₹{highest_price:,.2f}"
    if covered is not None:
        text += f" | Costs covered: {'Yes' if covered else 'No'}"
    if duration is not None:
        text += f"\nDuration: {duration} min"
    if exit_reason:
        text += f"\nReason: {exit_reason}"
    if trade_id:
        text += f"\nTrade ID: {trade_id}"
    text += f"\n{datetime.now().strftime('%H:%M:%S')}"
    return send_message(text, reply_markup=_trade_buttons())


def alert_fno_trade(symbol, side, quantity, premium, instrument_key=None, paper=False):
    """Alert for F&O trade."""
    prefix = "📝 PAPER" if paper else "⚡"
    emoji = "🟢" if side == "BUY" else "🔴"
    text = (
        f"{prefix} <b>F&O Trade</b>\n"
        f"{emoji} <b>{side} {symbol}</b>\n"
        f"Qty: {quantity} | Premium: ₹{premium:,.2f}\n"
        f"Total: ₹{premium * quantity:,.2f}"
    )
    if instrument_key:
        text += f"\nInstrument: {instrument_key}"
    text += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    return send_message(text, reply_markup=_trade_buttons())


def alert_stop_loss_hit(symbol, entry_price, exit_price, pnl, pnl_pct):
    """Alert when stop-loss is triggered."""
    text = (
        f"🛑 <b>Stop-Loss Hit</b>\n"
        f"<b>{symbol}</b>\n"
        f"Entry: ₹{entry_price:,.2f} → Exit: ₹{exit_price:,.2f}\n"
        f"P&L: ₹{pnl:,.2f} ({pnl_pct:+.1f}%)\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(text)


def alert_target_hit(symbol, entry_price, exit_price, pnl, pnl_pct):
    """Alert when target is hit."""
    text = (
        f"🎯 <b>Target Reached!</b>\n"
        f"<b>{symbol}</b>\n"
        f"Entry: ₹{entry_price:,.2f} → Exit: ₹{exit_price:,.2f}\n"
        f"P&L: ₹{pnl:,.2f} ({pnl_pct:+.1f}%)\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(text)


def alert_signal(symbol, signal, confidence, alpha_score=None):
    """Alert on a strong signal from the research engine."""
    emoji = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "SELL": "🔴", "REDUCE": "🔴🔴", "STRONG_SELL": "🔴🔴"}.get(signal, "🟡")
    text = (
        f"{emoji} <b>Signal: {signal}</b>\n"
        f"<b>{symbol}</b>\n"
        f"Confidence: {confidence:.0f}%"
    )
    if alpha_score:
        text += f"\nAlpha Score: {alpha_score}"
    text += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
    return send_message(text, reply_markup=_signal_buttons())


def alert_daily_summary(portfolio_value=0, day_pnl=0, open_positions=0,
                        top_signals=None, market_mood=""):
    """Send daily summary (typically end of day)."""
    text = (
        f"📊 <b>Daily Summary</b> — {datetime.now().strftime('%d %b %Y')}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Portfolio: ₹{portfolio_value:,.0f}\n"
        f"Day P&L: ₹{day_pnl:+,.0f}\n"
        f"Open Positions: {open_positions}\n"
    )
    if market_mood:
        text += f"Market: {market_mood}\n"
    if top_signals:
        text += "\n<b>Top Signals:</b>\n"
        for s in top_signals[:5]:
            text += f"  {s['symbol']}: {s['signal']} (α={s.get('alpha', 'N/A')})\n"
    return send_message(text, reply_markup=_signal_buttons())


def alert_portfolio_warning(symbol, message, severity="WARNING"):
    """Alert for portfolio-level warnings (large drawdown, margin call, etc.)."""
    emoji = {"WARNING": "⚠️", "CRITICAL": "🚨", "INFO": "ℹ️"}.get(severity, "⚠️")
    text = (
        f"{emoji} <b>{severity}</b>\n"
        f"<b>{symbol}</b>\n"
        f"{message}\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(text)


def alert_research(symbol, verdict, alpha_score, conviction, catalysts=None):
    """Alert on significant research findings."""
    emoji = {"STRONG_BUY": "🟢🟢", "BUY": "🟢", "ACCUMULATE": "🔵",
             "HOLD": "🟡", "REDUCE": "🟠", "SELL": "🔴"}.get(verdict, "🟡")
    text = (
        f"{emoji} <b>Research: {verdict}</b>\n"
        f"<b>{symbol}</b>\n"
        f"Alpha: {alpha_score} | Conviction: {conviction}%"
    )
    if catalysts:
        text += "\n<b>Catalysts:</b>"
        for c in catalysts[:3]:
            text += f"\n  • {c.get('catalyst', c) if isinstance(c, dict) else c}"
    return send_message(text)


# ─── Scheduled Summary ───────────────────────────────────────────────────────

def send_scheduled_summary():
    """Generate and send a daily summary. Called by scheduler."""
    if not is_enabled():
        return

    try:
        # Gather portfolio data
        from bot import get_holdings, get_predictions
        holdings = get_holdings()
        total_value = sum(h.get("current_value", 0) for h in holdings) if holdings else 0
        total_pnl = sum(h.get("pnl", 0) for h in holdings) if holdings else 0

        # Get research leaderboard top signals
        from research_engine import get_cached_leaderboard
        lb = get_cached_leaderboard() or []
        top = []
        for s in lb[:5]:
            v = s.get("verdict", {})
            stance = v.get("stance", "HOLD") if isinstance(v, dict) else v
            top.append({"symbol": s["symbol"], "signal": stance, "alpha": s.get("alpha_score", 0)})

        alert_daily_summary(
            portfolio_value=total_value,
            day_pnl=total_pnl,
            open_positions=len(holdings) if holdings else 0,
            top_signals=top,
        )
    except Exception as e:
        logger.warning("Daily summary alert failed: %s", e)
