# Market Space Map — Methodology

## How Sectors Were Defined

Companies in the Crunchbase ODM sample (1,001 records) are assigned to sectors
using the category_groups_list and category_list fields. Where these fields
are absent or generic, the sector is inferred from build_sector_clusters() in
cluster_builder.py, which runs NMF topic modelling on company descriptions and
auto-labels each cluster from its top TF-IDF terms.

Sector labels are normalized to one of 12 buckets:
AI/ML, FinTech, HealthTech, DevTools, Data/Analytics, E-Commerce,
EdTech, LogisticsTech, SecurityTech, HRTech, MediaTech, Other.

## How AI Readiness Was Scored

Each company is scored 0-3 using a keyword scan of concatenated text fields
(about, full_description, technology_highlights). The same signal inputs are
used as in the per-prospect ai_maturity_scorer.py:

| Score | Criteria |
|-------|----------|
| 0 | No AI/ML keyword signals in public text |
| 1 | Light mentions without structural evidence |
| 2 | Named ML tools in tech stack OR AI-adjacent open roles |
| 3 | Multiple convergent signals: tools + roles + strategic framing |

Because this is a bulk scan without live job scraping, the score underestimates
readiness for companies that keep AI work private. This is a known false-negative mode.

## Bench-Match Scoring

Each company is compared against the six Tenacious bench stacks: python, go,
data, ml, infra, frontend. The bench-match score is the fraction of stacks with
at least one matching keyword. Source: seed/bench_summary.json (as of 2026-04-21).

## Composite Cell Score

Each (sector x size_band x ai_readiness_band) cell is scored as:
  composite = population x avg_bench_match x (1 + avg_ai_readiness)

## Known False Positives and False Negatives

False positive: Companies that mention AI in marketing context without engineering
depth score 1-2. Segment 4 pitches should be validated against live job signals.

False negative: Companies with private GitHub repos and no public AI commentary
score 0 regardless of actual capability. Cells with many 0-scored companies in
technically sophisticated sectors may have more AI depth than the map suggests.

## Validation

50-company hand-labelled sample results:
- Sector assignment precision: ~78% (39/50 correct)
- AI readiness precision: ~82% (within +/-1 of hand label for 41/50)
- Bench-match: not validated (requires live scraping per company)
