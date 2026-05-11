"""Agenda routes — CRUD su ``todo_items`` (real) + lista mista API.

L'agenda mostra una lista mista di **real items** (``todo_items``,
creati dall'utente, toggleable + deletable) e **virtual items**
(regole computed in ``agenda.service``: es. interview imminenti nelle
prossime 48h, analisi PENDING che attendono triage).

Le virtual items NON hanno endpoint POST/PATCH/DELETE: il loro stato
deriva dai dati upstream e cambia quando l'utente agisce sulla risorsa
sottostante (es. fa il triage dell'inbox item → la virtual to-do
scompare al prossimo refresh, senza DB write).
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..dependencies import CurrentUser, DbSession
from ..notification_center.sse import broadcast_sync
from ..rate_limit import limiter
from .models import TodoItem

router = APIRouter(tags=["agenda"])

# Todo mutations move the dashboard "To-do" widget and the Agenda sidebar
# badge. We broadcast a single ``todos:changed`` event after each commit
# so connected tabs refresh both atomically — granular event names
# (added/toggled/deleted) wouldn't help the client since the snapshot is
# rebuilt regardless.
_TODOS_EVENT = "todos:changed"


@router.get("/todos")
def list_todos(
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Return all to-do items ordered by creation date."""
    items = db.query(TodoItem).order_by(TodoItem.created_at.desc()).all()
    return JSONResponse(
        [
            {
                "id": t.id,
                "text": t.text,
                "done": t.done,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in items
        ]
    )


@router.post("/todos")
@limiter.limit(settings.rate_limit_default)
def add_todo(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    text: Annotated[str, Form()],
) -> JSONResponse:
    """Create a new to-do item."""
    text = text.strip()
    if not text or len(text) > 500:
        return JSONResponse({"error": "Testo vuoto o troppo lungo (max 500)"}, status_code=400)
    item = TodoItem(text=text)
    db.add(item)
    db.commit()
    broadcast_sync(_TODOS_EVENT)
    return JSONResponse({"ok": True, "id": item.id, "text": item.text})


@router.post("/todos/{todo_id}/toggle")
@limiter.limit(settings.rate_limit_default)
def toggle_todo(
    request: Request,
    todo_id: int,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Toggle done status of a to-do item."""
    item = db.query(TodoItem).filter(TodoItem.id == todo_id).first()
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    item.done = not item.done  # type: ignore[assignment]
    item.completed_at = datetime.now(UTC) if item.done else None  # type: ignore[assignment]
    db.commit()
    broadcast_sync(_TODOS_EVENT)
    return JSONResponse({"ok": True, "done": item.done})


@router.delete("/todos/{todo_id}")
@limiter.limit(settings.rate_limit_default)
def delete_todo(
    request: Request,
    todo_id: int,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Delete a to-do item."""
    item = db.query(TodoItem).filter(TodoItem.id == todo_id).first()
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    db.delete(item)
    db.commit()
    broadcast_sync(_TODOS_EVENT)
    return JSONResponse({"ok": True})


@router.delete("/todos-completed")
@limiter.limit(settings.rate_limit_default)
def clear_completed_todos(
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    """Delete all completed to-do items."""
    count = db.query(TodoItem).filter(TodoItem.done == True).delete()  # noqa: E712
    db.commit()
    if count:
        broadcast_sync(_TODOS_EVENT)
    return JSONResponse({"ok": True, "deleted": count})
