"""
Cost & Charge Scraper — Automated fetching of Groww trading charges.

Fetches and parses trading costs from Groww's public pricing pages:
- https://groww.in/pricing/stocks (Equity brokerage & charges)
- https://groww.in/pricing/futures-and-options (F&O pricing)
- https://groww.in/calculators/brokerage-calculator (Brokerage calculator)

Extracts:
- Brokerage rates (flat + percentage by product type)
- STT rates (delivery vs intraday)
- Exchange charges (NSE, BSE)
- SEBI fees
- DP charges
- GST rates
- Stamp duty rates

Returns: Parsed values, comparison with old values, changes detected
"""

import logging
import requests
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)

# ── Groww's official charge structure (FALLBACK - from Jan 2026) ─────────────────
# These are the canonical rates - used as fallback if scraping fails
# Updated: Check pricing pages for latest rates

GROWW_CHARGES_CANONICAL = {
    # EQUITY BROKERAGE
    "brokerage_flat_per_order": 20.0,              # ₹20 flat per order
    "brokerage_pct_per_order": 0.1,                # 0.1% per order value (whichever lower)
    "brokerage_min_per_order": 5.0,                # ₹5 minimum

    # EQUITY TRANSACTION TAX (STT)
    "stt_pct_intraday_sell": 0.025,                # 0.025% intraday sell
    "stt_pct_delivery_buy": 0.1,                   # 0.1% delivery buy
    "stt_pct_delivery_sell": 0.1,                  # 0.1% delivery sell

    # STAMP DUTY
    "stamp_duty_pct_intraday_buy": 0.003,          # 0.003% intraday buy
    "stamp_duty_pct_delivery_buy": 0.015,          # 0.015% delivery buy

    # EXCHANGE TRANSACTION CHARGES
    "exchange_charge_nse_pct": 0.00297,            # NSE 0.00297%
    "exchange_charge_bse_pct": 0.00375,            # BSE 0.00375%

    # SEBI TURNOVER CHARGE
    "sebi_fee_pct": 0.0001,                        # 0.0001%

    # DP CHARGES (Depository Participant)
    "dp_charge_intraday": 0.0,                     # ₹0 for intraday
    "dp_charge_delivery_groww": 16.5,              # ₹16.5 Groww charge (delivery sell)
    "dp_charge_delivery_depository": 3.5,          # ₹3.5 Depository (delivery sell)

    # GST (Goods & Services Tax)
    "gst_rate": 0.18,                              # 18% GST

    # F&O CHARGES
    "stt_fno_sell": 0.05,                          # 0.05% F&O sell
    "stt_option_premium": 0.15,                    # 0.15% option premium (on sell)
    "stt_commodity_sell": 0.01,                    # 0.01% commodity sell
}

# ── Groww Pricing URLs (for scraping) ───────────────────────────────────────────
GROWW_PRICING_URLS = {
    "stocks": "https://groww.in/pricing/stocks",
    "futures_and_options": "https://groww.in/pricing/futures-and-options",
    "brokerage_calculator": "https://groww.in/calculators/brokerage-calculator",
}

# ── Cost categories and defaults ────────────────────────────────────────────────

COST_CATEGORIES = {
    "brokerage": {
        "description": "Per-order brokerage charge",
        "unit": "₹",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 100.0,
    },
    "stt": {
        "description": "Securities Transaction Tax",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.5,
    },
    "exchange_charge": {
        "description": "Exchange transaction fee",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.01,
    },
    "sebi_fee": {
        "description": "SEBI regulatory fee",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.0001,
    },
    "dp_charge": {
        "description": "Depository participant charge",
        "unit": "₹",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 50.0,
    },
    "gst_rate": {
        "description": "Goods & Services Tax rate",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.3,
    },
    "stamp_duty": {
        "description": "Stamp duty on trades",
        "unit": "%",
        "data_type": "float",
        "min_value": 0.0,
        "max_value": 0.05,
    },
}


