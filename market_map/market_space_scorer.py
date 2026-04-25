"""
market_space_scorer.py — Score every company in the Crunchbase dataset and build
a market-space map, identifying the highest-value (sector × size × AI-readiness)
cells for Tenacious outreach.

This is the "distinguished tier" deliverable: it converts the raw Crunchbase CSV
into a structured opportunity landscape so a sales team can prioritise outreach
by cell rather than by individual company.

Tenacious bench stacks (from bench_summary.json):
  python, go, data, ml, infra, frontend
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRUNCHBASE_CSV = PROJECT_ROOT / "data" / "raw" / "crunchbase_odm_sample.csv"
BENCH_SUMMARY = PROJECT_ROOT / "data" / "tenacious_sales_data" / "seed" / "bench_summary.json"

# ── Bench tech-stack keywords ────────────────────────────────────────────────
# Keys match bench_summary.json stack names; values are keyword sets for matching
_BENCH_KEYWORDS: dict[str, set[str]] = {
    "python": {
        "python", "django", "fastapi", "flask", "sqlalchemy", "celery",
        "pytest", "asyncio",
    },
    "go": {
        "go", "golang", "grpc", "goroutine", "kafka",
        "microservice", "infrastructure tooling",
    },
    "data": {
        "dbt", "snowflake", "databricks", "airflow", "fivetran",
        "powerbi", "quicksight", "data modeling",
    },
    "ml": {
        "langchain", "langgraph", "lora", "qlora", "rag",
        "retrieval augmented", "pytorch", "huggingface", "mlflow",
        "weights and biases", "wandb", "llm", "machine learning",
        "agentic", "multi-tool", "prompt engineering",
    },
    "infra": {
        "terraform", "aws", "gcp", "kubernetes", "docker",
        "github actions", "gitlab ci", "datadog", "grafana",
        "eks", "lambda", "rds", "gke", "cloud run",
    },
    "frontend": {
        "react", "next.js", "nextjs", "typescript", "tailwind",
        "shadcn", "vitest", "playwright",
    },
}

# AI-readiness terms by score level (score 1-3; score 0 = no match)
_AI_READINESS_TERMS: dict[int, set[str]] = {
    3: {
        "llm", "large language model", "generative ai", "genai", "gpt",
        "langchain", "llmops", "mlops", "vector database", "rag",
        "retrieval augmented", "agentic", "foundation model",
    },
    2: {
        "machine learning", "deep learning", "neural network", "nlp",
        "natural language", "computer vision", "recommendation system",
        "reinforcement learning", "pytorch", "tensorflow", "huggingface",
        "sagemaker", "vertex ai", "databricks", "mlflow",
    },
    1: {
        "ai", "data science", "predictive", "analytics", "data pipeline",
        "data warehouse", "snowflake", "dbt", "forecasting",
    },
}

# Employee-count range → size band
_SIZE_BANDS: list[tuple[str, int, int]] = [
    ("startup", 1, 80),
    ("growth", 81, 200),
    ("mid_market", 201, 2000),
    ("enterprise", 2001, 10_000_000),
]


# ── Low-level helpers ────────────────────────────────────────────────────────

def _parse_employee_midpoint(raw: str) -> Optional[float]:
    """Return midpoint of an employee range string like '11-50' or '1001-5000'."""
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    # Patterns: "11-50", "1,001-5,000", "10000+"
    cleaned = raw.replace(",", "")
    range_m = re.match(r"(\d+)-(\d+)", cleaned)
    if range_m:
        lo, hi = int(range_m.group(1)), int(range_m.group(2))
        return (lo + hi) / 2.0
    plus_m = re.match(r"(\d+)\+", cleaned)
    if plus_m:
        return float(plus_m.group(1))
    bare = re.match(r"^(\d+)$", cleaned)
    if bare:
        return float(bare.group(1))
    return None


def _size_band(midpoint: Optional[float]) -> str:
    if midpoint is None:
        return "unknown"
    for band, lo, hi in _SIZE_BANDS:
        if lo <= midpoint <= hi:
            return band
    return "enterprise" if midpoint > 2000 else "startup"


def _text_for_row(row: pd.Series) -> str:
    """Concatenate all useful text columns for keyword matching."""
    parts: list[str] = []
    for col in (
        "about", "full_description", "technology_highlights",
        "overview_highlights", "people_highlights", "industries",
    ):
        val = row.get(col, "")
        if isinstance(val, str) and val.strip():
            if col == "technology_highlights" and val.strip().startswith("["):
                try:
                    items = json.loads(val)
                    val = " ".join(
                        str(item.get("name", "")) if isinstance(item, dict) else str(item)
                        for item in items
                    )
                except Exception:
                    pass
            parts.append(val.strip())
    return " ".join(parts).lower()


def _ai_readiness_band(text: str) -> tuple[int, str]:
    """Return (score 0-3, band label)."""
    for score in sorted(_AI_READINESS_TERMS.keys(), reverse=True):
        terms = _AI_READINESS_TERMS[score]
        if any(term in text for term in terms):
            labels = {0: "none", 1: "early", 2: "developing", 3: "advanced"}
            return score, labels[score]
    return 0, "none"


def _bench_match_score(text: str) -> float:
    """
    Fraction of bench stacks (0-1) that appear in the company text.

    A stack is matched if at least one of its keywords is present.
    """
    matched = sum(
        1
        for keywords in _BENCH_KEYWORDS.values()
        if any(kw in text for kw in keywords)
    )
    return round(matched / len(_BENCH_KEYWORDS), 3)


def _has_funding_180d(row: pd.Series) -> bool:
    """Return True if the company has a funding round in the last 180 days."""
    raw = row.get("funding_rounds_list", "")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        rounds = json.loads(raw)
    except Exception:
        return False
    if not isinstance(rounds, list):
        return False

    from datetime import date, datetime
    today = date.today()
    for r in rounds:
        if not isinstance(r, dict):
            continue
        date_str = str(r.get("announced_on", "") or "")
        if not date_str:
            continue
        try:
            announced = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            if (today - announced).days <= 180:
                return True
        except ValueError:
            continue
    return False


def _has_layoff_signal(row: pd.Series) -> bool:
    """Return True if any layoff event is present in the row."""
    layoff_col = row.get("layoff", "")
    if isinstance(layoff_col, str) and layoff_col.strip() not in ("", "[]", "null"):
        return True
    return False


def _primary_sector(row: pd.Series) -> str:
    """
    Extract the primary sector label from the industries JSON array.
    Returns 'unknown' when the field is absent or unparseable.
    """
    raw = row.get("industries", "")
    if not isinstance(raw, str) or not raw.strip():
        return "unknown"
    try:
        items = json.loads(raw)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                return str(first.get("value", "unknown")).lower()
            return str(first).lower()
    except Exception:
        pass
    # If it's a plain string already
    return raw.strip().lower()


# ── Public API ───────────────────────────────────────────────────────────────

def score_company_for_market_map(row: pd.Series) -> dict:
    """
    Score a single Crunchbase company row and return a market-map record.

    Returns:
        {
            company_name:      str,
            sector:            str,
            size_band:         "startup" | "growth" | "mid_market" | "enterprise",
            ai_readiness_band: "none" | "early" | "developing" | "advanced",
            funding_180d:      bool,
            has_layoff_signal: bool,
            bench_match_score: float (0-1),
            composite_score:   float,
        }
    """
    company_name = str(row.get("name", "") or "unknown")
    sector = _primary_sector(row)

    emp_raw = str(row.get("num_employees", "") or "")
    midpoint = _parse_employee_midpoint(emp_raw)
    size_band = _size_band(midpoint)

    text = _text_for_row(row)
    ai_score, ai_band = _ai_readiness_band(text)
    bench_score = _bench_match_score(text)
    funding_180 = _has_funding_180d(row)
    layoff = _has_layoff_signal(row)

    # Composite: bench relevance × AI lift × size weight × funding boost
    size_weight = {"startup": 0.6, "growth": 0.8, "mid_market": 1.0, "enterprise": 0.7}.get(
        size_band, 0.5
    )
    funding_boost = 1.15 if funding_180 else 1.0
    layoff_discount = 0.85 if layoff else 1.0
    composite = round(
        bench_score * (1 + ai_score * 0.2) * size_weight * funding_boost * layoff_discount,
        4,
    )

    return {
        "company_name": company_name,
        "sector": sector,
        "size_band": size_band,
        "ai_readiness_band": ai_band,
        "funding_180d": funding_180,
        "has_layoff_signal": layoff,
        "bench_match_score": bench_score,
        "composite_score": composite,
    }


def build_market_space(csv_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load the Crunchbase CSV and score every company for the market-space map.

    Args:
        csv_path: Override the default path to crunchbase_odm_sample.csv.

    Returns:
        DataFrame with all scored companies, one row per company.
    """
    path = csv_path or CRUNCHBASE_CSV
    if not path.exists():
        logger.error("Crunchbase CSV not found at '%s'", path)
        return pd.DataFrame()

    df = pd.read_csv(path, low_memory=False)
    logger.info("Loaded %d companies from '%s'", len(df), path)

    records = df.apply(score_company_for_market_map, axis=1).tolist()
    result = pd.DataFrame(records)
    logger.info("Market-space scoring complete: %d rows", len(result))
    return result


