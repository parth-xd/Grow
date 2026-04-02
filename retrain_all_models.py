#!/usr/bin/env python3
"""
Retrain all ML models on the latest 5-minute candle data.
Runs both GradientBoosting (PricePredictor) and XGBoost (F&O) retraining.
"""

import logging
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)


def retrain_gradient_boosting():
    """Retrain PricePredictor (GradientBoosting) for all watchlist stocks."""
    from config import WATCHLIST
    import bot

    logger.info("=" * 60)
    logger.info("RETRAINING GradientBoosting (PricePredictor)")
    logger.info("=" * 60)

    results = {"success": 0, "failed": 0}
    for i, symbol in enumerate(WATCHLIST, 1):
        try:
            result = bot.train_model(symbol)
            if result.get("success"):
                logger.info(f"[{i}/{len(WATCHLIST)}] {symbol}: ✓ {result.get('message', '')} "
                           f"(accuracy={result.get('accuracy', '?')})")
                results["success"] += 1
            else:
                logger.warning(f"[{i}/{len(WATCHLIST)}] {symbol}: ✗ {result.get('message', 'unknown')}")
                results["failed"] += 1
        except Exception as e:
            logger.error(f"[{i}/{len(WATCHLIST)}] {symbol}: ✗ {e}")
            results["failed"] += 1

    logger.info(f"GradientBoosting: {results['success']} trained, {results['failed']} failed")
    return results


def retrain_xgboost():
    """Retrain XGBoost F&O models."""
    logger.info("=" * 60)
    logger.info("RETRAINING XGBoost (F&O)")
    logger.info("=" * 60)

    try:
        import xgboost as xgb
        import numpy as np
        from fno_backtester import _generate_xgb_training_data, FEATURE_NAMES
        import fno_backtester

        X, y_long, y_short = _generate_xgb_training_data()
        logger.info(f"Training data: {len(X)} samples")

        if len(X) < 100:
            logger.warning("Insufficient training data")
            return {"success": False}

        X = np.array(X, dtype=np.float32)
        y_long = np.array(y_long)
        y_short = np.array(y_short)

        lp, sp = int(y_long.sum()), int(y_short.sum())
        logger.info(f"Long wins: {lp} ({lp/len(X)*100:.1f}%), Short wins: {sp} ({sp/len(X)*100:.1f}%)")

        params = dict(
            n_estimators=150, max_depth=3, learning_rate=0.08,
            subsample=0.8, colsample_bytree=0.8,
            reg_alpha=1.0, reg_lambda=2.0, min_child_weight=5,
            random_state=42, eval_metric='logloss',
        )

        long_model = xgb.XGBClassifier(
            scale_pos_weight=max(1.0, (len(y_long) - lp) / max(1, lp)), **params
        )
        long_model.fit(X, y_long)

        short_model = xgb.XGBClassifier(
            scale_pos_weight=max(1.0, (len(y_short) - sp) / max(1, sp)), **params
        )
        short_model.fit(X, y_short)

        fno_backtester._xgb_models = {"long": long_model, "short": short_model}
        fno_backtester._xgb_model_timestamp = datetime.now()

        # Log top features
        for tag, mdl in [("LONG", long_model), ("SHORT", short_model)]:
            imp = mdl.feature_importances_
            top5 = sorted(zip(FEATURE_NAMES, imp), key=lambda x: -x[1])[:5]
            logger.info(f"XGB {tag} top features: {', '.join(f'{n}={v:.3f}' for n, v in top5)}")

        logger.info("✓ XGBoost models retrained successfully")
        return {"success": True, "samples": len(X), "long_wins": lp, "short_wins": sp}

    except Exception as e:
        logger.error(f"XGBoost retraining failed: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    start = time.time()

    logger.info("=" * 60)
    logger.info("FULL MODEL RETRAIN ON 5-MINUTE CANDLE DATA")
    logger.info(f"Started: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    gb_results = retrain_gradient_boosting()
    xgb_results = retrain_xgboost()

    elapsed = time.time() - start
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"RETRAIN COMPLETE in {elapsed:.1f}s")
    logger.info(f"GradientBoosting: {gb_results['success']} models trained")
    logger.info(f"XGBoost F&O: {'✓' if xgb_results.get('success') else '✗'}")
    logger.info("=" * 60)
