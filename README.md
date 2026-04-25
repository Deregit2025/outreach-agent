# Conversion Engine — Tenacious Consulting & Outsourcing

Automated B2B outbound system that finds, enriches, and converts engineering-buyer prospects into booked discovery calls. Built on structured signal enrichment, multi-turn conversational evaluation (τ²-Bench 69% pass@1), and honest outreach guardrails.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Conversion Engine                                │
│                                                                             │
│  ┌──────────────────┐   enrich_prospect()   ┌──────────────────────────┐   │
│  │  Enrichment      │──────────────────────▶│  Agent Core              │   │
│  │  Pipeline        │                       │                          │   │
│  │                  │   HiringSignalBrief    │  decision_engine.py      │   │
│  │  crunchbase_     │   CompetitorGapBrief   │  → SEND_COLD_EMAIL       │   │
│  │  lookup.py       │                       │  → QUALIFY               │   │
│  │  layoffs_        │                       │  → SEND_BOOKING_LINK     │   │
│  │  lookup.py       │                       │  → ESCALATE              │   │
│  │  ai_maturity_    │                       │                          │   │
│  │  scorer.py       │                       │  agent.py                │   │
│  │  icp_classifier  │                       │  (LiteLLM + Jinja2       │   │
│  │  competitor_     │                       │   + RAG via ChromaDB)    │   │
│  │  finder.py       │                       │                          │   │
│  │  seed_rag.py     │                       │  Guardrails:             │   │
│  └──────────────────┘                       │  signal_honesty.py       │   │
│                                             │  bench_guard.py          │   │
│  ┌──────────────────┐                       │  tone_checker.py         │   │
│  │  Config          │                       │  segment_gate.py         │   │
│  │                  │                       └──────────┬───────────────┘   │
│  │  kill_switch.py  │                                  │ send_message()     │
│  │  bench_summary   │                                  ▼                   │
│  │  settings.py     │          ┌────────────────────────────────────────┐  │
│  └──────────────────┘          │  ChannelRouter  (state machine)        │  │
│                                │                                        │  │
│  ┌──────────────────┐          │  Email  ──▶  Resend API                │  │
│  │  FastAPI Server  │          │  SMS    ──▶  Africa's Talking API      │  │
│  │                  │◀─webhook─│  Calendar ▶  Cal.com v1 API           │  │
│  │  /webhook/email  │          │  CRM    ──▶  HubSpot REST v3           │  │
│  │  /webhook/sms    │          └────────────────────────────────────────┘  │
│  │  /webhook/cal    │                                                       │
│  └──────────────────┘  ┌─────────────────┐  ┌────────────────────────┐    │
│                         │  Observability  │  │  Evaluation            │    │
│                         │  tracer.py      │  │  harness.py (τ²-Bench) │    │
│                         │  latency_tracker│  │  stats.py (Wilson CI)  │    │
│                         │  cost_tracker   │  │  score_log.json        │    │
│                         └─────────────────┘  └────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Prospect identified  ──▶  enrich_prospect()  ──▶  Prospect + HiringSignalBrief + CompetitorGapBrief
2. Brief passed to agent  ──▶  decision_engine selects action
3. action == SEND_COLD_EMAIL  ──▶  LLM generates email  ──▶  4 guardrails check  ──▶  ChannelRouter.send_message()
4. ChannelRouter consults STAGE_CHANNEL_MAP  ──▶  EmailHandler.send()  ──▶  Resend API
5. Prospect replies  ──▶  /webhook/email  ──▶  ChannelRouter.handle_reply()  ──▶  agent turn 2
6. Stage transitions to warm_prefers_sms  ──▶  SMS gate enforced  ──▶  SMSHandler.send()
7. Stage reaches qualified  ──▶  booking link generated  ──▶  email + SMS delivery
8. Prospect books  ──▶  /webhook/cal  ──▶  CRM updated  ──▶  stage = booked
```

---

## ICP Segments

| # | Segment | Trigger | Pitch Angle |
|---|---------|---------|-------------|
| 1 | Recently-Funded Series A/B | Funding ≤ 180 days, 15–200 employees | Squad velocity before hiring ramp |
| 2 | Mid-Market Restructuring | Layoff event ≤ 12 months, 200–2,000 employees | Delivery continuity without reversing cost savings |
| 3 | Leadership Transition | New CTO/VP Eng ≤ 90 days | Immediate capacity for 30/60/90-day plan |
| 4 | Capability Gap | AI maturity ≥ 2 + identifiable sector gap | Specialist bench, faster than hiring |

**Segment 0 = abstain** — no outreach sent; escalated to human SDR.

---

## Signal Language Registers

Every factual claim is gated by signal strength before sending:

| Register | When | Example |
|----------|------|---------|
| `assert` | High-confidence, multi-source, ≤ 90 days old | "You raised a $12M Series A in February." |
| `hedge`  | Single source, 90–180 days old | "It looks like you may have recently closed a round." |
| `ask`    | Weak, unconfirmed, or > 180 days old | "Are you in an active growth phase?" |

The `signal_honesty` guardrail computes the register from data age + source count. The LLM cannot override it.

---

## Channel State Machine

```
new  ──email──▶  replied_by_email  ──email──▶  qualified  ──email──▶  booked
                       │                           │
               (SMS opt-in confirmed)      (booking link also
                       │                    sent via SMS if
                       ▼                    warm_prefers_sms)
               warm_prefers_sms  ──sms──▶  booked
