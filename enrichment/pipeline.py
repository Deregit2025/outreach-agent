from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

from enrichment.schemas.prospect import Prospect
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief, SignalItem
from enrichment.schemas.competitor_gap_brief import CompetitorGapBrief
from enrichment.crunchbase_lookup import (
    lookup_by_name,
    parse_funding_rounds,
    parse_leadership_hires,
    parse_layoff_events,
    parse_tech_stack,
    parse_employee_range,
    parse_industries,
)
from enrichment.layoffs_lookup import check_layoff
from enrichment.ai_maturity_scorer import score_ai_maturity
from enrichment.icp_classifier import classify_segment
from enrichment.competitor_finder import find_peers, build_competitor_gap_brief
from enrichment.evidence_graph import log_decision

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIEFS_DIR = PROJECT_ROOT / "data" / "processed" / "hiring_signal_briefs"
COMP_DIR = PROJECT_ROOT / "data" / "processed" / "competitor_gap_briefs"


def _funding_signal(prospect: Prospect) -> SignalItem | None:
    if not prospect.funding_rounds:
        return None
    latest = prospect.funding_rounds[0]
    age_days: int | None = None
    if latest.announced_on:
        try:
            event_date = datetime.strptime(latest.announced_on, "%Y-%m-%d").date()
            age_days = (datetime.now(timezone.utc).date() - event_date).days
        except ValueError:
            pass
    return SignalItem(
        signal_type="funding",
        value=latest.title or "Funding round",
        evidence=f"Round: {latest.title or 'unknown'}, announced {latest.announced_on or 'unknown'}",
        confidence="high" if latest.title else "medium",
        data_age_days=age_days,
        language_register="assert",
    )


def _leadership_signal(prospect: Prospect) -> SignalItem | None:
    if not prospect.leadership_hires:
        return None
    hire = prospect.leadership_hires[0]
    age_days: int | None = None
    if hire.key_event_date:
        try:
            event_date = datetime.strptime(hire.key_event_date[:10], "%Y-%m-%d").date()
            age_days = (datetime.now(timezone.utc).date() - event_date).days
        except ValueError:
            pass
    return SignalItem(
        signal_type="leadership_change",
        value=hire.label,
        evidence=f"Leadership hire: {hire.label} on {hire.key_event_date or 'unknown'}",
        confidence="high" if age_days is not None and age_days <= 90 else "medium",
        data_age_days=age_days,
        language_register="ask",
    )


def _layoff_signal_from_crunchbase(prospect: Prospect) -> SignalItem | None:
    if not prospect.layoff_events:
        return None
    event = prospect.layoff_events[0]
    age_days: int | None = None
    if event.key_event_date:
        try:
            event_date = datetime.strptime(event.key_event_date[:10], "%Y-%m-%d").date()
            age_days = (datetime.now(timezone.utc).date() - event_date).days
        except ValueError:
            pass
    return SignalItem(
        signal_type="layoff",
        value=event.label,
        evidence=f"Layoff event: {event.label} on {event.key_event_date or 'unknown'} (Crunchbase)",
        confidence="high",
        data_age_days=age_days,
        language_register="hedge",
    )


def _layoff_signal_from_fyi(fyi_row: dict) -> SignalItem | None:
    if not fyi_row:
        return None
    date_str = str(fyi_row.get("date", ""))
    age_days: int | None = None
    if date_str:
        try:
            event_date = datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
            age_days = (datetime.now(timezone.utc).date() - event_date).days
        except ValueError:
            pass
    total = fyi_row.get("total_laid_off", "")
    pct = fyi_row.get("percentage_laid_off", "")
    evidence = f"Layoffs.fyi: {total} employees laid off ({pct}% of workforce) on {date_str}"
    return SignalItem(
        signal_type="layoff",
        value=f"{total} employees",
        evidence=evidence,
        confidence="high",
        data_age_days=age_days,
        language_register="hedge",
    )


def _tech_signal(prospect: Prospect) -> SignalItem | None:
    if not prospect.tech_stack:
        return None
    names = [t.name for t in prospect.tech_stack[:5]]
    return SignalItem(
        signal_type="tech_stack",
        value=", ".join(names),
        evidence=f"Detected technologies: {', '.join(names)}",
        confidence="medium",
        data_age_days=None,
        language_register="ask",
    )


