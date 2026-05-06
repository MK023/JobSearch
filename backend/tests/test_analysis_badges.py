"""Tests for the at-a-glance badges helpers (history card UI)."""

import pytest

from src.analysis.badges import career_track_label, recommendation_badge, salary_bracket


class TestRecommendationBadge:
    """Mappatura ``recommendation`` AI a icon+label+css."""

    @pytest.mark.parametrize(
        "raw,expected_label,expected_css",
        [
            ("APPLY", "APPLY", "rec-apply"),
            ("CONSIDER", "CONSIDER", "rec-consider"),
            ("SKIP", "SKIP", "rec-skip"),
            ("apply", "APPLY", "rec-apply"),  # case-insensitive
            ("  consider  ", "CONSIDER", "rec-consider"),  # trim/normalize? no — solo upper
        ],
    )
    def test_known_values(self, raw, expected_label, expected_css):
        result = recommendation_badge(raw)
        assert result["label"] == expected_label
        assert result["css"] == expected_css
        assert result["icon"]  # icon non vuota

    def test_unknown_falls_back_to_consider(self):
        for trash in ("", "WAT", None, "yes"):
            result = recommendation_badge(trash or "")
            assert result["label"] == "CONSIDER"
            assert result["css"] == "rec-consider"


class TestCareerTrackLabel:
    """Mappatura ``career_track`` enum a label friendly + css."""

    @pytest.mark.parametrize(
        "track,expected_label,expected_css",
        [
            ("plan_a_devops", "DevOps", "track-primary"),
            ("hybrid_a_b", "Hybrid", "track-primary"),
            ("plan_b_dev", "Dev", "track-secondary"),
            ("cybersec_junior_ok", "Cybersec", "track-secondary"),
            ("out_of_scope", "Off-target", "track-off"),
        ],
    )
    def test_known_tracks(self, track, expected_label, expected_css):
        result = career_track_label(track)
        assert result["label"] == expected_label
        assert result["css"] == expected_css

    def test_unknown_track_falls_back_to_hybrid(self):
        # Default "track-primary" su valori sconosciuti per non perdere info.
        for trash in ("", "made_up_value", None):
            result = career_track_label(trash or "")
            assert result["label"] == "Hybrid"
            assert result["css"] == "track-primary"


class TestSalaryBracketEmployee:
    """Bracket per dipendente: ≥45k=high, 35-45k=mid, <35k=low, vuoto=unknown."""

    def test_empty_returns_unknown(self):
        assert salary_bracket("", is_freelance=False)["bracket"] == "unknown"
        assert salary_bracket(None, is_freelance=False)["bracket"] == "unknown"
        assert salary_bracket("   ", is_freelance=False)["bracket"] == "unknown"

    def test_unparseable_returns_unknown(self):
        # Niente numeri → unknown
        assert salary_bracket("competitiva", is_freelance=False)["bracket"] == "unknown"
        assert salary_bracket("da definire", is_freelance=False)["bracket"] == "unknown"

    @pytest.mark.parametrize(
        "salary,expected",
        [
            ("45.000 € RAL", "high"),
            ("€45k", "high"),
            ("45000", "high"),
            ("55.000 EUR", "high"),
            ("€60k RAL", "high"),
            ("65 mila", "high"),
        ],
    )
    def test_high_bracket(self, salary, expected):
        assert salary_bracket(salary, is_freelance=False)["bracket"] == expected

    @pytest.mark.parametrize(
        "salary,expected",
        [
            ("35.000 € RAL", "mid"),
            ("€38k", "mid"),
            ("40000", "mid"),
            ("44 mila", "mid"),
        ],
    )
    def test_mid_bracket(self, salary, expected):
        assert salary_bracket(salary, is_freelance=False)["bracket"] == expected

    @pytest.mark.parametrize(
        "salary,expected",
        [
            ("28.000 € RAL", "low"),
            ("€25k", "low"),
            ("30000", "low"),
            ("32 mila", "low"),
        ],
    )
    def test_low_bracket(self, salary, expected):
        assert salary_bracket(salary, is_freelance=False)["bracket"] == expected


class TestSalaryBracketFreelance:
    """Bracket per freelance (day rate): ≥260€/d=high, <260€/d=low, vuoto=unknown.

    Soglia 260€/d = BAFNA Marco (Capgemini/Hays in pipeline).
    """

    def test_empty_returns_unknown(self):
        assert salary_bracket("", is_freelance=True)["bracket"] == "unknown"

    @pytest.mark.parametrize(
        "salary,expected",
        [
            ("260€/giorno", "high"),
            ("€280/day", "high"),
            ("300 euro al giorno", "high"),
            ("340€/MD", "high"),
        ],
    )
    def test_high_freelance(self, salary, expected):
        assert salary_bracket(salary, is_freelance=True)["bracket"] == expected

    @pytest.mark.parametrize(
        "salary,expected",
        [
            ("200€/day", "low"),
            ("€220 daily", "low"),
            ("180 euro/giorno", "low"),
            ("250€/MD", "low"),
        ],
    )
    def test_low_freelance(self, salary, expected):
        assert salary_bracket(salary, is_freelance=True)["bracket"] == expected

    def test_label_includes_day_rate_threshold(self):
        result = salary_bracket("280€/day", is_freelance=True)
        assert "260" in result["label"]
        assert "/d" in result["label"]
