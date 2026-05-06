"""Tests for the new AnalysisAIResponse fields: benefits, recruiter_info, experience_required."""

from src.integrations.validation import validate_analysis


class TestBenefits:
    def test_empty_list_default(self):
        result = validate_analysis({})
        assert result["benefits"] == []

    def test_list_of_strings_preserved(self):
        raw = {"benefits": ["smart working", "buoni pasto", "assicurazione"]}
        result = validate_analysis(raw)
        assert result["benefits"] == ["smart working", "buoni pasto", "assicurazione"]

    def test_comma_separated_string_split(self):
        raw = {"benefits": "smart working, buoni pasto, welfare"}
        result = validate_analysis(raw)
        assert result["benefits"] == ["smart working", "buoni pasto", "welfare"]

    def test_none_becomes_empty_list(self):
        raw = {"benefits": None}
        result = validate_analysis(raw)
        assert result["benefits"] == []


class TestRecruiterInfo:
    def test_empty_dict_default(self):
        result = validate_analysis({})
        assert result["recruiter_info"] == {}

    def test_dict_preserved(self):
        raw = {"recruiter_info": {"is_recruiter": True, "agency": "Hays", "contact": "john@hays.com"}}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_recruiter"] is True
        assert result["recruiter_info"]["agency"] == "Hays"

    def test_string_coerced_to_agency_dict(self):
        raw = {"recruiter_info": "Hays"}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["agency"] == "Hays"
        assert result["recruiter_info"]["is_recruiter"] is True

    def test_empty_string_is_not_recruiter(self):
        raw = {"recruiter_info": ""}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["agency"] == ""
        assert result["recruiter_info"]["is_recruiter"] is False

    def test_body_rental_flag_preserved(self):
        raw = {"recruiter_info": {"is_body_rental": True, "body_rental_company": "Capgemini"}}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_body_rental"] is True
        assert result["recruiter_info"]["body_rental_company"] == "Capgemini"
        # is_recruiter defaults to False even when body_rental is set
        assert result["recruiter_info"]["is_recruiter"] is False

    def test_body_rental_defaults_to_false_when_missing(self):
        raw = {"recruiter_info": {"is_recruiter": True, "agency": "Hays"}}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_recruiter"] is True
        assert result["recruiter_info"]["is_body_rental"] is False
        assert result["recruiter_info"]["body_rental_company"] == ""

    def test_string_form_initializes_body_rental_false(self):
        raw = {"recruiter_info": "Hays"}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_body_rental"] is False
        assert result["recruiter_info"]["body_rental_company"] == ""

    def test_freelance_flag_preserved(self):
        raw = {"recruiter_info": {"is_freelance": True, "freelance_reason": "richiesta P.IVA"}}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_freelance"] is True
        assert result["recruiter_info"]["freelance_reason"] == "richiesta P.IVA"
        # is_recruiter and is_body_rental default to False
        assert result["recruiter_info"]["is_recruiter"] is False
        assert result["recruiter_info"]["is_body_rental"] is False

    def test_freelance_defaults_to_false_when_missing(self):
        raw = {"recruiter_info": {"is_recruiter": True, "agency": "Hays"}}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_freelance"] is False
        assert result["recruiter_info"]["freelance_reason"] == ""

    def test_string_form_initializes_freelance_false(self):
        raw = {"recruiter_info": "Hays"}
        result = validate_analysis(raw)
        assert result["recruiter_info"]["is_freelance"] is False
        assert result["recruiter_info"]["freelance_reason"] == ""


