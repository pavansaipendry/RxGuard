"""Dosage range validator.

Runtime validation is a table lookup against a knowledge base built OFFLINE
(scripts/build_dosage_kb.py uses an LLM to structure openFDA label text once;
the checked-in CSV is the audited artifact). Nothing here calls an LLM.

Policy: daily dose above the adult maximum -> MODIFY (append a correction with
the label maximum); at or above 2x the maximum -> BLOCK (egregious).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from app.guards.base import GuardResult, Verdict
from app.guards.extraction import DoseStatement

EGREGIOUS_MULTIPLIER = 2.0


@dataclass
class KBEntry:
    drug: str
    rxcui: str
    route: str
    adult_max_daily: float
    unit: str  # "mg" or "mcg" — the unit the max is expressed in
    notes: str


class DosageKB:
    def __init__(self, csv_path: str | Path):
        self.entries: dict[str, KBEntry] = {}
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                self.entries[row["drug"].strip().lower()] = KBEntry(
                    drug=row["drug"].strip().lower(),
                    rxcui=row["rxcui"].strip(),
                    route=row["route"].strip(),
                    adult_max_daily=float(row["adult_max_daily"]),
                    unit=row["unit"].strip().lower(),
                    notes=row["notes"].strip(),
                )

    def get(self, drug: str) -> KBEntry | None:
        return self.entries.get(drug.lower())


def _daily_in_kb_unit(stmt: DoseStatement, entry: KBEntry) -> float:
    # DoseStatement daily amounts are normalized to mg internally.
    return stmt.daily_mg * 1000.0 if entry.unit == "mcg" else stmt.daily_mg


def validate_dosages(statements: list[DoseStatement], kb: DosageKB) -> GuardResult:
    """Check every attributable dose statement against the KB."""
    violations, validated = [], set()
    for stmt in statements:
        if not stmt.drug:
            continue
        entry = kb.get(stmt.drug)
        if entry is None:
            continue
        daily = _daily_in_kb_unit(stmt, entry)
        validated.add(stmt.drug)
        if daily > entry.adult_max_daily:
            violations.append((stmt, entry, daily))

    if not violations:
        # "cleared" tells the decision engine this category was affirmatively
        # evaluated, so an LLM-judge dosage finding can be overridden. If no
        # dose was parseable at all, we did NOT clear anything — a judge
        # flagging "take the whole bottle" must survive.
        return GuardResult(
            guard="dosage_validator",
            verdict=Verdict.ALLOW,
            category="dosage",
            reason=f"validated {len(validated)} drug(s), all within label maximums"
            if validated
            else "no attributable doses found",
            evidence={"validated_drugs": sorted(validated), "cleared": bool(validated)},
        )

    worst_ratio = max(d / e.adult_max_daily for _, e, d in violations)
    warnings = []
    for stmt, entry, daily in violations:
        warnings.append(
            f"The stated {entry.drug} regimen ({stmt.raw}, ≈{daily:g} {entry.unit}/day) "
            f"exceeds the adult maximum of {entry.adult_max_daily:g} {entry.unit}/day. "
            f"{entry.notes}"
        )
    verdict = Verdict.BLOCK if worst_ratio >= EGREGIOUS_MULTIPLIER else Verdict.MODIFY
    return GuardResult(
        guard="dosage_validator",
        verdict=verdict,
        category="dosage",
        reason=f"{len(violations)} dose(s) above label maximum (worst {worst_ratio:.1f}x)",
        warnings=warnings,
        evidence={
            "validated_drugs": sorted(validated),
            "violations": [
                {"drug": e.drug, "daily": d, "max": e.adult_max_daily, "unit": e.unit}
                for _, e, d in violations
            ],
        },
    )
