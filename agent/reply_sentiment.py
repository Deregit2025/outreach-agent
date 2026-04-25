"""
reply_sentiment.py — Prospect reply sentiment analysis.

Uses DistilBERT fine-tuned on SST-2 for binary sentiment classification,
then maps to a continuous score and action recommendation.

Model: distilbert-base-uncased-finetuned-sst-2-english (~268 MB)
  - Downloads automatically on first call via HuggingFace cache
  - Inference: ~0.3–0.5s per reply on CPU          

Output drives absorb_reply() in decision_engine.py:
  - "positive" + high score → accelerate (move toward booking)
  - "negative" + low score  → objection handling (softer approach)
  - "neutral"               → continue current cadence

Falls back gracefully if transformers is unavailable.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

SentimentLabel = Literal["positive", "negative", "neutral"]


class SentimentResult(TypedDict):
    sentiment: SentimentLabel
    score: float               # 0.0 (negative) → 1.0 (positive)
    confidence: float          # model confidence in the label
    suggested_tone_shift: str  # "accelerate" | "objection_handling" | "continue" | "hedge"
    model: str                 # which model produced the result


@lru_cache(maxsize=1)
def _load_pipeline():
    """Load DistilBERT sentiment pipeline (cached per process)."""
    from transformers import pipeline  # type: ignore
    return pipeline(
        "sentiment-analysis",
        model="distilbert-base-uncased-finetuned-sst-2-english",
        truncation=True,
        max_length=512,
    )


def analyze_sentiment(reply_text: str) -> SentimentResult:
    """
    Classify the sentiment of a prospect reply.

    Args:
        reply_text: Raw email or SMS reply body from the prospect

    Returns: 
        SentimentResult with score, label, and action recommendation
    """
    if not reply_text or not reply_text.strip():
        return SentimentResult(
            sentiment="neutral",
            score=0.5,
            confidence=0.0,
            suggested_tone_shift="continue",
            model="none",
        )

    try:
        pipe = _load_pipeline()
        result = pipe(reply_text[:512])[0]  # truncate to model max length

        label = result["label"].lower()   # "positive" or "negative"
        raw_confidence = float(result["score"])

        # Map to continuous score
        if label == "positive":
            score = 0.5 + (raw_confidence - 0.5) * 1.0  # 0.5 → 1.0
        else:
            score = 0.5 - (raw_confidence - 0.5) * 1.0  # 0.5 → 0.0

        score = max(0.0, min(1.0, round(score, 3)))

        # Determine sentiment label with neutral band
        if score >= 0.65:
            sentiment: SentimentLabel = "positive"
        elif score <= 0.35:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # Recommend tone shift
        if score >= 0.70:
            tone_shift = "accelerate"       # warm reply → move faster
        elif score >= 0.55:
            tone_shift = "continue"         # mildly positive → keep pace
        elif score >= 0.40:
            tone_shift = "hedge"            # lukewarm → soften slightly
        else:
            tone_shift = "objection_handling"  # cold/negative → handle objection

        return SentimentResult(
            sentiment=sentiment,
            score=score,
            confidence=round(raw_confidence, 3),
            suggested_tone_shift=tone_shift,
            model="distilbert-base-uncased-finetuned-sst-2-english",
        )

    except Exception as exc:
        logger.warning("Sentiment analysis failed: %s — returning neutral", exc)
        return SentimentResult(
            sentiment="neutral",
            score=0.5,
            confidence=0.0,
            suggested_tone_shift="continue",
            model="fallback",
        )
