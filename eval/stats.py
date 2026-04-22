"""
Statistical helpers for τ²-Bench evaluation.

Used by harness.py and by the mechanism ablation runner.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional


# ── Confidence interval ───────────────────────────────────────────────────────

def wilson_ci(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    z = _z_for_confidence(confidence)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, round(center - margin, 4)), min(1.0, round(center + margin, 4)))


def _z_for_confidence(confidence: float) -> float:
    z_table = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}
    return z_table.get(confidence, 1.960)


# ── Pass@k ────────────────────────────────────────────────────────────────────

def pass_at_1(rewards: list[float]) -> float:
    """Fraction of trials that passed (reward >= 1.0)."""
    if not rewards:
        return 0.0
    return sum(1 for r in rewards if r >= 1.0) / len(rewards)


def pass_at_k_unbiased(n: int, c: int, k: int) -> float:
    """
    Unbiased pass@k estimator from the HumanEval paper.
    n = total completions per task, c = correct completions, k = k in pass@k.
    """
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))


# ── Latency ───────────────────────────────────────────────────────────────────

def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def latency_summary(durations_s: list[float]) -> dict:
    return {
        "p50_s": percentile(durations_s, 50),
        "p95_s": percentile(durations_s, 95),
        "mean_s": round(sum(durations_s) / len(durations_s), 3) if durations_s else 0.0,
        "max_s": round(max(durations_s), 3) if durations_s else 0.0,
    }


# ── Delta tests ───────────────────────────────────────────────────────────────

def delta_a(method_pass1: float, baseline_pass1: float) -> float:
    """Delta A = method pass@1 minus baseline pass@1. Must be positive."""
    return round(method_pass1 - baseline_pass1, 4)


def chi2_significance(
    method_n_pass: int, method_n: int,
    baseline_n_pass: int, baseline_n: int,
) -> dict:
    """
    Two-proportion z-test for Delta A significance (H0: proportions are equal).

    Returns p-value and whether it is < 0.05.
    """
    if method_n == 0 or baseline_n == 0:
        return {"p_value": 1.0, "significant": False, "z_score": 0.0}

    p1 = method_n_pass / method_n
    p2 = baseline_n_pass / baseline_n
    p_pool = (method_n_pass + baseline_n_pass) / (method_n + baseline_n)

    if p_pool in (0.0, 1.0):
        return {"p_value": 1.0, "significant": False, "z_score": 0.0}

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / method_n + 1 / baseline_n))
    z = (p1 - p2) / se if se > 0 else 0.0

    # Approximate two-tailed p-value from z-score
    p_value = _z_to_p(abs(z))

    return {
        "z_score": round(z, 4),
        "p_value": round(p_value, 4),
        "significant_p05": p_value < 0.05,
    }


def _z_to_p(z: float) -> float:
    """Approximate two-tailed p-value from |z| using the complementary error function."""
    return math.erfc(z / math.sqrt(2))


# ── Score log helpers ─────────────────────────────────────────────────────────

def load_score_log(path: Optional[Path] = None) -> list[dict]:
    if path is None:
        path = Path(__file__).parent / "score_log.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def load_trace_log(path: Optional[Path] = None) -> list[dict]:
    if path is None:
        path = Path(__file__).parent / "trace_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize_run(run_name: str, score_log: Optional[list[dict]] = None) -> Optional[dict]:
    """Return the score entry for a named run."""
    entries = score_log or load_score_log()
    for entry in reversed(entries):
        if entry.get("run_name") == run_name:
            return entry
    return None


def print_comparison(baseline: dict, method: dict) -> None:
    """Print a formatted Delta A comparison table."""
    d_a = delta_a(method["pass_at_1"], baseline["pass_at_1"])
    sig = chi2_significance(
        method["n_pass"], method["n_total"],
        baseline["n_pass"], baseline["n_total"],
    )
    print(f"\n{'='*55}")
    print(f"{'Run':<30} {'pass@1':>8}  {'95% CI':>16}")
    print(f"{'-'*55}")
    print(f"{'Baseline: ' + baseline['run_name']:<30} {baseline['pass_at_1']:>8.1%}  "
          f"  [{baseline['ci_95'][0]:.1%} – {baseline['ci_95'][1]:.1%}]")
    print(f"{'Method:   ' + method['run_name']:<30} {method['pass_at_1']:>8.1%}  "
          f"  [{method['ci_95'][0]:.1%} – {method['ci_95'][1]:.1%}]")
    print(f"{'-'*55}")
    print(f"Delta A:  {d_a:+.1%}   z={sig['z_score']:.2f}  "
          f"p={sig['p_value']:.4f}  "
          f"{'SIGNIFICANT (p<0.05)' if sig['significant_p05'] else 'not significant'}")
    print(f"{'='*55}\n")
