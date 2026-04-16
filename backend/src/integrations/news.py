"""Real-Time News Data integration via RapidAPI.

Provides recent company news with DB-level caching (7 days).
Graceful degradation: returns None on missing API key, errors, or no data.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from ..config import settings
from ..database.base import Base

logger = logging.getLogger(__name__)

CACHE_DAYS = 7
RAPIDAPI_HOST = "real-time-news-data.p.rapidapi.com"
SEARCH_URL = f"https://{RAPIDAPI_HOST}/search"


class NewsCache(Base):
    """DB-level cache for company news (7-day TTL)."""

    __tablename__ = "news_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), unique=True, index=True, nullable=False)
    news_data = Column(Text, default="")
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def _call_api(query: str, limit: int = 5) -> list[dict[str, Any]] | None:
    """Call the Real-Time News Data API. Returns parsed data list or None."""
    if not settings.rapidapi_key:
        return None

    try:
        resp = httpx.get(
            SEARCH_URL,
            headers={
                "X-RapidAPI-Key": settings.rapidapi_key,
                "X-RapidAPI-Host": RAPIDAPI_HOST,
            },
            params={
                "query": query,
                "limit": str(limit),
                "time_published": "7d",
                "country": "IT",
                "lang": "it",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", [])
        return data if isinstance(data, list) else None
    except Exception:
        logger.warning("News API call failed for %r", query, exc_info=True)
        return None


def _parse_article(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a news article into a clean dict."""
    return {
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "snippet": item.get("snippet", ""),
        "published_at": item.get("published_datetime_utc", ""),
        "source_name": item.get("source_name", ""),
        "source_url": item.get("source_url", ""),
        "photo_url": item.get("photo_url", ""),
    }


def fetch_company_news(
    company_name: str,
    db: Session | None = None,
) -> list[dict[str, Any]] | None:
    """Fetch recent news for a company. Uses DB cache with 7-day TTL."""
    if not company_name or not settings.rapidapi_key:
        return None

    name_norm = company_name.strip().lower()

    # Check cache
    if db is not None:
        try:
            cached = db.query(NewsCache).filter(NewsCache.company_name == name_norm).first()
            if cached and cached.fetched_at:
                age = datetime.now(UTC) - cached.fetched_at.replace(tzinfo=UTC)
                if age < timedelta(days=CACHE_DAYS) and cached.news_data:
                    return json.loads(cached.news_data)
        except Exception:  # noqa: S110 — cache miss is non-fatal
            pass

    data = _call_api(company_name, limit=5)
    if not data:
        return None

    articles = [_parse_article(a) for a in data[:5]]

    # Update cache
    if db is not None:
        try:
            cached = db.query(NewsCache).filter(NewsCache.company_name == name_norm).first()
            if cached:
                cached.news_data = json.dumps(articles)
                cached.fetched_at = datetime.now(UTC)
            else:
                db.add(NewsCache(company_name=name_norm, news_data=json.dumps(articles)))
            db.flush()
        except Exception:
            logger.warning("Failed to cache news data", exc_info=True)

    return articles
