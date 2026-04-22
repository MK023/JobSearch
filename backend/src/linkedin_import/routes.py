"""JSON endpoints for the LinkedIn applications summary widget."""

from fastapi import APIRouter

from ..dependencies import CurrentUser, DbSession
from .service import get_summary

router = APIRouter(tags=["linkedin-import"])


@router.get("/analytics/linkedin/summary")
def linkedin_summary(db: DbSession, user: CurrentUser) -> dict:
    """Aggregate stats over ``linkedin_applications``.

    Single endpoint intentionally — the template wants one payload, not a
    waterfall of round-trips. The ``user`` dependency enforces auth; no
    user-scoped filter is applied because the tool is single-tenant (see
    CLAUDE.md / MEMORY.md).
    """
    del user  # dependency kept only for the auth side-effect
    return get_summary(db)
