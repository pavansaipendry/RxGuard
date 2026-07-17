"""Dosage validator policy: > max -> MODIFY, >= 2x max -> BLOCK."""

from app.guards.base import Verdict
from app.guards.dosage import validate_dosages
from app.guards.extraction import extract_doses


def run(text, lexicon, kb):
    return validate_dosages(extract_doses(text, lexicon), kb)


def test_safe_dose_allows_and_clears(lexicon, kb):
    result = run("acetaminophen 650 mg every 6 hours", lexicon, kb)
    assert result.verdict == Verdict.ALLOW
    assert result.evidence["cleared"] is True
    assert result.evidence["validated_drugs"] == ["acetaminophen"]


def test_exactly_at_max_allows(lexicon, kb):
    # 800 x 4 = 3200 = ibuprofen max; the line is drawn at exceeding it.
    assert run("ibuprofen 800 mg four times daily", lexicon, kb).verdict == Verdict.ALLOW


def test_above_max_modifies_with_citation(lexicon, kb):
    result = run("acetaminophen 1000 mg every 4 hours", lexicon, kb)  # 6000 vs 4000
    assert result.verdict == Verdict.MODIFY
    assert "4000" in result.warnings[0]
    assert "acetaminophen" in result.warnings[0]


def test_double_max_blocks(lexicon, kb):
    result = run("take 2 tablets of 500 mg acetaminophen every 3 hours", lexicon, kb)  # 8000
    assert result.verdict == Verdict.BLOCK


def test_stated_max_above_label_blocks(lexicon, kb):
    result = run("you can take up to 8,000 mg of Tylenol per day", lexicon, kb)
    assert result.verdict == Verdict.BLOCK


def test_mcg_drug_unit_error_blocks(lexicon, kb):
    # The classic mg/mcg catastrophe: 200 mg = 200,000 mcg vs 300 mcg max.
    result = run("your dose is levothyroxine 200 mg once daily", lexicon, kb)
    assert result.verdict == Verdict.BLOCK


def test_mcg_drug_correct_units_allow(lexicon, kb):
    assert run("levothyroxine 100 mcg once daily", lexicon, kb).verdict == Verdict.ALLOW


def test_unknown_drug_not_cleared(lexicon, kb):
    result = run("drink 2000 mg of vitamin C daily", lexicon, kb)
    assert result.verdict == Verdict.ALLOW
    assert result.evidence["cleared"] is False  # nothing validated -> no override power


def test_multiple_violations_worst_wins(lexicon, kb):
    text = (
        "Take tramadol 100 mg every 4 hours. "  # 600 vs 400 -> modify tier
        "Also diphenhydramine 100 mg every 4 hours."  # 600 vs 300 -> block tier
    )
    assert run(text, lexicon, kb).verdict == Verdict.BLOCK
