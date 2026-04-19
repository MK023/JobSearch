"""Tests for agenda virtual-triage-todos aggregation from inbox state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.agenda.service import get_virtual_triage_todos, list_agenda_items
from src.analysis.models import AnalysisStatus, JobAnalysis
from src.inbox.models import InboxItem, InboxStatus


def _inbox(db, user, *, status=InboxStatus.DONE.value, analysis_id=None, processed_delta_days=0):
    item = InboxItem(
        id=uuid.uuid4(),
        user_id=user.id,
        raw_text="Job posting body text that is certainly long enough to pass sanitization.",
        content_hash=str(uuid.uuid4()),
        source="linkedin",
        source_url="https://www.linkedin.com/jobs/view/1",
        status=status,
        analysis_id=analysis_id,
        processed_at=datetime.now(UTC) - timedelta(days=processed_delta_days),
    )
    db.add(item)
    db.commit()
    return item


def _analysis(db, cv, *, status=AnalysisStatus.PENDING.value, company="Acme", role="Senior Python"):
    a = JobAnalysis(
        id=uuid.uuid4(),
        cv_id=cv.id,
        job_description="x",
        status=status,
        company=company,
        role=role,
    )
    db.add(a)
    db.commit()
    return a


class TestVirtualTriageTodos:
    def test_no_inbox_returns_empty(self, db_session, test_user):
        assert get_virtual_triage_todos(db_session, test_user.id) == []

    def test_done_inbox_with_pending_analysis_surfaces(self, db_session, test_user, test_cv):
        a = _analysis(db_session, test_cv, company="TechCorp", role="DevOps Engineer")
        _inbox(db_session, test_user, analysis_id=a.id)

        result = get_virtual_triage_todos(db_session, test_user.id)
        assert len(result) == 1
        item = result[0]
        assert item["kind"] == "virtual"
        assert item["toggleable"] is False
        assert item["removable"] is False
        assert item["action_url"] == f"/analysis/{a.id}"
        assert "TechCorp" in item["text"]
        assert "DevOps Engineer" in item["text"]

    def test_triaged_analysis_not_surfaced(self, db_session, test_user, test_cv):
        # status=APPLIED means triaged — should disappear
        a = _analysis(db_session, test_cv, status=AnalysisStatus.APPLIED.value)
        _inbox(db_session, test_user, analysis_id=a.id)

        assert get_virtual_triage_todos(db_session, test_user.id) == []

    def test_old_items_outside_14d_window_not_surfaced(self, db_session, test_user, test_cv):
        a = _analysis(db_session, test_cv)
        _inbox(db_session, test_user, analysis_id=a.id, processed_delta_days=20)

        assert get_virtual_triage_todos(db_session, test_user.id) == []

    def test_inbox_still_pending_not_surfaced(self, db_session, test_user, test_cv):
        # Inbox status=PENDING means analysis hasn't run yet — no link
        _inbox(db_session, test_user, status=InboxStatus.PENDING.value)

        assert get_virtual_triage_todos(db_session, test_user.id) == []

    def test_error_inbox_not_surfaced(self, db_session, test_user):
        _inbox(db_session, test_user, status=InboxStatus.ERROR.value)

        assert get_virtual_triage_todos(db_session, test_user.id) == []

    def test_isolated_per_user(self, db_session, test_user, other_user, test_cv):
        a1 = _analysis(db_session, test_cv)
        _inbox(db_session, test_user, analysis_id=a1.id)
        _inbox(db_session, other_user, analysis_id=a1.id)  # same analysis but other's inbox

        result = get_virtual_triage_todos(db_session, test_user.id)
        assert len(result) == 1


class TestListAgendaItems:
    def test_virtual_items_come_before_real(self, db_session, test_user, test_cv):
        from src.agenda.models import TodoItem

        real = TodoItem(text="Hand-typed task")
        db_session.add(real)
        db_session.commit()

        a = _analysis(db_session, test_cv)
        _inbox(db_session, test_user, analysis_id=a.id)

        merged = list_agenda_items(db_session, test_user.id)
        assert len(merged) == 2
        assert merged[0]["kind"] == "virtual"
        assert merged[1]["kind"] == "real"
        assert merged[1]["toggleable"] is True

    def test_only_real_when_no_inbox_pending(self, db_session, test_user):
        from src.agenda.models import TodoItem

        db_session.add(TodoItem(text="Only real one"))
        db_session.commit()

        merged = list_agenda_items(db_session, test_user.id)
        assert len(merged) == 1
        assert merged[0]["kind"] == "real"
