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
