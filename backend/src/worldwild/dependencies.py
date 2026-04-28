"""WorldWild-specific FastAPI dependencies.

Mirrors the primary ``DbSession`` alias in ``..dependencies`` but uses the
secondary engine. Routes that need access to Supabase import
``WorldwildDbSession`` and inject it like any other ``Annotated[Session, ...]``.

Routes also call ``ensure_worldwild_enabled`` first so a missing
``WORLDWILD_DATABASE_URL`` produces a friendly 503 instead of a 500 stack trace.
"""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..database.worldwild_db import get_worldwild_db, worldwild_enabled


def ensure_worldwild_enabled() -> None:
    """Reject early when the secondary DB is not configured."""
    if not worldwild_enabled:
        raise HTTPException(
            status_code=503,
            detail="WorldWild ingest layer is not configured (missing WORLDWILD_DATABASE_URL).",
        )


WorldwildDbSession = Annotated[Session, Depends(get_worldwild_db)]
WorldwildEnabledGuard = Annotated[None, Depends(ensure_worldwild_enabled)]
