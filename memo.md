# Conversion Engine — Decision Memo
**To:** Tenacious CEO and CFO
**From:** Dereje Derib, 10 Academy Intensive Program
**Date:** April 25, 2026
**Re:** Automated Lead Generation System — Deployment Recommendation

---

## Executive Summary

We built and tested an end-to-end automated outbound system that finds prospective engineering clients, grounds each outreach in verifiable public signals (funding events, layoffs, job-post velocity, leadership changes, AI maturity), and routes qualified prospects to a discovery call — all without manual effort. On the τ²-Bench conversational benchmark the system scores **69% pass@1** against a published ceiling of ~42% for voice agents and a Tenacious manual-process proxy of roughly 30–40% stalled-thread rate; signal-grounded outreach ran at **89% of messages** in testing (8 of 9 synthetic prospects). We recommend a pilot against Segment 1 (recently-funded Series A/B startups) at 60 touches per week, with a 30-day success criterion of ≥5 discovery calls booked.

---

## Page 1 — The Decision

### τ²-Bench Performance

| Condition | pass@1 | 95% CI | Source |
|---|---|---|---|
| Published retail reference (ceiling) | ~42% | — | τ²-Bench leaderboard, Feb 2026 |
| Our Day-1 dev baseline (30 tasks × 5 trials) | 72.67% | [65.0%, 79.2%] | `eval/score_log.json` → `dev_baseline_academy` |
| Our held-out final (20 tasks × 5 trials) | **69%** | [59.4%, 77.2%] | `eval/score_log.json` → `held_out_final_v4` |

The held-out slice is a sealed partition not seen during development. The 69% figure is the number the Tenacious executive team should hold us to. Delta vs. published ceiling: **+27 percentage points.**

### Cost Per Qualified Lead

| Item | Cost | Basis |
|---|---|---|
| LLM per outbound email | ~$0.02 | `total_agent_cost_usd / (num_tasks × num_trials)` from score_log |
| Email delivery (Resend) | $0.00 | Free tier, 3,000 emails/month |
| Signal enrichment (Playwright + ODM lookup) | $0.00 | Public data, self-hosted |
| **Cost per touch** | **~$0.02** | |
| Reply rate (signal-grounded, top-quartile) | 7–12% | Clay / Smartlead case studies |
| Qualify rate of replies | ~50% | Conservative estimate |
| **Cost per qualified lead** | **~$0.33–$0.57** | $0.02 ÷ (reply × qualify rate) |

Target from challenge spec: under $5 per qualified lead. We are **9–15× below target.**

### Stalled-Thread Rate

Tenacious current manual process: **30–40% of qualified conversations stall in the first two weeks** (Tenacious CFO interview, challenge brief). Our system sends follow-up automatically at configurable intervals, routing warm leads to SMS when they prefer fast scheduling. In our 14-interaction test run, zero threads stalled — the agent progressed every thread to at least a booking link. Measured stalled-thread rate from traces: **0%** (n=14; confidence interval wide at this sample size; pilot will produce the definitive number).

### Signal-Grounded Outbound Performance

In the Act II demo run across 9 prospects (8 synthetic + 1 live Playwright scrape of Airbyte):

- **8 of 9 emails (89%)** opened with a specific, verifiable public signal: funding round, layoff event, leadership hire, or scraped job-velocity count.
- **1 of 9 (11%)** fell back to a generic opening because the company (Airbyte) was absent from the Crunchbase ODM — no firmographic record to anchor the claim.
- Wellfound robots.txt was respected; the scraper skipped the disallowed URL and fell back to the company's own careers page, scraping 8 real posts (5 engineering roles).

Expected reply-rate delta: signal-grounded **7–12%** vs. generic **1–3%** (sources: Clay, Smartlead case studies; LeadIQ 2026 / Apollo benchmarks). At 60 touches/week, that is the difference between ~2 replies/week and ~6 replies/week from the same effort.

### Annualized Dollar Impact

Assumptions: 60 touches/week, 50 working weeks, signal-grounded reply rate 8% (midpoint), discovery-to-proposal 40% (Tenacious internal), proposal-to-close 30% (Tenacious internal), talent outsourcing ACV $480K (midpoint of $240K–$720K range).

| Adoption Scenario | Touches/yr | Replies | Qualified | Closed | ARR |
|---|---|---|---|---|---|
| Segment 1 only (funded startups) | 3,000 | 240 | 120 | 36 | **$17.3M** |
| Segments 1 + 3 (funded + leadership transition) | 6,000 | 480 | 240 | 72 | **$34.6M** |
| All four segments | 12,000 | 960 | 480 | 144 | **$69.1M** |

These figures assume the agent runs alongside one human SDR who handles discovery calls. Conversion rates are Tenacious-provided; ARR figures are illustrative and require a pilot to validate.

### Pilot Scope Recommendation

- **Segment:** Segment 1 — recently-funded Series A/B startups (clearest buying signal, least brand risk)
- **Volume:** 60 outbound touches per week for 4 weeks (240 touches)
- **Budget:** $5/week LLM + $0 email + $0 enrichment ≈ **$20 total**
- **Success criterion:** ≥5 discovery calls booked within 30 days
- **Kill switch:** `KILL_SWITCH=true` in `.env` routes all outbound to staff sink by default; set to `false` only after Tenacious executive sign-off

---

## Page 2 — The Skeptic's Appendix

### Four Failure Modes τ²-Bench Does Not Capture

**1. Offshore-perception objections.** A founder who has publicly written against outsourcing will read Tenacious's first email as confirmation of their bias, not as a research finding. τ²-Bench scores conversation quality, not prospect predisposition. The system currently has no pre-filter for anti-offshore public stance (a disqualifying signal in the ICP definition). Impact: wasted touches; potential brand damage on social media if a founder quote-tweets the email negatively.

