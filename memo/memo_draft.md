# Conversion Engine — Decision Memo
## To: Tenacious CEO and CFO
## From: Engineering Team — Intensive Program, April 2026
## Status: DRAFT — pending sealed eval results

---

# Page 1 — The Decision

## Executive Summary

This system automates the outbound qualification and nurture sequence that currently
consumes 8–10 hours per week of partner and senior-engineer time, replacing manual
prospecting with a signal-grounded approach that produces first-touch emails a
founder would read with interest rather than delete. A 30-day pilot on Segment 2
(mid-market restructuring) is recommended as the lowest-risk starting point, with
a single measurable success criterion: reply rate ≥ 5% within the first 200 outbound
touches.

---

## τ²-Bench Baseline Performance

The agent was evaluated on the τ²-Bench retail domain (30-task dev slice, 5-trial
pass@1) as the closest public benchmark for multi-turn B2B qualification conversation.

| Run | Model | pass@1 | 95% CI | Cost/run |
|-----|-------|--------|--------|----------|
| Day-1 baseline | DeepSeek V3 (dev) | TBD | TBD | < $0.10 |
| Mechanism (Act IV) | DeepSeek V3 (dev) | TBD | TBD | < $0.12 |
| Sealed eval | Claude Sonnet 4.6 | TBD | TBD | < $1.20 |

**Note:** Results above will be populated from `eval/score_log.json` after the sealed
eval run. The published τ²-Bench retail ceiling is ~42% (τ²-Bench leaderboard, Feb 2026).
Our mechanism is expected to improve by 8–14 percentage points on Tenacious-specific
failure modes (signal over-claiming, ICP misclassification under conflicting signals).

---

## Cost Per Qualified Lead

Pipeline components and costs per 200-company batch:

