"""
Market Intelligence Engine — Automated collection & analysis of:
  1) Institutional Holdings (quarterly shareholding patterns from Screener.in)
  2) Peer Comparison (fundamentals across sector competitors)
  3) Volume Seasonality (which months/quarters a stock fires the most)

Data stored in PostgreSQL for historical tracking and trend detection.
"""

import logging
import os
import re
from datetime import datetime, date, timedelta
from collections import defaultdict

import requests
import psycopg2
from psycopg2.extras import execute_batch, RealDictCursor
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DB_URL")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# ─────────────────────────────────────────────────────────────────────────────
# 1.  INSTITUTIONAL HOLDINGS — scrape quarterly shareholding from Screener.in
# ─────────────────────────────────────────────────────────────────────────────

def _safe_pct(text):
    """Extract float from '52.63%' → 52.63"""
    if not text:
        return None
    cleaned = text.replace("%", "").replace(",", "").replace("\xa0", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _safe_int(text):
    """Extract int from '10,82,650' → 1082650"""
    if not text:
        return None
    cleaned = text.replace(",", "").replace("\xa0", "").strip()
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_quarter_label(label):
    """Convert 'Mar 2023' → date(2023, 3, 31), 'Dec 2025' → date(2025, 12, 31)"""
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    parts = label.strip().split()
    if len(parts) != 2:
        return None
    mon = month_map.get(parts[0].lower()[:3])
    try:
        year = int(parts[1])
    except ValueError:
        return None
    if not mon:
        return None
    # Last day of the month
    if mon == 12:
        return date(year, 12, 31)
    next_month = date(year, mon + 1, 1)
    return next_month - timedelta(days=1)


def scrape_shareholding(symbol):
    """
    Scrape quarterly shareholding pattern from Screener.in.
    Returns list of dicts:
      [{"quarter": "Dec 2025", "quarter_date": "2025-12-31",
        "promoters": 52.63, "fiis": 12.78, "diis": 21.08,
        "government": 0.07, "public": 13.37, "others": 0.06,
        "num_shareholders": 1000999}, ...]
    """
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code == 404:
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=_HEADERS, timeout=12)
        if resp.status_code != 200:
            logger.warning("Screener returned %d for %s shareholding", resp.status_code, symbol)
            return []

        html = resp.text
        sh_idx = html.find('id="shareholding"')
        if sh_idx == -1:
            logger.debug("No shareholding section found for %s", symbol)
            return []

        section = html[sh_idx:sh_idx + 20000]

        # Get the first table (quarterly data)
        tables = re.findall(r'<table[^>]*>(.*?)</table>', section, re.DOTALL)
        if not tables:
            return []

        table = tables[0]  # Quarterly table

        # Headers = quarter labels
        thead = re.search(r'<thead>(.*?)</thead>', table, re.DOTALL)
        if not thead:
            return []
        ths = re.findall(r'<th[^>]*>(.*?)</th>', thead.group(1), re.DOTALL)
        quarters = [re.sub(r'<[^>]+>', '', h).replace('\xa0', ' ').strip() for h in ths]
        # First header is empty (row label column)
        quarters = [q for q in quarters if q]

        # Parse rows
        row_map = {}
        label_key_map = {
            "promoters": "promoters",
            "fiis": "fiis",
            "diis": "diis",
            "government": "government",
            "public": "public",
            "others": "others",
            "no. of shareholders": "num_shareholders",
        }

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells) < 2:
                continue
            raw_label = re.sub(r'<[^>]+>', '', cells[0]).replace('\xa0', ' ').strip().lower()
            key = None
            for k, v in label_key_map.items():
                if k in raw_label:
                    key = v
                    break
            if not key:
                continue
            values = [re.sub(r'<[^>]+>', '', c).replace('\xa0', '').strip() for c in cells[1:]]
            row_map[key] = values

        # Build result
        results = []
        for i, q_label in enumerate(quarters):
            q_date = _parse_quarter_label(q_label)
            if not q_date:
                continue
            entry = {
                "quarter": q_label,
                "quarter_date": q_date.isoformat(),
            }
            for key, values in row_map.items():
                if i < len(values):
                    if key == "num_shareholders":
                        entry[key] = _safe_int(values[i])
                    else:
                        entry[key] = _safe_pct(values[i])
            results.append(entry)

        logger.info("Scraped %d quarters of shareholding for %s", len(results), symbol)
        return results

    except Exception as e:
        logger.warning("Failed to scrape shareholding for %s: %s", symbol, e)
        return []


