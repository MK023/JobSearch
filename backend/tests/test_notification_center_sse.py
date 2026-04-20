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


@pytest.mark.asyncio
async def test_event_stream_emits_hello_then_event_then_cleans_up():
    """End-to-end of the generator: subscribe, feed one event, disconnect."""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
    sse._subscribers.add(q)
    calls = {"n": 0}

    async def is_disconnected() -> bool:
        # first call (before any event) → False so the loop enters;
        # second call (after event consumed) → True so the loop exits.
        calls["n"] += 1
        return calls["n"] >= 2

    stream = sse._event_stream(q, is_disconnected)

    hello = await stream.__anext__()
    assert hello.startswith("event: hello")

    q.put_nowait("analysis:new")
    event_frame = await stream.__anext__()
    assert "analysis:new" in event_frame

    # Next iteration — is_disconnected returns True → StopAsyncIteration.
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()

    # finally-block discard ran.
    assert q not in sse._subscribers


@pytest.mark.asyncio
async def test_event_stream_sends_keepalive_on_timeout(monkeypatch):
    """With no event queued and a short timeout, generator yields keepalive."""
    # 0.05s is long enough to avoid spurious event delivery but short enough
    # to keep the test snappy.
    monkeypatch.setattr(sse, "_HEARTBEAT_SECONDS", 0.05)
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=4)
    sse._subscribers.add(q)
    calls = {"n": 0}

    async def is_disconnected() -> bool:
        calls["n"] += 1
        # is_disconnected is only called once per loop iteration, not per
        # yield — so: False lets the loop time out once and emit keepalive,
        # then True breaks out on the next iteration.
        return calls["n"] >= 2

    stream = sse._event_stream(q, is_disconnected)

    await stream.__anext__()  # hello
    keepalive = await stream.__anext__()
    assert keepalive.startswith(": keepalive")

    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
