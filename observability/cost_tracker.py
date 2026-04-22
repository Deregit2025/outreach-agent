"""
Budget tracker — enforces the $20/week hard cap.

Import and call track() after every LLM API call.
Warns at 80% of budget. Hard-stops at 100%.

Usage:
    from observability.cost_tracker import tracker

    cost = tracker.track(
        category="dev_llm",
        tokens_in=450,
        tokens_out=220,
        cost_per_1k_in=0.0014,
        cost_per_1k_out=0.0028,
    )
"""

import json
from pathlib import Path
from datetime import datetime

from config.settings import settings


class BudgetExceededError(Exception):
    pass


class CostTracker:

    COST_LOG_PATH = Path("data/processed/cost_log.json")

    def __init__(self):
        self.spent: dict[str, float] = {
            "dev_llm":  0.0,
            "eval_llm": 0.0,
            "voice":    0.0,
        }
        self.log: list[dict] = []
        self._load_existing()

    def _load_existing(self) -> None:
        """Resume from previous runs so totals persist across restarts."""
        if self.COST_LOG_PATH.exists():
            try:
                data = json.loads(self.COST_LOG_PATH.read_text())
                self.spent  = data.get("spent", self.spent)
                self.log    = data.get("log", [])
            except Exception:
                pass

    def _save(self) -> None:
        self.COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.COST_LOG_PATH.write_text(
            json.dumps({"spent": self.spent, "log": self.log}, indent=2)
        )

    @property
    def total_spent(self) -> float:
        return sum(self.spent.values())

    def track(
        self,
        category: str,          # "dev_llm" | "eval_llm" | "voice"
        tokens_in: int,
        tokens_out: int,
        cost_per_1k_in: float,
        cost_per_1k_out: float,
        note: str = "",
    ) -> float:
        cost = (
            tokens_in  / 1000 * cost_per_1k_in +
            tokens_out / 1000 * cost_per_1k_out
        )

        self.spent[category] = self.spent.get(category, 0.0) + cost
        self.log.append({
            "ts":        datetime.utcnow().isoformat(),
            "category":  category,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost":      round(cost, 6),
            "total":     round(self.total_spent, 4),
            "note":      note,
        })
        self._save()

        total = self.total_spent
        budget = settings.budget_total

        # ── Warn at 80% ──────────────────────────────────────
        if total >= budget * 0.80:
            print(
                f"⚠️  BUDGET WARNING: ${total:.2f} spent of ${budget:.2f} "
                f"({total/budget*100:.0f}%). Switch to cheaper model soon."
            )

        # ── Hard stop at 100% ────────────────────────────────
        if total > budget:
            raise BudgetExceededError(
                f"🛑 HARD STOP: ${total:.2f} exceeds the ${budget:.2f} cap.\n"
                f"   Set LLM_PROVIDER=openrouter and use the dev model,\n"
                f"   or reduce call frequency before continuing."
            )

        return cost

    def summary(self) -> dict:
        return {
            "spent":        self.spent,
            "total_spent":  round(self.total_spent, 4),
            "budget_total": settings.budget_total,
            "remaining":    round(settings.budget_total - self.total_spent, 4),
            "pct_used":     round(self.total_spent / settings.budget_total * 100, 1),
        }


# Single instance imported everywhere
tracker = CostTracker()