def get_top_cells(df: pd.DataFrame, top_n: int = 5) -> list[dict]:
    """
    Group scored companies by (sector, size_band, ai_readiness_band) and
    return the top N cells ranked by opportunity score.

    Cell score = population × avg_bench_match × (1 + ai_readiness_numeric)

    Args:
        df:     Output of build_market_space().
        top_n:  Number of top cells to return.

    Returns:
        List of dicts, each describing one market-space cell.
    """
    if df.empty:
        return []

    # Map ai_readiness_band → numeric for weighting
    ai_numeric = {"none": 0, "early": 1, "developing": 2, "advanced": 3}
    df = df.copy()
    df["ai_readiness_num"] = df["ai_readiness_band"].map(ai_numeric).fillna(0)

    # job_velocity is optional; use 0 if absent
    if "job_velocity" not in df.columns:
        df["job_velocity"] = 0.0

    group_cols = ["sector", "size_band", "ai_readiness_band"]
    grouped = df.groupby(group_cols, observed=True)

    cells: list[dict] = []
    for name, grp in grouped:
        sector, size_band, ai_band = name
        population = len(grp)
        avg_bench = round(float(grp["bench_match_score"].mean()), 4)
        avg_funding = round(float(grp["funding_180d"].astype(float).mean()), 4)
        avg_hiring_velocity = round(float(grp["job_velocity"].mean()), 4)
        ai_num = ai_numeric.get(ai_band, 0)
        cell_score = round(population * avg_bench * (1 + ai_num), 4)

        cells.append({
            "sector": sector,
            "size_band": size_band,
            "ai_readiness_band": ai_band,
            "population": population,
            "avg_funding_180d_rate": avg_funding,
            "avg_hiring_velocity": avg_hiring_velocity,
            "avg_bench_match": avg_bench,
            "cell_score": cell_score,
        })

    cells.sort(key=lambda c: c["cell_score"], reverse=True)
    return cells[:top_n]
