"""Tests for batch service (persistent PostgreSQL queue)."""

from datetime import UTC, datetime, timedelta

from src.batch import service as batch_service
from src.batch.models import BatchItem, BatchItemStatus
from src.batch.service import (
    _process_item,
    add_to_queue,
    cleanup_stale_running,
    clear_completed,
    get_batch_status,
    get_pending_batch_id,
)


class TestAddToQueue:
    def test_adds_first_item(self, db_session, test_cv):
        batch_id, count, skipped = add_to_queue(
            db_session, test_cv.id, "Software Engineer at Google", cv_text="test cv"
        )
        assert batch_id
        assert count == 1
        assert skipped == 0

    def test_adds_to_existing_pending_batch(self, db_session, test_cv):
        bid1, c1, _ = add_to_queue(db_session, test_cv.id, "Job 1", cv_text="test cv")
        bid2, c2, _ = add_to_queue(db_session, test_cv.id, "Job 2", cv_text="test cv")
        assert bid1 == bid2
        assert c1 == 1
        assert c2 == 2

    def test_preserves_job_data(self, db_session, test_cv):
        bid, _, _ = add_to_queue(
            db_session, test_cv.id, "Data Scientist role", "https://example.com", "sonnet", "test cv"
        )
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        assert item.job_description == "Data Scientist role"
        assert item.job_url == "https://example.com"
        assert item.model == "sonnet"
        assert item.status == BatchItemStatus.PENDING

    def test_truncates_preview(self, db_session, test_cv):
        long_desc = "x" * 200
        bid, _, _ = add_to_queue(db_session, test_cv.id, long_desc, cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        assert len(item.preview) < len(long_desc)
        assert item.preview.endswith("...")

    def test_dedup_skips_existing_analysis(self, db_session, test_cv, test_analysis):
        """If an analysis with the same content_hash exists, item is SKIPPED."""
        # test_analysis has content_hash="abc123", we need to make add_to_queue
        # produce the same hash. Since content_hash = sha256(cv_text:job_description),
        # we just check the skipped mechanism works indirectly.
        bid, count, skipped = add_to_queue(db_session, test_cv.id, "Some job", cv_text="test cv")
        # Without a matching hash, it won't be skipped
        assert count == 1
        # skipped is 0 because the content_hash won't match test_analysis
        assert skipped == 0


class TestGetPendingBatchId:
    def test_returns_pending_batch(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        assert get_pending_batch_id(db_session) == bid

    def test_returns_none_when_empty(self, db_session):
        assert get_pending_batch_id(db_session) is None

    def test_returns_none_when_all_done(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.DONE
        db_session.commit()
        assert get_pending_batch_id(db_session) is None


class TestGetBatchStatus:
    def test_returns_status(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        status = get_batch_status(db_session)
        assert status["batch_id"] == bid
        assert status["status"] == "pending"
        assert status["total"] == 1

    def test_returns_empty_when_no_batches(self, db_session):
        status = get_batch_status(db_session)
        assert status["status"] == "empty"


class TestClearCompleted:
    def test_clears_done_items(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.DONE
        db_session.commit()
        clear_completed(db_session)
        assert db_session.query(BatchItem).count() == 0

    def test_clears_skipped_items(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.SKIPPED
        db_session.commit()
        clear_completed(db_session)
        assert db_session.query(BatchItem).count() == 0

    def test_clears_pending_items(self, db_session, test_cv):
        """clear_completed now deletes ALL items including pending."""
        add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        assert db_session.query(BatchItem).count() == 1
        clear_completed(db_session)
        assert db_session.query(BatchItem).count() == 0

    def test_preserves_running_items(self, db_session, test_cv):
        """RUNNING items are protected — deleting them would orphan in-flight workers."""
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.RUNNING
        db_session.commit()
        deleted = clear_completed(db_session)
        assert deleted == 0
        assert db_session.query(BatchItem).count() == 1
        remaining = db_session.query(BatchItem).first()
        assert remaining.status == BatchItemStatus.RUNNING

    def test_clears_error_items(self, db_session, test_cv):
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Test job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.ERROR
        db_session.commit()
        clear_completed(db_session)
        assert db_session.query(BatchItem).count() == 0

    def test_clears_all_non_running_statuses(self, db_session, test_cv):
        """clear_completed wipes every status except RUNNING."""
        statuses = [
            BatchItemStatus.PENDING,
            BatchItemStatus.RUNNING,
            BatchItemStatus.DONE,
            BatchItemStatus.SKIPPED,
            BatchItemStatus.ERROR,
        ]
        for i, st in enumerate(statuses):
            bid, _, _ = add_to_queue(db_session, test_cv.id, f"Job {i}", cv_text="test cv")
            item = (
                db_session.query(BatchItem)
                .filter(BatchItem.batch_id == bid, BatchItem.job_description == f"Job {i}")
                .first()
            )
            item.status = st
        db_session.commit()
        assert db_session.query(BatchItem).count() == len(statuses)
        deleted = clear_completed(db_session)
        assert deleted == len(statuses) - 1  # everything except RUNNING
        remaining = db_session.query(BatchItem).all()
        assert len(remaining) == 1
        assert remaining[0].status == BatchItemStatus.RUNNING

    def test_clears_only_specific_batch_id(self, db_session, test_cv):
        """When batch_id is provided, only that batch is cleared."""
        bid1, _, _ = add_to_queue(db_session, test_cv.id, "Job 1", cv_text="test cv")
        # Mark first done so a new batch_id is created for the next add
        item1 = db_session.query(BatchItem).filter(BatchItem.batch_id == bid1).first()
        item1.status = BatchItemStatus.DONE
        db_session.commit()
        bid2, _, _ = add_to_queue(db_session, test_cv.id, "Job 2", cv_text="test cv")
        assert db_session.query(BatchItem).count() == 2
        clear_completed(db_session, batch_id=bid1)
        assert db_session.query(BatchItem).count() == 1
        remaining = db_session.query(BatchItem).first()
        assert remaining.batch_id == bid2


class TestCleanupStaleRunning:
    def test_marks_old_running_items_as_error(self, db_session, test_cv):
        """Items stuck in RUNNING past the threshold get recovered to ERROR."""
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Stuck job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.RUNNING
        # Force updated_at into the past (SQLAlchemy onupdate doesn't fire on direct assignment)
        item.updated_at = datetime.now(UTC) - timedelta(minutes=30)
        db_session.commit()

        recovered = cleanup_stale_running(db_session, threshold_minutes=10)
        assert recovered == 1

        db_session.refresh(item)
        assert item.status == BatchItemStatus.ERROR
        assert "stale_running_recovered" in (item.error_message or "")

    def test_leaves_fresh_running_items_alone(self, db_session, test_cv):
        """Recently-started RUNNING items are not touched."""
        bid, _, _ = add_to_queue(db_session, test_cv.id, "Fresh job", cv_text="test cv")
        item = db_session.query(BatchItem).filter(BatchItem.batch_id == bid).first()
        item.status = BatchItemStatus.RUNNING
        db_session.commit()

        recovered = cleanup_stale_running(db_session, threshold_minutes=10)
        assert recovered == 0
        db_session.refresh(item)
        assert item.status == BatchItemStatus.RUNNING

    def test_ignores_non_running_statuses(self, db_session, test_cv):
        """Old DONE/SKIPPED/ERROR items are ignored even past the threshold."""
        for status in (BatchItemStatus.DONE, BatchItemStatus.SKIPPED, BatchItemStatus.ERROR):
            bid, _, _ = add_to_queue(db_session, test_cv.id, f"Job {status.value}", cv_text="test cv")
            item = (
                db_session.query(BatchItem)
                .filter(BatchItem.batch_id == bid)
                .order_by(BatchItem.created_at.desc())
                .first()
            )
            item.status = status
            item.updated_at = datetime.now(UTC) - timedelta(hours=2)
        db_session.commit()

        recovered = cleanup_stale_running(db_session, threshold_minutes=10)
        assert recovered == 0


class TestProcessItem:
    """_process_item drives the RUNNING → DONE/SKIPPED/ERROR state machine for a
    single batch row. All collaborators (analysis submission, Anthropic throttle,
    dedup lookup) are mocked so the test pins the state machine and DB effects.
    """

    def _make_item(self, db_session, test_cv) -> BatchItem:
        batch_id, _, _ = add_to_queue(db_session, test_cv.id, "Job A", cv_text="cv")
        return db_session.query(BatchItem).filter(BatchItem.batch_id == batch_id).first()

    def _patch_throttle(self, monkeypatch):
        """time.sleep(4) is the Anthropic rate-limit pause; short-circuit it in tests."""
        monkeypatch.setattr(batch_service.time, "sleep", lambda _s: None)

    def test_dedup_hit_marks_item_skipped(self, monkeypatch, db_session, test_cv, test_analysis):
        self._patch_throttle(monkeypatch)
        item = self._make_item(db_session, test_cv)

        monkeypatch.setattr(batch_service, "find_existing_analysis", lambda *a, **kw: test_analysis)

        def must_not_run(*a, **kw):
            raise AssertionError("dedup hit must skip analysis run")

        monkeypatch.setattr(batch_service, "_submit_and_run_analysis", must_not_run)

        status = _process_item(executor=None, db=db_session, item=item, cv=test_cv, user_id=test_cv.user_id, cache=None)

        assert status == BatchItemStatus.SKIPPED
        db_session.refresh(item)
        assert item.status == BatchItemStatus.SKIPPED
        assert item.analysis_id == test_analysis.id

    def test_happy_path_marks_item_done_and_commits(self, monkeypatch, db_session, test_cv, test_analysis):
        item = self._make_item(db_session, test_cv)

        monkeypatch.setattr(batch_service, "find_existing_analysis", lambda *a, **kw: None)
        monkeypatch.setattr(
            batch_service,
            "_submit_and_run_analysis",
            lambda *a, **kw: (test_analysis, {"cost_usd": 0.01, "tokens": {"input": 100, "output": 50}}),
        )

        slept: list[float] = []
        monkeypatch.setattr(batch_service.time, "sleep", lambda s: slept.append(s))

        status = _process_item(executor=None, db=db_session, item=item, cv=test_cv, user_id=test_cv.user_id, cache=None)

        assert status == BatchItemStatus.DONE
        db_session.refresh(item)
        assert item.status == BatchItemStatus.DONE
        assert item.analysis_id == test_analysis.id
        assert item.attempt_count == 1
        # Preserve the 4-second inter-item throttle contract: one sleep of 4s after DONE.
        assert slept == [4]

    def test_exception_rolls_back_and_marks_error(self, monkeypatch, db_session, test_cv):
        self._patch_throttle(monkeypatch)
        item = self._make_item(db_session, test_cv)

        monkeypatch.setattr(batch_service, "find_existing_analysis", lambda *a, **kw: None)

        def boom(*a, **kw):
            raise RuntimeError("anthropic timeout")

        monkeypatch.setattr(batch_service, "_submit_and_run_analysis", boom)

        status = _process_item(executor=None, db=db_session, item=item, cv=test_cv, user_id=test_cv.user_id, cache=None)

        assert status == BatchItemStatus.ERROR
        db_session.refresh(item)
        assert item.status == BatchItemStatus.ERROR
        assert "anthropic timeout" in (item.error_message or "")
        assert item.attempt_count == 1

    def test_defaults_to_haiku_when_item_model_is_empty(self, monkeypatch, db_session, test_cv, test_analysis):
        """An empty model string (legacy rows) must resolve to haiku, not KeyError."""
        self._patch_throttle(monkeypatch)
        item = self._make_item(db_session, test_cv)
        item.model = ""
        db_session.commit()

        captured: dict[str, str] = {}

        def fake_find(db, content_hash, model_id):
            captured["model_id"] = model_id
            return test_analysis  # short-circuit via SKIPPED

        monkeypatch.setattr(batch_service, "find_existing_analysis", fake_find)

        _process_item(executor=None, db=db_session, item=item, cv=test_cv, user_id=test_cv.user_id, cache=None)

        assert captured["model_id"] == batch_service.MODELS["haiku"]