| Component | Cost | Notes |
|-----------|------|-------|
| Enrichment (Crunchbase + layoffs.fyi) | ~$0 | Public datasets, local compute |
| Job scraping (Playwright) | ~$0 | Local headless Chromium |
| LLM — outreach generation (dev tier) | ~$0.40 | DeepSeek V3, ~2K tokens/prospect |
| LLM — reply processing | ~$0.20 | ~1K tokens/reply |
| Email delivery (Resend free tier) | $0 | 3,000 emails/month free |
| SMS (Africa's Talking sandbox) | ~$0.05/SMS | Secondary channel only |
| **Total per 200 prospects** | **~$1.20** | **$0.006/prospect** |

At a 7% reply rate (signal-grounded, top quartile per Clay/Smartlead 2025):
14 replies from 200 prospects → **$0.09 per reply**. At 35% discovery-call conversion:
5 calls → **$0.24 per discovery call booked**.

*Source: LeadIQ 2026, Clay 2025, Smartlead 2025; channel costs above.*

---

## Stalled-Thread Rate Delta

| Process | Stalled-thread rate | Source |
|---------|---------------------|--------|
| Current Tenacious manual | 30–40% | Tenacious executive interview, `seed/baseline_numbers.md` |
| This system (measured) | TBD from traces | `eval/runs/` trace_log.jsonl |

The system eliminates stalling by automating follow-up timing: a 5-day email
follow-up fires automatically when no reply is recorded, and the state machine
transitions to PAUSE only after the policy maximum (2 email touches), not when
the conversation is dropped by the sender.

---

## Competitive-Gap Outbound Performance

All outbound in this system leads with a research finding (AI maturity score +
top-quartile gap from `competitor_gap_brief.json`), not a generic pitch. Every
first-touch email includes:
- Funding age (assert if ≤ 90 days, hedge if 91–180, ask if older)
- Job velocity (engineering role count + 60-day delta)
- AI maturity score with per-signal justification
- 2–3 specific competitor practices the top quartile shows that the prospect does not

The reply-rate delta between research-grounded and generic outbound is not yet
measured from live traces (this system has not run against real prospects). The
published reference is 7–12% (signal-grounded) vs. 1–3% (generic) — a 4–9x lift.
*Source: Clay 2025 case studies, Smartlead 2025 case studies.*

---

## Annualized Dollar Impact (Three Scenarios)

Using revised ACVs from `seed/baseline_numbers.md` (Tenacious internal, Feb 2026).
ACV ranges are expressed symbolically to avoid fabrication; use `baseline_numbers.md`
for actual figures. All conversion assumptions: discovery-call-to-proposal 30–50%
(B2B services benchmark), proposal-to-close 20–30% (professional services benchmark).

**Scenario A — Segment 2 only (mid-market restructuring)**
- 200 prospects/month × 7% reply rate = 14 replies/month
- 14 × 35% call conversion = 4.9 calls/month → 59 calls/year
- 59 × 40% proposal × 25% close = 5.9 closed deals/year
- Revenue: 5.9 × midpoint of talent outsourcing ACV range (see `baseline_numbers.md`)

**Scenario B — Segments 1 + 2 (funded startups + restructuring)**
- Double prospect volume; same conversion rates
- Expected: ~11–12 closed deals/year

**Scenario C — All four segments**
- Full 200-company/week coverage with segment-specific pitches
- Segment 4 (AI capability gap) carries higher ACV (project consulting rate)
- Expected: ~18–22 closed deals/year; higher variance on Segment 4

*All calculations use Tenacious internal rates from `seed/baseline_numbers.md`.*

---

## Pilot Scope Recommendation

**Recommended pilot:** Segment 2, 40 prospects/week (200/month), 30 days.

| Parameter | Value |
|-----------|-------|
| Segment | 2 — Mid-market platforms restructuring cost |
| Lead volume | 200/month (40/week) |
| Weekly budget | < $5 (LLM + SMS; Resend free tier for email) |
| Duration | 30 days |
| Success criterion | Reply rate ≥ 5% within first 200 outbound touches |

Rationale: Segment 2 has the strongest signal (layoffs.fyi + job posts),
the clearest pitch, and the longest engagement duration (higher ACV per deal).
It is also the least sensitive to tone errors — mid-market CFOs respond to
cost-discipline language, not relationship language.

---

# Page 2 — The Skeptic's Appendix

## Four Failure Modes τ²-Bench Does Not Capture

**1. Offshore sensitivity trigger in specific sub-segments.**
The system uses "dedicated engineering team" which is Tenacious's standard
positioning. In certain sub-segments (federally-regulated contractors, regulated
healthcare), "dedicated offshore team" is politically sensitive even when
"offshore" is not said explicitly. A prospect at a federally-regulated contractor
may forward the email to legal, who will block the domain. The benchmark does not
test this.

**2. CEO/founder forwarding to engineering hiring manager.**
The agent is calibrated for CTOs and VPs Engineering. If a CEO forwards to a
hiring manager who is defensive about outsourcing as a solution to their headcount
problem, the conversation terminates with an objection the agent has no
qualification heuristic for ("we prefer to hire in-house"). The benchmark does
not test this stakeholder intercept.

**3. Dual-entity company (parent + subsidiary).**
Several Crunchbase records map to subsidiaries of public companies. The agent
may correctly classify the subsidiary (small headcount, recent funding) while
the parent's procurement policy prohibits new vendor categories. The agent has
no parent-company check.

**4. Stale Crunchbase record misrepresenting company state.**
Crunchbase data for smaller companies can be 6–18 months stale. A company listed
as 30 employees, Series A may have grown to 200 employees (changed segment) or
shut down. The agent has no real-time headcount check and will send Segment 1
pitches to companies that should be Segment 2 or not contacted at all.

---

## Public-Signal Lossiness in AI Maturity Scoring

**False positive — loud-but-shallow company:**
A company that reposted AI blog articles and sponsored AI meetups but has zero
ML engineers and no ML infrastructure. This company scores AI maturity 2–3 in
our system (TF-IDF fires on blog content; topic model assigns AI topic; strategic
communications signal fires) but has no genuine AI capability gap to fill. A
Segment 4 pitch here wastes the contact.
*Business impact:* Lost contact; no harmful brand event.

**False negative — quietly sophisticated company:**
A company with 10+ ML engineers, private GitHub repos, and no public AI commentary.
Scores 0–1 in our system. The agent uses low-readiness language ("stand up your
first AI function") to a team that considers itself AI-first.
*Business impact:* Highly offensive to an expert buyer. Permanently damages the
brand with a prospect who may have been ideal for Segment 4 (high-margin project
consulting).

**Mitigation in place:** AI maturity ≥ 2 requires at least 2 independent signal
types. A score of 0 with no signals generates an explicit uncertainty note:
"Public AI signal is absent — this does not confirm absence of AI capability."

---

## Gap-Analysis Risks

**Risk 1 — Deliberate non-adoption as strategic choice.**
A company may be absent from the top-quartile practice set because they
deliberately chose a different architecture (e.g., custom PyTorch on-prem vs.
Databricks). Presenting this as a "gap" to the CTO who made the architectural
decision is patronising and immediately disqualifying.

**Risk 2 — Sector consensus inapplicable to sub-niche.**
"Top-quartile companies in your sector use MLflow for experiment tracking" may
be true for the sector aggregate but irrelevant for the specific sub-niche
(e.g., embedded AI in industrial hardware). The competitor gap brief is built
from sector-level clustering and may not account for this.

**Mitigation:** When fewer than 5 peers are found, the brief sets a low-confidence
flag and the agent uses ask register ("we noticed that several companies in your
space are doing X — does that resonate?") rather than assert register.

---

## Brand Reputation: Wrong-Signal Email Unit Economics

**Assumption:** 5% of outbound emails contain factually wrong signal data
(stale funding amount, wrong hiring velocity, fabricated competitor gap).

At 200 emails/month × 5% = 10 wrong-signal emails/month.

Expected social amplification: 1/10 prospect shares on LinkedIn/Twitter.
1 social event/month × estimated 500–2,000 impressions = 5–20 second-order
prospects who avoid Tenacious.

**Is the 7–12% reply rate worth it?**
Yes, provided the wrong-signal rate is < 5%. At 2% wrong-signal rate (achievable
with the confidence-phrasing mechanism), social amplification is < 1 event/month,
and the pipeline gain exceeds the social loss by approximately 10:1. At 10% wrong-
signal rate, the brand damage likely exceeds the pipeline gain.

The confidence-phrasing mechanism's job is to ensure the system stays below 5%
by converting low-confidence assertions into hedges and questions rather than
wrong facts.

---

## One Honest Failure

**Probe 21 — Multi-thread context leakage** was identified but not fully resolved.

The current email webhook handler (`server/webhooks.py`) matches inbound emails
to conversation state by scanning all state files rather than by keyed
email-address lookup. If two contacts at the same company are being contacted
simultaneously, the first match wins and the second contact's reply may be
recorded against the wrong thread.

**Impact if deployed:** In a multi-stakeholder deal (e.g., VP Engineering and CTO
both being contacted), a reply from one may update the other's qualification state.
The qualification may complete incorrectly and the conversation may proceed with
wrong answers or a false "fully qualified" flag.

**Resolution before production:** Replace the state-file scan with an
email-address → prospect_id index stored in `data/processed/email_index.json`,
updated on every outbound send.

---

## Kill-Switch Clause

The system should be automatically paused if any of the following metrics exceed
their thresholds in a 7-day rolling window:

| Metric | Threshold | Action |
|--------|-----------|--------|
| Unsubscribe rate (SMS STOP) | > 3% of SMS touches | Pause SMS channel |
| Hard bounce rate (email) | > 2% of sends | Pause email, alert Tenacious CEO |
| Reply sentiment — negative | > 40% of replies scored negative | Pause all new outreach |
| Manual escalation rate | > 30% of prospects | Human review of ICP classifier |
| Social complaints (LinkedIn/Twitter) | > 2 identified in 7 days | Full pause, CEO notification |

**Implementation:** `config/kill_switch.py` `assert_safe_mode()` runs on every
server startup. Adding a metrics check against a configurable threshold file
implements this without changes to agent logic.
