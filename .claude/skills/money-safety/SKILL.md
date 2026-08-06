---
name: money-safety
description: Audit the trading money paths for duplicate orders, paper-mode leaks, client-side trade decisions, and unguarded exits. Use before touching bot.py, fno_trader.py, paper_trader.py, trailing_stop.py, any /api/buy|sell|fno|intraday endpoint, or the scheduler's trade tasks — and whenever asked about paper mode, idempotency, double orders, real-vs-simulated trades, or "can this place a duplicate trade".
---

# Money-Path Safety Audit

Checks the Groww trading system for the ways it can lose real money. Every
check here caught a **real, verified bug in this repo** — these are not
hypotheticals.

The governing rule: **the server is the only authority on anything involving
money, and every money action must be safe to repeat.**

Report findings; do not fix without asking (`CLAUDE.md` requires confirmation,
and twice for deletions).

Severity: **CRITICAL** if it can place or duplicate a real exchange order,
**HIGH** if it corrupts the paper ledger or capital accounting, **MEDIUM**
otherwise.

---

## 1. Paper mode must fail CLOSED and cover every exchange call

Paper mode is the gate between simulation and real money. Two failure shapes:

**1a. A gate that fails open.** `is_paper_mode()` must return `True` (safe)
when it cannot reach the DB — never `False`.

```bash
sed -n "/def is_paper_mode/,/^def /p" bot.py
```
Judgement: the `except` branch must return `True`. Returning `False` on error
means a DB blip starts placing real orders.

**1b. An exchange call that bypasses the gate.** Find every broker call and
confirm each is behind a paper check.

```bash
grep -rn "place_order\|create_smart_order\|_groww_api\.\|groww\." --include="*.py" . \
  | grep -v archive | grep -vi "get_\|quote\|candle\|ltp\|positions_for_user\|holdings"
```
For each hit, walk **up** to the caller and confirm a paper check sits between
the entry point and the call.

> **Real bug this found:** `auto_trade()` called `place_gtt_stop_loss()`
> immediately after `place_buy()`. `place_buy` had a paper intercept;
> `place_gtt_stop_loss` did not. Paper mode placed a *real GTT sell order on
> the exchange*. Guard at the function itself, not the call site — that
> protects callers added later.

---

## 2. The client must never decide paper vs. real

A checkbox, a `localStorage` value, or a request-body flag is user-editable.
Any of them steering a money decision is a security bug.

```bash
grep -n "paper-mode\|paperMode\|isPaperMode\|is_paper" index.html
```
Judgement — a hit is a BUG if it:
- picks which endpoint to call (`isPaperMode ? '/api/x-paper' : '/api/x'`)
- sends `is_paper` in a request body
- gates whether an order request is sent at all

A hit is FINE if it only *displays* a mode the server reported.

Then confirm the server ignores any client claim:
```bash
grep -n "is_paper\|paper_mode" app.py | grep -i "request\|data.get\|json"
```
The server must read paper mode from config, never from the request.

---

## 3. Every order path must be safe to repeat

A trade request arrives twice for reasons unrelated to user intent: a
double-click, or the order reaching the broker while the **response** is lost,
so the client retries something that already succeeded.

```bash
grep -n "@idempotent" app.py                     # which routes are protected
grep -n '@app.route.*methods=\["POST"\]' app.py | grep -iE "buy|sell|order|trade|close|enter"
```
Judgement: every money-moving POST needs `@idempotent("<scope>")`. Compare the
two lists; anything in the second not in the first is unprotected.

Frontend side — every order control needs an in-flight guard AND a key:
```bash
grep -n "api('/api/\(buy\|sell\|fno/buy\|fno/sell\|intraday/enter-paper\)'" index.html
```
Each must use `withBusy(...)` and send an `Idempotency-Key` header.
`confirm()` is **not** a guard — after the user clicks OK the button is live
again for the whole request duration.

**Check `api()` arity while here.** `api(path, opts)` takes two args.
```bash
grep -nE "api\('[^']+',\s*'(POST|PUT|DELETE)'" index.html
```
Any hit passes a string where `fetch` wants an options object, so the request
silently downgrades to **GET** and the POST-only route 405s.

> **Real bug this found:** both intraday paper endpoints were called this way
> and had never worked.

---

## 4. Auto-exit loops must not machine-gun orders

`scheduler.py` runs trade tasks every **5 seconds**. Anything that decides to
exit from *broker position data* will re-decide before the previous fill is
reflected.

```bash
grep -n "_register(\"fno_auto_trade\|_register(\"cash_auto_trade\|_register(\"auto_close" scheduler.py
sed -n "/def _check_position_exits/,/^def /p" fno_trader.py | grep -n "place_fno_sell\|cooldown\|in_flight\|exiting"
```
Judgement: a sell inside a loop with no in-flight set, cooldown, or
exit-state marker is CRITICAL. Broker position data lags fills by seconds, so
the same position gets sold repeatedly.

Also check duplicate-entry guards built from broker positions:
```bash
grep -n "open_symbols\|_count_open_positions" bot.py fno_trader.py
```
In paper mode the broker reports **no positions**, so `symbol not in
open_symbols` is always true and the bot re-enters the same symbol every
cycle. The guard must union broker positions with open *paper* positions.

---

## 5. Capital ledger must not drift

```bash
grep -n "update_used_capital\|get_available_capital\|fno.used_capital" fno_trader.py
```
Judgement: check the read → order → write sequence. If capital is read before
the order and written after, two concurrent requests both pass the check
(TOCTOU). Also confirm the deploy and release paths are symmetric — deploying
`entry + charges` but releasing `sell_price × qty` drifts every round trip.

---

## 6. Silent failures on money paths

```bash
grep -rn -A2 "except" bot.py fno_trader.py paper_trader.py trailing_stop.py \
  | grep -B1 "pass$"
```
Judgement: on a money path, a swallowed exception is CRITICAL when it sits
between a paper-mode check and an order, or around a ledger update. The order
still goes out; only the bookkeeping is lost.

---

## 7. Session hygiene on trade paths

Trade functions run on long-lived scheduler threads that reuse one
`scoped_session`. A commit that fails without a rollback leaves the session in
an aborted transaction, and **every later trade on that thread also fails**.

```bash
grep -n -A6 "session.commit()" bot.py fno_trader.py | grep -B4 "except" | grep -v rollback
```
Judgement: every `except` around a trade commit needs `session.rollback()`,
and the `close()` belongs in a `finally`.

---

## Reporting

Group by severity, most severe first. For each: `file:line`, the concrete
failure scenario (inputs → wrong outcome), and whether real money can move.
State explicitly which checks passed clean — a short "no findings" per
category is useful signal.
