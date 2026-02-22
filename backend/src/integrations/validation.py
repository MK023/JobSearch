"""Pydantic validation schemas for AI response parsing.

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
    type: str = "sconosciuto"
    detail: str = ""
    note: str = ""


class CompanyReputation(BaseModel):
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
        try:
            val = int(float(str(v)))
            return max(0, min(100, val))
        except (ValueError, TypeError):
            return 0

    @field_validator("recommendation", mode="before")
    @classmethod
    def normalize_recommendation(cls, v: object) -> str:
        allowed = {"APPLY", "CONSIDER", "SKIP"}
        s = str(v).upper().strip()
        return s if s in allowed else "CONSIDER"

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: object) -> str:
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
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(item)
                elif isinstance(item, str):
                    result.append({"question": item, "suggested_answer": ""})
            return result
        return []


# ── Cover letter response ─────────────────────────────────────────────


class CoverLetterAIResponse(BaseModel):
    """Cover letter response from AI."""

    cover_letter: str = ""
    subject_lines: list[str] = Field(default_factory=list)

    @field_validator("subject_lines", mode="before")
    @classmethod
    def coerce_subject_lines(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(s) for s in v if s]
        return []

    @field_validator("cover_letter", mode="before")
    @classmethod
    def coerce_cover_letter(cls, v: object) -> str:
        return str(v) if v else ""


# ── Follow-up email response ──────────────────────────────────────────


class FollowupEmailAIResponse(BaseModel):
    """Follow-up email response from AI."""

    subject: str = ""
    body: str = ""
    tone_notes: str = ""

    @field_validator("subject", "body", mode="before")
    @classmethod
    def coerce_string(cls, v: object) -> str:
        return str(v) if v else ""


# ── LinkedIn message response ─────────────────────────────────────────


class LinkedInMessageAIResponse(BaseModel):
    """LinkedIn message response from AI."""

    message: str = ""
    connection_note: str = ""
    approach_tip: str = ""

    @field_validator("message", "connection_note", "approach_tip", mode="before")
    @classmethod
    def coerce_string(cls, v: object) -> str:
        return str(v) if v else ""


# ── Validation entry points ───────────────────────────────────────────


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


def validate_cover_letter(raw: dict) -> dict:
    """Validate and coerce a cover letter response."""
    try:
        validated = CoverLetterAIResponse.model_validate(raw)
        result = validated.model_dump()
        for key in raw:
            if key not in result:
                result[key] = raw[key]
        return result
    except Exception:
        logger.exception("Cover letter validation failed, using raw dict")
        return {
            "cover_letter": raw.get("cover_letter", str(raw)),
            "subject_lines": raw.get("subject_lines", []),
            **{k: v for k, v in raw.items() if k not in ("cover_letter", "subject_lines")},
        }


def validate_followup_email(raw: dict) -> dict:
    """Validate and coerce a follow-up email response."""
    try:
        validated = FollowupEmailAIResponse.model_validate(raw)
        result = validated.model_dump()
        for key in raw:
            if key not in result:
                result[key] = raw[key]
        return result
    except Exception:
        logger.exception("Followup email validation failed, using raw dict")
        return {
            "subject": raw.get("subject", ""),
            "body": raw.get("body", ""),
            "tone_notes": raw.get("tone_notes", ""),
            **raw,
        }


def validate_linkedin_message(raw: dict) -> dict:
    """Validate and coerce a LinkedIn message response."""
    try:
        validated = LinkedInMessageAIResponse.model_validate(raw)
        result = validated.model_dump()
        for key in raw:
            if key not in result:
                result[key] = raw[key]
        return result
    except Exception:
        logger.exception("LinkedIn message validation failed, using raw dict")
        return {
            "message": raw.get("message", ""),
            "connection_note": raw.get("connection_note", ""),
            "approach_tip": raw.get("approach_tip", ""),
            **raw,
        }


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
    return result
