# Interview Section Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated interview scheduling section with 4-tab history, interview booking modal, detail card, and upcoming interview dashboard banner.

**Architecture:** New `Interview` model with 1:1 FK to `JobAnalysis`. New `interview` module under `backend/src/` with model, service, API routes. Frontend gets a modal form triggered by the "Colloquio" pill, a detail partial, and a dashboard banner. History tabs change from 3 to 4.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Jinja2, Alpine.js, vanilla JS, CSS custom properties

---

### Task 1: Interview Model + Migration

**Files:**
- Create: `backend/src/interview/__init__.py`
- Create: `backend/src/interview/models.py`
- Create: `backend/alembic/versions/004_add_interviews.py`
- Modify: `backend/src/analysis/models.py:86-89` (add relationship)
- Modify: `backend/tests/conftest.py:10-22` (import new model)

**Step 1: Create the interview model**

Create `backend/src/interview/__init__.py` (empty file).

Create `backend/src/interview/models.py`:

```python
"""Interview scheduling model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..database.base import Base


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("job_analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    interview_type = Column(String(20), nullable=True)  # virtual, phone, in_person
    recruiter_name = Column(String(255), nullable=True)
    recruiter_email = Column(String(255), nullable=True)
    meeting_link = Column(String(500), nullable=True)
    phone_number = Column(String(50), nullable=True)
    phone_pin = Column(String(20), nullable=True)
    location = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    analysis = relationship("JobAnalysis", back_populates="interview")

    __table_args__ = (
        Index("idx_interviews_scheduled", "scheduled_at"),
    )
```

**Step 2: Add relationship to JobAnalysis**

In `backend/src/analysis/models.py`, after line 89 (the `contacts` relationship), add:

```python
    interview = relationship("Interview", back_populates="analysis", uselist=False, cascade="all, delete-orphan")
```

**Step 3: Register model in conftest**

In `backend/tests/conftest.py`, add import at top:

```python
from src.interview.models import Interview
```

Add `Interview` to `_ALL_MODELS` list (line 22):

```python
_ALL_MODELS = [AppSettings, CoverLetter, Contact, GlassdoorCache, AuditLog, NotificationLog, Interview]
```

**Step 4: Create Alembic migration**

Create `backend/alembic/versions/004_add_interviews.py`:

```python
"""Add interviews table for scheduling.

Revision ID: 004
Revises: 003
Create Date: 2026-02-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_analyses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interview_type", sa.String(20), nullable=True),
        sa.Column("recruiter_name", sa.String(255), nullable=True),
        sa.Column("recruiter_email", sa.String(255), nullable=True),
        sa.Column("meeting_link", sa.String(500), nullable=True),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("phone_pin", sa.String(20), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_interviews_scheduled", "interviews", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("idx_interviews_scheduled", table_name="interviews")
    op.drop_table("interviews")
```

**Step 5: Run tests to verify model creation doesn't break anything**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m pytest backend/tests/ -v`
Expected: All existing tests PASS

**Step 6: Commit**

```bash
git add backend/src/interview/ backend/alembic/versions/004_add_interviews.py backend/src/analysis/models.py backend/tests/conftest.py
git commit -m "feat: add Interview model and migration"
```

---

### Task 2: Interview Service Layer

**Files:**
- Create: `backend/src/interview/service.py`
- Create: `backend/tests/test_interview_service.py`

**Step 1: Write the failing tests**

Create `backend/tests/test_interview_service.py`:

```python
"""Tests for interview service."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.analysis.models import AnalysisStatus
from src.interview.models import Interview
from src.interview.service import (
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
)


class TestCreateOrUpdateInterview:
    def test_creates_new_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        interview = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=scheduled
        )
        assert interview is not None
        assert interview.analysis_id == test_analysis.id
        assert interview.scheduled_at == scheduled

    def test_creates_with_all_fields(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        interview = create_or_update_interview(
            db_session,
            test_analysis.id,
            scheduled_at=scheduled,
            ends_at=datetime(2026, 3, 10, 12, 15, tzinfo=UTC),
            interview_type="virtual",
            recruiter_name="Katharina Witting",
            recruiter_email="k.witting@example.com",
            meeting_link="https://meet.google.com/abc-def-ghi",
            phone_number="+39 02 3046 1972",
            phone_pin="333598657",
            notes="Colloquio recruiting",
        )
        assert interview.recruiter_name == "Katharina Witting"
        assert interview.interview_type == "virtual"
        assert interview.meeting_link == "https://meet.google.com/abc-def-ghi"

    def test_updates_existing_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        new_scheduled = datetime(2026, 3, 12, 14, 0, tzinfo=UTC)
        updated = create_or_update_interview(
            db_session, test_analysis.id, scheduled_at=new_scheduled, recruiter_name="New Person"
        )
        db_session.flush()

        assert updated.scheduled_at == new_scheduled
        assert updated.recruiter_name == "New Person"
        # Should be same record, not a new one
        interviews = db_session.query(Interview).filter_by(analysis_id=test_analysis.id).all()
        assert len(interviews) == 1

    def test_returns_none_for_missing_analysis(self, db_session):
        fake_id = uuid.uuid4()
        result = create_or_update_interview(
            db_session, fake_id, scheduled_at=datetime.now(UTC)
        )
        assert result is None


class TestGetInterviewByAnalysis:
    def test_returns_interview(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        result = get_interview_by_analysis(db_session, test_analysis.id)
        assert result is not None
        assert result.scheduled_at == scheduled

    def test_returns_none_when_no_interview(self, db_session, test_analysis):
        result = get_interview_by_analysis(db_session, test_analysis.id)
        assert result is None


class TestDeleteInterview:
    def test_deletes_existing(self, db_session, test_analysis):
        scheduled = datetime(2026, 3, 10, 11, 30, tzinfo=UTC)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=scheduled)
        db_session.flush()

        deleted = delete_interview(db_session, test_analysis.id)
        assert deleted is True
        assert get_interview_by_analysis(db_session, test_analysis.id) is None

    def test_returns_false_when_none(self, db_session, test_analysis):
        deleted = delete_interview(db_session, test_analysis.id)
        assert deleted is False


class TestGetUpcomingInterviews:
    def test_returns_interviews_within_48h(self, db_session, test_analysis):
        soon = datetime.now(UTC) + timedelta(hours=12)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=soon)
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 1

    def test_excludes_past_interviews(self, db_session, test_analysis):
        past = datetime.now(UTC) - timedelta(hours=1)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=past)
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 0

    def test_excludes_far_future(self, db_session, test_analysis, test_cv):
        far = datetime.now(UTC) + timedelta(days=5)
        create_or_update_interview(db_session, test_analysis.id, scheduled_at=far)
        test_analysis.status = AnalysisStatus.INTERVIEW
        db_session.flush()

        upcoming = get_upcoming_interviews(db_session)
        assert len(upcoming) == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m pytest backend/tests/test_interview_service.py -v`
