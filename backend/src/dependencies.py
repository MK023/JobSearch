"""Shared FastAPI dependencies."""

from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .auth.models import User
from .database import get_db
from .integrations.cache import CacheService


class AuthRequired(Exception):
    """Raised when user is not authenticated. Handled by exception handler in main.py."""

    pass


def get_cache(request: Request) -> CacheService:
    """Get the cache service from app state."""
    return request.app.state.cache


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Get the authenticated user from session, or redirect to login."""
    user_id_str = request.session.get("user_id")
    if not user_id_str:
        raise AuthRequired()
    try:
        user_id = UUID(user_id_str)
    except (ValueError, AttributeError):
        request.session.clear()
        raise AuthRequired()
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        request.session.clear()
        raise AuthRequired()
    return user


