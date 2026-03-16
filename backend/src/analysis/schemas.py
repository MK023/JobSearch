"""Analysis request/response schemas."""

import enum

from pydantic import BaseModel, Field


class ModelChoice(enum.StrEnum):
    """Supported Anthropic model tiers."""

    HAIKU = "haiku"
    SONNET = "sonnet"


class AnalyzeRequest(BaseModel):
    """Input schema for job analysis submission."""

    job_description: str = Field(..., min_length=50, max_length=50_000)
    job_url: str = Field("", max_length=500)
    model: ModelChoice = ModelChoice.HAIKU
