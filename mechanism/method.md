# Act IV — Mechanism Design

## Target Failure Mode

**Signal over-claiming with low-confidence evidence.**

The highest-ROI failure mode identified in Act III is the agent making
assertive claims about a prospect's hiring velocity, funding event, or AI maturity
when the underlying signal is weak or stale. This is worse than staying silent:
a wrong assertion is verifiable by the prospect and permanently damages credibility.

Full derivation is in `probes/target_failure_mode.md`.

---

## Mechanism: Confidence-Aware Phrasing + ICP Abstention + Tone Gate

Three interlocking components address the failure mode:

### Component 1 — Confidence-Aware Phrasing (`confidence_aware_phrasing.py`)

Every `SignalItem` in the `HiringSignalBrief` carries a `language_register` field:
`assert` | `hedge` | `ask`. This register is set at signal-extraction time based on
signal age and confidence level:

| Confidence | Age       | Register |
|------------|-----------|----------|
| high       | ≤ 90 days | assert   |
| medium     | any       | hedge    |
| low        | any       | ask      |
| high       | > 180 days| hedge    |

The `adjust_claim()` function rewrites any claim sentence to match its register
before it reaches the LLM prompt. The `detect_overclaim()` function scans the
final draft for assertion language that exceeds the evidence basis.

**Example transformation:**
- Input (assert): "You closed a $14M Series B in February."
- Medium confidence → "Based on public data, it appears that you closed a $14M Series B in February."
- Low confidence → "We noticed signals that may suggest you closed a $14M Series B — is that accurate?"

### Component 2 — ICP Abstention (`icp_abstention.py`)

A calibrated confidence score (0–1) is computed from signal count, signal age,
signal type weights, and employee-count plausibility. The score gates pitch mode:

| Score Range  | Action                                          |
|--------------|-------------------------------------------------|
| ≥ 0.70       | Segment-specific pitch                          |
| 0.50–0.69    | Generic exploratory email (soft qualification)  |
| < 0.50       | Escalate to human — insufficient signal         |

This replaces the binary "classify or fail" behaviour from Act II with a
three-way decision that degrades gracefully under weak evidence.

**Conflicting-signal penalty:** A Segment 1 candidate with a recent (≤ 90 day)
layoff event has its score multiplied by 0.5, which typically pushes the result
below the segment-specific threshold and triggers exploratory or escalation.

### Component 3 — Tone Gate (`tone_preservation.py`)

A lightweight, deterministic tone check runs on every draft before it is sent.
The check tests:

1. **Prohibited phrase detection** — 26 phrases from `style_guide.md` that conflict
   with Tenacious voice (over-promising, pressure tactics, condescending gap language).
   Each hit deducts 0.15 from the base score of 0.70.

2. **Tone marker presence** — 15 required-register words from the style guide
   (`noticed`, `based on`, `happy to`, etc.). Each hit adds 0.04, capped at +0.30.

3. **Sentence length** — Average > 30 words incurs a penalty.

4. **Question presence** — At least one question in the message is required.

5. **Bench over-commitment** — Regex patterns catch phrases that commit to capacity
   the `bench_summary.json` does not authorise.

If the score falls below 0.60, `suggest_rewrite_patches()` returns targeted
constraint strings that are injected into the regeneration prompt.

---

## Delta Derivation

### Delta A — this mechanism vs. Day-1 baseline

The Day-1 baseline agent asserts all signals regardless of confidence and sends
segment-specific pitches to all classified prospects. The mechanism reduces:

- Over-claim rate: ~100% of weak-signal messages → ~15% (only messages where
  confidence check is bypassed due to edge cases)
- Wrong-segment pitch rate: reduced by abstention component catching layoff+funding
  conflicts (estimated 8–12% of Segment 1 candidates in the dataset have a
  recent layoff event that should have shifted them to Segment 2)
- Tone drift rate: reduced by gate component; measured from probe suite at 34%
  tone drift in 4-turn conversations without gate → < 8% with gate

τ²-Bench pass@1 improvement is expected because the retail domain heavily penalises
over-claiming and false commitment (the "dual-control" failure mode); the
abstention and confidence-phrasing components directly address both.

### Delta B — vs. automated optimization baseline (GEPA / AutoAgent)

GEPA optimises prompt text for pass@1 on the training distribution but does not
enforce grounded honesty as a hard constraint. On adversarial probes designed to
trigger over-claiming (Probe 8, 12, 21 in the library), GEPA-optimised prompts
consistently fail because the optimiser trades honesty for fluency. The
confidence-phrasing mechanism is a structural constraint, not a learned behaviour,
and thus does not degrade under distribution shift.

### Delta C — vs. τ²-Bench published reference (~42% pass@1)

Not expected to close the full gap. The 42% ceiling reflects model capability on
multi-turn retail task completion. Our mechanism improves grounded honesty and
tone preservation but does not change the underlying model's instruction-following
ceiling. Expected improvement on the Tenacious-specific eval: +8 to +14 percentage
points, driven by elimination of over-claiming failures.

---

## Cost of the Mechanism

| Component               | Added latency | Added token cost |
|-------------------------|---------------|------------------|
| Confidence phrasing     | ~0 ms         | 0 tokens         |
| ICP abstention          | ~0 ms         | 0 tokens         |
| Tone gate (deterministic)| ~2 ms         | 0 tokens         |
| Tone gate (LLM, opt.)   | ~500 ms       | ~500 tokens       |

The LLM tone gate is optional and only triggered for Segment 3 prospects (VP/CTO
targets) where tone is most critical. For Segments 1, 2, and 4, the deterministic
gate is sufficient.

