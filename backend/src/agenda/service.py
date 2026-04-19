"""Agenda service: aggregates real to-dos with rule-based virtual items.

Real items live in ``todo_items`` (user-created, toggleable, deletable).
Virtual items are computed on-the-fly from app state — they appear when a
condition is true and disappear when it resolves, without DB writes.

Current virtual source: inbox-originated analyses still in PENDING triage.
The user ingests a job via the Chrome extension → inbox_item becomes DONE
with a linked JobAnalysis → the virtual to-do surfaces ("Triagia Acme —
Senior Python Engineer") → user triages the analysis on /analysis/<id> →
virtual to-do disappears at next poll.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from ..inbox.models import InboxItem, InboxStatus
from .models import TodoItem


def _serialize_real(item: TodoItem) -> dict[str, Any]:
    return {
        "id": f"todo:{item.id}",
        "kind": "real",
        "text": item.text,
        "done": bool(item.done),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "action_url": None,
        "removable": True,
        "toggleable": True,
    }


def _serialize_virtual(inbox: InboxItem, analysis: JobAnalysis) -> dict[str, Any]:
    company = analysis.company or "(azienda sconosciuta)"
    role = analysis.role or "(ruolo sconosciuto)"
    source_label = str(inbox.source or "inbox")
    return {
        "id": f"inbox-triage:{inbox.id}",
        "kind": "virtual",
        "text": f"Triagia {company} — {role} (da {source_label})",
        "done": False,
        "created_at": inbox.processed_at.isoformat() if inbox.processed_at else None,
        "action_url": f"/analysis/{analysis.id}",
        "removable": False,
        "toggleable": False,
    }


def get_virtual_triage_todos(db: Session, user_id: UUID, *, days: int = 14) -> list[dict[str, Any]]:
    """Inbox-originated analyses awaiting triage — surface as virtual to-dos.

    Scope is limited to the last ``days`` days so the list can't grow
    indefinitely if the user never triages; old items stay on /history
    but don't clog the agenda.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        db.query(InboxItem, JobAnalysis)
        .join(JobAnalysis, InboxItem.analysis_id == JobAnalysis.id)
        .filter(
            InboxItem.user_id == user_id,
            InboxItem.status == InboxStatus.DONE.value,
            InboxItem.processed_at >= cutoff,
            JobAnalysis.status == AnalysisStatus.PENDING.value,
        )
        .order_by(InboxItem.processed_at.desc())
        .all()
    )
    return [_serialize_virtual(inbox, analysis) for inbox, analysis in rows]


def list_agenda_items(db: Session, user_id: UUID) -> list[dict[str, Any]]:
    """Merged list: virtual triage to-dos on top, real to-dos below.

    Virtual items surface attention-requiring work linked to fresh inbox
    activity. Real items come next so the user sees the actionable stuff
    first but still has their hand-curated list visible.
    """
    virtual = get_virtual_triage_todos(db, user_id)
    real = [_serialize_real(t) for t in db.query(TodoItem).order_by(TodoItem.created_at.desc()).all()]
    return virtual + real
