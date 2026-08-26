"""
Master Scheduler — thread-pool daemon coordinating all background tasks.

Tasks run concurrently via a thread pool (max 4 workers) so slow tasks
(deep analysis, research) never block fast critical ones (candle collection,
auto-trade).  Each task has its own lock to prevent self-overlap.
"""

import logging
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import numpy as np

from config import APP_DEVICE_TOKEN

logger = logging.getLogger(__name__)

# app.py now requires X-Device-Token on every mutating request, including
# these same-machine calls to its own API — see app.py's
# _block_cross_origin_mutations for why "no Origin header" is no longer
# treated as automatically trusted.
_DEVICE_HEADERS = {'X-Device-Token': APP_DEVICE_TOKEN} if APP_DEVICE_TOKEN else {}

# ── Task definitions ─────────────────────────────────────────────────────────

_tasks = []
_task_locks = {}          # per-task locks to prevent self-overlap
_pool = None              # thread pool (created on first start)
MAX_WORKERS = 4           # concurrent task limit


def _boot_warmup_active():
    """
    True while the FYERS boot warm-up is still running (see
    fyers_boot_warmup.py). Bulk FYERS tasks check this and skip the tick.

    Which tasks are gated is decided HERE, at the task level, rather than by
    threading a priority flag through every FYERS call site or keeping a
    separate registry that can rot. Adding a genuinely new bulk path means
    adding a scheduler task, and whoever adds it has to decide explicitly
    whether it belongs — the same discipline the fno_auto_trade_enabled gate
    already uses.

    Fails OPEN on any error: if this module is missing or broken, tasks run
    exactly as they do today rather than silently pausing forever. The
    dangerous direction here is "everything stays paused", not "a burst".
    """
    try:
        import fyers_boot_warmup
        return fyers_boot_warmup.is_active()
    except Exception:
        return False


def _register(name, fn, interval_seconds, initial_delay=0):
    """Register a periodic task.  initial_delay = seconds after scheduler
    start before the first run (used to stagger startup bursts)."""
    _tasks.append({
        "name": name,
        "fn": fn,
        "interval": interval_seconds,
        "initial_delay": initial_delay,
        "last_run": 0,
        "_started": False,   # tracks whether initial_delay has elapsed
    })
    _task_locks[name] = threading.Lock()


def get_task_registry():
    """Every registered task with its compiled-in default interval.

    Exists so the settings API can list what actually runs instead of keeping a
    second hand-maintained copy — that copy had drifted to 9 of the 29 tasks, so
    the other 20 were overridable by the scheduler but invisible in the UI.

    `interval` here is always the registered default: _resolve_interval() returns
    the effective value per pass without writing it back, so this never reflects
    a DB override. Empty until start_scheduler() has run.
    """
    return [
        {
            "name": t["name"],
            "default_interval": t["interval"],
            "initial_delay": t["initial_delay"],
        }
        for t in _tasks
    ]


def _task_auto_analysis():
    """Run watchlist auto-analysis (predictions for all watchlist stocks)."""
    # Bulk: fans out over the whole watchlist. Deferred during boot warm-up
    # so it does not race the coordinator for FYERS tokens. Skipping a tick
    # loses nothing — this recomputes from scratch each run, and
    # _run_task_safe() stamps last_run on dispatch, so there is no catch-up
    # pile-up when the pause lifts.
    if _boot_warmup_active():
        return
    import auto_analyzer
    auto_analyzer.auto_analyze_watchlist()


def _task_news_prefetch():
    """Pre-fetch news sentiment for watchlist stocks to warm cache."""
    from config import WATCHLIST
    import news_sentiment
    for symbol in WATCHLIST:
        try:
            news_sentiment.get_news_sentiment(symbol)
        except Exception as e:
            logger.debug("News prefetch failed for %s: %s", symbol, e)


def _task_supply_chain():
    """Run supply chain commodity data collector."""
    try:
        from supply_chain_collector import collect_once
        collect_once()
    except Exception as e:
        logger.warning("Supply chain collection failed: %s", e)


def _task_cache_refresh():
    """Refresh fundamentals cache for ALL dashboard stocks (hourly).

    Each symbol only truly re-scrapes when its 6h cache expires, so the hourly
    pass is cheap and scrape load spreads out naturally. Also detects freshly
    published quarterly results and queues an immediate Tijori refresh so
    new-quarter numbers flow into analysis within hours instead of days.
    """
    # Bulk FYERS consumer, despite the name. get_fundamental_analysis() calls
    # bot.fetch_quote() for the symbol plus up to 5 competitors, over the whole
    # stock_prices universe (~67 symbols) — up to ~400 quote requests when the
    # 6h fundamentals cache is cold, which it always is after an overnight gap.
    #
    # Measured on the 2026-08-25 08:56 restart: this task (initial_delay=0, so
    # the FIRST task to fire) ran straight into the boot warm-up and produced
    # 65 blocked calls, compounding a token-auth failure into a 300s rate-limit
    # cap. Gated here and given a non-zero initial_delay at registration.
    if _boot_warmup_active():
        return

    import fundamental_analysis as fa

    symbols = []
    try:
        from db_manager import get_db
        from sqlalchemy import text as _text
        db = get_db()
        with db.Session() as session:
            rows = session.execute(_text("SELECT DISTINCT symbol FROM stock_prices ORDER BY symbol")).fetchall()
            symbols = [r[0] for r in rows]
    except Exception as e:
        logger.debug("Dashboard universe query failed (%s); using config WATCHLIST", e)
    if not symbols:
        from config import WATCHLIST
        symbols = list(WATCHLIST)

    for symbol in symbols:
        try:
            result = fa.get_fundamental_analysis(None, symbol)
            _detect_new_quarter(symbol, result)
        except Exception as e:
            logger.debug("Cache refresh failed for %s: %s", symbol, e)


def _detect_new_quarter(symbol, fundamentals):
    """Earnings-aware refresh: when the latest quarterly revenue changes vs
    what we last recorded, new results were just published — mark the symbol's
    Tijori data stale so the next tijori_refresh pass (≤6h) re-collects it."""
    try:
        from db_manager import get_config, set_config
        qrev = ((fundamentals or {}).get("financials") or {}).get("latest_quarterly_revenue")
        if qrev is None:
            return
        key = f"earnings.last_qrev.{symbol}"
        prev = get_config(key)
        if prev is not None and str(prev) != str(qrev):
            set_config(f"tijori.last_collected.{symbol}", "1970-01-01T00:00:00")
            logger.info("📊 New quarterly results detected for %s (rev %s → %s) — Tijori refresh queued",
                        symbol, prev, qrev)
        set_config(key, str(qrev))
    except Exception as e:
        logger.debug("New-quarter detection failed for %s: %s", symbol, e)


