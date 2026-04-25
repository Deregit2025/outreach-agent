# Target Failure Mode — Signal Over-Claiming

## Selection Rationale

Of the 8 failure categories in the probe library, **signal over-claiming** is selected
as the Act IV target based on a four-factor business-cost derivation:

---

## Factor 1: Frequency Across Prospect Pool

The Crunchbase ODM sample contains 1,001 companies. Signal quality analysis:

| Signal category        | High confidence | Medium confidence | Low/absent |
|------------------------|-----------------|-------------------|------------|
| Funding (180-day window) | ~18%           | ~12%              | ~70%       |
| Job velocity (scraped)  | ~25%            | ~15%              | ~60%       |
| Layoff (layoffs.fyi)    | ~8%             | —                 | ~92%       |
| Leadership change        | ~5%             | ~10%              | ~85%       |
| AI maturity ≥ 2         | ~15%            | ~20%              | ~65%       |

**Conclusion:** For roughly 60–70% of prospects, at least one primary signal is
medium or low confidence. The baseline agent asserts all signals regardless of
confidence. Over-claiming affects the **majority** of first-touch messages.

---

## Factor 2: Business Cost Per Incident

Using Tenacious baseline numbers from `seed/baseline_numbers.md`:

- Signal-grounded reply rate (top quartile): 7–12%
- Cold email reply rate (generic): 1–3%
- Discovery-call-to-proposal conversion: 30–50%
- Average talent outsourcing ACV: see `baseline_numbers.md`

A wrong-signal email does not just fail — it **actively reduces future receptivity**.
A prospect who receives an email citing a wrong funding amount, wrong hiring velocity,
or fabricated competitor comparison will:
1. Not reply (lost from 7–12% pool, falls to ~0%)
2. Mentally blacklist Tenacious (reduced receptivity for 6–12 months)
3. Potentially share the bad experience (social/LinkedIn: estimated 1–3 second-order
   prospects lost per incident in small tech communities)

**Per-incident cost estimate (illustrative):**
- Lost qualified prospect: ~$45K expected revenue (1% probability × $4.5M pipeline
  equivalent, using mid-range ACV and conversion rates from `baseline_numbers.md`)
- Blacklist effect (6-month horizon): additional ~0.5× of above
- Social amplification: negligible at current scale (<200 companies/week)

**Total per-incident cost: ~$60–70K in expected pipeline value.**

---

## Factor 3: Fixability with an Act IV Mechanism

The failure mode has a clean, testable mechanical fix:

1. Each `SignalItem` already has a `confidence` field (set at extraction time).
2. Adding a `language_register` field derived from confidence makes the fix
   structural, not dependent on prompt engineering.
3. The fix is provable in ablation: run Act I eval with and without the register
   transformation and measure over-claim rate on a labelled probe set.
4. The fix generalises: it improves all 6 signal types simultaneously.

Contrast with bench over-commitment (Category 3), which requires integration
with a live bench inventory system; or multi-thread leakage (Category 6), which
is an architecture concern rather than a content-generation concern.

---

## Factor 4: τ²-Bench Alignment

The τ²-Bench retail domain's primary failure mode is **dual-control coordination** —
the agent either fails to act when action is needed, or acts prematurely based on
incomplete information. Over-claiming maps directly to "acting prematurely on
incomplete information." Fixing it should yield a measurable τ²-Bench improvement,
making Delta A verifiable.

---

## Highest-ROI Verdict

**Signal over-claiming** satisfies:
- Affects majority of prospects (frequency: HIGH)
- Costs ~$60–70K per incident in expected pipeline (severity: HIGH)
- Has a clean, verifiable mechanical fix (fixability: HIGH)
- Maps directly to the benchmark's core failure mode (benchmark alignment: HIGH)

The runner-up, **ICP misclassification**, is addressed as a secondary component of
the Act IV mechanism (abstention) because the Probe 1 scenario (layoff+funding
conflict) is a specific case of the same root cause: the agent acts with more
certainty than the evidence supports.

---

## Deployed Mechanism

See `mechanism/method.md` for full implementation description.

Components implemented in Act IV:
- `mechanism/confidence_aware_phrasing.py` — primary fix
- `mechanism/icp_abstention.py` — secondary (conflicting signal detection)
- `mechanism/tone_preservation.py` — tertiary (prevents over-claiming language in final draft)
