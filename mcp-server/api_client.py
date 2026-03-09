"""HTTP client for the JobSearch backend API with session-based auth."""

import httpx

from config import settings

_client: httpx.AsyncClient | None = None
_session_cookie: str | None = None


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.backend_url,
            timeout=30.0,
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
        # Session cookie set on redirect
        cookie = resp.cookies.get("session")

    if not cookie:
        raise RuntimeError(f"Login failed: status={resp.status_code}")

    _session_cookie = cookie
    return cookie


async def api_get(path: str, params: dict | None = None) -> dict | list:
    """Make an authenticated GET request to the backend API.

    Handles automatic login and session refresh on 401/403.
    """
    global _session_cookie
    client = await get_client()

    if not _session_cookie:
        await _login()

    resp = await client.get(
        path,
        params=params,
        cookies={"session": _session_cookie},
    )

    # Re-authenticate on session expiry
    if resp.status_code in (401, 403) or (resp.status_code == 303 and "/login" in resp.headers.get("location", "")):
        await _login()
        resp = await client.get(
            path,
            params=params,
            cookies={"session": _session_cookie},
        )

    resp.raise_for_status()
    return resp.json()


async def close_client() -> None:
    """Close the HTTP client."""
    global _client, _session_cookie
    if _client and not _client.is_closed:
        await _client.aclose()
    _client = None
    _session_cookie = None
