# τ²-Bench Retail Baseline

**Run name:** `dev_baseline_v1`
**Date:** 2026-04-22
**Model:** `ollama/minimax-m2.7:cloud`

---

## What Was Reproduced

The τ²-Bench retail domain was run against the 30-task development slice
(partitioned deterministically with seed=42 from the training split).
The harness wraps `run_single_task` from `tau2.runner`, writes every trial
to `trace_log.jsonl`, and appends a summary entry to `score_log.json`.
Langfuse trace IDs are recorded per trial for cost and latency attribution.

A prior 2-task smoke test (`smoke_test`) with `openrouter/deepseek/deepseek-chat`
confirmed the harness runs end-to-end before the full dev baseline was started.

---

## Results

| Metric | Value |
|---|---|
| **pass@1** | **3.33%** |
| **95% CI (Wilson)** | **[0.9%, 11.4%]** |
| Tasks attempted | 30 |
| Trials per task | 2 |
| Total attempts | 60 |
| Attempts passed | 2 (both on task #10) |
| Tasks passing (any trial) | 1 / 30 |
| Tasks passing (all trials) | 1 / 30 |
| Latency p50 | 6.0 s |
| Latency p95 | 287.2 s |
| Total wall time | 54 min (3,268 s) |
| Agent cost | $0.00 (local model, no token billing) |

---

## Confidence Interval

Wilson score 95% CI with n=60, successes=2: **[0.9%, 11.4%]**.
A 5-trial re-run will narrow this to approximately ±4 percentage points.

---

## Unexpected Behaviour

**Most failures were near-instant (~6 s).** 28 of 30 tasks returned
`reward=0.0` within 5–8 seconds. The model produced a response on the
first turn but did not issue a valid tool call, causing τ²-Bench to
terminate the episode immediately. This is the dual-control coordination
failure mode: the agent proceeded without invoking the required tool action.

**Task #10 passed both trials** (37 s and 200 s). It is a simpler retail
task with fewer required tool-call steps — consistent with smaller models
succeeding only when the task requires minimal orchestration.

**One long-running failure** (task #2, trial 1: 972 s) entered a loop
before terminating. This is a cost-pathology case — a probe category
already identified in the adversarial probe plan.

---

## Published Reference vs. Baseline

| | pass@1 |
|---|---|
| Published ceiling (GPT-5 class) | ~42% |
| This baseline (`minimax-m2.7:cloud`) | 3.33% |

The gap is model-driven. The mechanism (Act IV) targets the highest-ROI
failure mode from the adversarial probe library (Act III), evaluated on
the sealed 20-task held-out slice.
