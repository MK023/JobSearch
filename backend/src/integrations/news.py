"""Real-Time News Data integration via RapidAPI.

Provides recent company news with DB-level caching (7 days).
Graceful degradation: returns None on missing API key, errors, or no data.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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


def _load_cached_row(db: Session, name_norm: str) -> NewsCache | None:
    """Return the NewsCache row for this company, or None on query errors."""
    try:
        return db.query(NewsCache).filter(NewsCache.company_name == name_norm).first()
    except Exception:  # pragma: no cover — cache miss is non-fatal
        logger.warning("News cache lookup failed for %r", name_norm, exc_info=True)
        return None


def _cached_articles_if_fresh(cached: NewsCache | None) -> list[dict[str, Any]] | None:
    """Return cached articles if the row is present AND within TTL; else None."""
    if not cached or not cached.fetched_at or not cached.news_data:
        return None
    age = datetime.now(UTC) - cached.fetched_at.replace(tzinfo=UTC)
    if age >= timedelta(days=CACHE_DAYS):
        return None
    try:
        return cast(list[dict[str, Any]], json.loads(str(cached.news_data)))
    except Exception:
        return None


def _upsert_cache(db: Session, name_norm: str, cached: NewsCache | None, articles: list[dict[str, Any]]) -> None:
    """Persist the freshly-fetched articles to the DB cache. Best-effort."""
    try:
        if cached:
            cached.news_data = json.dumps(articles)  # type: ignore[assignment]
            cached.fetched_at = datetime.now(UTC)  # type: ignore[assignment]
        else:
            db.add(NewsCache(company_name=name_norm, news_data=json.dumps(articles)))
        db.flush()
    except Exception:
        logger.warning("Failed to cache news data", exc_info=True)


def fetch_company_news(
    company_name: str,
    db: Session | None = None,
) -> list[dict[str, Any]] | None:
    """Fetch recent news for a company. DB cache 7-day TTL."""
    if not company_name or not settings.rapidapi_key:
        return None

    name_norm = company_name.strip().lower()
    cached = _load_cached_row(db, name_norm) if db is not None else None

    fresh = _cached_articles_if_fresh(cached)
    if fresh is not None:
        return fresh

    data = _call_api(company_name, limit=5)
    if not data:
        return None

    articles = [_parse_article(a) for a in data[:5]]

    if db is not None:
        _upsert_cache(db, name_norm, cached, articles)

    return articles


def get_cached_news(company_names: list[str], db: Session) -> list[dict[str, Any]]:
    """Read news from DB cache only — no API calls. Fast for page rendering.

    Single IN-query instead of one per company (fixes N+1 reported by Sentry).
    """
    if not company_names:
        return []

    # Normalize once, build a lookup map to preserve original casing in output
    by_norm = {name.strip().lower(): name for name in company_names}
    try:
        rows = db.query(NewsCache).filter(NewsCache.company_name.in_(list(by_norm.keys()))).all()
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for row in rows:
        if not row.news_data:
            continue
        try:
            articles = cast(list[dict[str, Any]], json.loads(str(row.news_data)))
        except Exception:  # noqa: S112
            continue
        if articles:
            original = by_norm.get(str(row.company_name), str(row.company_name))
            results.append({"company": original, "articles": articles})
    return results
