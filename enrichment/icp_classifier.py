from __future__ import annotations

from enrichment.schemas.prospect import Prospect
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief


def classify_segment(
    prospect: Prospect,
    brief: HiringSignalBrief,
) -> tuple[int, str]:
    has_leadership = brief.leadership_change is not None
    has_layoff = brief.layoff is not None
    has_funding = brief.funding is not None

    leadership_age = (
        brief.leadership_change.data_age_days
        if has_leadership and brief.leadership_change.data_age_days is not None
        else None
    )

    emp_min = prospect.employee_count_min
    emp_max = prospect.employee_count_max

    # Segment 3: leadership transition
    if has_leadership and leadership_age is not None and leadership_age <= 90:
        return (3, "high")

    # Segment 2: restructuring
    if has_layoff:
        if emp_min is not None and emp_min >= 200:
            return (2, "high")
        return (2, "medium")

    # Segment 1: funded startup
    if has_funding:
        if emp_max is not None and emp_max <= 200:
            return (1, "high")
        return (1, "medium")

    # Segment 4: capability gap
    ai_score = prospect.ai_maturity_score or 0
    if ai_score >= 2:
        return (4, "medium")

    return (0, "abstain")
