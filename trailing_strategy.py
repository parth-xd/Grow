"""
Single unified trailing-exit strategy.

Merges the good logic already proven in this codebase with the reprieve rule:

  KEPT from trailing_stop.py CHECK 2
    - arm at max(breakeven_pct * 1.2, 0.20)          [SIEMENS incident]
    - give-back tiers as MULTIPLES OF BREAKEVEN      [size-aware]
    - give-back capped at half the peak              [cannot hand back >50%]
    - breakeven stamped at ENTRY, not recomputed
  KEPT from paper_trader.update_trailing_stop
    - stop ratchets in the profit direction only
    - percentage-based, never an absolute rupee buffer  [LT bid-ask incident]
  NEW
    - every stop clamped to the TRUE breakeven price, so a position that has
      covered its costs can never be made to hand them back
    - one model-confidence reprieve to a hard floor, then unconditional exit

Deliberately NOT carried over: PEAK_EROSION_60. It closed at 60% give-back,
but the half-peak cap already closes at 50%, so it can never fire first — it
is strictly dominated and would be dead code.

Clamping uses breakeven_price, NOT cost_coverage_price: the latter is a
hardcoded 0.06% (paper_trader.py:82) while MARUTI's real breakeven was
0.377%, so clamping there would still exit at -Rs130.

PURE: no file, DB or network I/O. evaluate() returns a decision plus the state
to persist; the caller owns all writes. That is what makes it testable without
touching live trading records.
"""
from typing import Any, Callable, Dict, Optional

DEFAULTS = {
    "trail.confidence_min": 0.60,
    # RULE 2: once peak profit reaches this many rupees, give-back is capped
    # in RUPEES rather than percent. Measured GROSS (price move x quantity).
    # On MARUTI gross peak was Rs417 (triggers) while net was Rs262 (would
    # not) - flip this key to change which side of that line the rule sits on.
    "trail.peak_profit_trigger_rs": 300.0,
    "trail.max_giveback_rs": 100.0,
    # RULE 3: at or above this move from entry the trade is a BIG WINNER and
    # jumps straight to the tightest existing tier.
    "trail.big_winner_pct": 1.5,
}
ACTION_HOLD, ACTION_CLOSE = "HOLD", "CLOSE"


def _tier_giveback(peak_pnl: float, be: float, entry: float = 0.0,
                   qty: int = 0, cfg: Optional[Dict[str, float]] = None) -> float:
    """
    Give-back %, as the TIGHTEST of every applicable cap.

    Order of tightening, loosest first:
      1. tier          - multiples of breakeven (size-aware, pre-existing)
      2. BIG WINNER    - at/above big_winner_pct from entry, jump straight to
                         the tightest existing tier (0.5%)                [R3]
      3. half-peak cap - never hand back more than 50% of the peak (pre-existing)
      4. rupee cap     - once peak profit >= peak_profit_trigger_rs, give back
                         no more than max_giveback_rs                     [R2]

    Every cap only ever TIGHTENS, so they compose without ordering hazards.
    """
    cfg = cfg or dict(DEFAULTS)

    # RULE 3 — a big winner skips the ladder and takes the tightest tier.
    if peak_pnl >= cfg["trail.big_winner_pct"]:
        tier = 0.5
    elif peak_pnl >= be * 4:
        tier = 0.5
    elif peak_pnl >= be * 2.5:
        tier = 0.75
    else:
        tier = 1.0

    give = min(tier, peak_pnl * 0.5)          # half-peak cap (pre-existing)

    # RULE 2 — rupee cap. Needs quantity, since a % give-back on 3 shares and
    # on 300 shares are wildly different amounts of money. Peak profit is GROSS
    # (price move x qty); charges are not deducted. On MARUTI: peak profit
    # Rs417 >= Rs300, so give-back is capped at Rs100 = Rs33.33/share =
    # 0.2435%, which is tighter than both the 0.75% tier and the 0.508%
    # half-peak cap, and therefore binds.
    if entry > 0 and qty > 0:
        peak_profit_rs = (peak_pnl / 100.0) * entry * qty
        if peak_profit_rs >= cfg["trail.peak_profit_trigger_rs"]:
            rupee_cap_pct = (cfg["trail.max_giveback_rs"] / qty) / entry * 100.0
            give = min(give, rupee_cap_pct)

    return give


