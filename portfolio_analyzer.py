"""
Portfolio Analyzer — Deep analysis of every holding/position in the user's
Groww portfolio before any trading happens.

For each stock, runs:
  • Full AI prediction (ML + News + Market Context)
  • Fundamental analysis (financials, P&L, balance sheet, cash flow)
  • Competitor comparison
  • Cost-aware profitability check
  • P&L analysis (unrealised gain/loss relative to avg price)
  • Technical health check (RSI, trend, patterns)
  • Action recommendation: HOLD / ADD MORE / BOOK PROFIT / EXIT / WATCH

No trades are placed — this is read-only analysis for the user to review.
"""

import logging
from datetime import datetime

from config import (
    DEFAULT_EXCHANGE, DEFAULT_PRODUCT,
    MAX_TRADE_QUANTITY, MAX_TRADE_VALUE,
    STOP_LOSS_PCT, TARGET_PCT,
)
import costs
import fundamental_analysis

logger = logging.getLogger(__name__)


def analyze_portfolio(groww_api, get_prediction_fn, fetch_live_price_fn):
    """
    Fetch holdings + positions from Groww and run full analysis on each item.

    Args:
        groww_api: Authenticated GrowwAPI instance
        get_prediction_fn: bot.get_prediction function
        fetch_live_price_fn: bot.fetch_live_price function

    Returns dict with:
        - summary: overall portfolio health
        - holdings: list of analyzed holdings
        - positions: list of analyzed positions
    """
    logger.info("analyze_portfolio received groww_api: %s (is None: %s)", type(groww_api).__name__ if groww_api else "None", groww_api is None)
    
    # ── Fetch portfolio data from Groww ──────────────────────────────────
    try:
        holdings_resp = groww_api.get_holdings_for_user()
        raw_holdings = holdings_resp.get("holdings", []) if holdings_resp else []
    except Exception as e:
        logger.error("Failed to fetch holdings: %s", e)
        raw_holdings = []

    try:
        positions_resp = groww_api.get_positions_for_user()
        raw_positions = positions_resp.get("positions", []) if positions_resp else []
    except Exception as e:
        logger.error("Failed to fetch positions: %s", e)
        raw_positions = []

    # ── Analyze each holding ─────────────────────────────────────────────
    analyzed_holdings = []
    for h in raw_holdings:
        if not h:
            continue
        symbol = h.get("trading_symbol", "")
        qty = h.get("quantity", 0)
        avg_price = h.get("average_price", 0)

        if not symbol or qty <= 0:
            continue

        try:
            analysis = _analyze_stock(
                symbol=symbol,
                quantity=qty,
                avg_price=avg_price,
                source="holding",
                get_prediction_fn=get_prediction_fn,
                fetch_live_price_fn=fetch_live_price_fn,
                groww_api=groww_api,
            )
            analysis["raw"] = h
            analyzed_holdings.append(analysis)
        except Exception as e:
            logger.error(f"Failed to analyze holding {symbol}: {e}", exc_info=True)
            continue

    # ── Analyze each position ────────────────────────────────────────────
    analyzed_positions = []
    for p in raw_positions:
        if not p:
            continue
        symbol = p.get("trading_symbol", "")
        qty = p.get("quantity", 0)
        net_price = p.get("net_price", 0)
        realised_pnl = p.get("realised_pnl", 0)

        if not symbol or qty <= 0:
            continue

        try:
            analysis = _analyze_stock(
                symbol=symbol,
                quantity=qty,
                avg_price=net_price,
                source="position",
                get_prediction_fn=get_prediction_fn,
                fetch_live_price_fn=fetch_live_price_fn,
                groww_api=groww_api,
            )
            analysis["realised_pnl"] = realised_pnl
            analysis["raw"] = p
            analyzed_positions.append(analysis)
        except Exception as e:
            logger.error(f"Failed to analyze position {symbol}: {e}", exc_info=True)
            continue

    # ── Build portfolio summary ──────────────────────────────────────────
    all_items = analyzed_holdings + analyzed_positions
    summary = _build_summary(all_items, analyzed_holdings, analyzed_positions)

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "holdings": analyzed_holdings,
        "positions": analyzed_positions,
    }


