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


class AnalysisImportRequest(BaseModel):
    """Input schema for importing a pre-computed analysis from the MCP server."""

    job_description: str
    job_url: str = ""
    content_hash: str
    job_summary: str = ""
    company: str = ""
    role: str = ""
    location: str = ""
    work_mode: str = ""
    salary_info: str = ""
    score: int = 0
    recommendation: str = ""
    strengths: list = []
    gaps: list = []
    interview_scripts: list = []
    advice: str = ""
    company_reputation: dict = {}
    full_response: str = ""
    model_used: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
