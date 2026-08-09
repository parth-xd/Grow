"""
One-shot check: run this right after connecting a new Groww API
subscription, to see in one command whether it actually unlocked live
market data — and specifically whether TATAMOTORS resolves.

Background (2026-08-09): the token in .env at the time this was written had
role "order-basic,non_trading-basic,order_read_only-basic" — order
placement/read only, no live-quote scope at all. Every fetch_live_price()
call failed with "Access forbidden", for every symbol tested, including
ones known to be actively trading (RELIANCE). That masked the real
question: whether "TATAMOTORS" (retired in Tata Motors' 2025 demerger into
TMPV/TMCV) is a symbol Groww's instrument master still recognizes.

This script separates those two questions by checking known-good control
symbols alongside TATAMOTORS. Read-only — fetch_live_price() is a quote
lookup, no order is placed.

Run:
    .venv/bin/python check_groww_market_data.py
"""
import base64
import json
import os

from dotenv import load_dotenv

load_dotenv(override=True)


def decode_token_role():
    tok = os.getenv("GROWW_ACCESS_TOKEN", "")
    parts = tok.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
        sub = json.loads(data["sub"])
        return sub.get("role")
    except Exception:
        return None


def check_symbol(bot, symbol):
    try:
        price = bot.fetch_live_price(symbol)
        return {"symbol": symbol, "ok": True, "price": price, "error": None}
    except Exception as e:
        return {"symbol": symbol, "ok": False, "price": None, "error": f"{type(e).__name__}: {e}"}


def main():
    print("=== Token scope ===")
    role = decode_token_role()
    print(f"  role: {role or '(could not decode)'}")
    if role and "order-basic" in role and "market" not in role.lower() and "quote" not in role.lower():
        print("  -> looks like the SAME order-only scope as before. If so, the results")
        print("     below will fail the same way regardless of TATAMOTORS specifically.")
    print()

    import bot  # deferred: prints "Ready to Groww!" and needs GROWW_API_KEY/SECRET set

    print("=== Live quote checks (read-only, no orders placed) ===")
    controls = ["RELIANCE", "TCS"]
    target = "TATAMOTORS"
    successors = ["TMCV", "TMPV"]

    results = {s: check_symbol(bot, s) for s in controls + [target] + successors}
    for s, r in results.items():
        status = f"₹{r['price']}" if r["ok"] else r["error"]
        print(f"  {s:<12} {'OK  ' if r['ok'] else 'FAIL'}  {status}")

    print()
    print("=== Verdict ===")
    controls_ok = all(results[s]["ok"] for s in controls)
    target_ok = results[target]["ok"]

    if not controls_ok:
        print("  Controls (RELIANCE/TCS) still fail -> market-data scope is still")
        print("  missing. The new subscription didn't add it, or it needs activating")
        print("  separately in Groww's own dashboard. TATAMOTORS's result below isn't")
        print("  meaningful yet — nothing can resolve until the controls pass.")
    elif target_ok:
        print("  Controls pass AND TATAMOTORS resolves -> it was purely the scope.")
        print("  scheduler.py's Phase 1 (Groww live-update) will now succeed for it")
        print("  going forward; no further action needed.")
    else:
        print("  Controls pass but TATAMOTORS fails -> scope is fine, the symbol")
        print(f"  itself doesn't resolve. Error was: {results[target]['error']}")
        print("  This confirms the ticker is genuinely gone from Groww too, matching")
        print("  the 2025 demerger (Tata Motors -> TMPV / TMCV) — not a bug, and not")
        print("  fixable by reconnecting. Check the TMCV/TMPV rows above: if either")
        print("  resolves, that's the successor entity you'd add as a NEW watchlist")
        print("  symbol if you want to keep tracking it — a deliberate choice, not")
        print("  an automatic replacement for the old TATAMOTORS entry.")


if __name__ == "__main__":
    main()