def _ai_maturity_signal(score: int, confidence: str, justification: list[str]) -> SignalItem:
    score_labels = {0: "none", 1: "early", 2: "developing", 3: "advanced"}
    register = "assert" if score >= 2 else "ask"
    return SignalItem(
        signal_type="ai_maturity",
        value=score_labels.get(score, "unknown"),
        evidence="; ".join(justification) if justification else "No AI signals detected",
        confidence=confidence,
        data_age_days=None,
        language_register=register,
    )


def enrich_prospect(
    company_name: str,
    prospect_id: str | None = None,
    wellfound_slug: str | None = None,
    builtin_slug: str | None = None,
    website_override: str | None = None,
) -> tuple[Prospect, HiringSignalBrief, CompetitorGapBrief]:
    if prospect_id is None:
        prospect_id = str(uuid4())[:8]

    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: Crunchbase lookup → build Prospect
    row = lookup_by_name(company_name)
    if row:
        emp_min, emp_max = parse_employee_range(row)
        funding_rounds = parse_funding_rounds(row)
        leadership_hires = parse_leadership_hires(row)
        layoff_events = parse_layoff_events(row)
        tech_stack = parse_tech_stack(row)
        industries = parse_industries(row)
        prospect = Prospect(
            prospect_id=prospect_id,
            crunchbase_id=str(row.get("uuid", "") or ""),
            company_name=str(row.get("name", company_name)),
            website=str(row.get("website", "") or "") or None,
            industries=industries,
            country_code=str(row.get("country_code", "") or "") or None,
            region=str(row.get("region", "") or "") or None,
            employee_count_raw=str(row.get("num_employees", "") or "") or None,
            employee_count_min=emp_min,
            employee_count_max=emp_max,
            description=str(row.get("about", "") or "") or None,
            funding_rounds=funding_rounds,
            leadership_hires=leadership_hires,
            layoff_events=layoff_events,
            tech_stack=tech_stack,
            last_enriched_at=now_iso,
        )
    else:
        prospect = Prospect(
            prospect_id=prospect_id,
            company_name=company_name,
            last_enriched_at=now_iso,
        )

    # Step 2: Layoffs.fyi lookup → layoff signal
    fyi_row = check_layoff(company_name)

    # Step 3a: Build combined company text for NLP modules
    full_description = str(row.get("full_description", "") or "") if row else ""
    tech_highlights_raw = str(row.get("technology_highlights", "") or "") if row else ""

    # Step 3b: Score AI maturity (now uses TF-IDF + topic signals internally)
    ai_score, ai_confidence, ai_justification = score_ai_maturity(
        tech_stack=prospect.tech_stack,
        leadership_hires=prospect.leadership_hires,
        industries=prospect.industries,
        description=prospect.description or "",
        full_description=full_description,
        technology_highlights_raw=tech_highlights_raw,
    )
    prospect.ai_maturity_score = ai_score
    prospect.ai_maturity_confidence = ai_confidence

    log_decision(
        prospect_id=prospect_id,
        decision_type="ai_maturity",
        inputs={
            "tech_stack": [t.name for t in prospect.tech_stack[:5]],
            "leadership_hires": [h.label for h in prospect.leadership_hires[:3]],
            "industries": prospect.industries[:3],
            "description_length": len(prospect.description or ""),
            "full_description_length": len(full_description),
        },
        logic=(
            f"AI maturity scored {ai_score}/3 with {ai_confidence} confidence "
            f"from {len(ai_justification)} signals"
        ),
        output={"score": ai_score, "confidence": ai_confidence, "justifications": ai_justification},
        decision=f"ai_maturity:{ai_score} ({ai_confidence})",
    )

    # Step 3c: Job velocity — scrape public job posts
    # Use explicit overrides if provided, otherwise derive from Crunchbase website
    if website_override and not prospect.website:
        prospect.website = website_override
    job_velocity_sig: SignalItem | None = None
    try:
        from scraper.job_scraper import get_job_velocity_signal
        website = prospect.website or ""
        careers_url = (website.rstrip("/") + "/careers") if website else None
        jv = get_job_velocity_signal(
            company_name=company_name,
            wellfound_slug=wellfound_slug,
            builtin_slug=builtin_slug,
            careers_url=careers_url,
        )
        if jv:
            job_velocity_sig = SignalItem(
                signal_type=jv["signal_type"],
                value=jv["value"],
                evidence=jv["evidence"],
                confidence=jv["confidence"],
                language_register=jv["language_register"],
            )
            log_decision(
                prospect_id=prospect_id,
                decision_type="job_velocity",
                inputs={"company_name": company_name, "careers_url": careers_url},
                logic=(
                    f"Job scrape: {jv.get('engineering_role_count', 0)} engineering roles, "
                    f"delta={jv.get('role_delta_60d', 0)}"
                ),
                output=jv,
                decision=f"job_velocity:{jv['value']}",
            )
    except Exception as _jv_exc:
        logger.debug("Job velocity scrape skipped: %s", _jv_exc)

    # Step 4: Build signals
    funding_sig = _funding_signal(prospect)
    leadership_sig = _leadership_signal(prospect)
    layoff_sig = (
        _layoff_signal_from_fyi(fyi_row)
        if fyi_row
        else _layoff_signal_from_crunchbase(prospect)
    )
    tech_sig = _tech_signal(prospect)
    ai_sig = _ai_maturity_signal(ai_score, ai_confidence, ai_justification)

    partial_brief = HiringSignalBrief(
        prospect_id=prospect_id,
        company_name=prospect.company_name,
        generated_at=now_iso,
        funding=funding_sig,
        job_velocity=job_velocity_sig,
        leadership_change=leadership_sig,
        layoff=layoff_sig,
        tech_stack=tech_sig,
        ai_maturity=ai_sig,
    )

    # Step 4: Classify ICP segment
    segment, seg_confidence = classify_segment(prospect, partial_brief)
    prospect.icp_segment = segment if segment != 0 else None
    prospect.icp_confidence = seg_confidence if seg_confidence != "abstain" else None

    log_decision(
        prospect_id=prospect_id,
        decision_type="segment_classification",
        inputs={
            "funding_age_days": partial_brief.funding.data_age_days if partial_brief.funding else None,
            "layoff_age_days": partial_brief.layoff.data_age_days if partial_brief.layoff else None,
            "leadership_age_days": partial_brief.leadership_change.data_age_days if partial_brief.leadership_change else None,
            "ai_maturity_score": ai_score,
            "employee_count_min": prospect.employee_count_min,
            "employee_count_max": prospect.employee_count_max,
        },
        logic=f"Segment {segment} selected with confidence '{seg_confidence}' per ICP priority rules",
        output={"segment": segment, "confidence": seg_confidence},
        decision=f"segment:{segment} ({seg_confidence})",
    )

    pitch_language = "high_readiness" if ai_score >= 2 else "low_readiness"

    active_signals = partial_brief.all_signals()
    summary_parts = [f"{s.signal_type}: {s.value}" for s in active_signals]
    brief_summary = f"{prospect.company_name} — " + "; ".join(summary_parts) if summary_parts else prospect.company_name

    brief = HiringSignalBrief(
        prospect_id=prospect_id,
        company_name=prospect.company_name,
        generated_at=now_iso,
        funding=funding_sig,
        job_velocity=job_velocity_sig,
        leadership_change=leadership_sig,
        layoff=layoff_sig,
        tech_stack=tech_sig,
        ai_maturity=ai_sig,
        recommended_segment=segment if segment != 0 else None,
        segment_confidence=seg_confidence,
        pitch_language_ai=pitch_language,
        brief_summary=brief_summary,
    )

    # Step 5: Find peers → build CompetitorGapBrief
    peers_raw = find_peers(prospect)
    comp_brief = build_competitor_gap_brief(prospect, brief, peers_raw)

    # Step 7: Save to disk
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    COMP_DIR.mkdir(parents=True, exist_ok=True)

    brief_path = BRIEFS_DIR / f"{prospect_id}.json"
    comp_path = COMP_DIR / f"{prospect_id}.json"

    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    comp_path.write_text(comp_brief.model_dump_json(indent=2), encoding="utf-8")

    return prospect, brief, comp_brief


def load_brief(
    prospect_id: str,
) -> tuple[HiringSignalBrief, CompetitorGapBrief] | None:
    brief_path = BRIEFS_DIR / f"{prospect_id}.json"
    comp_path = COMP_DIR / f"{prospect_id}.json"

    if not brief_path.exists() or not comp_path.exists():
        return None

    brief = HiringSignalBrief.model_validate(
        json.loads(brief_path.read_text(encoding="utf-8"))
    )
    comp_brief = CompetitorGapBrief.model_validate(
        json.loads(comp_path.read_text(encoding="utf-8"))
    )
    return brief, comp_brief