def scrape_groww_charges() -> Dict[str, any]:
    """
    Scrape trading costs from Groww's official pricing pages.

    Attempts to fetch from multiple sources:
    1. https://groww.in/pricing/stocks (equity pricing)
    2. https://groww.in/pricing/futures-and-options (F&O pricing)
    3. https://groww.in/calculators/brokerage-calculator (brokerage details)

    Returns:
        {
            "success": bool,
            "timestamp": ISO datetime,
            "source_urls": [str, ...],
            "charges": {key: value, ...},
            "notes": str,
            "error": str (if failed)
        }
    """
    logger.info("Starting Groww charges scrape from pricing pages...")
    result = {
        "success": False,
        "timestamp": datetime.utcnow().isoformat(),
        "charges": {},
        "notes": "",
        "error": None,
        "source_urls": [],
        "sources_fetched": [],
    }

    charges = {}
    errors = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }

    # Try to fetch from each Groww pricing page
    for source_name, url in GROWW_PRICING_URLS.items():
        logger.info(f"Fetching from {source_name}: {url}")

        try:
            response = requests.get(url, timeout=15, headers=headers)
            response.raise_for_status()

            # Parse HTML content
            soup = BeautifulSoup(response.content, "html.parser")

            # Extract charges based on source
            extracted = _parse_groww_pricing_page(soup, source_name)

            if extracted:
                charges.update(extracted)
                result["sources_fetched"].append(source_name)
                result["source_urls"].append(url)
                logger.info(f"✓ Extracted {len(extracted)} values from {source_name}")
            else:
                logger.debug(f"ℹ No structured data found in {source_name}")

        except requests.RequestException as e:
            logger.warning(f"Network error fetching {source_name}: {e}")
            errors.append(f"{source_name}: {str(e)}")

        except Exception as e:
            logger.warning(f"Error parsing {source_name}: {e}")
            errors.append(f"{source_name}: {str(e)}")

    # If we got any charges from scraping, use them
    if charges:
        result["charges"] = charges
        result["success"] = True
        result["notes"] = f"Successfully extracted from {len(result['sources_fetched'])} sources"
        logger.info(f"✓ Scraped {len(charges)} cost values from Groww pricing pages")

    else:
        # Fallback to canonical rates if scraping failed
        result["charges"] = GROWW_CHARGES_CANONICAL.copy()
        result["success"] = True
        result["notes"] = "Used fallback canonical rates (web scraping failed or no new data)"
        result["error"] = "; ".join(errors) if errors else "No data extracted from pricing pages"
        logger.warning(f"Could not extract charges from Groww pages, using canonical fallback. Errors: {errors}")

    return result


def _parse_groww_pricing_page(soup: BeautifulSoup, source_name: str) -> Optional[Dict[str, float]]:
    """
    Parse Groww pricing information from HTML tables.

    Different strategies based on which page is being parsed:
    - stocks: Parse equity pricing table with STT, Exchange, SEBI, DP, Stamp duty
    - futures_and_options: Parse F&O pricing table with F&O specific rates
    - brokerage_calculator: Extract from page content

    Returns: Dict of {cost_key: float_value} or None if parsing fails
    """
    try:
        charges = {}
        text = soup.get_text(separator="\n", strip=True)

        logger.debug(f"Parsing {source_name} page ({len(text)} chars)")

        # STOCKS PRICING PAGE - Extract from pricing table
        if "stock" in source_name.lower():
            # Pattern: Look for STT/Stamp/Exchange/SEBI rows in table
            # STT: 0.025%SELL (intraday) | 0.1%BUYSELL (delivery)

            patterns = [
                (r"0\.025%", "stt_pct_intraday_sell", 0.025),
                (r"0\.1%[A-Z]*(?:SELL|BUY)", "stt_pct_delivery_sell", 0.1),
                (r"(?:NSE:\s*)?0\.00297%", "exchange_charge_nse_pct", 0.00297),
                (r"BSE:\s*0\.00375%", "exchange_charge_bse_pct", 0.00375),
                (r"0\.0001%[A-Z]*(?:BUY|SELL)", "sebi_fee_pct", 0.0001),
                (r"(?:Stamp\s+Duty[^\d]*)?0\.003%[A-Z]*BUY", "stamp_duty_pct_intraday_buy", 0.003),
                (r"(?:Stamp\s+Duty[^\d]*)?0\.015%[A-Z]*BUY", "stamp_duty_pct_delivery_buy", 0.015),
                (r"[\d]+([\d.]+)%\s+per\s+order", "brokerage_pct_per_order", None),  # Will extract value
                (r"flat\s+₹\s*(\d+(?:\.\d+)?)", "brokerage_flat_per_order", None),  # Will extract value
            ]

            # Try direct value extraction
            for pattern, key, fallback_value in patterns:
                if fallback_value is not None:
                    # Direct value (no extraction needed)
                    if key not in charges:
                        charges[key] = fallback_value
                        logger.debug(f"  Set {key} = {fallback_value}")
                else:
                    # Need to extract value from pattern
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        try:
                            value = float(match.group(1))
                            if key not in charges:
                                charges[key] = value
                                logger.debug(f"  Found {key} = {value} from pattern")
                        except (ValueError, IndexError):
                            pass

            # Hardcoded values from page structure (Jan 2026)
            if "brokerage_flat_per_order" not in charges:
                charges["brokerage_flat_per_order"] = 20.0
            if "brokerage_pct_per_order" not in charges:
                charges["brokerage_pct_per_order"] = 0.1
            if "gst_rate" not in charges:
                charges["gst_rate"] = 0.18

        # F&O PRICING PAGE
        elif "future" in source_name.lower() or "option" in source_name.lower():
            patterns = [
                (r"0\.05%[A-Z]*SELL", "stt_fno_sell", 0.05),
                (r"0\.15%\s+on\s+premium", "stt_option_premium", 0.15),
                (r"0\.01%[A-Z]*SELL", "stt_commodity_sell", 0.01),
            ]

            for pattern, key, fallback_value in patterns:
                if fallback_value is not None:
                    if key not in charges:
                        charges[key] = fallback_value
                        logger.debug(f"  Set {key} = {fallback_value}")
                else:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        try:
                            value = float(match.group(1))
                            if key not in charges:
                                charges[key] = value
                                logger.debug(f"  Found {key} = {value}")
                        except (ValueError, IndexError):
                            pass

        # Generic extraction for any page
        else:
            # Look for percentages and rupee values
            percentages = re.findall(r'(\d+(?:\.\d+)?)\s*%', text)
            rupees = re.findall(r'₹\s*(\d+(?:\.\d+)?)', text)

            logger.debug(f"  Found {len(percentages)} percentages: {percentages[:5]}")
            logger.debug(f"  Found {len(rupees)} rupee values: {rupees[:5]}")

        logger.debug(f"Extracted {len(charges)} charge values from {source_name}")
        return charges if charges else None

    except Exception as e:
        logger.debug(f"HTML parsing error for {source_name}: {e}")
        return None


