"""Shared FastAPI dependencies and Annotated type aliases."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .auth.models import User
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


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    """Get the authenticated user from session, or redirect to login."""
    user_id_str = request.session.get("user_id")
    if not user_id_str:
        raise AuthRequired()
    try:
        user_id = UUID(user_id_str)
    except (ValueError, AttributeError):
        request.session.clear()
        raise AuthRequired() from None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        request.session.clear()
        raise AuthRequired()
    return user


# Annotated type aliases for FastAPI dependency injection (best practice).
# Import these in route files instead of using raw Depends().
DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Cache = Annotated[CacheService, Depends(get_cache)]
