"""Pydantic schemas for WorldWild HTTP endpoints.

Mirrors the inbox.schemas pattern: Literal types for enum-like query params
(boundary validation), Field descriptors with explicit constraints. Boundary
validation here is the architectural fix for Sonar S5145 — the ``decision``
param is type-narrowed at FastAPI's edge instead of being untainted via the
hardcoded ``_SAFE_DECISION_LABELS`` workaround introduced in PR #197.
"""

from typing import Literal

from pydantic import BaseModel, Field

DecisionLiteral = Literal["skip", "promote"]


class DecideResponse(BaseModel):
    """Reply to /api/v1/worldwild/decide/{offer_id}."""

    ok: bool
    offer_id: str
    decision: DecisionLiteral


class PromoteResponse(BaseModel):
    """Reply to /api/v1/worldwild/promote/{offer_id}.

    Returned synchronously when the request is accepted. The actual
    promotion runs in a BackgroundTask; the UI polls or listens via SSE
    for the terminal state (done / skipped_low_match / failed).
    """

    accepted: bool
    offer_id: str
    state: str = Field(..., description="One of: idle, pending, done, skipped_low_match, failed")
    message: str = ""


class IngestResponse(BaseModel):
    """Reply to /api/v1/worldwild/ingest/adzuna (manual trigger)."""

    ok: bool
    run_id: str
    fetched: int
    new: int
    filtered_out: int
