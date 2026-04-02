#!/usr/bin/env python3
"""
Retrain XGBoost models on all available candle data.
Works with current database state - no additional data generation needed.
"""

import logging
from datetime import datetime
from db_manager import CandleDatabase, Candle
from fno_backtester import _generate_xgb_training_data, FEATURE_NAMES

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

def retrain_models():
    """Retrain XGBoost models on all available data."""
    logger.info("=" * 80)
    logger.info("XGBoost Model Retraining")
    logger.info("=" * 80)
    
    try:
        import xgboost as xgb
    except ImportError:
        logger.error("XGBoost not installed")
        return False
    
    # Get training data
    logger.info("Generating training dataset...")
    X_train, y_train, dates = _generate_xgb_training_data()
    
    if X_train is None or len(X_train) == 0:
        logger.error("No training data available")
        return False
    
    logger.info(f"Training data prepared:")
    logger.info(f"  Samples: {len(X_train):,}")
    logger.info(f"  Features: {X_train.shape[1]}")
    logger.info(f"  Positive labels: {sum(y_train)} ({100*sum(y_train)/len(y_train):.1f}%)")
    logger.info("")
    
    # Train models
    logger.info("Training models...")
    
    models = {}
    for label in ["immediate", "conservative", "balanced"]:
        logger.info(f"  Training {label} model...")
        
        # Adjust target thresholds based on model type
        if label == "immediate":
            threshold = 0.5
        elif label == "conservative":
            threshold = 1.0
        else:  # balanced
            threshold = 0.75
        
        y_label = (y_train > threshold).astype(int)
        
        model = xgb.XGBClassifier(
            max_depth=7,
            learning_rate=0.1,
            n_estimators=150,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            tree_method='hist',
            device='cpu'
        )
        
        model.fit(X_train, y_label, verbose=False)
        models[label] = model
        
        # Get accuracy on training set
        accuracy = model.score(X_train, y_label)
        logger.info(f"    {label}: Accuracy {accuracy:.1%}")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("Training Complete")
    logger.info("=" * 80)
    logger.info(f"Timestamp: {datetime.now()}")
    logger.info(f"Trained on {len(X_train):,} samples with {X_train.shape[1]} features")
    logger.info("")
    
    # Save models
    try:
        import pickle
        import os
        
        cache_dir = "/tmp/xgb_models"
        os.makedirs(cache_dir, exist_ok=True)
        
        for label, model in models.items():
            path = f"{cache_dir}/xgb_{label}_model.pkl"
            with open(path, 'wb') as f:
                pickle.dump(model, f)
            logger.info(f"✓ Saved {label} model to {path}")
            
    except Exception as e:
        logger.error(f"Failed to save models: {e}")
    
    return True

if __name__ == "__main__":
    retrain_models()
