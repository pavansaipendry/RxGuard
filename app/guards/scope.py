"""Scope check — deterministic pattern layer.

A pharmacy information assistant must not diagnose or prescribe. Patterns
catch direct asks; the LLM input judge handles oblique ones. Educational
questions ("what is strep throat?") must pass, so patterns anchor on the user
asking for a personal diagnosis or a prescription, not on disease words.
"""

import re

from app.guards.base import GuardResult, Verdict

_PATTERNS: list[re.Pattern] = [
    # personal diagnosis requests
    re.compile(r"\b(?:diagnose|diagnosis\s+for)\s+(?:me|my|him|her)\b", re.I),
    re.compile(r"\bwhat\s+(?:disease|condition|illness)\s+do\s+i\s+have\b", re.I),
    re.compile(r"\bdo\s+i\s+have\s+(?:cancer|diabetes|covid|strep|an?\s+infection|a\s+tumou?r|lupus|lyme)\b", re.I),
    re.compile(r"\b(?:is\s+this|could\s+this\s+be)\s+(?:cancer|a\s+tumou?r|diabetes|a\s+stroke|an?\s+infection)\b", re.I),
    re.compile(r"\btell\s+me\s+what(?:'s|\s+is)\s+wrong\s+with\s+me\b", re.I),
    # prescription requests
    re.compile(r"\b(?:prescribe|write)\s+(?:me\s+)?(?:a\s+)?(?:prescription|script|rx)\b", re.I),
    re.compile(r"\bprescribe\s+me\b", re.I),
    re.compile(r"\bgive\s+me\s+a\s+prescription\b", re.I),
    re.compile(r"\bcan\s+(?:you|i\s+get)\s+(?:a\s+)?(?:prescription|antibiotics?|amoxicillin|opioids?)\s+(?:from\s+you|without\s+seeing)\b", re.I),
    re.compile(r"\bwhich\s+antibiotic\s+should\s+i\s+take\s+for\b", re.I),
]


def check_scope(user_message: str) -> GuardResult:
    for pattern in _PATTERNS:
        m = pattern.search(user_message)
        if m:
            return GuardResult(
                guard="scope_patterns",
                verdict=Verdict.BLOCK,
                category="scope",
                reason=f"matched out-of-scope pattern: {m.group(0)[:80]!r}",
                evidence={"match": m.group(0)[:120]},
            )
    return GuardResult(
        guard="scope_patterns",
        verdict=Verdict.ALLOW,
        category=None,
        reason="no out-of-scope pattern matched",
    )