```

**Warm-lead SMS gate:** SMS is only sent after the prospect has replied to email AND explicitly confirmed SMS preference (keyword: "text me", "WhatsApp", phone number provided). Cold SMS is prohibited. The `ChannelRouter` enforces this via `transition_state()` — transitioning to `warm_prefers_sms` requires `sms_opt_in=True`.

---

## Bench Availability (current snapshot)

| Specialty | Count |
|-----------|-------|
| Python engineers | 4 |
| ML / AI engineers | 2 |
| Go engineers | 1 |
| Data engineers (dbt) | 3 |
| Infrastructure / DevOps | 2 |

Source: `data/seed/bench_summary.md`. `bench_guard.py` blocks any draft claiming availability for a specialty at 0.

---

## Kill Switch

`KILL_SWITCH=true` (default) routes all outbound to the program staff sink. **No real prospect receives email or SMS while this is true.** Set `KILL_SWITCH=false` only after explicit Tenacious executive approval.

---

## Setup

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.13+ | Tested on 3.13.2 |
| pip | 26+ | Bundled with Python 3.13 |
| Playwright Chromium | latest | Required for job scraping |
| Git | any | For submodule (tau2-bench) |

### Installation

```bash
# 1. Clone the repo (includes tau2-bench submodule)
git clone <repo-url>
cd conversion-agent

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install tau2-bench into the same venv
pip install -e tau2-bench

# 4. Install Playwright browser (one-time)
playwright install chromium

# 5. Build the RAG index (one-time, ~30s)
python -c "from enrichment.seed_rag import init_rag; init_rag()"
```

### Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
# ── LLM / OpenRouter ─────────────────────────────────────────────────────────
OPENROUTER_API_KEY=sk-or-...          # Primary key (required)
OPENROUTER_API_KEYS=sk-or-a,...,f    # Comma-separated rotation list (6 keys recommended)
OPENROUTER_MODEL=anthropic/claude-sonnet-4-6  # Default model

# ── Email: Resend ─────────────────────────────────────────────────────────────
RESEND_API_KEY=re_...                 # Resend API key
RESEND_FROM_EMAIL=agent@yourfirm.dev # Verified sender domain

# ── SMS: Africa's Talking ─────────────────────────────────────────────────────
AT_API_KEY=...                        # Africa's Talking API key
AT_USERNAME=sandbox                   # Use "sandbox" for testing
AT_SHORT_CODE=20880                   # Registered shortcode or sender ID

# ── Calendar: Cal.com ────────────────────────────────────────────────────────
CALCOM_API_KEY=cal_live_...           # Cal.com API key
CALCOM_BASE_URL=https://cal.com       # Or self-hosted URL
CALCOM_EVENT_TYPE_ID=123456           # Discovery call event type ID
CALCOM_BOOKING_URL=https://cal.com/yourfirm/discovery  # Public booking link

# ── CRM: HubSpot ─────────────────────────────────────────────────────────────
HUBSPOT_ACCESS_TOKEN=pat-na1-...     # HubSpot private app token

# ── Observability: Langfuse ──────────────────────────────────────────────────
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# ── Kill Switch ───────────────────────────────────────────────────────────────
KILL_SWITCH=true                      # MUST be true until Tenacious approves live deployment
STAFF_SINK_EMAIL=yourname@yourorg.com # All outbound routes here when kill switch is ON
STAFF_SINK_PHONE=+1555000000          # All SMS routes here when kill switch is ON
```

