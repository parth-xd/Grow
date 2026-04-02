"""
Telegram Commander — interactive bot that listens for commands via polling.

Gives remote control of the trading bot from Telegram:
  /status    — System status, scheduler state, uptime
  /balance   — Groww balance + available margin
  /holdings  — Current holdings with P&L
  /trades    — Recent paper/real trades
  /pnl       — Today's P&L summary
  /positions — Open F&O positions
  /analysis  — Latest AI analysis summary
  /signals   — Top buy/sell signals right now
  /stop      — Pause all scheduler tasks (emergency stop)
  /start     — Resume all scheduler tasks
  /paper     — Toggle paper trading mode
  /help      — Show all commands
"""

import logging
import os
import html
import threading
import time
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_BASE_URL = "https://api.telegram.org/bot{token}/{method}"
_polling_thread = None
_last_update_id = 0
_scheduler_paused = False  # Global pause flag checked by scheduler


def is_scheduler_paused():
    """Check if scheduler is paused via Telegram command."""
    return _scheduler_paused


def _get_config():
    try:
        from db_manager import get_config
        token = get_config("telegram_bot_token")
        chat_id = get_config("telegram_chat_id")
        return token, chat_id
    except Exception:
        return None, None


def _send(text, token=None, chat_id=None, parse_mode="HTML", reply_markup=None):
    """Send a message back to the user."""
    if not token or not chat_id:
        token, chat_id = _get_config()
    if not token or not chat_id:
        return
    url = _BASE_URL.format(token=token, method="sendMessage")
    # Telegram has a 4096 char limit per message
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        # Only attach buttons to the last chunk
        if reply_markup and i + 4000 >= len(text):
            payload["reply_markup"] = reply_markup
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.warning("Telegram send error: %s", e)


def _answer_callback(callback_query_id, token, text=None):
    """Answer a callback query to dismiss the loading spinner."""
    url = _BASE_URL.format(token=token, method="answerCallbackQuery")
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass


def _escape(value):
    return html.escape(str(value)) if value is not None else ""


def _truncate(text, limit=120):
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit - 1] + "…"


def _fmt_money(value, signed=False, decimals=2):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"

    abs_text = f"₹{abs(amount):,.{decimals}f}"
    if signed:
        if amount > 0:
            return f"+{abs_text}"
        if amount < 0:
            return f"-{abs_text}"
        return f"₹{0:,.{decimals}f}"
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs_text}"


def _fmt_pct(value, signed=True, decimals=1):
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "—"

    abs_text = f"{abs(pct):,.{decimals}f}%"
    if signed:
        if pct > 0:
            return f"+{abs_text}"
        if pct < 0:
            return f"-{abs_text}"
        return f"{0:,.{decimals}f}%"
    sign = "-" if pct < 0 else ""
    return f"{sign}{abs_text}"


def _time_ago(iso_text):
    if not iso_text:
        return "—"
    try:
        cleaned = str(iso_text).replace("Z", "+00:00")
        when = datetime.fromisoformat(cleaned)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - when.astimezone(timezone.utc)
        seconds = max(int(delta.total_seconds()), 0)
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return str(iso_text)[:16]


def _extract_symbol(args):
    if not args:
        return ""
    return str(args).strip().split()[0].upper().replace(",", "")


def _response(text, reply_markup=None, parse_mode="HTML"):
    payload = {"text": text, "parse_mode": parse_mode}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return payload


def _dispatch_response(response, token, chat_id, default_reply_markup=None):
    if response is None:
        return

    text = response
    reply_markup = default_reply_markup
    parse_mode = "HTML"

    if isinstance(response, dict):
        text = response.get("text", "")
        parse_mode = response.get("parse_mode", "HTML")
        if "reply_markup" in response:
            reply_markup = response["reply_markup"]

    if not isinstance(text, str):
        text = str(text)

    if text:
        _send(text, token=token, chat_id=chat_id, parse_mode=parse_mode, reply_markup=reply_markup)


def _menu_keyboard(rows, back_target="cmd_menu", back_text="<< Main Menu"):
    keyboard_rows = [list(row) for row in rows]
    keyboard_rows.append([{"text": back_text, "callback_data": back_target}])
    return {"inline_keyboard": keyboard_rows}


def _symbol_rows(prefix, symbols, per_row=3):
    rows = []
    current = []
    for symbol in symbols:
        current.append({"text": symbol, "callback_data": f"{prefix}:{symbol}"})
        if len(current) == per_row:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows


def _get_watchlist_rows():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        db_url = os.getenv("DB_URL")
        if db_url:
            conn = psycopg2.connect(db_url, connect_timeout=3)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT DISTINCT symbol,
                       COUNT(*) AS price_candles,
                       MIN(date) AS earliest_date,
                       MAX(date) AS latest_date
                FROM stock_prices
                GROUP BY symbol
                ORDER BY symbol
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return rows
    except Exception as e:
        logger.debug("Watchlist lookup failed: %s", e)

    try:
        from config import WATCHLIST
        return [{"symbol": s, "price_candles": None, "earliest_date": None, "latest_date": None} for s in WATCHLIST]
    except Exception:
        return []


def _get_watchlist_symbols(limit=None):
    symbols = [row.get("symbol") for row in _get_watchlist_rows() if row.get("symbol")]
    if limit is not None:
        return symbols[:limit]
    return symbols


def _get_thesis_symbols(limit=None):
    try:
        from thesis_manager import get_manager
        symbols = [t.symbol for t in get_manager().get_all_theses()]
    except Exception:
        symbols = []
    if limit is not None:
        return symbols[:limit]
    return symbols


def _get_research_symbols(limit=None):
    try:
        from research_engine import get_cached_leaderboard
        lb = get_cached_leaderboard() or []
        symbols = [row.get("symbol") for row in lb if row.get("symbol")]
    except Exception:
        symbols = []
    if limit is not None:
        return symbols[:limit]
    return symbols


def _main_menu_keyboard():
    """Build the Telegram dashboard main menu."""
    return {"inline_keyboard": [
        [{"text": "Dashboard", "callback_data": "cmd_dashboard"}, {"text": "Markets", "callback_data": "cmd_market"}],
        [{"text": "Watchlist", "callback_data": "cmd_watchlist"}, {"text": "Research", "callback_data": "cmd_research"}],
        [{"text": "Trading", "callback_data": "cmd_trading"}, {"text": "Paper", "callback_data": "cmd_paperdesk"}],
        [{"text": "Journal", "callback_data": "cmd_journal"}, {"text": "F&O", "callback_data": "cmd_fno"}],
        [{"text": "Thesis", "callback_data": "cmd_thesis"}, {"text": "Controls", "callback_data": "cmd_controls"}],
    ]}


def _back_button(back_target="cmd_menu", label="<< Main Menu"):
    """Single back button keyboard."""
    return {"inline_keyboard": [[{"text": label, "callback_data": back_target}]]}


def _market_keyboard():
    rows = [
        [{"text": "Market Sentiment", "callback_data": "cmd_market"}, {"text": "World News", "callback_data": "cmd_worldnews"}],
        [{"text": "Macro", "callback_data": "cmd_worldnews:macro"}, {"text": "Sector", "callback_data": "cmd_worldnews:sector"}],
        [{"text": "Global", "callback_data": "cmd_worldnews:global"}, {"text": "Raw Materials", "callback_data": "cmd_rawmat"}],
        [{"text": "Collect World News", "callback_data": "cmd_worldcollect"}],
    ]
    quick_symbols = _get_watchlist_symbols(limit=4)
    if quick_symbols:
        rows.extend(_symbol_rows("cmd_newsstock", quick_symbols, per_row=2))
    return _menu_keyboard(rows)


def _watchlist_keyboard():
    rows = [
        [{"text": "Watchlist Summary", "callback_data": "cmd_watchlist"}, {"text": "Scan Now", "callback_data": "cmd_watchscan"}],
        [{"text": "Latest AI", "callback_data": "cmd_analysis"}, {"text": "Run AI Now", "callback_data": "cmd_runanalysis"}],
    ]
    quick_symbols = _get_watchlist_symbols(limit=6)
    if quick_symbols:
        rows.extend(_symbol_rows("cmd_watchstock", quick_symbols, per_row=3))
    return _menu_keyboard(rows)


def _research_keyboard():
    rows = [
        [{"text": "Leaderboard", "callback_data": "cmd_research"}, {"text": "Run All Research", "callback_data": "cmd_runresearch"}],
    ]
    quick_symbols = _get_research_symbols(limit=6)
    if quick_symbols:
        rows.extend(_symbol_rows("cmd_researchstock", quick_symbols, per_row=3))
    return _menu_keyboard(rows)


def _trading_keyboard():
    return _menu_keyboard([
        [{"text": "Status", "callback_data": "cmd_status"}, {"text": "Balance", "callback_data": "cmd_balance"}, {"text": "P&L", "callback_data": "cmd_pnl"}],
        [{"text": "Holdings", "callback_data": "cmd_holdings"}, {"text": "Trades", "callback_data": "cmd_trades"}, {"text": "Positions", "callback_data": "cmd_positions"}],
        [{"text": "Run Auto-Trade", "callback_data": "cmd_autotrade"}, {"text": "Monitor Stops", "callback_data": "cmd_stops"}],
        [{"text": "Paper Desk", "callback_data": "cmd_paperdesk"}, {"text": "Journal", "callback_data": "cmd_journal"}],
    ])


def _paper_keyboard():
    return _menu_keyboard([
        [{"text": "Paper Desk", "callback_data": "cmd_paperdesk"}, {"text": "Open Trades", "callback_data": "cmd_paper_open"}],
        [{"text": "Closed Trades", "callback_data": "cmd_paper_closed"}, {"text": "Toggle Paper Mode", "callback_data": "cmd_paper_toggle"}],
        [{"text": "Journal", "callback_data": "cmd_journal"}, {"text": "Trading", "callback_data": "cmd_trading"}],
    ])


def _journal_keyboard():
    return _menu_keyboard([
        [{"text": "Journal Summary", "callback_data": "cmd_journal"}, {"text": "Open Trades", "callback_data": "cmd_journal_open"}],
        [{"text": "Closed Trades", "callback_data": "cmd_journal_closed"}, {"text": "Paper Trades", "callback_data": "cmd_journal_paper"}],
        [{"text": "Actual Trades", "callback_data": "cmd_journal_actual"}],
    ])


def _fno_keyboard():
    return _menu_keyboard([
        [{"text": "F&O Desk", "callback_data": "cmd_fno"}, {"text": "Best Setup", "callback_data": "cmd_fno_best"}],
        [{"text": "Tomorrow Signals", "callback_data": "cmd_fno_tomorrow"}, {"text": "Global Indices", "callback_data": "cmd_fno_global"}],
        [{"text": "F&O Positions", "callback_data": "cmd_fno_positions"}, {"text": "Auto Log", "callback_data": "cmd_fno_autolog"}],
        [{"text": "Run F&O Auto", "callback_data": "cmd_fno_run"}],
    ])


def _thesis_keyboard():
    rows = [
        [{"text": "Thesis Summary", "callback_data": "cmd_thesis"}],
    ]
    quick_symbols = _get_thesis_symbols(limit=6)
    if quick_symbols:
        rows.extend(_symbol_rows("cmd_thesisstock", quick_symbols, per_row=3))
    return _menu_keyboard(rows)