def _analyze_stock(symbol, quantity, avg_price, source, get_prediction_fn, fetch_live_price_fn, groww_api=None):
    """Run full analysis on a single stock."""
    now = datetime.now()
    result = {
        "symbol": symbol,
        "quantity": quantity,
        "avg_price": avg_price,
        "source": source,
        "analysis_time": now.isoformat(),
    }

    # ── Live price ───────────────────────────────────────────────────────
    try:
        ltp = fetch_live_price_fn(symbol)
        result["ltp"] = ltp
    except Exception as e:
        logger.warning("Could not fetch LTP for %s: %s", symbol, e)
        result["ltp"] = avg_price  # fallback
        ltp = avg_price

    # ── Unrealised P&L ──────────────────────────────────────────────────
    if avg_price > 0 and ltp > 0:
        unrealised_pnl = round((ltp - avg_price) * quantity, 2)
        unrealised_pnl_pct = round((ltp - avg_price) / avg_price * 100, 2)
        invested_value = round(avg_price * quantity, 2)
        current_value = round(ltp * quantity, 2)
    else:
        unrealised_pnl = 0
        unrealised_pnl_pct = 0
        invested_value = 0
        current_value = 0

    result["invested_value"] = invested_value
    result["current_value"] = current_value
    result["unrealised_pnl"] = unrealised_pnl
    result["unrealised_pnl_pct"] = unrealised_pnl_pct

    # ── Net profit if sold now (after all charges) ──────────────────────
    try:
        sell_pnl = costs.net_profit(avg_price, ltp, quantity,
                                     product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)
        result["net_pnl_if_sold"] = round(sell_pnl["net_profit"], 2)
        result["charges_if_sold"] = round(sell_pnl["total_charges"], 2)
    except Exception:
        result["net_pnl_if_sold"] = unrealised_pnl
        result["charges_if_sold"] = 0

    # ── AI Prediction ───────────────────────────────────────────────────
    try:
        prediction = get_prediction_fn(symbol)
        if prediction is None:
            prediction = {"signal": "HOLD", "confidence": 0, "reason": "Prediction unavailable"}
        
        result["prediction"] = prediction
        result["ai_signal"] = prediction.get("signal", "HOLD")
        result["ai_confidence"] = prediction.get("confidence", 0)
        result["ai_reason"] = prediction.get("reason", "")
        result["combined_score"] = prediction.get("combined_score", 0)

        # Sources
        sources = prediction.get("sources", {})
        result["ml_signal"] = sources.get("ml", {}).get("signal")
        result["ml_confidence"] = sources.get("ml", {}).get("confidence", 0)
        result["news_signal"] = sources.get("news", {}).get("signal") if sources.get("news") else None
        result["news_score"] = sources.get("news", {}).get("avg_score", 0) if sources.get("news") else 0
        result["market_signal"] = sources.get("market_context", {}).get("market_signal")
        result["sector"] = sources.get("market_context", {}).get("sector")
        result["sector_signal"] = sources.get("market_context", {}).get("sector_signal")
        result["volatility_regime"] = sources.get("market_context", {}).get("volatility_regime")

        # Indicators
        indicators = prediction.get("indicators", {})
        result["rsi"] = indicators.get("rsi")
        result["macd"] = indicators.get("macd")
        result["trend"] = indicators.get("trend")
        result["ema_crossover"] = indicators.get("ema_crossover")
        result["stoch_k"] = indicators.get("stoch_k")
        result["candle_patterns"] = indicators.get("candle_patterns", [])

    except Exception as e:
        logger.warning("Prediction failed for %s: %s", symbol, e)
        result["prediction"] = None
        result["ai_signal"] = "HOLD"
        result["ai_confidence"] = 0
        result["ai_reason"] = f"Analysis failed: {e}"

    # ── Target & Stop Loss (SMART — based on 5Y data + technicals) ───
    # Uses historical resistance, 5Y average, and current signal
    # to set strategic exit targets, NOT a blind % from buy price
    prediction = result.get("prediction")
    long_term = prediction.get("long_term_trend", {}) if prediction and isinstance(prediction, dict) else {}
    
    # Ensure long_term is not None
    if long_term is None:
        long_term = {}
    
    resistance_5y = long_term.get("resistance", 0)
    max_price_5y = long_term.get("max_price", 0)
    avg_price_5y = long_term.get("avg_price", 0)
    support_5y = long_term.get("support", 0)
    
    ai_signal = result.get("ai_signal", "HOLD")
    
    if resistance_5y > 0 and max_price_5y > 0:
        # Strategic multi-level targets based on historical price action
        # T1: Conservative — 5Y resistance zone (where price regularly reverses)
        # T2: Strategic — between resistance and all-time high
        # T3: Optimistic — near all-time high
        t1 = round(resistance_5y, 2)
        t2 = round((resistance_5y + max_price_5y) / 2, 2)
        t3 = round(max_price_5y * 0.95, 2)  # 95% of ATH
        
        # Pick primary target based on signal strength
        if ai_signal == "BUY":
            target_price = t2  # Bullish → aim higher
        elif ai_signal == "SELL":
            # Even for SELL, if holding, set a recovery target
            target_price = t1  # Conservative exit
        else:
            # HOLD — use the 5Y average as a mean-reversion target if above current,
            # else use resistance
            if avg_price_5y > ltp * 1.05:
                target_price = round(avg_price_5y, 2)
            else:
                target_price = t1
        
        # Never set target below buy price (that's not a target, that's a loss)
        if target_price < avg_price * 1.02:
            target_price = round(avg_price * 1.10, 2)  # At minimum 10% above buy
        
        # Store all target levels for display
        result["target_levels"] = {
            "conservative": t1,
            "strategic": t2,
            "optimistic": t3,
            "5y_avg": round(avg_price_5y, 2),
        }
    else:
        # Fallback: no 5Y data available, use a reasonable %
        target_price = round(avg_price * (1 + TARGET_PCT / 100), 2)
        result["target_levels"] = None
    
    # Stop loss — use 5Y support if available, else fixed %
    if support_5y > 0 and support_5y < ltp:
        stop_loss_price = round(support_5y, 2)
    else:
        stop_loss_price = round(avg_price * (1 - STOP_LOSS_PCT / 100), 2)
    
    # Calculate what happens at target/SL INCLUDING charges
    try:
        target_profit_info = costs.net_profit(avg_price, target_price, quantity,
                                               product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)
        result["target_price"] = target_price
        result["target_profit"] = round(target_profit_info["net_profit"], 2)
    except Exception:
        result["target_price"] = target_price
        result["target_profit"] = round((target_price - avg_price) * quantity, 2)
    
    try:
        sl_loss_info = costs.net_profit(avg_price, stop_loss_price, quantity,
                                         product=DEFAULT_PRODUCT, exchange=DEFAULT_EXCHANGE)
        result["stop_loss_price"] = stop_loss_price
        result["stop_loss_loss"] = round(sl_loss_info["net_profit"], 2)
    except Exception:
        result["stop_loss_price"] = stop_loss_price
        result["stop_loss_loss"] = round((stop_loss_price - avg_price) * quantity, 2)
    
    # ── Distance from key levels ────────────────────────────────────────
    result["pct_to_target"] = round((target_price - ltp) / ltp * 100, 2) if ltp > 0 else 0
    result["pct_to_stop_loss"] = round((ltp - stop_loss_price) / ltp * 100, 2) if ltp > 0 else 0
    result["pct_from_buy"] = round((ltp - avg_price) / avg_price * 100, 2) if avg_price > 0 else 0

    # ── Fundamental Analysis ────────────────────────────────────────────
    try:
        if groww_api:
            fundamentals = fundamental_analysis.get_fundamental_analysis(groww_api, symbol)
            if fundamentals is None:
                fundamentals = {}
            result["fundamentals"] = fundamentals
            result["fundamental_rating"] = fundamentals.get("fundamental_rating", "N/A")
            result["fundamental_score"] = fundamentals.get("fundamental_score", 0)
            result["fundamental_pct"] = fundamentals.get("fundamental_pct", 0)
            result["fundamental_flags"] = fundamentals.get("positive_flags", [])
            result["fundamental_concerns"] = fundamentals.get("concerns", [])
            result["competitors"] = fundamentals.get("competitors", [])
            result["sector"] = fundamentals.get("sector", "Unknown")
            result["pe_ratio"] = fundamentals.get("financials", {}).get("pe_ratio")
            result["roe"] = fundamentals.get("financials", {}).get("roe")
            result["roce"] = fundamentals.get("financials", {}).get("roce")
            result["debt_to_equity"] = fundamentals.get("financials", {}).get("debt_to_equity")
            result["promoter_holding"] = fundamentals.get("financials", {}).get("promoter_holding")
            result["52w_position_pct"] = fundamentals.get("52w_position_pct")
            result["volume_signal"] = fundamentals.get("volume_signal")
            result["vs_peers"] = fundamentals.get("vs_peers")
            
            # ── Institutional Holdings (FIIs, Mutual Funds) ────────────────
            try:
                from fii_tracker import format_institutional_holdings
                result = format_institutional_holdings(symbol, result)
            except Exception as e:
                logger.warning("Failed to fetch FII/MF holdings for %s: %s", symbol, e)

            # ── Commodity / Environmental Factors ──────────────────────────
            try:
                from commodity_tracker import get_commodity_impact
                commodity_impact = get_commodity_impact(symbol)
                if commodity_impact:
                    result["commodity_impact"] = commodity_impact
            except Exception as e:
                logger.warning("Failed to fetch commodity data for %s: %s", symbol, e)
        else:
            result["fundamentals"] = None
    except Exception as e:
        logger.warning("Fundamental analysis failed for %s: %s", symbol, e)
        result["fundamentals"] = None
        result["fundamental_rating"] = "N/A"
        result["fundamental_score"] = 0
        result["fundamental_pct"] = 0
        result["fundamental_flags"] = []
        result["fundamental_concerns"] = []
        result["competitors"] = []
        result["pe_ratio"] = None
        result["roe"] = None
        result["roce"] = None
        result["debt_to_equity"] = None
        result["promoter_holding"] = None
        result["52w_position_pct"] = None
        result["volume_signal"] = None
        result["vs_peers"] = None
    except Exception as e:
        logger.warning("Fundamental analysis failed for %s: %s", symbol, e)
        result["fundamentals"] = None
        result["fundamental_rating"] = "N/A"

    # ── Generate recommendation ─────────────────────────────────────────
    recommendation = _generate_recommendation(result)
    result["recommendation"] = recommendation["action"]
    result["recommendation_reason"] = recommendation["reason"]
    result["health"] = recommendation["health"]

    return result


