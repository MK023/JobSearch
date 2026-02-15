"""Analysis request/response schemas."""

import enum

from pydantic import BaseModel, Field


class ModelChoice(str, enum.Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"


class AnalyzeRequest(BaseModel):
    job_description: str = Field(..., min_length=50, max_length=50_000)
    job_url: str = Field("", max_length=500)
    model: ModelChoice = ModelChoice.HAIKU


class StatusUpdateRequest(BaseModel):
    new_status: str


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0


class AnalysisResult(BaseModel):
    """Structured AI analysis result."""

    company: str = ""
    role: str = ""
    location: str = ""
    work_mode: str = ""
    salary_info: str = ""
    score: int = 0
    score_label: str = ""
    potential_score: int | None = None
    gap_timeline: str = ""
    confidence: str = ""
    confidence_reason: str = ""
    recommendation: str = ""
    job_summary: str = ""
    summary: str = ""
    strengths: list = Field(default_factory=list)
    gaps: list = Field(default_factory=list)
    interview_scripts: list = Field(default_factory=list)
    advice: str = ""
    application_method: dict = Field(default_factory=dict)
    company_reputation: dict = Field(default_factory=dict)
    model_used: str = ""
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    from_cache: bool = False
    full_response: str = ""
    content_hash: str = ""