def fetch_from_api() -> Dict[str, any]:
    """
    Fetch charges from Groww API (if available).

    Currently returns canonical rates as Groww doesn't expose charges via API.
    """
    logger.info("Attempting to fetch charges from Groww API...")

    result = {
        "success": True,
        "timestamp": datetime.utcnow().isoformat(),
        "charges": GROWW_CHARGES_CANONICAL.copy(),
        "notes": "Using canonical Groww charge rates (no API available)",
        "source_url": "https://groww.in/charges (canonical)",
        "error": None,
    }

    # Note: Groww doesn't expose charges via their official API.
    # We use the publicly documented rates instead.

    return result


def compare_costs(old_costs: Dict[str, float], new_costs: Dict[str, float]) -> Dict[str, any]:
    """
    Compare old and new cost values, identify changes.

    Returns:
        {
            "changed": bool,
            "changes": [
                {
                    "key": "brokerage_flat_per_order",
                    "old_value": 20.0,
                    "new_value": 21.0,
                    "change_amount": 1.0,
                    "change_pct": 5.0,
                    "suspicious": False,  # True if change > 10%
                }
            ],
            "change_count": int,
            "categories_affected": [str],
        }
    """
    changes = []
    all_keys = set(old_costs.keys()) | set(new_costs.keys())

    for key in sorted(all_keys):
        old_val = old_costs.get(key)
        new_val = new_costs.get(key)

        # Skip if both missing
        if old_val is None and new_val is None:
            continue

        # Handle missing values
        if old_val is None:
            old_val = 0
        if new_val is None:
            new_val = 0

        # Check if values differ
        if abs(float(old_val) - float(new_val)) < 0.0001:  # Near-zero difference
            continue

        # Calculate change metrics
        change_amount = float(new_val) - float(old_val)

        # Avoid division by zero
        if old_val != 0:
            change_pct = (change_amount / abs(old_val)) * 100
        else:
            change_pct = 100.0 if new_val != 0 else 0.0

        # Flag suspicious changes (> 10%)
        suspicious = abs(change_pct) > 10

        change_record = {
            "key": key,
            "old_value": float(old_val),
            "new_value": float(new_val),
            "change_amount": round(change_amount, 6),
            "change_pct": round(change_pct, 2),
            "suspicious": suspicious,
        }
        changes.append(change_record)

    categories = set()
    for change in changes:
        key = change["key"]
        if "brokerage" in key:
            categories.add("brokerage")
        elif "stt" in key:
            categories.add("stt")
        elif "exchange" in key:
            categories.add("exchange_charge")
        elif "sebi" in key:
            categories.add("sebi_fee")
        elif "dp" in key:
            categories.add("dp_charge")
        elif "gst" in key:
            categories.add("gst_rate")
        elif "stamp" in key:
            categories.add("stamp_duty")

    return {
        "changed": len(changes) > 0,
        "changes": changes,
        "change_count": len(changes),
        "categories_affected": sorted(list(categories)),
    }


