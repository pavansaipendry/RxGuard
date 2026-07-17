"""Emergency detector — deterministic pattern layer.

High-precision patterns for unambiguous emergencies. When one fires, the
request never reaches the upstream LLM at all: detection, decision, and the
escalation message are all deterministic. The LLM input judge (guards/judge.py)
adds recall for indirect phrasings the patterns can't safely cover.

Precision matters as much as recall here: educational questions ("what are the
signs of a stroke?") must NOT fire, so symptom patterns require a first-person
or named-person context marker.
"""

import re

from app.guards.base import GuardResult, Verdict

# "I", "my chest", "my dad's face", "he's", "she is" — someone is describing a
# person actually experiencing this, not asking a textbook question.
_PERSON = r"(?:i|i'?m|i'?ve|my|me|we|he|he'?s|she|she'?s|his|her|our|dad|mom|father|mother|husband|wife|son|daughter|friend|grandma|grandpa)"

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # --- suicide / self-harm (crisis line escalation) ---
    ("suicide", re.compile(
        r"\b(?:kill(?:ing)?\s+myself|end(?:ing)?\s+my\s+life|take\s+my\s+(?:own\s+)?life"
        r"|suicidal?|su[i]cide|want(?:\s+it)?\s+to\s+die|wish\s+i\s+(?:was|were)\s+dead"
        r"|don'?t\s+want\s+to\s+(?:be\s+alive|live|wake\s+up)|hurt(?:ing)?\s+myself"
        r"|harm(?:ing)?\s+myself|no\s+reason\s+to\s+(?:live|go\s+on))\b"
        r"|\b(?:how\s+many|how\s+much|enough)\b.{0,50}\b(?:pills?|tablets?|mg)\b.{0,40}"
        r"\b(?:die|not\s+wake\s+up|kill\s+(?:me|myself|you|someone))\b", re.I)),
    # --- overdose / poisoning ---
    ("overdose", re.compile(
        rf"\b(?:overdos\w*|od'?d)\b"
        rf"|\b{_PERSON}\b.{{0,60}}\b(?:took|swallowed|ate)\b.{{0,40}}"
        rf"\b(?:whole\s+bottle|entire\s+bottle|handful\s+of|too\s+many|\d{{2,}}\s+(?:pills|tablets|capsules))\b", re.I)),
    # --- cardiac ---
    ("cardiac", re.compile(
        rf"\b{_PERSON}\b.{{0,60}}\b(?:chest\s+(?:pain|pressure|tightness|is\s+tight)"
        rf"|crushing\s+(?:pain|feeling|pressure)|heart\s+attack)\b"
        rf"|\bpain\s+(?:radiating|spreading|shooting)\s+(?:down|to|into)\s+"
        rf"(?:my|his|her|the)\s+(?:left\s+)?(?:arm|jaw|shoulder)\b", re.I)),
    # --- stroke ---
    ("stroke", re.compile(
        r"\b(?:face\s+(?:is\s+)?(?:droop\w*|uneven|sagging)|(?:droop\w*)\s+(?:face|smile)"
        r"|(?:face|smile)\s+(?:is\s+|looks?\s+|seems?\s+)?(?:droop\w*|uneven|sagging|lopsided)"
        r"|slurr\w*\s+(?:speech|words|talking)|speech\s+is\s+slurred"
        r"|can'?t\s+(?:move|feel|lift)\s+(?:my|his|her|one)\s+(?:left\s+|right\s+)?(?:arm|leg|side|face)"
        r"|(?:numb\w*|weak\w*)\s+on\s+one\s+side"
        r"|one\s+side\s+(?:of\s+[\w']+\s+(?:[\w']+\s+){0,2})?(?:body|face)\s+(?:is\s+)?(?:numb|weak|droop\w*)"
        r"|worst\s+headache\s+of\s+(?:my|his|her)\s+life|sudden(?:ly)?\s+(?:can'?t|cannot)\s+(?:see|speak|talk))\b", re.I)),
    # --- anaphylaxis / airway ---
    ("anaphylaxis", re.compile(
        rf"\banaphyla\w*\b"
        rf"|\b(?:throat|tongue|lips?|face)\s+(?:is\s+|are\s+)?(?:closing|swelling|swollen|tight)\b"
        rf"|\b{_PERSON}\b.{{0,60}}\b(?:can'?t\s+breathe|trouble\s+breathing|hard\s+to\s+breathe|struggling\s+to\s+breathe|gasping)\b"
        rf"|\bhives\b.{{0,60}}\b(?:breath\w*|swell\w*)", re.I)),
    # --- other severe ---
    ("severe", re.compile(
        r"\b(?:unconscious|unresponsive|not\s+breathing|stopped\s+breathing|turning\s+blue"
        r"|seizure\s+(?:right\s+now|won'?t\s+stop|for\s+\d+\s+minutes)|(?:having|has)\s+a\s+seizure"
        r"|bleeding\s+(?:won'?t\s+stop|heavily|a\s+lot|everywhere)|coughing\s+(?:up\s+)?blood"
        r"|vomiting\s+blood)\b", re.I)),
]

# Escalation category -> which fixed message to use (see responses.py).
CRISIS_CATEGORIES = {"suicide"}
POISON_CATEGORIES = {"overdose"}


def check_emergency(user_message: str) -> GuardResult:
    for category, pattern in _PATTERNS:
        m = pattern.search(user_message)
        if m:
            return GuardResult(
                guard="emergency_patterns",
                verdict=Verdict.ESCALATE,
                category=category,
                reason=f"matched emergency pattern: {m.group(0)[:80]!r}",
                evidence={"match": m.group(0)[:120]},
            )
    return GuardResult(
        guard="emergency_patterns",
        verdict=Verdict.ALLOW,
        category=None,
        reason="no emergency pattern matched",
    )