def _generate_recommendation(analysis):
    """
    Generate a FULLY TRANSPARENT recommendation showing EVERY component & decision path.
    
    Every decision must show:
      - P&L position relative to buy price
      - AI signal (ML+News+Market combined) with source breakdown
      - Fundamental analysis (rating, PE, ROE, ROCE, D/E, promoter holding)
      - Technical indicators (RSI, Trend, EMA, 52-week position)
      - Competitor performance (vs peers, outperforming/underperforming)
      - Market conditions & volume signals
      - Cost analysis (will charges eat profits?)
      - Composite scoring and decision logic
    
    Returns: {"action": str, "reason": detailed_breakdown, "health": status, 
             "components": detailed_scores}
    """
    signal = analysis.get("ai_signal", "HOLD")
    confidence = analysis.get("ai_confidence", 0)
    pnl_pct = analysis.get("unrealised_pnl_pct", 0)
    rsi = analysis.get("rsi")
    trend = analysis.get("trend")
    vol = analysis.get("volatility_regime", "NORMAL")
    net_pnl = analysis.get("net_pnl_if_sold", 0)
    ltp = analysis.get("ltp", 0)
    avg_price = analysis.get("avg_price", 0)
    
    # Fundamentals
    fund_rating = analysis.get("fundamental_rating", "N/A")
    fund_pct = analysis.get("fundamental_pct", 0)
    pe = analysis.get("pe_ratio")
    roe = analysis.get("roe")
    roce = analysis.get("roce")
    de = analysis.get("debt_to_equity")
    promoter = analysis.get("promoter_holding")
    pos_52w = analysis.get("52w_position_pct")
    vol_signal = analysis.get("volume_signal")
    vs_peers = analysis.get("vs_peers")
    fund_flags = analysis.get("fundamental_flags", [])
    fund_concerns = analysis.get("fundamental_concerns", [])

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 1: P&L ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    pnl_section = []
    pnl_score = 0
    
    if pnl_pct > 20:
        pnl_section.append(f"📈 Strong profit: Up {pnl_pct:.1f}% (₹{(ltp-avg_price)*analysis.get('quantity',0):.0f}) — need to protect gains")
        pnl_score = 1
    elif pnl_pct > 5:
        pnl_section.append(f"📈 Profitable: Up {pnl_pct:.1f}% — in sweet spot for hold/book decisions")
        pnl_score = 2
    elif pnl_pct > 0:
        pnl_section.append(f"📊 Small profit: Up {pnl_pct:.1f}% — slightly above buy price")
        pnl_score = 1
    elif pnl_pct > -5:
        pnl_section.append(f"📉 Near breakeven: {pnl_pct:+.1f}% — add or exit decision critical")
        pnl_score = 0
    elif pnl_pct > -15:
        pnl_section.append(f"📉 Moderate loss: {pnl_pct:.1f}% down (₹{(ltp-avg_price)*analysis.get('quantity',0):.0f}) — average down or cut losses?")
        pnl_score = -1
    else:
        pnl_section.append(f"🔴 DEEP LOSS: {pnl_pct:.1f}% down (₹{(ltp-avg_price)*analysis.get('quantity',0):.0f}) — serious decision needed")
        pnl_score = -2

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 2: AI SIGNAL BREAKDOWN (DETAILED TRANSPARENCY)
    # ─────────────────────────────────────────────────────────────────────────
    ai_section = []
    ai_score = 0
    
    # Handle case where prediction is None
    prediction = analysis.get("prediction")
    if prediction and isinstance(prediction, dict):
        sources = prediction.get("sources", {})
        indicators = prediction.get("indicators", {})
        long_term_data = prediction.get("long_term_trend", {})
    else:
        sources = {}
        indicators = {}
        long_term_data = {}
    
    # Ensure long_term_data is never None
    if long_term_data is None:
        long_term_data = {}
    
    ml_signal = sources.get("ml", {}).get("signal", "---")
    ml_conf = sources.get("ml", {}).get("confidence", 0)
    ml_score = sources.get("ml", {}).get("score", 0)
    
    news_data = sources.get("news", {})
    news_signal = news_data.get("signal", "---") if news_data else "---"
    news_articles = news_data.get("total_articles", 0) if news_data else 0
    news_score = news_data.get("avg_score", 0) if news_data else 0
    
    ctx = sources.get("market_context", {})
    market_signal = ctx.get("market_signal", "---")
    sector = ctx.get("sector", "UNKNOWN")
    sector_signal = ctx.get("sector_signal", "---")
    volatility = ctx.get("volatility_regime", "NORMAL")
    multi_tf = ctx.get("multi_tf_aligned", False)
    
    long_term_score = sources.get("long_term", {}).get("score", 0)
    trend_pct = long_term_data.get("trend_pct", 0)
    
    # Main consensus line - protect against None prediction
    combined_score = 0
    if prediction and isinstance(prediction, dict):
        combined_score = prediction.get('combined_score', 0)
    ai_section.append(f"🤖 AI CONSENSUS: {signal} ({confidence*100:.0f}% confidence) | Score: {combined_score:+.2f}/10")
    ai_section.append(f"    Weights: ML 40% | 5Y-Trend 15% | News 20% | Market 25%")
    ai_section.append("")
    
    # 1. ML Model Details
    ai_section.append(f"📊 ML/TECHNICAL MODEL ({ml_conf*100:.0f}% confidence, contributes {ml_score:+.2f} to score):")
    ai_section.append(f"    Signal: {ml_signal}")
    if indicators:
        ai_section.append(f"    Indicators detected:")
        if indicators.get("rsi"):
            rsi = indicators.get("rsi")
            rsi_status = "OVERBOUGHT" if rsi > 70 else "OVERSOLD" if rsi < 30 else "Normal"
            ai_section.append(f"      • RSI: {rsi:.0f} ({rsi_status})")
        if indicators.get("macd"):
            ai_section.append(f"      • MACD: {indicators.get('macd'):.4f}")
        if indicators.get("trend"):
            ai_section.append(f"      • Trend: {indicators.get('trend')}")
        if indicators.get("ema_crossover"):
            ai_section.append(f"      • EMA Crossover: {indicators.get('ema_crossover')}")
        if indicators.get("stoch_k"):
            ai_section.append(f"      • Stochastic: {indicators.get('stoch_k')}")
        candle_patterns = indicators.get("candle_patterns", [])
        if candle_patterns:
            ai_section.append(f"      • Candle Patterns: {', '.join(candle_patterns[:3])}")
    ai_section.append("")
    
    # 2. 5-Year Trend Analysis
    ai_section.append(f"📈 5-YEAR TREND ANALYSIS ({long_term_score:+.2f} to score):")
    ai_section.append(f"    Long-term trend: {trend_pct:+.1f}%")
    if long_term_data:
        ai_section.append(f"    Support Price: ₹{long_term_data.get('support_price', 0):.2f} (Distance: {long_term_data.get('distance_from_support_pct', 0):+.1f}%)")
        ai_section.append(f"    Resistance Price: ₹{long_term_data.get('resistance_price', 0):.2f} (Distance: {long_term_data.get('distance_from_resistance_pct', 0):+.1f}%)")
        ai_section.append(f"    Volatility (5Y): {long_term_data.get('volatility_pct', 0):.1f}%")
    ai_section.append("")
    
    # 3. News Sentiment Details
    ai_section.append(f"📰 NEWS SENTIMENT ({news_signal}, +{news_score:+.2f} to score, {news_articles} articles analyzed):")
    if news_data and news_articles > 0:
        bullish_count = news_data.get("bullish_count", 0)
        bearish_count = news_data.get("bearish_count", 0)
        neutral_count = news_data.get("neutral_count", 0)
        ai_section.append(f"    Distribution: {bullish_count}↑ bullish, {bearish_count}↓ bearish, {neutral_count}→ neutral")
        ai_section.append(f"    Average score: {news_score:+.2f} (range: -1 to +1)")
        # Show top headlines if available
        if news_data.get("top_articles"):
            ai_section.append(f"    Top headlines:")
            for article in news_data.get("top_articles", [])[:2]:
                sentiment_emoji = "📈" if article.get("sentiment") == "BULLISH" else "📉" if article.get("sentiment") == "BEARISH" else "➡️"
                ai_section.append(f"      {sentiment_emoji} {article.get('title', '')[:80]} (score: {article.get('score', 0):+.2f})")
    else:
        ai_section.append(f"    No news available for analysis")
    ai_section.append("")
    
    # 4. Market Context
    ai_section.append(f"🌍 MARKET CONTEXT ({ctx.get('context_score', 0):+.2f} to score):")
    ai_section.append(f"    Nifty 50: {market_signal}")
    if sector and sector != "UNKNOWN":
        ai_section.append(f"    Sector ({sector}): {sector_signal}")
    ai_section.append(f"    Volatility Regime: {volatility}")
    if multi_tf:
        ai_section.append(f"    ✓ Multi-timeframe aligned (confidence +15%)")
    else:
        ai_section.append(f"    • Timeframes not aligned")
    ai_section.append("")
    
    if signal == "BUY":
        ai_score = min(3, round(confidence * 3))
    elif signal == "SELL":
        ai_score = -min(3, round(confidence * 3))

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 3: FUNDAMENTAL ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    fund_section = []
    fund_score = 0
    
    if fund_rating != "N/A":
        fund_section.append(f"💼 Fundamentals: {fund_rating.upper()} ({fund_pct:.0f}%)")
        fund_section.append(f"   Financials: PE={pe or '?'}, ROE={roe or '?'}%, ROCE={roce or '?'}%, D/E={de or '?'}, Promoter={promoter or '?'}%")
        
        if fund_flags:
            fund_section.append(f"   ✅ Strengths: {', '.join(fund_flags[:2])}")
        if fund_concerns:
            fund_section.append(f"   ⚠️ Concerns: {', '.join(fund_concerns[:2])}")
        
        if fund_rating == "STRONG":
            fund_score = 2
            fund_section.append("   → Strong fundamental base supports this stock")
        elif fund_rating == "MODERATE":
            fund_score = 1
            fund_section.append("   → Decent fundamentals, mixed growth profile")
        elif fund_rating == "WEAK":
            fund_score = -1
            fund_section.append("   → Weak fundamentals, risky profile")
        elif fund_rating == "POOR":
            fund_score = -2
            fund_section.append("   → Poor fundamentals, high risk of further loss")
    else:
        fund_section.append("💼 Fundamentals: Not available (API issue)")
        fund_score = 0

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 4: TECHNICAL ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    tech_section = []
    tech_score = 0
    
    tech_section.append("📊 Technical Setup:")
    if rsi:
        if rsi > 75:
            tech_section.append(f"   RSI={rsi:.0f} (OVERBOUGHT) → pullback risk, unlikely to rally")
            tech_score -= 1
        elif rsi > 70:
            tech_section.append(f"   RSI={rsi:.0f} (Overbought zone) → some pullback likely")
            tech_score -= 0.5
        elif rsi < 25:
            tech_section.append(f"   RSI={rsi:.0f} (OVERSOLD) → bounce likely, good entry for longs")
            tech_score += 1
        elif rsi < 30:
            tech_section.append(f"   RSI={rsi:.0f} (Oversold zone) → early signs of bounce")
            tech_score += 0.5
        elif rsi > 60:
            tech_section.append(f"   RSI={rsi:.0f} (Bullish) → momentum on upside")
            tech_score += 0.5
        elif rsi < 40:
            tech_section.append(f"   RSI={rsi:.0f} (Weak) → lacking momentum")
            tech_score -= 0.5
        else:
            tech_section.append(f"   RSI={rsi:.0f} (Neutral) → no strong directional bias")
    
    if trend:
        if "UP" in str(trend).upper() or "BULL" in str(trend).upper():
            tech_section.append(f"   Trend: {trend} ↗️ → prices making higher highs/lows")
            tech_score += 1
        elif "DOWN" in str(trend).upper() or "BEAR" in str(trend).upper():
            tech_section.append(f"   Trend: {trend} ↘️ → prices making lower highs/lows")
            tech_score -= 1
        else:
            tech_section.append(f"   Trend: {trend} → sideways/consolidating")

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 5: VALUATION & 52-WEEK POSITION
    # ─────────────────────────────────────────────────────────────────────────
    val_section = []
    val_score = 0
    
    if pos_52w is not None:
        if pos_52w < 20:
            val_section.append(f"📍 Trading at {pos_52w:.0f}% of 52W range (NEAR LOW) → value buying zone")
            val_score += 1
        elif pos_52w > 90:
            val_section.append(f"📍 Trading at {pos_52w:.0f}% of 52W range (NEAR HIGH) → limited upside, extended valuation")
            val_score -= 1
        elif pos_52w < 50:
            val_section.append(f"📍 Trading at {pos_52w:.0f}% of 52W range (Lower half) → some upside available")
            val_score += 0.5
        elif pos_52w > 50:
            val_section.append(f"📍 Trading at {pos_52w:.0f}% of 52W range (Upper half) → rich valuation")
            val_score -= 0.5
    
    if pe and pe < 15:
        val_section.append(f"   P/E={pe:.1f} → undervalued relative to historical")
        val_score += 0.5
    elif pe and pe > 30:
        val_section.append(f"   P/E={pe:.1f} → expensive valuation, limited margin of safety")
        val_score -= 0.5

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 6: PEER COMPARISON & MARKET CONDITIONS
    # ─────────────────────────────────────────────────────────────────────────
    peer_section = []
    peer_score = 0
    
    if vs_peers is not None:
        if vs_peers > 2:
            peer_section.append(f"🏆 Outperforming peers by {vs_peers:+.1f}% (stronger than industry)")
            peer_score += 1
        elif vs_peers > 0.5:
            peer_section.append(f"📈 Slightly ahead of peers ({vs_peers:+.1f}%)")
            peer_score += 0.25
        elif vs_peers < -2:
            peer_section.append(f"⚠️ Underperforming peers by {abs(vs_peers):.1f}% (weaker than competitors)")
            peer_score -= 1
        elif vs_peers < -0.5:
            peer_section.append(f"📉 Slightly behind peers ({vs_peers:+.1f}%)")
            peer_score -= 0.25
        else:
            peer_section.append(f"📊 In line with peers ({vs_peers:+.1f}%)")
    
    if vol_signal and vol_signal != "NORMAL":
        if vol_signal == "HIGH_VOLUME":
            peer_section.append(f"📊 {vol_signal} spike → institutional activity, breakout likely")
            peer_score += 0.5
        elif vol_signal == "LOW_VOLUME":
            peer_section.append(f"⚠️ {vol_signal} → illiquid, hard to exit position")
            peer_score -= 0.5

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 7B: INSTITUTIONAL HOLDINGS (FII / MF)
    # ─────────────────────────────────────────────────────────────────────────
    inst_section = []
    inst_score = 0

    fii_signal = analysis.get("fii_signal")
    mf_signal = analysis.get("mf_signal")
    shareholding_summary = analysis.get("shareholding_summary")

    if shareholding_summary:
        inst_section.append(f"🏛️ Shareholding: {shareholding_summary}")

        # FII signal scoring
        if fii_signal == "STRONG_BUY":
            inst_section.append("   FII holding >15% → strong institutional confidence")
            inst_score += 1.0
        elif fii_signal == "BUY":
            inst_section.append("   FII holding 8-15% → moderate institutional interest")
            inst_score += 0.5
        elif fii_signal == "SELL":
            inst_section.append("   FII holding <3% → low institutional confidence")
            inst_score -= 0.5
        elif fii_signal == "NEUTRAL":
            inst_section.append("   FII holding 3-8% → neutral institutional stance")

        # MF signal scoring
        if mf_signal == "STRONG_BUY":
            inst_section.append("   MF holding >12% → high domestic fund conviction")
            inst_score += 0.5
        elif mf_signal == "BUY":
            inst_section.append("   MF holding 6-12% → moderate domestic fund interest")
            inst_score += 0.25
        elif mf_signal == "NEUTRAL":
            inst_section.append("   MF holding <6% → limited domestic fund exposure")
    else:
        inst_section.append("🏛️ Institutional Holdings: Data not available")

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 7C: ENVIRONMENTAL / COMMODITY FACTORS
    # ─────────────────────────────────────────────────────────────────────────
    env_section = []
    env_score = 0

    commodity_impact = analysis.get("commodity_impact")
    if commodity_impact:
        commodity_name = commodity_impact.get("commodity", "")
        commodity_trend = commodity_impact.get("trend", "NEUTRAL")
        price_change_pct = commodity_impact.get("price_change_pct", 0)
        relationship = commodity_impact.get("relationship", "inverse")
        env_summary = commodity_impact.get("summary", "")

        env_section.append(f"🛢️ COMMODITY IMPACT ({commodity_name}):")
        env_section.append(f"   {env_summary}")
        env_section.append(f"   Trend: {commodity_trend} ({price_change_pct:+.1f}% change)")
        env_section.append(f"   Relationship: {relationship} (rising {commodity_name} = {'negative' if relationship == 'inverse' else 'positive'} for stock)")

        # Score based on commodity trend and relationship
        if relationship == "inverse":
            if commodity_trend == "RISING":
                env_score -= 0.5 if abs(price_change_pct) < 10 else -1.0
                env_section.append(f"   → Headwind: rising input costs pressuring margins")
            elif commodity_trend == "FALLING":
                env_score += 0.5 if abs(price_change_pct) < 10 else 1.0
                env_section.append(f"   → Tailwind: falling input costs boosting margins")
        elif relationship == "direct":
            if commodity_trend == "RISING":
                env_score += 0.5 if abs(price_change_pct) < 10 else 1.0
                env_section.append(f"   → Tailwind: rising commodity prices boost revenue")
            elif commodity_trend == "FALLING":
                env_score -= 0.5 if abs(price_change_pct) < 10 else -1.0
                env_section.append(f"   → Headwind: falling commodity prices hurt revenue")
    else:
        env_section.append("🌍 Environmental Factors: No significant commodity dependency")

    # ─────────────────────────────────────────────────────────────────────────
    # COMPONENT 8: COST ANALYSIS
    # ─────────────────────────────────────────────────────────────────────────
    cost_section = []
    if net_pnl < analysis.get("unrealised_pnl", 0):
        loss_to_charges = analysis.get("unrealised_pnl", 0) - net_pnl
        cost_section.append(f"💰 Cost Impact: ₹{loss_to_charges:.0f} lost to charges if you sell now")
        if loss_to_charges > abs(net_pnl) * 0.5:
            cost_section.append("   ⚠️ Charges would consume >50% of profit — DON'T sell yet!")

    # ─────────────────────────────────────────────────────────────────────────
    # FINAL SCORING & DECISION
    # ─────────────────────────────────────────────────────────────────────────
    total_score = round(pnl_score + ai_score + fund_score + tech_score + val_score + peer_score + inst_score + env_score, 1)
    
    action = "HOLD"
    health = "GOOD"
    decision_reason = ""
    
    # ─ Decision Logic ─
    if pnl_pct > 20:  # BIG PROFITS
        if total_score <= -2:
            action = "BOOK PROFIT"
            health = "WARNING"
            decision_reason = "Significant gains + weakening signals → lock in profits before reversal"
        elif total_score >= 3:
            action = "HOLD"
            health = "GOOD"
            decision_reason = "Strong profit + positive outlook → let it run for more upside"
        else:
            action = "HOLD"
            health = "GOOD"
            decision_reason = "Protecting gains, mixed signals ahead"

    elif pnl_pct > 5:  # MODERATE PROFIT
        if total_score <= -3:
            action = "BOOK PROFIT"
            health = "WARNING"
            decision_reason = "Profit at risk from multiple negative signals → book before reversal"
        elif total_score >= 2:
            action = "HOLD"
            health = "GOOD"
            decision_reason = "Profitable + positive outlook → compound gains"
        else:
            action = "HOLD"
            health = "GOOD"
            decision_reason = "Moderate profit, wait for clearer trend"

    elif pnl_pct > -5:  # NEAR BREAKEVEN
        if total_score >= 4:
            action = "ADD MORE"
            health = "GOOD"
            decision_reason = "Strong signals at buy price → accumulate before rally"
        elif total_score <= -3:
            action = "WATCH"
            health = "WARNING"
            decision_reason = "Mixed signals at breakeven → hold & monitor before deciding"
        else:
            action = "HOLD"
            health = "GOOD"
            decision_reason = "Breakeven zone, let signals clear before acting"

    elif pnl_pct > -15:  # MODERATE LOSS
        health = "WARNING"
        if total_score >= 3:
            action = "ADD MORE"
            decision_reason = "Strong recovery signals + good fundamentals → average down on dip"
        elif total_score >= 0:
            action = "HOLD"
            decision_reason = "Loss but company still has merit → wait for recovery"
        elif total_score <= -4:
            action = "EXIT"
            health = "DANGER"
            decision_reason = "Weak fundamentals + AI bearish + losses deepening → cut losses"
        else:
            action = "HOLD"
            decision_reason = "Moderate loss with mixed signals → patience needed"

    else:  # DEEP LOSS
        health = "DANGER"
        if total_score >= 4:
            action = "HOLD"
            decision_reason = "Deep loss BUT strong recovery signals → conviction hold"
        elif total_score >= 1:
            action = "HOLD"
            decision_reason = "Deep loss but some positive signals → hold for turnaround"
        elif total_score <= -3:
            action = "EXIT"
            decision_reason = "Deep loss + weak company + AI bearish → cut losses immediately"
        else:
            action = "WATCH"
            decision_reason = "Deep loss, need clearer signal before deciding"

    # Volatility override
    if vol == "HIGH" and action == "ADD MORE":
        action = "HOLD"
        decision_reason += " | OVERRIDE: High market volatility, hold instead of buying"

    # Build full breakdown
    reason_lines = [
        "═══════════════════════════════════════════════════════════════",
        f"{'RECOMMENDATION':<30} {action:>20}  [{health}]",
        "═══════════════════════════════════════════════════════════════",
        "",
        "📊 DECISION BREAKDOWN:",
        "",
        "1️⃣ P&L ANALYSIS:",
        *pnl_section,
        "",
        "2️⃣ AI SIGNALS (ML + News + Market):",
        *ai_section,
        "",
        "3️⃣ FUNDAMENTAL STRENGTH:",
        *fund_section,
        "",
        "4️⃣ TECHNICAL CONDITION:",
        *tech_section,
        "",
        "5️⃣ VALUATION & 52-WEEK POSITION:",
        *val_section,
        "",
        "6️⃣ PEER COMPARISON & VOLUME:",
        *peer_section,
        "",
        "7️⃣ INSTITUTIONAL HOLDINGS (FII / MF):",
        *inst_section,
        "",
        "8️⃣ ENVIRONMENTAL / COMMODITY FACTORS:",
        *env_section,
        "",
        "9️⃣ COST ANALYSIS:",
        *(cost_section if cost_section else ["   No significant cost impact"]),
        "",
        "═════════════════════════════════════════════════════════════════",
        f"🎯 COMPONENT SCORES:",
        f"   P&L: {pnl_score:+.0f}  |  AI: {ai_score:+.0f}  |  Fundamentals: {fund_score:+.0f}  |  Technical: {tech_score:+.0f}  |  Valuation: {val_score:+.0f}  |  Peers: {peer_score:+.0f}  |  FII/MF: {inst_score:+.1f}  |  Commodity: {env_score:+.1f}",
        f"   ═════════════════════════════════════════════════════════════════",
        f"   TOTAL COMPOSITE SCORE: {total_score:+.1f}/10",
        "",
        "🎯 DECISION LOGIC:",
        f"   {decision_reason}",
        "",
    ]

    return {
        "action": action,
        "reason": "\n".join(reason_lines),
        "health": health,
        "components": {
            "pnl_score": pnl_score,
            "ai_score": ai_score,
            "fundamental_score": fund_score,
            "technical_score": tech_score,
            "valuation_score": val_score,
            "peer_score": peer_score,
            "institutional_score": inst_score,
            "commodity_score": env_score,
            "total_composite": total_score,
        }
    }


