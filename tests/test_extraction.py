"""Drug NER + dose parsing — the deterministic core, tested hard."""

from app.guards.extraction import extract_doses


def daily_for(text, lexicon, drug):
    return [s.daily_mg for s in extract_doses(text, lexicon) if s.drug == drug]


class TestDrugLexicon:
    def test_generic_and_brand_map_to_same_generic(self, lexicon):
        assert lexicon.find_generics("I take Tylenol and some acetaminophen") == {"acetaminophen"}

    def test_brand_aliases(self, lexicon):
        assert lexicon.find_generics("Coumadin with my Advil and Aleve") == {
            "warfarin", "ibuprofen", "naproxen",
        }

    def test_case_insensitive(self, lexicon):
        assert lexicon.find_generics("WARFARIN and zoloft") == {"warfarin", "sertraline"}

    def test_word_boundaries_no_substring_hits(self, lexicon):
        assert lexicon.find_generics("aspiring pharmacist, gabapentinoid research") == set()

    def test_multiword_alias(self, lexicon):
        assert lexicon.find_generics("started potassium chloride and a Z-pack") == {
            "potassium chloride", "azithromycin",
        }


class TestDoseParsing:
    def test_spec_example(self, lexicon):
        # The canonical case from the project spec.
        doses = daily_for(
            "take 2 tablets of 500mg acetaminophen twice daily", lexicon, "acetaminophen"
        )
        assert doses == [2000.0]

    def test_every_four_hours_worst_case(self, lexicon):
        assert daily_for(
            "acetaminophen 1000 mg every 4 hours", lexicon, "acetaminophen"
        ) == [6000.0]

    def test_range_frequency_uses_max(self, lexicon):
        assert daily_for(
            "ibuprofen 400 mg every 4-6 hours", lexicon, "ibuprofen"
        ) == [2400.0]

    def test_word_multiplier(self, lexicon):
        assert daily_for(
            "two 650 mg acetaminophen caplets every 4 hours", lexicon, "acetaminophen"
        ) == [7800.0]

    def test_no_spurious_multiplier_from_amount_digits(self, lexicon):
        # "500 mg" must never parse as 50 x "0 mg" or similar.
        assert daily_for("take 500 mg naproxen daily", lexicon, "naproxen") == [500.0]

    def test_gram_normalization(self, lexicon):
        doses = daily_for("0.5 g of amoxicillin three times daily", lexicon, "amoxicillin")
        assert doses == [1500.0]

    def test_mcg_normalization(self, lexicon):
        doses = daily_for("levothyroxine 200 mcg once daily", lexicon, "levothyroxine")
        assert doses == [0.2]  # normalized to mg internally

    def test_comma_thousands(self, lexicon):
        stmts = [
            s for s in extract_doses(
                "you can take up to 4,000 mg of Tylenol per day", lexicon
            ) if s.is_stated_max
        ]
        assert len(stmts) == 1
        assert stmts[0].daily_mg == 4000.0
        assert stmts[0].drug == "acetaminophen"

    def test_stated_max_do_not_exceed(self, lexicon):
        stmts = [
            s for s in extract_doses(
                "Take ibuprofen 400 mg as needed. Do not exceed 1,200 mg in 24 hours.", lexicon
            ) if s.is_stated_max
        ]
        assert [s.daily_mg for s in stmts] == [1200.0]
        assert stmts[0].drug == "ibuprofen"  # carried from previous sentence

    def test_hyphenated_dose(self, lexicon):
        assert daily_for("a 500-mg naproxen tablet twice daily", lexicon, "naproxen") == [1000.0]

    def test_drug_carries_across_sentences(self, lexicon):
        doses = daily_for(
            "Tramadol is an option for you. Take 100 mg every 6 hours.", lexicon, "tramadol"
        )
        assert doses == [400.0]

    def test_missing_frequency_assumes_once_and_flags(self, lexicon):
        stmts = extract_doses("sertraline 50 mg is a common starting point", lexicon)
        assert stmts[0].daily_mg == 50.0
        assert stmts[0].frequency_found is False

    def test_bid_abbreviation(self, lexicon):
        assert daily_for("metformin 1000 mg BID", lexicon, "metformin") == [2000.0]

    def test_no_drug_no_attribution(self, lexicon):
        stmts = extract_doses("drink 2000 mg of vitamin C daily", lexicon)
        assert all(s.drug is None for s in stmts)