def evaluate(trade: Dict[str, Any], current_price: float,
             confidence_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
             cfg: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    cfg = cfg or dict(DEFAULTS)
    side = (trade.get("signal") or trade.get("side") or "BUY").upper()
    entry = float(trade.get("entry_price") or 0)
    state: Dict[str, Any] = {}
    if entry <= 0 or not current_price:
        return {"action": ACTION_HOLD, "reason": "no valid price", "state": state}
    long = side == "BUY"

    be = float(trade.get("breakeven_pct") or 0) or 0.20
    be_px = float(trade.get("breakeven_price") or (entry * (1 + be / 100)))

    # ── hard stop-loss: absolute, checked first, never overridden ────────────
    hsl = trade.get("stop_loss")
    if hsl and ((long and current_price <= hsl) or (not long and current_price >= hsl)):
        return {"action": ACTION_CLOSE,
                "reason": f"HARD_STOP_LOSS ({current_price:.2f} vs {hsl:.2f})", "state": state}

    # ── ratchet the peak ─────────────────────────────────────────────────────
    pk = "highest_price_reached" if long else "lowest_price_reached"
    prev = trade.get(pk)
    peak = current_price if prev is None else (max(prev, current_price) if long else min(prev, current_price))
    state[pk] = peak
    peak_pnl = ((peak - entry) / entry * 100) if long else ((entry - peak) / entry * 100)
    state["peak_pnl"] = peak_pnl

    if (long and current_price >= be_px) or (not long and current_price <= be_px):
        state["has_covered_costs"] = True

    # ── arm ──────────────────────────────────────────────────────────────────
    arm_at = max(be * 1.2, 0.20)
    if peak_pnl < arm_at:
        return {"action": ACTION_HOLD,
                "reason": f"unarmed: peak +{peak_pnl:.3f}% < {arm_at:.3f}%", "state": state}

    # ── soft stop: tiered, half-peak capped, clamped to breakeven, ratcheting ─
    give = _tier_giveback(peak_pnl, be, entry, int(trade.get("quantity") or 0), cfg)
    soft = entry * (1 + (peak_pnl - give) / 100) if long else entry * (1 - (peak_pnl - give) / 100)
    soft = max(soft, be_px) if long else min(soft, be_px)
    prev_soft = trade.get("trailing_stop")
    if prev_soft is not None:
        soft = max(soft, prev_soft) if long else min(soft, prev_soft)
    state["trailing_stop"] = round(soft, 2)

    # ── existing hard floor is absolute ──────────────────────────────────────
    hf = trade.get("hard_floor")
    if hf is not None:
        if (long and current_price <= hf) or (not long and current_price >= hf):
            return {"action": ACTION_CLOSE,
                    "reason": f"HARD_FLOOR_HIT ({current_price:.2f} vs {hf:.2f} | peak {peak:.2f})",
                    "state": state}
        if (long and current_price > soft) or (not long and current_price < soft):
            state["hard_floor"] = None          # recovered: reprieve spent, not owed
        return {"action": ACTION_HOLD, "reason": f"in reprieve, floor {hf:.2f}", "state": state}

    # ── soft stop touched -> consult model ONCE ──────────────────────────────
    if not ((long and current_price <= soft) or (not long and current_price >= soft)):
        return {"action": ACTION_HOLD,
                "reason": f"trailing {soft:.2f} (peak {peak:.2f}, give-back {give:.3f}%)", "state": state}

    conf = sig = None
    if confidence_fn is not None:
        try:
            p = confidence_fn(trade.get("symbol")) or {}
            conf, sig = float(p.get("confidence") or 0), (p.get("signal") or "").upper()
        except Exception:
            conf = sig = None

    if conf is not None and sig == ("BUY" if long else "SELL") and conf >= cfg["trail.confidence_min"]:
        floor = soft * (1 - give / 100) if long else soft * (1 + give / 100)
        floor = max(floor, be_px) if long else min(floor, be_px)
        # RULE 2 outranks the reprieve where they conflict: the floor may not
        # push total give-back past max_giveback_rs. Consequence, stated
        # plainly rather than engineered around - once peak profit clears the
        # rupee trigger there is no room left below the soft stop, so the
        # reprieve becomes INERT and the trade simply closes at the soft stop.
        _q = int(trade.get("quantity") or 0)
        if _q > 0:
            _peak_rs = (peak_pnl / 100.0) * entry * _q
            if _peak_rs >= cfg["trail.peak_profit_trigger_rs"]:
                _cap_px = peak - (cfg["trail.max_giveback_rs"] / _q) if long else \
                          peak + (cfg["trail.max_giveback_rs"] / _q)
                floor = max(floor, _cap_px) if long else min(floor, _cap_px)
                # Epsilon: floor and soft can land within floating-point noise
                # of each other (measured 13792.6667 vs 13792.6670 on MARUTI),
                # which made a genuinely inert reprieve report as a HARD_FLOOR
                # hit one tick later. One paisa is below tick size, so this
                # cannot mask a real gap.
                _eps = 0.01
                if (long and floor >= soft - _eps) or (not long and floor <= soft + _eps):
                    return {"action": ACTION_CLOSE,
                            "reason": (f"TRAILING_STOP ({current_price:.2f} vs {soft:.2f} | "
                                       f"reprieve inert: Rs{cfg['trail.max_giveback_rs']:.0f} "
                                       f"give-back cap leaves no room)"),
                            "state": state}
        state["hard_floor"] = round(floor, 2)
        return {"action": ACTION_HOLD,
                "reason": f"REPRIEVE (model {sig} @ {conf:.0%}) floor {floor:.2f}", "state": state}

    why = "model unavailable" if conf is None else f"model {sig or 'n/a'} @ {conf:.0%}"
    return {"action": ACTION_CLOSE,
            "reason": f"TRAILING_STOP ({current_price:.2f} vs {soft:.2f} | peak +{peak_pnl:.2f}% | {why})",
            "state": state}


def build_trade(entry_price, quantity, side="BUY", stop_loss=None, symbol=""):
    """
    Construct the state dict evaluate() expects, with breakeven priced for the
    REAL quantity (fixed brokerage/DP do not scale, so breakeven is
    size-dependent). Shared by the live path and the backtesters so a backtest
    can never diverge from what actually trades.

    RULE 1: the initial hard stop is capped at MAX_CASH_SL_PCT from entry.
    """
    from config import MAX_CASH_SL_PCT
    long = str(side).upper() == "BUY"
    try:
        from trailing_stop import breakeven_pct_for
        be_pct = float(breakeven_pct_for(entry_price, quantity))
    except Exception:
        be_pct = 0.20
    be_px = entry_price * (1 + be_pct / 100) if long else entry_price * (1 - be_pct / 100)
    cap = entry_price * (1 - MAX_CASH_SL_PCT / 100) if long else entry_price * (1 + MAX_CASH_SL_PCT / 100)
    sl = cap if stop_loss is None else (max(stop_loss, cap) if long else min(stop_loss, cap))
    return {"symbol": symbol, "signal": "BUY" if long else "SELL",
            "entry_price": float(entry_price), "quantity": int(quantity),
            "breakeven_pct": round(be_pct, 4), "breakeven_price": round(be_px, 2),
            "stop_loss": round(sl, 2)}