Expected: FAIL (module not found)

**Step 3: Implement the service**

Create `backend/src/interview/service.py`:

```python
"""Interview scheduling service."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from .models import Interview


def create_or_update_interview(
    db: Session,
    analysis_id: UUID,
    *,
    scheduled_at: datetime,
    ends_at: datetime | None = None,
    interview_type: str | None = None,
    recruiter_name: str | None = None,
    recruiter_email: str | None = None,
    meeting_link: str | None = None,
    phone_number: str | None = None,
    phone_pin: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> Interview | None:
    """Create or update an interview for the given analysis."""
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return None

    interview = db.query(Interview).filter(Interview.analysis_id == analysis_id).first()

    if interview:
        interview.scheduled_at = scheduled_at
        interview.ends_at = ends_at
        interview.interview_type = interview_type
        interview.recruiter_name = recruiter_name
        interview.recruiter_email = recruiter_email
        interview.meeting_link = meeting_link
        interview.phone_number = phone_number
        interview.phone_pin = phone_pin
        interview.location = location
        interview.notes = notes
    else:
        interview = Interview(
            analysis_id=analysis_id,
            scheduled_at=scheduled_at,
            ends_at=ends_at,
            interview_type=interview_type,
            recruiter_name=recruiter_name,
            recruiter_email=recruiter_email,
            meeting_link=meeting_link,
            phone_number=phone_number,
            phone_pin=phone_pin,
            location=location,
            notes=notes,
        )
        db.add(interview)

    db.flush()
    return interview


def get_interview_by_analysis(db: Session, analysis_id: UUID) -> Interview | None:
    """Get interview for an analysis."""
    return db.query(Interview).filter(Interview.analysis_id == analysis_id).first()


def delete_interview(db: Session, analysis_id: UUID) -> bool:
    """Delete interview for an analysis. Returns True if deleted."""
    interview = db.query(Interview).filter(Interview.analysis_id == analysis_id).first()
    if not interview:
        return False
    db.delete(interview)
    db.flush()
    return True


def get_upcoming_interviews(db: Session, hours: int = 48) -> list[dict]:
    """Get interviews scheduled within the next N hours.

    Returns list of dicts with interview + analysis info for the banner.
    """
    now = datetime.now(UTC)
    cutoff = now + timedelta(hours=hours)

    rows = (
        db.query(Interview, JobAnalysis)
        .join(JobAnalysis, Interview.analysis_id == JobAnalysis.id)
        .filter(
            JobAnalysis.status == AnalysisStatus.INTERVIEW,
            Interview.scheduled_at > now,
            Interview.scheduled_at <= cutoff,
        )
        .order_by(Interview.scheduled_at.asc())
        .all()
    )

    return [
        {
            "analysis_id": str(a.id),
            "company": a.company,
            "role": a.role,
            "scheduled_at": i.scheduled_at.isoformat(),
            "ends_at": i.ends_at.isoformat() if i.ends_at else None,
            "interview_type": i.interview_type,
            "meeting_link": i.meeting_link,
        }
        for i, a in rows
    ]
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m pytest backend/tests/test_interview_service.py -v`
Expected: All PASS

