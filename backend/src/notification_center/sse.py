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
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..dependencies import AuthRequired

# Signature alias for the "is the peer gone?" probe that StreamingResponse
# exposes on Request — mocked in tests via a tiny callable.
IsDisconnected = Callable[[], Awaitable[bool]]

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
    n = len(_subscribers)
    # INFO (not debug) so Render logs show whether broadcasts actually fire
    # — essential to diagnose "SSE didn't trigger" reports from the field.
    logger.info("sse broadcast: event=%s subscribers=%d", event_name, n)
    for queue in list(_subscribers):
        try:
            queue.put_nowait(event_name)
        except asyncio.QueueFull:
            logger.warning("sse: queue full, dropping event %s", event_name)


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
        logger.info("sse broadcast_sync: dropped event=%s (no main loop captured — no tab connected yet)", event_name)
        return
    asyncio.run_coroutine_threadsafe(broadcast(event_name), _main_loop)


async def _event_stream(queue: asyncio.Queue[str], is_disconnected: IsDisconnected) -> AsyncIterator[str]:
    """SSE frame producer — extracted so tests can drive it without spinning
    up a full HTTP client. Yields the initial `hello` frame, then alternates
    event frames and keepalive comments until the peer disconnects."""
    try:
        yield "event: hello\ndata: connected\n\n"
        while True:
            if await is_disconnected():
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


@router.get("/sse")
async def notifications_stream(request: Request) -> StreamingResponse:
    """SSE stream. The client subscribes via ``EventSource`` and calls
    its existing fetchNotifications() when it receives any event.

    Auth is session-only on purpose: the regular ``CurrentUser`` dependency
    issues a DB query and keeps the Session open for the lifetime of the
    request. For a minute-long streaming response that means an idle
    PostgreSQL connection which eventually drops its SSL (Sentry issue
    7ee718f44d — "SSL connection has been closed unexpectedly" on /sse).
    Checking ``request.session`` only is cheap, in-memory, and enough
    gate for a push-only endpoint that never reads DB rows.
    """
    if not request.session.get("user_id"):
        raise AuthRequired()

    global _main_loop
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(queue)

    return StreamingResponse(
        _event_stream(queue, request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable Nginx/Render buffering
            "Connection": "keep-alive",
            # Chrome over Cloudflare's HTTP/3 (QUIC) aborts long-lived SSE
            # streams with ERR_QUIC_PROTOCOL_ERROR after a few frames. The
            # `Alt-Svc: clear` header tells the browser to forget any QUIC
            # alternative for this host on this response, so the next retry
            # falls back to HTTP/1.1/2 over TCP which handles streaming
            # reliably. Side effect (discarding Alt-Svc cache) is fine —
            # the browser just re-learns it on regular requests.
            "Alt-Svc": "clear",
        },
    )
