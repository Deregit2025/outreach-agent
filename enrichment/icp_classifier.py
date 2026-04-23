from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Any

from enrichment.schemas.prospect import Prospect
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief


def _load_icp_definitions() -> Dict[str, Any]:
    """Load ICP definitions from the tenacious_sales_data/seed/icp_definition.md file."""
    icp_path = Path("data/tenacious_sales_data/seed/icp_definition.md")
    
    if not icp_path.exists():
        # Fallback definitions based on the template
        return {
            1: {
                "name": "Recently-funded Series A/B startups",
                "qualifying_filters": {
                    "funding_amount_min": 5000000,
                    "funding_amount_max": 30000000,
                    "funding_age_days_max": 180,
                    "headcount_min": 15,
                    "headcount_max": 80,
                    "open_roles_min": 5
                },
                "disqualifying_filters": ["corporate_investor", "anti_offshore", "competitor_client", "recent_layoff"]
            },
            2: {
                "name": "Mid-market platforms restructuring cost",
                "qualifying_filters": {
                    "headcount_min": 200,
                    "headcount_max": 2000,
                    "layoff_age_days_max": 120
                },
                "disqualifying_filters": ["layoff_percentage_high", "bankruptcy", "complex_regulation"]
            },
            3: {
                "name": "Engineering-leadership transitions",
                "qualifying_filters": {
                    "leadership_age_days_max": 90,
                    "headcount_min": 50,
                    "headcount_max": 500
                },
                "disqualifying_filters": ["interim_leader", "in_house_bias", "existing_vendor"]
            },
            4: {
                "name": "Specialized capability gaps",
                "qualifying_filters": {
                    "ai_maturity_min": 2
                },
                "disqualifying_filters": ["ai_maturity_low", "capability_not_on_bench", "specialist_boutique"]
            }
        }
    
    # Parse the markdown file
    content = icp_path.read_text()
    segments = {}
    
    # Simple parsing - this could be improved with a proper markdown parser
    segment_pattern = r'## Segment (\d+) — (.+?)(?=## Segment|\Z)'
    matches = re.findall(segment_pattern, content, re.DOTALL)
    
    for match in matches:
        segment_num = int(match[0])
        segment_name = match[1].strip()
        
        # Extract qualifying filters
        qualifying = {}
        funding_match = re.search(r'Closed a Series A or Series B round.*?\$(\d+)M–\$(\d+)M.*?last.*?(\d+).*?days', match[1], re.DOTALL)
        if funding_match:
            qualifying['funding_amount_min'] = int(funding_match.group(1)) * 1000000
            qualifying['funding_amount_max'] = int(funding_match.group(2)) * 1000000
            qualifying['funding_age_days_max'] = int(funding_match.group(3))
        
        headcount_match = re.search(r'headcount.*?(\d+)–(\d+)', match[1], re.DOTALL)
        if headcount_match:
            qualifying['headcount_min'] = int(headcount_match.group(1))
            qualifying['headcount_max'] = int(headcount_match.group(2))
        
        leadership_match = re.search(r'New.*?CTO.*?VP Engineering.*?appointed.*?last.*?(\d+).*?days', match[1], re.DOTALL)
        if leadership_match:
            qualifying['leadership_age_days_max'] = int(leadership_match.group(1))
        
        ai_match = re.search(r'AI-readiness score.*?(\d+)', match[1], re.DOTALL)
        if ai_match:
            qualifying['ai_maturity_min'] = int(ai_match.group(1))
        
        segments[segment_num] = {
            "name": segment_name,
            "qualifying_filters": qualifying,
            "disqualifying_filters": []  # Would need more parsing for disqualifiers
        }
    
    return segments


_ICP_DEFINITIONS = _load_icp_definitions()


def classify_segment(
    prospect: Prospect,
    brief: HiringSignalBrief,
) -> tuple[int, str]:
    """
    Classify prospect into ICP segment based on the loaded definitions.
    Returns (segment_number, confidence) where segment 0 means no match.
    """
    
    # Check each segment in priority order (3, 2, 1, 4)
    segments_to_check = [3, 2, 1, 4]
    
    for segment_num in segments_to_check:
        if segment_num not in _ICP_DEFINITIONS:
            continue
            
        definition = _ICP_DEFINITIONS[segment_num]
        filters = definition["qualifying_filters"]
        
        match = True
        confidence = "medium"
        
        # Segment 3: Engineering-leadership transitions
        if segment_num == 3:
            has_leadership = brief.leadership_change is not None
            leadership_age = (
                brief.leadership_change.data_age_days
                if has_leadership and brief.leadership_change.data_age_days is not None
                else None
            )
            
            if not (has_leadership and leadership_age is not None and leadership_age <= filters.get('leadership_age_days_max', 90)):
                match = False
            else:
                emp_min = prospect.employee_count_min
                emp_max = prospect.employee_count_max
                headcount_ok = (
                    (emp_min is None or emp_min >= filters.get('headcount_min', 50)) and
                    (emp_max is None or emp_max <= filters.get('headcount_max', 500))
                )
                if not headcount_ok:
                    match = False
                else:
                    confidence = "high"
        
        # Segment 2: Mid-market platforms restructuring cost
        elif segment_num == 2:
            has_layoff = brief.layoff is not None
            if not has_layoff:
                match = False
            else:
                emp_min = prospect.employee_count_min
                if emp_min is not None and emp_min >= filters.get('headcount_min', 200):
                    confidence = "high"
                else:
                    confidence = "medium"
        
        # Segment 1: Recently-funded Series A/B startups
        elif segment_num == 1:
            has_funding = brief.funding is not None
            if not has_funding:
                match = False
            else:
                emp_max = prospect.employee_count_max
                if emp_max is not None and emp_max <= filters.get('headcount_max', 200):
                    confidence = "high"
                else:
                    confidence = "medium"
        
        # Segment 4: Specialized capability gaps
        elif segment_num == 4:
            ai_score = prospect.ai_maturity_score or 0
            if ai_score < filters.get('ai_maturity_min', 2):
                match = False
            else:
                confidence = "medium"
        
        if match:
            return (segment_num, confidence)
    
    return (0, "abstain")
