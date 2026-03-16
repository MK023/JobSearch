"""Audit log service."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from ..rate_limit import get_client_ip
from .models import AuditLog


def audit(db: Session, request: Request, action: str, detail: str = "", user_id: UUID | None = None) -> None:
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
            ip_address=get_client_ip(request),
        )
    )