def _controls_keyboard():
    return _menu_keyboard([
        [{"text": "Pause Bot", "callback_data": "cmd_stop"}, {"text": "Resume Bot", "callback_data": "cmd_start"}],
        [{"text": "Toggle Cash Auto", "callback_data": "cmd_cashtrade"}, {"text": "Toggle Paper Mode", "callback_data": "cmd_paper_toggle"}],
        [{"text": "Send Daily Summary", "callback_data": "cmd_summary"}],
    ])


def _default_reply_markup(callback_name):
    if callback_name in {"cmd_status", "cmd_balance", "cmd_pnl", "cmd_holdings", "cmd_trades", "cmd_positions", "cmd_autotrade", "cmd_stops"}:
        return _back_button("cmd_trading", "<< Trading")
    if callback_name in {"cmd_analysis", "cmd_watchscan", "cmd_watchstock", "cmd_runanalysis"}:
        return _back_button("cmd_watchlist", "<< Watchlist")
    if callback_name in {"cmd_market", "cmd_worldnews", "cmd_rawmat", "cmd_newsstock", "cmd_worldcollect"}:
        return _back_button("cmd_market", "<< Markets")
    if callback_name in {"cmd_research", "cmd_researchstock", "cmd_runresearch"}:
        return _back_button("cmd_research", "<< Research")
    if callback_name in {"cmd_paperdesk", "cmd_paper_open", "cmd_paper_closed", "cmd_paper_toggle"}:
        return _back_button("cmd_paperdesk", "<< Paper")
    if callback_name in {"cmd_journal", "cmd_journal_open", "cmd_journal_closed", "cmd_journal_actual", "cmd_journal_paper"}:
        return _back_button("cmd_journal", "<< Journal")
    if callback_name in {"cmd_fno", "cmd_fno_best", "cmd_fno_tomorrow", "cmd_fno_positions", "cmd_fno_autolog", "cmd_fno_run", "cmd_fno_global"}:
        return _back_button("cmd_fno", "<< F&O")
    if callback_name in {"cmd_thesis", "cmd_thesisstock"}:
        return _back_button("cmd_thesis", "<< Thesis")
    if callback_name in {"cmd_controls", "cmd_summary", "cmd_start", "cmd_stop", "cmd_cashtrade"}:
        return _back_button("cmd_controls", "<< Controls")
    return _back_button()


def _send_menu(token=None, chat_id=None):
    """Send the main control panel with buttons."""
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    text = (
        "<b>Groww AI Bot — Phone Dashboard</b>\n"
        f"{now}\n\n"
        "Tap a section below to open the Telegram version of your dashboard."
    )
    _send(text, token=token, chat_id=chat_id, reply_markup=_main_menu_keyboard())


