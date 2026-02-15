"""CV request/response schemas."""

from pydantic import BaseModel, Field


class CVSaveRequest(BaseModel):
    cv_text: str = Field(..., min_length=20, max_length=100_000)
    cv_name: str = Field("", max_length=255)
