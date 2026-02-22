"""Audit log service."""

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def audit(db: Session, request: Request, action: str, detail: str = "", user_id=None) -> None:
    """Write an audit log entry."""
    if user_id is None:
        uid = request.session.get("user_id")
        if uid:
            import contextlib
            from uuid import UUID

            with contextlib.suppress(ValueError, AttributeError):
                user_id = UUID(uid)

    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            detail=detail,
            ip_address=_get_ip(request),
        )
    )
