"""Tests for batch route-level logic (max_batch_size, pending-items, item status, clear)."""

import uuid

from sqlalchemy import func

from src.batch.models import BatchItem, BatchItemStatus
from src.batch.service import add_to_queue, clear_completed, get_batch_status, get_pending_batch_id
from src.config import settings


class TestBatchAddHardLimit:
    """The route enforces max_batch_size by counting PENDING+RUNNING items."""

    def test_allows_up_to_max_batch_size(self, db_session, test_cv):
        """Adding max_batch_size items should succeed."""
        for i in range(settings.max_batch_size):
            add_to_queue(db_session, test_cv.id, f"Job {i}", cv_text="test cv")
        db_session.commit()

        pending_count = (
            db_session.query(func.count(BatchItem.id))
            .filter(BatchItem.status.in_([BatchItemStatus.PENDING, BatchItemStatus.RUNNING]))
            .scalar()
            or 0
        )
        assert pending_count == settings.max_batch_size

    def test_rejects_beyond_max_batch_size(self, db_session, test_cv):
        """After max_batch_size pending items, the route-level check should trigger.

        We simulate the route-level guard: count PENDING+RUNNING, compare to max_batch_size.
        """
        for i in range(settings.max_batch_size):
            add_to_queue(db_session, test_cv.id, f"Job {i}", cv_text="test cv")
        db_session.commit()

        pending_count = (
            db_session.query(func.count(BatchItem.id))
            .filter(BatchItem.status.in_([BatchItemStatus.PENDING, BatchItemStatus.RUNNING]))
            .scalar()
            or 0
        )
        # This is the guard from routes.py batch_add
        assert pending_count >= settings.max_batch_size

    def test_done_items_dont_count_toward_limit(self, db_session, test_cv):
        """Items marked DONE should not count against the batch size limit."""
        for i in range(settings.max_batch_size):
            add_to_queue(db_session, test_cv.id, f"Job {i}", cv_text="test cv")
        db_session.commit()

        # Mark all as done
        db_session.query(BatchItem).update({BatchItem.status: BatchItemStatus.DONE}, synchronize_session="fetch")
        db_session.commit()

        pending_count = (
            db_session.query(func.count(BatchItem.id))
            .filter(BatchItem.status.in_([BatchItemStatus.PENDING, BatchItemStatus.RUNNING]))
            .scalar()
            or 0
        )
        # No pending/running items, so adding more should be allowed
        assert pending_count == 0
        assert pending_count < settings.max_batch_size


