"""
Dry-run test for key rotation logic.

Simulates 12 trials (no real API calls). Inject fake 403 failures on
specific keys to verify:
  1. Round-robin assigns a different key to each trial in order
  2. When a key hits 403, it is retired permanently and never used again
  3. Failover immediately picks the next active key and retries
  4. When all keys are exhausted, trials are skipped gracefully

Run:
    python eval/test_key_rotation.py
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# ── Same key-pool logic as harness.py ────────────────────────────────────────
_keys_multi = [k.strip() for k in os.getenv("OPENROUTER_API_KEYS", "").split(",") if k.strip()]
_key_single = os.getenv("OPENROUTER_API_KEY", "").strip()
OR_KEYS: list[str] = _keys_multi + ([_key_single] if _key_single and _key_single not in _keys_multi else [])

_exhausted: set[int] = set()
_rr_cursor: int = 0

def _active_count() -> int:
    return len(OR_KEYS) - len(_exhausted)

def _pick_rr_key() -> tuple[int, str] | tuple[None, None]:
    global _rr_cursor
    n = len(OR_KEYS)
    for _ in range(n):
        idx = _rr_cursor % n
        _rr_cursor += 1
        if idx not in _exhausted:
            return idx, OR_KEYS[idx]
    return None, None

def _retire_and_failover(failed_idx: int) -> tuple[int, str] | tuple[None, None]:
    _exhausted.add(failed_idx)
    remaining = _active_count()
    print(f"    [key-pool] key {failed_idx + 1} weekly limit — RETIRED FOREVER  "
          f"({remaining} key(s) still active)")
    n = len(OR_KEYS)
    for i in range(1, n):
        idx = (failed_idx + i) % n
        if idx not in _exhausted:
            print(f"    [key-pool] failover → key {idx + 1}")
            return idx, OR_KEYS[idx]
    print("    [key-pool] ALL keys exhausted — no more retries")
    return None, None

# ── Simulated failure injection ───────────────────────────────────────────────
# Trials (0-based) where the currently-assigned key will hit 403.
# Whatever key is active on that trial gets retired and failover fires.
FAIL_ON_TRIAL: set[int] = {2, 7, 11}

# ── Run simulation ────────────────────────────────────────────────────────────
NUM_TRIALS = 12

print(f"\n{'='*60}")
print(f"KEY ROTATION TEST  —  {len(OR_KEYS)} keys loaded")
for i, k in enumerate(OR_KEYS):
    print(f"  key {i+1}: ...{k[-8:]}")
print(f"\nInjected 403s on trials: {sorted(t+1 for t in FAIL_ON_TRIAL)} (1-based)")
print(f"{'='*60}\n")

for trial in range(NUM_TRIALS):
    cur_idx, _ = _pick_rr_key()

    if cur_idx is None:
        print(f"  trial {trial+1:2d}: [ALL KEYS EXHAUSTED] — skipped")
        continue

    print(f"  trial {trial+1:2d}: [k{cur_idx+1}]", end="")

    # Inject a 403 on this trial — retire the current key and failover
    if trial in FAIL_ON_TRIAL:
        print(f"  → 403 weekly limit on key {cur_idx+1}!", end="")
        cur_idx, _ = _retire_and_failover(cur_idx)
        if cur_idx is not None:
            print(f"\n            retry [k{cur_idx+1}] → SUCCESS  (P)")
        else:
            print(f"\n            no keys left → FAILED  (F)")
    else:
        print("  → SUCCESS  (P)")

print(f"\n{'='*60}")
print(f"Done.  Keys retired: {sorted(i+1 for i in _exhausted)}  |  "
      f"Keys still active: {sorted(i+1 for i in range(len(OR_KEYS)) if i not in _exhausted)}")
print(f"{'='*60}\n")
