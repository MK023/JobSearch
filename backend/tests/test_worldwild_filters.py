"""Unit tests for the WorldWild rule-based pre-filter.

Pure-function tests: no DB, no network. Purpose is to lock in the blacklist /
whitelist behavior we tuned against real Adzuna IT samples on 28 Apr 2026.
Future rule changes that flip these assertions need an explicit reason in the
PR description.
"""

from src.worldwild.filters import HARD_SALARY_FLOOR_EUR, has_remote_hint, pre_filter


class TestPreFilterBlacklist:
    """Titles that should always be rejected — high-noise patterns from Adzuna IT."""

    def test_help_desk_rejected(self) -> None:
        passed, reason = pre_filter({"title": "Help Desk 2° livello"})
        assert passed is False
        assert "blacklist" in reason

    def test_helpdesk_no_space_rejected(self) -> None:
        passed, reason = pre_filter({"title": "Helpdesk Senior"})
        assert passed is False
        assert "blacklist" in reason

    def test_junior_rejected_even_with_devops(self) -> None:
        # Blacklist runs before whitelist — junior wins regardless of domain.
        passed, reason = pre_filter({"title": "DevOps Junior Engineer"})
        assert passed is False
        assert "junior" in reason.lower()

    def test_legge_68_rejected(self) -> None:
        passed, reason = pre_filter({"title": "Application Maintenance Legge 68/1999"})
        assert passed is False
        assert "blacklist" in reason

    def test_l_68_short_form_rejected(self) -> None:
        passed, reason = pre_filter({"title": "Sviluppatore Junior L. 68"})
        assert passed is False

    def test_categoria_protetta_rejected(self) -> None:
        passed, reason = pre_filter({"title": "Sistemista categoria protetta"})
        assert passed is False
        assert "blacklist" in reason

    def test_stagista_rejected(self) -> None:
        passed, _ = pre_filter({"title": "Stagista DevOps"})
        assert passed is False

    def test_tirocinio_rejected(self) -> None:
        passed, _ = pre_filter({"title": "Tirocinio in cloud computing"})
        assert passed is False

    def test_sales_rejected(self) -> None:
        passed, _ = pre_filter({"title": "Sales Engineer"})
        assert passed is False

    def test_marketing_rejected(self) -> None:
        passed, _ = pre_filter({"title": "Digital Marketing Specialist"})
        assert passed is False


class TestPreFilterWhitelist:
    """Titles that should pass the whitelist — real Marco-fit patterns."""

    def test_devops_engineer_passes(self) -> None:
        passed, reason = pre_filter({"title": "DevOps Engineer"})
        assert passed is True
        assert reason == ""

    def test_dev_ops_with_space_passes(self) -> None:
        passed, _ = pre_filter({"title": "Senior Dev Ops Engineer"})
        assert passed is True

    def test_devsecops_passes(self) -> None:
        passed, _ = pre_filter({"title": "DevSecOps Lead"})
        assert passed is True

    def test_sre_passes(self) -> None:
        passed, _ = pre_filter({"title": "Site Reliability Engineer"})
        assert passed is True

    def test_platform_engineer_passes(self) -> None:
        passed, _ = pre_filter({"title": "Platform Engineer (80-100%)"})
        assert passed is True

    def test_cloud_engineer_passes(self) -> None:
        passed, _ = pre_filter({"title": "AWS Cloud Infrastructure Engineer"})
        assert passed is True

    def test_python_developer_passes(self) -> None:
        passed, _ = pre_filter({"title": "Senior Python Developer"})
        assert passed is True

    def test_kubernetes_passes(self) -> None:
        passed, _ = pre_filter({"title": "Kubernetes Specialist"})
        assert passed is True

    def test_sistemista_italian_passes(self) -> None:
        passed, _ = pre_filter({"title": "Sistemista Linux & IT Specialist"})
        assert passed is True

    def test_observability_engineer_passes(self) -> None:
        passed, _ = pre_filter({"title": "Observability Engineer"})
        assert passed is True


class TestPreFilterEdgeCases:
    """Boundary behaviors: salary floor, empty input, no whitelist match."""

    def test_empty_title_rejected(self) -> None:
        passed, reason = pre_filter({"title": ""})
        assert passed is False
        assert "empty title" in reason

    def test_missing_title_key_rejected(self) -> None:
        passed, reason = pre_filter({})
        assert passed is False
        assert "empty title" in reason

    def test_salary_below_floor_rejected(self) -> None:
        passed, reason = pre_filter({"title": "DevOps Engineer", "salary_min": HARD_SALARY_FLOOR_EUR - 1000})
        assert passed is False
        assert "salary_min" in reason

    def test_salary_at_floor_passes(self) -> None:
        passed, _ = pre_filter({"title": "DevOps Engineer", "salary_min": HARD_SALARY_FLOOR_EUR})
        assert passed is True

    def test_salary_zero_or_none_passes(self) -> None:
        # When Adzuna omits salary, we don't enforce — let AI step decide.
        passed, _ = pre_filter({"title": "DevOps Engineer", "salary_min": None})
        assert passed is True
        passed, _ = pre_filter({"title": "DevOps Engineer", "salary_min": 0})
        assert passed is True

    def test_completely_unrelated_title_rejected(self) -> None:
        # No blacklist hit, no whitelist match → reject with neutral reason.
        passed, reason = pre_filter({"title": "Maître d'Hôtel"})
        assert passed is False
        assert "no whitelist title match" in reason


class TestRemoteHint:
    """Soft signal — used in UI, never as a filter gate."""

    def test_smart_working_in_description(self) -> None:
        assert has_remote_hint({"title": "DevOps", "description": "Smart working possibile.", "location": "Milano"})

    def test_full_remote_in_description(self) -> None:
        assert has_remote_hint({"title": "DevOps", "description": "Full remote EU.", "location": ""})

    def test_no_hint_when_purely_onsite(self) -> None:
        assert not has_remote_hint({"title": "DevOps", "description": "On-site Milano, no flex.", "location": "Milano"})