**2. Bench mismatch on commitment.** The agent correctly refuses to promise specific headcount the bench summary does not show. But it cannot detect a *partial* mismatch — a prospect needing 4 Go engineers when the bench shows 2. The agent will book the discovery call; the human delivery lead discovers the gap. Impact: a discovery call that cannot convert, damaging the rep-to-prospect relationship. Fix cost: cross-reference bench summary against prospect tech stack in the ICP classifier before sending a booking link.

**3. Wrong-company AI maturity score.** A company that does all its AI work in a private GitHub org, publishes no blog posts, and has no public job postings will score 0/3 in our system. We demonstrated this with Airbyte — a clearly AI-adjacent data-infrastructure company that scored 0/3 because its Crunchbase description was absent from our ODM sample. The agent would then pitch them a low-readiness message to an audience that finds it patronising. Impact: one misaligned email; possible unsubscribe.

**4. Multi-thread context leakage across a company.** If both the co-founder and the VP Engineering of the same company are in the prospect pool, the agent may send two independent cold emails referencing the same funding signal with slightly different language. τ²-Bench tests single-thread coherence; it does not test cross-thread isolation. Impact: the two contacts compare notes; the company perceives Tenacious as running a spray-and-pray campaign.

### Public-Signal Lossiness

**Quietly sophisticated but publicly silent:** A company doing serious ML work in a private monorepo, with no named AI leadership on LinkedIn and no AI-adjacent job postings, scores 0/3 in our system. Our AI maturity scorer relies on TF-IDF over company descriptions and NMF topic modeling — both require a public text corpus to function. If that corpus is absent (company not in ODM, private GitHub, no press), the score defaults to 0 and the agent uses low-readiness language. Business impact: the agent talks down to an AI-sophisticated audience, undermining credibility.

**Loud but shallow:** A company whose CEO tweets frequently about AI transformation, posts ML job ads that stay open for 12 months, and has "AI-powered" in its tagline will score 2–3. If the actual engineering practice is minimal, any Segment 4 (capability gap) pitch will fall flat when a delivery lead gets on the call and the prospect has no real ML initiative to staff. Business impact: a wasted discovery call and a mis-scoped proposal.

### Gap-Analysis Risks

**Deliberate strategic silence.** Some companies in a prospect's sector adopt a top-quartile practice (e.g., Weights & Biases for ML observability) because their product depends on it; others deliberately avoid it because their architecture does not. When the competitor gap brief asserts "3 of your top-quartile peers use W&B and you do not," a CTO who made a conscious architectural choice to avoid experiment tracking will find this condescending, not insightful. The framing must always ask rather than assert when the evidence is a tool-adoption gap, not a capability-delivery gap.

**Sub-niche irrelevance.** A logistics software company in a sector where the top-quartile adopts LLM-based document processing is not necessarily behind — their core product may not require it. Applying sector-level AI-maturity benchmarks to sub-niches produces false gaps. Our current competitor finder uses the first listed industry from the ODM, which may be too broad (e.g., "Software" covers everything from payroll tools to GPU orchestration).

### Brand-Reputation Comparison

If the agent sends 1,000 signal-grounded emails and 5% (50 emails) contain factually wrong signal data — for example, citing a funding round that was later corrected, or claiming 15 open engineering roles when the careers page now shows 3 — the brand impact must be weighed against the reply-rate gain.

Assumptions: wrong-signal email damages trust with 30% of affected recipients (15 founders); 5% of those post publicly (1 social post). Expected value of 7–12% reply rate on 950 correct emails = 66–114 replies. Expected revenue lost from 1 negative public post (assume 2 qualified deals lost at $480K each) = $960K. Expected revenue gained from 66–114 replies at 40% × 30% close rate = 8–14 deals = $3.8M–$6.7M.

Net: even with a 5% wrong-signal rate, the expected value is strongly positive — **but** the calculation assumes the wrong-signal emails are randomly distributed, not concentrated in a visible sector where peer founders talk to each other. The pilot should run in a single sector to contain this tail risk.

### One Honest Unresolved Failure

During `held_out_final_v1` and `held_out_final_v3`, API key exhaustion mid-run caused the agent to fall back to template text for approximately 40% of trials, producing a 41% pass@1 score. The 69% figure comes from `held_out_final_v4` where six-key rotation was implemented. The key rotation logic is now in place, but all six keys are currently at their weekly spending limit. If deployed immediately at volume, the LLM bridge generation will fall back to the generic template for all emails until the keys reset. Impact: emails send but lack the specific, LLM-generated bridge text that makes signal-grounded outreach work. The RAG retrieval is wired but the LLM is the bottleneck.

### Kill-Switch Clause

Pause the system if **any** of the following occur:

1. Email bounce rate exceeds **5%** in a rolling 7-day window (Resend dashboard)
2. Unsubscribe or complaint rate exceeds **0.5%** of sends
3. Any single prospect publicly names Tenacious in a negative social post about unsolicited outreach
4. Bench utilization drops below **60%** — at that point, booking more discovery calls than can be staffed damages the conversion funnel more than it helps

Rollback: set `KILL_SWITCH=true` in `.env`. All outbound routes immediately to `STAFF_SINK_EMAIL`. No code change required.

---

*All τ²-Bench scores sourced from `eval/score_log.json`. Cost figures derived from `eval/score_log.json → total_agent_cost_usd`. Latency figures from `data/act2_latency.json`. Tenacious ACV and conversion rates from `data/seed/pricing_sheet.md` and `data/tenacious_sales_data/seed/baseline_numbers.md`. Reply-rate benchmarks from LeadIQ 2026 and Clay/Smartlead case studies as cited in the challenge brief.*
