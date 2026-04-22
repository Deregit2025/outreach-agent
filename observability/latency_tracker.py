"""
latency_tracker.py — Records agent tick durations and computes p50/p95.

Backed by a simple in-memory ring buffer + optional append-only JSONL file.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_LOG = Path(__file__).resolve().parents[1] / "eval" / "latency_log.jsonl"

_MAX_BUFFER = 10_000  # keep last N entries in memory


class LatencyTracker:
    def __init__(self, log_path: Path = _DEFAULT_LOG, buffer_size: int = _MAX_BUFFER) -> None:
        self._log_path = log_path
        self._buffer: deque[float] = deque(maxlen=buffer_size)

    # ------------------------------------------------------------------

    def record(
        self,
        duration_s: float,
        action: str = "",
        prospect_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record a single duration and optionally write to the JSONL log."""
        self._buffer.append(duration_s)
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            record: dict = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_s": round(duration_s, 4),
                "action": action,
                "prospect_id": prospect_id,
                **(extra or {}),
            }
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:
            pass  # never crash the agent over telemetry

    def percentile(self, pct: float) -> float:
        """Return the p-th percentile of recorded durations (0–100)."""
        values = sorted(self._buffer)
        if not values:
            return 0.0
        k = (len(values) - 1) * pct / 100
        lo = int(k)
        hi = min(lo + 1, len(values) - 1)
        return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 3)

    def p50(self) -> float:
        return self.percentile(50)

    def p95(self) -> float:
        return self.percentile(95)

    def summary(self) -> dict:
        n = len(self._buffer)
        return {
            "n": n,
            "p50_s": self.p50() if n else 0.0,
            "p95_s": self.p95() if n else 0.0,
            "min_s": round(min(self._buffer), 3) if n else 0.0,
            "max_s": round(max(self._buffer), 3) if n else 0.0,
        }


# Singleton imported across the project
latency_tracker = LatencyTracker()


class timed:
    """Context manager that records duration into the tracker."""

    def __init__(
        self,
        action: str = "",
        prospect_id: str = "",
        extra: dict[str, Any] | None = None,
        tracker: LatencyTracker = latency_tracker,
    ) -> None:
        self._action = action
        self._prospect_id = prospect_id
        self._extra = extra
        self._tracker = tracker
        self._t0: float = 0.0

    def __enter__(self) -> "timed":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        duration = time.perf_counter() - self._t0
        self._tracker.record(duration, self._action, self._prospect_id, self._extra)
