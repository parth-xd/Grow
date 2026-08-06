"""
Indian equity trading cost calculator.
Accounts for all taxes and charges on NSE/BSE for CNC (delivery) and MIS (intraday).

Rates are loaded from the DB (config_settings table) and fall back to hardcoded defaults.
A scheduled task refreshes rates from known sources every 3 days.

Defaults as of FY 2025-26:
  - Brokerage:              Groww ₹20/order or 0.05% (whichever lower) for intraday;
                            ₹20/order flat for delivery
  - STT:                    0.1% on buy+sell (delivery), 0.025% on sell only (intraday)
  - Exchange Txn Charges:   NSE 0.00345%, BSE 0.00375%
  - SEBI Turnover Fee:      ₹10 per crore (0.0001%)
  - GST:                    18% on (brokerage + exchange charges + SEBI fee)
  - Stamp Duty:             0.015% on buy (delivery), 0.003% on buy (intraday)
  - DP Charges:             ₹15.93 per scrip on sell (delivery only)
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (fallback when DB unavailable) ─────────────────────────

_DEFAULTS = {
    "BROKERAGE_PER_ORDER": 20.0,
    "BROKERAGE_INTRADAY_PCT": 0.05,
    "STT_DELIVERY_PCT": 0.1,
    "STT_INTRADAY_SELL_PCT": 0.025,
    "EXCHANGE_TXN_NSE_PCT": 0.00345,
    "EXCHANGE_TXN_BSE_PCT": 0.00375,
    "SEBI_FEE_PCT": 0.0001,
    "GST_PCT": 18.0,
    "STAMP_DUTY_DELIVERY_PCT": 0.015,
    "STAMP_DUTY_INTRADAY_PCT": 0.003,
    "DP_CHARGES": 15.93,
}

# In-memory cache so we don't hit DB on every cost calc
_rate_cache = {}
_cache_loaded = False


def _load_rates():
    """Load trading cost rates from DB, falling back to hardcoded defaults."""
    global _rate_cache, _cache_loaded
    try:
        from db_manager import get_config
        for key, default in _DEFAULTS.items():
            val = get_config(f"cost.{key}", default=None)
            _rate_cache[key] = float(val) if val is not None else default
    except Exception:
        _rate_cache = dict(_DEFAULTS)
    _cache_loaded = True


def _get_rate(key):
    """Get a rate constant, loading from DB on first call."""
    if not _cache_loaded:
        _load_rates()
    return _rate_cache.get(key, _DEFAULTS.get(key, 0))


def reload_rates():
    """Force reload rates from DB (called by scheduler after update)."""
    global _cache_loaded
    _cache_loaded = False
    _load_rates()


def seed_cost_rates():
    """Seed default cost rates into DB if not already present."""
    try:
        from db_manager import get_config, set_config
        descriptions = {
            "BROKERAGE_PER_ORDER": "Flat brokerage per order (₹)",
            "BROKERAGE_INTRADAY_PCT": "Intraday brokerage % (capped at flat rate)",
            "STT_DELIVERY_PCT": "STT % on buy+sell delivery turnover",
            "STT_INTRADAY_SELL_PCT": "STT % on sell-side intraday turnover",
            "EXCHANGE_TXN_NSE_PCT": "NSE exchange transaction charge %",
            "EXCHANGE_TXN_BSE_PCT": "BSE exchange transaction charge %",
            "SEBI_FEE_PCT": "SEBI turnover fee %",
            "GST_PCT": "GST % on brokerage + exchange + SEBI",
            "STAMP_DUTY_DELIVERY_PCT": "Stamp duty % on buy-side delivery",
            "STAMP_DUTY_INTRADAY_PCT": "Stamp duty % on buy-side intraday",
            "DP_CHARGES": "DP charges per scrip on sell (₹)",
        }
        for key, default in _DEFAULTS.items():
            existing = get_config(f"cost.{key}")
            if existing is None:
                set_config(f"cost.{key}", str(default), descriptions.get(key, ""))
        logger.info("✓ Cost rates seeded in DB")
    except Exception as e:
        logger.warning("Failed to seed cost rates: %s", e)


def update_cost_rates():
    """
    AUTOMATED COST UPDATE SYSTEM — Main orchestrator

    Complete cost update workflow:
    1. Scrape latest costs from Groww
    2. Validate costs
    3. Compare with existing values
    4. Update database with audit trail
    5. Send notifications
    6. Reload in-memory cache

    Called by scheduler every 45 days.
    Also called manually via API for verification.

    Returns:
        {
            "success": bool,
            "timestamp": ISO datetime,
            "scrape": {...},
            "update": {...},
            "notifications": {...},
            "summary": {...}
        }
    """
    try:
        import json
        from datetime import datetime
        from cost_scraper import scrape
        from cost_updater import update_costs
        from cost_notifications import send_cost_change_notification

        logger.info("╔════════════════════════════════════════════════════════════════════╗")
        logger.info("║                  COST UPDATE WORKFLOW STARTED                       ║")
        logger.info("╚════════════════════════════════════════════════════════════════════╝")

        result = {
            "success": False,
            "timestamp": datetime.utcnow().isoformat(),
            "scrape": None,
            "update": None,
            "notifications": None,
            "summary": {
                "costs_checked": 0,
                "costs_updated": 0,
                "costs_unchanged": 0,
                "suspicious_changes": [],
                "total_errors": 0,
            }
        }

        # Step 1: SCRAPE
        logger.info("\n[1/4] SCRAPING COSTS FROM GROWW...")
        scrape_result = scrape()
        result["scrape"] = scrape_result

        if not scrape_result["success"]:
            logger.error(f"Scrape failed: {scrape_result.get('error')}")
            result["summary"]["total_errors"] += 1
            return result

        new_costs = scrape_result.get("charges", {})
        logger.info(f"✓ Scraped {len(new_costs)} costs")

        # Step 2: COMPARE
        logger.info("\n[2/4] COMPARING WITH EXISTING COSTS...")
        comparison = scrape_result.get("comparison")

        if comparison:
            costs_changed = comparison.get("changed", False)
            change_count = comparison.get("change_count", 0)
            result["summary"]["costs_checked"] = len(new_costs)
            result["summary"]["costs_unchanged"] = len(new_costs) - change_count
            result["summary"]["costs_updated"] = change_count

            if costs_changed:
                logger.warning(f"⚠ {change_count} costs differ from existing values")
                suspicious = [c["key"] for c in comparison.get("changes", []) if c.get("suspicious")]
                result["summary"]["suspicious_changes"] = suspicious
                if suspicious:
                    logger.warning(f"🚨 {len(suspicious)} suspicious changes flagged for review")
            else:
                logger.info("✓ All costs match existing values")
        else:
            result["summary"]["costs_checked"] = len(new_costs)

        # Step 3: UPDATE DATABASE
        logger.info("\n[3/4] UPDATING DATABASE...")
        changes = scrape_result.get("comparison", {}).get("changes", []) if scrape_result.get("comparison") else None
        update_result = update_costs(new_costs, changes=changes)
        result["update"] = update_result

        if not update_result["success"]:
            result["summary"]["total_errors"] += update_result.get("failed_count", 0)
            logger.error("Database update had errors")
        else:
            logger.info(f"✓ Database updated successfully")

        # Step 4: SEND NOTIFICATIONS & RELOAD CACHE
        logger.info("\n[4/4] SENDING NOTIFICATIONS & RELOADING CACHE...")
        try:
            notif_result = send_cost_change_notification(update_result, scrape_result)
            result["notifications"] = notif_result
            logger.info("✓ Notifications sent")
        except Exception as e:
            logger.warning(f"Notification sending failed: {e}")
            result["notifications"] = {"error": str(e)}

        # Reload in-memory cache
        reload_rates()
        logger.info("✓ In-memory cache reloaded")

        # Final summary
        result["success"] = result["summary"]["total_errors"] == 0
        logger.info("\n" + "=" * 70)
        logger.info("COST UPDATE WORKFLOW SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Status: {'✅ SUCCESS' if result['success'] else '⚠️ PARTIAL SUCCESS'}")
        logger.info(f"Costs Checked: {result['summary']['costs_checked']}")
        logger.info(f"Costs Updated: {result['summary']['costs_updated']}")
        logger.info(f"Costs Unchanged: {result['summary']['costs_unchanged']}")
        if result["summary"]["suspicious_changes"]:
            logger.warning(f"Suspicious Changes: {len(result['summary']['suspicious_changes'])}")
            for key in result["summary"]["suspicious_changes"]:
                logger.warning(f"  - {key}")
        if result["summary"]["total_errors"] > 0:
            logger.warning(f"Errors: {result['summary']['total_errors']}")
        logger.info("=" * 70 + "\n")

        return result

    except Exception as e:
        logger.error(f"Cost update workflow failed: {e}", exc_info=True)
        # Fallback to old simple method if new system fails
        try:
            import requests
            from bs4 import BeautifulSoup
            from db_manager import get_config, set_config

            resp = requests.get(
                "https://groww.in/charges",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.info("Cost rates page returned %d, keeping existing rates", resp.status_code)
                return

            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text().lower()

            updates = {}
            import re
            stt_match = re.search(r"stt[^\d]*delivery[^\d]*([\d.]+)\s*%", text)
            if stt_match:
                updates["STT_DELIVERY_PCT"] = float(stt_match.group(1))

            stt_intra = re.search(r"stt[^\d]*intraday[^\d]*([\d.]+)\s*%", text)
            if stt_intra:
                updates["STT_INTRADAY_SELL_PCT"] = float(stt_intra.group(1))

            stamp_del = re.search(r"stamp[^\d]*delivery[^\d]*([\d.]+)\s*%", text)
            if stamp_del:
                updates["STAMP_DUTY_DELIVERY_PCT"] = float(stamp_del.group(1))

            dp_match = re.search(r"dp\s*charges?[^\d]*([\d.]+)", text)
            if dp_match:
                val = float(dp_match.group(1))
                if 5 < val < 50:
                    updates["DP_CHARGES"] = val

            if updates:
                for key, val in updates.items():
                    old = get_config(f"cost.{key}")
                    if old is not None and abs(float(old) - val) > 0.0001:
                        set_config(f"cost.{key}", str(val))
                        logger.info("Cost rate updated: %s = %s (was %s)", key, val, old)
                reload_rates()
                logger.info("✓ Cost rates checked (fallback), %d updated", len(updates))
            else:
                logger.info("Cost rates checked (fallback), no changes detected")

        except ImportError:
            logger.debug("beautifulsoup4 not available, skipping cost rate scraping")
        except Exception as fallback_error:
            logger.warning("Fallback cost rate update also failed: %s", fallback_error)


@dataclass
class TradeCost:
    """Breakdown of all charges for a round-trip trade (buy + sell)."""
    buy_value: float
    sell_value: float
    brokerage: float
    stt: float
    exchange_txn: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    dp_charges: float

    @property
    def total(self) -> float:
        return (self.brokerage + self.stt + self.exchange_txn +
                self.sebi_fee + self.gst + self.stamp_duty + self.dp_charges)

    @property
    def total_pct(self) -> float:
        """Total cost as a % of buy value."""
        return (self.total / self.buy_value * 100) if self.buy_value else 0

    @property
    def breakeven_pct(self) -> float:
        """Minimum price move % needed to break even after all costs."""
        return self.total_pct

    def to_dict(self) -> dict:
        return {
            "buy_value": round(self.buy_value, 2),
            "sell_value": round(self.sell_value, 2),
            "brokerage": round(self.brokerage, 2),
            "stt": round(self.stt, 2),
            "exchange_txn": round(self.exchange_txn, 2),
            "sebi_fee": round(self.sebi_fee, 2),
            "gst": round(self.gst, 2),
            "stamp_duty": round(self.stamp_duty, 2),
            "dp_charges": round(self.dp_charges, 2),
            "total": round(self.total, 2),
            "total_pct": round(self.total_pct, 4),
            "breakeven_pct": round(self.breakeven_pct, 4),
        }


def calc_brokerage(turnover: float, is_intraday: bool) -> float:
    if is_intraday:
        return min(_get_rate("BROKERAGE_PER_ORDER"), turnover * _get_rate("BROKERAGE_INTRADAY_PCT") / 100)
    return _get_rate("BROKERAGE_PER_ORDER")


def calculate_costs(
    price: float,
    quantity: int,
    sell_price: float = None,
    product: str = "CNC",
    exchange: str = "NSE",
) -> TradeCost:
    """
    Calculate full round-trip (buy + sell) trading costs.
    If sell_price is None, assumes sell at same price (breakeven calc).
    """
    is_delivery = product.upper() == "CNC"
    is_intraday = not is_delivery

    if sell_price is None:
        sell_price = price

    buy_value = price * quantity
    sell_value = sell_price * quantity
    turnover = buy_value + sell_value

    # Brokerage: per order for buy + sell
    brokerage_buy = calc_brokerage(buy_value, is_intraday)
    brokerage_sell = calc_brokerage(sell_value, is_intraday)
    brokerage = brokerage_buy + brokerage_sell

    # STT
    if is_delivery:
        stt = turnover * _get_rate("STT_DELIVERY_PCT") / 100
    else:
        stt = sell_value * _get_rate("STT_INTRADAY_SELL_PCT") / 100

    # Exchange transaction charges
    exc_rate = _get_rate("EXCHANGE_TXN_NSE_PCT") if exchange.upper() == "NSE" else _get_rate("EXCHANGE_TXN_BSE_PCT")
    exchange_txn = turnover * exc_rate / 100

    # SEBI turnover fee
    sebi_fee = turnover * _get_rate("SEBI_FEE_PCT") / 100

    # GST on brokerage + exchange charges + SEBI fee
    gst = (brokerage + exchange_txn + sebi_fee) * _get_rate("GST_PCT") / 100

    # Stamp duty (on buy side only)
    if is_delivery:
        stamp_duty = buy_value * _get_rate("STAMP_DUTY_DELIVERY_PCT") / 100
    else:
        stamp_duty = buy_value * _get_rate("STAMP_DUTY_INTRADAY_PCT") / 100

    # DP charges (delivery sell only)
    dp = _get_rate("DP_CHARGES") if is_delivery else 0.0

    return TradeCost(
        buy_value=buy_value,
        sell_value=sell_value,
        brokerage=brokerage,
        stt=stt,
        exchange_txn=exchange_txn,
        sebi_fee=sebi_fee,
        gst=gst,
        stamp_duty=stamp_duty,
        dp_charges=dp,
    )


def min_profitable_move(price: float, quantity: int, product: str = "CNC", exchange: str = "NSE") -> dict:
    """
    Calculate the minimum price increase needed to be profitable after all costs.
    Returns breakeven price and required % move.
    """
    costs = calculate_costs(price, quantity, sell_price=price, product=product, exchange=exchange)
    # Profit must exceed total costs: (sell - buy) * qty > total_cost
    # sell > buy + total_cost / qty
    min_move_per_share = costs.total / quantity
    breakeven_price = price + min_move_per_share

    return {
        "buy_price": round(price, 2),
        "breakeven_sell_price": round(breakeven_price, 2),
        "min_move_rupees": round(min_move_per_share, 2),
        "min_move_pct": round(min_move_per_share / price * 100, 4),
        "costs": costs.to_dict(),
    }


def net_profit(buy_price: float, sell_price: float, quantity: int,
               product: str = "CNC", exchange: str = "NSE") -> dict:
    """Calculate net profit/loss after all charges."""
    costs = calculate_costs(buy_price, quantity, sell_price=sell_price,
                            product=product, exchange=exchange)
    gross = (sell_price - buy_price) * quantity
    net = gross - costs.total

    return {
        "gross_profit": round(gross, 2),
        "total_charges": round(costs.total, 2),
        "net_profit": round(net, 2),
        "profitable": net > 0,
        "costs": costs.to_dict(),
    }