def store_shareholding(symbol, data):
    """Store shareholding data in DB (upsert by symbol + quarter_date)."""
    if not data or not DB_URL:
        return 0
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cursor = conn.cursor()
        rows = []
        for d in data:
            rows.append((
                symbol, d["quarter_date"], d.get("quarter", ""),
                d.get("promoters"), d.get("fiis"), d.get("diis"),
                d.get("government"), d.get("public"), d.get("others"),
                d.get("num_shareholders"),
            ))
        execute_batch(cursor, """
            INSERT INTO shareholding_patterns
                (symbol, quarter_date, quarter_label, promoters, fiis, diis,
                 government, public_pct, others, num_shareholders)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, quarter_date) DO UPDATE SET
                promoters = EXCLUDED.promoters,
                fiis = EXCLUDED.fiis,
                diis = EXCLUDED.diis,
                government = EXCLUDED.government,
                public_pct = EXCLUDED.public_pct,
                others = EXCLUDED.others,
                num_shareholders = EXCLUDED.num_shareholders,
                updated_at = NOW()
        """, rows, page_size=50)
        conn.commit()
        stored = len(rows)
        cursor.close()
        conn.close()
        return stored
    except Exception as e:
        logger.error("Failed to store shareholding for %s: %s", symbol, e)
        return 0


