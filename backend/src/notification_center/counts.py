"""Sidebar badge counts — single endpoint, in-memory cache.

The sidebar shows four live badges (Storico / Agenda / Notifiche / Colloqui)
plus the Analytics unlock dot. They all derive from short DB queries, but
without an endpoint the client can only see fresh values on full SSR
reloads — the previous design left the badges frozen during a session.

Why one endpoint instead of four:
    A single round-trip lets the client patch the whole sidebar atomically
    after a SSE nudge. Four parallel calls would fan out the same auth
    + DB connect cost four times.

Why an in-memory cache:
    Neon free tier was hitting 80% capacity. With a 5-second TTL the
    endpoint absorbs SSE-driven bursts (50 imports → 50 broadcasts →
    at most ~12 actual queries instead of 50). For a single-user app a
    5-second staleness window is invisible; the next poll/SSE tick
    refreshes naturally.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..agenda.models import TodoItem
from ..analysis.service import count_pending_analyses
from ..analytics_page.service import get_lock_state
from ..dependencies import CurrentUser, DbSession
from ..interview.service import get_upcoming_interviews
from .service import get_unread_count

router = APIRouter(prefix="/api/v1/notifications", tags=["sidebar-counts"])

_CACHE_TTL_SECONDS = 5.0
_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}


def _compute_counts(db: Session) -> dict[str, Any]:
    """Run the four count queries in sequence and shape the response.

    Kept as plain functions/queries (no ORM relationships, no joins) so
    each one can be inspected and tuned independently — the analytics
    unlock check in particular is doing extra work we don't want to
    bake into a join.
    """
    pending_count = count_pending_analyses(db)
    agenda_count = (
        db.query(func.count(TodoItem.id)).filter(TodoItem.done == False).scalar() or 0  # noqa: E712
    )
    interview_count = len(get_upcoming_interviews(db, days=14))
    notification_count = get_unread_count(db)
    analytics_available = bool(not get_lock_state(db).get("locked", True))

    return {
        "pending_count": int(pending_count),
        "agenda_count": int(agenda_count),
        "interview_count": int(interview_count),
        "notification_count": int(notification_count),
        "analytics_available": analytics_available,
    }


def get_sidebar_counts(db: Session, *, force: bool = False) -> dict[str, Any]:
    """Return cached counts, recomputing only when the TTL expires.

    ``force=True`` bypasses the cache (used by tests; production code
    should rely on the TTL to absorb bursts).
    """
    now = time.monotonic()
    cached = _cache["value"]
    if not force and cached is not None and now < _cache["expires_at"]:
        return dict(cached)

    fresh = _compute_counts(db)
    _cache["value"] = fresh
    _cache["expires_at"] = now + _CACHE_TTL_SECONDS
    return dict(fresh)


def invalidate_cache() -> None:
    """Drop the cached counts so the next request recomputes from DB.

    Exposed for tests; production relies on the TTL.
    """
    _cache["value"] = None
    _cache["expires_at"] = 0.0


@router.get("/sidebar-counts")
def sidebar_counts_endpoint(db: DbSession, _user: CurrentUser) -> dict[str, Any]:
    """Return all sidebar badge counts in one payload.

    Auth required: same gate as every other notification endpoint.
    The user object is unused but the dependency still runs so an
    unauthenticated caller gets a 401 before any DB work happens.
    """
    return get_sidebar_counts(db)
