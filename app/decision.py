"""Decision engine — pure Python, no LLM.

Combines every guard signal with strict precedence ESCALATE > BLOCK > MODIFY >
ALLOW. One rule resolves conflicts: when a DETERMINISTIC guard has cleanly
evaluated a category (e.g. the dosage validator checked every attributable
dose), a non-deterministic (LLM judge) finding in that same category is
overridden and logged — the lookup table outranks the model's opinion.
"""

from dataclasses import dataclass, field

from app import responses
from app.guards.base import VERDICT_RANK, GuardResult, Verdict
from app.guards.emergency import CRISIS_CATEGORIES, POISON_CATEGORIES


@dataclass
class Decision:
    verdict: Verdict
    final_content: str
    fired: list[GuardResult] = field(default_factory=list)  # guards that raised signals
    all_results: list[GuardResult] = field(default_factory=list)
    overridden: list[GuardResult] = field(default_factory=list)  # judge findings vetoed

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "fired": [r.to_dict() for r in self.fired],
            "overridden": [r.to_dict() for r in self.overridden],
        }


def escalation_message(category: str | None) -> str:
    if category in CRISIS_CATEGORIES:
        return responses.ESCALATION_CRISIS
    if category in POISON_CATEGORIES:
        return responses.ESCALATION_POISON
    return responses.ESCALATION_EMERGENCY


def block_message(category: str | None) -> str:
    if category == "injection":
        return responses.BLOCK_INJECTION
    if category == "scope":
        return responses.BLOCK_SCOPE
    return responses.BLOCK_UNSAFE


def decide(results: list[GuardResult], upstream_content: str | None) -> Decision:
    """Combine guard results into the final verdict and user-facing content."""
    # Categories a deterministic guard affirmatively evaluated: either it
    # cleared the category with evidence (evidence["cleared"]) or it fired on
    # it (in which case the judge's duplicate finding adds nothing).
    cleared = {
        r.category
        for r in results
        if r.deterministic
        and r.category
        and (r.evidence.get("cleared") or r.verdict != Verdict.ALLOW)
    }

    effective: list[GuardResult] = []
    overridden: list[GuardResult] = []
    for r in results:
        # A judge finding may span several categories (evidence["categories"]).
        # "other" is treated as noise when a specific category is present —
        # judges habitually append it. The finding is overridden when every
        # specific category it raises is deterministically covered; if it
        # raises only "other" (something the validators can't see), it stands.
        judge_categories = set(r.evidence.get("categories") or ([r.category] if r.category else []))
        specific = judge_categories - {"other"}
        if (
            not r.deterministic
            and r.verdict in (Verdict.MODIFY, Verdict.BLOCK)
            and specific
            and specific <= cleared
        ):
            overridden.append(r)
        else:
            effective.append(r)

    fired = [r for r in effective if r.verdict != Verdict.ALLOW]
    if not fired:
        return Decision(Verdict.ALLOW, upstream_content or "", [], results, overridden)

    top = max(fired, key=lambda r: VERDICT_RANK[r.verdict])

    if top.verdict == Verdict.ESCALATE:
        return Decision(
            Verdict.ESCALATE, escalation_message(top.category), fired, results, overridden
        )

    if top.verdict == Verdict.BLOCK:
        return Decision(Verdict.BLOCK, block_message(top.category), fired, results, overridden)

    # MODIFY: pass the upstream response through with safety notes appended.
    warnings: list[str] = []
    for r in fired:
        for w in r.warnings:
            if w not in warnings:
                warnings.append(w)
    content = (upstream_content or "") + responses.WARNING_PREFIX + "\n".join(
        f"- {w}" for w in warnings
    )
    return Decision(Verdict.MODIFY, content, fired, results, overridden)