def get_shareholding_history(symbol):
    """Get stored shareholding history for a stock."""
    if not DB_URL:
        return []
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT * FROM shareholding_patterns
            WHERE symbol = %s ORDER BY quarter_date
        """, (symbol,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows
    except Exception as e:
        logger.warning("Failed to get shareholding for %s: %s", symbol, e)
        return []


def analyze_institutional_trend(symbol):
    """
    Analyze FII/DII trends from stored shareholding history.
    Returns insights like "FIIs have been selling for 4 quarters" etc.
    """
    history = get_shareholding_history(symbol)
    if len(history) < 2:
        return {"symbol": symbol, "insights": [], "trend": "INSUFFICIENT_DATA"}

    latest = history[-1]
    prev = history[-2]
    oldest = history[0]

    insights = []
    trend_score = 0  # positive = bullish institutional activity

    # ── FII trend ──
    fii_latest = latest.get("fiis") or 0
    fii_prev = prev.get("fiis") or 0
    fii_oldest = oldest.get("fiis") or 0
    fii_change_qoq = round(fii_latest - fii_prev, 2)
    fii_change_total = round(fii_latest - fii_oldest, 2)

    # Count consecutive quarters of FII buying/selling
    fii_streak = 0
    for i in range(len(history) - 1, 0, -1):
        curr_fii = history[i].get("fiis") or 0
        prev_fii = history[i - 1].get("fiis") or 0
        if curr_fii > prev_fii:
            if fii_streak >= 0:
                fii_streak += 1
            else:
                break
        elif curr_fii < prev_fii:
            if fii_streak <= 0:
                fii_streak -= 1
            else:
                break
        else:
            break

    if fii_streak >= 3:
        insights.append(f"FIIs buying for {fii_streak} consecutive quarters (+{fii_change_total:.1f}% total)")
        trend_score += 2
    elif fii_streak >= 1:
        insights.append(f"FIIs increased holdings this quarter (+{fii_change_qoq:.1f}%)")
        trend_score += 1
    elif fii_streak <= -3:
        insights.append(f"FIIs selling for {abs(fii_streak)} consecutive quarters ({fii_change_total:+.1f}% total)")
        trend_score -= 2
    elif fii_streak <= -1:
        insights.append(f"FIIs reduced holdings this quarter ({fii_change_qoq:+.1f}%)")
        trend_score -= 1

    # ── DII trend ──
    dii_latest = latest.get("diis") or 0
    dii_prev = prev.get("diis") or 0
    dii_change_qoq = round(dii_latest - dii_prev, 2)

    dii_streak = 0
    for i in range(len(history) - 1, 0, -1):
        curr_dii = history[i].get("diis") or 0
        prev_dii = history[i - 1].get("diis") or 0
        if curr_dii > prev_dii:
            if dii_streak >= 0:
                dii_streak += 1
            else:
                break
        elif curr_dii < prev_dii:
            if dii_streak <= 0:
                dii_streak -= 1
            else:
                break
        else:
            break

    if dii_streak >= 3:
        insights.append(f"DIIs accumulating for {dii_streak} straight quarters")
        trend_score += 1
    elif dii_streak <= -3:
        insights.append(f"DIIs reducing for {abs(dii_streak)} straight quarters")
        trend_score -= 1

    # ── Promoter stability ──
    prom_latest = latest.get("promoters") or 0
    prom_oldest = oldest.get("promoters") or 0
    prom_change = round(prom_latest - prom_oldest, 2)
    if abs(prom_change) < 1:
        insights.append(f"Promoter holding stable at {prom_latest:.1f}%")
    elif prom_change < -3:
        insights.append(f"Promoter holding dropped {abs(prom_change):.1f}% — possible pledge/sell")
        trend_score -= 2
    elif prom_change > 2:
        insights.append(f"Promoter increased stake by {prom_change:.1f}% — strong conviction")
        trend_score += 2

    # ── Shareholder count trend ──
    sh_latest = latest.get("num_shareholders") or 0
    sh_prev = prev.get("num_shareholders") or 0
    if sh_latest and sh_prev:
        sh_change_pct = round((sh_latest - sh_prev) / sh_prev * 100, 1) if sh_prev else 0
        if sh_change_pct > 10:
            insights.append(f"Retail interest surging — shareholders up {sh_change_pct:.0f}% QoQ")
        elif sh_change_pct < -10:
            insights.append(f"Retail exiting — shareholders down {abs(sh_change_pct):.0f}% QoQ")

    # Overall trend
    if trend_score >= 3:
        trend = "STRONG_INSTITUTIONAL_BUY"
    elif trend_score >= 1:
        trend = "INSTITUTIONAL_ACCUMULATION"
    elif trend_score <= -3:
        trend = "STRONG_INSTITUTIONAL_SELL"
    elif trend_score <= -1:
        trend = "INSTITUTIONAL_DISTRIBUTION"
    else:
        trend = "NEUTRAL"

    return {
        "symbol": symbol,
        "latest_quarter": latest.get("quarter_label", ""),
        "promoters": prom_latest,
        "fiis": fii_latest,
        "diis": dii_latest,
        "public": latest.get("public_pct") or 0,
        "fii_change_qoq": fii_change_qoq,
        "dii_change_qoq": dii_change_qoq,
        "fii_streak": fii_streak,
        "dii_streak": dii_streak,
        "num_shareholders": sh_latest,
        "trend": trend,
        "trend_score": trend_score,
        "insights": insights,
        "history": [
            {
                "quarter": h.get("quarter_label", ""),
                "promoters": h.get("promoters"),
                "fiis": h.get("fiis"),
                "diis": h.get("diis"),
                "public": h.get("public_pct"),
            }
            for h in history
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2.  PEER COMPARISON — fetch key ratios for sector peers
# ─────────────────────────────────────────────────────────────────────────────

def _scrape_peer_ratios(symbol):
    """
    Scrape key financial ratios from Screener.in for a single stock.
    Returns dict: {pe, pb, roe, roce, debt_equity, market_cap, dividend_yield, opm}
    """
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code == 404:
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return {}

        html = resp.text
        data = {}
        patterns = {
            "market_cap": r"Market Cap[^₹]*₹\s*([\d,]+(?:\.\d+)?)\s*Cr",
            "pe": r"Stock P/E[^0-9]*([\d.]+)",
            "pb": r"Price to book value[^0-9]*([\d.]+)",
            "dividend_yield": r"Dividend Yield[^0-9]*([\d.]+)\s*%",
            "roce": r"ROCE[^0-9]*([\d.]+)\s*%",
            "roe": r"ROE[^0-9]*([\d.]+)\s*%",
            "debt_equity": r"Debt to equity[^0-9]*([\d.]+)",
            "promoter_holding": r"Promoter holding[^0-9]*([\d.]+)\s*%",
            "opm": r"OPM\s*[^0-9]*([\d.]+)\s*%",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                val = match.group(1).replace(",", "")
                try:
                    data[key] = float(val)
                except ValueError:
                    pass
        return data
    except Exception as e:
        logger.debug("Failed to scrape ratios for %s: %s", symbol, e)
        return {}


def collect_peer_comparison(symbol):
    """
    Collect and compare fundamentals for a stock vs its sector peers.
    Returns dict with per-stock ratios and relative positioning.
    """
    from fundamental_analysis import _get_competitors, _get_sector_display

    peers = _get_competitors(symbol)
    sector = _get_sector_display(symbol)

    all_symbols = [symbol] + peers[:5]
    peer_data = {}

    for sym in all_symbols:
        ratios = _scrape_peer_ratios(sym)
        if ratios:
            peer_data[sym] = ratios
            logger.debug("Scraped ratios for %s: %s", sym, ratios)

    if symbol not in peer_data:
        return {"symbol": symbol, "sector": sector, "peers": [], "ranking": {}}

    stock_ratios = peer_data[symbol]
    peer_list = []
    for sym in all_symbols:
        if sym in peer_data:
            entry = {"symbol": sym, "is_target": sym == symbol}
            entry.update(peer_data[sym])
            peer_list.append(entry)

    # Rank within peers for each metric
    ranking = {}
    metrics_higher_better = ["roe", "roce", "opm", "dividend_yield"]
    metrics_lower_better = ["pe", "debt_equity"]

    for metric in metrics_higher_better + metrics_lower_better:
        values = [(p["symbol"], p.get(metric)) for p in peer_list if p.get(metric) is not None]
        if not values:
            continue
        reverse = metric in metrics_higher_better
        sorted_vals = sorted(values, key=lambda x: x[1], reverse=reverse)
        for rank, (sym, val) in enumerate(sorted_vals, 1):
            if sym == symbol:
                ranking[metric] = {
                    "rank": rank,
                    "total": len(sorted_vals),
                    "value": stock_ratios.get(metric),
                    "best": sorted_vals[0][1],
                    "worst": sorted_vals[-1][1],
                    "median": sorted([v for _, v in sorted_vals])[len(sorted_vals) // 2],
                }
                break

    # Generate insights
    insights = []
    for metric, info in ranking.items():
        rank = info["rank"]
        total = info["total"]
        if rank == 1:
            insights.append(f"Best {metric.upper().replace('_',' ')} among peers ({info['value']})")
        elif rank == total:
            insights.append(f"Worst {metric.upper().replace('_',' ')} among peers ({info['value']})")
        elif rank <= total / 3:
            insights.append(f"Top-third {metric.upper().replace('_',' ')} ({info['value']}, rank {rank}/{total})")

    return {
        "symbol": symbol,
        "sector": sector,
        "peers": peer_list,
        "ranking": ranking,
        "insights": insights,
        "collected_at": datetime.now().isoformat(),
    }


def store_peer_comparison(symbol, data):
    """Store peer comparison snapshot in DB."""
    if not data or not DB_URL:
        return False
    try:
        import json
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO peer_comparisons (symbol, data_json, collected_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                data_json = EXCLUDED.data_json,
                collected_at = NOW()
        """, (symbol, json.dumps(data, default=str)))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        logger.error("Failed to store peer comparison for %s: %s", symbol, e)
        return False


