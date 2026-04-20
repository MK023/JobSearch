"""Routes for reading/writing whitelisted app_preferences.

Auth: CurrentUser required (session or X-API-Key). Writes are further
restricted to ALLOWED_KEYS — arbitrary keys return 400.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..dependencies import CurrentUser, DbSession
from .service import ALLOWED_KEYS, get_preference, set_preference

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

# OpenAPI response spec shared by both routes: 400 for non-whitelisted keys.
_NON_ALLOWED_KEY_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Preference key not in the server-side whitelist."},
}


class PreferencePayload(BaseModel):
    """Payload for updating a preference — any JSON value is allowed."""

    value: Any


@router.get("/{key}", responses=_NON_ALLOWED_KEY_RESPONSES)
def read_preference(key: str, db: DbSession, user: CurrentUser) -> JSONResponse:
    """Return a whitelisted preference value. 400 if key not whitelisted."""
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail="Preference key not allowed")
    return JSONResponse({"key": key, "value": get_preference(db, key, default=None)})


@router.put("/{key}", responses=_NON_ALLOWED_KEY_RESPONSES)
def write_preference(
    key: str,
    payload: PreferencePayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Upsert a whitelisted preference. 400 if key not whitelisted."""
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail="Preference key not allowed")
    set_preference(db, key, payload.value)
    return JSONResponse({"ok": True, "key": key, "value": payload.value})
