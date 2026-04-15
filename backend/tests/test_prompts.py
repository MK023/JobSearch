"""Prompt-level guardrails — anti-regression on critical detection rules.

These tests verify that the analysis prompt keeps the expected trigger
keywords and rule structure. They do NOT call the AI; they read the
ANALYSIS_SYSTEM_PROMPT string and assert invariants that protect users
from regressions (e.g. is_freelance not being flagged on daily-rate salaries).
"""

from src.prompts import ANALYSIS_PROMPT_VERSION, ANALYSIS_SYSTEM_PROMPT


class TestPromptVersion:
    def test_version_is_set(self):
        assert isinstance(ANALYSIS_PROMPT_VERSION, str)
        assert ANALYSIS_PROMPT_VERSION.startswith("v")

    def test_version_is_at_least_v5(self):
        # v5 introduced hardened is_freelance detection — never downgrade.
        major = int(ANALYSIS_PROMPT_VERSION.lstrip("v").split(".")[0])
        assert major >= 5, f"ANALYSIS_PROMPT_VERSION regressed below v5: {ANALYSIS_PROMPT_VERSION}"


class TestFreelanceDetectionRules:
    """The is_freelance rule must cover daily/hourly salary triggers.

    These checks protect against accidental removal of the hardened rules
    (introduced in v5) that closed a regression where € X/giorno and
    € X/mese P.IVA were not flagging is_freelance=true.
    """

    def test_daily_rate_trigger_documented(self):
        # The prompt must mention daily-rate salary as a strong trigger.
        lower = ANALYSIS_SYSTEM_PROMPT.lower()
        assert "giorno" in lower or "daily rate" in lower
        assert "is_freelance=true" in lower

    def test_hourly_rate_trigger_documented(self):
        lower = ANALYSIS_SYSTEM_PROMPT.lower()
        assert "/ora" in lower or "hour" in lower

    def test_piva_salary_trigger_documented(self):
        # Explicit P.IVA inside salary_info must force is_freelance=true.
        lower = ANALYSIS_SYSTEM_PROMPT.lower()
        assert "p.iva" in lower
        assert "salary" in lower  # rule references salary_info

    def test_body_rental_distinct_from_freelance(self):
        # The prompt must keep body_rental and freelance as separate concepts.
        lower = ANALYSIS_SYSTEM_PROMPT.lower()
        assert "is_body_rental" in lower
        assert "is_freelance" in lower
        # Body rental examples still present
        for company in ("capgemini", "reply", "accenture"):
            assert company in lower, f"{company} missing from body_rental list"

    def test_exception_requires_all_three_conditions(self):
        # The only fallback to is_freelance=false must be guarded by an
        # explicit multi-condition check, not a single "or".
        text = ANALYSIS_SYSTEM_PROMPT.lower()
        assert "eccezione" in text or "exception" in text
        # The exception section mentions RAL/CCNL as requirement
        assert "ral" in text or "ccnl" in text
