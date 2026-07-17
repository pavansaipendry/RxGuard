"""Deterministic drug + dose extraction.

Drug NER is a curated-lexicon matcher (generic names + brand aliases), which is
fast, auditable, and has zero false positives outside the formulary we can
actually validate. A scispaCy backend can be swapped in behind the same
interface, but anything it finds outside the dosage KB couldn't be validated
anyway, so the lexicon is the honest default.

Dose parsing turns free text like "take 2 tablets of 500 mg twice daily" into a
normalized daily amount (2000 mg/day). Everything here is pure Python — no LLM.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Drug lexicon
# ---------------------------------------------------------------------------


@dataclass
class DrugMention:
    generic: str
    matched: str  # the surface form found in text
    start: int
    end: int


class DrugLexicon:
    def __init__(self, csv_path: str | Path):
        self.alias_to_generic: dict[str, str] = {}
        self.rxcui: dict[str, str] = {}
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                generic = row["generic"].strip().lower()
                self.rxcui[generic] = row.get("rxcui", "").strip()
                self.alias_to_generic[generic] = generic
                for alias in row["aliases"].split("|"):
                    alias = alias.strip().lower()
                    if alias:
                        self.alias_to_generic[alias] = generic
        # Longest aliases first so "naproxen sodium" wins over "naproxen".
        alternates = sorted(self.alias_to_generic, key=len, reverse=True)
        self._pattern = re.compile(
            r"\b(" + "|".join(re.escape(a) for a in alternates) + r")\b", re.IGNORECASE
        )

    def find(self, text: str) -> list[DrugMention]:
        """All drug mentions, deduplicated per position, mapped to generic names."""
        mentions = []
        for m in self._pattern.finditer(text):
            mentions.append(
                DrugMention(
                    generic=self.alias_to_generic[m.group(1).lower()],
                    matched=m.group(1),
                    start=m.start(),
                    end=m.end(),
                )
            )
        return mentions

    def find_generics(self, text: str) -> set[str]:
        return {m.generic for m in self.find(text)}


# ---------------------------------------------------------------------------
# Dose parsing
# ---------------------------------------------------------------------------

# Every amount is normalized to milligrams internally.
_UNIT_TO_MG = {
    "mg": 1.0,
    "milligram": 1.0,
    "milligrams": 1.0,
    "g": 1000.0,
    "gram": 1000.0,
    "grams": 1000.0,
    "mcg": 0.001,
    "microgram": 0.001,
    "micrograms": 0.001,
    "µg": 0.001,
    "ug": 0.001,
}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}

_NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
_UNITS = r"mg|milligrams?|mcg|micrograms?|µg|ug|g|grams?"

# "500 mg", "4,000mg", "0.5 g", "200 mcg", "500-mg"
_AMOUNT_RE = re.compile(rf"({_NUM})\s*(?:-\s*)?({_UNITS})\b", re.IGNORECASE)

# "two 500 mg tablets", "2 x 500mg". The separator (whitespace or an explicit
# "x") is mandatory so the "50" inside "500 mg" can never be read as a
# multiplier for the trailing "0 mg".
_MULTIPLIER_BEFORE_RE = re.compile(
    rf"\b(\d+|{'|'.join(_NUMBER_WORDS)})(?:\s*x\s*|\s+)(?=(?:{_NUM})\s*(?:{_UNITS})\b)",
    re.IGNORECASE,
)
_TABLETS_OF_RE = re.compile(
    rf"\b(\d+|{'|'.join(_NUMBER_WORDS)})\s+(?:tablets?|capsules?|caplets?|pills?)\s+"
    rf"(?:of\s+)?(?:\w+\s+)?(?=({_NUM})\s*(?:{_UNITS}))",
    re.IGNORECASE,
)

# Frequency phrases -> doses per day. Ranges use the WORST CASE (max frequency).
_FREQUENCY_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\bevery\s+3\s*(?:-|to)\s*4\s+hours?\b|\bq3-4h\b", re.I), 8),
    (re.compile(r"\bevery\s+3\s+hours?\b|\bq3h\b", re.I), 8),
    (re.compile(r"\bevery\s+4\s*(?:-|to)\s*6\s+hours?\b|\bq4-6h\b", re.I), 6),
    (re.compile(r"\bevery\s+4\s+hours?\b|\bq4h\b", re.I), 6),
    (re.compile(r"\bevery\s+6\s*(?:-|to)\s*8\s+hours?\b|\bq6-8h\b", re.I), 4),
    (re.compile(r"\bevery\s+6\s+hours?\b|\bq6h\b|\bfour\s+times\s+(?:a\s+|per\s+)?da(?:y|ily)\b|\bqid\b|\b4\s*(?:x|times)\s*(?:a\s+|per\s+)?day\b", re.I), 4),
    (re.compile(r"\bevery\s+8\s+hours?\b|\bq8h\b|\bthree\s+times\s+(?:a\s+|per\s+)?da(?:y|ily)\b|\btid\b|\b3\s*(?:x|times)\s*(?:a\s+|per\s+)?day\b", re.I), 3),
    (re.compile(r"\bevery\s+12\s+hours?\b|\bq12h\b|\btwice\s+(?:a\s+|per\s+)?da(?:y|ily)\b|\btwo\s+times\s+(?:a\s+|per\s+)?da(?:y|ily)\b|\bbid\b|\b2\s*(?:x|times)\s*(?:a\s+|per\s+)?day\b", re.I), 2),
    (re.compile(r"\bonce\s+(?:a\s+|per\s+)?da(?:y|ily)\b|\bonce\s+nightly\b|\bat\s+bedtime\b|\bnightly\b|\bevery\s+(?:day|night|morning|evening)\b|\bdaily\b|\bqd\b|\bper\s+day\b|\ba\s+day\b", re.I), 1),
]

# "do not exceed 4000 mg in 24 hours", "maximum of 3,000 mg per day", "up to 1200 mg daily"
_STATED_MAX_RE = re.compile(
    rf"(?:do\s+not\s+(?:take\s+more|exceed)|no\s+more\s+than|max(?:imum)?(?:\s+of)?|up\s+to|limit(?:\s+of)?)"
    rf"[^.;]{{0,40}}?({_NUM})\s*({_UNITS})\b"
    rf"[^.;]{{0,40}}?(?:per\s+day|a\s+day|daily|in\s+(?:a\s+)?24\s*(?:hours?|hrs?|h))",
    re.IGNORECASE,
)


@dataclass
class DoseStatement:
    drug: str | None  # generic name, if attributable
    dose_mg: float  # single-dose amount, mg
    times_per_day: float
    daily_mg: float
    is_stated_max: bool = False  # "do not exceed X per day" style statement
    frequency_found: bool = True
    raw: str = ""
    unit_in_text: str = "mg"


def _to_mg(amount_str: str, unit: str) -> float:
    amount = float(amount_str.replace(",", ""))
    return amount * _UNIT_TO_MG[unit.lower()]


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;\n])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _multiplier_for(sentence: str, amount_match: re.Match) -> float:
    """Look for '2 tablets of <amount>' or 'two <amount>' immediately before."""
    for pattern in (_TABLETS_OF_RE, _MULTIPLIER_BEFORE_RE):
        for m in pattern.finditer(sentence):
            if m.end() == amount_match.start():
                word = m.group(1).lower()
                return float(_NUMBER_WORDS.get(word, word if word.isdigit() else 1))
    return 1.0


def _attribute_drug(sentence: str, pos: int, mentions: list[DrugMention]) -> str | None:
    """Nearest drug mention before the dose in the sentence, else nearest after."""
    if not mentions:
        return None
    before = [m for m in mentions if m.start <= pos]
    if before:
        return before[-1].generic
    return mentions[0].generic


def extract_doses(text: str, lexicon: DrugLexicon) -> list[DoseStatement]:
    """Parse dose statements out of free text, sentence by sentence.

    Sentences with no explicit frequency assume once daily but are flagged
    (frequency_found=False) so the validator can stay conservative about them.
    """
    statements: list[DoseStatement] = []
    carry_drug: str | None = None  # last drug seen, for "Take 500 mg every..." follow-ups

    for sentence in split_sentences(text):
        mentions = lexicon.find(sentence)
        if mentions:
            carry_drug = mentions[-1].generic

        stated_max_spans = []
        for sm in _STATED_MAX_RE.finditer(sentence):
            # "up to 1800 mg three times daily" is a per-dose statement, not a
            # daily cap — leave it for the regular amount x frequency path.
            if re.search(r"\b(?:times|every)\b", sentence[sm.end(2):sm.end()], re.IGNORECASE):
                continue
            dose_mg = _to_mg(sm.group(1), sm.group(2))
            drug = _attribute_drug(sentence, sm.start(1), mentions) or carry_drug
            statements.append(
                DoseStatement(
                    drug=drug, dose_mg=dose_mg, times_per_day=1, daily_mg=dose_mg,
                    is_stated_max=True, raw=sm.group(0), unit_in_text=sm.group(2).lower(),
                )
            )
            stated_max_spans.append((sm.start(1), sm.end(2)))

        times_per_day, freq_found = 1.0, False
        for pattern, per_day in _FREQUENCY_PATTERNS:
            if pattern.search(sentence):
                times_per_day, freq_found = per_day, True
                break

        for am in _AMOUNT_RE.finditer(sentence):
            if any(s <= am.start() < e for s, e in stated_max_spans):
                continue  # already consumed as a stated daily max
            dose_mg = _to_mg(am.group(1), am.group(2)) * _multiplier_for(sentence, am)
            drug = _attribute_drug(sentence, am.start(), mentions) or carry_drug
            statements.append(
                DoseStatement(
                    drug=drug,
                    dose_mg=dose_mg,
                    times_per_day=times_per_day,
                    daily_mg=dose_mg * times_per_day,
                    frequency_found=freq_found,
                    raw=am.group(0),
                    unit_in_text=am.group(2).lower(),
                )
            )
    return statements
