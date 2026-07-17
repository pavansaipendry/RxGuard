"""Drug-drug interaction validator.

Collects every drug mentioned across the conversation plus the assistant's
response, checks all pairs against the curated DDInter table (shared with
rxpilot), and appends a warning when a known interaction isn't already
addressed in the response.
"""

import csv
import re
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from app.guards.base import GuardResult, Verdict
from app.guards.extraction import DrugLexicon

# If the response already talks about the risk, don't warn twice.
_WARNING_MARKERS = re.compile(
    r"interact|bleed|avoid (?:tak|combin|us)|do not (?:take|combine|use)"
    r"|should not (?:take|be taken|combine)"
    r"|not recommended|serious risk|increases? the risk|talk to your (?:doctor|pharmacist) before"
    r"|check with your (?:doctor|pharmacist)|serotonin syndrome|toxicity",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Interaction:
    drug_a: str
    drug_b: str
    severity: str  # Major | Moderate | Minor
    description: str


class InteractionTable:
    def __init__(self, csv_path: str | Path):
        self.by_pair: dict[frozenset, Interaction] = {}
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                inter = Interaction(
                    drug_a=row["drug_a"].strip().lower(),
                    drug_b=row["drug_b"].strip().lower(),
                    severity=row["severity"].strip(),
                    description=row["description"].strip(),
                )
                self.by_pair[frozenset((inter.drug_a, inter.drug_b))] = inter

    def lookup(self, a: str, b: str) -> Interaction | None:
        return self.by_pair.get(frozenset((a.lower(), b.lower())))


def validate_interactions(
    conversation_text: str,
    response_text: str,
    lexicon: DrugLexicon,
    table: InteractionTable,
) -> GuardResult:
    drugs = lexicon.find_generics(conversation_text) | lexicon.find_generics(response_text)
    hits = []
    for a, b in combinations(sorted(drugs), 2):
        inter = table.lookup(a, b)
        if inter and inter.severity in ("Major", "Moderate"):
            hits.append(inter)

    if not hits:
        # No "cleared" flag: the curated table is not exhaustive, so an
        # LLM-judge interaction finding must NOT be overridden by this ALLOW.
        return GuardResult(
            guard="interaction_validator",
            verdict=Verdict.ALLOW,
            category="interaction",
            reason=f"no known interactions among {len(drugs)} drug(s) in scope",
            evidence={"drugs": sorted(drugs)},
        )

    already_warned = bool(_WARNING_MARKERS.search(response_text))
    if already_warned:
        return GuardResult(
            guard="interaction_validator",
            verdict=Verdict.ALLOW,
            category="interaction",
            reason=f"{len(hits)} known interaction(s) present but response already warns",
            evidence={
                "interactions": [f"{i.drug_a}+{i.drug_b} ({i.severity})" for i in hits],
                "cleared": True,
            },
        )

    warnings = [
        f"**{i.drug_a.title()} + {i.drug_b.title()} ({i.severity} interaction):** {i.description}"
        for i in hits
    ]
    return GuardResult(
        guard="interaction_validator",
        verdict=Verdict.MODIFY,
        category="interaction",
        reason=f"{len(hits)} known interaction(s) not addressed in response",
        warnings=warnings,
        evidence={"interactions": [f"{i.drug_a}+{i.drug_b} ({i.severity})" for i in hits]},
    )
