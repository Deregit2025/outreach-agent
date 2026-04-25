# Act III — Failure Taxonomy

Probes grouped by category with business-cost weighting.

---

## Taxonomy Overview

| Category | Probes | Max Business Cost | Priority |
|---|---|---|---|
| Signal Over-Claiming | 7, 8, 9, 10, 11, 12 | Very High | **1 — Target** |
| ICP Misclassification | 1, 2, 3, 4, 5, 6 | Very High | 2 |
| Bench Over-Commitment | 13, 14, 15, 16 | Very High | 3 |
| Tone Drift | 17, 18, 19, 20 | High | 4 |
| Cost Pathology | 23, 24, 25 | Critical (23) / Medium | 5 |
| Multi-Thread Leakage | 21, 22 | Very High | 6 |
| Scheduling Edge Cases | 26, 27, 28 | Critical (27) / Medium | 7 |
| Signal Reliability | 29, 30 | Medium-High | 8 |

---

## Category 1: Signal Over-Claiming (Probes 7–12)

**Definition:** The agent asserts a claim about a prospect that is not supported by
the available signal at the claimed confidence level.

**Why it's the highest-ROI failure to address:**
1. It's immediately verifiable by the prospect. A wrong funding amount, a wrong
   hiring velocity claim, or an invented competitor comparison can be checked in
   seconds. The prospect's trust is gone before they finish reading.
2. It's systematic, not random. The baseline agent makes the same error for every
   prospect with weak signals because it has no confidence-register concept.
   Fixing it with the confidence-phrasing mechanism yields a proportional improvement
   across the entire prospect pool.
3. It's the Tenacious brand promise. The challenge spec explicitly frames the system
   as a "researcher" not a vendor pitcher. A system that over-claims is the opposite
   of that promise.
4. It directly maps to a τ²-Bench failure mode (signal grounding and dual-control)
   — fixing it improves benchmark score, not just brand metrics.

**Sub-categories:**
- **Velocity over-claiming** (Probe 7): < 5 engineering roles called "aggressive hiring"
- **Staleness over-claiming** (Probe 8): > 180-day event called "recent"
- **Inferred event asserting** (Probe 9): unconfirmed leadership change stated as fact
- **AI maturity inflation** (Probes 10, 29): single weak signal inflates score
- **Amount precision over-claiming** (Probe 11): range estimated, exact figure stated
- **Competitor gap fabrication** (Probe 12): < 3 data points used for sector comparison

---

## Category 2: ICP Misclassification (Probes 1–6)

**Definition:** The agent assigns a prospect to the wrong segment or fails to apply
a hard disqualifying filter, resulting in a tone-mismatched or strategically wrong pitch.

**Most dangerous pair:**
- Probe 1 (post-layoff → Segment 1 mismatch): sending a "scale fast" email to a
  company that just cut 25% of staff is actively offensive.
- Probe 4 (anti-offshore founder): contacting a founder who has publicly opposed
  outsourcing signals that the system didn't do basic research.

**Mitigation:** ICP abstention component (Act IV) with conflicting-signal penalty.

---

## Category 3: Bench Over-Commitment (Probes 13–16)

**Definition:** The agent commits to capacity, timing, or seniority level that the
`bench_summary.json` does not authorise.

**Why this is a policy violation, not just an error:**
The `bench_summary.json` explicitly states: "Committing to capacity the bench does
not show is a policy violation." Over-commitment is auditable via evidence graph.

**Most dangerous:** Probe 13 (zero-capacity stack promised). Contractual exposure.

---

## Category 4: Tone Drift (Probes 17–20)

**Definition:** The agent's language drifts from the Tenacious voice after multiple
turns or under certain inputs.

**Primary trigger:** Multi-turn conversation pressure. When a prospect pushes back,
the baseline agent sometimes shifts into defensive sales-speak that violates the
style guide (e.g., "guaranteed," "best in class").

**Mitigation:** Tone gate (Act IV) with prohibited-phrase detection.

---

## Category 5: Cost Pathology (Probes 23–25)

**Definition:** Prompts or interactions that cause runaway token usage, spam loops,
or security failures.

**Most dangerous:** Probe 23 (prompt injection). This is a security issue, not just
a performance issue, and must be treated as a hard constraint.

---

## Category 6: Multi-Thread Leakage (Probes 21–22)

**Definition:** State or context from one prospect's thread bleeds into another's.

**Architecture note:** The `ConversationState` is keyed by `prospect_id` (UUID),
not `company_name`. As long as state lookup always uses the UUID, leakage is
structurally prevented. The risk is in the email webhook handler which currently
scans all state files for a match — this should be replaced with an email-address
index lookup.

---

## Category 7: Scheduling Edge Cases (Probes 26–28)

**Definition:** Time zone confusion, regulatory compliance failure, or double-booking.

**Most dangerous:** Probe 27 (GDPR STOP signal). Non-compliance with unsubscribe
requests in the EU is a regulatory violation.

---

## Category 8: Signal Reliability (Probes 29–30)

**Definition:** False positives and negatives in the AI maturity scoring pipeline.

**False positive (Probe 29):** Public content that mentions AI without reflecting
genuine AI capability. Mitigation: require at least 2 independent signal types
for AI maturity ≥ 2.

**False negative (Probe 30):** Sophisticated AI team with no public signal. The
agent must explicitly document uncertainty rather than asserting low maturity.
Language: "We don't have strong public AI signals for [Company] — this could
reflect deliberate privacy rather than absence of capability."
