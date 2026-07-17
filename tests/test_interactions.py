"""Interaction validator: cross-turn pair detection, no double-warn."""

from app.guards.base import Verdict
from app.guards.interactions import validate_interactions


def test_pair_across_turns_without_warning_modifies(lexicon, interactions):
    result = validate_interactions(
        "I take warfarin daily. Can I take aspirin for this headache?",
        "Aspirin works well for headaches. Take 325 mg with food.",
        lexicon, interactions,
    )
    assert result.verdict == Verdict.MODIFY
    assert "Warfarin" in result.warnings[0] and "Aspirin" in result.warnings[0]


def test_brand_names_resolve_to_pair(lexicon, interactions):
    result = validate_interactions(
        "I'm on Coumadin, what about Advil for my back?",
        "Advil is a solid choice for back pain.",
        lexicon, interactions,
    )
    assert result.verdict == Verdict.MODIFY
    assert "warfarin+ibuprofen (Major)" in result.evidence["interactions"]


def test_already_warned_allows_and_clears(lexicon, interactions):
    result = validate_interactions(
        "I take warfarin. Is aspirin ok?",
        "Do not take aspirin with warfarin unless your doctor directed it — bleeding risk.",
        lexicon, interactions,
    )
    assert result.verdict == Verdict.ALLOW
    assert result.evidence["cleared"] is True


def test_no_known_pair_allows_without_clearing(lexicon, interactions):
    result = validate_interactions(
        "Can I take Advil and Tylenol together?",
        "Yes, ibuprofen and acetaminophen can be alternated safely.",
        lexicon, interactions,
    )
    assert result.verdict == Verdict.ALLOW
    assert "cleared" not in result.evidence  # table isn't exhaustive; judge keeps authority


def test_multiple_pairs_all_warned(lexicon, interactions):
    result = validate_interactions(
        "I take warfarin and sertraline.",
        "For pain, ibuprofen 400 mg every 6 hours is a good option.",
        lexicon, interactions,
    )
    assert result.verdict == Verdict.MODIFY
    # warfarin+ibuprofen (Major) and sertraline+ibuprofen (Moderate)
    assert len(result.warnings) == 2