def _task_update_watchlist_prices():
    """
    DISABLED as of 2026-08-15 — migrated to FYERS. Was: Groww LTP snapshot
    (market hours) + yfinance historical backfill (after hours) into
    stock_prices. Left commented rather than deleted in case of rollback.

    Known consequence, explicitly accepted: bot.analyze_long_term_trend()
    reads stock_prices and feeds bot.get_prediction()'s long-term trend
    score, which real live/paper trade decisions use. With this task
    disabled, stock_prices stops getting fresher data — that signal is now
    frozen at whatever's already stored, not actively wrong, but no longer
    reflecting reality, until bot.py's prediction engine is separately
    repointed to FYERS (not done as part of this change).

    # import os
    # from datetime import datetime, timedelta
    #
    # conn = None
    # try:
    #     import psycopg2
    #     from dotenv import load_dotenv
    #     load_dotenv()
    #
    #     db_url = os.getenv("DB_URL")
    #     if not db_url:
    #         return
    #
    #     conn = psycopg2.connect(db_url, connect_timeout=3)
    #     cursor = conn.cursor()
    #
    #     now = datetime.now()
    #     today = now.date()
    #     is_after_hours = now.hour >= 16 or os.environ.get("_FORCE_BACKFILL") == "1"
    #
    #     # Get ALL unique symbols in stock_prices (not just WATCHLIST config)
    #     cursor.execute("SELECT DISTINCT symbol FROM stock_prices ORDER BY symbol")
    #     all_symbols = [r[0] for r in cursor.fetchall()]
    #
    #     # Also include WATCHLIST config symbols that might not be in DB yet
    #     try:
    #         from config import WATCHLIST
    #         for s in WATCHLIST:
    #             if s not in all_symbols:
    #                 all_symbols.append(s)
    #     except ImportError:
    #         pass
    #
    #     if not all_symbols:
    #         cursor.close()
    #         return
    #
    #     updated = 0
    #     backfilled = 0
    #
    #     # ── Phase 1: Quick live-price update (Groww API) ─────────────────
    #     try:
    #         import bot
    #         for symbol in all_symbols:
    #             try:
    #                 ltp = bot.fetch_live_price(symbol)
    #                 if ltp and ltp > 0:
    #                     cursor.execute("""
    #                         INSERT INTO stock_prices (symbol, date, close)
    #                         VALUES (%s, %s, %s)
    #                         ON CONFLICT (symbol, date) DO UPDATE SET close = EXCLUDED.close
    #                     """, (symbol, today, ltp))
    #                     updated += 1
    #             except Exception:
    #                 pass
    #         conn.commit()
    #     except ImportError:
    #         pass
    #
    #     # ── Phase 2: After-hours yfinance backfill for stale stocks ──────
    #     if is_after_hours:
    #         try:
    #             import yfinance as yf
    #
    #             # Find stocks with stale data (latest date > 1 trading day behind)
    #             cursor.execute("""
    #                 SELECT symbol, MAX(date) as latest
    #                 FROM stock_prices
    #                 GROUP BY symbol
    #                 HAVING MAX(date) < %s
    #             """, (today - timedelta(days=1),))
    #             stale_stocks = cursor.fetchall()
    #
    #             for symbol, latest_date in stale_stocks:
    #                 try:
    #                     # Fetch missing days from yfinance
    #                     start = (latest_date + timedelta(days=1)).strftime("%Y-%m-%d")
    #                     nse_ticker = f"{symbol}.NS"
    #                     data = yf.download(nse_ticker, start=start, interval="1d", progress=False)
    #
    #                     if data is not None and not data.empty:
    #                         close_col = data["Close"]
    #                         if hasattr(close_col, "columns"):
    #                             close_col = close_col.iloc[:, 0]
    #
    #                         for dt_idx, price in close_col.dropna().items():
    #                             dt = dt_idx.date() if hasattr(dt_idx, "date") else dt_idx
    #                             p = float(price)
    #                             if p > 0:
    #                                 cursor.execute("""
    #                                     INSERT INTO stock_prices (symbol, date, close)
    #                                     VALUES (%s, %s, %s)
    #                                     ON CONFLICT (symbol, date) DO NOTHING
    #                                 """, (symbol, dt, round(p, 2)))
    #                         backfilled += 1
    #                 except Exception as e:
    #                     logger.debug("yfinance backfill failed for %s: %s", symbol, e)
    #
    #             conn.commit()
    #         except ImportError:
    #             logger.debug("yfinance not available for backfill")
    #
    #     if updated > 0 or backfilled > 0:
    #         logger.info("✓ Watchlist prices: %d live-updated, %d backfilled via yfinance", updated, backfilled)
    #
    #     cursor.close()
    # except Exception as e:
    #     logger.warning("Watchlist price update failed: %s", e)
    # finally:
    #     if conn is not None:
    #         try:
    #             conn.close()
    #         except Exception:
    #             pass
    return



