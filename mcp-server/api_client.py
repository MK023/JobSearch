"""HTTP client for the JobSearch backend API with session-based auth.

Handles Fly.io cold starts with retry logic — the backend may take
10-15s to wake from sleep on the free tier.
"""

import asyncio

import httpx

from config import settings

_client: httpx.AsyncClient | None = None
_session_cookie: str | None = None

# Fly.io free tier: machine sleeps after inactivity, first request may timeout
_WAKE_TIMEOUT = 60.0  # generous timeout for cold start
_NORMAL_TIMEOUT = 30.0
_MAX_RETRIES = 2
_RETRY_DELAY = 3.0


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=_WAKE_TIMEOUT,
            follow_redirects=False,
        )
    return _client


async def _login() -> str:
    """Authenticate against the backend and return session cookie."""
    global _session_cookie
    client = await get_client()

    resp = await client.post(
        "/login",
        data={"email": settings.backend_email, "password": settings.backend_password},
        follow_redirects=False,
    )

    cookie = resp.cookies.get("session")
    if not cookie and resp.status_code in (302, 303):
        cookie = resp.cookies.get("session")

    if not cookie:
        raise RuntimeError(f"Login failed: status={resp.status_code}")

    _session_cookie = cookie
    return cookie


async def _ensure_auth() -> None:
    """Ensure we have a valid session cookie."""
    if not _session_cookie:
        await _login()


def _is_auth_failure(resp: httpx.Response) -> bool:
    """Check if response indicates session expiry."""
    return resp.status_code in (401, 403) or (resp.status_code == 303 and "/login" in resp.headers.get("location", ""))


async def _request_with_retry(method: str, path: str, **kwargs) -> httpx.Response:
    """Execute an HTTP request with retry for Fly.io cold starts."""
    client = await get_client()
    await _ensure_auth()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await getattr(client, method)(path, cookies={"session": _session_cookie}, **kwargs)

            if _is_auth_failure(resp):
                await _login()
                resp = await getattr(client, method)(path, cookies={"session": _session_cookie}, **kwargs)

            resp.raise_for_status()
            return resp

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY)
                continue
            raise RuntimeError(
                f"Backend unreachable after {_MAX_RETRIES + 1} attempts " f"(Fly.io may be sleeping): {exc}"
            ) from exc

    raise RuntimeError("Unreachable: retry loop completed without return or raise")


async def api_get(path: str, params: dict | None = None) -> dict | list:
    """Make an authenticated GET request to the backend API."""
    resp = await _request_with_retry("get", path, params=params)
    return resp.json()


async def api_post(path: str, data: dict | None = None) -> dict | list:
    """Make an authenticated POST request to the backend API."""
    resp = await _request_with_retry("post", path, data=data)
    return resp.json()


async def api_delete(path: str) -> dict | list:
    """Make an authenticated DELETE request to the backend API."""
    resp = await _request_with_retry("delete", path)
    return resp.json()


async def close_client() -> None:
    """Close the HTTP client."""
    global _client, _session_cookie
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None
    _session_cookie = None
