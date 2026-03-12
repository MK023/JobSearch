"""Cover letter request/response schemas."""

import enum

from pydantic import BaseModel, Field


class CoverLetterLanguage(enum.StrEnum):
    """Supported languages for cover letter generation."""

    ITALIANO = "italiano"
    ENGLISH = "english"
    FRANCAIS = "francais"
    DEUTSCH = "deutsch"
    ESPANOL = "espanol"


class CoverLetterRequest(BaseModel):
    """Input schema for cover letter generation."""

    analysis_id: str
    language: CoverLetterLanguage = CoverLetterLanguage.ITALIANO
    model: str = "haiku"


class CoverLetterResult(BaseModel):
    """Output schema for a generated cover letter."""

    cover_letter: str = ""
    subject_lines: list[str] = Field(default_factory=list)
    model_used: str = ""
    tokens: dict = Field(default_factory=dict)
    cost_usd: float = 0.0
    from_cache: bool = False
