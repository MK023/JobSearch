"""Tests for MCP server tools — mock the backend API calls."""

from unittest.mock import AsyncMock, patch

import pytest
from server import (
    get_activity_summary,
    get_candidature,
    get_candidature_by_date_range,
    get_candidature_detail,
    get_cover_letter,
    get_dashboard_stats,
    get_interview_prep,
    get_pending_followups,
    get_spending,
    get_stale_candidature,
    get_top_candidature,
    get_upcoming_interviews,
    search_candidature,
    search_contacts,
)


@pytest.fixture(autouse=True)
def mock_api():
    """Mock api_get for all tests."""
    with patch("server.api_get", new_callable=AsyncMock) as mock:
        mock.return_value = {"ok": True}
        yield mock


class TestCandidatureTools:
    @pytest.mark.asyncio
    async def test_get_candidature_no_filter(self, mock_api):
        result = await get_candidature()
        mock_api.assert_called_once_with("/api/v1/candidature", {"limit": 50})
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_get_candidature_with_status(self, mock_api):
        await get_candidature(status="candidato", limit=10)
        mock_api.assert_called_once_with("/api/v1/candidature", {"limit": 10, "status": "candidato"})

    @pytest.mark.asyncio
    async def test_search_candidature(self, mock_api):
        await search_candidature(query="google")
        mock_api.assert_called_once_with("/api/v1/candidature/search", {"q": "google", "limit": 20})

    @pytest.mark.asyncio
    async def test_get_candidature_detail(self, mock_api):
        await get_candidature_detail(analysis_id="abc-123")
        mock_api.assert_called_once_with("/api/v1/candidature/abc-123")

    @pytest.mark.asyncio
    async def test_get_top_candidature(self, mock_api):
        await get_top_candidature(limit=5)
        mock_api.assert_called_once_with("/api/v1/candidature/top", {"limit": 5})

    @pytest.mark.asyncio
    async def test_get_candidature_by_date_range(self, mock_api):
        await get_candidature_by_date_range(date_from="2026-01-01", date_to="2026-03-09")
        mock_api.assert_called_once_with(
            "/api/v1/candidature/date-range", {"date_from": "2026-01-01", "date_to": "2026-03-09"}
        )

    @pytest.mark.asyncio
    async def test_get_stale_candidature(self, mock_api):
        await get_stale_candidature(days=14)
        mock_api.assert_called_once_with("/api/v1/candidature/stale", {"days": 14})


class TestInterviewTools:
    @pytest.mark.asyncio
    async def test_get_upcoming_interviews(self, mock_api):
        await get_upcoming_interviews(days=3)
        mock_api.assert_called_once_with("/api/v1/interviews-upcoming", {"days": 3})

    @pytest.mark.asyncio
    async def test_get_interview_prep(self, mock_api):
        await get_interview_prep(analysis_id="abc-123")
        mock_api.assert_called_once_with("/api/v1/interview-prep/abc-123")


class TestCoverLetterTools:
    @pytest.mark.asyncio
    async def test_get_cover_letter(self, mock_api):
        await get_cover_letter(analysis_id="abc-123")
        mock_api.assert_called_once_with("/api/v1/cover-letters/abc-123")


class TestContactTools:
    @pytest.mark.asyncio
    async def test_search_contacts(self, mock_api):
        await search_contacts(query="marco")
        mock_api.assert_called_once_with("/api/v1/contacts/search", {"q": "marco", "limit": 20})


class TestDashboardTools:
    @pytest.mark.asyncio
    async def test_get_dashboard_stats(self, mock_api):
        await get_dashboard_stats()
        mock_api.assert_called_once_with("/api/v1/dashboard")

    @pytest.mark.asyncio
    async def test_get_spending(self, mock_api):
        await get_spending()
        mock_api.assert_called_once_with("/api/v1/spending")

    @pytest.mark.asyncio
    async def test_get_pending_followups(self, mock_api):
        await get_pending_followups()
        mock_api.assert_called_once_with("/api/v1/followups/pending")

    @pytest.mark.asyncio
    async def test_get_activity_summary(self, mock_api):
        await get_activity_summary(days=30)
        mock_api.assert_called_once_with("/api/v1/activity-summary", {"days": 30})
