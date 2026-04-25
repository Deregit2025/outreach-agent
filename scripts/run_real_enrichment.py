#!/usr/bin/env python3
"""
Real Enrichment Demo — runs the FULL pipeline on a live company.

Target: Airbyte (data integration platform, Series B, Python-heavy)
  - Crunchbase ODM lookup (minimal — Airbyte may not be in the 1k-row sample)
  - layoffs.fyi lookup (real check)
  - Playwright job scraping from Wellfound (REAL web scrape)
  - AI maturity scoring from description
  - Competitor gap brief from Crunchbase peers
  - Agent cold email -> staff sink (kill switch ON)

Usage:
    python scripts/run_real_enrichment.py

Requirements:
    playwright install chromium   (run this once if not done)
"""

from __future__ import annotations

import io
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("real_enrichment")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from enrichment.pipeline import enrich_prospect
from enrichment.schemas.prospect import Prospect
from agent.agent import run as agent_run
from agent.state import ConversationState
from channels.channel_router import ChannelRouter

# ── Target company ────────────────────────────────────────────────────────────
# Airbyte: open-source data integration, Series B ($150M), Python/data stack,
# ~350 employees, HQ San Francisco. Perfect Tenacious ICP target.
COMPANY_NAME = "Airbyte"
WELLFOUND_SLUG = "airbyte"      # wellfound.com/company/airbyte/jobs
CAREERS_URL = "https://airbyte.com/careers"

# Synthetic contact for the demo (challenge rule: no real contact data)
CONTACT = {
    "contact_first_name": "Alex",
    "contact_last_name": "Rivera",
    "contact_email": "alex.rivera@airbyte.io",   # synthetic — routed to staff sink via kill switch
    "contact_title": "VP Engineering",
    "contact_phone": "+14155550199",
}


def main() -> None:
    print(f"\n{'='*65}")
    print(f"  REAL ENRICHMENT DEMO — {COMPANY_NAME}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*65}\n")

    print("Step 1: Running full enrich_prospect() pipeline ...")
    print("  -> Crunchbase ODM lookup")
    print("  -> layoffs.fyi lookup")
    print("  -> Playwright job scraping (wellfound + careers page)")
    print("  -> AI maturity scoring")
    print("  -> Competitor gap brief\n")

    t0 = time.perf_counter()

    # Pass wellfound_slug so the job scraper hits Wellfound
    # enrich_prospect does Crunchbase lookup first; Airbyte may not be in the
    # 1k-row ODM sample, so it falls back to a minimal Prospect.
    # The Playwright scrape still runs via get_job_velocity_signal.
    prospect, brief, comp_brief = enrich_prospect(
        company_name=COMPANY_NAME,
        prospect_id="real001",
        wellfound_slug=WELLFOUND_SLUG,
        website_override=CAREERS_URL.replace("/careers", ""),
    )

    enrich_elapsed = round(time.perf_counter() - t0, 2)

    # Inject synthetic contact details (not scraped from a real person)
    prospect.contact_first_name = CONTACT["contact_first_name"]
    prospect.contact_last_name = CONTACT["contact_last_name"]
    prospect.contact_email = CONTACT["contact_email"]
    prospect.contact_title = CONTACT["contact_title"]
    prospect.contact_phone = CONTACT["contact_phone"]

    # Also override careers URL hint for the scraper (already ran, but useful for log)
    prospect.website = "https://airbyte.com"

    print(f"Enrichment complete in {enrich_elapsed:.1f}s\n")
    print(f"  Company       : {prospect.company_name}")
    print(f"  ICP segment   : {prospect.icp_segment} ({prospect.icp_confidence})")
    print(f"  AI maturity   : {prospect.ai_maturity_score}/3 ({prospect.ai_maturity_confidence})")
    print(f"  Employee range: {prospect.employee_count_raw or 'unknown'}")
    print(f"  Industries    : {', '.join(prospect.industries[:3]) or 'none'}")

    print(f"\n  Hiring Signal Brief:")
    for sig in brief.all_signals():
        print(f"    [{sig.signal_type:20s}] {sig.value[:60]}  conf={sig.confidence}")

    print(f"\n  Competitor Gap Brief:")
    print(f"    Hook: {comp_brief.gap_hook[:120] if comp_brief.gap_hook else 'none'}")
    print(f"    Peers analyzed: {len(comp_brief.peers)}")
    for gap in comp_brief.gaps[:3]:
        print(f"    Gap: {gap.capability} — {gap.evidence[:60]}")

    # Show job velocity specifically (the Playwright scrape result)
    if brief.job_velocity:
        print(f"\n  Job Velocity (Playwright scraped):")
        print(f"    Value   : {brief.job_velocity.value}")
        print(f"    Evidence: {brief.job_velocity.evidence[:100]}")
        print(f"    Confidence: {brief.job_velocity.confidence}")
    else:
        print(f"\n  Job Velocity: no signal (careers page may have blocked scraper)")

    # Load briefs from disk to confirm they were saved
    brief_path = Path("data/processed/hiring_signal_briefs/real001.json")
    comp_path  = Path("data/processed/competitor_gap_briefs/real001.json")
    print(f"\n  Briefs saved:")
    print(f"    {brief_path}  ({brief_path.stat().st_size // 1024}KB)" if brief_path.exists() else f"    {brief_path}  MISSING")
    print(f"    {comp_path}   ({comp_path.stat().st_size // 1024}KB)" if comp_path.exists() else f"    {comp_path}  MISSING")

    print(f"\n{'='*65}")
    print("Step 2: Running agent -> send cold email to staff sink ...")
    print(f"{'='*65}\n")

    # If ODM didn't find the company, ICP classifier abstains.
    # Fall back to segment 1 (active hiring = fresh-growth pattern) when
    # job_velocity is the only signal and no disqualifiers exist.
    if not prospect.icp_segment:
        prospect.icp_segment = 1
        prospect.icp_confidence = "medium"
        brief.recommended_segment = 1
        brief.segment_confidence = "medium"
        print("\n  [Note] No Crunchbase record found — defaulting to segment 1 (active hiring signal)")

    state = ConversationState(
        prospect_id="real001",
        company_name=COMPANY_NAME,
        segment=prospect.icp_segment or 1,
        segment_confidence=prospect.icp_confidence or "medium",
    )
    router = ChannelRouter()

    t1 = time.perf_counter()
    result = agent_run(
        prospect=prospect,
        brief=brief,
        comp_brief=comp_brief,
        state=state,
        router=router,
    )
    agent_elapsed = round(time.perf_counter() - t1, 2)

    print(f"  Action : {result.get('action')}")
    print(f"  Sent   : {result.get('sent')}  ({agent_elapsed:.2f}s)")
    print(f"  Subject: {result.get('subject', '')[:80]}")
    print(f"  Error  : {result.get('error')}")
    if result.get("body"):
        print(f"\n  Email body (first 10 lines):")
        for line in result["body"].splitlines()[:10]:
            print(f"    {line}")

    print(f"\n{'='*65}")
    print("  Done.")
    print(f"  Check derejederib@gmail.com for the email.")
    print(f"  Briefs at data/processed/hiring_signal_briefs/real001.json")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
