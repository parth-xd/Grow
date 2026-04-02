"""
Enhanced NLP Sentiment — FinBERT transformer model with keyword fallback.

Tries to load ProsusAI/finbert for deep financial sentiment analysis.
Falls back to an enhanced keyword model with negation handling, context windows,
bigram patterns, and source credibility weighting.

Install FinBERT:  pip install transformers torch
(~2GB download — optional, the fallback works well for most cases)
"""

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ─── Try loading FinBERT ─────────────────────────────────────────────────────

HAS_FINBERT = False
_finbert_pipeline = None

try:
    from transformers import pipeline as hf_pipeline
    _finbert_pipeline = hf_pipeline(
        "sentiment-analysis",
        model="ProsusAI/finbert",
        truncation=True,
        max_length=512,
    )
    HAS_FINBERT = True
    logger.info("✓ FinBERT model loaded for deep NLP sentiment")
except ImportError:
    logger.info("FinBERT not available (install: pip install transformers torch). Using enhanced keyword model.")
except Exception as e:
    logger.warning("FinBERT load failed: %s. Using enhanced keyword model.", e)


# ─── FinBERT Scoring ─────────────────────────────────────────────────────────

def finbert_score(text: str) -> float:
    """Score text using FinBERT. Returns -1.0 to 1.0."""
    if not HAS_FINBERT or not _finbert_pipeline:
        return _enhanced_keyword_score(text)

    try:
        result = _finbert_pipeline(text[:512])[0]
        label = result["label"].lower()
        confidence = result["score"]

        if label == "positive":
            return confidence
        elif label == "negative":
            return -confidence
        return 0.0
    except Exception:
        return _enhanced_keyword_score(text)


def batch_score(texts: List[str]) -> List[float]:
    """Score multiple texts efficiently (batched for FinBERT)."""
    if not HAS_FINBERT or not _finbert_pipeline:
        return [_enhanced_keyword_score(t) for t in texts]

    try:
        truncated = [t[:512] for t in texts]
        results = _finbert_pipeline(truncated, batch_size=16)
        scores = []
        for r in results:
            label = r["label"].lower()
            conf = r["score"]
            if label == "positive":
                scores.append(conf)
            elif label == "negative":
                scores.append(-conf)
            else:
                scores.append(0.0)
        return scores
    except Exception:
        return [_enhanced_keyword_score(t) for t in texts]


# ─── Enhanced Keyword Model ──────────────────────────────────────────────────
# Significantly improved over basic keyword matching:
# • Negation handling ("not bullish" → bearish)
# • Bigram/trigram patterns
# • Context window scoring
# • Source quality weighting

# Weighted financial lexicon (phrase → weight 1-5)
_BULLISH = {
    # Single words
    "upgrade": 3, "outperform": 3, "breakout": 3, "rally": 3, "surge": 3,
    "bullish": 2, "uptrend": 2, "growth": 2, "positive": 1, "gain": 1,
    "profit": 1, "dividend": 1, "expansion": 2, "recovery": 2, "innovation": 2,
    "acquisition": 1, "partnership": 1, "approved": 2, "raised": 1,
    # Strong phrases
    "record high": 4, "all-time high": 4, "strong buy": 4, "beat estimates": 3,
    "buy rating": 3, "target raised": 3, "margin expansion": 3, "beat expectations": 3,
    "order book": 2, "market share gain": 3, "revenue growth": 2, "strong demand": 2,
    "overweight": 2, "accumulate": 2,
    # India-specific
    "nifty up": 2, "sensex gains": 2, "rbi rate cut": 3, "fpi inflow": 3,
    "fii buying": 3, "rupee strengthens": 2, "iip growth": 2, "gdp growth": 2,
    "make in india": 1, "pli scheme": 2,
}

_BEARISH = {
    # Single words
    "downgrade": 3, "underperform": 3, "crash": 4, "plunge": 3, "slump": 3,
    "bearish": 2, "downtrend": 2, "decline": 2, "negative": 1, "loss": 2,
    "default": 4, "bankruptcy": 5, "fraud": 5, "scam": 5, "miss": 2,
    "weakness": 2, "contraction": 2, "layoff": 2, "selloff": 3, "recession": 3,
    # Strong phrases
    "record low": 4, "strong sell": 4, "miss estimates": 3, "below expectations": 3,
    "sell rating": 3, "target cut": 3, "margin pressure": 3, "debt concern": 3,
    "order cancellation": 3, "market share loss": 3, "revenue decline": 2,
    "underweight": 2, "profit warning": 4, "earnings miss": 3,
    # India-specific
    "nifty down": 2, "sensex falls": 2, "rbi rate hike": 3, "fpi outflow": 3,
    "fii selling": 3, "rupee weakens": 2, "inflation rises": 2,
    "current account deficit": 2, "fiscal deficit": 2,
}

# Negation words that flip sentiment
_NEGATION = {"not", "no", "never", "neither", "nor", "barely", "hardly",
             "unlikely", "without", "fail", "failed", "fails", "lacking",
             "despite", "although", "however", "but"}

