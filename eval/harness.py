"""
τ²-Bench retail baseline harness for the Conversion Engine project.

Run from the tau2-bench directory using its uv environment:
    cd tau2-bench
    uv run python ../eval/harness.py [--mode dev|held_out] [--trials N]

Outputs (written to eval/):
    score_log.json    — one entry per run with pass@1, 95% CI, cost, latency
    trace_log.jsonl   — one line per simulation (task_id, trial, reward, duration, cost)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
HARNESS_DIR = Path(__file__).resolve().parent   # eval/
PROJECT_ROOT = HARNESS_DIR.parent               # project root
TAU2_DIR = PROJECT_ROOT / "tau2-bench"

sys.path.insert(0, str(TAU2_DIR / "src"))

# Tell tau2 where its data lives (needed when running outside the tau2-bench uv env)
os.environ.setdefault("TAU2_DATA_DIR", str(TAU2_DIR / "data"))

# audioop was removed in Python 3.13; stub it so tau2's voice imports don't crash.
# We only use text (half-duplex) mode — the stub is never actually called.
if sys.version_info >= (3, 13) and "audioop" not in sys.modules:
    from types import ModuleType as _ModuleType
    sys.modules["audioop"] = _ModuleType("audioop")

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(TAU2_DIR / ".env", override=False)
except ImportError:
    pass

# ── OpenRouter key pool (round-robin + permanent retirement) ──────────────────
# Load all keys: OPENROUTER_API_KEYS (comma-separated) + OPENROUTER_API_KEY
_keys_multi = [k.strip() for k in os.getenv("OPENROUTER_API_KEYS", "").split(",") if k.strip()]
_key_single = os.getenv("OPENROUTER_API_KEY", "").strip()
OR_KEYS: list[str] = _keys_multi + ([_key_single] if _key_single and _key_single not in _keys_multi else [])
_exhausted: set[int] = set()   # indices of keys permanently retired (weekly limit hit)
_rr_cursor: int = 0            # round-robin cursor across all keys

def _active_count() -> int:
    return len(OR_KEYS) - len(_exhausted)

def _pick_rr_key() -> tuple[int, str] | tuple[None, None]:
    """Round-robin: advance cursor, skip exhausted keys, set env var."""
    global _rr_cursor
    n = len(OR_KEYS)
    for _ in range(n):
        idx = _rr_cursor % n
        _rr_cursor += 1
        if idx not in _exhausted:
            os.environ["OPENROUTER_API_KEY"] = OR_KEYS[idx]
            return idx, OR_KEYS[idx]
    return None, None  # all keys exhausted

def _retire_and_failover(failed_idx: int) -> tuple[int, str] | tuple[None, None]:
    """Permanently retire a key that hit its weekly limit, failover to next."""
    _exhausted.add(failed_idx)
    remaining = _active_count()
    print(f"\n  [key-pool] key {failed_idx + 1} weekly limit — retired forever  "
          f"({remaining} key(s) still active)", flush=True)
    n = len(OR_KEYS)
    for i in range(1, n):
        idx = (failed_idx + i) % n
        if idx not in _exhausted:
            os.environ["OPENROUTER_API_KEY"] = OR_KEYS[idx]
            print(f"  [key-pool] failover → key {idx + 1}", flush=True)
            return idx, OR_KEYS[idx]
    print("  [key-pool] ALL keys exhausted — no more retries", flush=True)
    return None, None

if OR_KEYS:
    os.environ["OPENROUTER_API_KEY"] = OR_KEYS[0]
    os.environ.setdefault("OR_SITE_URL", "https://gettenacious.com")
    os.environ.setdefault("OR_APP_NAME", "TenaciousConversionEngine")
    print(f"[key-pool] loaded {len(OR_KEYS)} key(s) for round-robin rotation")

# ── Langfuse (optional) ───────────────────────────────────────────────────────
try:
    from langfuse import Langfuse
    _lf = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    )
    LANGFUSE_AVAILABLE = bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
except Exception:
    _lf = None
    LANGFUSE_AVAILABLE = False

# ── tau2 imports ──────────────────────────────────────────────────────────────
from tau2.data_model.simulation import TextRunConfig
from tau2.evaluator.evaluator import EvaluationType
from tau2.runner import get_tasks, run_single_task

# ── Task partition (deterministic, seed=42) ───────────────────────────────────
def _build_partition() -> dict[str, list[str]]:
    split_file = TAU2_DIR / "data/tau2/domains/retail/split_tasks.json"
    splits = json.loads(split_file.read_text())
    rng = random.Random(42)
    train = splits["train"][:]
    rng.shuffle(train)
    return {
        "dev": sorted(train[:30]),
        "held_out": sorted(splits["test"][:20]),
    }

PARTITION = _build_partition()


# ── Statistical helpers ───────────────────────────────────────────────────────

def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, round(center - margin, 4)), min(1.0, round(center + margin, 4)))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


# ── Langfuse trace helper ─────────────────────────────────────────────────────

def _log_trace(task_id: str, trial: int, reward: float, duration: float,
               agent_cost: float | None, model: str, run_name: str) -> str | None:
    if not LANGFUSE_AVAILABLE or _lf is None:
        return None
    try:
        trace = _lf.trace(
            name=f"tau2-retail-{run_name}",
            metadata={
                "task_id": task_id,
                "trial": trial,
                "model": model,
                "domain": "retail",
                "run_name": run_name,
            },
        )
        _lf.generation(
            trace_id=trace.id,
            name="tau2_simulation",
            model=model,
            usage={"total_cost": agent_cost or 0.0},
            metadata={"reward": reward, "duration_s": duration},
        )
        return trace.id
    except Exception as e:
        print(f"  [langfuse] warning: {e}")
        return None


# ── Core runner ───────────────────────────────────────────────────────────────

def run_baseline(
    mode: str,
    trials: int,
    agent_model: str,
    user_model: str,
    run_name: str | None = None,
    max_tasks: int | None = None,
) -> dict:
    """
    Run the τ²-Bench retail baseline.

    Returns the score entry dict written to score_log.json.
    """
    task_ids = PARTITION[mode]
    if max_tasks:
        task_ids = task_ids[:max_tasks]

    if run_name is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_name = f"{mode}_{ts}"

    print(f"\n{'='*60}")
    print(f"tau2-bench retail  mode={mode}  trials={trials}  tasks={len(task_ids)}")
    print(f"agent : {agent_model}")
    print(f"user  : {user_model}")
    print(f"run   : {run_name}")
    print(f"langfuse: {'on' if LANGFUSE_AVAILABLE else 'off (no key)'}")
    print(f"{'='*60}\n")

    config = TextRunConfig(
        domain="retail",
        llm_agent=agent_model,
        llm_user=user_model,
        llm_args_agent={"temperature": 0.0, "max_tokens": 4096},
        llm_args_user={"temperature": 0.7, "max_tokens": 4096},
    )

    tasks = get_tasks("retail", task_ids=task_ids)
    trace_records: list[dict] = []
    task_rewards: dict[str, list[float]] = {}
    all_durations: list[float] = []
    total_agent_cost: float = 0.0
    run_start = time.time()

    for idx, task in enumerate(tasks):
        task_rewards[task.id] = []
        print(f"  task {task.id:>4}  ({idx+1:2}/{len(tasks)})", end="", flush=True)

        for trial in range(trials):
            seed = 42 + trial * 1000
            reward, duration, agent_cost = 0.0, 0.0, 0.0

            # Round-robin: pick next active key for this simulation
            cur_idx, _ = _pick_rr_key()
            if cur_idx is None:
                print(f"\n  [key-pool] all keys exhausted — skipping trial {trial}", flush=True)
                task_rewards[task.id].append(0.0)
                all_durations.append(0.0)
                continue

            print(f" [k{cur_idx + 1}]", end="", flush=True)

            # Retry loop: on 403, retire key and failover to next
            while True:
                t0 = time.time()
                try:
                    sim = run_single_task(
                        config,
                        task,
                        seed=seed,
                        evaluation_type=EvaluationType.ALL,
                    )
                    reward = float(sim.reward_info.reward) if sim.reward_info else 0.0
                    duration = sim.duration if sim.duration else (time.time() - t0)
                    agent_cost = sim.agent_cost or 0.0
                    break
                except Exception as e:
                    err = str(e)
                    is_key_limit = ("403" in err and "weekly" in err.lower()) or "Key limit exceeded" in err
                    if is_key_limit:
                        cur_idx, _ = _retire_and_failover(cur_idx)
                        if cur_idx is not None:
                            print(f" [k{cur_idx + 1}]", end="", flush=True)
                            continue
                    print(f"\n    [trial {trial}] ERROR: {e}", flush=True)
                    reward, duration, agent_cost = 0.0, time.time() - t0, 0.0
                    break

            total_agent_cost += agent_cost
            all_durations.append(duration)
            task_rewards[task.id].append(reward)

            trace_id = _log_trace(
                task.id, trial, reward, duration, agent_cost, agent_model, run_name
            )

            record: dict = {
                "run_name": run_name,
                "mode": mode,
                "task_id": task.id,
                "trial": trial,
                "seed": seed,
                "reward": reward,
                "duration_s": round(duration, 3),
                "agent_cost_usd": round(agent_cost, 6),
                "agent_model": agent_model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if trace_id:
                record["langfuse_trace_id"] = trace_id
            trace_records.append(record)
            print(f"  {'P' if reward >= 1.0 else 'F'}", end="", flush=True)

        print()

    wall_time = time.time() - run_start

    # ── Aggregate stats ───────────────────────────────────────────────────────
    all_rewards = [r for rewards in task_rewards.values() for r in rewards]
    n_total = len(all_rewards)
    n_pass = sum(1 for r in all_rewards if r >= 1.0)
    pass_at_1 = round(n_pass / n_total, 4) if n_total else 0.0
    ci_lo, ci_hi = _wilson_ci(n_pass, n_total)

    task_pass_any = sum(
        1 for rewards in task_rewards.values() if any(r >= 1.0 for r in rewards)
    )
    task_pass_all = sum(
        1 for rewards in task_rewards.values() if all(r >= 1.0 for r in rewards)
    )

    p50 = _percentile(all_durations, 50)
    p95 = _percentile(all_durations, 95)
    cost_per_task = round(total_agent_cost / len(task_ids), 6) if task_ids else 0.0

    score_entry = {
        "run_name": run_name,
        "mode": mode,
        "agent_model": agent_model,
        "user_model": user_model,
        "num_tasks": len(task_ids),
        "num_trials": trials,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pass_at_1": pass_at_1,
        "ci_95": [ci_lo, ci_hi],
        "n_pass": n_pass,
        "n_total": n_total,
        "task_pass_any": task_pass_any,
        "task_pass_all": task_pass_all,
        "latency_p50_s": p50,
        "latency_p95_s": p95,
        "total_agent_cost_usd": round(total_agent_cost, 6),
        "cost_per_task_usd": cost_per_task,
        "wall_time_s": round(wall_time, 1),
        "task_ids": task_ids,
    }

    # ── Write results ─────────────────────────────────────────────────────────
    score_log_path = HARNESS_DIR / "score_log.json"
    trace_log_path = HARNESS_DIR / "trace_log.jsonl"

    existing: list = []
    if score_log_path.exists():
        try:
            existing = json.loads(score_log_path.read_text())
            if not isinstance(existing, list):
                existing = [existing]
        except Exception:
            existing = []
    existing.append(score_entry)
    score_log_path.write_text(json.dumps(existing, indent=2))

    with trace_log_path.open("a", encoding="utf-8") as fh:
        for rec in trace_records:
            fh.write(json.dumps(rec) + "\n")

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"RESULTS  {run_name}")
    print(f"  pass@1        {pass_at_1:.1%}  (95% CI {ci_lo:.1%} – {ci_hi:.1%})")
    print(f"  tasks passing {task_pass_any}/{len(task_ids)} (any trial)")
    print(f"  latency       p50={p50:.1f}s   p95={p95:.1f}s")
    print(f"  agent cost    ${total_agent_cost:.4f}  (${cost_per_task:.4f}/task)")
    print(f"  wall time     {wall_time:.0f}s")
    print(f"  score_log  -> {score_log_path}")
    print(f"  trace_log  -> {trace_log_path}")
    print(f"{'='*60}\n")

    return score_entry


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="tau2-bench retail harness")
    p.add_argument("--mode", choices=["dev", "held_out"], default="dev")
    p.add_argument("--trials", type=int, default=5,
                   help="Trials per task for pass@k (default: 5)")
    p.add_argument("--agent-model", default="openrouter/deepseek/deepseek-chat",
                   help="LiteLLM model string for agent (dev default: openrouter/deepseek/deepseek-chat, eval: openrouter/anthropic/claude-sonnet-4-6)")
    p.add_argument("--user-model", default="openrouter/deepseek/deepseek-chat",
                   help="LiteLLM model string for user simulator")
    p.add_argument("--run-name", default=None,
                   help="Label for this run (auto-generated if omitted)")
    p.add_argument("--max-tasks", type=int, default=None,
                   help="Cap task count for smoke tests (e.g. --max-tasks 3)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_baseline(
        mode=args.mode,
        trials=args.trials,
        agent_model=args.agent_model,
        user_model=args.user_model,
        run_name=args.run_name,
        max_tasks=args.max_tasks,
    )
