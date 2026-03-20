"""Shared FastAPI dependencies and Annotated type aliases."""

import secrets
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .auth.models import User
from .config import settings
from .database import get_db
from .integrations.cache import CacheService


def validate_uuid(value: str) -> UUID:
    """Validate and parse a UUID string. Raises 400 on invalid input."""
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid ID format") from None


class AuthRequired(Exception):
    """Raised when user is not authenticated. Handled by exception handler in main.py."""

    pass


def get_cache(request: Request) -> CacheService:
    """Get the cache service from app state."""
    return cast(CacheService, request.app.state.cache)


def _get_user_from_session(request: Request, db: Session) -> User | None:
    """Try to get the authenticated user from session cookie. Returns None on failure."""
    user_id_str = request.session.get("user_id")
    if not user_id_str:
        return None
    try:
        user_id = UUID(user_id_str)
    except (ValueError, AttributeError):
        request.session.clear()
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        request.session.clear()
        return None
    return user


def _verify_api_key(api_key_header: str | None) -> bool:
    """Check if the provided API key matches the configured one.

    Returns True if:
    - api_key is not configured (dev mode, allow all)
    - api_key is configured and the header matches
    """
    if not settings.api_key:
        # Dev mode: no API key configured, allow all API key attempts
        return True
    if not api_key_header:
        return False
    return secrets.compare_digest(api_key_header, settings.api_key)


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> User:
    """Get the authenticated user from session cookie or API key.

    Authentication methods (tried in order):
    1. Session cookie (web UI)
    2. X-API-Key header (programmatic access, e.g. MCP server)

    For API key auth, the admin user is looked up by admin_email from settings.
    """
    # Try session auth first
    user = _get_user_from_session(request, db)
    if user:
        return user

    # Try API key auth
    if x_api_key and _verify_api_key(x_api_key):
        if not settings.admin_email:
            raise HTTPException(
                status_code=500,
                detail="API key auth requires ADMIN_EMAIL to be configured",
            )
        admin = db.query(User).filter(User.email == settings.admin_email).first()
        if not admin:
            raise HTTPException(status_code=500, detail="Admin user not found")
        return admin

    # Neither auth method succeeded
    raise AuthRequired()


# Annotated type aliases for FastAPI dependency injection (best practice).
# Import these in route files instead of using raw Depends().
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Cache = Annotated[CacheService, Depends(get_cache)]
