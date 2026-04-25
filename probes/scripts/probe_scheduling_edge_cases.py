"""
probe_scheduling_edge_cases.py — Probes 26-28: Scheduling Edge Cases.

1. SMS STOP/UNSUBSCRIBE detection — detect_sms_stop()
2. Timezone ambiguity detection — draft must specify timezone
3. has_explicit_timezone() helper validation

All assertions are deterministic — no LLM calls.
"""

from __future__ import annotations

import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mechanism.tone_preservation import check_tone


# ── SMS stop detection helper (inline, tested here) ──────────────────────────

_SMS_STOP_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bSTOP\b", re.I),
    re.compile(r"\bUNSUBSCRIBE\b", re.I),
    re.compile(r"\bOPT.?OUT\b", re.I),
    re.compile(r"\bCANCEL\b", re.I),
    re.compile(r"\bEND\b", re.I),
    re.compile(r"\bQUIT\b", re.I),
]


def detect_sms_stop(text: str) -> bool:
    """
    Return True if the SMS body contains a STOP / UNSUBSCRIBE signal.

    Per TCPA and GDPR: any of STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT
    must trigger immediate suppression.
    """
    stripped = text.strip()
    return any(p.search(stripped) for p in _SMS_STOP_PATTERNS)


# ── Timezone detection helper ─────────────────────────────────────────────────

_TZ_PATTERNS: list[re.Pattern] = [
    # Named zone abbreviations: UTC, EAT, EST, PST, CET, IST, etc.
    re.compile(r"\b(UTC|GMT|EAT|EST|EDT|CST|CDT|MST|MDT|PST|PDT|CET|CEST|IST|WAT|CAT)\b"),
    # UTC offset: +03:00, -07:00, +05:30
    re.compile(r"[+-]\d{2}:\d{2}"),
    # "Nairobi time", "Eastern time", "Pacific time", "East Africa Time"
    re.compile(r"\b(nairobi|eastern|pacific|central|mountain|london|lagos|addis)\s+time\b", re.I),
]


def has_explicit_timezone(time_str: str) -> bool:
    """
    Return True if the time string contains an explicit timezone reference.

    A bare "2pm" or "14:00" without a timezone is ambiguous and should return False.
    """
    return any(p.search(time_str) for p in _TZ_PATTERNS)


def run_probe() -> dict:
    failures: list[str] = []
    details: list[str] = []

    # ── Probe 26: detect_sms_stop() ───────────────────────────────────────────
    stop_cases: list[tuple[str, bool]] = [
        ("STOP", True),
        ("stop", True),
        ("UNSUBSCRIBE", True),
        ("Unsubscribe", True),
        ("stop please", True),
        ("Please STOP sending me messages", True),
        ("OPT-OUT", True),
        ("opt out", True),
        ("CANCEL", True),
        ("END", True),
        ("QUIT", True),
        ("Thanks, not interested right now.", False),
        ("Sure, let's set up a call.", False),
        ("Can you send more information?", False),
        ("I will stop by your office tomorrow.", False),  # "stop" as verb, not command
    ]

    for text, expected in stop_cases:
        result = detect_sms_stop(text)
        case_ok = result == expected
        details.append(
            f"Probe 26 SMS-STOP (expected={expected}): '{text}' → "
            f"detected={result} — {'PASS' if case_ok else 'FAIL'}"
        )
        if not case_ok:
            failures.append(
                f"Probe 26: detect_sms_stop('{text}') expected {expected}, got {result}"
            )

    # ── Probe 27: Timezone check in draft message ─────────────────────────────
    # A draft proposing a meeting time without a timezone should be flaggable.
    # We implement the check inline: if a time expression exists without a TZ → flag it.
    draft_no_tz = (
        "Hi,\n\n"
        "Would 2pm on Thursday work for a quick call to discuss next steps?\n\n"
        "Best, Tenacious"
    )
    # Detect bare time expression: e.g. "2pm", "14:00" without TZ
    bare_time_pattern = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", re.I)
    has_bare_time = bool(bare_time_pattern.search(draft_no_tz))
    has_tz = has_explicit_timezone(draft_no_tz)
    ambiguous_time = has_bare_time and not has_tz

    ok27 = ambiguous_time  # The probe passes if we correctly detect ambiguity
    details.append(
        f"Probe 27 (timezone ambiguity in draft): has_bare_time={has_bare_time}, "
        f"has_tz={has_tz}, ambiguous={ambiguous_time} — {'PASS' if ok27 else 'FAIL'}"
    )
    if not ok27:
        failures.append(
            f"Probe 27: '2pm on Thursday' without timezone should be flagged as ambiguous; "
            f"has_bare_time={has_bare_time}, has_tz={has_tz}"
        )

    # Verify that a draft WITH timezone is not flagged as ambiguous
    draft_with_tz = (
        "Hi,\n\n"
        "Would 2pm EAT (11am UTC) on Thursday work for a quick call?\n\n"
        "Best, Tenacious"
    )
    has_bare_time_tz = bool(bare_time_pattern.search(draft_with_tz))
    has_tz_explicit = has_explicit_timezone(draft_with_tz)
    ambiguous_with_tz = has_bare_time_tz and not has_tz_explicit

    ok27b = not ambiguous_with_tz
    details.append(
        f"Probe 27b (TZ present → not ambiguous): has_tz={has_tz_explicit}, "
        f"ambiguous={ambiguous_with_tz} — {'PASS' if ok27b else 'FAIL'}"
    )
    if not ok27b:
        failures.append(
            f"Probe 27b: '2pm EAT' should NOT be flagged as ambiguous; "
            f"has_tz={has_tz_explicit}"
        )

    # ── Probe 28: has_explicit_timezone() unit tests ──────────────────────────
    tz_cases: list[tuple[str, bool]] = [
        ("2pm EAT", True),
        ("14:00 UTC", True),
        ("11am GMT", True),
        ("9:00 EST", True),
        ("3pm +03:00", True),
        ("2pm Eastern time", True),
        ("10am Nairobi time", True),
        ("2pm", False),
        ("14:00", False),
        ("Thursday at 3", False),
        ("next Monday morning", False),
    ]

    for time_str, expected in tz_cases:
        result = has_explicit_timezone(time_str)
        case_ok = result == expected
        details.append(
            f"Probe 28 has_explicit_timezone (expected={expected}): "
            f"'{time_str}' → {result} — {'PASS' if case_ok else 'FAIL'}"
        )
        if not case_ok:
            failures.append(
                f"Probe 28: has_explicit_timezone('{time_str}') expected {expected}, got {result}"
            )

    passed = len(failures) == 0
    return {
        "probe_id": "scheduling_edge_cases",
        "passed": passed,
        "details": details,
        "failures": failures,
        "business_cost_label": (
            "Critical (GDPR STOP violation) / Medium (timezone miss causing missed call)"
        ),
    }


if __name__ == "__main__":
    import json
    result = run_probe()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
