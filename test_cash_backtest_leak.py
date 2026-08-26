"""
Look-ahead leak tests for cash_backtester.

These exist because a backtest that leaks the future does not fail loudly —
it produces beautiful, confident, wrong numbers. Every assertion here checks
that a data source cannot see past the decision instant.

Run:  .venv/bin/python3 test_cash_backtest_leak.py
"""

import logging
import sys
from datetime import datetime

logging.disable(logging.WARNING)

SYMBOL = "RELIANCE"
DATE = "2026-05-13"
AS_OF = datetime(2026, 5, 13, 15, 30)
SESSION_OPEN = datetime(2026, 5, 13, 9, 15)

_failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


print("\n1. CANDLE READERS — must not return a bar after the ceiling")
from db_manager import CandleDatabase
db = CandleDatabase()
for fn, kw in (("get_fyers_candles_as_5min", {"days": 30}),
               ("get_fyers_1min", {"days": 5}),
               ("get_fyers_daily", {"days": 400})):
    df = getattr(db, fn)(SYMBOL, as_of=AS_OF, **kw)
    check(f"{fn} respects as_of", not df.empty and df["datetime"].max() <= AS_OF,
          f"max={df['datetime'].max() if not df.empty else 'EMPTY'}")

# as_of=None must be unchanged (live path regression guard)
live = db.get_fyers_candles_as_5min(SYMBOL, days=30)
check("as_of=None still reaches present day",
      not live.empty and live["datetime"].max() > AS_OF,
      f"max={live['datetime'].max() if not live.empty else 'EMPTY'}")


print("\n2. NEWS — must only see articles FETCHED by the ceiling")
import news_sentiment
past = news_sentiment.get_news_sentiment(SYMBOL, as_of=AS_OF)
now = news_sentiment.get_news_sentiment(SYMBOL)
check("replay sees fewer articles than live", len(past.articles) < len(now.articles),
      f"{len(past.articles)} vs {len(now.articles)}")

from db_manager import NewsArticle
sess = news_sentiment._get_news_db_session()
leaked = sess.query(NewsArticle).filter(
    NewsArticle.symbol == SYMBOL,
    NewsArticle.published_at >= AS_OF.replace(day=6),
    NewsArticle.fetched_at > AS_OF,
    NewsArticle.published_at <= AS_OF,
).count()
sess.close()
check("gating on fetched_at excludes already-published-but-not-yet-fetched",
      leaked > 0, f"{leaked} articles correctly withheld")

check("replay does not poison the live cache",
      news_sentiment.get_news_sentiment(SYMBOL).avg_score == now.avg_score)


print("\n3. MARKET CONTEXT — replay must not call the live API")
import market_context
_api_calls = []
_orig = market_context._fetch_candle_data
market_context._fetch_candle_data = lambda *a, **k: (_api_calls.append(a) or _orig(*a, **k))
try:
    ctx = market_context.analyze_market_context(None, SYMBOL, as_of=AS_OF)
    check("no live-API fallback fired in replay", len(_api_calls) == 0,
          f"{len(_api_calls)} calls")
    check("context_score produced", "context_score" in ctx,
          f"score={ctx.get('context_score')}")
finally:
    market_context._fetch_candle_data = _orig


print("\n4. LONG-TERM TREND — must be bounded by as_of")
import bot
lt_past = bot.analyze_long_term_trend(SYMBOL, as_of=AS_OF.date())
lt_now = bot.analyze_long_term_trend(SYMBOL)
check("as_of trend differs from unbounded trend",
      lt_past and lt_now and lt_past["trend_pct"] != lt_now["trend_pct"],
      f"{lt_past['trend_pct']:.2f}% vs {lt_now['trend_pct']:.2f}%" if lt_past and lt_now else "N/A")


print("\n5. MODEL — must be walk-forward, not the nightly artifact")
import cash_backtester as cb
from datetime import timedelta
predictor, train_df, err = cb._train_walk_forward(
    SYMBOL, cb.MODEL_GBC, SESSION_OPEN - timedelta(minutes=1))
check("walk-forward fit succeeded", err is None, err or "")
if train_df is not None:
    check("training data ends BEFORE the session being graded",
          train_df["datetime"].max() < SESSION_OPEN,
          f"max={train_df['datetime'].max()}")

import os
prod = os.path.join("models", "gbc_cash", f"{SYMBOL}.joblib")
if os.path.exists(prod):
    import joblib
    saved = joblib.load(prod)
    same = getattr(saved, "model", None) is getattr(predictor, "model", None)
    check("walk-forward model is NOT the production artifact", not same)
    mtime = datetime.fromtimestamp(os.path.getmtime(prod))
    check("production artifact would have leaked (proves the fix matters)",
          mtime > AS_OF, f"artifact dated {mtime:%Y-%m-%d}")


print("\n6. END-TO-END — no output field may reference the future")
r = cb.run_cash_backtest(SYMBOL, DATE, model="gbc")
check("backtest ran", "error" not in r, r.get("error", ""))
if "error" not in r:
    labels = r["chart"]["labels"]
    check("chart never extends past the ceiling year/month",
          all(not l.startswith(("Jun", "Jul", "Aug")) for l in labels),
          f"last label={labels[-1]}")
    check("segment tagged", r.get("segment") == "cash")
    check("option_type is EQ not CE/PE",
          r["trade_simulation"].get("option_type") in (None, "EQ"))


print("\n" + "=" * 60)
if _failures:
    print(f"FAILED ({len(_failures)}): " + ", ".join(_failures))
    sys.exit(1)
print("ALL LEAK CHECKS PASSED")
