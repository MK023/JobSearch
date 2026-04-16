"""Agenda to-do CRUD routes."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from ..dependencies import CurrentUser, DbSession
from .models import TodoItem

router = APIRouter(tags=["agenda"])


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
def add_todo(
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
    return JSONResponse({"ok": True, "id": item.id, "text": item.text})


@router.post("/todos/{todo_id}/toggle")
def toggle_todo(
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
    return JSONResponse({"ok": True, "done": item.done})


@router.delete("/todos/{todo_id}")
def delete_todo(
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
    return JSONResponse({"ok": True})
