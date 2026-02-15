"""Dashboard and spending schemas."""

from pydantic import BaseModel, Field


class SpendingResponse(BaseModel):
    budget: float = 0.0
    total_cost_usd: float = 0.0
    remaining: float | None = None
    total_analyses: int = 0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    today_cost_usd: float = 0.0
    today_analyses: int = 0
    today_tokens_input: int = 0
    today_tokens_output: int = 0


class DashboardResponse(BaseModel):
    total: int = 0
    applied: int = 0
    interviews: int = 0
    skipped: int = 0
    pending: int = 0
    avg_score: float = 0.0
    followup_count: int = 0
    top_match: dict | None = None


class BudgetUpdateRequest(BaseModel):
    budget: float = Field(..., ge=0)