### Run Order

Run these in order on first setup:

```bash
# Step 1 — Verify enrichment pipeline works
python scripts/run_real_enrichment.py

# Step 2 — Run Act II demo (8 synthetic prospects + full thread)
python scripts/run_act2_demo.py

# Step 3 — Start the API server (handles inbound webhooks)
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000

# Step 4 — Run τ²-Bench smoke test (2 tasks, sanity check)
python eval/harness.py --mode dev --max-tasks 2 --trials 1 --run-name smoke_test

# Step 5 — Run full held-out evaluation (20 tasks × 5 trials, ~90 min)
python eval/harness.py --mode held_out --trials 5 --run-name held_out_final_v4
```

---

## Directory Index

| Folder / File | Purpose |
|---|---|
| `agent/` | SDR orchestrator — decision engine, prompts, guardrails |
| `agent/agent.py` | Main entry point: `run(prospect, brief, comp_brief, state, router)` |
| `agent/decision_engine.py` | Deterministic action selector (SEND_COLD_EMAIL / QUALIFY / SEND_BOOKING_LINK / ESCALATE) |
| `agent/state.py` | `ConversationState` Pydantic model — tracks stage, turn count, opt-ins |
| `agent/bench_guard.py` | Blocks drafts that over-commit bench capacity |
| `agent/guardrails/signal_honesty.py` | Computes assert/hedge/ask register; cannot be overridden |
| `agent/guardrails/segment_gate.py` | Blocks outreach to abstained or disqualified segments |
| `agent/guardrails/tone_checker.py` | Prohibited phrases + over-claim detection |
| `agent/prompts/` | Jinja2 templates for cold email, qualification, booking, SMS |
| `channels/` | All outbound/inbound channel handlers |
| `channels/channel_router.py` | State machine + unified send/receive interface |
| `channels/email_handler.py` | Resend API — send + inbound webhook parsing |
| `channels/sms_handler.py` | Africa's Talking — send + inbound webhook parsing |
| `channels/calendar_handler.py` | Cal.com v1 — slots, booking creation, webhook parsing |
| `channels/crm_handler.py` | HubSpot REST v3 — contact upsert, notes, deals, email activity |
| `config/` | Settings, kill switch, bench summary loader |
| `config/settings.py` | Pydantic BaseSettings — all env vars with defaults |
| `config/kill_switch.py` | `route_email()` / `route_phone()` — redirects when KILL_SWITCH=true |
| `config/bench_summary.py` | Loads `data/seed/bench_summary.md` as structured dict |
| `enrichment/` | Signal extraction and prospect classification |
| `enrichment/pipeline.py` | `enrich_prospect()` — main entrypoint; returns Prospect + briefs |
| `enrichment/crunchbase_lookup.py` | CSV singleton + parsers for funding, leadership, tech, employees |
| `enrichment/layoffs_lookup.py` | layoffs.fyi CSV lookup by company name |
| `enrichment/ai_maturity_scorer.py` | Scores 0–3 using TF-IDF + NMF + keyword + leadership signals |
| `enrichment/icp_classifier.py` | Assigns Segment 1–4 (or 0 = abstain) from brief signals |
| `enrichment/competitor_finder.py` | Finds sector peers; builds `CompetitorGapBrief` |
| `enrichment/seed_rag.py` | ChromaDB + sentence-transformers RAG over 14 Tenacious seed docs |
| `enrichment/tfidf_extractor.py` | TF-IDF feature extraction over 1,000-company corpus |
| `enrichment/topic_modeler.py` | 8-topic NMF topic modeling |
| `enrichment/schemas/` | Pydantic models: Prospect, HiringSignalBrief, CompetitorGapBrief |
| `eval/` | τ²-Bench evaluation harness |
| `eval/harness.py` | Runs τ²-Bench simulations; writes score_log.json + trace files |
| `eval/stats.py` | Wilson CI, pass@k, p50/p95 latency |
| `eval/score_log.json` | Appended on each run; holds all evaluation results |
| `eval/held_out_traces.jsonl` | Per-turn traces for the held-out final evaluation |
| `eval/ablation_results.json` | Component ablation: score per guardrail enabled/disabled |
| `data/raw/` | Crunchbase ODM CSV (1,000 rows), layoffs.fyi CSV |
| `data/seed/` | ICP definition, style guide, bench summary, pricing sheet, email templates |
| `data/synthetic/` | 8 pre-built synthetic prospect profiles for Act II demo |
| `data/processed/` | Enrichment outputs: hiring_signal_briefs/, competitor_gap_briefs/ |
| `data/tenacious_sales_data/` | Baseline numbers, policy, schemas (challenge-provided) |
| `docs/` | Notes, final report chapters |
| `docs/final_report/` | 7-chapter report as .md files; `report.pdf` generated by script |
| `memo/` | Act V decision memo sources: evidence_graph.json, evidence_validator.py |
| `memo.md` | 2-page executive decision memo (final version) |
| `observability/` | Langfuse tracer, latency tracker, cost tracker |
| `probes/` | Adversarial probe library, failure taxonomy, target failure mode |
| `scraper/` | Playwright job scraper for Wellfound, BuiltIn, and careers pages |
| `scripts/` | Runnable demo scripts and PDF report generator |
| `scripts/run_act2_demo.py` | Full pipeline demo on 8 synthetic prospects |
| `scripts/run_real_enrichment.py` | Live Playwright scrape + agent run on Airbyte |
| `scripts/generate_pdf_report.py` | Renders docs/final_report/*.md → docs/final_report/report.pdf |
| `server/` | FastAPI app — webhook endpoints for email, SMS, calendar replies |
| `tau2-bench/` | τ²-Bench submodule (retail domain evaluation framework) |

---

## Known Limitations and Next Steps

### Current Limitations

| Limitation | Impact | Fix Sprint |
|---|---|---|
| Crunchbase ODM is a 1,000-row sample | ~15% of Segment 1 prospects not found; AI maturity defaults to 0 | Sprint 2: full Crunchbase API or expanded CSV |
| AI maturity scorer is text-only | Silent companies (private GitHub, no public blog) score 0 even with sophisticated ML | Sprint 2: wire job-post content into scorer |
| RAG index has only 14 seed docs | LLM bridge text may not match prospect's specific sub-niche | Sprint 2: add 50+ Tenacious case studies |
| Six API keys all at weekly spending limit | LLM bridge falls back to template on all sends until keys reset | Before launch: add paid credits |
| No cross-thread deduplication | Same company can receive two emails if two contacts are in separate prospect pools | Sprint 2: company-level contact lock |
| Wellfound blocks scraper via robots.txt | Job velocity signal missing for many prospects | Sprint 3: alternative job-board integration |
| Cal.com booking link not embedded in SMS | SMS only says "reply YES to book" instead of a direct link | Sprint 1 (see below) |

### Immediate Next Steps Before Live Deployment

1. **Add API credits** to at least one OpenRouter key ($5 covers the 4-week pilot at $0.02/touch)
2. **Fix guardrail bypass**: `agent.py:_generate_cold_email()` should raise on LLM failure, not fall back silently to template
3. **Set `KILL_SWITCH=false`** after executive sign-off — no other change required to go live
4. **Verify Resend domain** is validated in the Resend dashboard before sending from `agent@yourfirm.dev`
5. **Register Cal.com event type** and set `CALCOM_EVENT_TYPE_ID` to the discovery call type ID

### A New Engineer Running This for the First Time

If you are onboarding to this codebase:

1. Read `data/seed/icp_definition.md` to understand the 4 ICP segments
2. Read `data/seed/bench_summary.md` to understand what the agent can and cannot promise
3. Run `python scripts/run_real_enrichment.py` — this shows the full enrichment pipeline with live web scraping
4. Run `python eval/harness.py --mode dev --max-tasks 2 --trials 1 --run-name onboard_test` — this validates τ²-Bench is wired
5. Check `eval/score_log.json` for your test results
6. The kill switch is `KILL_SWITCH=true` by default — you cannot accidentally email a real prospect