class TestPendingItems:
    """Test the pending-items query logic used by the /batch/pending-items endpoint."""

    def test_returns_pending_items(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Backend Dev at Google", cv_text="test cv")
        db_session.commit()

        items = (
            db_session.query(BatchItem)
            .filter(BatchItem.batch_id == bid, BatchItem.status == BatchItemStatus.PENDING)
            .order_by(BatchItem.created_at.asc())
            .all()
        )
        assert len(items) == 1
        assert items[0].job_description == "Backend Dev at Google"

    def test_excludes_non_pending(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Job 1", cv_text="test cv")
        add_to_queue(db_session, test_cv.id, "Job 2", cv_text="test cv")
        db_session.commit()

        # Mark first item as DONE
        item = (
            db_session.query(BatchItem).filter(BatchItem.batch_id == bid, BatchItem.job_description == "Job 1").first()
        )
        item.status = BatchItemStatus.DONE
        db_session.commit()

        pending = (
            db_session.query(BatchItem)
            .filter(BatchItem.batch_id == bid, BatchItem.status == BatchItemStatus.PENDING)
            .all()
        )
        assert len(pending) == 1
        assert pending[0].job_description == "Job 2"

    def test_returns_empty_when_no_pending_batch(self, db_session):
        batch_id = get_pending_batch_id(db_session)
        assert batch_id is None

    def test_items_have_content_hash(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Some job", cv_text="test cv")
        db_session.commit()

        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        assert item.content_hash
        assert len(item.content_hash) == 64  # SHA-256 hex digest


class TestItemStatusUpdate:
    """Test updating a single batch item's status (as done by /batch/item/{id}/status)."""

    def test_update_status_to_done(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        db_session.commit()

        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.DONE
        item.attempt_count = (item.attempt_count or 0) + 1
        db_session.commit()

        refreshed = db_session.query(BatchItem).filter(BatchItem.id == item.id).first()
        assert refreshed.status == BatchItemStatus.DONE
        assert refreshed.attempt_count == 1

    def test_update_status_to_error_with_message(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        db_session.commit()

        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.ERROR
        item.error_message = "API timeout"
        item.attempt_count = (item.attempt_count or 0) + 1
        db_session.commit()

        refreshed = db_session.query(BatchItem).filter(BatchItem.id == item.id).first()
        assert refreshed.status == BatchItemStatus.ERROR
        assert refreshed.error_message == "API timeout"

    def test_update_status_sets_analysis_id(self, db_session, test_cv, test_analysis):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        db_session.commit()

        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.DONE
        item.analysis_id = test_analysis.id
        db_session.commit()

        refreshed = db_session.query(BatchItem).filter(BatchItem.id == item.id).first()
        assert refreshed.analysis_id == test_analysis.id

    def test_invalid_item_id_not_found(self, db_session):
        fake_id = uuid.uuid4()
        item = db_session.query(BatchItem).filter(BatchItem.id == fake_id).first()
        assert item is None


class TestBatchClear:
    """Test that batch_clear (via clear_completed) deletes everything."""

    def test_clears_all_items(self, db_session, test_cv):
        add_to_queue(db_session, test_cv.id, "Job 1", cv_text="test cv")
        add_to_queue(db_session, test_cv.id, "Job 2", cv_text="test cv")
        db_session.commit()

        # Mark one as done
        item = db_session.query(BatchItem).first()
        item.status = BatchItemStatus.DONE
        db_session.commit()

        assert db_session.query(BatchItem).count() == 2
        clear_completed(db_session)
        assert db_session.query(BatchItem).count() == 0

    def test_clear_on_empty_db(self, db_session):
        """Clearing when nothing exists should not error."""
        clear_completed(db_session)
        assert db_session.query(BatchItem).count() == 0

    def test_status_is_empty_after_clear(self, db_session, test_cv):
        add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        db_session.commit()
        clear_completed(db_session)
        status = get_batch_status(db_session)
        assert status["status"] == "empty"


class TestBatchSourcePropagation:
    """Source set on the batch entry must reach the resulting JobAnalysis.

    Until the fix, ``run_analysis`` always defaulted to ``manual`` when
    invoked from the batch executor. The dashboard widget
    "Da valutare — Cowork" filters on ``source=cowork``, so any
    Cowork-driven batch silently disappeared from that widget.
    """

    def test_default_source_is_manual(self, db_session, test_cv):
        """Direct UI submissions (no source param) must stay tagged manual."""
        add_to_queue(db_session, test_cv.id, "Cloud Engineer at Acme", cv_text="cv")
        db_session.commit()
        item = db_session.query(BatchItem).filter(BatchItem.job_description == "Cloud Engineer at Acme").one()
        assert item.source == "manual"

    def test_explicit_cowork_source_is_persisted(self, db_session, test_cv):
        """The MCP Cowork workflow passes ``source='cowork'`` — that must
        round-trip onto the batch row, ready to flow through to
        ``run_analysis`` later."""
        add_to_queue(db_session, test_cv.id, "DevOps at Initech", cv_text="cv", source="cowork")
        db_session.commit()
        item = db_session.query(BatchItem).filter(BatchItem.job_description == "DevOps at Initech").one()
        assert item.source == "cowork"

    def test_arbitrary_source_string_is_stored_at_service_layer(self, db_session, test_cv):
        """Service layer is permissive — the route-level whitelist is what
        guards against arbitrary strings reaching the column. Document the
        contract here so a future refactor doesn't accidentally tighten the
        service signature without also updating the route."""
        add_to_queue(db_session, test_cv.id, "Job from API", cv_text="cv", source="api")
        db_session.commit()
        item = db_session.query(BatchItem).filter(BatchItem.job_description == "Job from API").one()
        assert item.source == "api"
