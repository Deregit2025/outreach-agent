"""
Bench summary loader.

Reads bench_summary.md from the seed repo and exposes
available engineer counts to bench_guard.py.

Replace the HARDCODED_BENCH dict below with real values
once you receive bench_summary.md on Day 0.
"""

from pathlib import Path


# ── Fallback hardcoded values ─────────────────────────────────
# Replace these with values from the actual seed repo file.
HARDCODED_BENCH: dict[str, int] = {
    "python":          4,
    "ml":              2,
    "go":              1,
    "data":            3,
    "infrastructure":  2,
}


def load_bench() -> dict[str, int]:
    """
    Tries to load bench_summary.md from the seed repo path.
    Falls back to hardcoded values if file not found.
    Returns a dict of {stack_name: available_count}.
    """
    bench_path = Path("data/raw/bench_summary.md")

    if not bench_path.exists():
        return HARDCODED_BENCH.copy()

    bench: dict[str, int] = {}
    for line in bench_path.read_text().splitlines():
        line = line.strip().lower()
        # Parses lines like: "Python backend: 4 engineers"
        for stack in HARDCODED_BENCH:
            if stack in line:
                parts = [p for p in line.split() if p.isdigit()]
                if parts:
                    bench[stack] = int(parts[0])

    if not bench:
        return HARDCODED_BENCH.copy()

    return bench


# Single instance imported everywhere
BENCH: dict[str, int] = load_bench()


def get_available(stack: str) -> int:
    """Returns how many engineers of a given stack are available."""
    return BENCH.get(stack.lower(), 0)


def has_capacity(stack: str, count: int) -> bool:
    """Returns True if Tenacious bench can fulfil the requested count."""
    return get_available(stack) >= count