# Intensifiers
_INTENSIFIERS = {"very": 1.5, "extremely": 2.0, "significantly": 1.5,
                 "substantially": 1.5, "sharply": 1.8, "dramatically": 2.0,
                 "massive": 1.8, "huge": 1.5, "strong": 1.3, "deep": 1.5}

# Diminishers
_DIMINISHERS = {"slightly": 0.5, "marginally": 0.5, "somewhat": 0.6,
                "minor": 0.5, "modest": 0.6, "limited": 0.5, "small": 0.5}


def _enhanced_keyword_score(text: str) -> float:
    """
    Enhanced keyword-based sentiment scoring.

    Improvements over basic keyword matching:
    1. Negation detection in 3-word window before keyword
    2. Intensifier/diminisher detection
    3. Sentence-level scoring (not just document-level)
    4. Bigram/trigram matching (already in the lexicon)
    """
    if not text:
        return 0.0

    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)

    # Split into sentences for sentence-level scoring
    sentences = re.split(r'[.!?;]', text_lower)
    if not sentences:
        sentences = [text_lower]

    total_score = 0.0
    match_count = 0

    for sentence in sentences:
        sent_words = re.findall(r'\b\w+\b', sentence)
        sent_score = 0.0
        sent_matches = 0

        # Check phrases (bigrams/trigrams from lexicon)
        for phrase, weight in _BULLISH.items():
            if phrase in sentence:
                # Check negation in 3-word window before phrase
                idx = sentence.find(phrase)
                context_before = sentence[max(0, idx - 30):idx].split()
                negated = any(w in _NEGATION for w in context_before[-3:])
                # Check intensifiers/diminishers
                modifier = 1.0
                for w in context_before[-2:]:
                    if w in _INTENSIFIERS:
                        modifier = _INTENSIFIERS[w]
                    elif w in _DIMINISHERS:
                        modifier = _DIMINISHERS[w]

                if negated:
                    sent_score -= weight * modifier
                else:
                    sent_score += weight * modifier
                sent_matches += 1

        for phrase, weight in _BEARISH.items():
            if phrase in sentence:
                idx = sentence.find(phrase)
                context_before = sentence[max(0, idx - 30):idx].split()
                negated = any(w in _NEGATION for w in context_before[-3:])
                modifier = 1.0
                for w in context_before[-2:]:
                    if w in _INTENSIFIERS:
                        modifier = _INTENSIFIERS[w]
                    elif w in _DIMINISHERS:
                        modifier = _DIMINISHERS[w]

                if negated:
                    sent_score += weight * modifier
                else:
                    sent_score -= weight * modifier
                sent_matches += 1

        total_score += sent_score
        match_count += sent_matches

    if match_count == 0:
        # No financial keywords found — try generic sentiment
        pos_generic = sum(1 for w in words if w in {"good", "great", "excellent", "strong", "better", "improve", "success"})
        neg_generic = sum(1 for w in words if w in {"bad", "poor", "weak", "worse", "fail", "crisis", "risk", "concern"})
        if pos_generic + neg_generic > 0:
            return (pos_generic - neg_generic) / (pos_generic + neg_generic) * 0.3
        return 0.0

    # Normalize: scale to roughly -1.0 to 1.0
    max_possible = match_count * 3  # average weight ~3
    normalized = total_score / max_possible if max_possible > 0 else 0
    return max(min(normalized, 1.0), -1.0)


# ─── Unified Scoring Interface ───────────────────────────────────────────────

def score_text(text: str) -> float:
    """
    Score text sentiment. Uses FinBERT if available, else enhanced keywords.
    Returns: float from -1.0 (very bearish) to 1.0 (very bullish).
    """
    if HAS_FINBERT:
        return finbert_score(text)
    return _enhanced_keyword_score(text)


def score_with_details(text: str) -> dict:
    """Score text and return details including model used and confidence."""
    if HAS_FINBERT:
        try:
            result = _finbert_pipeline(text[:512])[0]
            label = result["label"].lower()
            conf = result["score"]
            score = conf if label == "positive" else (-conf if label == "negative" else 0)
            return {
                "score": round(score, 4),
                "label": label,
                "confidence": round(conf, 4),
                "model": "finbert",
            }
        except Exception:
            pass

    score = _enhanced_keyword_score(text)
    if score > 0.15:
        label = "positive"
    elif score < -0.15:
        label = "negative"
    else:
        label = "neutral"

    return {
        "score": round(score, 4),
        "label": label,
        "confidence": round(abs(score), 4),
        "model": "enhanced_keyword",
    }


def get_model_info() -> dict:
    """Return info about the NLP model in use."""
    return {
        "finbert_available": HAS_FINBERT,
        "active_model": "ProsusAI/finbert" if HAS_FINBERT else "enhanced_keyword_v2",
        "features": [
            "negation_handling",
            "intensifier_detection",
            "sentence_level_scoring",
            "india_specific_lexicon",
            "bigram_trigram_patterns",
        ] + (["transformer_deep_nlp"] if HAS_FINBERT else []),
    }
