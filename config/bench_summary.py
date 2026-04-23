"""
Bench summary loader.

Reads bench_summary.json from the tenacious_sales_data/seed folder and exposes
available engineer counts to bench_guard.py.
"""

import json
from pathlib import Path


# ── Fallback hardcoded values ─────────────────────────────────
# Replace these with values from the actual seed repo file.
HARDCODED_BENCH: dict[str, int] = {
    "python":          7,
    "ml":              5,
    "go":              3,
    "data":            9,
    "infrastructure":  4,
    "frontend":        6,
    "fullstack_nestjs": 2,
}


def load_bench() -> dict[str, int]:
    """
    Tries to load bench_summary.json from the tenacious_sales_data/seed folder.
    Falls back to hardcoded values if file not found.
    Returns a dict of {stack_name: available_engineers}.
    """
    bench_path = Path("data/tenacious_sales_data/seed/bench_summary.json")

    if not bench_path.exists():
        return HARDCODED_BENCH.copy()

    try:
        with open(bench_path, 'r') as f:
            data = json.load(f)
        
        bench = {}
        for stack, details in data.get("stacks", {}).items():
            bench[stack] = details.get("available_engineers", 0)
        
        if not bench:
            return HARDCODED_BENCH.copy()

        return bench
    except (json.JSONDecodeError, KeyError):
        return HARDCODED_BENCH.copy()


# Single instance imported everywhere
BENCH: dict[str, int] = load_bench()


def get_available(stack: str) -> int:
    """Returns how many engineers of a given stack are available."""
    return BENCH.get(stack.lower(), 0)


def has_capacity(stack: str, count: int) -> bool:
    """Returns True if Tenacious bench can fulfil the requested count."""
    return get_available(stack) >= count