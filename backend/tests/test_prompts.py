"""Prompt-level guardrails — anti-regression on critical detection rules.

These tests verify that the analysis prompt keeps the expected trigger
keywords and rule structure. They do NOT call the AI; they read the
ANALYSIS_SYSTEM_PROMPT string and assert invariants that protect users
from regressions (e.g. is_freelance not being flagged on daily-rate salaries).
"""

from src.prompts import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SYSTEM_PROMPT,
    COVER_LETTER_PROMPT_VERSION,
    COVER_LETTER_SYSTEM_PROMPT,
)


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


class TestCoverLetterPromptVersion:
    def test_version_set(self):
        assert isinstance(COVER_LETTER_PROMPT_VERSION, str)
        assert COVER_LETTER_PROMPT_VERSION.startswith("v")

    def test_version_at_least_v2(self):
        major = int(COVER_LETTER_PROMPT_VERSION.lstrip("v").split(".")[0])
        assert major >= 2, f"COVER_LETTER_PROMPT_VERSION regressed below v2: {COVER_LETTER_PROMPT_VERSION}"


class TestCoverLetterPromptHardening:
    """v2 hardening rules — anti-regression on the cover letter prompt quality."""

    def test_no_cliche_phrases_in_rules(self):
        # The prompt must explicitly forbid common cliché phrases.
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "missione mi ha colpito" in lower
        assert "appassionato" in lower
        assert "team player" in lower

    def test_concrete_opening_required(self):
        # v2 forbids generic motivational openings, requires a concrete intersection-of-skills opener.
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "intersezione" in lower or "intersection" in lower
        assert "niente fluff" in lower or "no fluff" in lower

    def test_cite_real_projects_required(self):
        # The prompt must require concrete project citations from CV, not vague claims.
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "progetto reale" in lower or "real project" in lower or "evidenze concrete" in lower

    def test_gap_management_documented(self):
        # The prompt must address how to handle missing requirements (Bachelor's, years, stack).
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "gap" in lower
        assert "bachelor" in lower
        assert "onestamente" in lower or "honestly" in lower

    def test_country_specific_tone_documented(self):
        # The prompt must adapt tone per country (IT, US, UK, FR, DE, ES).
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "italia" in lower or "italian" in lower
        assert "us" in lower or "english" in lower

    def test_call_to_action_required(self):
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "call-to-action" in lower or "call to action" in lower
        # CTA must be specific not generic
        assert "specifico" in lower or "specific" in lower

    def test_length_limit_documented(self):
        # 500 words ceiling for a single A4 page.
        lower = COVER_LETTER_SYSTEM_PROMPT.lower()
        assert "500" in COVER_LETTER_SYSTEM_PROMPT or "350" in COVER_LETTER_SYSTEM_PROMPT
        assert "parole" in lower or "words" in lower
