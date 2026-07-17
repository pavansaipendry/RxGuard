"""Decision engine: precedence, deterministic-over-judge override, warning assembly."""

from app import responses
from app.decision import decide
from app.guards.base import GuardResult, Verdict


def gr(guard, verdict, category=None, deterministic=True, warnings=None, evidence=None):
    return GuardResult(
        guard=guard, verdict=verdict, category=category, deterministic=deterministic,
        warnings=warnings or [], evidence=evidence or {},
    )


def test_all_allow_passes_content_through( ):
    decision = decide([gr("dosage_validator", Verdict.ALLOW, "dosage")], "the answer")
    assert decision.verdict == Verdict.ALLOW
    assert decision.final_content == "the answer"


def test_escalate_beats_everything():
    decision = decide(
        [
            gr("emergency_patterns", Verdict.ESCALATE, "cardiac"),
            gr("dosage_validator", Verdict.BLOCK, "dosage"),
        ],
        "unsafe content",
    )
    assert decision.verdict == Verdict.ESCALATE
    assert decision.final_content == responses.ESCALATION_EMERGENCY


def test_suicide_category_gets_crisis_message():
    decision = decide([gr("emergency_patterns", Verdict.ESCALATE, "suicide")], None)
    assert "988" in decision.final_content


def test_overdose_category_gets_poison_control():
    decision = decide([gr("emergency_patterns", Verdict.ESCALATE, "overdose")], None)
    assert "1-800-222-1222" in decision.final_content


def test_block_replaces_content():
    decision = decide([gr("injection_patterns", Verdict.BLOCK, "injection")], "jailbroken output")
    assert decision.verdict == Verdict.BLOCK
    assert decision.final_content == responses.BLOCK_INJECTION
    assert "jailbroken" not in decision.final_content


def test_modify_appends_deduped_warnings():
    decision = decide(
        [
            gr("interaction_validator", Verdict.MODIFY, "interaction",
               warnings=["warn A", "warn B"]),
            gr("output_judge", Verdict.MODIFY, "other", deterministic=False, warnings=["warn A"]),
        ],
        "base answer",
    )
    assert decision.verdict == Verdict.MODIFY
    assert decision.final_content.startswith("base answer")
    assert decision.final_content.count("warn A") == 1
    assert "warn B" in decision.final_content


def test_deterministic_clearance_overrides_judge():
    # Dosage validator affirmatively cleared the dose; judge's dosage complaint is vetoed.
    decision = decide(
        [
            gr("dosage_validator", Verdict.ALLOW, "dosage",
               evidence={"cleared": True, "validated_drugs": ["ibuprofen"]}),
            gr("output_judge", Verdict.BLOCK, "dosage", deterministic=False),
        ],
        "safe answer",
    )
    assert decision.verdict == Verdict.ALLOW
    assert len(decision.overridden) == 1


def test_judge_survives_when_nothing_was_cleared():
    # Extractor parsed nothing ("take the whole bottle") -> judge finding must stand.
    decision = decide(
        [
            gr("dosage_validator", Verdict.ALLOW, "dosage",
               evidence={"cleared": False, "validated_drugs": []}),
            gr("output_judge", Verdict.BLOCK, "dosage", deterministic=False),
        ],
        "dangerous answer",
    )
    assert decision.verdict == Verdict.BLOCK


def test_judge_escalation_is_never_overridden():
    decision = decide(
        [
            gr("dosage_validator", Verdict.ALLOW, "dosage", evidence={"cleared": True}),
            gr("input_judge", Verdict.ESCALATE, "cardiac", deterministic=False),
        ],
        None,
    )
    assert decision.verdict == Verdict.ESCALATE
