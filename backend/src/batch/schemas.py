"""Batch analysis schemas."""

import enum

from pydantic import BaseModel, Field


class BatchModelChoice(enum.StrEnum):
    """Supported model tiers for batch analysis."""

    HAIKU = "haiku"
    SONNET = "sonnet"


class BatchAddRequest(BaseModel):
    """Input schema for adding a job to the batch queue."""

    job_description: str = Field(..., min_length=50, max_length=50_000)
    job_url: str = Field("", max_length=500)
    model: BatchModelChoice = BatchModelChoice.HAIKU
