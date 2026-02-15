"""Cover letter request/response schemas."""

import enum

from pydantic import BaseModel, Field


class CoverLetterLanguage(str, enum.Enum):
    ITALIANO = "italiano"
    ENGLISH = "english"
    FRANCAIS = "francais"
    DEUTSCH = "deutsch"
    ESPANOL = "espanol"


class CoverLetterRequest(BaseModel):
    analysis_id: str
    language: CoverLetterLanguage = CoverLetterLanguage.ITALIANO
    model: str = "haiku"


class CoverLetterResult(BaseModel):
    cover_letter: str = ""
    subject_lines: list[str] = Field(default_factory=list)
    model_used: str = ""
    tokens: dict = Field(default_factory=dict)
    cost_usd: float = 0.0
    from_cache: bool = False
