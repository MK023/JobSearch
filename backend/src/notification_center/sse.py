"""Server-Sent Events push for notification refresh signals.

The client already polls `/api/v1/notifications` every 30s (see
frontend/static/js/modules/notifications.js). This endpoint lets the
server nudge the client to refetch *immediately* when something
relevant happens (new analysis landed, inbox item processed, etc.)
without raising polling frequency across the board.

Design choice — signals only, not state. The stream pushes tiny
event names like "analysis:new"; the client reacts by calling its
existing fetch function. Streaming full notification state would
force JS/server to agree on a diff format and would diverge quickly
from the polling-rendered DOM.

Single-worker assumption: the subscriber set lives in this process.
On Render free tier JobSearch runs one Uvicorn worker, so a single
broadcaster reaches every connected tab. Multi-worker deployments
would need Redis pub/sub or Postgres LISTEN — not added here to keep
the footprint minimal.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..dependencies import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications-sse"])

# Per-process queue registry. Each connected tab owns one bounded queue
# — bounded so a stuck client can't grow memory unbounded; full queues
# drop new events (the client's next poll/fetch still picks them up).
_QUEUE_MAX = 16
_subscribers: set[asyncio.Queue[str]] = set()
_HEARTBEAT_SECONDS = 15

# Reference to the main event loop, captured at first SSE connect.
# Sync route handlers run on FastAPI's thread pool where there's no
# running loop, so we need an explicit reference to schedule coroutines
# back onto the async side.
_main_loop: asyncio.AbstractEventLoop | None = None


async def broadcast(event_name: str) -> None:
    """Push ``event_name`` to every connected SSE subscriber (fire-and-forget).

    Safe to call from any async code path; sync code should use
    :func:`broadcast_sync` instead.
    """
    for queue in list(_subscribers):
        try:
            queue.put_nowait(event_name)
        except asyncio.QueueFull:
            logger.debug("sse: queue full, dropping event %s", event_name)


def broadcast_sync(event_name: str) -> None:
    """Schedule a broadcast from synchronous code.

    FastAPI's sync ``def`` handlers run on a thread pool with no running
    loop, so we can't call ``broadcast`` directly — we need a handle
    to the main loop that owns the subscriber queues. That reference is
    captured lazily the first time an SSE connection opens. If nothing
    is subscribed yet (no tab open), there's nothing to deliver and this
    is a silent no-op, which is the correct behavior.
    """
    if _main_loop is None:
        return
    asyncio.run_coroutine_threadsafe(broadcast(event_name), _main_loop)


@router.get("/sse")
async def notifications_stream(request: Request, user: CurrentUser) -> StreamingResponse:
    """SSE stream. The client subscribes via ``EventSource`` and calls
    its existing fetchNotifications() when it receives any event.

    Auth piggybacks on the standard cookie session — CurrentUser raises
    AuthRequired for anonymous callers, handled by the global handler.
    """
    del user  # auth side effect only

    global _main_loop
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(queue)

    async def event_generator() -> AsyncIterator[str]:
        try:
            yield "event: hello\ndata: connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                    yield f"event: {event}\ndata: {event}\n\n"
                except TimeoutError:
                    # Comment line keeps the connection alive through
                    # proxies/load balancers that close idle streams.
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable Nginx/Render buffering
            "Connection": "keep-alive",
        },
    )
