import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

TRACKER_FILE = os.path.join(os.path.dirname(__file__), "paper_trades.json")
CLOSED_TRADE_STATUSES = {"CLOSED", "HIT_TARGET", "HIT_SL"}
IST = timezone(timedelta(hours=5, minutes=30))


def load_tracker_trades(path: str = TRACKER_FILE) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as handle:
            data = json.load(handle)
            return data if isinstance(data, list) else []
    except Exception as exc:
        LOGGER.warning("Failed to read paper trade tracker file %s: %s", path, exc)
        return []


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt
    except Exception:
        return None


def _time_score_seconds(left: Any, right: Any) -> float:
    left_dt = _parse_dt(left)
    right_dt = _parse_dt(right)
    if not left_dt or not right_dt:
        return 999999.0
    return abs((left_dt - right_dt).total_seconds())


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _merge_non_null(base: Optional[Dict[str, Any]], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(base or {})
    for key, value in (overlay or {}).items():
        if value is not None:
            result[key] = value
    return result


def _normalize_status(value: Any) -> str:
    status = str(value or "OPEN").upper()
    return status if status else "OPEN"


def _tracker_side(trade: Dict[str, Any]) -> str:
    side = str(trade.get("side") or trade.get("signal") or "BUY").upper()
    return side or "BUY"


def _price_match(tracker_trade: Dict[str, Any], entry: Dict[str, Any]) -> bool:
    tracker_price = _as_float(tracker_trade.get("entry_price"))
    entry_price = _as_float(entry.get("entry_price"))
    if tracker_price is None or entry_price is None:
        return False
    tolerance = max(0.5, tracker_price * 0.0005)
    return abs(tracker_price - entry_price) <= tolerance


def _is_potential_tracker_match(tracker_trade: Dict[str, Any], entry: Dict[str, Any]) -> bool:
    if (entry.get("symbol") or "").upper() != (tracker_trade.get("symbol") or "").upper():
        return False
    if (entry.get("side") or entry.get("signal") or "").upper() != _tracker_side(tracker_trade):
        return False
    if _as_int(entry.get("quantity")) != _as_int(tracker_trade.get("quantity")):
        return False
    if not _price_match(tracker_trade, entry):
        return False
    return _time_score_seconds(tracker_trade.get("entry_time"), entry.get("entry_time")) <= 5.0


def _build_tracker_post_trade(trade: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    side = _tracker_side(trade)
    entry_price = _as_float(trade.get("entry_price"), 0.0) or 0.0
    exit_price = _as_float(trade.get("exit_price"), 0.0) or 0.0
    quantity = _as_int(trade.get("quantity"), 0)

    pnl_info = None
    if entry_price and exit_price and quantity:
        try:
            import costs

            if side == "SELL":
                pnl_info = costs.net_profit(exit_price, entry_price, quantity)
            else:
                pnl_info = costs.net_profit(entry_price, exit_price, quantity)
        except Exception:
            pnl_info = None

    existing = trade.get("post_trade")
    if isinstance(existing, dict) and existing:
        post = dict(existing)
        if post.get("exit_time") is None and trade.get("exit_time") is not None:
            post["exit_time"] = trade.get("exit_time")
        if post.get("exit_price") is None and trade.get("exit_price") is not None:
            post["exit_price"] = trade.get("exit_price")
        if post.get("move_pct") is None and trade.get("actual_profit_pct") is not None:
            post["move_pct"] = trade.get("actual_profit_pct")
        if pnl_info is not None:
            if post.get("gross_pnl") is None:
                post["gross_pnl"] = pnl_info["gross_profit"]
            if post.get("total_charges") is None:
                post["total_charges"] = pnl_info["total_charges"]
            if post.get("net_pnl") is None:
                post["net_pnl"] = pnl_info["net_profit"]
            if post.get("profitable") is None:
                post["profitable"] = pnl_info["net_profit"] > 0
        return post

    if trade.get("exit_price") is None:
        return None

    gross_pnl = _as_float(trade.get("gross_pnl"))
    net_pnl = _as_float(trade.get("net_pnl"))
    total_charges = _as_float(trade.get("total_charges"))

    if pnl_info is not None:
        if gross_pnl is None:
            gross_pnl = pnl_info["gross_profit"]
        if net_pnl is None:
            net_pnl = pnl_info["net_profit"]
        if total_charges is None:
            total_charges = pnl_info["total_charges"]
    else:
        if gross_pnl is None and entry_price and quantity:
            gross_pnl = (exit_price - entry_price) * quantity if side == "BUY" else (entry_price - exit_price) * quantity
        if net_pnl is None:
            net_pnl = gross_pnl
        if total_charges is None and gross_pnl is not None and net_pnl is not None:
            total_charges = gross_pnl - net_pnl

    duration_minutes = None
    entry_dt = _parse_dt(trade.get("entry_time"))
    exit_dt = _parse_dt(trade.get("exit_time"))
    if entry_dt and exit_dt:
        duration_minutes = round((exit_dt - entry_dt).total_seconds() / 60, 1)

    actual_profit_pct = _as_float(trade.get("actual_profit_pct"))

    return {
        "exit_time": trade.get("exit_time"),
        "exit_price": exit_price,
        "exit_reason": trade.get("exit_reason"),
        "duration_minutes": duration_minutes,
        "gross_pnl": round(gross_pnl, 2) if gross_pnl is not None else None,
        "net_pnl": round(net_pnl, 2) if net_pnl is not None else None,
        "total_charges": round(total_charges, 2) if total_charges is not None else None,
        "move_pct": actual_profit_pct,
        "profitable": (net_pnl is not None and net_pnl > 0),
    }


def _normalize_tracker_trade(tracker_trade: Dict[str, Any], matched_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    side = _tracker_side(tracker_trade)
    pre_trade = _merge_non_null(matched_entry.get("pre_trade") if matched_entry else None, tracker_trade.get("pre_trade"))
    post_trade = _merge_non_null(_build_tracker_post_trade(tracker_trade), matched_entry.get("post_trade") if matched_entry else None)

    entry_price = _as_float(tracker_trade.get("entry_price"))
    quantity = _as_int(tracker_trade.get("quantity"))
    exit_price = _as_float(tracker_trade.get("exit_price"), _as_float(matched_entry.get("exit_price")) if matched_entry else None)
    projected_exit = _as_float(
        tracker_trade.get("projected_exit"),
        _as_float(matched_entry.get("projected_exit")) if matched_entry else _as_float(pre_trade.get("target_price")),
    )
    stop_loss = _as_float(
        tracker_trade.get("stop_loss"),
        _as_float(matched_entry.get("stop_loss")) if matched_entry else _as_float(pre_trade.get("stop_loss_price")),
    )
    actual_profit_pct = _as_float(
        tracker_trade.get("actual_profit_pct"),
        _as_float(matched_entry.get("actual_profit_pct")) if matched_entry else _as_float(post_trade.get("move_pct")),
    )
    confidence = _as_float(
        tracker_trade.get("confidence"),
        _as_float(matched_entry.get("confidence")) if matched_entry else _as_float(pre_trade.get("confidence")),
    )
    breakeven_price = _as_float(
        tracker_trade.get("breakeven_price"),
        _as_float(matched_entry.get("breakeven_price")) if matched_entry else _as_float(pre_trade.get("breakeven_price")),
    )
    if breakeven_price is None:
        breakeven_price = _as_float(tracker_trade.get("cost_coverage_price"))

    entry_time = tracker_trade.get("entry_time") or (matched_entry.get("entry_time") if matched_entry else None)
    exit_time = tracker_trade.get("exit_time") or (matched_entry.get("exit_time") if matched_entry else None)

    if post_trade:
        if post_trade.get("exit_time") is None and exit_time is not None:
            post_trade["exit_time"] = exit_time
        if post_trade.get("exit_price") is None and exit_price is not None:
            post_trade["exit_price"] = exit_price
        if post_trade.get("move_pct") is None and actual_profit_pct is not None:
            post_trade["move_pct"] = actual_profit_pct

    if pre_trade:
        pre_trade.setdefault("signal", side)
        if confidence is not None:
            pre_trade.setdefault("confidence", confidence)
        if projected_exit is not None:
            pre_trade.setdefault("target_price", projected_exit)
        if stop_loss is not None:
            pre_trade.setdefault("stop_loss_price", stop_loss)
        if breakeven_price is not None:
            pre_trade.setdefault("breakeven_price", breakeven_price)

    return {
        "trade_id": tracker_trade.get("id") or tracker_trade.get("trade_id"),
        "status": _normalize_status(tracker_trade.get("status")),
        "symbol": (tracker_trade.get("symbol") or "").upper(),
        "side": side,
        "quantity": quantity,
        "trigger": tracker_trade.get("trigger") or (matched_entry.get("trigger") if matched_entry else "auto"),
        "is_paper": True,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "exit_reason": tracker_trade.get("exit_reason") or (matched_entry.get("exit_reason") if matched_entry else None),
        "signal": side,
        "confidence": confidence,
        "stop_loss": stop_loss,
        "projected_exit": projected_exit,
        "peak_pnl": _as_float(tracker_trade.get("peak_pnl"), _as_float(matched_entry.get("peak_pnl")) if matched_entry else None),
        "actual_profit_pct": actual_profit_pct,
        "breakeven_price": breakeven_price,
        "gross_pnl": _as_float(post_trade.get("gross_pnl")) if post_trade else None,
        "net_pnl": _as_float(post_trade.get("net_pnl")) if post_trade else None,
        "total_charges": _as_float(post_trade.get("total_charges")) if post_trade else None,
        "pre_trade": pre_trade,
        "post_trade": post_trade or None,
        "trailing_stop": tracker_trade.get("trailing_stop"),
        "entry_value": round((entry_price or 0.0) * quantity, 2),
        "intraday_candles": tracker_trade.get("intraday_candles") or (matched_entry.get("intraday_candles") if matched_entry else None),
    }


def _sort_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        list(entries),
        key=lambda entry: _parse_dt(entry.get("entry_time")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def build_canonical_trade_views(db_entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    db_entry_list = [dict(entry) for entry in db_entries]
    tracker_trades = load_tracker_trades()

    used_db_indexes = set()
    paper_entries: List[Dict[str, Any]] = []

    for tracker_trade in tracker_trades:
        tracker_id = tracker_trade.get("id") or tracker_trade.get("trade_id")
        matched_index = None
        matched_entry = None

        if tracker_id:
            for index, entry in enumerate(db_entry_list):
                if index in used_db_indexes:
                    continue
                if entry.get("trade_id") == tracker_id:
                    matched_index = index
                    matched_entry = entry
                    break

        if matched_entry is None:
            best_score: Optional[Tuple[float, int]] = None
            for index, entry in enumerate(db_entry_list):
                if index in used_db_indexes:
                    continue
                if not _is_potential_tracker_match(tracker_trade, entry):
                    continue

                score = (
                    _time_score_seconds(tracker_trade.get("entry_time"), entry.get("entry_time"))
                    + abs((_as_float(tracker_trade.get("entry_price"), 0.0) or 0.0) - (_as_float(entry.get("entry_price"), 0.0) or 0.0)) * 4
                    + (0.0 if entry.get("is_paper") else 1.0)
                )
                if best_score is None or score < best_score[0]:
                    best_score = (score, index)

            if best_score is not None:
                matched_index = best_score[1]
                matched_entry = db_entry_list[matched_index]

        if matched_index is not None:
            used_db_indexes.add(matched_index)

        paper_entries.append(_normalize_tracker_trade(tracker_trade, matched_entry))

    unmatched_paper_entries: List[Dict[str, Any]] = []
    actual_entries: List[Dict[str, Any]] = []

    for index, entry in enumerate(db_entry_list):
        if index in used_db_indexes:
            continue

        if any(_is_potential_tracker_match(tracker_trade, entry) for tracker_trade in tracker_trades):
            continue

        if entry.get("is_paper"):
            unmatched_paper_entries.append(entry)
        else:
            actual_entries.append(entry)

    paper_entries.extend(unmatched_paper_entries)

    paper_entries = _sort_entries(paper_entries)
    actual_entries = _sort_entries(actual_entries)
    all_entries = _sort_entries([*paper_entries, *actual_entries])

    return {
        "paper": paper_entries,
        "actual": actual_entries,
        "all": all_entries,
        "lookup": {entry.get("trade_id"): entry for entry in all_entries if entry.get("trade_id")},
    }