class TestExperienceRequired:
    def test_empty_dict_default(self):
        result = validate_analysis({})
        assert result["experience_required"] == {}

    def test_full_dict_preserved(self):
        raw = {"experience_required": {"years_min": 3, "years_max": 5, "level": "mid", "raw_text": "3-5 anni"}}
        result = validate_analysis(raw)
        assert result["experience_required"]["years_min"] == 3
        assert result["experience_required"]["years_max"] == 5
        assert result["experience_required"]["level"] == "mid"

    def test_invalid_level_becomes_unspecified(self):
        raw = {"experience_required": {"years_min": 2, "level": "rockstar"}}
        result = validate_analysis(raw)
        assert result["experience_required"]["level"] == "unspecified"

    def test_string_years_coerced_to_int(self):
        raw = {"experience_required": {"years_min": "3", "years_max": "5", "level": "mid"}}
        result = validate_analysis(raw)
        assert result["experience_required"]["years_min"] == 3
        assert result["experience_required"]["years_max"] == 5

    def test_null_years_preserved_as_none(self):
        raw = {"experience_required": {"years_min": None, "years_max": "null", "level": "junior"}}
        result = validate_analysis(raw)
        assert result["experience_required"]["years_min"] is None
        assert result["experience_required"]["years_max"] is None

    def test_invalid_years_become_none(self):
        raw = {"experience_required": {"years_min": "n/a", "years_max": "a few", "level": "senior"}}
        result = validate_analysis(raw)
        assert result["experience_required"]["years_min"] is None
        assert result["experience_required"]["years_max"] is None
        assert result["experience_required"]["level"] == "senior"

    def test_raw_string_becomes_raw_text(self):
        raw = {"experience_required": "almeno 5 anni di esperienza"}
        result = validate_analysis(raw)
        assert result["experience_required"]["raw_text"] == "almeno 5 anni di esperienza"
        assert result["experience_required"]["level"] == "unspecified"


class TestRedFlags:
    def test_empty_list_default(self):
        result = validate_analysis({})
        assert result["red_flags"] == []

    def test_list_of_strings_preserved(self):
        raw = {"red_flags": ["salary non specificato", "stack troppo lungo"]}
        result = validate_analysis(raw)
        assert result["red_flags"] == ["salary non specificato", "stack troppo lungo"]

    def test_comma_separated_string_split(self):
        raw = {"red_flags": "salary mancante, stack eterogeneo, JD generico"}
        result = validate_analysis(raw)
        assert result["red_flags"] == ["salary mancante", "stack eterogeneo", "JD generico"]

    def test_capped_at_five_items(self):
        raw = {"red_flags": ["a", "b", "c", "d", "e", "f", "g"]}
        result = validate_analysis(raw)
        assert len(result["red_flags"]) == 5
        assert result["red_flags"] == ["a", "b", "c", "d", "e"]

    def test_none_becomes_empty_list(self):
        raw = {"red_flags": None}
        result = validate_analysis(raw)
        assert result["red_flags"] == []

    def test_empty_strings_filtered(self):
        raw = {"red_flags": ["valido", "", "  ", "altro"]}
        result = validate_analysis(raw)
        assert result["red_flags"] == ["valido", "altro"]


class TestEnglishLevelRequired:
    """``english_level_required`` normalizza CEFR + sinonimi comuni in JD italiane/inglesi.

    Il campo è additive: vuoto se la JD non menziona inglese, altrimenti uno fra
    A1/A2/B1/B2/C1/C2/Native. Sinonimi noti vengono mappati per non perdere info.
    """

    def test_empty_default_when_missing(self):
        result = validate_analysis({})
        assert result["english_level_required"] == ""

    def test_none_becomes_empty(self):
        result = validate_analysis({"english_level_required": None})
        assert result["english_level_required"] == ""

    def test_blank_string_becomes_empty(self):
        result = validate_analysis({"english_level_required": "   "})
        assert result["english_level_required"] == ""

    def test_valid_cefr_uppercase_preserved(self):
        for token in ("A1", "A2", "B1", "B2", "C1", "C2"):
            result = validate_analysis({"english_level_required": token})
            assert result["english_level_required"] == token

    def test_valid_cefr_lowercase_normalized(self):
        result = validate_analysis({"english_level_required": "b2"})
        assert result["english_level_required"] == "B2"

    def test_synonym_native_variants(self):
        for syn in ("Native", "native", "Madrelingua", "Mother tongue", "Bilingual", "Bilingue"):
            result = validate_analysis({"english_level_required": syn})
            assert result["english_level_required"] == "Native"

    def test_synonym_fluent_maps_to_c1(self):
        for syn in ("fluent", "Fluente", "professional", "Proficient", "advanced", "Avanzato"):
            result = validate_analysis({"english_level_required": syn})
            assert result["english_level_required"] == "C1"

    def test_synonym_intermediate_maps_to_b1(self):
        for syn in ("intermediate", "Intermedio"):
            result = validate_analysis({"english_level_required": syn})
            assert result["english_level_required"] == "B1"

    def test_synonym_upper_intermediate_maps_to_b2(self):
        for syn in ("upper intermediate", "Upper-Intermediate"):
            result = validate_analysis({"english_level_required": syn})
            assert result["english_level_required"] == "B2"

    def test_synonym_basic_maps_to_a2(self):
        for syn in ("basic", "Base"):
            result = validate_analysis({"english_level_required": syn})
            assert result["english_level_required"] == "A2"

    def test_synonym_beginner_maps_to_a1(self):
        for syn in ("beginner", "Principiante"):
            result = validate_analysis({"english_level_required": syn})
            assert result["english_level_required"] == "A1"

    def test_unknown_token_degraded_to_empty(self):
        for trash in ("dunno", "lol", "B7", "Z9", "fluentish"):
            result = validate_analysis({"english_level_required": trash})
            assert result["english_level_required"] == ""


