"""Inbox ingestion endpoint — entry point for the Chrome extension."""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from ..audit.service import audit
from ..config import settings
from ..database import SessionLocal
from ..dependencies import Cache, CurrentUser, DbSession
from ..rate_limit import limiter
from .schemas import InboxRequest, InboxResponse
from .service import InboxValidationError, ingest, process_pending

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.post("", response_model=InboxResponse)
@limiter.limit(settings.rate_limit_analyze)
def ingest_inbox(
    request: Request,
    payload: InboxRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    cache: Cache,
    db: DbSession,
) -> JSONResponse:
    """Ingest raw pasted job content from the Chrome extension.

    Auth: X-API-Key header OR session cookie (CurrentUser accepts both).
    Validation gates (in order): Pydantic model → domain whitelist → sanitize
    → pending quota → content_hash dedup. Async-triggers analyze_job on a
    new BackgroundTask when the item is freshly created.
    """
    try:
        item, dedup = ingest(
            db=db,
            user_id=cast(UUID, user.id),
            raw_text=payload.raw_text,
            source_url=str(payload.source_url),
            source=payload.source,
        )
    except InboxValidationError as exc:
        # Domain-level validation errors carry a user-facing message
        # authored by us (e.g. "testo troppo corto"). Log the typed exception
        # server-side for audit and return only the first arg — never the
        # full str() which CodeQL flags as stack-trace exposure because
        # a future subclass could embed internal state in its repr.
        _logger.info("inbox validation rejected: %s", exc)
        message = str(exc.args[0]) if exc.args else "Richiesta non valida."
        return JSONResponse({"error": message}, status_code=400)

    audit(
        db,
        request,
        "inbox_ingest",
        f"inbox={item.id}, source={payload.source}, dedup={dedup}",
    )
    db.commit()

    if not dedup:
        # Detach the item id; background task uses its own session.
        inbox_id = cast(UUID, item.id)
        user_id = cast(UUID, user.id)

        def _run_in_background() -> None:
            bg_db = SessionLocal()
            try:
                process_pending(bg_db, inbox_id, user_id, cache=cache)
            finally:
                bg_db.close()

        background_tasks.add_task(_run_in_background)

    return JSONResponse(
        {
            "inbox_id": str(item.id),
            "status": str(item.status),
            "analysis_id": str(item.analysis_id) if item.analysis_id else None,
            "dedup": dedup,
            "message": (
                "Analysis already exists — linked to this inbox item"
                if dedup
                else "Accepted — analysis running in background"
            ),
        }
    )
