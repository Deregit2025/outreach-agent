"""
evidence_graph.py — Append-only audit trail for every agent decision.

Every time the enrichment pipeline or agent makes a decision that affects
outreach (segment classification, confidence adjustment, register assignment,
guardrail check), it should call log_decision(). This creates a queryable
JSONL file that judges can replay to verify "why did the agent say X?"

Schema per entry:
  {
    "timestamp":     ISO-8601 UTC string
    "prospect_id":   str
    "decision_type": str (segment_classification | ai_maturity | register_assignment
                         | guardrail_check | sentiment_analysis | rag_retrieval
                         | tfidf_signal | topic_signal)
    "decision":      str (human-readable outcome)
    "inputs":        dict (all inputs that drove the decision)
    "logic":         str (one-sentence explanation of why)
    "output":        dict (final output values)
  }
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = PROJECT_ROOT / "data" / "processed" / "evidence_graph.jsonl"

# Thread-safe write lock
_write_lock = threading.Lock()


def log_decision(
    prospect_id: str,
    decision_type: str,
    inputs: dict,
    logic: str,
    output: dict,
    decision: str | None = None,
) -> None:
    """
    Append one decision record to the evidence graph.

    Args:
        prospect_id:   Company identifier (used as the trace key)
        decision_type: Category from the schema above
        inputs:        Dict of all inputs that drove the decision
        logic:         One-sentence human-readable explanation
        output:        Dict of final output values
        decision:      Short label for the outcome (auto-derived from output if None)
    """
    if decision is None:
        decision = str(next(iter(output.values()), "?"))[:80]

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prospect_id": prospect_id,
        "decision_type": decision_type,
        "decision": decision,
        "inputs": inputs,
        "logic": logic,
        "output": output,
    }

    try:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with EVIDENCE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("Evidence graph write failed: %s", exc)


def query_evidence(prospect_id: str) -> list[dict]:
    """Return all decision records for a given prospect, in order."""
    if not EVIDENCE_PATH.exists():
        return []
    records: list[dict] = []
    with EVIDENCE_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("prospect_id") == prospect_id:
                    records.append(rec)
            except json.JSONDecodeError:
                continue
    return records


def export_evidence_report(prospect_id: str) -> str:
    """Return a human-readable lineage report for a prospect."""
    records = query_evidence(prospect_id)
    if not records:
        return f"No evidence records found for prospect '{prospect_id}'."

    lines = [f"Evidence Graph — Prospect: {prospect_id}", "=" * 60]
    for i, rec in enumerate(records, 1):
        ts = rec.get("timestamp", "?")
        dtype = rec.get("decision_type", "?")
        decision = rec.get("decision", "?")
        logic = rec.get("logic", "?")
        lines.append(f"\n[{i}] {ts[:19]}  {dtype}")
        lines.append(f"    Decision: {decision}")
        lines.append(f"    Logic:    {logic}")
        out = rec.get("output", {})
        if out:
            lines.append(f"    Output:   {json.dumps(out, default=str)}")
    return "\n".join(lines)