def _build_summary(all_items, holdings, positions):
    """Build aggregate portfolio summary."""
    total_invested = sum(a.get("invested_value", 0) for a in all_items)
    total_current = sum(a.get("current_value", 0) for a in all_items)
    total_unrealised = sum(a.get("unrealised_pnl", 0) for a in all_items)
    total_pnl_pct = round((total_current - total_invested) / total_invested * 100, 2) if total_invested > 0 else 0

    # Categorize by health
    good = [a for a in all_items if a.get("health") == "GOOD"]
    warning = [a for a in all_items if a.get("health") == "WARNING"]
    danger = [a for a in all_items if a.get("health") == "DANGER"]

    # Categorize by recommendation
    exits = [a for a in all_items if a.get("recommendation") == "EXIT"]
    book_profits = [a for a in all_items if a.get("recommendation") == "BOOK PROFIT"]
    add_more = [a for a in all_items if a.get("recommendation") == "ADD MORE"]
    holds = [a for a in all_items if a.get("recommendation") == "HOLD"]

    # Best & worst performers
    if all_items:
        best = max(all_items, key=lambda a: a.get("unrealised_pnl_pct", 0))
        worst = min(all_items, key=lambda a: a.get("unrealised_pnl_pct", 0))
    else:
        best = worst = None

    # Overall portfolio health
    if len(danger) > len(all_items) * 0.4:
        overall_health = "DANGER"
    elif len(warning) + len(danger) > len(all_items) * 0.5:
        overall_health = "WARNING"
    else:
        overall_health = "GOOD"

    return {
        "total_stocks": len(all_items),
        "holdings_count": len(holdings),
        "positions_count": len(positions),
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "total_unrealised_pnl": round(total_unrealised, 2),
        "total_pnl_pct": total_pnl_pct,
        "overall_health": overall_health,
        "good_count": len(good),
        "warning_count": len(warning),
        "danger_count": len(danger),
        "exit_count": len(exits),
        "book_profit_count": len(book_profits),
        "add_more_count": len(add_more),
        "hold_count": len(holds),
        "exit_symbols": [a["symbol"] for a in exits],
        "book_profit_symbols": [a["symbol"] for a in book_profits],
        "add_more_symbols": [a["symbol"] for a in add_more],
        "best_performer": {"symbol": best["symbol"], "pnl_pct": best["unrealised_pnl_pct"]} if best else None,
        "worst_performer": {"symbol": worst["symbol"], "pnl_pct": worst["unrealised_pnl_pct"]} if worst else None,
    }
