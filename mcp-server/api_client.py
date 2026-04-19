"""HTTP client for the JobSearch backend API with API key auth.

Includes retry logic with exponential backoff for transient failures.
"""

import asyncio
from typing import cast

import httpx

from config import settings

_client: httpx.AsyncClient | None = None

# Timeouts and retry config
_WAKE_TIMEOUT = 60.0  # generous timeout for cold start / health check
_NORMAL_TIMEOUT = 30.0  # regular API calls
_BATCH_TIMEOUT = 120.0  # batch operations that may take longer to start
_MAX_RETRIES = 3  # 4 total attempts (initial + 3 retries)
_RETRY_BASE_DELAY = 3.0  # exponential backoff: 3s, 6s, 12s


def _auth_headers() -> dict[str, str]:
    """Build authentication headers for API requests."""
    if settings.api_key:
        return {"X-API-Key": settings.api_key}
    return {}


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=_WAKE_TIMEOUT,
            headers=_auth_headers(),
            follow_redirects=False,
        )
    return _client


async def _request_with_retry(
    method: str,
    path: str,
    *,
    deadline: float | None = None,
    **kwargs: object,
) -> httpx.Response:
    """Execute an HTTP request with retry and exponential backoff.

    The per-request timeout is enforced via ``asyncio.timeout()`` instead of
    the httpx ``timeout=`` parameter (SonarCloud python:S7483); the shared
    client uses its own base timeout configured at construction time.

    Args:
        method: HTTP method (get, post, delete).
        path: API path.
        deadline: Optional per-request deadline in seconds (wraps the call
            with ``asyncio.timeout``). Falls back to the client-level timeout
            when ``None``.
        **kwargs: Extra keyword arguments forwarded to httpx.
    """
    client = await get_client()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with asyncio.timeout(deadline):
                resp = cast(httpx.Response, await getattr(client, method)(path, **kwargs))
            resp.raise_for_status()
            return resp

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, TimeoutError) as exc:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2**attempt)  # 3s, 6s, 12s
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(f"Backend unreachable after {_MAX_RETRIES + 1} attempts: {exc}") from exc

    raise RuntimeError("Unreachable: retry loop completed without return or raise")


async def api_get(path: str, params: dict | None = None, *, deadline: float | None = None) -> dict | list:
    """Make an authenticated GET request to the backend API.

    Args:
        path: API path.
        params: Optional query parameters.
        deadline: Optional per-request deadline in seconds (asyncio.timeout).
    """
    resp = await _request_with_retry("get", path, deadline=deadline, params=params)
    return cast("dict | list", resp.json())


async def api_post(path: str, data: dict | None = None, *, deadline: float | None = None) -> dict | list:
    """Make an authenticated POST request to the backend API.

    Args:
        path: API path.
        data: Optional request body.
        deadline: Optional per-request deadline in seconds (asyncio.timeout).
    """
    resp = await _request_with_retry("post", path, deadline=deadline, data=data)
    return cast("dict | list", resp.json())


async def api_post_json(path: str, payload: dict, *, deadline: float | None = None) -> dict | list:
    """Make an authenticated POST request with JSON body.

    Args:
        path: API path.
        payload: JSON request body.
        deadline: Optional per-request deadline in seconds (asyncio.timeout).
    """
    resp = await _request_with_retry("post", path, deadline=deadline, json=payload)
    return cast("dict | list", resp.json())


async def api_delete(path: str, *, deadline: float | None = None) -> dict | list:
    """Make an authenticated DELETE request to the backend API.

    Args:
        path: API path.
        deadline: Optional per-request deadline in seconds (asyncio.timeout).
    """
    resp = await _request_with_retry("delete", path, deadline=deadline)
    return cast("dict | list", resp.json())


async def close_client() -> None:
    """Close the HTTP client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None
