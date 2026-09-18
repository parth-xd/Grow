"""
Telegram Commander — interactive bot that listens for commands via polling.

Every screen is a monospace block of label/value rows (see _block/_title),
built from the same reconciled data the dashboard reads, so a number here
never disagrees with the one on screen. Anything that touches money
(Pause, Paper Mode, Cash Auto) asks to confirm first.

Tree (main menu -> branch -> leaves):
  Dashboard  where you stand / what is running / what is next
  Trading    Overview, Positions, Holdings, Run Auto-Trade, Move Stops
  Market     Signal, Headlines (world news), Raw Materials
  Watchlist  Signals (with a button per stock -> call / news / research),
             Research leaderboard, Run AI Now, Run Research
  Journal    Recent, Stats
  Controls   Pause / Resume, Paper Mode, Cash Auto, Send Daily Summary

Slash commands mirror the tree (/dashboard, /trading, /positions, /holdings,
/market, /worldnews [category], /rawmat, /watchlist, /analysis, /watch SYM,
/news SYM, /research [SYM], /journal, /controls, /autotrade, /stops,
/runanalysis, /runresearch, /summary, /papermode, /cashtrade, /stop, /start,
/help, /menu).
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


def _time_ago(iso_text, naive_tz=IST):
    """Age of a timestamp. Naive stamps carry no zone, and producers differ:
    auto_analyzer/journal write IST wall-clock, research_engine writes
    utcnow() - so the caller passes `naive_tz` for its source. RSS dates
    (RFC-2822) are accepted too."""
    if not iso_text:
        return "—"
    try:
        when = None
        if isinstance(iso_text, datetime):
            when = iso_text
        else:
            cleaned = str(iso_text).replace("Z", "+00:00")
            try:
                when = datetime.fromisoformat(cleaned)
            except ValueError:
                from email.utils import parsedate_to_datetime
                when = parsedate_to_datetime(str(iso_text))
        if when.tzinfo is None:
            when = when.replace(tzinfo=naive_tz)
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
    return {"inline_keyboard": [
        [{"text": "Dashboard", "callback_data": "cmd_dashboard"}, {"text": "Trading", "callback_data": "cmd_trading"}],
        [{"text": "Market", "callback_data": "cmd_market"}, {"text": "Watchlist", "callback_data": "cmd_watchlist"}],
        [{"text": "Journal", "callback_data": "cmd_journal"}, {"text": "Controls", "callback_data": "cmd_controls"}],
    ]}


def _back_button(back_target="cmd_menu", label="<< Main Menu"):
    return {"inline_keyboard": [[{"text": label, "callback_data": back_target}]]}


def _trading_keyboard():
    return _menu_keyboard([
        [{"text": "Overview", "callback_data": "cmd_trading"}, {"text": "Positions", "callback_data": "cmd_positions"}],
        [{"text": "Holdings", "callback_data": "cmd_holdings"}],
        [{"text": "Run Auto-Trade", "callback_data": "cmd_autotrade"}, {"text": "Move Stops", "callback_data": "cmd_stops"}],
    ])


def _market_keyboard():
    return _menu_keyboard([
        [{"text": "Signal", "callback_data": "cmd_market"}, {"text": "Headlines", "callback_data": "cmd_worldnews"}],
        [{"text": "Raw Materials", "callback_data": "cmd_rawmat"}],
    ])


def _watchlist_keyboard(symbols=()):
    """Watchlist hub keyboard. `symbols` (optional) become one-tap drill-down
    buttons above the fixed rows, so a BUY on the Signals screen is reachable
    without typing /watch SYMBOL."""
    return _menu_keyboard(_symbol_rows("cmd_watchstock", list(symbols)) + [
        [{"text": "Signals", "callback_data": "cmd_watchlist"}, {"text": "Research", "callback_data": "cmd_research"}],
        [{"text": "Run AI Now", "callback_data": "cmd_runanalysis"}, {"text": "Run Research", "callback_data": "cmd_runresearch"}],
    ])


def _journal_keyboard():
    return _menu_keyboard([
        [{"text": "Recent", "callback_data": "cmd_journal"}, {"text": "Stats", "callback_data": "cmd_journal_stats"}],
    ])


def _controls_keyboard():
    return _menu_keyboard([
        [{"text": "Pause Bot", "callback_data": "cmd_stop"}, {"text": "Resume Bot", "callback_data": "cmd_start"}],
        [{"text": "Paper Mode", "callback_data": "cmd_paper_toggle"}, {"text": "Cash Auto", "callback_data": "cmd_cashtrade"}],
        [{"text": "Send Daily Summary", "callback_data": "cmd_summary"}],
    ])


def _default_reply_markup(callback_name):
    if callback_name in {"cmd_trading", "cmd_positions", "cmd_holdings", "cmd_autotrade", "cmd_stops"}:
        return _back_button("cmd_trading", "<< Trading")
    if callback_name in {"cmd_analysis", "cmd_watchlist", "cmd_watchstock", "cmd_newsstock", "cmd_runanalysis",
                         "cmd_research", "cmd_researchstock", "cmd_runresearch"}:
        return _back_button("cmd_watchlist", "<< Watchlist")
    if callback_name in {"cmd_market", "cmd_worldnews", "cmd_rawmat"}:
        return _back_button("cmd_market", "<< Market")
    if callback_name in {"cmd_journal", "cmd_journal_stats"}:
        return _back_button("cmd_journal", "<< Journal")
    if callback_name in {"cmd_controls", "cmd_summary", "cmd_start", "cmd_stop", "cmd_stop_confirm",
                         "cmd_cashtrade", "cmd_cashtrade_confirm", "cmd_paper_toggle", "cmd_paper_confirm"}:
        return _back_button("cmd_controls", "<< Controls")
    return _back_button()


def _send_menu(token=None, chat_id=None):
    """Send the main control panel with buttons."""
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    _send(f"<b>Groww</b> · {now}", token=token, chat_id=chat_id, reply_markup=_main_menu_keyboard())


def _set_my_commands(token):
    commands = [
        {"command": "menu", "description": "Main menu"},
        {"command": "dashboard", "description": "Where you stand, what is running, what is next"},
        {"command": "trading", "description": "P&L, open positions, last trades"},
        {"command": "positions", "description": "Open positions with stops"},
        {"command": "market", "description": "Market signal and the headlines behind it"},
        {"command": "watchlist", "description": "Signals vs your entry floor"},
        {"command": "watch", "description": "One stock: /watch TCS"},
        {"command": "news", "description": "Stock news: /news RELIANCE"},
        {"command": "journal", "description": "Recent closed trades"},
        {"command": "autotrade", "description": "Run one cash auto-trade cycle"},
        {"command": "stops", "description": "Move trailing stops now"},
        {"command": "papermode", "description": "Toggle paper mode (asks to confirm)"},
        {"command": "controls", "description": "Pause / resume / toggles"},
    ]
    try:
        url = _BASE_URL.format(token=token, method="setMyCommands")
        requests.post(url, json={"commands": commands}, timeout=10)
    except Exception as e:
        logger.debug("Telegram command registration failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

def _block(rows, w=9):
    """
    rows -> a <pre> block. Each row is (label, value) or a plain string.
    Labels pad to `w`; keep every line under ~38 chars so a phone shows it
    without horizontal scroll. Values are escaped here, callers pass raw.
    """
    out = []
    for r in rows:
        if isinstance(r, tuple):
            lab, val = r
            out.append(f"{lab:<{w}}{val}")
        else:
            out.append(r)
    return "<pre>" + _escape("\n".join(out)) + "</pre>"


def _title(name, *bits):
    tail = "  ".join(str(b) for b in bits if b)
    return f"<b>{_escape(name)}</b>" + (f"  {_escape(tail)}" if tail else "")


def _age(iso, naive_tz=IST):
    a = _time_ago(iso, naive_tz=naive_tz)
    return a.replace(" ago", "").replace("minutes", "m").replace("minute", "m").replace("hours", "h").replace("hour", "h").replace("days", "d").replace("day", "d").replace(" ", "")


_EMOJI = None


def _headline(text, limit=110):
    """Source headline, cleaned for a plain-text phone screen: emoji and
    variation selectors stripped, long dashes normalised, whitespace
    collapsed, then truncated. The words are untouched."""
    global _EMOJI
    if _EMOJI is None:
        import re
        _EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")
    cleaned = _EMOJI.sub("", str(text or "")).replace("—", "-").replace("–", "-")
    return _truncate(cleaned, limit)


def _dur(minutes):
    if not minutes: return ""
    return f"{minutes/60:.1f}h" if minutes >= 90 else f"{minutes:.0f}m"


def _reason(t):
    r = (t.get("exit_reason") or "").split(" (")[0].lower()
    return {"trailing_stop": "trail", "trailing_stop_hit": "trail", "signal_reversed": "signal",
            "manual": "manual", "hit_target": "target", "hit_sl": "stop", "stop_loss_hit": "stop"}.get(r, r.replace("_", " ")[:8])


def _paper_trades():
    """
    Every paper trade, from the SAME reconciliation the dashboard reads
    (/api/paper-trading/status), so a number here can never disagree with the
    one on screen. Net/gross/charges come from costs.py; peak from candles.
    """
    from db_manager import get_db, TradeJournalEntry
    from paper_trade_reconciliation import build_canonical_trade_views
    with get_db().Session() as session:
        rows = [t.to_dict() for t in session.query(TradeJournalEntry)
                .order_by(TradeJournalEntry.created_at.desc()).limit(2000).all()]
    return list(build_canonical_trade_views(rows)["paper"])


def _pnl(trades):
    """Net / gross / charges / peak-gross / wins / losses / today, in rupees."""
    closed = [t for t in trades if (t.get("status") or "").upper() != "OPEN" and t.get("net_pnl") is not None]
    today = datetime.now(IST).date()
    def _day(t):
        try: return datetime.fromisoformat(str(t.get("exit_time"))).date()
        except Exception: return None
    net = sum(t["net_pnl"] for t in closed)
    gross = sum(t.get("gross_pnl") or 0 for t in closed)
    charges = sum(t.get("total_charges") or 0 for t in closed)
    peak = sum(((t.get("peak_price") - t["entry_price"]) * t["quantity"]) if t.get("peak_price") else (t.get("gross_pnl") or 0) for t in closed)
    return {
        "closed": len(closed), "net": net, "gross": gross, "charges": charges, "peak_gross": peak,
        "wins": sum(1 for t in closed if t["net_pnl"] > 0), "losses": sum(1 for t in closed if t["net_pnl"] < 0),
        "today_net": sum(t["net_pnl"] for t in closed if _day(t) == today),
        "today_n": sum(1 for t in closed if _day(t) == today),
        "open": [t for t in trades if (t.get("status") or "").upper() == "OPEN"],
    }


def _market_state():
    try:
        from fno_trader import _is_market_open
        is_open, _ = _is_market_open()
        return "market open" if is_open else "market closed"
    except Exception:
        return ""


def _stamp():
    return datetime.now(IST).strftime("%d %b %H:%M")


def _rs(v, signed=True):
    return _fmt_money(v, signed=signed, decimals=0)


def _ltps(symbols):
    """Last price per symbol, fetched in parallel; a symbol that fails maps to
    None so one bad quote does not blank the whole screen."""
    from concurrent.futures import ThreadPoolExecutor
    import bot
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols:
        return {}
    def one(sym):
        try: return sym, float(bot.fetch_live_price(sym))
        except Exception: return sym, None
    with ThreadPoolExecutor(max_workers=min(4, len(symbols))) as ex:
        return dict(ex.map(one, symbols))


def _scan():
    """Latest watchlist scan plus the two entry gates, read once per screen."""
    from db_manager import get_config
    import auto_analyzer
    latest = auto_analyzer.get_latest_analysis() or {}
    return {
        "preds": latest.get("predictions") or [],
        "ts": latest.get("timestamp"),
        "floor": float(get_config("paper.min_confidence") or 0.5) * 100,
        "be_max": float(get_config("trade.max_breakeven_pct") or 0.6),
    }


def _entry_verdict(pred, floor, be_max):
    """One phrase: why this signal will or will not become a trade."""
    sig = pred.get("signal", "HOLD"); conf = (pred.get("confidence") or 0) * 100
    be = (pred.get("costs") or {}).get("breakeven_pct")
    if sig != "BUY":
        return "no entry" if sig == "HOLD" else "exit signal"
    if conf <= floor:
        return f"{floor - conf:.1f} below floor"
    if be is not None and be > be_max:
        return f"breakeven {be:.2f}% > {be_max:.2f}%"
    return "eligible"


def _cmd_help(**kw):
    lines = ["<b>Groww</b>", "",
             "<b>/dashboard</b> where you stand, what is running, what is next",
             "<b>/trading</b> P&amp;L, open positions, last trades",
             "<b>/positions</b> open positions with stops",
             "<b>/market</b> signal and the headlines behind it",
             "<b>/watchlist</b> signals vs your entry floor",
             "<b>/journal</b> recent closed trades", "",
             "<b>/autotrade</b> run one cash cycle now",
             "<b>/stops</b> move trailing stops now",
             "<b>/papermode</b> toggle paper mode (confirms first)", "",
             "<b>/watch</b> TCS · <b>/news</b> RELIANCE · <b>/research</b> TITAN · <b>/menu</b>"]
    return _response("\n".join(lines), reply_markup=_main_menu_keyboard())


def _cmd_holdings(**kw):
    """Broker (Groww) holdings — real money, separate from paper trades."""
    try:
        import bot
        resp = bot.get_holdings()
        raw = resp.get("holdings", resp.get("data", [])) if isinstance(resp, dict) else (resp or [])
        held = []
        for h in raw:
            sym = str(h.get("trading_symbol") or h.get("tradingSymbol") or h.get("symbol") or "?").split("-")[0]
            qty = float(h.get("quantity") or h.get("totalQuantity") or h.get("net_quantity") or 0)
            avg = float(h.get("average_price") or h.get("averagePrice") or h.get("avg_price") or 0)
            if qty > 0:
                held.append((sym, qty, avg))
        if not held:
            return _response(_title("HOLDINGS", _stamp()) + "\n<pre>Nothing held at the broker.</pre>",
                             reply_markup=_trading_keyboard())
        ltp = _ltps([s for s, _, _ in held])
        rows = [f"{'':<10}{'qty':>4}{'avg':>7}{'ltp':>7}{'pnl':>8}"]
        inv = cur = 0.0; body = []
        for sym, qty, avg in held:
            p = ltp.get(sym)
            inv += avg * qty
            if p is None:
                body.append((0.0, f"{sym[:10]:<10}{qty:>4.0f}{avg:>7.0f}{'—':>7}{'—':>8}"))
                continue
            cur += p * qty
            pnl = (p - avg) * qty
            body.append((pnl, f"{sym[:10]:<10}{qty:>4.0f}{avg:>7.0f}{p:>7.0f}{pnl:>+8.0f}"))
        body.sort(key=lambda x: x[0])                      # worst first
        rows += [r for _, r in body[:12]]
        priced = sum(1 for _, r in body if "—" not in r)
        pnl_t = cur - inv if priced == len(held) else None
        rows += ["", ("Invested", _rs(inv, signed=False)),
                 ("Current", _rs(cur, signed=False) if pnl_t is not None else f"{priced}/{len(held)} priced"),
                 ("P&L", f"{_rs(pnl_t)} · {pnl_t / inv * 100:+.1f}%" if pnl_t is not None and inv else "—")]
        text = _title("HOLDINGS", f"{len(held)} held", _stamp()) + "\n" + _block(rows)
        if len(held) > 12:
            text += f"\n{len(held) - 12} more not shown; worst 12 listed first."
        return _response(text, reply_markup=_trading_keyboard())
    except Exception as e:
        why = "Groww session expired; holdings need a fresh token." if "auth" in str(e).lower() or "token" in str(e).lower() else _escape(e)
        return _response(f"Holdings unavailable: {why}", reply_markup=_trading_keyboard())


def _cmd_positions(**kw):
    try:
        import bot, costs
        opens = [t for t in _paper_trades() if (t.get("status") or "").upper() == "OPEN"]
        if not opens:
            return _response(_title("POSITIONS", _stamp(), _market_state()) + "\n<pre>Nothing open.</pre>", reply_markup=_trading_keyboard())
        rows = [f"{'':<10}{'entry':>7}{'ltp':>7}{'net':>7}{'stop':>7}"]
        total = 0.0; unarmed = []
        for t in opens[:8]:
            e, q = float(t["entry_price"]), int(t["quantity"])
            try: ltp = bot.fetch_live_price(t["symbol"])
            except Exception: ltp = None
            stop = t.get("trailing_stop") or t.get("stop_loss")
            if not t.get("trailing_stop"): unarmed.append(t["symbol"])
            if ltp:
                net = costs.net_profit(e, float(ltp), q)["net_profit"]; total += net
                rows.append(f"{t['symbol'][:10]:<10}{e:>7.0f}{float(ltp):>7.0f}{net:>+7.0f}{(float(stop) if stop else 0):>7.0f}")
            else:
                rows.append(f"{t['symbol'][:10]:<10}{e:>7.0f}{'—':>7}{'—':>7}{(float(stop) if stop else 0):>7.0f}")
        rows += ["", ("Open net", f"{_rs(total)} after est. exit charges")]
        text = _title("POSITIONS", _stamp(), _market_state()) + "\n" + _block(rows)
        if unarmed:
            text += f"\nNo trailing stop yet on {', '.join(_escape(x) for x in unarmed[:4])}."
        return _response(text, reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"Positions unavailable: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_rawmat(**kw):
    """Commodity moves and which watchlist stocks they push. Prices come from
    the same fetcher as /api/raw-materials, fetched in parallel."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        import commodity_tracker as ct
        groups = {}
        for stock, info in ct.get_commodity_map_dict().items():
            g = groups.setdefault(info["ticker"], {"name": info["commodity"], "direct": [], "inverse": []})
            g["direct" if info.get("relationship") == "direct" else "inverse"].append(stock)
        def one(t):
            try: return t, ct.fetch_commodity_price(t)
            except Exception: return t, None
        with ThreadPoolExecutor(max_workers=min(6, len(groups))) as ex:
            prices = dict(ex.map(one, list(groups)))
        got = [(t, g, prices[t]) for t, g in groups.items() if prices.get(t)]
        if not got:
            return _response(_title("RAW MATERIALS", _stamp()) + "\nCommodity prices unavailable right now (yfinance).",
                             reply_markup=_market_keyboard())
        got.sort(key=lambda x: -abs(x[2]["price_change_1m"]))
        short = lambda n: n.split(" / ")[0][:10]
        rows = [f"{'':<10}{'price':>8}{'1m':>7}{'3m':>7}"]
        for t, g, p in got:
            cur = ("₹" if "INR" in t else "$") + f"{p['current_price']:,.0f}"
            rows.append(f"{short(g['name']):<10}{cur:>8}{p['price_change_1m']:>+6.1f}%{p['price_change_3m']:>+6.1f}%")
        movers = [(t, g, p) for t, g, p in got if abs(p["price_change_1m"]) >= 2][:3]
        text = _title("RAW MATERIALS", f"{len(got)} tracked", _stamp()) + "\n" + _block(rows)
        if movers:
            mr = []
            for t, g, p in movers:
                up = p["price_change_1m"] > 0
                helps = g["direct"] if up else g["inverse"]; hurts = g["inverse"] if up else g["direct"]
                lst = lambda xs: " ".join(xs[:2]) + (f" +{len(xs) - 2}" if len(xs) > 2 else "")
                mr.append(f"{short(g['name'])} {p['price_change_1m']:+.0f}% this month")
                if helps: mr.append(f"  helps {lst(helps)}")
                if hurts: mr.append(f"  hurts {lst(hurts)}")
            text += "\n" + _block(mr)
        else:
            text += "\nNo commodity moved 2% this month: no raw-material push on the watchlist."
        missing = [short(g["name"]) for t, g in groups.items() if not prices.get(t)]
        if missing:
            text += f"\nNot priced right now: {', '.join(missing)}."
        return _response(text, reply_markup=_market_keyboard())
    except Exception as e:
        return _response(f"Raw materials unavailable: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_start(**kw):
    global _scheduler_paused
    _scheduler_paused = False
    logger.info("SCHEDULER RESUMED via Telegram command")
    return _response("Bot <b>resumed</b>. Every task is back on schedule and the stop monitor is enforcing again.",
                     reply_markup=_controls_keyboard())


def _cmd_cashtrade(**kw):
    """Step 1 of 2: say what the flip does in the current mode, then confirm.
    Turning it on in live mode places real orders, so it confirms like Paper
    Mode and Pause do."""
    try:
        from db_manager import get_config
        on = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        paper = get_config("paper_trading", "false").lower() == "true"
        floor = float(get_config("paper.min_confidence") or 0.5) * 100
        if on:
            text = ("<b>Turn cash auto-trade OFF?</b>\n\n"
                    "No new entries and trailing stops stop moving. "
                    "The 5-second monitor still closes positions at the stops already set.")
            yes = "Yes, turn off"
        else:
            text = ("<b>Turn cash auto-trade ON?</b>\n\n"
                    f"In market hours the bot enters every BUY at or above {floor:.0f}% confidence "
                    + ("as <b>paper</b> trades." if paper else "with <b>real money</b>; paper mode is OFF."))
            yes = "Yes, turn on"
        kb = {"inline_keyboard": [[{"text": yes, "callback_data": "cmd_cashtrade_confirm"},
                                   {"text": "Cancel", "callback_data": "cmd_controls"}]]}
        return _response(text, reply_markup=kb)
    except Exception as e:
        return _response(f"Could not read the toggle: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_cashtrade_confirm(**kw):
    """Step 2 of 2: flip it."""
    try:
        from db_manager import get_config, set_config
        on = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        new_val = "false" if on else "true"
        set_config("cash_auto_trade_enabled", new_val, description="Cash equity auto-trade (true/false)")
        paper = get_config("paper_trading", "false").lower() == "true"
        msg = ("Cash auto-trade <b>OFF</b>. Open positions keep their stops." if new_val == "false"
               else f"Cash auto-trade <b>ON</b> in {'paper' if paper else '<b>LIVE</b>'} mode from the next cycle.")
        return _response(msg, reply_markup=_controls_keyboard())
    except Exception as e:
        return _response(f"Toggle failed: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_dashboard(**kw):
    try:
        from db_manager import get_config
        import bot, auto_analyzer, news_sentiment
        p = _pnl(_paper_trades())
        paper_mode = get_config("paper_trading", "false").lower() == "true"
        cash_auto = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        floor = float(get_config("paper.min_confidence") or 0.5) * 100
        deployed = sum((t.get("entry_value") or 0) for t in p["open"])
        state = _market_state()
        preds = (auto_analyzer.get_latest_analysis() or {}).get("predictions") or []
        buys = sorted([x for x in preds if x.get("signal") == "BUY"], key=lambda x: -(x.get("confidence") or 0))
        above = [x for x in buys if (x.get("confidence") or 0) * 100 > floor]
        try:
            m = news_sentiment.get_market_sentiment().to_dict()
            mscore = float(m.get("avg_score") or 0); msig = (m.get("signal") or "neutral").lower()
        except Exception:
            mscore, msig = 0.0, "n/a"
        try:
            h = bot.get_holdings(); hs = h.get("holdings", h.get("data", [])) if isinstance(h, dict) else (h or [])
            hcost = sum(float(x.get("quantity") or 0) * float(x.get("average_price") or 0) for x in hs)
        except Exception:
            hs, hcost = [], 0.0

        mode = "paper" if paper_mode else "LIVE"
        wd = datetime.now(IST).weekday()
        nxt = ("running" if state == "market open" else ("Mon 09:15" if wd >= 4 else "09:15")) if cash_auto else ""
        if above:
            sig = f"{len(buys)} BUY · {len(above)} >{floor:.0f}% · {above[0]['symbol'][:9]} {above[0]['confidence']*100:.0f}"
        elif buys:
            sig = f"{len(buys)} BUY · 0 >{floor:.0f}% (top {buys[0]['confidence']*100:.1f})"
        else:
            sig = f"0 BUY of {len(preds)}" if preds else "no scan yet"
        shift = abs(mscore) * 0.25
        rows = [
            ("Net", f"{_rs(p['net'])} all-time · {_rs(p['today_net'])} today"),
            ("Open", f"{len(p['open'])} · {_rs(deployed, signed=False)} at risk"),
            ("Mode", f"{mode} · auto {'ON' if cash_auto else 'OFF'}" + (f" · {nxt}" if nxt else "")),
            "",
            ("Signals", sig),
            ("Market", f"{mscore:+.2f} {msig} · {'negligible' if shift < 0.05 else f'±{shift:.2f}'}"),
            ("Holdings", f"{len(hs)} · {_rs(hcost, signed=False)} cost" if hs else "none"),
        ]
        return _response(_title("DASHBOARD", _stamp(), state) + "\n" + _block(rows), reply_markup=_main_menu_keyboard())
    except Exception as e:
        return _response(f"Dashboard unavailable: {_escape(e)}", reply_markup=_main_menu_keyboard())


def _cmd_market(args="", **kw):
    try:
        import news_sentiment
        m = news_sentiment.get_market_sentiment().to_dict()
        score = float(m.get("avg_score") or 0); conf = float(m.get("confidence") or 0) * 100
        sig = (m.get("signal") or "neutral").lower(); shift = abs(score) * 0.25
        rows = [("Signal", f"{sig} {score:+.2f} · conf {conf:.0f}%"),
                ("Weight", f"25% of score → ±{shift:.2f}"),
                ("Articles", f"{m.get('total_articles', 0)} · {m.get('bullish_count', 0)} bull · {m.get('bearish_count', 0)} bear"),
                "", "Headlines"]
        rows += [f"· {_headline(a.get('title', ''), 36)}" for a in (m.get("articles") or [])[:3]] or ["· none"]
        text = _title("MARKET", _stamp()) + "\n" + _block(rows)
        if conf < 30:
            text += f"\nAt {conf:.0f}% confidence the model is guessing; the headlines are the better read."
        return _response(text, reply_markup=_market_keyboard())
    except Exception as e:
        return _response(f"Market unavailable: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_worldnews(args="", **kw):
    """Headlines from the world-news collector. The Market screen shows the
    three behind the sentiment signal; this is the wider feed, by category.
    No age per line: the collector's published_at stamps are IST wall-clock
    labelled "Z", so an age computed from them is wrong by up to 5h30."""
    try:
        from world_news_collector import get_recent_news
        category = (args or "").strip().lower() or None
        arts = get_recent_news(category=category, limit=8, days=7) or []
        head = _title("WORLD NEWS", category or "all", "latest 8 of 7d")
        if not arts:
            return _response(head + "\nNothing collected in the last 7 days; the collector may be down.",
                             reply_markup=_market_keyboard())
        out = [head]; seen = set()
        for a in arts:
            t = _headline(a.get("title", ""), 110)
            k = t[:40].lower()
            if k in seen: continue
            seen.add(k)
            meta = " · ".join(x for x in (str(a.get("category") or "general"), str(a.get("source") or "")[:30]) if x)
            out.append(f"<b>{_escape(meta)}</b>\n{_escape(t)}")
        return _response("\n\n".join(out), reply_markup=_market_keyboard())
    except Exception as e:
        return _response(f"World news unavailable: {_escape(e)}", reply_markup=_market_keyboard())


def _cmd_newsstock(args="", **kw):
    """News behind one stock's call: the signal it feeds in, its weight, the
    headlines. Reads the sentiment model's output; does not change it."""
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /news SYMBOL, or tap News on a stock.", reply_markup=_watchlist_keyboard())
    try:
        import news_sentiment
        from db_manager import get_config
        w = float(get_config("prediction.weight.news", default="0.20"))
        d = news_sentiment.get_news_sentiment(symbol).to_dict()
        score = float(d.get("avg_score") or 0); conf = float(d.get("confidence") or 0) * 100
        rows = [("Signal", f"{str(d.get('signal') or 'neutral').lower()} {score:+.2f} · conf {conf:.0f}%"),
                ("Weight", f"{w*100:.0f}% of the call → ±{abs(score)*w:.2f}"),
                ("Articles", f"{d.get('total_articles', 0)} · {d.get('bullish_count', 0)} bull · {d.get('bearish_count', 0)} bear")]
        out = [_title(symbol, "news", _stamp()) + "\n" + _block(rows)]
        arts, seen = [], set()
        for a in d.get("articles") or []:
            t = _headline(a.get("title", ""), 110)
            k = t[:40].lower()
            if k in seen: continue
            seen.add(k); arts.append((a, t))
            if len(arts) == 5: break
        for a, t in arts:
            meta = " · ".join(x for x in (str(a.get("sentiment") or "").lower(), _age(a.get("published"), naive_tz=timezone.utc),
                                          str(a.get("source") or "")[:30]) if x)
            out.append(f"<b>{_escape(meta)}</b>\n{_escape(t)}")
        if not arts:
            out.append("No articles in the window; the signal above is the neutral default.")
        elif conf < 30:
            out.append(f"At {conf:.0f}% confidence the model is guessing; read the headlines, not the score.")
        kb = _menu_keyboard([
            [{"text": "Call", "callback_data": f"cmd_watchstock:{symbol}"}, {"text": "Research", "callback_data": f"cmd_researchstock:{symbol}"}],
        ], back_target=f"cmd_watchstock:{symbol}", back_text=f"<< {symbol}")
        return _response("\n\n".join(out), reply_markup=kb)
    except Exception as e:
        return _response(f"{_escape(symbol)} news unavailable: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_watchlist(args="", **kw):
    """Watchlist hub: the latest scan ranked against the entry floor, with a
    button per BUY to open that stock. /analysis lands here too, so there is
    one signals screen, not a signals screen and a summary of it."""
    try:
        s = _scan(); floor, be = s["floor"], s["be_max"]
        preds = s["preds"]
        buys = sorted([x for x in preds if x.get("signal") == "BUY"], key=lambda x: -(x.get("confidence") or 0))
        sells = sorted([x for x in preds if x.get("signal") == "SELL"], key=lambda x: -(x.get("confidence") or 0))
        above = [x for x in buys if (x.get("confidence") or 0) * 100 > floor]
        if not preds:
            return _response(_title("SIGNALS", _stamp()) + "\nNo scan yet. Run AI Now builds one; open this again in a few minutes.",
                             reply_markup=_watchlist_keyboard())
        rows = [f"BUY {len(buys)} · {len(above)} above the {floor:.0f}% floor"]
        rows += [f"{x['symbol'][:10]:<10}{(x.get('confidence') or 0)*100:>6.1f}{'  eligible' if (x.get('confidence') or 0)*100 > floor else ''}" for x in buys[:6]] or ["none"]
        rows += ["", f"SELL {len(sells)}"] + ([f"{x['symbol'][:10]:<10}{(x.get('confidence') or 0)*100:>6.1f}" for x in sells[:4]] or ["none"])
        holds = len(preds) - len(buys) - len(sells)
        if holds:
            rows += ["", f"HOLD {holds}"]
        text = _title("SIGNALS", f"{len(preds)} scanned", _age(s["ts"])) + "\n" + _block(rows)
        text += f"\nEligible still needs breakeven ≤{be:.2f}% at entry." if above else f"\nNothing above {floor:.0f}%: no entries from this scan."
        text += "\nTap a symbol for the full call."
        # buttons: every BUY first; when there are few, the highest-confidence
        # names of any signal so the drill-down is never a dead end
        syms = [x["symbol"] for x in buys[:6]]
        for x in sorted(preds, key=lambda x: -(x.get("confidence") or 0)):
            if len(syms) >= 6: break
            if x.get("symbol") and x["symbol"] not in syms: syms.append(x["symbol"])
        return _response(text, reply_markup=_watchlist_keyboard(syms))
    except Exception as e:
        return _response(f"Signals unavailable: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_analysis(**kw):
    return _cmd_watchlist(**kw)


def _cmd_watchstock(args="", **kw):
    """One stock: the call, the inputs behind it, the model's own reasoning.
    Reads the cached scan so the number matches the Signals screen; falls back
    to a live prediction for a symbol the scan did not cover."""
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /watch SYMBOL, or tap a symbol on the Signals screen.", reply_markup=_watchlist_keyboard())
    try:
        import bot
        from db_manager import get_watchlist_note
        s = _scan()
        pred = next((x for x in s["preds"] if x.get("symbol") == symbol), None)
        src = f"scan {_age(s['ts'])}" if pred else "live"
        if pred is None:
            pred = bot.get_prediction(symbol)
        ind = pred.get("indicators") or {}; so = pred.get("sources") or {}
        ml = so.get("ml") or {}; news = so.get("news") or {}; ctx = so.get("market_context") or {}
        c = pred.get("costs") or {}; lt = pred.get("long_term_trend") or {}
        conf = (pred.get("confidence") or 0) * 100
        price = ind.get("price")
        if not price:
            try: price = bot.fetch_live_price(symbol)
            except Exception: price = None
        rows = [("Call", f"{pred.get('signal', 'HOLD')} {conf:.1f}% · {_entry_verdict(pred, s['floor'], s['be_max'])}"),
                ("Price", (f"{price:,.2f}" if price else "—") + (f" · breakeven +{c['breakeven_pct']:.2f}%" if c.get("breakeven_pct") is not None else "")),
                ("Charges", f"₹{c['total_charges']:,.0f} round trip" if c.get("total_charges") is not None else "—"),
                "",
                ("ML", f"{ml.get('signal', '—')} {(ml.get('confidence') or 0)*100:.0f}%" if ml else "—"),
                ("News", f"{news.get('signal', '—')} {float(news.get('avg_score') or 0):+.2f} · {news.get('total_articles', 0)} art" if news else "—"),
                ("Market", str(ctx.get("market_signal") or "—").lower()),
                ("RSI", f"{ind['rsi']:.0f} · {str(ind.get('trend') or '').lower()} trend" if ind.get("rsi") is not None else "—")]
        if lt.get("trend_pct") is not None:
            rows.append(("5y", f"{lt['trend_pct']:+.0f}% · {lt.get('support', 0):,.0f} / {lt.get('resistance', 0):,.0f}"))
        text = _title(symbol, src) + "\n" + _block(rows)
        if pred.get("reason"):
            text += "\n" + _escape(_truncate(pred["reason"], 180))
        try: note = get_watchlist_note(symbol)
        except Exception: note = None
        if note:
            text += "\n<b>Note</b> " + _escape(_truncate(note, 160))
        kb = _menu_keyboard([
            [{"text": "News", "callback_data": f"cmd_newsstock:{symbol}"}, {"text": "Research", "callback_data": f"cmd_researchstock:{symbol}"}],
            [{"text": "Refresh", "callback_data": f"cmd_watchstock:{symbol}"}],
        ], back_target="cmd_watchlist", back_text="<< Signals")
        return _response(text, reply_markup=kb)
    except Exception as e:
        return _response(f"{_escape(symbol)} unavailable: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_research(args="", **kw):
    """Research leaderboard: alpha ranks the edge, conviction says how sure."""
    symbol = _extract_symbol(args)
    if symbol:
        return _cmd_researchstock(symbol)
    try:
        from research_engine import get_cached_leaderboard
        lb = sorted(get_cached_leaderboard() or [], key=lambda r: -(r.get("alpha_score") or 0))
        if not lb:
            return _response(_title("RESEARCH", _stamp()) + "\nNo leaderboard from the last 2 days. Run Research builds it; it works stock by stock and takes a while.",
                             reply_markup=_watchlist_keyboard())
        rows = [f"{'':<10}{'stance':<6}{'alpha':>6}{'conv':>5}"]
        for r in lb[:10]:
            v = r.get("verdict") if isinstance(r.get("verdict"), dict) else {}
            rows.append(f"{str(r.get('symbol') or '?')[:9]:<10}{str(v.get('stance') or 'hold').lower()[:5]:<6}{float(r.get('alpha_score') or 0):>6.1f}{float(r.get('conviction') or 0):>5.0f}")
        buys = sum(1 for r in lb if isinstance(r.get("verdict"), dict) and r["verdict"].get("stance") == "BUY")
        text = _title("RESEARCH", f"{len(lb)} ranked", _age(lb[0].get("generated_at"), naive_tz=timezone.utc)) + "\n" + _block(rows)
        text += f"\n{buys} of {len(lb)} rate BUY. Alpha ranks the edge, conviction how sure; tap a symbol for the report."
        kb = _menu_keyboard(_symbol_rows("cmd_researchstock", [r["symbol"] for r in lb[:6] if r.get("symbol")]) + [
            [{"text": "Signals", "callback_data": "cmd_watchlist"}, {"text": "Run Research", "callback_data": "cmd_runresearch"}],
        ], back_target="cmd_watchlist", back_text="<< Watchlist")
        return _response(text, reply_markup=kb)
    except Exception as e:
        return _response(f"Research unavailable: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_researchstock(args="", **kw):
    """One research report: verdict, the five dimension scores, catalysts."""
    symbol = _extract_symbol(args)
    if not symbol:
        return _response("Use /research SYMBOL, or tap a symbol on Research.", reply_markup=_watchlist_keyboard())
    try:
        from research_engine import generate_research, get_cached_report
        rep = get_cached_report(symbol) or generate_research(symbol)
        v = rep.get("verdict") or {}; dims = rep.get("dimensions") or {}
        rr = rep.get("risk_reward") or {}; lt = rep.get("long_term") or {}
        low = lambda x: str(x or "").replace("_", " ").lower()
        rows = [("Verdict", f"{v.get('stance', 'HOLD')} · {low(v.get('confidence'))} conf"),
                ("Alpha", f"{float(rep.get('alpha_score') or 0):.1f} · {float(rep.get('conviction') or 0):.0f}% conviction"),
                ("Risk", f"{low(v.get('risk_label')).replace(' risk', '')} · {low(rep.get('regime'))}")]
        if rr.get("upside_pct") is not None:
            rows.append(("Up/down", f"+{rr['upside_pct']:.1f}% / -{rr.get('downside_pct', 0):.1f}% · {rr.get('risk_reward', 0):.2f}"))
            if rr.get("support"):
                rows.append(("Sup/res", f"{rr['support']:,.0f} / {rr.get('resistance', 0):,.0f}"))
        sc = [f"{lab} {float(dims[k]['score']):.0f}" for k, lab in (("technical", "Tech"), ("fundamental", "Fund"), ("institutional", "Inst"), ("sentiment", "Sent"), ("risk", "Risk"))
              if isinstance(dims.get(k), dict) and dims[k].get("score") is not None]
        if sc:
            rows += ["", ("Scores", " ".join(sc[:3])), ("", " ".join(sc[3:]))]
        if lt.get("return_5y_pct") is not None:
            rows.append(f"5y {lt['return_5y_pct']:+.0f}% · max drawdown {lt.get('max_drawdown_pct', 0):.0f}%")
        text = _title(symbol, "research", _age(rep.get("generated_at"), naive_tz=timezone.utc)) + "\n" + _block(rows)
        cats = [c.get("catalyst") or c.get("title") or c.get("name") if isinstance(c, dict) else str(c) for c in (rep.get("catalysts") or [])[:3]]
        cats = [c for c in cats if c]
        if cats:
            text += "\n" + "\n".join(f"· {_escape(_headline(c, 60))}" for c in cats)
        else:
            text += "\nNo catalyst on file: the verdict rests on price and positioning alone."
        if rr.get("risk_reward") is not None and rr["risk_reward"] < 1 and v.get("stance") == "BUY":
            text += f"\nDownside outweighs upside at this price; entries nearer {rr.get('support', 0):,.0f} change that."
        kb = _menu_keyboard([
            [{"text": "Call", "callback_data": f"cmd_watchstock:{symbol}"}, {"text": "News", "callback_data": f"cmd_newsstock:{symbol}"}],
            [{"text": "Refresh", "callback_data": f"cmd_researchstock:{symbol}"}],
        ], back_target="cmd_research", back_text="<< Research")
        return _response(text, reply_markup=kb)
    except Exception as e:
        return _response(f"{_escape(symbol)} research unavailable: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_runanalysis(**kw):
    try:
        import auto_analyzer
        threading.Thread(target=auto_analyzer.auto_analyze_watchlist, daemon=True, name="telegram-auto-analysis").start()
        return _response("Scan started in the background. Open Signals in a few minutes; its title shows the scan age.",
                         reply_markup=_watchlist_keyboard())
    except Exception as e:
        return _response(f"Scan did not start: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_runresearch(**kw):
    try:
        from research_engine import generate_research_all
        threading.Thread(target=generate_research_all, daemon=True, name="telegram-research-batch").start()
        return _response("Research batch started. It works stock by stock and takes a while; Research shows the age of what it has.",
                         reply_markup=_watchlist_keyboard())
    except Exception as e:
        return _response(f"Research batch did not start: {_escape(e)}", reply_markup=_watchlist_keyboard())


def _cmd_trading(**kw):
    try:
        from db_manager import get_config
        trades = _paper_trades(); p = _pnl(trades)
        paper_mode = get_config("paper_trading", "false").lower() == "true"
        cap = float(get_config("paper.cap.xgboost") or 50000)
        n = p["closed"]; wr = (p["wins"] / n * 100) if n else 0
        fee = (p["charges"] / p["gross"] * 100) if p["gross"] > 0 else 0
        deployed = sum((t.get("entry_value") or 0) for t in p["open"])
        rows = [("Net", f"{_rs(p['net'])} · {p['wins']}W {p['losses']}L · {wr:.1f}%"),
                ("Gross", _rs(p["gross"])),
                ("Charges", f"{_rs(p['charges'], signed=False)} · {fee:.0f}% of gross"),
                ("Peak", f"{_rs(p['peak_gross'])} gross"),
                ("Gave back", _rs(p["peak_gross"] - p["gross"], signed=False)),
                "",
                ("Open", f"{len(p['open'])} · {_rs(deployed, signed=False)} / {_rs(cap, signed=False)}")]
        for t in p["open"][:4]:
            stop = t.get("trailing_stop") or t.get("stop_loss")
            rows.append(f"{t['symbol']:<10} {t['quantity']}@{t['entry_price']:.0f}" + (f" stop {stop:.0f}" if stop else " no stop"))
        closed = sorted([t for t in trades if (t.get("status") or "").upper() != "OPEN" and t.get("exit_time")],
                        key=lambda t: t["exit_time"], reverse=True)[:3]
        if closed:
            rows += ["", "Last closed"]
            for t in closed:
                d = _dur((t.get("post_trade") or {}).get("duration_minutes"))
                rows.append(f"{t['symbol']:<10} {_rs(t.get('net_pnl') or 0):>7}  {_reason(t):<6} {d}")
        return _response(_title("TRADING", "paper" if paper_mode else "LIVE", _stamp()) + "\n" + _block(rows, w=10), reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"Trading unavailable: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_autotrade(**kw):
    """Run one cash cycle now and report what it did and why it skipped."""
    try:
        from db_manager import get_config
        import bot
        paper_mode = get_config("paper_trading", "false").lower() == "true"
        r = bot.auto_trade()
        if r.get("error"):
            return _response(f"Cycle did not run: {_escape(r.get('message', r['error']))}", reply_markup=_trading_keyboard())
        acts = r.get("actions") or []
        by = lambda k: [a for a in acts if a.get("action") == k]
        buys, sells, skips, errs, holds = by("BUY"), by("SELL"), by("SKIP"), by("ERROR"), by("HOLD")
        def why(a):
            s = str(a.get("reason") or "").lower()
            if "low confidence" in s: return "under floor"
            if "cost-gated" in s: return "cost-gated"
            if "capital" in s: return "capital cap"
            if "too small" in s: return "too small"
            return "other"
        skip_counts = {}
        for a in skips:
            skip_counts[why(a)] = skip_counts.get(why(a), 0) + 1
        why_rows = ([f"{'':<8}{len(holds)} hold"] if holds else []) + \
                   [f"{'':<8}{n} {k}" for k, n in sorted(skip_counts.items(), key=lambda x: -x[1])[:3]]
        rows = [("Bought", f"{len(buys)}"), ("Sold", f"{len(sells)}"),
                ("Skipped", f"{len(skips) + len(holds)}")] + why_rows + [("Errors", f"{len(errs)}")]
        for a in (buys + sells)[:6]:
            t = a.get("trade") or {}
            rows.append(f"{a.get('action'):<5}{str(a.get('symbol') or '?')[:10]:<10} {t.get('quantity', '?')}@{float(t.get('price') or 0):,.0f}")
        for a in errs[:3]:
            rows.append(f"ERR  {str(a.get('symbol') or '?')[:10]:<10} {_truncate(a.get('reason', ''), 20)}")
        text = _title("CYCLE", "paper" if paper_mode else "LIVE", _stamp()) + "\n" + _block(rows, w=8)
        if not buys and not sells:
            text += "\nNothing traded this cycle; the skip reasons above are the gates that held."
        return _response(text, reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"Cycle failed: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_stops(**kw):
    try:
        import bot
        r = bot.monitor_and_update_trailing_stops()
        rows = [("Checked", f"{r.get('monitored', 0)} open"), ("Moved", f"{r.get('updated', 0)}")]
        rows += [f"{e.get('symbol', '?')[:10]:<10} → {float(e.get('price') or 0):.0f}" for e in (r.get("events") or [])[:5]]
        text = _title("STOPS", _stamp()) + "\n" + _block(rows) + "\nClosing is the 5-second monitor's job, not this command's."
        return _response(text, reply_markup=_trading_keyboard())
    except Exception as e:
        return _response(f"Stops unavailable: {_escape(e)}", reply_markup=_trading_keyboard())


def _cmd_journal(**kw):
    try:
        closed = sorted([t for t in _paper_trades() if (t.get("status") or "").upper() != "OPEN" and t.get("exit_time")],
                        key=lambda t: t["exit_time"], reverse=True)
        rows = [f"{t['symbol'][:10]:<10} {_rs(t.get('net_pnl') or 0):>7}  {_reason(t):<6} {_age(t.get('exit_time')):>5}" for t in closed[:10]] or ["No closed trades yet"]
        return _response(_title("JOURNAL", f"last {min(10, len(closed))} of {len(closed)}") + "\n" + _block(rows), reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"Journal unavailable: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_journal_stats(**kw):
    try:
        trades = _paper_trades()
        closed = [t for t in trades if (t.get("status") or "").upper() != "OPEN" and t.get("net_pnl") is not None]
        wins = [t["net_pnl"] for t in closed if t["net_pnl"] > 0]; losses = [t["net_pnl"] for t in closed if t["net_pnl"] < 0]
        avg_w = sum(wins) / len(wins) if wins else 0; avg_l = sum(losses) / len(losses) if losses else 0
        def acc(key):
            v = [(t.get("post_trade") or {}).get(key) for t in closed]; v = [x for x in v if x is not None]
            return (sum(1 for x in v if x) / len(v) * 100, len(v)) if v else (None, 0)
        pred, npd = acc("prediction_correct"); ml, nml = acc("ml_correct"); news, nnw = acc("news_correct")
        wr = (len(wins) / len(closed) * 100) if closed else 0
        rows = [("Win rate", f"{wr:.1f}%  ({len(wins)}/{len(closed)})"),
                ("Avg win", _rs(avg_w)), ("Avg loss", _rs(avg_l)),
                ("W/L", f"{(avg_w / abs(avg_l)) if avg_l else 0:.2f}"), "",
                ("Calls", f"right {pred:.0f}%  ({npd} analysed)" if pred is not None else "not analysed"),
                ("ML", f"right {ml:.0f}%  ({nml})" if ml is not None else "not analysed"),
                ("News", f"right {news:.0f}%  ({nnw})" if news is not None else "not analysed")]
        text = _title("STATS", f"{len(closed)} closed") + "\n" + _block(rows)
        if pred is not None and pred >= 70 and wr < 50:
            text += "\nCalls are right and trades still lose: the exit, not the pick, is where money goes."
        if npd < len(closed):
            text += f"\n{len(closed) - npd} of {len(closed)} predate post-trade analysis."
        return _response(text, reply_markup=_journal_keyboard())
    except Exception as e:
        return _response(f"Stats unavailable: {_escape(e)}", reply_markup=_journal_keyboard())


def _cmd_controls(**kw):
    try:
        from db_manager import get_config
        paper = get_config("paper_trading", "false").lower() == "true"
        cash = get_config("cash_auto_trade_enabled", "false").lower() == "true"
        rows = [("Bot", "PAUSED · stops not enforced" if is_scheduler_paused() else "running"),
                ("Mode", "paper" if paper else "LIVE · real orders"),
                ("Cash auto", "ON" if cash else "OFF")]
        return _response(_title("CONTROLS", _stamp()) + "\n" + _block(rows, w=10) + "\nPause and Paper Mode ask to confirm.", reply_markup=_controls_keyboard())
    except Exception as e:
        return _response(f"Controls unavailable: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_toggle_paper(**kw):
    """Step 1 of 2: show what the flip means and ask for confirmation."""
    try:
        from db_manager import get_config
        current = get_config("paper_trading", "false").lower() == "true"
        if current:
            text = ("<b>Turn paper mode OFF?</b>\n\n"
                    "The next auto-trade cycle will place <b>real orders</b> with real money.\n"
                    "Open paper positions stay paper.")
            kb = {"inline_keyboard": [[{"text": "Yes, go live", "callback_data": "cmd_paper_confirm"},
                                       {"text": "Cancel", "callback_data": "cmd_controls"}]]}
        else:
            text = ("<b>Turn paper mode ON?</b>\n\n"
                    "The bot stops placing real orders and simulates instead.\n"
                    "Existing real positions are untouched.")
            kb = {"inline_keyboard": [[{"text": "Yes, go paper", "callback_data": "cmd_paper_confirm"},
                                       {"text": "Cancel", "callback_data": "cmd_controls"}]]}
        return _response(text, reply_markup=kb)
    except Exception as e:
        return _response(f"Could not read mode: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_paper_confirm(**kw):
    """Step 2 of 2: flip it."""
    try:
        from db_manager import get_config, set_config
        current = get_config("paper_trading", "false").lower() == "true"
        new_val = "false" if current else "true"
        set_config("paper_trading", new_val, description="Paper trading mode (true/false)")
        msg = ("Paper mode <b>OFF</b>: real orders from the next cycle." if new_val == "false"
               else "Paper mode <b>ON</b>: simulated orders only.")
        return _response(msg, reply_markup=_controls_keyboard())
    except Exception as e:
        return _response(f"Toggle failed: {_escape(e)}", reply_markup=_controls_keyboard())


def _cmd_stop(**kw):
    """Step 1 of 2: pausing also stops the auto-close monitor."""
    text = ("<b>Pause the bot?</b>\n\n"
            "Every scheduled task stops, including the 5-second stop monitor, so "
            "<b>open positions will not be protected</b> while paused.")
    kb = {"inline_keyboard": [[{"text": "Yes, pause", "callback_data": "cmd_stop_confirm"},
                               {"text": "Cancel", "callback_data": "cmd_controls"}]]}
    return _response(text, reply_markup=kb)


def _cmd_stop_confirm(**kw):
    global _scheduler_paused
    _scheduler_paused = True
    return _response("Bot <b>paused</b>. Stops are not enforced until you resume.", reply_markup=_controls_keyboard())


def _cmd_summary(**kw):
    try:
        from daily_summary import send_daily_summary
        r = send_daily_summary()
        if r.get("sent"):
            return _response("Daily summary sent to this chat.", reply_markup=_controls_keyboard())
        return _response(f"Daily summary not sent: {_escape(r.get('reason') or r.get('error') or 'unknown reason')}",
                         reply_markup=_controls_keyboard())
    except Exception as e:
        return _response(f"Daily summary failed: {_escape(e)}", reply_markup=_controls_keyboard())


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

_COMMANDS = {
    "/help": _cmd_help,
    "/start": _cmd_start,
    "/menu": None,  # handled specially
    "/dashboard": _cmd_dashboard,
    "/trading": _cmd_trading,
    "/positions": _cmd_positions,
    "/holdings": _cmd_holdings,
    "/market": _cmd_market,
    "/worldnews": _cmd_worldnews,
    "/rawmat": _cmd_rawmat,
    "/news": _cmd_newsstock,
    "/watchlist": _cmd_watchlist,
    "/watch": _cmd_watchstock,
    "/analysis": _cmd_analysis,
    "/research": _cmd_research,
    "/journal": _cmd_journal,
    "/controls": _cmd_controls,
    "/autotrade": _cmd_autotrade,
    "/stops": _cmd_stops,
    "/runanalysis": _cmd_runanalysis,
    "/runresearch": _cmd_runresearch,
    "/summary": _cmd_summary,
    "/papermode": _cmd_toggle_paper,
    "/cashtrade": _cmd_cashtrade,
    "/stop": _cmd_stop,
}

_CALLBACKS = {
    "cmd_menu": None,
    "cmd_help": _cmd_help,
    "cmd_dashboard": _cmd_dashboard,
    "cmd_trading": _cmd_trading,
    "cmd_positions": _cmd_positions,
    "cmd_holdings": _cmd_holdings,
    "cmd_autotrade": _cmd_autotrade,
    "cmd_stops": _cmd_stops,
    "cmd_market": _cmd_market,
    "cmd_worldnews": _cmd_worldnews,
    "cmd_rawmat": _cmd_rawmat,
    "cmd_newsstock": _cmd_newsstock,
    "cmd_watchlist": _cmd_watchlist,
    "cmd_watchstock": _cmd_watchstock,
    "cmd_analysis": _cmd_analysis,
    "cmd_research": _cmd_research,
    "cmd_researchstock": _cmd_researchstock,
    "cmd_runanalysis": _cmd_runanalysis,
    "cmd_runresearch": _cmd_runresearch,
    "cmd_journal": _cmd_journal,
    "cmd_journal_stats": _cmd_journal_stats,
    "cmd_controls": _cmd_controls,
    "cmd_summary": _cmd_summary,
    "cmd_start": _cmd_start,
    "cmd_stop": _cmd_stop,
    "cmd_stop_confirm": _cmd_stop_confirm,
    "cmd_cashtrade": _cmd_cashtrade,
    "cmd_cashtrade_confirm": _cmd_cashtrade_confirm,
    "cmd_paper_toggle": _cmd_toggle_paper,
    "cmd_paper_confirm": _cmd_paper_confirm,
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
