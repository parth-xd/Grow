"""
Live-price batching tests for the XGB watchlist scan.

These exist because the batching has one property that is easy to lose and
invisible when lost: a symbol the batch could not price must abort the scan,
NOT quietly fall back to a per-symbol quote or a stale candle close. A
silent fallback restores the exact N-request behaviour the batch replaced,
and nothing in the output would look wrong.

No network, no DB, no trading paths: the FYERS transport and the prediction
body are stubbed, so nothing here can place, price or persist a trade.

Run:  .venv/bin/python3 test_xgb_price_batching.py
"""

import logging
import sys

logging.disable(logging.ERROR)

_failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


# ── 1. Generic chunking: ceil(n/50) requests, at any n ───────────────────
print("\n1. CHUNKING — arbitrary watchlist size, no hardcoded count")

import fyers_market_data_provider as fmdp

_calls = []


def _fake_get_quotes(chunk):
    _calls.append(list(chunk))
    return 200, {"s": "ok", "d": [{"n": s, "v": {"lp": 100.0}} for s in chunk]}


fmdp.fyers_client.get_quotes = _fake_get_quotes

for n, expected in ((1, 1), (50, 1), (51, 2), (66, 2), (100, 2), (101, 3), (500, 10)):
    _calls.clear()
    fmdp._quote_cache.clear()          # TTL cache would mask real request count
    syms = [f"SYM{n}_{i}" for i in range(n)]
    fmdp._get_quotes_cached(syms)
    check(f"{n} symbols -> {expected} request(s)", len(_calls) == expected,
          f"got {len(_calls)}")
    check(f"{n} symbols: no chunk exceeds the 50 cap",
          all(len(c) <= 50 for c in _calls),
          f"max chunk {max((len(c) for c in _calls), default=0)}")

_calls.clear()
fmdp._quote_cache.clear()
check("chunk size constant is the documented cap", fmdp._QUOTES_BATCH_SIZE == 50,
      f"_QUOTES_BATCH_SIZE={fmdp._QUOTES_BATCH_SIZE}")


# ── 2. scan_watchlist_xgb: one prefetch, price handed to every worker ────
print("\n2. SCAN — prefetch once, pass price down, never fetch per symbol")

import bot

_orig = {
    "get_active_watchlist": bot.get_active_watchlist,
    "get_prediction_xgb": bot.get_prediction_xgb,
    "fetch_live_price": bot.fetch_live_price,
    "scan_watchlist": bot.scan_watchlist,
}

WATCH = [f"STK{i}" for i in range(66)]
_seen = {}
_batch_calls = []


def _fake_worker(symbol, live_price=None):
    _seen[symbol] = live_price
    return {"symbol": symbol, "signal": "HOLD", "confidence": 0.1,
            "model_source": "XGBoost"}


def _boom_live_price(symbol):
    raise AssertionError(f"fetch_live_price() called for {symbol} — fallback leaked")


def _boom_gbc():
    raise AssertionError("scan_watchlist() (GBC) ran — retired model must not be fed")


class _FakeProvider:
    _result = None

    def get_ltp_batch(self, symbols):
        _batch_calls.append(list(symbols))
        if callable(self._result):
            return self._result(symbols)
        return self._result


bot.get_active_watchlist = lambda: list(WATCH)
bot.get_prediction_xgb = _fake_worker
bot.fetch_live_price = _boom_live_price
bot.scan_watchlist = _boom_gbc
fmdp.FYERSMarketDataProvider = _FakeProvider

# Happy path: every symbol priced.
_FakeProvider._result = staticmethod(lambda syms: {s: 100.0 + i for i, s in enumerate(syms)})
_seen.clear()
_batch_calls.clear()
res = bot.scan_watchlist_xgb()

check("exactly one batch prefetch for the whole scan", len(_batch_calls) == 1,
      f"{len(_batch_calls)} call(s)")
check("prefetch asked for every active symbol",
      _batch_calls and sorted(_batch_calls[0]) == sorted(WATCH))
check("every worker received a prefetched price", len(_seen) == len(WATCH),
      f"{len(_seen)}/{len(WATCH)}")
check("prices forwarded verbatim",
      _seen.get("STK0") == 100.0 and _seen.get("STK65") == 165.0,
      f"STK0={_seen.get('STK0')} STK65={_seen.get('STK65')}")
check("no worker fell back to fetch_live_price", True, "boom-stub never raised")
check("scan returned a result per symbol", len(res) == len(WATCH), f"{len(res)}")
check("GBC scan never invoked", True, "boom-stub never raised")


# ── 3. Failure is surfaced, never silently downgraded ────────────────────
print("\n3. FAILURE — abort loudly instead of falling back")

