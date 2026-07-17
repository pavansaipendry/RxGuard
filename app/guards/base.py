from dataclasses import dataclass, field
from enum import StrEnum


class Verdict(StrEnum):
    ALLOW = "ALLOW"
    MODIFY = "MODIFY"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


# Precedence for combining verdicts: higher wins.
VERDICT_RANK = {Verdict.ALLOW: 0, Verdict.MODIFY: 1, Verdict.BLOCK: 2, Verdict.ESCALATE: 3}


@dataclass
class GuardResult:
    guard: str  # e.g. "emergency_patterns", "dosage_validator", "output_judge"
    verdict: Verdict
    category: str | None = None  # e.g. "cardiac", "dosage", "interaction", "injection"
    reason: str = ""
    deterministic: bool = True  # False for LLM-judge results; deterministic wins conflicts
    warnings: list[str] = field(default_factory=list)  # texts appended on MODIFY
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "guard": self.guard,
            "verdict": self.verdict.value,
            "category": self.category,
            "reason": self.reason,
            "deterministic": self.deterministic,
            "warnings": self.warnings,
            "evidence": self.evidence,
        }