def _task_retrain_xgb_daily():
    """Retrain XGBoost F&O models with all available candle data (runs daily post-market)."""
    from fno_backtester import _generate_xgb_training_data, FEATURE_NAMES
    from datetime import datetime
    
    try:
        import xgboost as xgb
    except ImportError:
        logger.warning("XGBoost not available for retraining")
        return
    
    import training_progress
    try:
        logger.info("🧠 Starting daily XGBoost retraining...")

        # Per-instrument progress so the panel can show a real ETA rather
        # than only elapsed time. Total is the instrument count; the
        # generator advances one unit per instrument it finishes.
        import fno_backtester as _fb
        _instruments = list(_fb.BACKTEST_INSTRUMENTS)
        training_progress.start("fno_xgb", len(_instruments), label="F&O · XGBoost")

        # Generate training data from all candles in DB
        X, y_long, y_short = _generate_xgb_training_data(
            progress_cb=lambda sym: training_progress.advance("fno_xgb", current=sym)
        )
        
        if len(X) < 100:
            logger.warning("Insufficient training data for XGBoost retraining: %d samples", len(X))
            return
        
        X = np.array(X, dtype=np.float32)
        y_long = np.array(y_long)
        y_short = np.array(y_short)
        
        lp = int(y_long.sum())
        sp = int(y_short.sum())
        logger.info("XGB retraining: %d samples — long wins %d (%.0f%%), short wins %d (%.0f%%)",
                    len(X), lp, lp / len(X) * 100, sp, sp / len(X) * 100)
        
        # Guard against degenerate labels
        if lp < 5 or sp < 5:
            logger.warning("Too few positive labels (long=%d, short=%d) — skipping retrain", lp, sp)
            return
        
        params = dict(
            n_estimators=150,
            max_depth=3,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=1.0,
            reg_lambda=2.0,
            min_child_weight=5,
            random_state=42,
            eval_metric='logloss',
        )
        
        # Train long model
        long_model = xgb.XGBClassifier(
            scale_pos_weight=max(1.0, (len(y_long) - lp) / max(1, lp)),
            **params,
        )
        long_model.fit(X, y_long)
        
        # Train short model
        short_model = xgb.XGBClassifier(
            scale_pos_weight=max(1.0, (len(y_short) - sp) / max(1, sp)),
            **params,
        )
        short_model.fit(X, y_short)
        
        # Update global cache
        import fno_backtester
        fno_backtester._xgb_models = {"long": long_model, "short": short_model}

        # PERSIST TO DISK. Setting the module global alone only survives for
        # this process's lifetime — so every daily retrain since April trained
        # for ~30 minutes and then discarded its work on exit, while
        # models/xgb_backtester.joblib stayed frozen at the April build. That
        # is why the live F&O model read 137 days stale despite a daily task.
        #
        # Same payload shape _get_xgb_models() writes and expects to load,
        # including n_features — the loader rejects a file whose feature count
        # doesn't match the current code, so omitting it would make the saved
        # model silently unloadable.
        # Stamp the timestamp BEFORE the dump that writes it.
        #
        # This assignment used to sit after the joblib.dump below, so the dump
        # persisted whatever _xgb_model_timestamp already held. In a process
        # where _get_xgb_models() had never run, that is its module-level
        # initial value: None. The nightly retrain therefore wrote a model with
        # "trained_at": None, and the loader's `.strftime()` on that None threw
        # AttributeError, was swallowed, and sent every subsequent backtest into
        # a fresh 30-40 minute retrain. Observed exactly once per day, matching
        # this task's schedule: file mtime 2026-08-25 11:14:10 == this task's
        # own "Saved retrained XGB models" log line to the second.
        fno_backtester._xgb_model_timestamp = datetime.now()

        try:
            import joblib
            os.makedirs(os.path.dirname(fno_backtester._XGB_MODEL_PATH), exist_ok=True)
            # Atomic replace, same reasoning as _get_xgb_models(): a truncated
            # model still loads and silently returns garbage signals.
            _tmp = f"{fno_backtester._XGB_MODEL_PATH}.tmp.{os.getpid()}"
            joblib.dump({
                "long": long_model,
                "short": short_model,
                "n_features": len(FEATURE_NAMES),
                "trained_at": fno_backtester._xgb_model_timestamp,
                "n_samples": len(X),
            }, _tmp)
            os.replace(_tmp, fno_backtester._XGB_MODEL_PATH)
            logger.info("Saved retrained XGB models to %s", fno_backtester._XGB_MODEL_PATH)
        except Exception as e:
            logger.error("XGB retrain succeeded but SAVING FAILED (%s) — models live "
                         "in memory only and will be lost on restart", e)
            try:
                os.remove(_tmp)
            except Exception:
                pass
        
        # Calculate win rates for logging
        long_win_rate = (lp / len(y_long) * 100) if len(y_long) > 0 else 0
        short_win_rate = (sp / len(y_short) * 100) if len(y_short) > 0 else 0
        
        logger.info("✅ XGBoost models retrained successfully at %s", datetime.now().isoformat())
        logger.info("   Long model: %d wins / %d trades (%.1f%% win rate)", lp, len(y_long), long_win_rate)
        logger.info("   Short model: %d wins / %d trades (%.1f%% win rate)", sp, len(y_short), short_win_rate)
        
        # Log feature importances
        for tag, mdl in [("LONG", long_model), ("SHORT", short_model)]:
            imp = mdl.feature_importances_
            top5 = sorted(zip(FEATURE_NAMES, imp), key=lambda x: -x[1])[:5]
            logger.info("XGB %s top features: %s", tag, ", ".join(f"{n}={v:.3f}" for n, v in top5))
        
        # Log training event to metadata table
        try:
            from db_manager import log_xgb_training_event
            log_xgb_training_event(len(X), long_win_rate, short_win_rate)
        except Exception as e:
            logger.debug("Failed to log training metadata: %s", e)
        
    except Exception as e:
        logger.error("XGBoost retraining failed: %s", e)
    finally:
        # Always clears the "running" record, so a failed retrain shows as
        # finished rather than an ETA that never completes.
        try:
            training_progress.finish("fno_xgb")
        except Exception:
            pass


def _task_ml_retrain():
    """
    Retrain ML models for all watchlist stocks.

    Uses bot.get_active_watchlist() (the real DB watchlist) rather than
    config.WATCHLIST — that static 10-symbol seed list meant only 10 of ~70
    models were ever retrained, leaving the rest months stale on disk while
    the dashboard happily served their predictions.
    """
    import bot
    import training_progress

    symbols = bot.get_active_watchlist()
    ok = failed = 0
    # Reported to /api/data-health so the Data Coverage panel can show a
    # real ETA instead of only a file count.
    training_progress.start("cash_gbc", len(symbols), label="Cash · GradientBoosting")
    try:
        for symbol in symbols:
            try:
                res = bot.train_model(symbol)
                if (res or {}).get("success"):
                    ok += 1
                else:
                    failed += 1
                    logger.debug("ML retrain unsuccessful for %s: %s", symbol, (res or {}).get("message"))
            except Exception as e:
                failed += 1
                logger.debug("ML retrain failed for %s: %s", symbol, e)
            finally:
                training_progress.advance("cash_gbc", current=symbol)
    finally:
        training_progress.finish("cash_gbc")
    logger.info("ML retrain complete: %d trained, %d failed (of %d)", ok, failed, len(symbols))


