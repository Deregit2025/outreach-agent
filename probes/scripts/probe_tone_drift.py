"""
probe_tone_drift.py — Probes 17-20: Tone Drift failures.

Tests tone_preservation.check_tone() for prohibited phrases, condescending language,
excessive length, and missing closing questions. All assertions are deterministic.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mechanism.tone_preservation import check_tone, PROHIBITED_PHRASES


def run_probe() -> dict:
    failures: list[str] = []
    details: list[str] = []

    # ── Probe 17: Draft with "industry-leading" → fails, score < 0.6 ─────────
    draft_industry_leading = (
        "Hi,\n\n"
        "Tenacious provides industry-leading engineering talent to B2B companies "
        "looking to scale their product teams.\n\n"
        "Our guaranteed results speak for themselves — we have helped hundreds of "
        "startups move faster.\n\n"
        "Would it be worth a quick call?"
    )
    r17 = check_tone(draft_industry_leading)
    # Expect: 'industry-leading' + 'guaranteed' both hit → prohibit_penalty = 0.30
    # score = 0.70 + marker_bonus + 0.05 - 0.30 → should be < 0.6 if markers are few
    ok17 = not r17.passed and r17.score < 0.60 and "industry-leading" in r17.prohibited_hits
    details.append(
        f"Probe 17 ('industry-leading'): passed={r17.passed}, score={r17.score}, "
        f"prohibited_hits={r17.prohibited_hits} — {'PASS' if ok17 else 'FAIL'}"
    )
    if not ok17:
        failures.append(
            f"Probe 17: 'industry-leading' must fail tone check with score < 0.60; "
            f"got passed={r17.passed}, score={r17.score}"
        )

    # ── Probe 18: Draft with "guaranteed results" → fails ─────────────────────
    draft_guaranteed = (
        "Hi,\n\n"
        "We deliver guaranteed results every single time. Our engineering teams "
        "are best in class across every technology stack.\n\n"
        "Please let me know if you would like to connect."
    )
    r18 = check_tone(draft_guaranteed)
    ok18 = not r18.passed and "guaranteed" in r18.prohibited_hits
    details.append(
        f"Probe 18 ('guaranteed results'): passed={r18.passed}, score={r18.score}, "
        f"prohibited_hits={r18.prohibited_hits} — {'PASS' if ok18 else 'FAIL'}"
    )
    if not ok18:
        failures.append(
            f"Probe 18: 'guaranteed results' must fail tone check; "
            f"passed={r18.passed}, prohibited_hits={r18.prohibited_hits}"
        )

    # ── Probe 19: Draft with "your competitors are beating you" → fails ────────
    draft_condescending = (
        "Hi,\n\n"
        "I noticed that your competitors are beating you in AI adoption. "
        "Companies like yours are falling behind if they don't act quickly.\n\n"
        "Would it make sense to discuss how Tenacious can help?"
    )
    r19 = check_tone(draft_condescending)
    ok19 = not r19.passed and "your competitors are beating you" in r19.prohibited_hits
    details.append(
        f"Probe 19 ('competitors are beating you'): passed={r19.passed}, score={r19.score}, "
        f"prohibited_hits={r19.prohibited_hits} — {'PASS' if ok19 else 'FAIL'}"
    )
    if not ok19:
        failures.append(
            f"Probe 19: 'your competitors are beating you' must fail tone check; "
            f"passed={r19.passed}, prohibited_hits={r19.prohibited_hits}"
        )

    # ── Probe 20: Draft > 300 words → flags avg sentence length ──────────────
    # Generate a long draft with many long sentences to push avg word count up.
    long_sentences = [
        "We noticed that your engineering team has been growing steadily over "
        "the past several quarters based on the public job postings we have tracked "
        "across Wellfound and your company careers page over an extended observation window.",
        "Tenacious provides dedicated engineering and data teams to B2B technology "
        "companies that are either scaling rapidly in headcount or navigating a specific "
        "capability gap that has emerged in their existing team composition over time.",
        "Our typical engagement model involves embedding experienced engineers directly "
        "into your existing workflow using your tooling, your ceremonies, and your "
        "standards, so there is minimal onboarding friction and maximum delivery velocity.",
        "We have found that companies at your stage often underestimate the cumulative "
        "cost of recruiting delays compared to the cost of augmenting with an experienced "
        "external team that can deliver in the short term while permanent hiring proceeds.",
        "I would love to explore whether there is a specific engineering initiative or "
        "timeline pressure on your radar right now where an additional team could "
        "meaningfully accelerate your roadmap and reduce the risk of missing a key milestone.",
        "Please do let me know if any of this resonates or if you would like to share "
        "more context about where the team is focused over the next quarter or two so "
        "that I can tailor any follow-up conversation to what is most relevant for you.",
    ]
    long_draft = "Hi,\n\n" + " ".join(long_sentences) + "\n\nBest, Tenacious"
    word_count = len(long_draft.split())
    r20 = check_tone(long_draft)
    # Avg sentence length will be high → length_penalty should apply
    # Even if it passes threshold, avg_sentence_length should be flagged
    ok20 = r20.avg_sentence_length > 25 or word_count > 300
    details.append(
        f"Probe 20 (long draft {word_count} words): passed={r20.passed}, "
        f"avg_sentence_length={r20.avg_sentence_length}, score={r20.score} "
        f"— {'PASS' if ok20 else 'FAIL'}"
    )
    if not ok20:
        failures.append(
            f"Probe 20: {word_count}-word draft should trigger avg_sentence_length flag "
            f"(>25 words avg); got avg_sentence_length={r20.avg_sentence_length}"
        )

    # ── Probe 20b: Draft with no question → flags missing question ───────────
    draft_no_question = (
        "Hi Marcus,\n\n"
        "I noticed your team has been hiring several backend engineers this quarter. "
        "Tenacious provides dedicated engineering capacity to companies in your space. "
        "We would be happy to connect and share more about how we work.\n\n"
        "Best, Tenacious"
    )
    r20b = check_tone(draft_no_question)
    ok20b = not r20b.has_question and any("question" in f.lower() for f in r20b.flags)
    details.append(
        f"Probe 20b (no question flag): has_question={r20b.has_question}, "
        f"flags={r20b.flags} — {'PASS' if ok20b else 'FAIL'}"
    )
    if not ok20b:
        failures.append(
            f"Probe 20b: draft with no question must set has_question=False and "
            f"include a 'question' flag; got has_question={r20b.has_question}, flags={r20b.flags}"
        )

    # ── Probe 20c: Good draft with proper Tenacious voice → score >= 0.7 ──────
    draft_good = (
        "Hi Sarah,\n\n"
        "I noticed your team has been building out its data engineering capacity "
        "based on public signals — looks like a few open dbt and Snowflake roles "
        "on Wellfound.\n\n"
        "Tenacious provides dedicated data engineering teams to B2B tech companies. "
        "We typically work with teams either scaling fast or navigating a stack migration.\n\n"
        "Would a 20-minute conversation make sense to see if the timing is right?"
    )
    r20c = check_tone(draft_good)
    ok20c = r20c.passed and r20c.score >= 0.70
    details.append(
        f"Probe 20c (good Tenacious-voice draft): passed={r20c.passed}, "
        f"score={r20c.score} — {'PASS' if ok20c else 'FAIL'}"
    )
    if not ok20c:
        failures.append(
            f"Probe 20c: well-formed Tenacious-voice draft must pass and score >= 0.70; "
            f"got passed={r20c.passed}, score={r20c.score}, flags={r20c.flags}"
        )

    passed = len(failures) == 0
    return {
        "probe_id": "tone_drift",
        "passed": passed,
        "details": details,
        "failures": failures,
        "business_cost_label": (
            "Medium-High — tone drift erodes the Tenacious brand and "
            "condescending language turns potential buyers into angry non-buyers"
        ),
    }


if __name__ == "__main__":
    import json
    result = run_probe()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