class TestCompareCefrLevels:
    """``compare_cefr_levels(required, owned)`` ritorna match/gap/unknown/not_required.

    Ordering CEFR canonico: A1 < A2 < B1 < B2 < C1 < C2 < Native.
    ``Native`` superiore a C2 perché madrelingua implica fluency oltre l'esame.
    """

    def test_not_required_when_no_jd_request(self):
        from src.integrations.validation import compare_cefr_levels

        assert compare_cefr_levels("", "B2") == "not_required"
        assert compare_cefr_levels("", "") == "not_required"

    def test_unknown_when_user_level_missing(self):
        from src.integrations.validation import compare_cefr_levels

        assert compare_cefr_levels("B2", "") == "unknown"

    def test_unknown_when_token_unrecognized(self):
        from src.integrations.validation import compare_cefr_levels

        # Garbage tokens fall back to unknown rather than raising.
        assert compare_cefr_levels("XX", "B2") == "unknown"
        assert compare_cefr_levels("B2", "ZZ") == "unknown"

    def test_match_when_owned_equals_required(self):
        from src.integrations.validation import compare_cefr_levels

        for level in ("A1", "A2", "B1", "B2", "C1", "C2", "Native"):
            assert compare_cefr_levels(level, level) == "match"

    def test_match_when_owned_above_required(self):
        from src.integrations.validation import compare_cefr_levels

        # Marco scenario: B2 user su B1 JD (sufficient).
        assert compare_cefr_levels("B1", "B2") == "match"
        # Native su C1 JD.
        assert compare_cefr_levels("C1", "Native") == "match"
        # Edge: A1 JD, anyone qualifies.
        assert compare_cefr_levels("A1", "C2") == "match"

    def test_gap_when_owned_below_required(self):
        from src.integrations.validation import compare_cefr_levels

        # Marco scenario: B2 user su C1 JD (gap di 1).
        assert compare_cefr_levels("C1", "B2") == "gap"
        # Big gap: A2 user su C2 JD.
        assert compare_cefr_levels("C2", "A2") == "gap"
        # Adjacent: B2 user su C1.
        assert compare_cefr_levels("C2", "C1") == "gap"

    def test_native_outranks_c2(self):
        from src.integrations.validation import compare_cefr_levels

        assert compare_cefr_levels("C2", "Native") == "match"
        assert compare_cefr_levels("Native", "C2") == "gap"


class TestRunAnalysisWiringEnglishLevel:
    """Anti-regression: ``run_analysis`` deve passare ``english_level_required``
    dal result dict al costruttore JobAnalysis. Bug 6/5: il mapping era stato
    dimenticato in PR1 e per 2-3h le analisi salvavano il campo a "" invece
    del valore estratto dall'AI.
    """

    def test_run_analysis_includes_english_level_in_constructor(self):
        # Lettura statica: il sorgente di run_analysis deve costruire
        # JobAnalysis(english_level_required=result.get("english_level_required", ...)).
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "src" / "analysis" / "service.py"
        text = src.read_text()
        assert "english_level_required=result.get" in text, (
            "run_analysis() non sta passando english_level_required al costruttore JobAnalysis"
        )

    def test_rebuild_result_exposes_english_level(self):
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "src" / "analysis" / "service.py"
        text = src.read_text()
        assert '"english_level_required": analysis.english_level_required' in text, (
            "_base_result/rebuild_result non sta esponendo english_level_required nel dict"
        )
