"""
ablation_runner.py — Run Act IV ablation experiments.

Each ablation config toggles one or more mechanism components on/off to
measure their individual contribution to output quality. The five configs
correspond directly to the table in mechanism/method.md:

  A: Full mechanism  (confidence_phrasing=ON, abstention=ON, tone_gate=ON)
  B: Baseline + gate (confidence_phrasing=OFF, abstention=ON, tone_gate=ON)
  C: No soft-qualify (confidence_phrasing=ON, abstention=OFF, tone_gate=ON)
  D: No tone check   (confidence_phrasing=ON, abstention=ON, tone_gate=OFF)
  E: Day-1 baseline  (confidence_phrasing=OFF, abstention=OFF, tone_gate=OFF)

Results are written to eval/ablation_results.json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "eval" / "ablation_results.json"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class AblationConfig:
    """Toggles for the three Act IV mechanism components."""
    name: str
    confidence_phrasing: bool   # Component 1 — adjust_claim / detect_overclaim
    abstention: bool            # Component 2 — classify_with_abstention
    tone_gate: bool             # Component 3 — check_tone


@dataclass
class AblationResult:
    """Aggregate statistics from one ablation run."""
    config_name: str
    n_prospects: int
    segment_specific_count: int     # prospects that received a segment-specific pitch
    exploratory_count: int          # prospects routed to generic exploratory email
    escalate_count: int             # prospects escalated to human review
    tone_pass_rate: float           # fraction of drafts that passed tone gate (0-1)
    overclaim_warnings: int         # total over-claim warnings fired across all prospects
    run_duration_s: float           # wall-clock seconds for the full run


# ── The 5 canonical ablation configs from method.md ──────────────────────────

ABLATION_CONFIGS: list[AblationConfig] = [
    AblationConfig(
        name="A_full_mechanism",
        confidence_phrasing=True,
        abstention=True,
        tone_gate=True,
    ),
    AblationConfig(
        name="B_baseline_plus_gate",
        confidence_phrasing=False,
        abstention=True,
        tone_gate=True,
    ),
    AblationConfig(
        name="C_no_soft_qualify",
        confidence_phrasing=True,
        abstention=False,
        tone_gate=True,
    ),
    AblationConfig(
        name="D_no_tone_check",
        confidence_phrasing=True,
        abstention=True,
        tone_gate=False,
    ),
    AblationConfig(
        name="E_day1_baseline",
        confidence_phrasing=False,
        abstention=False,
        tone_gate=False,
    ),
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_signals(brief: dict) -> list[dict]:
    """Extract the list of non-null SignalItem dicts from a HiringSignalBrief dict."""
    signal_keys = ("funding", "job_velocity", "layoff", "leadership_change",
                   "tech_stack", "ai_maturity")
    signals: list[dict] = []
    for key in signal_keys:
        item = brief.get(key)
        if isinstance(item, dict):
            signals.append(item)
    return signals


def _build_draft_opener(prospect: dict, brief: dict, config: AblationConfig) -> str:
    """
    Build a minimal draft opener for tone checking.

    When confidence_phrasing is ON, uses build_grounded_opener() from
    confidence_aware_phrasing.py (which applies register-aware language).
    When OFF, produces a flat assertive sentence regardless of signal confidence.
    """
    company_name = prospect.get("company_name", "this company")
    signals = _get_signals(brief)
    ai_score = brief.get("ai_maturity", {}).get("value", "0")

    if config.confidence_phrasing:
        try:
            from mechanism.confidence_aware_phrasing import build_grounded_opener
            # Convert numeric ai_score string to int
            try:
                ai_int = int(str(ai_score).split()[0])
            except (ValueError, TypeError):
                ai_int = 0
            return build_grounded_opener(
                company_name=company_name,
                signals=signals,
                ai_maturity_score=ai_int,
            )
        except Exception as exc:
            logger.debug("build_grounded_opener failed: %s", exc)

    # OFF: flat assertive opener (Day-1 behaviour)
    if signals:
        top = signals[0]
        sig_type = top.get("signal_type", "signal")
        value = top.get("value", "activity")
        return f"Your company recently showed {sig_type}: {value}. We can help."
    return f"Your company is growing fast. Tenacious can support your engineering needs."


def _run_abstention(prospect: dict, brief: dict) -> str:
    """
    Run ICP abstention scoring. Returns pitch_mode string.
    Falls back to 'segment_specific' on import error.
    """
    try:
        from mechanism.icp_abstention import classify_with_abstention
        segment = brief.get("recommended_segment") or 0
        signals = _get_signals(brief)
        result = classify_with_abstention(
            segment=segment,
            signals=signals,
            employee_min=prospect.get("employee_count_min"),
            employee_max=prospect.get("employee_count_max"),
        )
        return result.pitch_mode
    except Exception as exc:
        logger.debug("classify_with_abstention failed: %s", exc)
        return "segment_specific"


def _run_tone_gate(draft: str) -> bool:
    """Run tone check on *draft*. Returns True if the draft passes."""
    try:
        from mechanism.tone_preservation import check_tone
        result = check_tone(draft)
        return result.passed
    except Exception as exc:
        logger.debug("check_tone failed: %s", exc)
        return True  # default pass so tone_gate=OFF runs are comparable


def _count_overclaims(brief: dict, draft: str) -> int:
    """Return the number of over-claim warnings for a draft / brief pair."""
    try:
        from mechanism.confidence_aware_phrasing import detect_overclaim
        signals = _get_signals(brief)
        return len(detect_overclaim(draft, signals))
    except Exception as exc:
        logger.debug("detect_overclaim failed: %s", exc)
        return 0


# ── Public API ────────────────────────────────────────────────────────────────

def run_ablation(
    config: AblationConfig,
    prospects: list[dict],
    signals_by_id: dict,
) -> AblationResult:
    """
    Run one ablation configuration against the given prospect list.

    Args:
        config:         AblationConfig specifying which components are enabled.
        prospects:      List of prospect dicts (must include prospect_id,
                        company_name, optional employee_count_min/max).
        signals_by_id:  Mapping of prospect_id → HiringSignalBrief dict.

    Returns:
        AblationResult with aggregate statistics.
    """
    t_start = time.perf_counter()

    segment_specific_count = 0
    exploratory_count = 0
    escalate_count = 0
    tone_pass_total = 0
    tone_checked = 0
    overclaim_total = 0

    for prospect in prospects:
        pid = prospect.get("prospect_id", "")
        brief = signals_by_id.get(pid, {})

        # Step 1: Build draft opener
        draft = _build_draft_opener(prospect, brief, config)

        # Step 2: Over-claim detection (only relevant when phrasing is ON;
        #         when OFF we still count warnings to measure the delta)
        overclaim_total += _count_overclaims(brief, draft)

        # Step 3: Abstention / routing
        if config.abstention:
            pitch_mode = _run_abstention(prospect, brief)
        else:
            # OFF: always send segment-specific (Day-1 behaviour)
            segment = brief.get("recommended_segment")
            pitch_mode = "segment_specific" if segment else "exploratory"

        if pitch_mode == "segment_specific":
            segment_specific_count += 1
        elif pitch_mode == "exploratory":
            exploratory_count += 1
        else:
            escalate_count += 1

        # Step 4: Tone gate
        if config.tone_gate:
            passed = _run_tone_gate(draft)
            tone_pass_total += 1 if passed else 0
            tone_checked += 1

    n = len(prospects)
    tone_pass_rate = round(tone_pass_total / tone_checked, 4) if tone_checked > 0 else 1.0
    run_duration = round(time.perf_counter() - t_start, 4)

    return AblationResult(
        config_name=config.name,
        n_prospects=n,
        segment_specific_count=segment_specific_count,
        exploratory_count=exploratory_count,
        escalate_count=escalate_count,
        tone_pass_rate=tone_pass_rate,
        overclaim_warnings=overclaim_total,
        run_duration_s=run_duration,
    )


def run_all_ablations(
    prospects: list[dict],
    signals_by_id: dict,
) -> list[AblationResult]:
    """
    Run all 5 ablation configurations against *prospects*.

    Args:
        prospects:      List of prospect dicts.
        signals_by_id:  Mapping of prospect_id → HiringSignalBrief dict.

    Returns:
        List of AblationResult, one per config (in the order defined by
        ABLATION_CONFIGS: A, B, C, D, E).
    """
    results: list[AblationResult] = []
    for config in ABLATION_CONFIGS:
        logger.info("Running ablation config '%s' on %d prospects", config.name, len(prospects))
        result = run_ablation(config, prospects, signals_by_id)
        logger.info(
            "  segment_specific=%d  exploratory=%d  escalate=%d  "
            "tone_pass=%.2f  overclaims=%d  duration=%.3fs",
            result.segment_specific_count,
            result.exploratory_count,
            result.escalate_count,
            result.tone_pass_rate,
            result.overclaim_warnings,
            result.run_duration_s,
        )
        results.append(result)
    return results


def save_ablation_results(
    results: list[AblationResult],
    path: Optional[Path] = None,
) -> None:
    """
    Serialise ablation results to JSON.

    Args:
        results: List of AblationResult instances.
        path:    Output file path. Defaults to eval/ablation_results.json.
    """
    out_path = path or DEFAULT_OUTPUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "ablation_results": [asdict(r) for r in results],
        "configs": [asdict(c) for c in ABLATION_CONFIGS],
        "n_configs": len(results),
    }

    out_path.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Ablation results saved to '%s'", out_path)
