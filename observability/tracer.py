"""
tracer.py — Langfuse v2 tracing wrapper.

Wraps LLM calls and agent ticks with Langfuse traces.
Gracefully no-ops when LANGFUSE_PUBLIC_KEY is not set.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_lf = None
_available = False

try:
    from langfuse import Langfuse  # type: ignore
    _pub = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    _sec = os.getenv("LANGFUSE_SECRET_KEY", "")
    _host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    if _pub and _sec:
        _lf = Langfuse(public_key=_pub, secret_key=_sec, host=_host)
        _available = True
except Exception as exc:
    logger.debug("Langfuse not available: %s", exc)


def is_available() -> bool:
    return _available


def start_trace(name: str, metadata: dict[str, Any] | None = None) -> Any:
    """
    Start a Langfuse trace and return the trace object.
    Returns None when Langfuse is not configured.
    """
    if not _available or _lf is None:
        return None
    try:
        return _lf.trace(name=name, metadata=metadata or {})
    except Exception as exc:
        logger.warning("Langfuse trace start failed: %s", exc)
        return None


def log_generation(
    trace: Any,
    name: str,
    model: str,
    input_messages: list[dict],
    output: str,
    cost_usd: float | None = None,
    latency_s: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log an LLM generation against an existing trace."""
    if not _available or _lf is None or trace is None:
        return
    try:
        _lf.generation(
            trace_id=trace.id,
            name=name,
            model=model,
            input=input_messages,
            output=output,
            usage={"total_cost": cost_usd or 0.0},
            metadata={
                **(metadata or {}),
                "latency_s": latency_s,
            },
        )
    except Exception as exc:
        logger.warning("Langfuse generation log failed: %s", exc)


def log_agent_tick(
    prospect_id: str,
    company_name: str,
    action: str,
    segment: int,
    tone_score: float | None,
    sent: bool,
    duration_s: float,
    model: str = "",
) -> str | None:
    """
    Convenience wrapper: create a trace for one agent tick.
    Returns the trace ID or None.
    """
    trace = start_trace(
        name=f"agent-tick-{action.lower()}",
        metadata={
            "prospect_id": prospect_id,
            "company": company_name,
            "action": action,
            "segment": segment,
            "tone_score": tone_score,
            "sent": sent,
            "duration_s": duration_s,
            "model": model,
        },
    )
    if trace is None:
        return None
    return getattr(trace, "id", None)


def flush() -> None:
    """Flush any buffered Langfuse events (call at process exit)."""
    if _available and _lf is not None:
        try:
            _lf.flush()
        except Exception:
            pass