def get_peer_comparison(symbol):
    """Get stored peer comparison for a stock."""
    if not DB_URL:
        return None
    try:
        import json
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT data_json, collected_at FROM peer_comparisons
            WHERE symbol = %s
        """, (symbol,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            data["db_collected_at"] = row[1].isoformat() if row[1] else None
            return data
        return None
    except Exception as e:
        logger.warning("Failed to get peer comparison for %s: %s", symbol, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 3.  VOLUME SEASONALITY — analyze which months/quarters stock fires most
# ─────────────────────────────────────────────────────────────────────────────

def analyze_volume_seasonality(symbol):
    """
    Analyze historical volume data to find seasonal patterns.
    Uses stock_prices table (daily OHLCV, 5-year history).

    Returns:
      - monthly_avg: avg volume per month (Jan-Dec)
      - quarterly_avg: avg volume per quarter (Q1-Q4)
      - best_months: top 3 months by volume
      - best_quarter: highest volume quarter
      - volume_trend: recent vs historical volume
      - return_seasonality: avg monthly returns
      - best_return_months: months with best avg returns
      - current_month_outlook: what to expect this month historically
    """
    if not DB_URL:
        return {"symbol": symbol, "error": "No DB"}

    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT date, open, high, low, close, volume
            FROM stock_prices
            WHERE symbol = %s AND volume > 0
            ORDER BY date
        """, (symbol,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if len(rows) < 60:  # Need at least ~3 months of data
            return {"symbol": symbol, "error": "Insufficient data", "data_points": len(rows)}

        # ── Monthly volume aggregation ──
        monthly_volumes = defaultdict(list)
        monthly_returns = defaultdict(list)
        weekly_volumes = defaultdict(list)

        prev_close = None
        for dt, open_p, high, low, close, volume in rows:
            month = dt.month
            monthly_volumes[month].append(volume)
            week_of_year = dt.isocalendar()[1]
            weekly_volumes[week_of_year].append(volume)

            if prev_close and prev_close > 0:
                ret = (close - prev_close) / prev_close * 100
                monthly_returns[month].append(ret)
            prev_close = close

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        # Average volume per month
        monthly_avg = {}
        for m in range(1, 13):
            vols = monthly_volumes.get(m, [])
            if vols:
                monthly_avg[month_names[m - 1]] = {
                    "avg_volume": round(sum(vols) / len(vols)),
                    "max_volume": max(vols),
                    "data_points": len(vols),
                }

        # Overall average for normalization
        all_vols = [v for vols in monthly_volumes.values() for v in vols]
        overall_avg = sum(all_vols) / len(all_vols) if all_vols else 1

        # Volume index: month_avg / overall_avg (>1 means above-average month)
        for m_name, m_data in monthly_avg.items():
            m_data["volume_index"] = round(m_data["avg_volume"] / overall_avg, 2)

        # ── Average return per month ──
        monthly_return_avg = {}
        for m in range(1, 13):
            rets = monthly_returns.get(m, [])
            if rets:
                avg_ret = sum(rets) / len(rets)
                positive_pct = len([r for r in rets if r > 0]) / len(rets) * 100
                monthly_return_avg[month_names[m - 1]] = {
                    "avg_return": round(avg_ret, 3),
                    "positive_pct": round(positive_pct, 1),
                    "data_points": len(rets),
                }

        # ── Quarterly aggregation ──
        quarter_map = {1: "Q1 (Jan-Mar)", 2: "Q1 (Jan-Mar)", 3: "Q1 (Jan-Mar)",
                       4: "Q2 (Apr-Jun)", 5: "Q2 (Apr-Jun)", 6: "Q2 (Apr-Jun)",
                       7: "Q3 (Jul-Sep)", 8: "Q3 (Jul-Sep)", 9: "Q3 (Jul-Sep)",
                       10: "Q4 (Oct-Dec)", 11: "Q4 (Oct-Dec)", 12: "Q4 (Oct-Dec)"}

        quarterly_volumes = defaultdict(list)
        quarterly_returns = defaultdict(list)
        for m, vols in monthly_volumes.items():
            q = quarter_map[m]
            quarterly_volumes[q].extend(vols)
        for m, rets in monthly_returns.items():
            q = quarter_map[m]
            quarterly_returns[q].extend(rets)

        quarterly_avg = {}
        for q_name in ["Q1 (Jan-Mar)", "Q2 (Apr-Jun)", "Q3 (Jul-Sep)", "Q4 (Oct-Dec)"]:
            vols = quarterly_volumes.get(q_name, [])
            rets = quarterly_returns.get(q_name, [])
            if vols:
                quarterly_avg[q_name] = {
                    "avg_volume": round(sum(vols) / len(vols)),
                    "volume_index": round((sum(vols) / len(vols)) / overall_avg, 2),
                    "avg_return": round(sum(rets) / len(rets), 3) if rets else 0,
                    "positive_pct": round(len([r for r in rets if r > 0]) / len(rets) * 100, 1) if rets else 0,
                }

        # ── Best months / quarters ──
        sorted_months = sorted(
            monthly_avg.items(),
            key=lambda x: x[1]["avg_volume"],
            reverse=True,
        )
        best_months = [{"month": m, "avg_volume": d["avg_volume"], "volume_index": d["volume_index"]}
                       for m, d in sorted_months[:3]]

        best_quarter = max(quarterly_avg.items(), key=lambda x: x[1]["avg_volume"])[0] if quarterly_avg else None

        # Best return months
        sorted_return_months = sorted(
            monthly_return_avg.items(),
            key=lambda x: x[1]["avg_return"],
            reverse=True,
        )
        best_return_months = [
            {"month": m, "avg_return": d["avg_return"], "positive_pct": d["positive_pct"]}
            for m, d in sorted_return_months[:3]
        ]
        worst_return_months = [
            {"month": m, "avg_return": d["avg_return"], "positive_pct": d["positive_pct"]}
            for m, d in sorted_return_months[-3:]
        ]

        # ── Recent vs historical volume trend ──
        recent_30 = [r[5] for r in rows[-30:] if r[5]]
        historical = [r[5] for r in rows[:-30] if r[5]]
        recent_avg = sum(recent_30) / len(recent_30) if recent_30 else 0
        hist_avg = sum(historical) / len(historical) if historical else 1
        volume_trend_ratio = round(recent_avg / hist_avg, 2) if hist_avg else 1.0

        if volume_trend_ratio > 1.5:
            volume_trend = "SURGING"
        elif volume_trend_ratio > 1.2:
            volume_trend = "INCREASING"
        elif volume_trend_ratio < 0.7:
            volume_trend = "DECLINING"
        elif volume_trend_ratio < 0.85:
            volume_trend = "DECREASING"
        else:
            volume_trend = "STABLE"

        # ── Current month outlook ──
        current_month = month_names[datetime.now().month - 1]
        current_month_data = monthly_avg.get(current_month, {})
        current_return_data = monthly_return_avg.get(current_month, {})

        # ── Generate insights ──
        insights = []

        if best_months:
            top_m = best_months[0]
            insights.append(
                f"Historically highest volume in {top_m['month']} "
                f"({top_m['volume_index']:.1f}x average)"
            )

        if best_return_months:
            best_m = best_return_months[0]
            insights.append(
                f"Best returns historically in {best_m['month']} "
                f"(avg {best_m['avg_return']:+.2f}%, positive {best_m['positive_pct']:.0f}% of the time)"
            )

        if worst_return_months:
            worst_m = worst_return_months[-1]
            if worst_m["avg_return"] < 0:
                insights.append(
                    f"Weakest month: {worst_m['month']} "
                    f"(avg {worst_m['avg_return']:+.2f}%, positive only {worst_m['positive_pct']:.0f}%)"
                )

        if current_month_data:
            vol_idx = current_month_data.get("volume_index", 1)
            ret = current_return_data.get("avg_return", 0)
            pos = current_return_data.get("positive_pct", 50)
            if vol_idx > 1.3:
                insights.append(f"{current_month} is historically a high-activity month ({vol_idx:.1f}x volume)")
            elif vol_idx < 0.7:
                insights.append(f"{current_month} is typically a quiet month ({vol_idx:.1f}x volume)")

            if pos > 65:
                insights.append(f"{current_month} historically bullish ({pos:.0f}% positive, avg {ret:+.2f}%)")
            elif pos < 40:
                insights.append(f"{current_month} historically bearish ({pos:.0f}% positive, avg {ret:+.2f}%)")

        if volume_trend == "SURGING":
            insights.append(f"Recent volume {volume_trend_ratio:.1f}x historical average — unusual activity")
        elif volume_trend == "DECLINING":
            insights.append(f"Volume declining — only {volume_trend_ratio:.1f}x historical levels")

        return {
            "symbol": symbol,
            "data_points": len(rows),
            "date_range": f"{rows[0][0].isoformat()} to {rows[-1][0].isoformat()}",
            "overall_avg_volume": round(overall_avg),
            "monthly_avg": monthly_avg,
            "monthly_returns": monthly_return_avg,
            "quarterly_avg": quarterly_avg,
            "best_months": best_months,
            "best_quarter": best_quarter,
            "best_return_months": best_return_months,
            "worst_return_months": worst_return_months,
            "volume_trend": volume_trend,
            "volume_trend_ratio": volume_trend_ratio,
            "current_month": current_month,
            "current_month_volume": current_month_data,
            "current_month_returns": current_return_data,
            "insights": insights,
        }

    except Exception as e:
        logger.error("Volume seasonality analysis failed for %s: %s", symbol, e)
        return {"symbol": symbol, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 4.  UNIFIED COLLECTION — run all collectors for a symbol
# ─────────────────────────────────────────────────────────────────────────────

def collect_all_intelligence(symbol):
    """Run all data collectors for a given symbol."""
    results = {"symbol": symbol}

    # 1. Shareholding pattern
    try:
        sh_data = scrape_shareholding(symbol)
        if sh_data:
            stored = store_shareholding(symbol, sh_data)
            results["shareholding"] = {"quarters": len(sh_data), "stored": stored}
        else:
            results["shareholding"] = {"quarters": 0, "error": "No data"}
    except Exception as e:
        results["shareholding"] = {"error": str(e)}

    # 2. Peer comparison
    try:
        peer_data = collect_peer_comparison(symbol)
        if peer_data.get("peers"):
            stored = store_peer_comparison(symbol, peer_data)
            results["peers"] = {"count": len(peer_data["peers"]), "stored": stored}
        else:
            results["peers"] = {"count": 0}
    except Exception as e:
        results["peers"] = {"error": str(e)}

    # 3. Volume seasonality (analysis only, uses existing price data)
    try:
        vol_data = analyze_volume_seasonality(symbol)
        if not vol_data.get("error"):
            results["volume_seasonality"] = {"data_points": vol_data["data_points"]}
        else:
            results["volume_seasonality"] = {"error": vol_data["error"]}
    except Exception as e:
        results["volume_seasonality"] = {"error": str(e)}

    return results


def collect_all_watchlist():
    """Run intelligence collection for all watchlist stocks."""
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM stock_prices")
        symbols = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error("Failed to get watchlist symbols: %s", e)
        return []

    results = []
    for symbol in symbols:
        try:
            r = collect_all_intelligence(symbol)
            results.append(r)
            logger.info("Intelligence collected for %s: %s", symbol, r)
        except Exception as e:
            logger.error("Intelligence collection failed for %s: %s", symbol, e)

    return results