**Step 5: Run all tests**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m pytest backend/tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add backend/src/interview/service.py backend/tests/test_interview_service.py
git commit -m "feat: add interview service with create/update/delete/upcoming"
```

---

### Task 3: Interview API Routes

**Files:**
- Create: `backend/src/interview/routes.py`
- Modify: `backend/src/api_v1.py` (register router)

**Step 1: Create API routes**

Create `backend/src/interview/routes.py`:

```python
"""Interview JSON API routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus
from ..analysis.service import get_analysis_by_id, update_status
from ..audit.service import audit
from ..auth.models import User
from ..database import get_db
from ..dependencies import get_current_user
from .service import (
    create_or_update_interview,
    delete_interview,
    get_interview_by_analysis,
    get_upcoming_interviews,
)

router = APIRouter(tags=["interviews"])


class InterviewPayload(BaseModel):
    scheduled_at: str
    ends_at: str | None = None
    interview_type: str | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    meeting_link: str | None = None
    phone_number: str | None = None
    phone_pin: str | None = None
    location: str | None = None
    notes: str | None = None


@router.post("/interviews/{analysis_id}")
def upsert_interview(
    request: Request,
    analysis_id: str,
    payload: InterviewPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    try:
        scheduled = datetime.fromisoformat(payload.scheduled_at)
    except ValueError:
        return JSONResponse({"error": "Invalid scheduled_at format"}, status_code=400)

    ends = None
    if payload.ends_at:
        try:
            ends = datetime.fromisoformat(payload.ends_at)
        except ValueError:
            return JSONResponse({"error": "Invalid ends_at format"}, status_code=400)

    interview = create_or_update_interview(
        db,
        analysis.id,
        scheduled_at=scheduled,
        ends_at=ends,
        interview_type=payload.interview_type,
        recruiter_name=payload.recruiter_name,
        recruiter_email=payload.recruiter_email,
        meeting_link=payload.meeting_link,
        phone_number=payload.phone_number,
        phone_pin=payload.phone_pin,
        location=payload.location,
        notes=payload.notes,
    )

    # Also set status to INTERVIEW
    update_status(db, analysis, AnalysisStatus.INTERVIEW)
    audit(db, request, "interview_upsert", f"id={analysis_id}")
    db.commit()

    return JSONResponse({"ok": True, "status": "colloquio"})


@router.get("/interviews/{analysis_id}")
def get_interview(
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    interview = get_interview_by_analysis(db, analysis_id)
    if not interview:
        return JSONResponse({"error": "No interview found"}, status_code=404)

    return JSONResponse({
        "analysis_id": str(interview.analysis_id),
        "scheduled_at": interview.scheduled_at.isoformat(),
        "ends_at": interview.ends_at.isoformat() if interview.ends_at else None,
        "interview_type": interview.interview_type,
        "recruiter_name": interview.recruiter_name,
        "recruiter_email": interview.recruiter_email,
        "meeting_link": interview.meeting_link,
        "phone_number": interview.phone_number,
        "phone_pin": interview.phone_pin,
        "location": interview.location,
        "notes": interview.notes,
    })


@router.delete("/interviews/{analysis_id}")
def remove_interview(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    deleted = delete_interview(db, analysis.id)
    if not deleted:
        return JSONResponse({"error": "No interview to delete"}, status_code=404)

    # Revert status to APPLIED
    update_status(db, analysis, AnalysisStatus.APPLIED)
    audit(db, request, "interview_delete", f"id={analysis_id}")
    db.commit()

    return JSONResponse({"ok": True, "status": "candidato"})


@router.get("/interviews-upcoming")
def upcoming_interviews(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return JSONResponse(get_upcoming_interviews(db))
```

**Step 2: Register the router in api_v1.py**

In `backend/src/api_v1.py`, add import and include:

```python
from .interview.routes import router as interview_router
```

And add at the end:

```python
api_v1_router.include_router(interview_router)
```

**Step 3: Run all tests**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m pytest backend/tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add backend/src/interview/routes.py backend/src/api_v1.py
git commit -m "feat: add interview API routes (CRUD + upcoming)"
```

---

### Task 4: History Tabs - 3 to 4 tabs

**Files:**
- Modify: `frontend/templates/partials/history.html` (add 4th tab)
- Modify: `frontend/static/js/modules/history.js` (4-tab filtering logic)

**Step 1: Update history.html to 4 tabs**

Replace the entire tabs section in `frontend/templates/partials/history.html` (lines 6-19):

```html
    <div class="tabs" id="history-tabs">
        <div class="tab" :class="{ 'active': activeTab === 'valutazione' }"
             @click="switchTab('valutazione')">
            In valutazione <span class="tab-badge" x-text="counts.valutazione">0</span>
        </div>
        <div class="tab" :class="{ 'active': activeTab === 'candidature' }"
             @click="switchTab('candidature')">
            Candidature <span class="tab-badge" x-text="counts.candidature">0</span>
        </div>
        <div class="tab" :class="{ 'active': activeTab === 'colloqui' }"
             @click="switchTab('colloqui')">
            Colloqui <span class="tab-badge" x-text="counts.colloqui">0</span>
        </div>
        <div class="tab" :class="{ 'active': activeTab === 'scartati' }"
             @click="switchTab('scartati')">
            Scartati <span class="tab-badge" x-text="counts.scartati">0</span>
        </div>
    </div>
```

**Step 2: Rewrite history.js for 4 tabs**

Replace the entire `historyTabs()` function in `frontend/static/js/modules/history.js`:

```javascript
/**
 * Alpine.js component: history tabs with DOM-based filtering.
 *
 * Items get their status from data-hist-status attributes, which are
 * updated imperatively by status.js when a user changes status.
 * The Alpine component handles tab switching and re-filtering.
 */

function historyTabs() {
    return {
        activeTab: 'valutazione',

        counts: {
            valutazione: 0,
            candidature: 0,
            colloqui: 0,
            scartati: 0
        },

        init: function() {
            this.filterItems();
        },

        switchTab: function(tab) {
            this.activeTab = tab;
            this.filterItems();
        },

        filterItems: function() {
            var tab = this.activeTab;
            var cVal = 0, cCand = 0, cColl = 0, cScar = 0;

            document.querySelectorAll('.history-item[data-hist-status]').forEach(function(item) {
                var st = item.dataset.histStatus || 'da_valutare';

                var bucket;
                if (st === 'da_valutare') { cVal++; bucket = 'valutazione'; }
                else if (st === 'candidato') { cCand++; bucket = 'candidature'; }
                else if (st === 'colloquio') { cColl++; bucket = 'colloqui'; }
                else { cScar++; bucket = 'scartati'; }

                item.style.display = (tab === bucket) ? '' : 'none';
            });

            this.counts.valutazione = cVal;
            this.counts.candidature = cCand;
            this.counts.colloqui = cColl;
            this.counts.scartati = cScar;
        }
    };
}


/**
 * Global function to refresh history tab counts and visibility
 * after imperative status changes. Called by status.js.
 */
function refreshHistoryCounts() {
    var histEl = document.querySelector('.history-section');
    if (!histEl) return;

    // Access Alpine v3 data and re-filter
    if (typeof Alpine !== 'undefined') {
        try {
            var data = Alpine.$data(histEl);
            if (data && data.filterItems) {
                data.filterItems();
            }
        } catch (e) {
            // Fallback: just re-query DOM
            console.warn('Could not access Alpine data for history, falling back', e);
        }
    }
}
```

**Step 3: Update mobile CSS for 4 tabs**

In `frontend/static/css/components.css`, the current mobile rule at line 541 sets `.tabs { flex-direction: column; }`. Change it to horizontal scrolling instead:

```css
    .tabs {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        flex-wrap: nowrap;
    }

    .tab {
        flex: 0 0 auto;
        white-space: nowrap;
        font-size: .72rem;
        padding: var(--space-md) var(--space-base);
    }
```

**Step 4: Verify by visual inspection**

Run the app and check that the 4 tabs display correctly on desktop and mobile.

**Step 5: Commit**

```bash
git add frontend/templates/partials/history.html frontend/static/js/modules/history.js frontend/static/css/components.css
git commit -m "feat: split history into 4 separate tabs"
```

---

### Task 5: Interview Modal (Form + JS)

**Files:**
- Create: `frontend/templates/partials/interview_modal.html`
- Create: `frontend/static/js/modules/interview.js`
- Modify: `frontend/static/js/modules/status.js:5-60` (intercept colloquio click)
- Modify: `frontend/templates/index.html` (include modal + script)

**Step 1: Create the modal template**

Create `frontend/templates/partials/interview_modal.html`:

```html
{# Interview booking modal #}
<div id="interview-modal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeInterviewModal()">
    <div class="modal-content card">
        <div class="modal-header">
            <h3 id="interview-modal-title">Prenota colloquio</h3>
            <button class="btn btn-sm" onclick="closeInterviewModal()" aria-label="Chiudi">&times;</button>
        </div>
        <form id="interview-form" onsubmit="return submitInterview(event)">
            <input type="hidden" id="iv-analysis-id" value="">

            <div class="form-grid">
                <div class="form-group form-group-required">
                    <label for="iv-scheduled">Data e ora *</label>
                    <input type="datetime-local" id="iv-scheduled" required>
                </div>
                <div class="form-group">
                    <label for="iv-ends">Ora fine</label>
                    <input type="datetime-local" id="iv-ends">
                </div>
                <div class="form-group">
                    <label for="iv-type">Tipo</label>
                    <select id="iv-type">
                        <option value="">-- Seleziona --</option>
                        <option value="virtual">Video call</option>
                        <option value="phone">Telefonico</option>
                        <option value="in_person">In presenza</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="iv-recruiter-name">Recruiter</label>
                    <input type="text" id="iv-recruiter-name" placeholder="Nome e cognome">
                </div>
                <div class="form-group">
                    <label for="iv-recruiter-email">Email recruiter</label>
                    <input type="email" id="iv-recruiter-email" placeholder="email@example.com">
                </div>
                <div class="form-group">
                    <label for="iv-meeting-link">Link videocall</label>
                    <input type="url" id="iv-meeting-link" placeholder="https://meet.google.com/...">
                </div>
                <div class="form-group">
                    <label for="iv-phone">Telefono</label>
                    <input type="tel" id="iv-phone" placeholder="+39 02 3046 1972">
                </div>
                <div class="form-group">
                    <label for="iv-pin">PIN telefono</label>
                    <input type="text" id="iv-pin" placeholder="333598657">
                </div>
                <div class="form-group">
                    <label for="iv-location">Luogo (se in presenza)</label>
                    <input type="text" id="iv-location" placeholder="Via Roma 1, Milano">
                </div>
                <div class="form-group form-group-full">
                    <label for="iv-notes">Note</label>
                    <textarea id="iv-notes" rows="3" placeholder="Dettagli aggiuntivi..."></textarea>
                </div>
            </div>

            <div class="modal-actions">
                <button type="button" class="btn btn-sm" onclick="closeInterviewModal()">Annulla</button>
                <button type="submit" class="btn btn-primary btn-sm">Conferma</button>
            </div>
        </form>
    </div>
</div>
```

**Step 2: Create interview.js**

Create `frontend/static/js/modules/interview.js`:

```javascript
/**
 * Interview modal: open, close, submit, populate.
 */

function openInterviewModal(analysisId) {
    var modal = document.getElementById('interview-modal');
    document.getElementById('iv-analysis-id').value = analysisId;
    document.getElementById('interview-modal-title').textContent = 'Prenota colloquio';

    // Try to load existing interview data
    fetch('/api/v1/interviews/' + analysisId, {
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) {
        if (r.ok) return r.json();
        return null;
    })
    .then(function(data) {
        if (data && data.scheduled_at) {
            populateInterviewForm(data);
            document.getElementById('interview-modal-title').textContent = 'Modifica colloquio';
        }
        modal.style.display = 'flex';
    })
    .catch(function() {
        modal.style.display = 'flex';
    });
}


function closeInterviewModal() {
    var modal = document.getElementById('interview-modal');
    modal.style.display = 'none';
    resetInterviewForm();
}


function resetInterviewForm() {
    document.getElementById('interview-form').reset();
    document.getElementById('iv-analysis-id').value = '';
}


function populateInterviewForm(data) {
    if (data.scheduled_at) {
        document.getElementById('iv-scheduled').value = isoToLocalInput(data.scheduled_at);
    }
    if (data.ends_at) {
        document.getElementById('iv-ends').value = isoToLocalInput(data.ends_at);
    }
    if (data.interview_type) document.getElementById('iv-type').value = data.interview_type;
    if (data.recruiter_name) document.getElementById('iv-recruiter-name').value = data.recruiter_name;
    if (data.recruiter_email) document.getElementById('iv-recruiter-email').value = data.recruiter_email;
    if (data.meeting_link) document.getElementById('iv-meeting-link').value = data.meeting_link;
    if (data.phone_number) document.getElementById('iv-phone').value = data.phone_number;
    if (data.phone_pin) document.getElementById('iv-pin').value = data.phone_pin;
    if (data.location) document.getElementById('iv-location').value = data.location;
    if (data.notes) document.getElementById('iv-notes').value = data.notes;
}


function isoToLocalInput(iso) {
    // Convert ISO string to datetime-local input value (YYYY-MM-DDTHH:MM)
    var d = new Date(iso);
    var pad = function(n) { return n < 10 ? '0' + n : n; };
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
           'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}


function submitInterview(e) {
    e.preventDefault();

    var analysisId = document.getElementById('iv-analysis-id').value;
    var scheduled = document.getElementById('iv-scheduled').value;
    if (!scheduled) return false;

    var payload = {
        scheduled_at: new Date(scheduled).toISOString(),
        ends_at: null,
        interview_type: document.getElementById('iv-type').value || null,
        recruiter_name: document.getElementById('iv-recruiter-name').value || null,
        recruiter_email: document.getElementById('iv-recruiter-email').value || null,
        meeting_link: document.getElementById('iv-meeting-link').value || null,
        phone_number: document.getElementById('iv-phone').value || null,
        phone_pin: document.getElementById('iv-pin').value || null,
        location: document.getElementById('iv-location').value || null,
        notes: document.getElementById('iv-notes').value || null
    };

    var endsVal = document.getElementById('iv-ends').value;
    if (endsVal) {
        payload.ends_at = new Date(endsVal).toISOString();
    }

    fetch('/api/v1/interviews/' + analysisId, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            closeInterviewModal();
            // Update pill buttons
            var group = document.querySelector('[data-analysis-id="' + analysisId + '"]');
            if (group) {
                group.querySelectorAll('.pill-btn').forEach(function(b) {
                    b.classList.remove('active');
                });
                var collBtn = group.querySelector('[data-status="colloquio"]');
                if (collBtn) collBtn.classList.add('active');
            }
            // Update history item
            var histItem = document.querySelector('[data-hist-id="' + analysisId + '"]');
            if (histItem) {
                histItem.dataset.histStatus = 'colloquio';
                var stEl = histItem.querySelector('.status-badge');
                if (stEl) {
                    stEl.className = 'status-badge status-badge-colloquio';
                    stEl.textContent = '\uD83D\uDDE3\uFE0F colloquio';
                }
            }
            refreshHistoryCounts();
            refreshSpending();
            refreshDashboard();
            // Reload page if on detail view to show interview card
            if (window.location.pathname.indexOf('/analysis/') !== -1) {
                window.location.reload();
            }
        }
    })
    .catch(function(e) { console.error('submitInterview error:', e); });

    return false;
}


function deleteInterviewFromDetail(analysisId) {
    if (!confirm('Rimuovere il colloquio? Lo status tornera\' a "candidato".')) return;

    fetch('/api/v1/interviews/' + analysisId, {
        method: 'DELETE',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            window.location.reload();
        }
    })
    .catch(function(e) { console.error('deleteInterview error:', e); });
}
```

**Step 3: Modify status.js to intercept "colloquio" click**

In `frontend/static/js/modules/status.js`, modify the `setStatus` function. When `status === 'colloquio'`, open the modal instead of calling the API directly:

Replace the entire `setStatus` function (lines 5-60):

```javascript
function setStatus(btn) {
    var group = btn.closest('.pill-group');
    var id = group.dataset.analysisId;
    var status = btn.dataset.status;

    // Intercept colloquio: open modal instead of direct status change
    if (status === 'colloquio') {
        openInterviewModal(id);
        return;
    }

    fetch('/api/v1/status/' + id + '/' + status, {
        method: 'POST',
        headers: { 'Accept': 'application/json' }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            // Update pill buttons
            group.querySelectorAll('.pill-btn').forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');

            // Update history item
            var histItem = document.querySelector('[data-hist-id="' + id + '"]');
            if (histItem) {
                histItem.dataset.histStatus = status;
                var stEl = histItem.querySelector('.status-badge');
                if (stEl) {
                    stEl.className = 'status-badge status-badge-' + status;
                    var icons = {
                        'da_valutare': '\uD83D\uDD0D',
                        'candidato': '\uD83D\uDCE8',
                        'colloquio': '\uD83D\uDDE3\uFE0F',
                        'scartato': '\u274C'
                    };
                    stEl.textContent = (icons[status] || '') + ' ' + status.replace('_', ' ');
                }
            }

            refreshHistoryCounts();
            refreshSpending();
            refreshDashboard();

            // Hide cover letter if rejected
            var clCard = document.getElementById('cover-letter-card');
            var clResult = document.getElementById('cover-letter-result-card');
            if (status === 'scartato') {
                if (clCard) clCard.style.display = 'none';
                if (clResult) clResult.style.display = 'none';
            }

            // Remove result card only when rejected
            if (status === 'scartato') {
                var resCard = btn.closest('.result-card');
                if (resCard) resCard.remove();
            }
        }
    })
    .catch(function(e) { console.error('setStatus error:', e); });
}
```

**Step 4: Include modal and script in index.html**

Find where other partials and scripts are included in `frontend/templates/index.html`. Add the modal partial (before closing `</body>` or near other modals) and the JS file (after status.js).

Add to template includes:
```html
{% include "partials/interview_modal.html" %}
```

Add to script includes:
```html
<script src="/static/js/modules/interview.js"></script>
```

**Step 5: Commit**

```bash
git add frontend/templates/partials/interview_modal.html frontend/static/js/modules/interview.js frontend/static/js/modules/status.js frontend/templates/index.html
git commit -m "feat: add interview booking modal with form"
```

---

### Task 6: Modal + Interview Card CSS

**Files:**
- Modify: `frontend/static/css/components.css` (modal styles)
- Modify: `frontend/static/css/sections.css` (interview card styles)

**Step 1: Add modal styles to components.css**

Append to `frontend/static/css/components.css` (before the responsive media query):

```css
/* ---- Modal ---- */

.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, .6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: var(--space-lg);
}

.modal-content {
    width: 100%;
    max-width: 560px;
    max-height: 90vh;
    overflow-y: auto;
    animation: modalIn .2s ease-out;
}

@keyframes modalIn {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-lg);
}

.modal-header h3 {
    margin: 0;
}

.modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-md);
    margin-top: var(--space-xl);
    padding-top: var(--space-lg);
    border-top: 1px solid var(--color-border);
}

.form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-md);
}

.form-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
}

.form-group label {
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--color-text-muted);
}

.form-group-full {
    grid-column: 1 / -1;
}

.form-group-required label::after {
    content: '';
}
```

**Step 2: Add interview card styles to sections.css**

Append to `frontend/static/css/sections.css` (before responsive media queries):

```css
/* ---- Interview detail card ---- */

.interview-detail-card {
    background: var(--color-lime-bg);
    border: 1px solid var(--color-lime-border);
    border-radius: var(--radius-lg);
    padding: var(--space-xl);
    margin-bottom: var(--space-xl);
}

.interview-detail-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--space-lg);
}

.interview-detail-title {
    font-weight: 700;
    font-size: 1rem;
    color: var(--color-lime-light);
}

.interview-detail-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: var(--space-sm) var(--space-lg);
    align-items: baseline;
}

.interview-detail-icon {
    font-size: 1rem;
    min-width: 24px;
    text-align: center;
}

.interview-detail-value {
    font-size: var(--font-size-sm);
    color: var(--color-text-body);
    word-break: break-word;
}

.interview-detail-value a {
    color: var(--color-lime-light);
    text-decoration: underline;
}

.interview-detail-actions {
    display: flex;
    gap: var(--space-md);
    margin-top: var(--space-lg);
    padding-top: var(--space-md);
    border-top: 1px solid var(--color-lime-border);
}

/* ---- Upcoming interview banner ---- */

.upcoming-interview-banner {
    background: var(--color-lime-bg);
    border: 1px solid var(--color-lime-border);
    border-radius: var(--radius-lg);
    padding: var(--space-lg) var(--space-xl);
    margin-bottom: var(--space-lg);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-lg);
}

.upcoming-interview-info {
    display: flex;
    flex-direction: column;
    gap: var(--space-xs);
}

.upcoming-interview-title {
    font-weight: 700;
    color: var(--color-lime-light);
}

.upcoming-interview-meta {
    font-size: var(--font-size-sm);
    color: var(--color-text-muted);
}
```

**Step 3: Add responsive rules for modal and interview card**

Add to the `@media (width <= 768px)` section in `components.css`:

```css
    .form-grid {
        grid-template-columns: 1fr;
    }

    .modal-content {
        max-width: 100%;
        margin: var(--space-md);
    }
```

Add to the `@media (width <= 768px)` section in `sections.css`:

```css
    .upcoming-interview-banner {
        flex-direction: column;
        align-items: flex-start;
    }

    .interview-detail-grid {
        grid-template-columns: auto 1fr;
    }
```

**Step 4: Commit**

```bash
git add frontend/static/css/components.css frontend/static/css/sections.css
git commit -m "feat: add modal and interview card CSS (mobile-first)"
```

---

### Task 7: Interview Detail Partial (in result page)

**Files:**
- Create: `frontend/templates/partials/interview_detail.html`
- Modify: `frontend/templates/partials/result.html:55-57` (include after reputation)
- Modify: `backend/src/analysis/routes.py:71-83` (pass interview to template)

**Step 1: Create the interview detail partial**

Create `frontend/templates/partials/interview_detail.html`:

```html
{# Interview detail card - shown when status is colloquio and interview exists #}
{% if current and current.interview and current.status.value == 'colloquio' %}
<div class="interview-detail-card">
    <div class="interview-detail-header">
        <span class="interview-detail-title">Colloquio prenotato</span>
        <span class="status-badge status-badge-colloquio">colloquio</span>
    </div>

    {% set iv = current.interview %}
    <div class="interview-detail-grid">
        <span class="interview-detail-icon">📅</span>
        <span class="interview-detail-value">
            {{ iv.scheduled_at.strftime('%A %d %B %Y, %H:%M') }}{% if iv.ends_at %} – {{ iv.ends_at.strftime('%H:%M') }}{% endif %}
        </span>

        {% if iv.interview_type %}
        <span class="interview-detail-icon">{% if iv.interview_type == 'virtual' %}💻{% elif iv.interview_type == 'phone' %}📞{% else %}🏢{% endif %}</span>
        <span class="interview-detail-value">{% if iv.interview_type == 'virtual' %}Video call{% elif iv.interview_type == 'phone' %}Telefonico{% else %}In presenza{% endif %}</span>
        {% endif %}

        {% if iv.recruiter_name %}
        <span class="interview-detail-icon">👤</span>
        <span class="interview-detail-value">{{ iv.recruiter_name }}</span>
        {% endif %}

        {% if iv.recruiter_email %}
        <span class="interview-detail-icon">✉️</span>
        <span class="interview-detail-value"><a href="mailto:{{ iv.recruiter_email }}">{{ iv.recruiter_email }}</a></span>
        {% endif %}

        {% if iv.meeting_link %}
        <span class="interview-detail-icon">🔗</span>
        <span class="interview-detail-value"><a href="{{ iv.meeting_link }}" target="_blank" rel="noopener noreferrer">{{ iv.meeting_link }}</a></span>
        {% endif %}

        {% if iv.phone_number %}
        <span class="interview-detail-icon">📞</span>
        <span class="interview-detail-value">{{ iv.phone_number }}{% if iv.phone_pin %} (PIN: {{ iv.phone_pin }}){% endif %}</span>
        {% endif %}

        {% if iv.location %}
        <span class="interview-detail-icon">📍</span>
        <span class="interview-detail-value">{{ iv.location }}</span>
        {% endif %}

        {% if iv.notes %}
        <span class="interview-detail-icon">📝</span>
        <span class="interview-detail-value">{{ iv.notes }}</span>
        {% endif %}
    </div>

    <div class="interview-detail-actions">
        <button class="btn btn-sm btn-primary" onclick="openInterviewModal('{{ current.id }}')">Modifica</button>
        <button class="btn btn-sm btn-danger" onclick="deleteInterviewFromDetail('{{ current.id }}')">Rimuovi</button>
    </div>
</div>
{% endif %}
```

**Step 2: Include in result.html**

In `frontend/templates/partials/result.html`, after line 56 (`{% include "partials/result_reputation.html" %}`), add:

```html
    {# ---- Interview details ---- #}
    {% include "partials/interview_detail.html" %}
```

**Step 3: Ensure interview relationship is loaded**

The `current.interview` access relies on the SQLAlchemy relationship already defined in Task 1. Since it's a `uselist=False` relationship, it will be lazily loaded when accessed. The `view_analysis` route in `backend/src/analysis/routes.py` already passes `current=analysis`, so `current.interview` will work with no changes needed.

**Step 4: Commit**

```bash
git add frontend/templates/partials/interview_detail.html frontend/templates/partials/result.html
git commit -m "feat: add interview detail card in analysis page"
```

---

### Task 8: Upcoming Interviews Dashboard Banner

**Files:**
- Modify: `frontend/templates/partials/dashboard.html:1-9` (add banner before dashboard)
- Modify: `backend/src/analysis/routes.py:86-117` (pass upcoming interviews to context)
- Modify: `frontend/static/js/modules/dashboard.js` (refresh banner)

**Step 1: Add upcoming interviews to page context**

In `backend/src/analysis/routes.py`, inside `_render_page()` function, after line 96 (`followup_alerts = get_followup_alerts(db)`), add:

```python
    from ..interview.service import get_upcoming_interviews
    upcoming_interviews = get_upcoming_interviews(db)
```

And add it to the `ctx` dict (around line 113):

```python
        "upcoming_interviews": upcoming_interviews,
```

**Step 2: Add banner to dashboard.html**

At the very top of `frontend/templates/partials/dashboard.html` (before line 1), add:

```html
{# Upcoming interview banners #}
{% if upcoming_interviews %}
{% for iv in upcoming_interviews %}
<div class="upcoming-interview-banner" id="upcoming-banner">
    <div class="upcoming-interview-info">
        <div class="upcoming-interview-title">Colloquio in arrivo — {{ iv.company }}</div>
        <div class="upcoming-interview-meta">
            {{ iv.role }} &middot; {{ iv.scheduled_at[:16]|replace('T', ' ') }}{% if iv.interview_type %} &middot; {% if iv.interview_type == 'virtual' %}Video call{% elif iv.interview_type == 'phone' %}Telefonico{% else %}In presenza{% endif %}{% endif %}
        </div>
    </div>
    <a href="/analysis/{{ iv.analysis_id }}" class="btn btn-sm btn-primary">Apri dettaglio</a>
</div>
{% endfor %}
{% endif %}
```

**Step 3: Add upcoming banner refresh to dashboard.js**

In `frontend/static/js/modules/dashboard.js`, add a new function that builds the banner using safe DOM methods, and call it from `refreshDashboard`.

Add at the end of the file:

```javascript

function refreshUpcomingBanners() {
    fetch('/api/v1/interviews-upcoming')
        .then(function(r) { return r.json(); })
        .then(function(interviews) {
            // Remove old banners
            document.querySelectorAll('.upcoming-interview-banner').forEach(function(el) {
                el.remove();
            });

            if (!interviews.length) return;

            // Find insertion point (before dashboard-details)
            var dashboard = document.getElementById('dashboard-details');
            if (!dashboard) return;

            interviews.forEach(function(iv) {
                var banner = document.createElement('div');
                banner.className = 'upcoming-interview-banner';

                var info = document.createElement('div');
                info.className = 'upcoming-interview-info';

                var title = document.createElement('div');
                title.className = 'upcoming-interview-title';
                title.textContent = 'Colloquio in arrivo \u2014 ' + iv.company;
                info.appendChild(title);

                var meta = document.createElement('div');
                meta.className = 'upcoming-interview-meta';
                var dateStr = iv.scheduled_at.substring(0, 16).replace('T', ' ');
                var metaText = iv.role + ' \u00b7 ' + dateStr;
                if (iv.interview_type === 'virtual') metaText += ' \u00b7 Video call';
                else if (iv.interview_type === 'phone') metaText += ' \u00b7 Telefonico';
                else if (iv.interview_type === 'in_person') metaText += ' \u00b7 In presenza';
                meta.textContent = metaText;
                info.appendChild(meta);

                banner.appendChild(info);

                var link = document.createElement('a');
                link.href = '/analysis/' + encodeURIComponent(iv.analysis_id);
                link.className = 'btn btn-sm btn-primary';
                link.textContent = 'Apri dettaglio';
                banner.appendChild(link);

                dashboard.parentNode.insertBefore(banner, dashboard);
            });
        })
        .catch(function(e) { console.error('refreshUpcomingBanners error:', e); });
}
```

Then in the `refreshDashboard` function, add a call to `refreshUpcomingBanners()` at the end of the `.then` block (before `.catch`):

```javascript
            refreshUpcomingBanners();
```

**Step 4: Commit**

```bash
git add frontend/templates/partials/dashboard.html frontend/static/js/modules/dashboard.js backend/src/analysis/routes.py
git commit -m "feat: add upcoming interview banner on dashboard"
```

---

### Task 9: Run Migration + Full Test Suite

**Step 1: Run Alembic migration**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && alembic -c backend/alembic.ini upgrade head`
Expected: Migration 004 applied successfully

**Step 2: Run full test suite**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m pytest backend/tests/ -v`
Expected: All tests PASS

**Step 3: Start the app and manual smoke test**

Run the app and verify:
1. History shows 4 tabs
2. Click "Colloquio" pill opens modal
3. Fill form and confirm -> status changes, interview saved
4. Detail page shows interview card
5. Upcoming banner shows if interview is within 48h
6. All 4 tabs filter correctly
7. Mobile layout works (responsive modal, tabs scroll)

**Step 4: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix: adjustments from smoke testing"
```

---

### Task 10: Final Cleanup + Integration Commit

**Step 1: Run linting**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && python -m ruff check backend/src/ backend/tests/ --fix`
Expected: No errors

**Step 2: Run stylelint if configured**

Run: `cd /Users/marcobellingeri/Documents/GitHub/JobSearch && npx stylelint "frontend/static/css/**/*.css" --fix` (if stylelint is configured)

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: interview scheduling — model, API, modal, detail card, upcoming banner, 4-tab history"
```
