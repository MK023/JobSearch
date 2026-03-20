# Copied from backend/src/integrations/validation.py — keep in sync
"""Pydantic validation schemas for AI analysis response parsing.

Validates and coerces AI responses into strict structures.
Missing fields get sensible defaults; wrong types get coerced.
This is the last line of defense against malformed AI output.
"""

import logging

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ── Gap item ──────────────────────────────────────────────────────────


class GapItem(BaseModel):
    """A single gap/skill deficit."""

    gap: str = ""
    severity: str = "minore"
    closable: bool = True
    how: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v: object) -> str:
        allowed = {"bloccante", "importante", "minore"}
        s = str(v).lower().strip()
        return s if s in allowed else "minore"


class InterviewScript(BaseModel):
    """A single interview Q&A."""

    question: str = ""
    suggested_answer: str = ""


class ApplicationMethod(BaseModel):
    """How to apply for the job (email, link, quick_apply, etc.)."""

    type: str = "sconosciuto"
    detail: str = ""
    note: str = ""


class CompanyReputation(BaseModel):
    """AI-estimated company reputation data."""

    glassdoor_estimate: str = "non disponibile"
    known_pros: list[str] = Field(default_factory=list)
    known_cons: list[str] = Field(default_factory=list)
    note: str = ""


# ── Analysis response ─────────────────────────────────────────────────


class AnalysisAIResponse(BaseModel):
    """Full analysis response from AI, with strict validation and defaults."""

    company: str = ""
    role: str = ""
    location: str = ""
    work_mode: str = ""
    salary_info: str = ""
    score: int = 0
    score_label: str = ""
    potential_score: int = 0
    gap_timeline: str = ""
    confidence: str = "media"
    confidence_reason: str = ""
    recommendation: str = "CONSIDER"
    job_summary: str = ""
    summary: str = ""
    strengths: list = Field(default_factory=list)
    gaps: list = Field(default_factory=list)
    interview_scripts: list = Field(default_factory=list)
    advice: str = ""
    application_method: dict = Field(default_factory=dict)
    company_reputation: dict = Field(default_factory=dict)
    full_response: str = ""

    @field_validator("score", mode="before")
    @classmethod
    def coerce_score(cls, v: object) -> int:
        """Ensure score is an int 0-100, handling strings and floats."""
        try:
            val = int(float(str(v)))
            return max(0, min(100, val))
        except (ValueError, TypeError):
            return 0

    @field_validator("potential_score", mode="before")
    @classmethod
    def coerce_potential_score(cls, v: object) -> int:
        """Ensure potential_score is an int 0-100."""
        try:
            val = int(float(str(v)))
            return max(0, min(100, val))
        except (ValueError, TypeError):
            return 0

    @field_validator("recommendation", mode="before")
    @classmethod
    def normalize_recommendation(cls, v: object) -> str:
        """Ensure recommendation is one of APPLY, CONSIDER, SKIP."""
        allowed = {"APPLY", "CONSIDER", "SKIP"}
        s = str(v).upper().strip()
        return s if s in allowed else "CONSIDER"

    @field_validator("job_summary", mode="before")
    @classmethod
    def coerce_job_summary(cls, v: object) -> str:
        """Accept string or list of bullet points, joining with newlines."""
        if isinstance(v, list):
            return "\n".join(str(item) for item in v)
        return str(v) if v else ""

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: object) -> str:
        """Ensure confidence is one of alta, media, bassa."""
        allowed = {"alta", "media", "bassa"}
        s = str(v).lower().strip()
        return s if s in allowed else "media"

    @field_validator("strengths", mode="before")
    @classmethod
    def coerce_strengths(cls, v: object) -> list:
        """Accept list of strings or list of dicts with 'skill' key."""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return v
        return []

    @field_validator("gaps", mode="before")
    @classmethod
    def coerce_gaps(cls, v: object) -> list:
        """Accept list of dicts, list of strings, or comma-separated string."""
        if isinstance(v, str):
            return [
                {"gap": g.strip(), "severity": "minore", "closable": True, "how": ""} for g in v.split(",") if g.strip()
            ]
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, str):
                    result.append({"gap": item, "severity": "minore", "closable": True, "how": ""})
                elif isinstance(item, dict):
                    result.append(item)
                else:
                    result.append({"gap": str(item), "severity": "minore", "closable": True, "how": ""})
            return result
        return []

    @field_validator("interview_scripts", mode="before")
    @classmethod
    def coerce_interview_scripts(cls, v: object) -> list:
        """Accept list of dicts or list of question strings."""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(item)
                elif isinstance(item, str):
                    result.append({"question": item, "suggested_answer": ""})
            return result
        return []


# ── Validation entry point ───────────────────────────────────────────


def validate_analysis(raw: dict) -> dict:
    """Validate and coerce an analysis response dict.

    Applies Pydantic validation, fills defaults, coerces types.
    Returns a clean dict. Never raises - logs warnings for issues.
    """
    try:
        validated = AnalysisAIResponse.model_validate(raw)
        result = validated.model_dump()
        # Preserve any extra fields from AI that we don't validate
        for key in raw:
            if key not in result:
                result[key] = raw[key]
        return result
    except Exception:
        logger.exception("Analysis validation failed, using raw dict with defaults")
        return _apply_analysis_defaults(raw)


def _apply_analysis_defaults(raw: dict) -> dict:
    """Apply defaults to a raw analysis dict (fallback when Pydantic fails)."""
    defaults = {
        "company": "",
        "role": "",
        "location": "",
        "work_mode": "",
        "salary_info": "",
        "score": 0,
        "score_label": "",
        "potential_score": 0,
        "gap_timeline": "",
        "confidence": "media",
        "confidence_reason": "",
        "recommendation": "CONSIDER",
        "job_summary": "",
        "summary": "",
        "strengths": [],
        "gaps": [],
        "interview_scripts": [],
        "advice": "",
        "application_method": {},
        "company_reputation": {},
        "full_response": "",
    }
    result = {**defaults, **raw}
    # Coerce score
    try:
        result["score"] = max(0, min(100, int(float(str(result["score"])))))
    except (ValueError, TypeError):
        result["score"] = 0
    # Coerce job_summary (AI sometimes returns a list)
    if isinstance(result.get("job_summary"), list):
        result["job_summary"] = "\n".join(str(item) for item in result["job_summary"])
    return result
