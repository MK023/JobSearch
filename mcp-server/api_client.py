"""HTTP client for the JobSearch backend API with API key auth.

Handles Fly.io cold starts with retry logic — the backend may take
10-15s to wake from sleep on the free tier.
"""

import asyncio

import httpx

from config import settings

_client: httpx.AsyncClient | None = None

# Fly.io free tier: machine sleeps after inactivity, first request may timeout
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


async def _request_with_retry(method: str, path: str, *, timeout: float | None = None, **kwargs) -> httpx.Response:
    """Execute an HTTP request with retry and exponential backoff for Fly.io cold starts.

    Args:
        method: HTTP method (get, post, delete).
        path: API path.
        timeout: Optional per-request timeout override (seconds).
        **kwargs: Extra keyword arguments forwarded to httpx.
    """
    client = await get_client()

    req_timeout = httpx.Timeout(timeout) if timeout else None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await getattr(client, method)(path, timeout=req_timeout, **kwargs)
            resp.raise_for_status()
            return resp

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2**attempt)  # 3s, 6s, 12s
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(
                f"Backend unreachable after {_MAX_RETRIES + 1} attempts " f"(Fly.io may be sleeping): {exc}"
            ) from exc

    raise RuntimeError("Unreachable: retry loop completed without return or raise")


async def api_get(path: str, params: dict | None = None, *, timeout: float | None = None) -> dict | list:
    """Make an authenticated GET request to the backend API.

    Args:
        path: API path.
        params: Optional query parameters.
        timeout: Optional timeout override in seconds.
    """
    resp = await _request_with_retry("get", path, timeout=timeout, params=params)
    return resp.json()


async def api_post(path: str, data: dict | None = None, *, timeout: float | None = None) -> dict | list:
    """Make an authenticated POST request to the backend API.

    Args:
        path: API path.
        data: Optional request body.
        timeout: Optional timeout override in seconds.
    """
    resp = await _request_with_retry("post", path, timeout=timeout, data=data)
    return resp.json()


async def api_post_json(path: str, payload: dict, *, timeout: float | None = None) -> dict | list:
    """Make an authenticated POST request with JSON body.

    Args:
        path: API path.
        payload: JSON request body.
        timeout: Optional timeout override in seconds.
    """
    resp = await _request_with_retry("post", path, timeout=timeout, json=payload)
    return resp.json()


async def api_delete(path: str, *, timeout: float | None = None) -> dict | list:
    """Make an authenticated DELETE request to the backend API.

    Args:
        path: API path.
        timeout: Optional timeout override in seconds.
    """
    resp = await _request_with_retry("delete", path, timeout=timeout)
    return resp.json()


async def close_client() -> None:
    """Close the HTTP client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None