def _expect_raise(label, result):
    _FakeProvider._result = staticmethod(result) if callable(result) else result
    _seen.clear()
    try:
        bot.scan_watchlist_xgb()
    except RuntimeError as e:
        check(label, True, f"raised: {str(e)[:60]}")
        check(f"{label}: no worker ran", not _seen, f"{len(_seen)} worker(s) ran")
        return
    except AssertionError:
        check(label, False, "fell back to a per-symbol fetch_live_price()")
        return
    check(label, False, "returned normally instead of raising")


_expect_raise("one symbol missing from batch",
              lambda syms: {s: 100.0 for s in syms if s != "STK7"})
_expect_raise("one symbol priced zero",
              lambda syms: {s: (0.0 if s == "STK3" else 100.0) for s in syms})
_expect_raise("one symbol priced negative",
              lambda syms: {s: (-5.0 if s == "STK9" else 100.0) for s in syms})
_expect_raise("one symbol priced None",
              lambda syms: {s: (None if s == "STK1" else 100.0) for s in syms})
_expect_raise("batch returns empty", lambda syms: {})
_expect_raise("batch returns None", lambda syms: None)


def _raising_batch(syms):
    raise RuntimeError("FYERS quotes failed for ['STK0', ...]: upstream 500")


_FakeProvider._result = staticmethod(_raising_batch)
_seen.clear()
try:
    bot.scan_watchlist_xgb()
    check("upstream batch error propagates", False, "swallowed")
except AssertionError:
    check("upstream batch error propagates", False, "fell back per-symbol")
except RuntimeError as e:
    check("upstream batch error propagates", "upstream 500" in str(e), str(e)[:60])
    check("upstream batch error: no worker ran", not _seen)

for k, v in _orig.items():
    setattr(bot, k, v)


# ── 4. get_prediction_xgb forwards the price it is given ─────────────────
print("\n4. FORWARDING — get_prediction_xgb -> get_prediction")

_fwd = {}
_orig_get_prediction = bot.get_prediction
_orig_xgb_predictor = bot._get_xgb_predictor
_orig_fetch5 = bot.fetch_5min_for_inference

import pandas as pd

bot.get_prediction = lambda symbol, **kw: _fwd.update({"symbol": symbol, **kw}) or {}
bot._get_xgb_predictor = lambda s, allow_train=True: object()
bot.fetch_5min_for_inference = lambda s, days=None: pd.DataFrame({"close": [1.0, 2.0, 3.0]})

bot.get_prediction_xgb("INFY", live_price=1234.5)
check("prefetched price forwarded", _fwd.get("live_price") == 1234.5, f"{_fwd.get('live_price')}")

_fwd.clear()
bot.get_prediction_xgb("INFY")
check("omitted price forwards as None (single-symbol callers unchanged)",
      _fwd.get("live_price") is None, f"{_fwd.get('live_price')}")

bot.get_prediction = _orig_get_prediction
bot._get_xgb_predictor = _orig_xgb_predictor
bot.fetch_5min_for_inference = _orig_fetch5


# ── 5. get_prediction itself: supplied price wins, absent price fetches ──
print("\n5. GET_PREDICTION — supplied price short-circuits the quote")

class _FakePredictor:
    def predict(self, df):
        return {"signal": "HOLD", "confidence": 0.5, "indicators": {"price": 11.0}}


_df = pd.DataFrame({"close": [10.0, 10.5, 11.0]})
_fetches = []


def _counting_fetch(symbol):
    _fetches.append(symbol)
    return 999.0


bot.fetch_live_price = _counting_fetch
bot.analyze_long_term_trend = lambda s, as_of=None: None
bot.get_model_trade_budget = lambda ms: 50000.0

_fetches.clear()
r = bot.get_prediction("INFY", ml_predictor=_FakePredictor(), ml_df=_df,
                       model_source="XGBoost", live_price=777.0)
check("no quote issued when a price is supplied", _fetches == [], f"{_fetches}")
check("supplied price used as the decision price",
      r.get("indicators", {}).get("price") == 777.0,
      f"{r.get('indicators', {}).get('price')}")

_fetches.clear()
r2 = bot.get_prediction("INFY", ml_predictor=_FakePredictor(), ml_df=_df,
                        model_source="XGBoost")
check("quote still issued when no price is supplied", _fetches == ["INFY"], f"{_fetches}")
check("fetched price used when none supplied",
      r2.get("indicators", {}).get("price") == 999.0,
      f"{r2.get('indicators', {}).get('price')}")

bot.fetch_live_price = _orig["fetch_live_price"]

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED ({len(_failures)}): " + ", ".join(_failures))
    sys.exit(1)
print("ALL BATCHING CHECKS PASSED")