def _task_xgb_cash_retrain():
    """
    Retrain the cash XGBoost models daily.

    Sibling of _task_ml_retrain (GradientBoosting), deliberately identical in
    shape: same active watchlist, same per-symbol call, same progress
    reporting. The difference is only which model gets fitted —
    bot.train_xgb_model() reads 5-minute bars resampled from native FYERS
    1-minute data and reuses predictor.build_features/create_labels
    unchanged, so no strategy, threshold or labelling behaviour differs
    between the two.

    Without this the cash XGB models were trained exactly once, by hand, and
    would have drifted stale indefinitely — the same end state as the F&O
    model, reached by a different route (F&O trained daily but never saved;
    these saved fine but never retrained).

    Saving is handled inside train_xgb_model(), which persists only after a
    successful fit and writes atomically.
    """
    import bot
    import training_progress

    symbols = bot.get_active_watchlist()
    ok = failed = 0
    training_progress.start("cash_xgb", len(symbols), label="Cash · XGBoost")
    try:
        for symbol in symbols:
            try:
                res = bot.train_xgb_model(symbol)
                if (res or {}).get("success"):
                    ok += 1
                else:
                    failed += 1
                    logger.debug("XGB retrain unsuccessful for %s: %s", symbol, (res or {}).get("message"))
            except Exception as e:
                failed += 1
                logger.debug("XGB retrain failed for %s: %s", symbol, e)
            finally:
                training_progress.advance("cash_xgb", current=symbol)
    finally:
        training_progress.finish("cash_xgb")
    logger.info("Cash XGB retrain complete: %d trained, %d failed (of %d)", ok, failed, len(symbols))


def _task_cost_rate_update():
    """Check and update trading cost rates from live sources."""
    try:
        from costs import update_cost_rates
        update_cost_rates()
    except Exception as e:
        logger.warning("Cost rate update failed: %s", e)


def _task_tijori_refresh():
    """Refresh Tijori supply-chain & fundamentals data for stale symbols."""
    try:
        import tijori_collector
        result = tijori_collector.collect_stale_symbols()
        logger.info("Tijori refresh: %s", result)
    except Exception as e:
        logger.warning("Tijori refresh failed: %s", e)


def _task_geopolitical_collect():
    """Collect and store geopolitical news for commodities."""
    try:
        from commodity_tracker import collect_geopolitical_news
        collect_geopolitical_news()
    except Exception as e:
        logger.warning("Geopolitical news collection failed: %s", e)


def _task_fno_auto_trade():
    """Run F&O automated trading cycle — entry/exit signals + order execution."""
    try:
        from db_manager import get_config
        # Master switch, mirroring the gate in _task_cash_auto_trade below.
        #
        # This task previously ran unconditionally: fno_trader defines
        # _AUTO_TRADE_CONFIG["enabled"] but nothing ever reads it, so the only
        # thing standing between this loop and a real F&O order was paper_trading.
        #
        # Defaults to "true" — seeding this key must not silently stop F&O
        # trading. Turning it off is the deliberate action.
        if get_config("fno_auto_trade_enabled", "true").lower() != "true":
            return
        import fno_trader
        result = fno_trader.auto_trade_fno()
        actions = result.get("actions", []) if result else []
        if actions:
            logger.info("F&O auto-trade: %d action(s) executed", len(actions))
        else:
            reason = result.get("skipped_reason", "no action") if result else "failed"
            logger.debug("F&O auto-trade: %s", reason)
    except Exception as e:
        logger.warning("F&O auto-trade failed: %s", e)


def _task_fno_capital_sync():
    """Sync F&O capital from actual Groww account balance."""
    try:
        import fno_trader
        synced = fno_trader.sync_capital_from_groww()
        if synced is not None:
            logger.debug("F&O capital synced: ₹%.2f", synced)
    except Exception as e:
        logger.warning("F&O capital sync failed: %s", e)


def _task_prune_idempotency_keys():
    """Drop expired idempotency keys so the table stays small."""
    try:
        from db_manager import prune_idempotency_keys, get_config
        hours = int(get_config("idempotency.retention_hours", 48) or 48)
        removed = prune_idempotency_keys(retention_hours=hours)
        if removed:
            logger.info("Pruned %d expired idempotency key(s)", removed)
    except Exception as e:
        logger.warning("Idempotency key prune failed: %s", e)


def _task_global_indices():
    """Fetch global indices data for F&O decision-making."""
    try:
        import fno_trader
        indices = fno_trader.fetch_global_indices()
        logger.debug("Global indices refreshed: %d indices", len(indices))
    except Exception as e:
        logger.warning("Global indices fetch failed: %s", e)


def _task_token_refresh():
    """Check if Groww token is still valid, refresh if expired."""
    try:
        from token_refresher import check_and_refresh
        check_and_refresh()
    except Exception as e:
        logger.warning("Token refresh check failed: %s", e)


def _task_self_healing():
    """
    Detect and repair recurring FYERS data faults (missing symbol backfill,
    stale intraday data) and alert on the ones that can't be auto-fixed
    (expired token — FYERS disabled unattended refresh for SEBI compliance).

    Backfill is locked while the market is open; during trading hours this
    reports faults but defers the repairs to after close. Runs hourly.
    """
    # Bulk: check_missing_symbols() calls backfill_symbol() (64 FYERS calls
    # per symbol) and check_stale_intraday() calls ensure_recent(ttl=0),
    # forcing a fetch regardless of freshness. Both would fight the boot
    # coordinator for the same token bucket. Hourly task — deferring one
    # tick costs nothing.
    if _boot_warmup_active():
        return
    try:
        import self_healing
        self_healing.run_all()
    except Exception as e:
        logger.warning("Self-healing run failed: %s", e)


def _task_fyers_token_refresh():
    """
    Keep the FYERS access token alive. FYERS access tokens expire at a fixed
    06:00 IST daily; the refresh token behind them lasts ~15 days, so this
    renews unattended and only needs a real interactive login roughly
    fortnightly. Requires FYER_PIN in .env — logs an ERROR if it's missing
    rather than failing silently, since a dead FYERS token now means no
    market data at all (there is no Groww fallback any more).
    """
    try:
        import fyers_auth
        fyers_auth.refresh_if_needed()
    except Exception as e:
        logger.warning("FYERS token refresh check failed: %s", e)