def _set_my_commands(token):
    commands = [
        {"command": "menu", "description": "Open the Telegram dashboard"},
        {"command": "dashboard", "description": "Top-level system overview"},
        {"command": "watchlist", "description": "Watchlist summary"},
        {"command": "watch", "description": "Drill into one stock: /watch TCS"},
        {"command": "market", "description": "Market sentiment and macro view"},
        {"command": "worldnews", "description": "World news feed"},
        {"command": "news", "description": "Stock news: /news RELIANCE"},
        {"command": "research", "description": "Research leaderboard or report"},
        {"command": "paper", "description": "Paper trading desk"},
        {"command": "journal", "description": "Trade journal summary"},
        {"command": "fno", "description": "F&O desk"},
        {"command": "thesis", "description": "Thesis summary or detail"},
        {"command": "runanalysis", "description": "Run watchlist AI analysis now"},
        {"command": "runresearch", "description": "Run all research now"},
        {"command": "autotrade", "description": "Run one cash auto-trade cycle"},
        {"command": "summary", "description": "Send the daily summary now"},
        {"command": "status", "description": "System status"},
        {"command": "holdings", "description": "Current holdings"},
        {"command": "pnl", "description": "P&L dashboard"},
        {"command": "papermode", "description": "Toggle paper mode"},
    ]
    try:
        url = _BASE_URL.format(token=token, method="setMyCommands")
        requests.post(url, json={"commands": commands}, timeout=10)
    except Exception as e:
        logger.debug("Telegram command registration failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

def _cmd_help(**kw):
    return (
        "<b>Groww AI Bot — Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Dashboard:\n"
        "/menu, /dashboard, /status, /balance, /pnl\n\n"
        "Watchlist + Research:\n"
        "/watchlist, /watch TCS, /analysis, /research, /research INFY\n\n"
        "Market + News:\n"
        "/market, /worldnews, /news RELIANCE, /rawmat\n\n"
        "Trading + Journal:\n"
        "/holdings, /trades, /positions, /journal, /paper, /autotrade, /stops\n\n"
        "Thesis + F&O:\n"
        "/thesis, /thesis HDFCBANK, /fno\n\n"
        "Controls:\n"
        "/runanalysis, /runresearch, /summary, /cashtrade, /papermode, /stop, /start"
    )


def _cmd_status(**kw):
    from db_manager import get_config
    import scheduler

    paper = get_config("paper_trading", "false").lower() == "true"
    cash_at = get_config("cash_auto_trade_enabled", "false").lower() == "true"
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")

    task_count = len(scheduler._tasks)
    paused = "PAUSED" if _scheduler_paused else "RUNNING"

    # Check if market is open
    try:
        from fno_trader import _is_market_open
        market_open, market_reason = _is_market_open()
        market_str = "OPEN" if market_open else f"CLOSED ({market_reason})"
    except Exception:
        market_str = "Unknown"

    cash_at_str = "ON" if cash_at else "OFF"
    cash_at_icon = "🟢" if cash_at else "🔴"

    return (
        f"⚙️ <b>System Status</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"  🕐  {now}\n"
        f"  📊  Market: {market_str}\n"
        f"  🤖  Scheduler: {paused} ({task_count} tasks)\n"
        f"  📝  Paper Mode: {'ON' if paper else 'OFF'}\n"
        f"  {cash_at_icon}  Cash Auto-Trade: {cash_at_str}\n"
        f"  ✅  Server: Running\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def _cmd_balance(**kw):
    try:
        import bot
        margin = bot.get_margin()
        if not isinstance(margin, dict):
            return f"<b>Balance</b>\n{margin}"

        cash = margin.get("clear_cash", 0)
        used = margin.get("net_margin_used", 0)
        charges = margin.get("brokerage_and_charges", 0)
        collateral = margin.get("collateral_available", 0)

        eq = margin.get("equity_margin_details", {})
        fno = margin.get("fno_margin_details", {})

        eq_avail = eq.get("cnc_balance_available", 0) + eq.get("mis_balance_available", 0)
        fno_avail = fno.get("option_buy_balance_available", 0) + fno.get("future_balance_available", 0)

        lines = [
            "💰 <b>Account Balance</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"  💵  Cash Available    ₹{cash:,.2f}",
            f"  🔒  Margin Used       ₹{used:,.2f}",
            f"  📊  Charges Today     ₹{charges:,.2f}",
            "",
            "┌─ <b>Equity</b>",
            f"│  CNC Available      ₹{eq.get('cnc_balance_available', 0):,.2f}",
            f"│  MIS Available      ₹{eq.get('mis_balance_available', 0):,.2f}",
            f"│  Equity Used        ₹{eq.get('net_equity_margin_used', 0):,.2f}",
            "│",
            "├─ <b>F&O</b>",
            f"│  Option Buy         ₹{fno.get('option_buy_balance_available', 0):,.2f}",
            f"│  Futures            ₹{fno.get('future_balance_available', 0):,.2f}",
            f"│  F&O Used           ₹{fno.get('net_fno_margin_used', 0):,.2f}",
            "│",
            "└─ <b>Collateral</b>",
            f"   Available          ₹{collateral:,.2f}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Balance fetch failed: {e}"


def _cmd_holdings(**kw):
    try:
        import bot
        holdings_resp = bot.get_holdings()
        if isinstance(holdings_resp, dict):
            holdings = holdings_resp.get("holdings", holdings_resp.get("data", []))
        elif isinstance(holdings_resp, list):
            holdings = holdings_resp
        else:
            holdings = []

        if not holdings:
            return "📭 No holdings found."

        total_invested = 0
        total_current = 0
        stock_lines = []

        for h in holdings:
            sym = h.get("trading_symbol", h.get("tradingSymbol", h.get("symbol", "?")))
            sym = sym.split("-")[0] if sym else "?"
            qty = float(h.get("quantity", h.get("totalQuantity", h.get("net_quantity", 0))))
            avg = float(h.get("average_price", h.get("averagePrice", h.get("avg_price", 0))))

            if qty <= 0:
                continue

            # Fetch live price from Groww
            try:
                ltp = bot.fetch_live_price(sym)
            except Exception:
                ltp = 0

            invested = avg * qty
            current = ltp * qty
            pnl = current - invested
            pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0

            total_invested += invested
            total_current += current

            # Visual indicator
            if pnl >= 0:
                icon = "🟢"
                pnl_str = f"+₹{pnl:,.0f}"
                pct_str = f"+{pnl_pct:.1f}%"
            else:
                icon = "🔴"
                pnl_str = f"-₹{abs(pnl):,.0f}"
                pct_str = f"{pnl_pct:.1f}%"

            stock_lines.append({
                "text": (
                    f"{icon} <b>{sym}</b>\n"
                    f"     {int(qty)} × ₹{avg:,.2f} → ₹{ltp:,.2f}\n"
                    f"     {pnl_str}  ({pct_str})"
                ),
                "pnl": pnl,
            })

        # Sort by P&L (worst first to highlight losses)
        stock_lines.sort(key=lambda x: x["pnl"])

        total_pnl = total_current - total_invested
        total_pct = ((total_current - total_invested) / total_invested * 100) if total_invested else 0
        portfolio_icon = "📈" if total_pnl >= 0 else "📉"

        lines = [
            f"📊 <b>My Holdings</b>  ({len(stock_lines)} stocks)",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        for s in stock_lines:
            lines.append(s["text"])
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"  Invested     ₹{total_invested:,.0f}")
        lines.append(f"  Current      ₹{total_current:,.0f}")
        if total_pnl >= 0:
            lines.append(f"  {portfolio_icon} <b>P&L         +₹{total_pnl:,.0f}  (+{total_pct:.2f}%)</b>")
        else:
            lines.append(f"  {portfolio_icon} <b>P&L         -₹{abs(total_pnl):,.0f}  ({total_pct:.2f}%)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Holdings fetch failed: {e}"


def _cmd_trades(**kw):
    try:
        import bot
        trades = bot.get_trade_log()
        if not trades:
            return "📭 No trades recorded yet."

        recent = trades[-10:]
        lines = [
            "📋 <b>Recent Trades</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        for t in reversed(recent):
            sym = t.get("symbol", "?")
            side = t.get("side", "?")
            qty = t.get("quantity", 0)
            price = t.get("price", 0)
            paper = " 📝" if t.get("paper") else ""
            ts = t.get("time", "")[:16]
            icon = "🟢 BUY " if side == "BUY" else "🔴 SELL"
            lines.append(f"{icon} <b>{sym}</b>{paper}")
            lines.append(f"     {qty} × ₹{price:,.2f}  •  {ts}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Trade log failed: {e}"


def _cmd_pnl(**kw):
    try:
        import bot
        holdings_resp = bot.get_holdings()
        if isinstance(holdings_resp, dict):
            holdings = holdings_resp.get("holdings", holdings_resp.get("data", []))
        elif isinstance(holdings_resp, list):
            holdings = holdings_resp
        else:
            holdings = []

        if not holdings:
            return "📭 No holdings — P&L unavailable."

        total_invested = 0
        total_current = 0
        winners = []
        losers = []

        for h in holdings:
            sym = h.get("trading_symbol", h.get("tradingSymbol", h.get("symbol", "?")))
            sym = sym.split("-")[0] if sym else "?"
            qty = float(h.get("quantity", h.get("totalQuantity", h.get("net_quantity", 0))))
            avg = float(h.get("average_price", h.get("averagePrice", h.get("avg_price", 0))))

            if qty <= 0:
                continue

            try:
                ltp = bot.fetch_live_price(sym)
            except Exception:
                ltp = 0

            invested = avg * qty
            current = ltp * qty
            pnl = current - invested
            pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0

            total_invested += invested
            total_current += current

            entry = {"sym": sym, "pnl": pnl, "pct": pnl_pct, "invested": invested}
            if pnl >= 0:
                winners.append(entry)
            else:
                losers.append(entry)

        winners.sort(key=lambda x: x["pnl"], reverse=True)
        losers.sort(key=lambda x: x["pnl"])

        total_pnl = total_current - total_invested
        total_pct = (total_pnl / total_invested * 100) if total_invested else 0
        portfolio_icon = "📈" if total_pnl >= 0 else "📉"

        lines = [
            f"{portfolio_icon} <b>P&L Dashboard</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"  💼  Invested       ₹{total_invested:,.0f}",
            f"  💰  Current        ₹{total_current:,.0f}",
        ]
        if total_pnl >= 0:
            lines.append(f"  ✅  <b>Net P&L       +₹{total_pnl:,.0f}  (+{total_pct:.2f}%)</b>")
        else:
            lines.append(f"  ❌  <b>Net P&L       -₹{abs(total_pnl):,.0f}  ({total_pct:.2f}%)</b>")

        if winners:
            lines.append("")
            lines.append("🏆 <b>Winners</b>")
            for w in winners[:5]:
                lines.append(f"  🟢 {w['sym']}  +₹{w['pnl']:,.0f}  (+{w['pct']:.1f}%)")

        if losers:
            lines.append("")
            lines.append("📉 <b>Losers</b>")
            for l in losers[:5]:
                lines.append(f"  🔴 {l['sym']}  -₹{abs(l['pnl']):,.0f}  ({l['pct']:.1f}%)")

        # Paper trade P&L
        try:
            paper_pnl = _get_paper_pnl()
            if paper_pnl:
                lines.append("")
                lines.append("━━━━━━━━━━━━━━━━━━━━")
                lines.append("📝 <b>Paper Trading (Today)</b>")
                lines.append(f"  Trades: {paper_pnl['count']}  •  P&L: ₹{paper_pnl['net_pnl']:+,.2f}")
                lines.append(f"  Charges: ₹{paper_pnl['charges']:.2f}")
        except Exception:
            pass

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ P&L fetch failed: {e}"


def _get_paper_pnl():
    """Calculate paper trading P&L from DB."""
    try:
        from db_manager import get_db, PaperTrade
        db = get_db()
        today = datetime.now(IST).date()
        with db.Session() as session:
            trades = [
                trade for trade in session.query(PaperTrade).all()
                if trade.created_at and trade.created_at.date() >= today
            ]
            if not trades:
                return None
            buys = {}
            net_pnl = 0
            total_charges = 0
            for t in trades:
                total_charges += t.charges or 0
                if t.side == "BUY":
                    buys[t.symbol] = buys.get(t.symbol, [])
                    buys[t.symbol].append(t)
                elif t.side == "SELL" and t.symbol in buys and buys[t.symbol]:
                    buy = buys[t.symbol].pop(0)
                    net_pnl += (t.price - buy.price) * t.quantity - (t.charges or 0) - (buy.charges or 0)
            return {"count": len(trades), "net_pnl": net_pnl, "charges": total_charges}
    except Exception:
        return None


def _cmd_positions(**kw):
    try:
        import bot
        positions_resp = bot.get_positions()
        if isinstance(positions_resp, dict):
            pos_list = positions_resp.get("positions", positions_resp.get("data", []))
        elif isinstance(positions_resp, list):
            pos_list = positions_resp
        else:
            pos_list = []

        if not pos_list:
            return "📭 No open positions."

        lines = [
            "📊 <b>Open Positions</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        total_pnl = 0
        shown = 0
        for p in pos_list:
            sym = p.get("trading_symbol", p.get("tradingSymbol", "?"))
            qty = float(p.get("quantity", p.get("netQuantity", p.get("net_quantity", 0))))
            if qty == 0:
                continue
            avg = float(p.get("average_price", p.get("averagePrice", 0)))

            try:
                ltp = bot.fetch_live_price(sym)
            except Exception:
                ltp = float(p.get("ltp", p.get("lastTradedPrice", p.get("last_price", 0))))

            pnl = (ltp - avg) * qty
            pnl_pct = ((ltp - avg) / avg * 100) if avg > 0 else 0
            total_pnl += pnl

            icon = "🟢" if pnl >= 0 else "🔴"
            side = "LONG" if qty > 0 else "SHORT"

            if pnl >= 0:
                pnl_str = f"+₹{pnl:,.0f}  (+{pnl_pct:.1f}%)"
            else:
                pnl_str = f"-₹{abs(pnl):,.0f}  ({pnl_pct:.1f}%)"

            lines.append(f"{icon} <b>{sym}</b>  •  {side}")
            lines.append(f"     {int(abs(qty))} × ₹{avg:,.2f} → ₹{ltp:,.2f}")
            lines.append(f"     {pnl_str}")
            lines.append("")
            shown += 1

        if shown == 0:
            return "📭 No open positions with non-zero quantity."

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        if total_pnl >= 0:
            lines.append(f"  ✅ <b>Total P&L  +₹{total_pnl:,.0f}</b>")
        else:
            lines.append(f"  ❌ <b>Total P&L  -₹{abs(total_pnl):,.0f}</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Positions fetch failed: {e}"


def _cmd_analysis(**kw):
    try:
        import auto_analyzer
        data = auto_analyzer.get_latest_analysis()
        if not data or not data.get("predictions"):
            return "📭 No recent analysis available. The auto-analyzer may not have run yet."

        preds = data["predictions"]
        summary = data.get("summary", {})
        ts = data.get("timestamp", "")[:16]

        total = summary.get("total_stocks", len(preds))
        buys_n = summary.get("buy_count", 0)
        sells_n = summary.get("sell_count", 0)
        holds_n = summary.get("hold_count", 0)

        lines = [
            "🤖 <b>AI Analysis</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"  📊  {total} stocks scanned",
            f"  🟢  {buys_n} BUY   🔴 {sells_n} SELL   ⚪ {holds_n} HOLD",
        ]
        if ts:
            lines.append(f"  🕐  Last run: {ts}")
        lines.append("")

        # Show top BUY signals
        buys = sorted([p for p in preds if p.get("signal") == "BUY"],
                       key=lambda x: x.get("confidence", 0), reverse=True)
        sells = sorted([p for p in preds if p.get("signal") == "SELL"],
                        key=lambda x: x.get("confidence", 0), reverse=True)

        if buys:
            lines.append("🟢 <b>Top BUY Signals</b>")
            for p in buys[:5]:
                conf = p.get("confidence", 0)
                score = p.get("combined_score", 0)
                reason = (p.get("reason", "") or "")[:70]
                bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
                lines.append(f"  <b>{p['symbol']}</b>  {bar} {conf*100:.0f}%")
                if reason:
                    lines.append(f"     {reason}")
            lines.append("")

        if sells:
            lines.append("🔴 <b>Top SELL Signals</b>")
            for p in sells[:5]:
                conf = p.get("confidence", 0)
                reason = (p.get("reason", "") or "")[:70]
                bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
                lines.append(f"  <b>{p['symbol']}</b>  {bar} {conf*100:.0f}%")
                if reason:
                    lines.append(f"     {reason}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Analysis fetch failed: {e}"


def _cmd_signals(**kw):
    try:
        from research_engine import get_cached_leaderboard
        lb = get_cached_leaderboard() or []
        if not lb:
            return "No research signals available yet."

        lines = ["<b>Top Research Signals</b>\n━━━━━━━━━━━━━━━━━━"]
        for s in lb[:10]:
            sym = s.get("symbol", "?")
            v = s.get("verdict", {})
            stance = v.get("stance", "HOLD") if isinstance(v, dict) else str(v)
            alpha = s.get("alpha_score", 0)
            conv = s.get("conviction", 0)
            lines.append(f"<b>{sym}</b>: {stance} | Alpha: {alpha} | Conviction: {conv}%")
        return "\n".join(lines)
    except Exception as e:
        return f"Signals fetch failed: {e}"


def _cmd_rawmat(**kw):
    try:
        import commodity_tracker as ct
        import yfinance as yf

        # Build commodity map with direct/inverse relationships
        seen = {}
        for stock, info in ct.get_commodity_map_dict().items():
            key = info["ticker"]
            if key not in seen:
                seen[key] = {
                    "commodity": info["commodity"],
                    "ticker": info["ticker"],
                    "stocks_direct": [],
                    "stocks_inverse": [],
                }
            if info.get("relationship") == "direct":
                seen[key]["stocks_direct"].append(stock)
            else:
                seen[key]["stocks_inverse"].append(stock)

        lines = [
            "🗺 <b>Raw Materials Heatmap</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        commodities_data = []
        for ticker, meta in seen.items():
            name = meta["commodity"]
            try:
                data = yf.download(ticker, period="3mo", interval="1wk", progress=False)
                if not data.empty and len(data) >= 4:
                    close_col = data["Close"]
                    if hasattr(close_col, "columns"):
                        close_col = close_col.iloc[:, 0]
                    current = float(close_col.iloc[-1])
                    price_1m = float(close_col.iloc[-4]) if len(close_col) >= 4 else current
                    price_3m = float(close_col.iloc[0])
                    chg_1m = ((current - price_1m) / price_1m * 100) if price_1m > 0 else 0
                    chg_3m = ((current - price_3m) / price_3m * 100) if price_3m > 0 else 0
                    is_inr = "INR" in ticker
                    commodities_data.append({
                        "name": name,
                        "price": current,
                        "is_inr": is_inr,
                        "chg_1m": chg_1m,
                        "chg_3m": chg_3m,
                        "direct": meta["stocks_direct"],
                        "inverse": meta["stocks_inverse"],
                    })
            except Exception:
                commodities_data.append({
                    "name": name, "price": 0, "is_inr": False,
                    "chg_1m": 0, "chg_3m": 0,
                    "direct": meta["stocks_direct"],
                    "inverse": meta["stocks_inverse"],
                })

        # Sort by absolute 1M change (most volatile first)
        commodities_data.sort(key=lambda x: abs(x["chg_1m"]), reverse=True)

        for c in commodities_data:
            # Heatmap-style colored block
            chg = c["chg_1m"]
            if chg > 5:
                heat = "🟩🟩🟩"
                trend_label = "🔥 SURGING"
            elif chg > 2:
                heat = "🟩🟩⬜"
                trend_label = "📈 RISING"
            elif chg > 0:
                heat = "🟩⬜⬜"
                trend_label = "↗️ SLIGHT UP"
            elif chg > -2:
                heat = "🟥⬜⬜"
                trend_label = "↘️ SLIGHT DIP"
            elif chg > -5:
                heat = "🟥🟥⬜"
                trend_label = "📉 FALLING"
            else:
                heat = "🟥🟥🟥"
                trend_label = "💀 CRASHING"

            currency = "₹" if c["is_inr"] else "$"
            price_str = f"{currency}{c['price']:,.1f}" if c["price"] else "N/A"

            lines.append(f"{heat}  <b>{c['name']}</b>  {price_str}")
            lines.append(f"       1M: {c['chg_1m']:+.1f}%  •  3M: {c['chg_3m']:+.1f}%  •  {trend_label}")

            # Affected stocks with ↑/↓ indicators
            stock_parts = []
            for s in c["direct"][:3]:
                stock_parts.append(f"↑{s}")
            for s in c["inverse"][:3]:
                stock_parts.append(f"↓{s}")
            if stock_parts:
                lines.append(f"       {' · '.join(stock_parts)}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("↑ = benefits when rising  •  ↓ = hurts when rising")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Raw materials fetch failed: {e}"


def _cmd_stop(**kw):
    global _scheduler_paused
    _scheduler_paused = True
    logger.warning("SCHEDULER PAUSED via Telegram command")
    return (
        "<b>ALL TASKS PAUSED</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "The scheduler will not execute any tasks until you send /start.\n"
        "No new trades, analysis, or data collection will run.\n"
        "Existing open positions are NOT affected.\n\n"
        "Send /start to resume."
    )


def _cmd_start(**kw):
    global _scheduler_paused
    _scheduler_paused = False
    logger.info("SCHEDULER RESUMED via Telegram command")
    return (
        "<b>ALL TASKS RESUMED</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Scheduler is running again. All tasks will execute on their normal intervals."
    )


def _cmd_paper(**kw):
    try:
        from db_manager import get_config, set_config
        current = get_config("paper_trading", "false").lower() == "true"
        new_val = "false" if current else "true"
        set_config("paper_trading", new_val, description="Paper trading mode (true/false)")
        state = "ON" if new_val == "true" else "OFF"
        return (
            f"<b>Paper Trading: {state}</b>\n"
            f"{'All future trades will be simulated (no real money).' if state == 'ON' else 'CAUTION: Real trades will be placed with real money!'}"
        )
    except Exception as e:
        return f"Toggle failed: {e}"


def _cmd_cashtrade(**kw):
    try:
        from db_manager import get_config, set_config
        current = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        new_val = "false" if current else "true"
        set_config("cash_auto_trade_enabled", new_val, description="Cash equity auto-trade (true/false)")
        paper = get_config("paper_trading", "false").lower() == "true"

        if new_val == "true":
            mode = "Paper Mode" if paper else "REAL TRADES"
            icon = "\u2705" if paper else "\u26a0\ufe0f"
            warning = "" if paper else "\n\n\u26a0\ufe0f <b>WARNING:</b> Paper mode is OFF. Real orders will be placed!"
            return (
                f"{icon} <b>Cash Auto-Trade: ENABLED</b>\n"
                f"Mode: {mode}\n"
                f"The bot will auto-trade your watchlist stocks every 5 min during market hours."
                f"{warning}"
            )
        else:
            return (
                "\u274c <b>Cash Auto-Trade: DISABLED</b>\n"
                "The bot will NOT auto-trade your portfolio stocks.\n"
                "F\u0026O auto-trade is controlled separately."
            )
    except Exception as e:
        return f"\u274c Toggle failed: {e}"


def _cmd_dashboard(**kw):
    try:
        from db_manager import get_config
        import bot
        import auto_analyzer
        import news_sentiment
        from paper_trader import PaperTradeTracker

        holdings_resp = bot.get_holdings()
        holdings = holdings_resp.get("holdings", holdings_resp.get("data", [])) if isinstance(holdings_resp, dict) else (holdings_resp or [])
        positions_resp = bot.get_positions()
        positions = positions_resp.get("positions", positions_resp.get("data", [])) if isinstance(positions_resp, dict) else (positions_resp or [])

        market = news_sentiment.get_market_sentiment().to_dict()
        latest = auto_analyzer.get_latest_analysis() or {}
        summary = latest.get("summary", {})

        paper_mode = get_config("paper_trading", "false").lower() == "true"
        cash_auto = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        tracker = PaperTradeTracker()
        paper_open = len(tracker.get_open_positions())
        watchlist_count = len(_get_watchlist_symbols())

        lines = [
            "📱 <b>Dashboard</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🕐 {datetime.now(IST).strftime('%d %b %Y, %H:%M IST')}",
            f"📚 Watchlist: {watchlist_count} stocks",
            f"💼 Holdings: {len(holdings)}",
            f"📊 Positions: {len([p for p in positions if float(p.get('quantity', p.get('net_quantity', 0) or 0)) != 0])}",
            f"📝 Paper Mode: {'ON' if paper_mode else 'OFF'} | Open Paper Trades: {paper_open}",
            f"🤖 Cash Auto-Trade: {'ON' if cash_auto else 'OFF'}",
            "",
            f"🌐 Market: {_escape(market.get('signal', 'NEUTRAL'))} | Score {market.get('avg_score', 0):+.2f}",
        ]

        if summary:
            lines.extend([
                "",
                "<b>Latest AI Run</b>",
                f"Scanned: {summary.get('total_stocks', 0)} | BUY {summary.get('buy_count', 0)} | SELL {summary.get('sell_count', 0)} | HOLD {summary.get('hold_count', 0)}",
            ])
            if latest.get("timestamp"):
                lines.append(f"Updated: {_time_ago(latest.get('timestamp'))}")
            if summary.get("best_buy"):
                lines.append(f"Top pick: <b>{_escape(summary.get('best_buy'))}</b> ({summary.get('best_buy_confidence', 0) * 100:.0f}% confidence)")

        return _response("\n".join(lines), reply_markup=_main_menu_keyboard())
    except Exception as e:
        return _response(f"❌ Dashboard load failed: {_escape(e)}", reply_markup=_main_menu_keyboard())


def _cmd_market(args="", **kw):
    try:
        import news_sentiment
        from world_news_collector import get_news_stats

        market = news_sentiment.get_market_sentiment().to_dict()
        stats = get_news_stats() or {}
        lines = [
            "🌐 <b>Market Desk</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Signal: <b>{_escape(market.get('signal', 'NEUTRAL'))}</b>",
            f"Score: {market.get('avg_score', 0):+.2f} | Confidence: {market.get('confidence', 0) * 100:.0f}%",
            f"Articles: {market.get('total_articles', 0)} | Bullish {market.get('bullish_count', 0)} | Bearish {market.get('bearish_count', 0)}",
        ]

        if stats:
            lines.extend([
                "",
                "<b>World News Feed</b>",
                f"24h: {stats.get('last_24h', 0)} | 7d: {stats.get('last_7d', 0)} | Total: {stats.get('total_articles', 0)}",
            ])

        articles = market.get("articles", [])[:3]
        if articles:
            lines.append("")
            lines.append("<b>Top Headlines</b>")
            for article in articles:
                mood = article.get("sentiment", "NEUTRAL")
                icon = "🟢" if mood == "BULLISH" else "🔴" if mood == "BEARISH" else "⚪"
                lines.append(f"{icon} {_escape(_truncate(article.get('title', ''), 95))}")

        return _response("\n".join(lines), reply_markup=_market_keyboard())
    except Exception as e:
        return _response(f"❌ Market desk failed: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_worldnews(args="", **kw):
    try:
        from world_news_collector import get_recent_news, get_news_stats

        category = (args or "").strip().lower() or None
        stats = get_news_stats() or {}
        articles = get_recent_news(category=category, limit=8, days=7)
        title = category.title() if category else "All"

        lines = [
            f"📰 <b>World News — {title}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"24h: {stats.get('last_24h', 0)} | 7d: {stats.get('last_7d', 0)}",
        ]

        categories = stats.get("categories", {})
        if categories:
            parts = []
            for key in ("market", "macro", "sector", "geopolitical", "global"):
                if key in categories:
                    parts.append(f"{key}:{categories[key]}")
            if parts:
                lines.append("Categories: " + " | ".join(parts))

        if not articles:
            lines.append("")
            lines.append("No recent world news found.")
            return _response("\n".join(lines), reply_markup=_market_keyboard())

        lines.append("")
        for article in articles:
            mood = article.get("sentiment", "NEUTRAL")
            icon = "🟢" if mood == "BULLISH" else "🔴" if mood == "BEARISH" else "⚪"
            category_label = article.get("category") or "general"
            lines.append(f"{icon} <b>{_escape(category_label.title())}</b> • {_escape(_time_ago(article.get('published_at')))}")
            lines.append(_escape(_truncate(article.get("title", ""), 105)))
            if article.get("source"):
                lines.append(f"Source: {_escape(article.get('source'))}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_market_keyboard())
    except Exception as e:
        return _response(f"❌ World news failed: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_worldcollect(**kw):
    try:
        from world_news_collector import collect_world_news

        threading.Thread(target=collect_world_news, daemon=True, name="telegram-world-news").start()
        return _response(
            "✅ <b>World news collection started</b>\nA background refresh is now pulling fresh macro and market headlines.",
            reply_markup=_market_keyboard(),
        )
    except Exception as e:
        return _response(f"❌ World news refresh failed: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_newsstock(args="", **kw):
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /news SYMBOL or tap a stock button from Markets.", reply_markup=_market_keyboard())

    try:
        import news_sentiment

        data = news_sentiment.get_news_sentiment(symbol).to_dict()
        lines = [
            f"🗞 <b>{_escape(symbol)} News</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Signal: <b>{_escape(data.get('signal', 'NEUTRAL'))}</b>",
            f"Score: {data.get('avg_score', 0):+.2f} | Confidence: {data.get('confidence', 0) * 100:.0f}%",
            f"Articles: {data.get('total_articles', 0)} | Bullish {data.get('bullish_count', 0)} | Bearish {data.get('bearish_count', 0)}",
        ]

        articles = data.get("articles", [])[:6]
        if articles:
            lines.append("")
            for article in articles:
                mood = article.get("sentiment", "NEUTRAL")
                icon = "🟢" if mood == "BULLISH" else "🔴" if mood == "BEARISH" else "⚪"
                lines.append(f"{icon} {_escape(_truncate(article.get('title', ''), 102))}")
                lines.append(f"{_escape(article.get('source', 'Unknown'))} • {_escape(_time_ago(article.get('published')))}")
                lines.append("")

        reply_markup = _menu_keyboard([
            [{"text": "Watch View", "callback_data": f"cmd_watchstock:{symbol}"}, {"text": "Research", "callback_data": f"cmd_researchstock:{symbol}"}],
            [{"text": "Market Desk", "callback_data": "cmd_market"}],
        ], back_target="cmd_market", back_text="<< Markets")

        return _response("\n".join(lines).strip(), reply_markup=reply_markup)
    except Exception as e:
        return _response(f"❌ News lookup failed for {_escape(symbol)}: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_watchlist(args="", **kw):
    rows = _get_watchlist_rows()
    try:
        import auto_analyzer
        latest = auto_analyzer.get_latest_analysis() or {}
        summary = latest.get("summary", {})
    except Exception:
        latest = {}
        summary = {}

    lines = [
        "📚 <b>Watchlist</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Tracked stocks: {len(rows)}",
    ]

    if rows:
        dated = [r for r in rows if r.get("earliest_date") and r.get("latest_date")]
        if dated:
            lines.append(f"Coverage: {dated[0]['earliest_date']} -> {dated[-1]['latest_date']}")

    if summary:
        lines.extend([
            "",
            "<b>Latest AI Snapshot</b>",
            f"BUY {summary.get('buy_count', 0)} | SELL {summary.get('sell_count', 0)} | HOLD {summary.get('hold_count', 0)}",
        ])
        if latest.get("timestamp"):
            lines.append(f"Updated: {_time_ago(latest.get('timestamp'))}")
        if summary.get("best_buy"):
            lines.append(f"Top pick: <b>{_escape(summary.get('best_buy'))}</b> ({summary.get('best_buy_confidence', 0) * 100:.0f}% confidence)")

    if rows:
        lines.append("")
        lines.append("<b>Tracked Symbols</b>")
        preview = rows[:12]
        for row in preview:
            symbol = row.get("symbol", "?")
            candles = row.get("price_candles")
            if candles:
                lines.append(f"• <b>{_escape(symbol)}</b> — {candles} candles")
            else:
                lines.append(f"• <b>{_escape(symbol)}</b>")
        if len(rows) > len(preview):
            lines.append(f"… and {len(rows) - len(preview)} more")

    return _response("\n".join(lines), reply_markup=_watchlist_keyboard())


def _cmd_watchscan(**kw):
    try:
        import bot

        preds = bot.scan_watchlist()
        buys = sorted([p for p in preds if p.get("signal") == "BUY"], key=lambda p: p.get("confidence", 0), reverse=True)
        sells = sorted([p for p in preds if p.get("signal") == "SELL"], key=lambda p: p.get("confidence", 0), reverse=True)

        lines = [
            "🔎 <b>Live Watchlist Scan</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Scanned: {len(preds)} stocks",
            f"BUY {len(buys)} | SELL {len(sells)} | HOLD {len(preds) - len(buys) - len(sells)}",
            "",
        ]

        if buys:
            lines.append("<b>Top BUYs</b>")
            for pred in buys[:5]:
                price = pred.get("indicators", {}).get("price", 0)
                lines.append(f"🟢 <b>{_escape(pred.get('symbol', '?'))}</b> • {pred.get('confidence', 0) * 100:.0f}% • {_fmt_money(price)}")
                lines.append(_escape(_truncate(pred.get("reason", ""), 90)))
            lines.append("")

        if sells:
            lines.append("<b>Top SELLs</b>")
            for pred in sells[:5]:
                price = pred.get("indicators", {}).get("price", 0)
                lines.append(f"🔴 <b>{_escape(pred.get('symbol', '?'))}</b> • {pred.get('confidence', 0) * 100:.0f}% • {_fmt_money(price)}")
                lines.append(_escape(_truncate(pred.get("reason", ""), 90)))

        return _response("\n".join(lines), reply_markup=_watchlist_keyboard())
    except Exception as e:
        return _response(f"❌ Watchlist scan failed: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_watchstock(args="", **kw):
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /watch SYMBOL or tap a stock button from Watchlist.", reply_markup=_watchlist_keyboard())

    try:
        import bot
        from db_manager import get_watchlist_note

        pred = bot.get_prediction(symbol)
        news = pred.get("sources", {}).get("news") or {}
        ml = pred.get("sources", {}).get("ml") or {}
        ctx = pred.get("sources", {}).get("market_context") or {}
        indicators = pred.get("indicators", {}) or {}
        trend = pred.get("long_term_trend") or {}
        price = indicators.get("price") or bot.fetch_live_price(symbol)
        note = get_watchlist_note(symbol)

        lines = [
            f"🎯 <b>{_escape(symbol)}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Signal: <b>{_escape(pred.get('signal', 'HOLD'))}</b> | Confidence: {pred.get('confidence', 0) * 100:.0f}%",
            f"Price: {_fmt_money(price)} | Combined score: {pred.get('combined_score', 0):+.3f}",
            f"ML: {_escape(ml.get('signal', '—'))} | News: {_escape(news.get('signal', 'NEUTRAL'))} | Market: {_escape(ctx.get('market_signal', 'NEUTRAL'))}",
        ]

        if indicators.get("rsi") is not None or indicators.get("trend"):
            lines.append(f"RSI: {indicators.get('rsi', '—')} | Trend: {_escape(indicators.get('trend', '—'))}")

        if trend:
            lines.append(
                f"5Y Trend: {_fmt_pct(trend.get('trend_pct', 0), signed=True)} | Support: {_fmt_money(trend.get('support'))} | Resistance: {_fmt_money(trend.get('resistance'))}"
            )

        costs = pred.get("costs") or {}
        if costs:
            lines.append(f"Breakeven: {_fmt_money(costs.get('breakeven_price'))} | Charges: {_fmt_money(costs.get('total_charges'))}")

        reason = pred.get("reason")
        if reason:
            lines.extend(["", "<b>Why It Looks Like This</b>", _escape(_truncate(reason, 260))])

        if note:
            lines.extend(["", "<b>Your Watchlist Note</b>", _escape(_truncate(note, 220))])

        reply_markup = _menu_keyboard([
            [{"text": "News", "callback_data": f"cmd_newsstock:{symbol}"}, {"text": "Research", "callback_data": f"cmd_researchstock:{symbol}"}],
            [{"text": "Refresh", "callback_data": f"cmd_watchstock:{symbol}"}],
        ], back_target="cmd_watchlist", back_text="<< Watchlist")

        return _response("\n".join(lines), reply_markup=reply_markup)
    except Exception as e:
        return _response(f"❌ Watch view failed for {_escape(symbol)}: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_research(args="", **kw):
    symbol = _extract_symbol(args)
    if symbol:
        return _cmd_researchstock(symbol)

    try:
        from research_engine import get_cached_leaderboard

        lb = get_cached_leaderboard() or []
        lines = [
            "🔬 <b>Research Desk</b>",
            "━━━━━━━━━━━━━━━━━━━━",
        ]

        if not lb:
            lines.append("No cached leaderboard yet. Run the research batch to generate rankings.")
            return _response("\n".join(lines), reply_markup=_research_keyboard())

        lines.append(f"Ranked stocks: {len(lb)}")
        lines.append("")
        for row in lb[:10]:
            verdict = row.get("verdict", {}) if isinstance(row.get("verdict"), dict) else {}
            stance = verdict.get("stance", "HOLD")
            lines.append(
                f"<b>{_escape(row.get('symbol', '?'))}</b> • {stance} • Alpha {row.get('alpha_score', 0):.1f} • Conviction {row.get('conviction', 0):.0f}%"
            )

        return _response("\n".join(lines), reply_markup=_research_keyboard())
    except Exception as e:
        return _response(f"❌ Research desk failed: {_escape(e)}", reply_markup=_research_keyboard())


def _cmd_researchstock(args="", **kw):
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /research SYMBOL or tap a research stock button.", reply_markup=_research_keyboard())

    try:
        from research_engine import generate_research, get_cached_report

        report = get_cached_report(symbol) or generate_research(symbol)
        verdict = report.get("verdict", {}) or {}
        dims = report.get("dimensions", {}) or {}
        lines = [
            f"🔬 <b>{_escape(symbol)} Research</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Verdict: <b>{_escape(verdict.get('stance_label', verdict.get('stance', 'HOLD')))}</b>",
            f"Alpha: {report.get('alpha_score', 0):.1f} | Conviction: {report.get('conviction', 0):.1f}%",
            f"Confidence: {_escape(verdict.get('confidence', 'UNKNOWN'))} | Risk: {_escape(verdict.get('risk_label', 'UNKNOWN'))}",
            f"Regime: {_escape(report.get('regime', 'UNKNOWN'))}",
        ]

        score_parts = []
        for key, label in (("technical", "Tech"), ("fundamental", "Fund"), ("institutional", "Inst"), ("sentiment", "Sent"), ("risk", "Risk")):
            score = dims.get(key, {}).get("score")
            if score is not None:
                score_parts.append(f"{label} {float(score):.0f}")
        if score_parts:
            lines.append("Scores: " + " | ".join(score_parts))

        catalysts = report.get("catalysts") or []
        if catalysts:
            lines.append("")
            lines.append("<b>Top Catalysts</b>")
            for catalyst in catalysts[:4]:
                if isinstance(catalyst, dict):
                    text = catalyst.get("catalyst") or catalyst.get("title") or catalyst.get("name") or str(catalyst)
                else:
                    text = catalyst
                lines.append(f"• {_escape(_truncate(text, 110))}")

        long_term = report.get("long_term") or {}
        if long_term.get("trend_pct") is not None:
            lines.append("")
            lines.append(
                f"Long-term trend: {_fmt_pct(long_term.get('trend_pct', 0), signed=True)} | From low {_fmt_pct(long_term.get('distance_from_low_pct', 0), signed=False)}"
            )

        reply_markup = _menu_keyboard([
            [{"text": "Watch View", "callback_data": f"cmd_watchstock:{symbol}"}, {"text": "News", "callback_data": f"cmd_newsstock:{symbol}"}],
            [{"text": "Refresh Research", "callback_data": f"cmd_researchstock:{symbol}"}],
        ], back_target="cmd_research", back_text="<< Research")

        return _response("\n".join(lines), reply_markup=reply_markup)
    except Exception as e:
        return _response(f"❌ Research lookup failed for {_escape(symbol)}: {_escape(e)}", reply_markup=_research_keyboard())


def _cmd_runanalysis(**kw):
    try:
        import auto_analyzer

        threading.Thread(target=auto_analyzer.auto_analyze_watchlist, daemon=True, name="telegram-auto-analysis").start()
        return _response(
            "✅ <b>Watchlist auto-analysis started</b>\nA fresh scan is running in the background.",
            reply_markup=_watchlist_keyboard(),
        )
    except Exception as e:
        return _response(f"❌ Auto-analysis start failed: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_runresearch(**kw):
    try:
        from research_engine import generate_research_all

        threading.Thread(target=generate_research_all, daemon=True, name="telegram-research-batch").start()
        return _response(
            "✅ <b>Research batch started</b>\nThe full research engine is now refreshing all tracked stocks.",
            reply_markup=_research_keyboard(),
        )
    except Exception as e:
        return _response(f"❌ Research batch failed to start: {_escape(e)}", reply_markup=_research_keyboard())


def _cmd_trading(**kw):
    try:
        from db_manager import get_config
        import bot

        holdings_resp = bot.get_holdings()
        holdings = holdings_resp.get("holdings", holdings_resp.get("data", [])) if isinstance(holdings_resp, dict) else (holdings_resp or [])
        positions_resp = bot.get_positions()
        positions = positions_resp.get("positions", positions_resp.get("data", [])) if isinstance(positions_resp, dict) else (positions_resp or [])
        trade_log = bot.get_trade_log() or []
        paper_mode = get_config("paper_trading", "false").lower() == "true"
        cash_auto = get_config("cash_auto_trade_enabled", "false").lower() == "true"

        lines = [
            "⚙️ <b>Trading Desk</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Paper mode: {'ON' if paper_mode else 'OFF'} | Cash auto-trade: {'ON' if cash_auto else 'OFF'}",
            f"Holdings: {len(holdings)} | Positions: {len([p for p in positions if float(p.get('quantity', p.get('net_quantity', 0) or 0)) != 0])}",
            f"Logged trades: {len(trade_log)}",
        ]

        if trade_log:
            latest = trade_log[-1]
            lines.extend([
                "",
                "<b>Most Recent Trade</b>",
                f"{_escape(latest.get('side', '?'))} <b>{_escape(latest.get('symbol', '?'))}</b> • {latest.get('quantity', 0)} x {_fmt_money(latest.get('price'))}",
                f"When: {_escape(_time_ago(latest.get('time')))}",
            ])

        return _response("\n".join(lines), reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"❌ Trading desk failed: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_autotrade(**kw):
    try:
        from db_manager import get_config
        import bot

        paper_mode = get_config("paper_trading", "false").lower() == "true"
        result = bot.auto_trade()

        if result.get("error"):
            return _response(
                f"⚠️ <b>Auto-trade did not run</b>\n{_escape(result.get('message', result['error']))}",
                reply_markup=_trading_keyboard(),
            )

        actions = result.get("actions", [])
        buys = [a for a in actions if a.get("action") == "BUY"]
        sells = [a for a in actions if a.get("action") == "SELL"]
        skips = [a for a in actions if a.get("action") == "SKIP"]
        errors = [a for a in actions if a.get("action") == "ERROR"]

        lines = [
            "▶️ <b>Cash Auto-Trade Cycle Complete</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Mode: {'Paper' if paper_mode else 'Live'}",
            f"BUY {len(buys)} | SELL {len(sells)} | SKIP {len(skips)} | ERRORS {len(errors)}",
        ]

        for entry in (buys + sells)[:6]:
            trade = entry.get("trade", {})
            lines.append(f"• {entry.get('action')} <b>{_escape(entry.get('symbol', '?'))}</b> @ {_fmt_money(trade.get('price'))}")

        if errors:
            lines.append("")
            lines.append("<b>Issues</b>")
            for entry in errors[:3]:
                lines.append(f"• {_escape(entry.get('symbol', '?'))}: {_escape(_truncate(entry.get('reason', ''), 80))}")

        return _response("\n".join(lines), reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"❌ Auto-trade run failed: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_stops(**kw):
    try:
        import bot

        result = bot.monitor_and_update_trailing_stops()
        lines = [
            "🛡 <b>Trailing Stop Monitor</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Monitored: {result.get('monitored', 0)} | Closed: {result.get('closed', 0)} | Updated: {result.get('updated', 0)}",
        ]
        events = result.get("events", []) or []
        if events:
            lines.append("")
            lines.append("<b>Recent Events</b>")
            for event in events[:8]:
                lines.append(f"• {_escape(event.get('action', '?'))} <b>{_escape(event.get('symbol', '?'))}</b> @ {_fmt_money(event.get('price'))}")
        return _response("\n".join(lines), reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"❌ Trailing stop monitor failed: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_paperdesk(**kw):
    try:
        from db_manager import get_config
        from paper_trader import PaperTradeTracker

        tracker = PaperTradeTracker()
        trades = tracker.trades
        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        closed_trades = [t for t in trades if t.get("status") != "OPEN" and t.get("net_pnl") is not None]
        realized = sum(float(t.get("net_pnl") or 0) for t in closed_trades)
        wins = [t for t in closed_trades if float(t.get("net_pnl") or 0) > 0]
        capital = sum(float(t.get("entry_price") or 0) * float(t.get("quantity") or 0) for t in open_trades)
        paper_mode = get_config("paper_trading", "false").lower() == "true"

        lines = [
            "📝 <b>Paper Trading Desk</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Mode: {'ON' if paper_mode else 'OFF'}",
            f"Open trades: {len(open_trades)} | Closed trades: {len(closed_trades)}",
            f"Capital deployed: {_fmt_money(capital, decimals=0)}",
            f"Realized net P&L: {_fmt_money(realized, signed=True)}",
        ]

        if closed_trades:
            win_rate = (len(wins) / len(closed_trades)) * 100
            lines.append(f"Win rate: {win_rate:.1f}%")

        if open_trades:
            lines.append("")
            lines.append("<b>Live Open Trades</b>")
            for trade in open_trades[:5]:
                lines.append(
                    f"• {_escape(trade.get('signal', '?'))} <b>{_escape(trade.get('symbol', '?'))}</b> • {trade.get('quantity', 0)} x {_fmt_money(trade.get('entry_price'))}"
                )

        return _response("\n".join(lines), reply_markup=_paper_keyboard())
    except Exception as e:
        return _response(f"❌ Paper desk failed: {_escape(e)}", reply_markup=_paper_keyboard())


def _cmd_paper_open(**kw):
    try:
        import bot
        from paper_trader import PaperTradeTracker

        tracker = PaperTradeTracker()
        open_trades = tracker.get_open_positions()
        if not open_trades:
            return _response("📭 No open paper trades.", reply_markup=_paper_keyboard())

        lines = ["📝 <b>Open Paper Trades</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for trade in open_trades[:8]:
            ltp = None
            try:
                ltp = bot.fetch_live_price(trade.get("symbol"))
            except Exception:
                pass

            entry = float(trade.get("entry_price") or 0)
            qty = float(trade.get("quantity") or 0)
            pnl = None
            if ltp:
                if trade.get("signal") == "BUY":
                    pnl = (ltp - entry) * qty
                else:
                    pnl = (entry - ltp) * qty

            lines.append(f"<b>{_escape(trade.get('symbol', '?'))}</b> • {_escape(trade.get('signal', '?'))}")
            lines.append(f"Entry: {_fmt_money(entry)} | Qty: {int(qty)}")
            if ltp:
                lines.append(f"LTP: {_fmt_money(ltp)} | Live P&L: {_fmt_money(pnl, signed=True)}")
            if trade.get("trailing_stop"):
                lines.append(f"Trailing stop: {_fmt_money(trade.get('trailing_stop'))}")
            if trade.get("cost_coverage_price"):
                covered = "Yes" if trade.get("has_covered_costs") else "No"
                lines.append(f"Cost cover: {_fmt_money(trade.get('cost_coverage_price'))} | Covered: {covered}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_paper_keyboard())
    except Exception as e:
        return _response(f"❌ Open paper trades failed: {_escape(e)}", reply_markup=_paper_keyboard())


def _cmd_paper_closed(**kw):
    try:
        from paper_trader import PaperTradeTracker

        tracker = PaperTradeTracker()
        closed_trades = [t for t in tracker.trades if t.get("status") != "OPEN" and t.get("exit_price") is not None]
        closed_trades.sort(key=lambda t: t.get("exit_time") or "", reverse=True)
        if not closed_trades:
            return _response("📭 No closed paper trades yet.", reply_markup=_paper_keyboard())

        lines = ["📘 <b>Closed Paper Trades</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for trade in closed_trades[:10]:
            lines.append(
                f"<b>{_escape(trade.get('symbol', '?'))}</b> • {_escape(trade.get('signal', '?'))} • {_fmt_money(trade.get('net_pnl'), signed=True)}"
            )
            lines.append(
                f"Entry {_fmt_money(trade.get('entry_price'))} -> Exit {_fmt_money(trade.get('exit_price'))} | {_escape(trade.get('exit_reason', 'closed'))}"
            )
            lines.append(f"Closed: {_escape(_time_ago(trade.get('exit_time')))}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_paper_keyboard())
    except Exception as e:
        return _response(f"❌ Closed paper trades failed: {_escape(e)}", reply_markup=_paper_keyboard())


def _cmd_journal(**kw):
    try:
        import trade_journal

        stats = trade_journal.get_journal_stats()
        lines = [
            "📓 <b>Trade Journal</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Total trades: {stats.get('total_trades', 0)} | Open: {stats.get('open_trades', 0)} | Closed: {stats.get('closed_trades', 0)}",
            f"Win rate: {stats.get('win_rate', 0):.1f}% | Total P&L: {_fmt_money(stats.get('total_pnl', 0), signed=True)}",
            f"Avg P&L: {_fmt_money(stats.get('avg_pnl', 0), signed=True)} | Charges: {_fmt_money(stats.get('total_charges', 0))}",
            f"Prediction accuracy: {stats.get('prediction_accuracy', 0):.1f}%",
            f"ML {stats.get('ml_accuracy', 0):.1f}% | News {stats.get('news_accuracy', 0):.1f}% | Market {stats.get('market_accuracy', 0):.1f}%",
        ]

        best = stats.get("best_trade")
        worst = stats.get("worst_trade")
        if best or worst:
            lines.append("")
        if best:
            lines.append(f"Best: <b>{_escape(best.get('symbol', '?'))}</b> {_fmt_money(best.get('pnl'), signed=True)}")
        if worst:
            lines.append(f"Worst: <b>{_escape(worst.get('symbol', '?'))}</b> {_fmt_money(worst.get('pnl'), signed=True)}")

        return _response("\n".join(lines), reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"❌ Journal summary failed: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_journal_open(**kw):
    try:
        import trade_journal

        entries = trade_journal.get_open_reports()
        if not entries:
            return _response("📭 No open journal trades.", reply_markup=_journal_keyboard())

        lines = ["📂 <b>Open Journal Trades</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for entry in entries[:10]:
            pre = entry.get("pre_trade", {}) or {}
            lines.append(
                f"<b>{_escape(entry.get('symbol', '?'))}</b> • {_escape(entry.get('side', '?'))} • {entry.get('quantity', 0)} x {_fmt_money(entry.get('entry_price'))}"
            )
            lines.append(
                f"Signal: {_escape(pre.get('signal', '—'))} | Confidence: {float(pre.get('confidence') or 0) * 100:.0f}% | Trigger: {_escape(entry.get('trigger', 'auto'))}"
            )
            if pre.get("target_price") or pre.get("stop_loss_price"):
                lines.append(f"Target {_fmt_money(pre.get('target_price'))} | Stop {_fmt_money(pre.get('stop_loss_price'))}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"❌ Open journal view failed: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_journal_closed(**kw):
    try:
        import trade_journal

        entries = trade_journal.get_closed_reports()
        if not entries:
            return _response("📭 No closed journal trades yet.", reply_markup=_journal_keyboard())

        lines = ["✅ <b>Closed Journal Trades</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for entry in entries[:10]:
            post = entry.get("post_trade", {}) or {}
            lines.append(
                f"<b>{_escape(entry.get('symbol', '?'))}</b> • {_escape(entry.get('status', '?'))} • {_fmt_money(post.get('net_pnl'), signed=True)}"
            )
            lines.append(
                f"Entry {_fmt_money(entry.get('entry_price'))} -> Exit {_fmt_money(entry.get('exit_price'))} | {_escape(post.get('exit_reason', 'closed'))}"
            )
            lines.append(f"Duration: {post.get('duration_minutes', '—')} min")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"❌ Closed journal view failed: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_journal_actual(**kw):
    try:
        import trade_journal

        entries = [e for e in trade_journal.get_all_reports() if not e.get("is_paper", False)]
        if not entries:
            return _response("📭 No actual journal trades found.", reply_markup=_journal_keyboard())

        lines = ["💼 <b>Actual Trades</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for entry in entries[:10]:
            status = entry.get("status", "OPEN")
            pnl = (entry.get("post_trade") or {}).get("net_pnl")
            pnl_text = _fmt_money(pnl, signed=True) if pnl is not None else "Open"
            lines.append(f"<b>{_escape(entry.get('symbol', '?'))}</b> • {_escape(status)} • {pnl_text}")
        return _response("\n".join(lines), reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"❌ Actual trades view failed: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_journal_paper(**kw):
    try:
        import trade_journal

        entries = [e for e in trade_journal.get_all_reports() if e.get("is_paper", False)]
        if not entries:
            return _response("📭 No paper journal trades found.", reply_markup=_journal_keyboard())

        lines = ["📝 <b>Paper Journal Trades</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for entry in entries[:10]:
            status = entry.get("status", "OPEN")
            pnl = (entry.get("post_trade") or {}).get("net_pnl")
            pnl_text = _fmt_money(pnl, signed=True) if pnl is not None else "Open"
            lines.append(f"<b>{_escape(entry.get('symbol', '?'))}</b> • {_escape(status)} • {pnl_text}")
        return _response("\n".join(lines), reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"❌ Paper trades view failed: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_fno(**kw):
    try:
        import fno_trader

        dash = fno_trader.get_fno_dashboard()
        capital = dash.get("capital", {}) or {}
        positions = (dash.get("positions") or {}).get("positions", []) if isinstance(dash.get("positions"), dict) else []
        config = fno_trader.get_auto_trade_config() or {}

        lines = [
            "📈 <b>F&O Desk</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Capital: {_fmt_money(capital.get('total', 0), decimals=0)} | Used: {_fmt_money(capital.get('used', 0), decimals=0)} | Available: {_fmt_money(capital.get('available', 0), decimals=0)}",
            f"Open positions: {len(positions)} | Logged trades: {dash.get('trade_count', 0)}",
            f"Min confidence: {float(config.get('min_confidence', 0)) * 100:.0f}% | Max positions: {config.get('max_positions', '—')}",
        ]

        instruments = dash.get("instruments", [])[:5]
        if instruments:
            lines.append("")
            lines.append("<b>Live Underlyings</b>")
            for instrument in instruments:
                lines.append(
                    f"• <b>{_escape(instrument.get('key', '?'))}</b> {_fmt_money(instrument.get('ltp'))} ({_fmt_pct(instrument.get('change_pct', 0))})"
                )

        return _response("\n".join(lines), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ F&O desk failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_fno_best(**kw):
    try:
        import fno_trader

        preferred = fno_trader.get_auto_trade_config().get("preferred_instruments") or ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        results = []
        for instrument in preferred[:5]:
            try:
                data = fno_trader.analyze_fno_opportunity(instrument)
                data["instrument"] = instrument
                results.append(data)
            except Exception:
                continue

        if not results:
            return _response("No F&O opportunities available right now.", reply_markup=_fno_keyboard())

        results.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        best = results[0]
        lines = [
            "🎯 <b>Best F&O Setup</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Top: <b>{_escape(best.get('instrument', '?'))}</b> • {_escape(best.get('direction', 'NEUTRAL'))} • {best.get('confidence', 0) * 100:.0f}%",
        ]

        if best.get("strength"):
            lines.append(f"Strength: {_escape(best.get('strength'))}")
        if best.get("global_score") is not None:
            lines.append(f"Global score: {best.get('global_score', 0):+.2f}")

        lines.append("")
        lines.append("<b>Preferred Instruments</b>")
        for row in results[:5]:
            lines.append(f"• {_escape(row.get('instrument', '?'))}: {_escape(row.get('direction', 'NEUTRAL'))} ({row.get('confidence', 0) * 100:.0f}%)")

        return _response("\n".join(lines), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ F&O opportunity scan failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_fno_tomorrow(**kw):
    try:
        import fno_backtester
        import fno_trader

        preferred = fno_trader.get_auto_trade_config().get("preferred_instruments") or ["NIFTY", "BANKNIFTY", "FINNIFTY"]
        lines = ["🧭 <b>Tomorrow Signals</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for instrument in preferred[:6]:
            signal = fno_backtester.get_xgb_signal(instrument)
            lines.append(
                f"<b>{_escape(instrument)}</b> • {_escape(signal.get('direction', 'NEUTRAL'))} • {signal.get('confidence', 0) * 100:.0f}%"
            )
            if signal.get("xgb_available"):
                delta = (signal.get("xgb_probs") or {}).get("delta")
                if delta is not None:
                    lines.append(f"XGBoost delta: {delta:+.3f}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ Tomorrow signals failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_fno_positions(**kw):
    try:
        import fno_trader

        result = fno_trader.get_fno_positions()
        positions = result.get("positions", []) if isinstance(result, dict) else []
        if not positions:
            return _response("📭 No open F&O positions.", reply_markup=_fno_keyboard())

        lines = ["📊 <b>F&O Positions</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for pos in positions[:10]:
            symbol = pos.get("trading_symbol") or pos.get("tradingSymbol") or pos.get("symbol") or "?"
            qty = pos.get("quantity") or pos.get("netQuantity") or pos.get("net_quantity") or 0
            avg = pos.get("average_price") or pos.get("averagePrice") or 0
            ltp = pos.get("ltp") or pos.get("lastTradedPrice") or pos.get("last_price") or 0
            lines.append(f"<b>{_escape(symbol)}</b> • Qty {qty}")
            lines.append(f"Avg {_fmt_money(avg)} -> LTP {_fmt_money(ltp)}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ F&O positions failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_fno_autolog(**kw):
    try:
        import fno_trader

        log = fno_trader.get_auto_trade_log().get("log", [])
        if not log:
            return _response("📭 No F&O auto-trade runs yet.", reply_markup=_fno_keyboard())

        lines = ["📜 <b>F&O Auto-Trade Log</b>", "━━━━━━━━━━━━━━━━━━━━", ""]
        for entry in reversed(log[-8:]):
            inst = entry.get("instrument") or entry.get("trading_symbol") or "—"
            direction = entry.get("direction") or entry.get("analysis", {}).get("direction") or "—"
            conf = entry.get("confidence") or (entry.get("analysis") or {}).get("confidence") or 0
            lines.append(f"<b>{_escape(inst)}</b> • {_escape(direction)} • {float(conf) * 100:.0f}%")
            if entry.get("result") and isinstance(entry.get("result"), dict) and entry["result"].get("status"):
                lines.append(f"Order status: {_escape(entry['result'].get('status'))}")
            elif entry.get("skipped_reason"):
                lines.append(f"Skipped: {_escape(_truncate(entry.get('skipped_reason'), 90))}")
            lines.append("")

        return _response("\n".join(lines).strip(), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ F&O auto log failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_fno_run(**kw):
    try:
        import fno_trader

        result = fno_trader.auto_trade_fno()
        lines = ["▶️ <b>F&O Auto-Trade Run</b>", "━━━━━━━━━━━━━━━━━━━━"]
        if result.get("error"):
            lines.append(_escape(result.get("error")))
        else:
            lines.append(f"Instrument: {_escape(result.get('instrument', '—'))}")
            if result.get("direction"):
                lines.append(f"Direction: {_escape(result.get('direction'))}")
            if result.get("confidence") is not None:
                lines.append(f"Confidence: {float(result.get('confidence') or 0) * 100:.0f}%")
            if result.get("result") and isinstance(result.get("result"), dict):
                order_result = result["result"]
                if order_result.get("order_id"):
                    lines.append(f"Order: {_escape(order_result.get('order_id'))}")
                if order_result.get("status"):
                    lines.append(f"Status: {_escape(order_result.get('status'))}")
            if result.get("skipped_reason"):
                lines.append(f"Skipped: {_escape(result.get('skipped_reason'))}")

        return _response("\n".join(lines), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ F&O auto-trade failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_fno_global(**kw):
    try:
        import fno_trader

        indices = fno_trader.fetch_global_indices() or {}
        sentiment = fno_trader.get_global_sentiment() or {}

        lines = [
            "🌍 <b>Global Indices</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Global score: {sentiment.get('score', 0):+.2f} | Signal: {_escape(sentiment.get('signal', 'UNKNOWN'))}",
            "",
        ]
        for name, data in list(indices.items())[:10]:
            price = data.get("price") if isinstance(data, dict) else None
            change = data.get("change_pct", 0) if isinstance(data, dict) else 0
            lines.append(f"<b>{_escape(name)}</b> • {_fmt_money(price) if price is not None else '—'} • {_fmt_pct(change)}")

        return _response("\n".join(lines), reply_markup=_fno_keyboard())
    except Exception as e:
        return _response(f"❌ Global indices failed: {_escape(e)}", reply_markup=_fno_keyboard())


def _cmd_thesis(args="", **kw):
    symbol = _extract_symbol(args)
    if symbol:
        return _cmd_thesisstock(symbol)

    try:
        from thesis_manager import get_manager

        theses = get_manager().get_all_theses()
        if not theses:
            return _response("📭 No personal theses saved yet.", reply_markup=_thesis_keyboard())

        lines = ["🎯 <b>My Thesis</b>", "━━━━━━━━━━━━━━━━━━━━", f"Saved theses: {len(theses)}", ""]
        for thesis in theses[:10]:
            lines.append(
                f"<b>{_escape(thesis.symbol)}</b> • Target {_fmt_money(thesis.target_price)} • Entry {_fmt_money(thesis.entry_price) if thesis.entry_price else '—'}"
            )
        return _response("\n".join(lines), reply_markup=_thesis_keyboard())
    except Exception as e:
        return _response(f"❌ Thesis desk failed: {_escape(e)}", reply_markup=_thesis_keyboard())


def _cmd_thesisstock(args="", **kw):
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /thesis SYMBOL or tap a thesis stock button.", reply_markup=_thesis_keyboard())

    try:
        import bot
        from thesis_manager import get_manager

        manager = get_manager()
        thesis = manager.get_thesis(symbol)
        if not thesis:
            return _response(f"📭 No thesis saved for {_escape(symbol)}.", reply_markup=_thesis_keyboard())

        current_price = bot.fetch_live_price(symbol)
        projection = manager.get_projection(symbol, current_price, thesis.quantity) if current_price else None

        lines = [
            f"🎯 <b>{_escape(symbol)} Thesis</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Target: {_fmt_money(thesis.target_price)} | Current: {_fmt_money(current_price)}",
            f"Entry: {_fmt_money(thesis.entry_price) if thesis.entry_price else '—'} | Qty: {thesis.quantity or '—'}",
        ]

        if projection:
            lines.extend([
                f"Distance to target: {_fmt_money(projection.get('distance_to_target_rs'))} ({_fmt_pct(projection.get('distance_to_target_pct'), signed=True)})",
                f"Net profit at target: {_fmt_money(projection.get('net_profit_at_target'), signed=True)}",
                f"Value at target: {_fmt_money(projection.get('value_at_target'))}",
            ])

        if thesis.comments:
            lines.extend(["", "<b>Your Thesis</b>", _escape(_truncate(thesis.comments, 320))])

        return _response("\n".join(lines), reply_markup=_thesis_keyboard())
    except Exception as e:
        return _response(f"❌ Thesis detail failed for {_escape(symbol)}: {_escape(e)}", reply_markup=_thesis_keyboard())


def _cmd_controls(**kw):
    try:
        from db_manager import get_config

        paper_mode = get_config("paper_trading", "false").lower() == "true"
        cash_auto = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        lines = [
            "🕹 <b>Controls</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Scheduler: {'PAUSED' if _scheduler_paused else 'RUNNING'}",
            f"Paper mode: {'ON' if paper_mode else 'OFF'}",
            f"Cash auto-trade: {'ON' if cash_auto else 'OFF'}",
            "",
            "Use the buttons below for runtime controls.",
        ]
        return _response("\n".join(lines), reply_markup=_controls_keyboard())
    except Exception as e:
        return _response(f"❌ Controls view failed: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_summary(**kw):
    try:
        from daily_summary import send_daily_summary

        result = send_daily_summary()
        if result.get("sent"):
            return _response("✅ <b>Daily summary sent</b>\nThe Telegram daily summary has been pushed to this chat.", reply_markup=_controls_keyboard())
        reason = result.get("reason") or result.get("error") or "unknown reason"
        return _response(f"⚠️ <b>Daily summary not sent</b>\n{_escape(reason)}", reply_markup=_controls_keyboard())
    except Exception as e:
        return _response(f"❌ Daily summary failed: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_toggle_paper(**kw):
    try:
        from db_manager import get_config, set_config
        current = get_config("paper_trading", "false").lower() == "true"
        new_val = "false" if current else "true"
        set_config("paper_trading", new_val, description="Paper trading mode (true/false)")
        state = "ON" if new_val == "true" else "OFF"
        return _response(
            f"<b>Paper Trading: {state}</b>\n"
            f"{'All future trades will be simulated.' if state == 'ON' else 'CAUTION: Real trades will be placed with real money.'}",
            reply_markup=_paper_keyboard(),
        )
    except Exception as e:
        return _response(f"Toggle failed: {_escape(e)}", reply_markup=_paper_keyboard())


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

_COMMANDS = {
    "/help": _cmd_help,
    "/start": _cmd_start,
    "/dashboard": _cmd_dashboard,
    "/market": _cmd_market,
    "/worldnews": _cmd_worldnews,
    "/watchlist": _cmd_watchlist,
    "/watch": _cmd_watchstock,
    "/research": _cmd_research,
    "/paper": _cmd_paperdesk,
    "/papermode": _cmd_toggle_paper,
    "/journal": _cmd_journal,
    "/fno": _cmd_fno,
    "/thesis": _cmd_thesis,
    "/news": _cmd_newsstock,
    "/trading": _cmd_trading,
    "/controls": _cmd_controls,
    "/runanalysis": _cmd_runanalysis,
    "/runresearch": _cmd_runresearch,
    "/autotrade": _cmd_autotrade,
    "/stops": _cmd_stops,
    "/summary": _cmd_summary,
    "/status": _cmd_status,
    "/balance": _cmd_balance,
    "/holdings": _cmd_holdings,
    "/trades": _cmd_trades,
    "/pnl": _cmd_pnl,
    "/positions": _cmd_positions,
    "/analysis": _cmd_analysis,
    "/signals": _cmd_signals,
    "/rawmat": _cmd_rawmat,
    "/stop": _cmd_stop,
    "/cashtrade": _cmd_cashtrade,
    "/menu": None,  # handled specially
}

# Map callback_data -> same handler functions
_CALLBACKS = {
    "cmd_help": _cmd_help,
    "cmd_dashboard": _cmd_dashboard,
    "cmd_market": _cmd_market,
    "cmd_worldnews": _cmd_worldnews,
    "cmd_worldcollect": _cmd_worldcollect,
    "cmd_watchlist": _cmd_watchlist,
    "cmd_watchscan": _cmd_watchscan,
    "cmd_watchstock": _cmd_watchstock,
    "cmd_research": _cmd_research,
    "cmd_researchstock": _cmd_researchstock,
    "cmd_runanalysis": _cmd_runanalysis,
    "cmd_runresearch": _cmd_runresearch,
    "cmd_trading": _cmd_trading,
    "cmd_autotrade": _cmd_autotrade,
    "cmd_stops": _cmd_stops,
    "cmd_paperdesk": _cmd_paperdesk,
    "cmd_paper_open": _cmd_paper_open,
    "cmd_paper_closed": _cmd_paper_closed,
    "cmd_paper_toggle": _cmd_toggle_paper,
    "cmd_journal": _cmd_journal,
    "cmd_journal_open": _cmd_journal_open,
    "cmd_journal_closed": _cmd_journal_closed,
    "cmd_journal_actual": _cmd_journal_actual,
    "cmd_journal_paper": _cmd_journal_paper,
    "cmd_fno": _cmd_fno,
    "cmd_fno_best": _cmd_fno_best,
    "cmd_fno_tomorrow": _cmd_fno_tomorrow,
    "cmd_fno_positions": _cmd_fno_positions,
    "cmd_fno_autolog": _cmd_fno_autolog,
    "cmd_fno_run": _cmd_fno_run,
    "cmd_fno_global": _cmd_fno_global,
    "cmd_thesis": _cmd_thesis,
    "cmd_thesisstock": _cmd_thesisstock,
    "cmd_newsstock": _cmd_newsstock,
    "cmd_controls": _cmd_controls,
    "cmd_summary": _cmd_summary,
    "cmd_status": _cmd_status,
    "cmd_balance": _cmd_balance,
    "cmd_holdings": _cmd_holdings,
    "cmd_trades": _cmd_trades,
    "cmd_pnl": _cmd_pnl,
    "cmd_positions": _cmd_positions,
    "cmd_analysis": _cmd_analysis,
    "cmd_signals": _cmd_signals,
    "cmd_rawmat": _cmd_rawmat,
    "cmd_stop": _cmd_stop,
    "cmd_start": _cmd_start,
    "cmd_cashtrade": _cmd_cashtrade,
    "cmd_paper": _cmd_toggle_paper,
    "cmd_menu": None,  # handled specially
}


def _handle_callback(callback_query, token, chat_id):
    """Process an inline keyboard button press."""
    cb_id = callback_query.get("id", "")
    data = callback_query.get("data", "")
    sender_chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))

    if sender_chat_id != str(chat_id):
        _answer_callback(cb_id, token, "Unauthorized")
        return

    # Answer immediately to remove loading spinner
    _answer_callback(cb_id, token)

    if data == "cmd_menu":
        _send_menu(token=token, chat_id=chat_id)
        return

    callback_name, callback_args = (data.split(":", 1) + [""])[:2] if ":" in data else (data, "")
    handler = _CALLBACKS.get(callback_name)
    if handler:
        try:
            response = handler(token=token, chat_id=chat_id, args=callback_args)
            _dispatch_response(response, token, chat_id, default_reply_markup=_default_reply_markup(callback_name))
        except Exception as e:
            _send(f"Command failed: {e}", token=token, chat_id=chat_id, reply_markup=_default_reply_markup(callback_name))


def _handle_message(message, token, chat_id):
    """Process an incoming Telegram message."""
    text = (message.get("text") or "").strip()
    expected_chat_id = str(chat_id)

    # Security: only respond to the configured chat_id
    msg_chat_id = str(message.get("chat", {}).get("id", ""))
    if msg_chat_id != expected_chat_id:
        logger.warning("Ignoring message from unauthorized chat: %s", msg_chat_id)
        return

    # Extract command (handle /command@botname format)
    cmd = text.split()[0].split("@")[0].lower() if text else ""
    args = text.split(None, 1)[1].strip() if text and len(text.split(None, 1)) > 1 else ""

    # /menu or /start -> show button panel
    if cmd in ("/menu", "/start"):
        if cmd == "/start":
            # /start from Telegram means "bot opened" — show menu, also resume scheduler
            _cmd_start(token=token, chat_id=chat_id)
        _send_menu(token=token, chat_id=chat_id)
        return

    handler = _COMMANDS.get(cmd)
    if handler:
        try:
            response = handler(token=token, chat_id=chat_id, args=args)
            _dispatch_response(response, token, chat_id, default_reply_markup=_back_button())
        except Exception as e:
            _send(f"Command failed: {e}", token=token, chat_id=chat_id, reply_markup=_back_button())
    elif text.startswith("/"):
        _send(f"Unknown command: {cmd}\nSend /menu for the control panel.", token=token, chat_id=chat_id, reply_markup=_main_menu_keyboard())
    else:
        # Any non-command text -> show menu
        _send_menu(token=token, chat_id=chat_id)


# ═══════════════════════════════════════════════════════════════════════════════
# POLLING LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def _polling_loop():
    """Long-poll Telegram for incoming commands."""
    global _last_update_id

    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.warning("Telegram commander: no token/chat_id configured, polling disabled")
        return

    logger.info("Telegram commander started — listening for commands")

    # Send startup message with main menu buttons
    _send(
        "<b>Groww AI Bot Online</b>\n"
        f"Time: {datetime.now(IST).strftime('%d %b %Y, %H:%M IST')}\n\n"
        "Tap a button to get started:",
        token=token, chat_id=chat_id,
        reply_markup=_main_menu_keyboard(),
    )

    consecutive_errors = 0
    while True:
        try:
            url = _BASE_URL.format(token=token, method="getUpdates")
            params = {"offset": _last_update_id + 1, "timeout": 30, "allowed_updates": ["message", "callback_query"]}
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()

            if not data.get("ok"):
                logger.warning("Telegram polling error: %s", data.get("description"))
                time.sleep(5)
                consecutive_errors += 1
                if consecutive_errors > 10:
                    logger.error("Too many polling errors, stopping")
                    break
                continue

            consecutive_errors = 0
            for update in data.get("result", []):
                _last_update_id = update["update_id"]
                message = update.get("message")
                callback_query = update.get("callback_query")
                if callback_query:
                    _handle_callback(callback_query, token, chat_id)
                elif message:
                    _handle_message(message, token, chat_id)

        except requests.exceptions.Timeout:
            continue  # Normal for long polling
        except Exception as e:
            logger.warning("Telegram polling error: %s", e)
            time.sleep(5)
            consecutive_errors += 1
            if consecutive_errors > 20:
                logger.error("Telegram polling stopped after too many errors")
                break


def start_commander():
    """Start the Telegram command listener in a background thread."""
    global _polling_thread

    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.info("Telegram commander skipped (not configured)")
        return None

    if _polling_thread and _polling_thread.is_alive():
        logger.info("Telegram commander already running in this process")
        return _polling_thread

    _set_my_commands(token)

    _polling_thread = threading.Thread(target=_polling_loop, daemon=True, name="telegram-commander")
    _polling_thread.start()
    logger.info("Telegram commander running in background")
    return _polling_thread