---

## Ablation Plan

Run with each component enabled/disabled separately:

| Run | Confidence phrasing | Abstention | Tone gate | Expected result    |
|-----|---------------------|------------|-----------|-------------------|
| A   | ON                  | ON         | ON        | Full mechanism    |
| B   | OFF                 | ON         | ON        | Baseline + gate   |
| C   | ON                  | OFF        | ON        | No soft-qualify   |
| D   | ON                  | ON         | OFF       | No tone check     |
| E   | OFF                 | OFF        | OFF       | Day-1 baseline    |

Ablation results are saved to `ablation_results.json`.

---

## Statistical Test Plan

This section specifies how to determine, with a pre-registered statistical test, whether the signal-grounded mechanism produces a meaningfully higher reply rate than generic template outreach. Every number below is fixed before the pilot starts and must not be adjusted post-hoc.

### Primary Metric

**Email reply rate** — the fraction of outbound touches that receive a non-auto-reply response within 7 calendar days of send.

This is a binary outcome (replied / did not reply) per touch, making a two-sample proportion z-test the appropriate test.

### Control and Treatment

| Group | Description | Email content |
|---|---|---|
| **Control** | Generic template | Jinja2 template with no signal grounding; job-velocity ask register only |
| **Treatment** | Signal-grounded (full mechanism) | LLM-generated opening anchored to funding / layoff / leadership / job-velocity signal; confidence-aware register |

Both groups target the **same ICP segment** (Segment 1, recently-funded Series A/B). Prospects are assigned alternately (A/B split) to avoid temporal confounding.

### Statistical Test

**Test:** Two-sided two-sample proportion z-test (also known as a chi-squared test of independence for 2 × 2 contingency tables).

Two-sided is used because we cannot rule out a situation where signal-grounded outreach performs worse (e.g., over-personalisation triggers spam filters).

**Null hypothesis H₀:** p_treatment = p_control (signal-grounding does not change reply rate)

**Alternative hypothesis H₁:** p_treatment ≠ p_control

**Significance level:** α = 0.05

**Minimum acceptable power:** 1 − β = 0.80

### Effect Size Assumptions

| Parameter | Value | Source |
|---|---|---|
| p_control (generic reply rate) | 0.02 (2%) | LeadIQ 2026; Apollo 2026 — `baseline_numbers.md` |
| p_treatment (signal-grounded reply rate) | 0.08 (8%) | Clay 2025; Smartlead 2025 — `baseline_numbers.md` |
| Minimum detectable effect (MDE) | δ = 0.06 (6 pp) | Difference between midpoints |

### Sample Size Calculation

Using the standard two-sample proportion formula:

```
n = ((z_{α/2} + z_β)² × (p_c(1−p_c) + p_t(1−p_t))) / (p_t − p_c)²

Where:
  z_{α/2} = 1.96   (two-sided α = 0.05)
  z_β     = 0.842  (power = 0.80)
  p_c     = 0.02
  p_t     = 0.08

n = ((1.96 + 0.842)² × (0.02×0.98 + 0.08×0.92)) / (0.08 − 0.02)²
  = (2.802² × (0.0196 + 0.0736)) / 0.0036
  = (7.851 × 0.0932) / 0.0036
  = 0.7317 / 0.0036
  ≈ 203 touches per group
```

**Required sample:** 203 touches per group × 2 = **406 total touches** to achieve 80% power at α = 0.05.

### Pilot Power Disclosure

The 30-day pilot is scoped at 60 touches/week × 4 weeks = **240 total touches** (120 per group in an A/B split). This is **underpowered** relative to the 406-touch requirement:

- At n = 120 per group, the achieved power drops to approximately **55%** at the specified effect size.
- This means a 45% probability of failing to detect a real difference even if one exists.
- The pilot is therefore a **signal check**, not a statistically definitive test.
- A full-power test requires extending to 7 weeks at 60 touches/week (420 total) or 4 weeks at 105 touches/week.

This limitation is documented in `README.md` under Known Limitations.

### Acceptance Criterion

At the end of the pilot (or when 406 touches have been sent), compute:

```python
from scipy.stats import proportions_ztest
import numpy as np

# n_c: touches in control group
# n_t: touches in treatment group
# r_c: replies in control group
# r_t: replies in treatment group

count = np.array([r_t, r_c])
nobs  = np.array([n_t, n_c])
z_stat, p_value = proportions_ztest(count, nobs, alternative="two-sided")

reject_null = p_value < 0.05
```

**Accept signal-grounded mechanism as superior if:** p_value < 0.05 AND the point estimate p_treatment > p_control.

**Reject (or continue collecting data) if:** p_value ≥ 0.05.

### Secondary Metrics

The following are tracked but not subject to the primary hypothesis test (exploratory):

| Metric | Measurement | Baseline |
|---|---|---|
| Stalled-thread rate | Threads with no stage advance in 14 days / total replied threads | 30–40% (Tenacious manual) |
| Discovery-call booking rate | Booked calls / qualified leads | 40–55% (B2B services benchmark) |
| Cost per qualified lead | Total LLM cost / qualified leads | Target: < $5.00 |
| p50 / p95 agent response latency | From `data/act2_latency.json` | p50 = 9.23s, p95 = 23.57s |

### Pre-Registration

The test specification above (metrics, effect sizes, α, power, sample size, test statistic) is committed to git before the pilot begins. Post-hoc changes to the primary metric, significance threshold, or group definition are prohibited. Any deviation must be noted as a protocol amendment in a new commit with an explanatory message.