def _task_world_news():
    """Collect world/macro/sector news from RSS feeds and Google News."""
    try:
        from world_news_collector import collect_world_news
        collect_world_news()
    except Exception as e:
        logger.warning("World news collection failed: %s", e)


def _task_deep_analysis():
    """Pre-generate deep contextual analysis for watchlist stocks (cached)."""
    try:
        from deep_analysis import generate_deep_analysis
        from config import WATCHLIST
        # Analyze top watchlist stocks to pre-warm cache
        for symbol in list(WATCHLIST)[:6]:
            try:
                generate_deep_analysis(symbol)
            except Exception as e:
                logger.debug("Deep analysis pre-gen failed for %s: %s", symbol, e)
    except Exception as e:
        logger.warning("Deep analysis task failed: %s", e)




def _task_market_intelligence():

    """Collect institutional holdings, peer comparisons for all watchlist stocks."""
    try:
        import market_intelligence as mi
        mi.collect_all_watchlist()
    except Exception as e:
        logger.warning("Market intelligence task failed: %s", e)


def _task_auto_metadata():
    """Auto-refresh stock metadata: company names, sectors, peers, commodities from Screener.in."""
    try:
        import auto_metadata as am
        am.refresh_all_metadata()
    except Exception as e:
        logger.warning("Auto-metadata refresh failed: %s", e)


def _task_research_engine():
    """Run the unified research algorithm on all tracked stocks."""
    try:
        import research_engine as re_eng
        re_eng.generate_research_all()
    except Exception as e:
        logger.warning("Research engine batch failed: %s", e)


def _task_cash_auto_trade():
    """Run cash equity auto-trade (paper or real based on DB config)."""
    try:
        from db_manager import get_config
        # Check if cash auto-trade is enabled (disabled by default)
        if get_config("cash_auto_trade_enabled", "false").lower() != "true":
            return
        import bot
        # Check market hours
        from fno_trader import _is_market_open
        market_open, _ = _is_market_open()
        if not market_open:
            return
        # Ensure portfolio is reviewed (auto-set for paper mode)
        if bot.is_paper_mode() and not bot.is_portfolio_reviewed():
            bot.mark_portfolio_reviewed()
        # NOT gated wholesale: this task both manages open positions
        # (trailing stops — money already at risk, must never pause) and
        # scans the full ~73-symbol watchlist for new entries (the single
        # biggest source of the restart burst). Only the second half is
        # deferred; see bot.auto_trade(skip_new_entries=...).
        result = bot.auto_trade(skip_new_entries=_boot_warmup_active())
        actions = result.get("actions", []) if result else []
        trades = [a for a in actions if a.get("action") in ("BUY", "SELL")]
        if trades:
            logger.info("Cash auto-trade: %d trade(s) executed", len(trades))
    except Exception as e:
        logger.warning("Cash auto-trade failed: %s", e)


def _task_auto_close_trades():
    """Automatically close trades when they hit target price or stop loss."""
    try:
        from fno_trader import _is_market_open
        import json
        import os
        from paper_trader import get_live_price
        from trailing_stop import check_and_close_trades_on_loss
        
        # Check market hours (only during trading)
        market_open, _ = _is_market_open()
        if not market_open:
            return
        
        trades_json_path = os.path.join('/Users/parthsharma/Desktop/Grow', 'paper_trades.json')
        if not os.path.exists(trades_json_path):
            return
        
        try:
            with open(trades_json_path, 'r') as f:
                trades = json.load(f)
        except:
            return
        
        # Get unique symbols from OPEN trades
        open_trades = [t for t in trades if t.get('status') == 'OPEN']
        if not open_trades:
            return
        
        open_symbols = list(set(t['symbol'] for t in open_trades))
        
        # Fetch live prices for all OPEN trade symbols
        live_prices = {}
        for symbol in open_symbols:
            try:
                price = get_live_price(symbol)
                if price:
                    live_prices[symbol] = price
            except Exception as e:
                logger.debug(f"Error fetching price for {symbol}: {e}")
        
        if not live_prices:
            return
        
        # Check and close trades
        closed_trades = check_and_close_trades_on_loss(
            paper_trades_file='paper_trades.json',
            live_prices=live_prices
        )
        
        if closed_trades:
            logger.info(f"Auto-closed {len(closed_trades)} trades: {[t['symbol'] + ' ' + t['reason'] for t in closed_trades]}")
    
    except Exception as e:
        logger.warning(f"Auto-close trades failed: {e}")



def _task_fyers_daily_topup():
    """
    Keep the fyers_candles DAILY tier current.

    Nothing did this before: ensure_recent() refreshes '5S' only, and
    backfill_symbol() is a first-time whole-history job (64 API calls/symbol).
    The 'D' tier therefore drifted to 2026-08-14 while 5S stayed at 2026-08-21.

    topup_daily() reads each symbol's newest stored daily bar and fetches only
    forward from it — 1 API call per symbol in steady state (measured: 66 calls,
    2,591 bars, 51s for the whole watchlist) versus 4,672 calls for a full
    backfill. Idempotent: storage is ON CONFLICT DO NOTHING.
    """
    # Bulk: up to one FYERS call per watchlist symbol. Deferred during boot
    # warm-up; it is an hourly end-of-day task, so a skipped tick is a no-op.
    if _boot_warmup_active():
        return
    from fno_trader import _is_market_open
    market_open, _ = _is_market_open()
    if market_open:
        return                     # end-of-day only; bars are not final intraday
    try:
        import fyers_historical_backfill
        fyers_historical_backfill.topup_daily()
    except Exception as e:
        logger.warning("FYERS daily top-up failed: %s", e)

