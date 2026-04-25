# Market Space Map — Top Cells

Ranked by composite score: population x avg_bench_match x (1 + avg_ai_readiness).
Generated from market_map/market_space_scorer.py on Crunchbase ODM sample (1,001 companies).
Run: python -m market_map.market_space_scorer to regenerate.

---

## Cell 1 — AI/ML x Startup (1-80) x Developing AI (score 2)

Population: ~38 companies

Why this cell: Series A/B AI-native startups with active ML roles and modern
data stacks. Bench-match 0.6-0.8 (python + ml + data). Budget is fresh from
recent rounds; hiring velocity typically exceeds in-house recruiting capacity.

Outbound: Segment 1 pitch, high-AI-readiness language. Target VP Engineering or
Head of AI. Lead with job velocity signal if 5+ open engineering roles confirmed.
Bench stacks: Python (7 available), ML (5 available), Data (9 available).

---

## Cell 2 — DevTools x Growth (81-200) x Early AI (score 1)

Population: ~52 companies

Why this cell: Mid-sized developer tooling companies beginning to add AI features.
Not yet AI-native but have active platform and data engineering hiring.
Bench-match 0.5-0.7 (python + infra + frontend).

Outbound: Segment 1 if 5+ roles open. Segment 4 if 1-3 specialist AI roles.
Use embedded squad framing, not outsourcing framing. Reference the 3-5 hour overlap.

---

## Cell 3 — FinTech x Mid-Market (201-2,000) x Developing AI (score 2)

Population: ~31 companies

Why this cell: Late-stage FinTech with data science functions and active
restructuring signals. Several have layoff events in the last 120 days (Segment 2).
Bench-match 0.5-0.6 (python + data + infra).

Outbound: Segment 2 pitch. Lead with layoffs.fyi signal + 3+ open roles post-layoff.
Note: regulated jurisdiction clients require background checks (+7 days deploy).

---

## Cell 4 — HealthTech x Startup (1-80) x Early AI (score 1)

Population: ~29 companies

Why this cell: Early-stage digital health with Python/data stacks and nascent ML.
Lower bench-match (0.4-0.5); ML bench partially committed through Q3 2026.

Outbound: Segment 1 if recently funded, low-AI-readiness framing. Do not pitch
Segment 4 (AI score 1 is below gate). Check HIPAA flag before sending.
Capacity: do not commit more than 3 ML engineers without checking bench_summary.json.

---

## Cell 5 — Data/Analytics x Mid-Market (201-2,000) x Advanced AI (score 3)

Population: ~19 companies

Why this cell: Data platform companies with full ML stacks (Databricks, dbt,
Snowflake + inference). Highest bench-match (0.7-0.9). Segment 4 targets.

Outbound: Segment 4 only, project-based consulting. Lead with competitor gap brief:
identify 2-3 specific practices the top quartile is doing that they have not yet
implemented (dbt contracts, feature stores, model monitoring). Highest ACV per deal.
Personalized competitor gap brief required before first touch.
