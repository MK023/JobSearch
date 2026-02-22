"""Tests for batch service."""

from src.batch.service import _batch_queue, add_to_queue, clear_completed, get_batch_status, get_pending_batch_id


def _clear_queue():
    """Reset the module-level batch queue between tests."""
    _batch_queue.clear()


class TestAddToQueue:
    def test_adds_first_item(self):
        _clear_queue()
        batch_id, count = add_to_queue("Software Engineer at Google")
        assert batch_id
        assert count == 1

    def test_adds_to_existing_pending_batch(self):
        _clear_queue()
        bid1, c1 = add_to_queue("Job 1")
        bid2, c2 = add_to_queue("Job 2")
        assert bid1 == bid2
        assert c1 == 1
        assert c2 == 2

    def test_preserves_job_data(self):
        _clear_queue()
        bid, _ = add_to_queue("Data Scientist role", "https://example.com", "sonnet")
        batch = _batch_queue[bid]
        item = batch["items"][0]
        assert item["job_description"] == "Data Scientist role"
        assert item["job_url"] == "https://example.com"
        assert item["model"] == "sonnet"
        assert item["status"] == "pending"

    def test_truncates_preview(self):
        _clear_queue()
        long_desc = "x" * 200
        bid, _ = add_to_queue(long_desc)
        item = _batch_queue[bid]["items"][0]
        assert len(item["preview"]) < len(long_desc)
        assert item["preview"].endswith("...")


class TestGetPendingBatchId:
    def test_returns_pending_batch(self):
        _clear_queue()
        bid, _ = add_to_queue("Test job")
        assert get_pending_batch_id() == bid

    def test_returns_none_when_empty(self):
        _clear_queue()
        assert get_pending_batch_id() is None

    def test_returns_none_when_all_done(self):
        _clear_queue()
        bid, _ = add_to_queue("Test job")
        _batch_queue[bid]["status"] = "done"
        assert get_pending_batch_id() is None


class TestGetBatchStatus:
    def test_returns_status(self):
        _clear_queue()
        bid, _ = add_to_queue("Test job")
        status = get_batch_status()
        assert status["batch_id"] == bid
        assert status["status"] == "pending"
        assert len(status["items"]) == 1

    def test_returns_empty_when_no_batches(self):
        _clear_queue()
        status = get_batch_status()
        assert status["status"] == "empty"


class TestClearCompleted:
    def test_clears_done_batches(self):
        _clear_queue()
        bid, _ = add_to_queue("Test job")
        _batch_queue[bid]["status"] = "done"
        clear_completed()
        assert len(_batch_queue) == 0

    def test_clears_pending_batches(self):
        _clear_queue()
        add_to_queue("Test job")
        clear_completed()
        assert len(_batch_queue) == 0

    def test_keeps_running_batches(self):
        _clear_queue()
        bid, _ = add_to_queue("Test job")
        _batch_queue[bid]["status"] = "running"
        clear_completed()
        assert len(_batch_queue) == 1