def _task_record_pnl():
    """Record unrealised P&L snapshot every 5 seconds during market hours."""
    try:
        import json
        import os
        from db_manager import get_db, PnLSnapshot
        
        # Market-hours guard, restored. This was commented out as a temporary
        # test ("TEST: Temporarily disabled market hours check to test P&L
        # recording") and left that way, which made this the only path
        # reaching FYERS live 24/7: the task POSTs to /api/live-prices every
        # 5s, and _get_latest_symbol_price() tries a live FYERS quote FIRST
        # for every symbol before falling back to intraday_db/daily_db.
        # Matches the identical gate _task_auto_close_trades already uses.
        from fno_trader import _is_market_open
        market_open, _ = _is_market_open()
        if not market_open:
            return


        trades_json_path = os.path.join('/Users/parthsharma/Desktop/Grow', 'paper_trades.json')
        if not os.path.exists(trades_json_path):
            return
        
        try:
            with open(trades_json_path, 'r') as f:
                trades = json.load(f)
        except Exception as load_error:
            logger.debug(f"Failed to load trades JSON: {load_error}")
            return
        
        # Calculate P&L from open trades
        open_trades = [t for t in trades if t.get('status') == 'OPEN']
        if not open_trades:
            return
        
        # Get live prices for all symbols
        live_prices = {}
        try:
            import requests
            symbols = list(set([t['symbol'] for t in open_trades]))
            
            response = requests.post(
                'http://127.0.0.1:8000/api/live-prices',
                json={'symbols': symbols},
                headers=_DEVICE_HEADERS,
                timeout=5
            )
            if response.status_code == 200:
                live_prices = response.json().get('prices', {})
                logger.debug(f"[PnL] Got live prices for {len(live_prices)} symbols")
            else:
                logger.debug(f"[PnL] Live prices API returned {response.status_code}")
        except Exception as price_error:
            logger.debug(f"[PnL] Failed to fetch live prices: {price_error}")
        
        total_pnl = 0.0
        total_pnl_pct = 0.0
        profit_count = 0
        loss_count = 0
        peak_pnl = 0.0
        
        for trade in open_trades:
            symbol = trade.get('symbol')
            entry_price = trade.get('entry_price', 0)
            current_price = live_prices.get(symbol)
            
            if current_price and entry_price:
                # Calculate P&L
                if trade.get('signal') == 'BUY':
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                else:  # SELL
                    pnl_pct = ((entry_price - current_price) / entry_price) * 100
                
                quantity = trade.get('quantity', 1)
                pnl_amount = (pnl_pct / 100) * (entry_price * quantity)
                
                total_pnl += pnl_amount
                total_pnl_pct += pnl_pct
                
                # Track peak P&L for each trade
                trade_peak = trade.get('peak_pnl', pnl_pct)
                if pnl_pct > trade_peak:
                    trade_peak = pnl_pct
                
                peak_pnl = max(peak_pnl, trade_peak)
                
                if pnl_pct > 0:
                    profit_count += 1
                elif pnl_pct < 0:
                    loss_count += 1
        
        # Average P&L percentage
        avg_pnl_pct = total_pnl_pct / len(open_trades) if open_trades else 0
        
        logger.debug(f"[PnL] Recording: total_pnl=₹{total_pnl:.2f}, avg_pct={avg_pnl_pct:.2f}%, profit={profit_count}, loss={loss_count}")
        
        # Store in database
        db = get_db()
        if db:
            session = db.Session()
            try:
                snapshot = PnLSnapshot(
                    total_pnl=round(total_pnl, 2),
                    total_pnl_pct=round(avg_pnl_pct, 2),
                    trades_count=len(open_trades),
                    peak_pnl=round(peak_pnl, 2),
                    peak_pnl_pct=round(peak_pnl, 2),
                    profit_trades=profit_count,
                    loss_trades=loss_count,
                )
                session.add(snapshot)
                session.commit()
                logger.debug(f"[PnL] ✓ Snapshot saved successfully")
            except Exception as save_error:
                logger.debug(f"[PnL] Failed to save snapshot: {save_error}")
            except Exception as save_error:
                logger.debug(f"Failed to save P&L snapshot: {save_error}")
            finally:
                session.close()
    
    except Exception as e:
        logger.debug(f"Record P&L task failed: {e}")


def _task_paper_eod_summary():
    """Send end-of-day paper trading summary via Telegram."""
    try:
        from db_manager import get_config
        if get_config("telegram_enabled", "false").lower() != "true":
            return
        if get_config("paper_trading", "false").lower() != "true":
            return
        from datetime import timezone, timedelta, time as dtime
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        # Only send between 15:30-16:00 IST
        if not (now_ist.hour == 15 and 30 <= now_ist.minute <= 59):
            return
        _send_paper_eod_summary()
    except Exception as e:
        logger.warning("Paper EOD summary failed: %s", e)


def _send_paper_eod_summary():
    """Generate and send paper trade EOD summary with reasoning."""
    import telegram_alerts
    from db_manager import get_db, PaperTrade
    from datetime import timezone, timedelta

    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()

    # PaperTrade.created_at is stored NAIVE UTC (Column default=datetime.utcnow)
    # while `today` above is an IST calendar date. Comparing them directly —
    # func.date(created_at) >= today — silently mixed two clocks 5h30m apart.
    # Market hours (09:15-15:30 IST = 03:45-10:00 UTC) happen to land on the
    # same calendar date, so this produced correct results in practice, but any
    # write between 00:00 and 05:30 IST fell on the previous UTC date and was
    # dropped from the EOD summary without trace.
    #
    # Convert the IST day boundary INTO UTC and compare like with like. Also
    # switches from func.date() to a plain range comparison, which is
    # sargable — func.date() on the column defeats any index on created_at.
    day_start_utc = datetime.combine(today, dtime.min).replace(
        tzinfo=ist).astimezone(timezone.utc).replace(tzinfo=None)

    try:
        db = get_db()
        with db.Session() as session:
            trades = session.query(PaperTrade).filter(
                PaperTrade.created_at >= day_start_utc
            ).order_by(PaperTrade.created_at).all()

            if not trades:
                telegram_alerts.send_message(
                    "<b>Paper Trading EOD</b>\n"
                    f"{today.strftime('%d %b %Y')}\n\n"
                    "No paper trades today. Market conditions did not meet thresholds."
                )
                return

            total_buy_value = 0
            total_charges = 0
            lines = [
                f"<b>Paper Trading EOD Summary</b>",
                f"{today.strftime('%d %b %Y')}",
                f"━━━━━━━━━━━━━━━━━━",
                f"Trades: {len(trades)}",
                "",
            ]
            for t in trades:
                emoji = "BUY" if t.side == "BUY" else "SELL"
                val = t.price * t.quantity
                total_charges += t.charges or 0
                if t.side == "BUY":
                    total_buy_value += val
                lines.append(
                    f"{emoji} <b>{t.symbol}</b> x{t.quantity} @ ₹{t.price:.2f} "
                    f"(₹{val:,.0f}) | Charges: ₹{t.charges:.2f}"
                )

            lines.append(f"\nTotal deployed: ₹{total_buy_value:,.0f}")
            lines.append(f"Total charges: ₹{total_charges:.2f}")

            # Capital recommendation
            if total_buy_value > 0:
                # Add buffer for margin + charges
                recommended = int(total_buy_value * 1.3 + total_charges * 2)
                lines.append(f"\n<b>Recommended capital: ₹{recommended:,}</b>")
                lines.append("(based on today's trades + 30% buffer + charges)")

            telegram_alerts.send_message("\n".join(lines))
    except Exception as e:
        logger.warning("Paper EOD summary generation failed: %s", e)


