"""Tests for the SSE broadcast helpers.

The streaming endpoint itself is hard to exercise inside a plain
pytest-asyncio test (TestClient doesn't play well with long-lived
StreamingResponse), so we cover the broadcaster primitives here. A
smoke integration test for the route is the next step.
"""

from __future__ import annotations

import asyncio

import pytest

from src.notification_center import sse


@pytest.fixture(autouse=True)
def _isolate_subscribers():
    """Reset module-level state so tests don't bleed into each other."""
    sse._subscribers.clear()
    sse._main_loop = None
    yield
    sse._subscribers.clear()
    sse._main_loop = None


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_subscribers():
    q1: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
    q2: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
    sse._subscribers.update({q1, q2})

    await sse.broadcast("analysis:new")

    assert q1.get_nowait() == "analysis:new"
    assert q2.get_nowait() == "analysis:new"


@pytest.mark.asyncio
async def test_broadcast_silently_drops_when_queue_full():
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    q.put_nowait("filler")  # now full
    sse._subscribers.add(q)

    # Must not raise — the stuck client's next fetch picks up state anyway.
    await sse.broadcast("analysis:new")
    assert q.qsize() == 1


def test_broadcast_sync_no_op_when_no_loop():
    # _main_loop is None until the first SSE connect populates it. Sync
    # callers before any tab subscribes should be silent no-ops.
    sse._main_loop = None
    sse.broadcast_sync("analysis:new")  # must not raise


@pytest.mark.asyncio
async def test_broadcast_sync_schedules_on_captured_loop():
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
    sse._subscribers.add(q)
    sse._main_loop = asyncio.get_running_loop()

    sse.broadcast_sync("analysis:new")

    # run_coroutine_threadsafe returns a concurrent.futures.Future; give
    # the loop a tick to actually run the coroutine.
    await asyncio.sleep(0.05)
    assert q.get_nowait() == "analysis:new"
