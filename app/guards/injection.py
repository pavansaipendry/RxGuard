"""Prompt injection detector — deterministic pattern layer.

Catches the well-known jailbreak grammar cheaply; the LLM input judge covers
novel phrasings. Patterns are scoped tightly to instruction-override and
policy-evasion language so ordinary pharmacy questions never trip them.
"""

import re

from app.guards.base import GuardResult, Verdict

_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:your\s+|the\s+|previous\s+|prior\s+|above\s+)*(?:instructions?|rules?|guidelines?|prompts?|training)\b", re.I),
    re.compile(r"\bdisregard\s+(?:your|the|all|previous|prior)\b", re.I),
    re.compile(r"\bforget\s+(?:your|all\s+your|everything\s+you)\s+(?:instructions?|rules?|training|were\s+told)\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\breveal\s+(?:your|the)\s+(?:instructions?|prompt|rules)\b", re.I),
    re.compile(r"\byou\s+are\s+(?:now|no\s+longer)\b", re.I),
    re.compile(r"\bpretend\s+(?:to\s+be|you(?:'re|\s+are))\b", re.I),
    re.compile(r"\b(?:act|roleplay)\s+as\s+(?:an?\s+)?(?:unrestricted|uncensored|unfiltered|jailbroken|different|evil)\b", re.I),
    re.compile(r"\b(?:developer|dan|god)\s+mode\b", re.I),
    re.compile(r"\bjailbreak\w*\b", re.I),
    re.compile(r"\bwithout\s+(?:any\s+)?(?:restrictions?|limitations?|filters?|safety|guardrails?)\b", re.I),
    re.compile(r"\bbypass\s+(?:your\s+|the\s+)?(?:safety|filters?|guardrails?|restrictions?|rules?)\b", re.I),
    re.compile(r"\bturn\s+off\s+(?:your\s+)?(?:safety|filters?|guardrails?)\b", re.I),
    re.compile(r"\bthis\s+is\s+(?:just\s+)?(?:a\s+)?(?:hypothetical|fiction(?:al)?|for\s+a\s+(?:story|novel|book|movie|script))\b.{0,80}\b(?:controlled|prescription|opioids?|narcotics?|oxycodone|fentanyl|adderall|xanax|benzos?)\b", re.I | re.S),
    # controlled-substance evasion
    re.compile(r"\b(?:get|obtain|buy|order|score)\b.{0,40}\b(?:controlled\s+substances?|opioids?|narcotics?|oxycodone|adderall|xanax|benzos?)\b.{0,40}\bwithout\s+(?:a\s+)?prescription\b", re.I | re.S),
    re.compile(r"\b(?:fake|forge|forging|counterfeit)\b.{0,30}\bprescriptions?\b", re.I | re.S),
    re.compile(r"\bconvince\s+(?:a\s+|my\s+)?(?:doctor|pharmacist)\s+to\s+(?:prescribe|give)\b", re.I),
]


def check_injection(user_message: str) -> GuardResult:
    for pattern in _PATTERNS:
        m = pattern.search(user_message)
        if m:
            return GuardResult(
                guard="injection_patterns",
                verdict=Verdict.BLOCK,
                category="injection",
                reason=f"matched injection pattern: {m.group(0)[:80]!r}",
                evidence={"match": m.group(0)[:120]},
            )
    return GuardResult(
        guard="injection_patterns",
        verdict=Verdict.ALLOW,
        category=None,
        reason="no injection pattern matched",
    )