def _task_telegram_daily_summary():
    """Send comprehensive daily summary via Telegram (once at ~15:30 IST)."""
    try:
        from db_manager import get_config
        if get_config("telegram_enabled", "false").lower() != "true":
            return
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        # Only send between 15:30-16:00 IST (right after market close)
        if not (now_ist.hour == 15 and 30 <= now_ist.minute <= 59):
            return
        from daily_summary import send_daily_summary
        send_daily_summary()
    except Exception as e:
        logger.warning("Telegram daily summary failed: %s", e)


def _task_build_daily_snapshots():
    """Build comprehensive end-of-day trading snapshots with REAL market data (1-min candles) after 4 PM."""
    try:
        from datetime import timezone, timedelta
        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist)
        
        # Only build snapshots between 4:05 PM - 4:30 PM IST (once per day)
        if not (now_ist.hour == 16 and 5 <= now_ist.minute <= 30):
            return
        
        # Check if already built today (prevent re-running)
        import json
        snapshots_path = '/Users/parthsharma/Desktop/Grow/daily_snapshots.json'
        if os.path.exists(snapshots_path):
            try:
                with open(snapshots_path, 'r') as f:
                    snapshots = json.load(f)
                # Check if snapshots are from today
                if snapshots and isinstance(snapshots, dict):
                    first_snapshot = next(iter(snapshots.values()), {})
                    snapshot_date = first_snapshot.get('date')
                    today_str = now_ist.date().strftime("%Y-%m-%d")
                    if snapshot_date == today_str:
                        logger.debug("Daily snapshots already built for today")
                        return
            except:
                pass
        
        logger.info("📊 Building daily trading snapshots with REAL market data (1-min candles)...")
        
        # Call the build endpoint which will attach real market candles
        import requests
        try:
            response = requests.post(
                'http://localhost:8000/api/paper-trading/build-daily-snapshots-with-candles',
                headers=_DEVICE_HEADERS,
                timeout=180
            )
            if response.status_code == 200:
                result = response.json()
                count = result.get('snapshots_count', 0)
                candles_count = result.get('candles_fetched', 0)
                logger.info(f"✓ Daily snapshots built: {count} symbols with {candles_count} 5-minute candles")
            else:
                logger.warning(f"Snapshot build failed: HTTP {response.status_code}")
        except Exception as e:
            logger.warning(f"Failed to build daily snapshots: {e}")
    
    except Exception as e:
        logger.warning("Daily snapshot task failed: %s", e)


# ── Scheduler engine ─────────────────────────────────────────────────────────

def _load_interval_overrides() -> dict:
    """
    Read every `scheduler_interval_*` override in ONE query.

    Called once per dispatch pass, never per task. Doing it per task meant ~29
    distinct keys every 15s — and because each key is different, the 30s memo in
    get_config could not dedupe them, so it was ~83,000 queries a day for values
    that almost never change. That is the exact "never call get_config in a
    loop" case in CLAUDE.md standard #1.

    Returns {} on any failure, so a config-table problem leaves the scheduler
    running on its compiled-in defaults rather than stopping.
    """
    try:
        from db_manager import get_configs_prefix
        return get_configs_prefix("scheduler_interval_") or {}
    except Exception as e:
        logger.debug("Could not batch-read scheduler interval overrides: %s", e)
        return {}


def _resolve_interval(overrides: dict, task_name: str, default_interval: int) -> int:
    """Pick a task's interval from a pre-loaded override map. No I/O."""
    raw = overrides.get(f"scheduler_interval_{task_name}")
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            logger.debug("Ignoring non-numeric interval override for %s: %r", task_name, raw)
    return default_interval


def _run_task_safe(task):
    """Run a single task with its own lock (prevents self-overlap)."""
    lock = _task_locks.get(task["name"])
    if lock and not lock.acquire(blocking=False):
        logger.debug("Skipping '%s' — still running from previous cycle", task["name"])
        return
    try:
        logger.debug("Scheduler running: %s", task["name"])
        task["fn"]()
        task["last_run"] = time.time()
    except Exception as e:
        logger.error("Scheduler task '%s' failed: %s", task["name"], e)
    finally:
        if lock:
            lock.release()


def _scheduler_loop():
    """Main scheduler loop — dispatches due tasks to thread pool."""
    global _pool
    _pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="sched")
    logger.info("Master scheduler started with %d tasks (pool=%d workers)", len(_tasks), MAX_WORKERS)

    # Wait for server to stabilize
    time.sleep(5)
    start_time = time.time()

    while True:
        # Check if paused via Telegram /stop command
        try:
            from telegram_commander import is_scheduler_paused
            if is_scheduler_paused():
                time.sleep(10)
                continue
        except Exception:
            pass

        now = time.time()
        elapsed = now - start_time
        # ONE query per pass for all interval overrides, not one per task.
        interval_overrides = _load_interval_overrides()
        for task in _tasks:
            # Honour initial_delay: skip until enough time has passed since start
            if not task["_started"]:
                if elapsed < task["initial_delay"]:
                    continue
                task["_started"] = True
                task["last_run"] = 0  # ensure it fires immediately once delay elapses

            interval = _resolve_interval(interval_overrides, task["name"], task["interval"])
            if now - task["last_run"] >= interval:
                # Submit to pool — non-blocking; lock prevents self-overlap
                _pool.submit(_run_task_safe, task)
                task["last_run"] = now  # mark scheduled (even if lock skips it)
        # Sleep 15s between checks (faster reaction to due tasks)
        time.sleep(15)


