"""
tone_preservation.py — Score a draft message against Tenacious style guide.

Act IV mechanism: a second lightweight check that detects tone drift from the
Tenacious voice before the message is sent. If the score falls below the threshold,
the draft is flagged for regeneration.

This avoids the top Act III failure mode: tone drift after 3-4 turns of back-and-forth,
where the agent slips into sales-speak, over-promises, or uses the prohibited phrases
from style_guide.md.

Scoring heuristics (deterministic, no LLM call):
  1. Prohibited phrase detection (hard penalty)
  2. Required tone markers present (positive score)
  3. Sentence length distribution (< 25 words avg = good)
  4. Assertive vs. question balance (at least one question per email)
  5. Over-commitment detection (bench capacity claims)

LLM-assisted re-scoring is available via check_tone_with_llm() for high-stakes
messages, with explicit cost warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STYLE_GUIDE_PATH = (
    PROJECT_ROOT / "data" / "tenacious_sales_data" / "seed" / "style_guide.md"
)

# Loaded once at import time
_STYLE_GUIDE_TEXT: str = ""


def _load_style_guide() -> str:
    global _STYLE_GUIDE_TEXT
    if _STYLE_GUIDE_TEXT:
        return _STYLE_GUIDE_TEXT
    if STYLE_GUIDE_PATH.exists():
        _STYLE_GUIDE_TEXT = STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    return _STYLE_GUIDE_TEXT


# ── Tone markers extracted from style_guide.md ───────────────────────────────

PROHIBITED_PHRASES: list[str] = [
    # Over-promising
    "guaranteed", "100%", "best in class", "world-class", "industry-leading",
    "game-changer", "revolutionary", "disruptive",
    # Pressure tactics
    "limited time", "act now", "don't miss out", "urgent",
    # Vague filler
    "synergize", "leverage our expertise", "holistic", "paradigm",
    "turn-key solution", "end-to-end solution",
    # Offshore sensitivity — never lead with "cheap"
    "cheap offshore", "low-cost offshore", "cheap talent",
    "outsource everything", "replace your team",
    # Condescending gap language
    "you are behind", "your competitors are beating you",
    "you are failing", "you clearly need",
]

REQUIRED_TONE_MARKERS: list[str] = [
    # Grounded, evidence-based opener signals
    "noticed", "saw", "based on", "data", "signal", "public",
    # Collaborative, not sales-y
    "happy to", "make sense", "if useful", "let me know",
    "worth a conversation", "curious", "would it make sense",
    # Specific value — shows research
    "engineering", "team", "delivery", "capacity", "stack",
]

# Hard stops — bench over-commitment patterns
OVERCOMMIT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(unlimited|any\s+size|whatever\s+you\s+need|as\s+many\s+as)\b", re.I),
    re.compile(r"\b(guarantee\s+\d+\s+engineers?|promise\s+\d+)\b", re.I),
    re.compile(r"\bwe\s+(have|can\s+provide)\s+\d{2,}\s+engineers?\b", re.I),
]


@dataclass
class ToneCheckResult:
    score: float                    # 0.0–1.0
    passed: bool                    # score >= threshold
    threshold: float
    prohibited_hits: list[str] = field(default_factory=list)
    tone_marker_count: int = 0
    overcommit_hits: list[str] = field(default_factory=list)
    avg_sentence_length: float = 0.0
    has_question: bool = False
    flags: list[str] = field(default_factory=list)


def check_tone(
    draft: str,
    threshold: float = 0.60,
) -> ToneCheckResult:
    """
    Score a draft against Tenacious tone requirements.

    Returns ToneCheckResult; if .passed is False, the caller should regenerate.
    """
    if not draft.strip():
        return ToneCheckResult(score=0.0, passed=False, threshold=threshold)

    text_lower = draft.lower()
    flags: list[str] = []

    # 1. Prohibited phrase detection (hard -0.15 per hit)
    prohibited_hits: list[str] = []
    for phrase in PROHIBITED_PHRASES:
        if phrase.lower() in text_lower:
            prohibited_hits.append(phrase)
    prohibited_penalty = min(len(prohibited_hits) * 0.15, 0.60)

    # 2. Required tone markers (up to +0.30 bonus)
    marker_count = sum(1 for m in REQUIRED_TONE_MARKERS if m.lower() in text_lower)
    marker_bonus = min(marker_count * 0.04, 0.30)

    # 3. Sentence length distribution
    sentences = re.split(r"[.!?]+", draft)
    sentences = [s.strip() for s in sentences if s.strip()]
    if sentences:
        word_counts = [len(s.split()) for s in sentences]
        avg_len = sum(word_counts) / len(word_counts)
    else:
        avg_len = 0.0
    # Penalty for very long sentences (average > 30 words)
    length_penalty = max(0.0, (avg_len - 30) * 0.01) if avg_len > 30 else 0.0

    # 4. Question presence (at least one question = good practice)
    has_question = "?" in draft
    question_bonus = 0.05 if has_question else 0.0
    if not has_question:
        flags.append("No question in message — consider ending with a clear question.")

    # 5. Over-commitment detection (hard -0.20 per hit)
    overcommit_hits: list[str] = []
    for pat in OVERCOMMIT_PATTERNS:
        m = pat.search(draft)
        if m:
            overcommit_hits.append(m.group(0))
    overcommit_penalty = min(len(overcommit_hits) * 0.20, 0.40)

    if prohibited_hits:
        flags.append(
            f"Prohibited phrases detected: {', '.join(prohibited_hits[:3])}. "
            f"Remove before sending."
        )
    if overcommit_hits:
        flags.append(
            f"Potential bench over-commitment language: {', '.join(overcommit_hits)}. "
            f"Verify against bench_summary.json."
        )

    # Base score starts at 0.70; adjust up/down
    base = 0.70
    score = base + marker_bonus + question_bonus - prohibited_penalty - length_penalty - overcommit_penalty
    score = max(0.0, min(1.0, score))

    return ToneCheckResult(
        score=round(score, 3),
        passed=score >= threshold,
        threshold=threshold,
        prohibited_hits=prohibited_hits,
        tone_marker_count=marker_count,
        overcommit_hits=overcommit_hits,
        avg_sentence_length=round(avg_len, 1),
        has_question=has_question,
        flags=flags,
    )


def suggest_rewrite_patches(result: ToneCheckResult, draft: str) -> list[str]:
    """
    Return a list of targeted rewrite suggestions when tone check fails.
    These are passed to the LLM regeneration prompt as constraints.
    """
    patches: list[str] = []

    for phrase in result.prohibited_hits:
        patches.append(f"Remove '{phrase}' — not in Tenacious voice.")

    for hit in result.overcommit_hits:
        patches.append(
            f"Replace '{hit}' with specific capacity language from bench_summary.json."
        )

    if not result.has_question:
        patches.append(
            "End the message with a specific question (e.g., 'Would a 20-minute "
            "conversation make sense?')."
        )

    if result.avg_sentence_length > 30:
        patches.append(
            "Shorten sentences — target under 25 words average. "
            "Split any sentence over 40 words."
        )

    return patches


async def check_tone_with_llm(
    draft: str,
    style_guide: Optional[str] = None,
    model: Optional[str] = None,
) -> ToneCheckResult:
    """
    LLM-assisted tone check. More expensive (~0.5s, ~500 tokens).

    Only call for high-stakes messages (Segment 3 leadership transitions,
    first-touch to prospects in senior roles).

    Falls back to deterministic check_tone() if LLM call fails.
    """
    base_result = check_tone(draft)
    if not model:
        return base_result

    guide = style_guide or _load_style_guide()
    if not guide:
        return base_result

    try:
        import litellm  # type: ignore

        prompt = (
            f"You are a tone auditor for Tenacious Consulting.\n"
            f"Style guide summary:\n{guide[:800]}\n\n"
            f"Draft message:\n{draft[:1200]}\n\n"
            f"Rate this draft 0–10 on: (1) Tenacious voice fidelity, "
            f"(2) absence of over-claiming, (3) grounded specificity. "
            f"Respond with JSON: {{\"score\": <float 0-1>, \"issues\": [\"...\"]}}. "
            f"No other text."
        )
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )
        import json
        data = json.loads(resp.choices[0].message.content)
        llm_score = float(data.get("score", base_result.score))
        issues = data.get("issues", [])

        # Blend LLM score (60%) with deterministic score (40%)
        blended = round(0.6 * llm_score + 0.4 * base_result.score, 3)
        base_result.score = blended
        base_result.passed = blended >= base_result.threshold
        base_result.flags.extend(issues)
        return base_result

    except Exception:
        return base_result
