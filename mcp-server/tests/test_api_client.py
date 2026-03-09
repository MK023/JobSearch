"""Tests for the API client — login flow and error handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import api_client
import httpx
import pytest
from api_client import _login, api_get, close_client


@pytest.fixture(autouse=True)
async def cleanup():
    """Reset client state between tests."""
    api_client._session_cookie = None
    api_client._client = None
    yield
    await close_client()


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_extracts_session_cookie(self):
        mock_response = MagicMock()
        mock_response.status_code = 303
        mock_response.cookies = httpx.Cookies()
        mock_response.cookies.set("session", "test-session-value")

        with patch("api_client.get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_gc.return_value = mock_client

            cookie = await _login()
            assert cookie == "test-session-value"

    @pytest.mark.asyncio
    async def test_login_raises_on_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.cookies = httpx.Cookies()

        with patch("api_client.get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_gc.return_value = mock_client

            with pytest.raises(RuntimeError, match="Login failed"):
                await _login()


class TestApiGet:
    @pytest.mark.asyncio
    async def test_calls_with_session_cookie(self):
        # Force-reset global state
        api_client._session_cookie = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = MagicMock()

        login_response = MagicMock()
        login_response.status_code = 303
        login_response.cookies = httpx.Cookies()
        login_response.cookies.set("session", "fresh-session")

        mock_client = AsyncMock()
        mock_client.post.return_value = login_response
        mock_client.get.return_value = mock_response
        mock_client.is_closed = False

        with patch("api_client.get_client", new_callable=AsyncMock, return_value=mock_client):
            result = await api_get("/api/v1/dashboard")
            assert result == {"data": "test"}
            # Login should have been called, then the GET with the new session
            mock_client.post.assert_called_once()
            mock_client.get.assert_called_with(
                "/api/v1/dashboard",
                params=None,
                cookies={"session": "fresh-session"},
            )