def start_scheduler():
    """
    Register all tasks and start the scheduler daemon thread.
    Call this once from app.py on startup.
    """
    # Register tasks — staggered initial_delay to avoid API rate-limit storm
    # Tier 1: Instant (0s) — lightweight / critical for dashboard
    _register("token_refresh",   _task_token_refresh, 3600, initial_delay=0)
    _register("fyers_token_refresh", _task_fyers_token_refresh, 3600, initial_delay=1)
    _register("self_healing", _task_self_healing, 3600, initial_delay=90)
    # initial_delay 0 -> 240: this is a bulk FYERS consumer (fundamentals
    # quotes for ~67 symbols x up to 6 quotes each on a cold cache). At 0 it
    # was the first task to fire on every restart, racing the boot warm-up.
    # 240s clears the warm-up's 150s timeout with margin.
    _register("cache_refresh",    _task_cache_refresh,  3600, initial_delay=240)
    _register("update_watchlist_prices", _task_update_watchlist_prices, 3600, initial_delay=10)

    # Tier 2: 5s — market data needed for predictions
    # Measured 51s for 73 symbols; runs hourly but no-ops while the market is
    # open and when a symbol is already current, so the real cost is one pass
    # after close. Offset clear of the retrains (T+150 / T+1800 / T+3000).
    # collect_5min_candles / sync_historical_candles / aggregate_candles_to_daily
    # were REMOVED here. All three were Groww-era and wrote to the legacy
    # `candles` table, which has had 0 rows since the FYERS migration — the
    # 5-minute collector had been inserting into a table nothing reads, every
    # 300s. fyers_daily_topup below is their replacement, and it targets
    # fyers_candles.
    _register("fyers_daily_topup", _task_fyers_daily_topup, 3600, initial_delay=200)  # End-of-day sync (after 3:30 PM IST)
    _register("record_pnl", _task_record_pnl, 5, initial_delay=8)  # Record P&L every 5 seconds

    # Tier 3: 15s — analysis that feeds the dashboard
    _register("auto_analysis",    _task_auto_analysis,  300, initial_delay=15)
    _register("news_prefetch",    _task_news_prefetch,   600, initial_delay=20)

    # Tier 4: 5s — trading tasks (need candles + predictions ready)
    _register("fno_auto_trade",   _task_fno_auto_trade,  5, initial_delay=2)
    _register("cash_auto_trade",      _task_cash_auto_trade,  5, initial_delay=3)
    _register("auto_close_trades", _task_auto_close_trades, 5, initial_delay=4)  # Check every 5s for TP/SL hits
    _register("fno_capital_sync", _task_fno_capital_sync, 600, initial_delay=40)

    # Maintenance: housekeeping, not a trading task despite sitting near them.
    _register("prune_idempotency", _task_prune_idempotency_keys, 3600, initial_delay=120)

    # Tier 5: 60s — secondary data feeds
    _register("global_indices",   _task_global_indices,  900, initial_delay=60)
    _register("world_news",      _task_world_news,    900, initial_delay=65)
    _register("geopolitical",     _task_geopolitical_collect, 1800, initial_delay=70)
    _register("supply_chain",     _task_supply_chain,    900, initial_delay=75)
    _register("telegram_summary",    _task_telegram_daily_summary, 1800, initial_delay=80)
    _register("paper_eod_summary",    _task_paper_eod_summary, 1800, initial_delay=85)
    _register("build_daily_snapshots", _task_build_daily_snapshots, 900, initial_delay=86)  # Check every 15 minutes after 4 PM
    # Cost scraper: every 45 days (3,888,000 seconds) with random 0-170s startup delay
    import random
    cost_scraper_delay = random.randint(0, 170)
    _register("cost_scraper", _task_cost_rate_update, 3888000, initial_delay=cost_scraper_delay)

    # Tier 6: 120s — heavy compute / rare tasks
    _register("deep_analysis",   _task_deep_analysis, 1800, initial_delay=120)
    _register("market_intelligence", _task_market_intelligence, 21600, initial_delay=130)
    _register("research_engine",     _task_research_engine, 14400, initial_delay=140)
    # ── Model retraining: STAGGERED, not concurrent ──────────────────────
    # Measured durations: GBC ~25 min (73 symbols), cash XGB ~4 min (65 x ~3s),
    # F&O XGB ~31 min (597k samples). These previously started 10 SECONDS
    # apart, so two ~30-minute jobs ran on top of each other, each holding
    # large frames in memory while the 5-second trade tasks kept firing.
    #
    # Offsets give each job its measured runtime plus margin before the next
    # begins:
    #   GBC       +150s   .. ~+1650s
    #   cash XGB  +1800s  .. ~+2100s   (30 min: after GBC finishes)
    #   F&O XGB   +2400s  .. ~+4300s   (40 min: after cash XGB finishes)
    # All three still run once every 86400s, so the daily cadence and the
    # relative spacing both hold on every subsequent day.
    # Offsets derived from MEASURED runtimes, not guessed (operational rule 5).
    #   ml_retrain       ~25 min  -> T+150  .. ~T+1650
    #   xgb_cash_retrain ~10.3min -> T+1800 .. ~T+2420   (73 symbols x ~8.5s,
    #                                full-history 5-minute bars, ~168.8k/symbol)
    #   retrain_xgb_daily ~31 min -> T+3000 .. ~T+4860
    # retrain_xgb_daily was T+2400, which the cash XGB retrain now overruns by
    # ~20s after moving from 365-day 1-minute to full-history 5-minute data.
    # Pushed to T+3000 for a ~580s buffer rather than letting two multi-minute
    # trainers stack on top of the 5-second trade tasks.
    _register("ml_retrain",        _task_ml_retrain,        86400, initial_delay=150)
    _register("xgb_cash_retrain",  _task_xgb_cash_retrain,  86400, initial_delay=1800)
    _register("retrain_xgb_daily", _task_retrain_xgb_daily, 86400, initial_delay=3000)
    _register("auto_metadata",       _task_auto_metadata, 604800, initial_delay=170)
    # Tijori supply-chain/fundamentals: check every 6h, refreshes only symbols
    # whose data is older than tijori.refresh_interval_days (config-driven)
    _register("tijori_refresh",      _task_tijori_refresh, 21600, initial_delay=180)

    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="master-scheduler")
    thread.start()
    logger.info("✓ Master scheduler running in background (%d tasks)", len(_tasks))
    return thread
