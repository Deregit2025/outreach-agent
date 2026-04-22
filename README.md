# Conversion Engine — Tenacious Consulting & Outsourcing

Automated B2B SDR system that finds, researches, and converts engineering-buyer prospects into booked discovery calls. Built on structured signal enrichment, honest outreach guardrails, and τ²-Bench evaluation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Conversion Engine                       │
│                                                             │
│  ┌──────────────┐    ┌───────────────┐    ┌─────────────┐  │
│  │  Enrichment  │───▶│  Agent Core   │───▶│  Channels   │  │
│  │  Pipeline    │    │               │    │             │  │
│  │              │    │  decision_    │    │  Email      │  │
│  │  Crunchbase  │    │  engine.py    │    │  (Resend)   │  │
│  │  Layoffs.fyi │    │               │    │             │  │
│  │  AI Maturity │    │  agent.py     │    │  SMS        │  │
│  │  ICP Segment │    │  (LiteLLM +   │    │  (Africa's  │  │
│  │  Competitor  │    │   Jinja2)     │    │   Talking)  │  │
│  │  Finder      │    │               │    │             │  │
│  └──────────────┘    │  Guardrails:  │    │  Calendar   │  │
│                      │  tone_checker │    │  (Cal.com)  │  │
│  ┌──────────────┐    │  bench_guard  │    │             │  │
│  │  Config      │    │  segment_gate │    │  CRM        │  │
│  │              │    │  signal_      │    │  (HubSpot)  │  │
│  │  kill_switch │    │  honesty      │    └─────────────┘  │
│  │  bench_summ  │    └───────────────┘                     │
│  │  settings    │                                           │
│  └──────────────┘    ┌───────────────┐    ┌─────────────┐  │
│                      │  Observability│    │  Eval       │  │
│  ┌──────────────┐    │               │    │             │  │
│  │  Server      │    │  tracer.py    │    │  harness.py │  │
│  │  (FastAPI)   │    │  (Langfuse)   │    │  stats.py   │  │
│  │              │    │  latency_     │    │  (τ²-Bench) │  │
│  │  /webhook/   │    │  tracker.py   │    │             │  │
│  │  email       │    │  cost_tracker │    │             │  │
│  │  sms         │    └───────────────┘    └─────────────┘  │
│  │  calendar    │                                           │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## ICP Segments

| # | Segment | Trigger | Pitch Angle |
|---|---------|---------|-------------|
| 1 | Recently-Funded Series A/B | Funding ≤ 180 days, ≤ 200 employees | Squad velocity before hiring ramp |
| 2 | Mid-Market Restructuring | Layoff event ≤ 12 months, 200–2000 employees | Delivery continuity without reversing cost savings |
| 3 | Leadership Transition | New CTO/VP Eng ≤ 90 days | Immediate capacity for 30/60/90-day plan |
| 4 | Capability Gap | AI maturity ≥ 2 + identifiable gap | Specialist bench, faster than hiring |

**Segment 0 = abstain** — no outreach sent; escalated to human SDR.

---

## Signal Language Registers

Every factual claim is gated by signal strength:

| Register | When | Example |
|----------|------|---------|
| `assert` | Strong, multi-source, recent | "You raised a $12M Series A in February." |
| `hedge`  | Single source or aging | "It looks like you may have recently closed a round." |
| `ask`    | Weak or unconfirmed | "Are you in an active growth phase?" |

The `signal_honesty` guardrail computes the register from thresholds — it cannot be overridden.

---

## Bench Availability (current)

| Specialty | Count |
|-----------|-------|
| Python engineers | 4 |
| ML / AI engineers | 2 |
| Go engineers | 1 |
| Data engineers (dbt) | 3 |
| Infrastructure / DevOps | 2 |

`bench_guard.py` blocks any draft that claims availability for a specialty at 0.

---

## Kill Switch

`KILL_SWITCH=true` (default) routes all outbound to the program staff sink. Set `KILL_SWITCH=false` only for live deployment with explicit Tenacious approval.

---

## Setup

### Prerequisites
- Python 3.13+
- uv (for τ²-Bench environment)

### Install

```bash
pip install -r requirements.txt
pip install -e tau2-bench   # installs tau2 into the main venv
```

### Environment

Copy `.env.example` to `.env` and fill in:

```
OPENROUTER_API_KEY=...
RESEND_API_KEY=...
RESEND_FROM_EMAIL=agent@yourfirm.dev
HUBSPOT_ACCESS_TOKEN=...
CALCOM_API_KEY=...
CALCOM_BOOKING_URL=https://cal.com/yourfirm/discovery
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
KILL_SWITCH=true
```

### Run the API server

```bash
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

### Run the τ²-Bench baseline

```bash
# Dev set (30 tasks, 5 trials each)
python eval/harness.py --mode dev --trials 5 --run-name dev_baseline_v1

# Smoke test (2 tasks, 1 trial)
python eval/harness.py --mode dev --max-tasks 2 --trials 1 --run-name smoke_test

# Use a specific model
python eval/harness.py --agent-model openrouter/google/gemma-3-12b-it:free
```

Results are written to:
- `eval/score_log.json` — one entry per run
- `eval/trace_log.jsonl` — one line per simulation

---

## Project Structure

```
conversion-agent/
├── agent/
│   ├── agent.py              # Main SDR orchestrator
│   ├── bench_guard.py        # Capacity commitment detector
│   ├── decision_engine.py    # Deterministic action selector
│   ├── state.py              # ConversationState Pydantic model
│   ├── guardrails/
│   │   ├── signal_honesty.py # Assert/hedge/ask register logic
│   │   ├── segment_gate.py   # ICP segment validation
│   │   └── tone_checker.py   # Prohibited phrases + over-claim detection
│   └── prompts/
│       ├── system_prompt.txt
│       ├── outreach_email.jinja2
│       ├── qualification.jinja2
│       ├── booking.jinja2
│       └── sms_warm.jinja2
├── channels/
│   ├── email_handler.py      # Resend API
│   ├── sms_handler.py        # Africa's Talking API
│   ├── calendar_handler.py   # Cal.com v1 API
│   ├── crm_handler.py        # HubSpot direct API
│   └── channel_router.py     # Stage → channel dispatcher
├── config/
│   ├── settings.py           # Pydantic BaseSettings
│   ├── kill_switch.py        # Route all outbound to sink
│   └── bench_summary.py      # Bench availability loader
├── enrichment/
│   ├── crunchbase_lookup.py  # CSV singleton + parsers
│   ├── layoffs_lookup.py     # Layoffs.fyi CSV lookup
│   ├── ai_maturity_scorer.py # Pure-function scorer 0–3
│   ├── icp_classifier.py     # Segment 1–4 classification
│   ├── competitor_finder.py  # Sector peer comparison
│   ├── pipeline.py           # enrich_prospect() entrypoint
│   └── schemas/
│       ├── prospect.py
│       ├── hiring_signal_brief.py
│       └── competitor_gap_brief.py
├── server/
│   ├── main.py               # FastAPI app
│   ├── webhooks.py           # /webhook/email, /sms, /calendar
│   ├── routes.py             # /api/health, /states
│   └── middleware.py         # CORS + request logging
├── observability/
│   ├── tracer.py             # Langfuse v2 wrapper
│   ├── latency_tracker.py    # p50/p95 duration tracking
│   └── cost_tracker.py       # Budget cap enforcement
├── eval/
│   ├── harness.py            # τ²-Bench runner
│   ├── stats.py              # Wilson CI, pass@k
│   ├── score_log.json        # Run results
│   └── trace_log.jsonl       # Per-simulation traces
├── data/
│   ├── raw/                  # Crunchbase CSV, layoffs.fyi CSV
│   ├── seed/                 # ICP definition, style guide, bench, pricing, templates
│   ├── synthetic/            # 8 synthetic test prospects
│   └── processed/            # Enrichment outputs + conversation states
└── tau2-bench/               # τ²-Bench submodule (retail domain)
```

---

## Evaluation (τ²-Bench)

The harness runs the retail domain tasks from τ²-Bench against your configured agent model. It reports:

- **pass@1**: fraction of tasks solved on the first trial
- **95% Wilson CI**: confidence interval around pass@1
- **p50/p95 latency**: agent response time
- **cost/task**: total LLM spend divided by tasks run

Scores are appended to `eval/score_log.json` with a timestamp, making it safe to run multiple evaluations without overwriting prior results.

---

## Honesty Constraints

- Never fabricate prospect data — only reference fields provided in the enrichment brief.
- Never claim bench availability for a specialty at 0.
- Never upgrade a signal's register beyond what `signal_honesty` computes.
- Never send to a real prospect when `KILL_SWITCH=true`.
- Never send cold SMS — SMS only after email reply + SMS preference confirmed.
