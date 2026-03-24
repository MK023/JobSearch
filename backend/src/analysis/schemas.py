"""Analysis request/response schemas."""

import enum
from typing import Any

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


class AnalysisImportRequest(BaseModel):
    """Input schema for importing a pre-computed analysis from the MCP server."""

    job_description: str = Field(..., max_length=50_000)
    job_url: str = Field("", max_length=500)
    content_hash: str = Field(..., max_length=128)
    job_summary: str = Field("", max_length=5_000)
    company: str = Field("", max_length=255)
    role: str = Field("", max_length=255)
    location: str = Field("", max_length=255)
    work_mode: str = Field("", max_length=50)
    salary_info: str = Field("", max_length=255)
    score: int = Field(0, ge=0, le=100)
    recommendation: str = Field("", max_length=2_000)
    strengths: list[Any] = []
    gaps: list[Any] = []
    interview_scripts: list[Any] = []
    advice: str = Field("", max_length=10_000)
    company_reputation: dict[str, Any] = {}
    full_response: str = Field("", max_length=100_000)
    model_used: str = Field("", max_length=100)
    tokens_input: int = Field(0, ge=0, le=10_000_000)
    tokens_output: int = Field(0, ge=0, le=10_000_000)
    cost_usd: float = Field(0.0, ge=0.0, le=1000.0)
