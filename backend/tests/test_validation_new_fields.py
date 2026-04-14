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
