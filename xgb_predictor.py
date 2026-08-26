"""
XGBoost cash-equity predictor — a second, independent model alongside the
existing sklearn GradientBoostingClassifier.

DESIGN: this is a DROP-IN SECOND MODEL, not a new strategy.

It deliberately reuses predictor.py's existing pieces verbatim:
  - build_features()  — same features
  - create_labels()   — same cost-aware BUY/HOLD/SELL labels, same horizon
  - PricePredictor.train()/predict() — inherited unchanged

Only the estimator differs. Nothing about the strategy, thresholds, signal
cadence or exit rules is altered here, and predictor.py is not modified at
all, so the GradientBoosting path cannot regress.

The one genuine technical incompatibility: XGBClassifier requires class
labels in 0..n-1, while this codebase's labels are -1 (SELL) / 0 (HOLD) /
1 (BUY). _XGBLabelAdapter translates in both directions so the inherited
train()/predict() — which assume sklearn's tolerance for -1 — keep working
untouched.

Artifacts live in models/xgb_cash/ so they can never collide with the
GradientBoosting models (models/*.joblib) or the F&O XGB model
(models/xgb_backtester.joblib).
"""

import logging
import os

import numpy as np

from predictor import PricePredictor

logger = logging.getLogger(__name__)

# Separate directory — cash XGB artifacts must not mix with GBC or F&O.
XGB_CASH_MODELS_DIR = os.path.join(os.path.dirname(__file__), "models", "xgb_cash")

MODEL_SOURCE_GBC = "GradientBoosting"
MODEL_SOURCE_XGB = "XGBoost"


class _XGBLabelAdapter:
    """
    Wraps XGBClassifier so it presents the sklearn API this codebase already
    expects, including support for the -1/0/1 label convention.

    XGBoost needs contiguous 0-based classes; mapping happens here rather
    than in PricePredictor so the inherited train()/predict() need no changes.
    """

    def __init__(self, **params):
        from xgboost import XGBClassifier
        self._clf = XGBClassifier(**params)
        self._classes = None          # sorted original labels, e.g. [-1, 0, 1]

    def fit(self, X, y):
        y = np.asarray(y)
        self._classes = np.unique(y)
        encoded = np.searchsorted(self._classes, y)

        # Balanced sample weights. The strategy's cost-aware labels are
        # imbalanced by construction. Measured across 5 liquid names:
        # 1-minute bars gave a median 0.18% minority (165 BUY+SELL in 91k
        # rows); full-history 5-minute bars give 1.41% (1,303 in 92k). The
        # bar width matters because create_labels() uses a 5-BAR horizon —
        # 5 minutes on 1-minute bars, where price rarely clears the
        # cost-aware breakeven, versus 25 minutes on 5-minute bars. Even at
        # 1.41%, unweighted XGBoost minimises loss by predicting HOLD every
        # time and scores ~0.986 while being useless.
        #
        # This weights classes inversely to frequency at FIT time only. The
        # labels themselves are untouched — same create_labels(), same
        # threshold, same horizon — so this is a model-fitting fix, not a
        # strategy change. sklearn's GradientBoostingClassifier is left
        # exactly as it was.
        counts = np.bincount(encoded, minlength=len(self._classes)).astype(float)
        counts[counts == 0] = 1.0
        class_w = counts.sum() / (len(self._classes) * counts)
        sample_w = class_w[encoded]

        self._clf.fit(X, encoded, sample_weight=sample_w)
        return self

    def predict(self, X):
        encoded = self._clf.predict(X)
        return self._classes[np.asarray(encoded, dtype=int)]

    def predict_proba(self, X):
        return self._clf.predict_proba(X)

    def score(self, X, y):
        y = np.asarray(y)
        return float((self.predict(X) == y).mean())

    @property
    def classes_(self):
        return self._classes

    @property
    def feature_importances_(self):
        return getattr(self._clf, "feature_importances_", None)


class XGBPricePredictor(PricePredictor):
    """
    Same features, same labels, same train/predict flow as PricePredictor —
    only the estimator changes. Hyperparameters mirror the GBC's shape
    (depth 4, lr 0.05, 200 trees) so the comparison isolates the algorithm
    rather than confounding it with a different capacity budget.
    """

    model_source = MODEL_SOURCE_XGB

    def __init__(self):
        super().__init__()          # sets scaler / is_trained / feature_columns
        self.model = _XGBLabelAdapter(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=2,               # bounded: training runs across ~70 symbols
            eval_metric="mlogloss",
            tree_method="hist",
        )


def model_path(symbol):
    return os.path.join(XGB_CASH_MODELS_DIR, f"{symbol}.joblib")


def load_model(symbol):
    """Load a persisted cash XGB model, or None."""
    import joblib
    path = model_path(symbol)
    if not os.path.exists(path):
        return None
    try:
        return joblib.load(path)
    except Exception as e:
        logger.debug("Failed to load XGB model for %s: %s", symbol, e)
        return None


def save_model(symbol, predictor):
    """
    Persist a trained model ATOMICALLY.

    joblib.dump() straight onto the final path is not safe: a crash, a kill,
    or a full disk mid-write leaves a truncated .joblib that loads as a
    corrupt model rather than as a missing one — so the symbol silently
    serves garbage instead of falling back to a retrain. Writing to a temp
    file in the same directory and os.replace()-ing it means readers only
    ever see a complete file (rename is atomic within a filesystem).

    Callers must only reach here after a successful train() — see
    bot.train_xgb_model, which checks result["success"] first.
    """
    import joblib
    import tempfile
    os.makedirs(XGB_CASH_MODELS_DIR, exist_ok=True)
    final = model_path(symbol)
    fd, tmp = tempfile.mkstemp(dir=XGB_CASH_MODELS_DIR, prefix=f".{symbol}_", suffix=".joblib")
    os.close(fd)
    try:
        joblib.dump(predictor, tmp)
        os.replace(tmp, final)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise
