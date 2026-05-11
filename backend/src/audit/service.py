"""Audit log service — dual-DB write con resilienza cross-database.

``audit(db, request, action, detail)`` aggiunge una riga in ``audit_logs``
sul DB primario; ``dual_audit(...)`` mirra anche su ``WorldwildAuditLog``
nel DB secondary (Supabase) per defense-in-depth se Neon hit la quota
mensile e rifiuta scritture.

Il caller possiede ``db.commit()`` — questo modulo si occupa solo di
``db.add(...)`` + estrazione di user_id e IP dalla sessione/request.
``contextlib.suppress`` su parse UUID/IP evita di rompere il flusso
utente per un audit log malformato (è defensive logging, non load-bearing).
"""

import contextlib
import logging
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from ..rate_limit import get_client_ip
from .models import AuditLog

_logger = logging.getLogger(__name__)


def audit(db: Session, request: Request, action: str, detail: str = "", user_id: UUID | None = None) -> None:
    """Write an audit log entry to the primary DB.

    Caller owns the commit. If you also want the entry mirrored to the
    secondary DB (defense-in-depth against primary-DB lockout), use
    :func:`dual_audit` instead.
    """
    if user_id is None:
        uid = request.session.get("user_id")
        if uid:
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


def dual_audit(
    primary_db: Session,
    secondary_db: Session,
    request: Request,
    action: str,
    detail: str = "",
    user_id: UUID | None = None,
) -> None:
    """Write an audit entry to BOTH primary and secondary DBs independently.

    Each write is wrapped in its own try/except: a failure on either side
    (Neon over-quota, Supabase paused, network blip) logs a warning but does
    NOT block the user-facing action. The trade-off is intentional — losing
    one of the two copies is acceptable, blocking the action over an audit
    failure is not.

    Caller still owns commits on each session.
    """
    # Primary write (Neon)
    try:
        audit(primary_db, request, action, detail, user_id)
    except Exception:  # noqa: BLE001 — never raise from audit path
        _logger.exception("audit primary-DB write failed: action=%s", action)

    # Secondary write (Supabase) — local import to avoid circular dependency
    # at module load (worldwild.audit_models imports from database.worldwild_db
    # which is independent of the primary DB module graph).
    try:
        from ..worldwild.audit_models import WorldwildAuditLog

        if user_id is None:
            uid = request.session.get("user_id")
            if uid:
                with contextlib.suppress(ValueError, AttributeError):
                    user_id = UUID(uid)
        secondary_db.add(
            WorldwildAuditLog(
                user_id=user_id,
                action=action,
                detail=detail,
                ip_address=get_client_ip(request),
            )
        )
    except Exception:  # noqa: BLE001 — never raise from audit path
        _logger.exception("audit secondary-DB write failed: action=%s", action)
