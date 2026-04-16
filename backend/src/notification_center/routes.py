"""Notification center API routes."""

from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from ..dependencies import CurrentUser, DbSession
from .models import NotificationDismissal
from .service import dismiss_notification, get_notifications, undismiss_notification

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
def notifications_api(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return the current notification list (dismissed ones excluded)."""
    notifications = get_notifications(db)
    return JSONResponse([n.model_dump(mode="json") for n in notifications])


@router.post("/notifications/dismiss")
def dismiss_api(
    db: DbSession,
    user: CurrentUser,
    notification_id: Annotated[str, Form()],
) -> JSONResponse:
    """Dismiss a notification server-side. Idempotent."""
    created = dismiss_notification(db, notification_id)
    db.commit()
    count = len(get_notifications(db))
    return JSONResponse({"ok": True, "created": created, "remaining_count": count})


@router.post("/notifications/undismiss")
def undismiss_api(
    db: DbSession,
    user: CurrentUser,
    notification_id: Annotated[str, Form()],
) -> JSONResponse:
    """Restore a previously dismissed notification."""
    removed = undismiss_notification(db, notification_id)
    db.commit()
    count = len(get_notifications(db))
    return JSONResponse({"ok": True, "removed": removed, "remaining_count": count})


@router.delete("/notifications/dismissals")
def clear_all_dismissals(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Clear all notification dismissals — all notifications resurface."""
    count = db.query(NotificationDismissal).delete()
    db.commit()
    return JSONResponse({"ok": True, "cleared": count})