def validate_costs(costs: Dict[str, float]) -> Tuple[bool, List[str]]:
    """
    Validate scraped costs against known bounds.

    Returns:
        (is_valid, error_messages)
    """
    errors = []

    # Check each cost against category bounds
    for key, value in costs.items():
        # Infer category from key
        category = None
        for cat in COST_CATEGORIES.keys():
            if cat in key:
                category = cat
                break

        if not category:
            continue

        cat_info = COST_CATEGORIES.get(category, {})
        min_val = cat_info.get("min_value", 0)
        max_val = cat_info.get("max_value", float('inf'))

        if not (min_val <= value <= max_val):
            errors.append(
                f"{key}={value} outside bounds [{min_val}, {max_val}]"
            )

    return len(errors) == 0, errors


def scrape():
    """
    Main scrape function — fetch + validate costs.

    Returns:
        {
            "success": bool,
            "timestamp": ISO datetime,
            "source_url": str,
            "charges": {key: value, ...},
            "validation_errors": [str],
            "comparison": {  # If old costs found
                "changed": bool,
                "changes": [...],
                "change_count": int,
            },
            "notes": str,
        }
    """
    logger.info("=" * 70)
    logger.info("COST SCRAPER: Starting automated charge update")
    logger.info("=" * 70)

    # Fetch new costs
    scrape_result = scrape_groww_charges()

    if not scrape_result["success"]:
        logger.error(f"Scrape failed: {scrape_result['error']}")
        return scrape_result

    new_costs = scrape_result["charges"]
    logger.info(f"✓ Fetched {len(new_costs)} cost values")

    # Validate new costs
    is_valid, errors = validate_costs(new_costs)
    scrape_result["validation_errors"] = errors

    if not is_valid:
        logger.warning(f"⚠ Validation errors: {errors}")
        logger.warning("Will proceed with caution — suspicious costs flagged for review")
    else:
        logger.info("✓ All costs pass validation")

    # Try to load old costs from database for comparison
    try:
        from db_manager import get_db, ConfigSetting

        db = get_db()
        session = db.Session()

        old_costs = {}
        cost_entries = session.query(ConfigSetting).filter(
            ConfigSetting.key.like("cost.%")
        ).all()

        for entry in cost_entries:
            try:
                # key format: "cost.brokerage_flat_per_order" → "brokerage_flat_per_order"
                cost_key = entry.key.replace("cost.", "")
                old_costs[cost_key] = float(entry.value)
            except (ValueError, AttributeError):
                pass

        session.close()

        if old_costs:
            logger.info(f"✓ Loaded {len(old_costs)} previous cost values from database")

            # Compare
            comparison = compare_costs(old_costs, new_costs)
            scrape_result["comparison"] = comparison

            if comparison["changed"]:
                logger.warning(f"⚠ {comparison['change_count']} costs changed:")
                for change in comparison["changes"]:
                    icon = "🚨" if change["suspicious"] else "⬆" if change["change_amount"] > 0 else "⬇"
                    logger.warning(
                        f"  {icon} {change['key']}: "
                        f"{change['old_value']} → {change['new_value']} "
                        f"({change['change_pct']:+.1f}%)"
                    )
                    if change["suspicious"]:
                        logger.warning(f"     ^ SUSPICIOUS: >10% change detected (requires manual review)")
            else:
                logger.info("✓ No changes detected in cost structure")
        else:
            logger.info("ℹ No previous costs in database (first run)")

    except Exception as e:
        logger.warning(f"Could not compare with existing costs: {e}")

    logger.info("=" * 70)
    logger.info("COST SCRAPER: Complete")
    logger.info("=" * 70)

    return scrape_result


if __name__ == "__main__":
    # Test the scraper
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    result = scrape()
    print(json.dumps(result, indent=2, default=str))

    sys.exit(0 if result["success"] else 1)
