"""Glassdoor company data integration via RapidAPI (company-data12).

Provides company reputation data with DB-level caching (30 days).
Graceful degradation: returns None on missing API key, errors, or no match.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from ..config import settings
from ..database.base import Base

CACHE_DAYS = 30
RAPIDAPI_HOST = "company-data12.p.rapidapi.com"
SEARCH_URL = f"https://{RAPIDAPI_HOST}/company-search"


class GlassdoorCache(Base):
    __tablename__ = "glassdoor_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), unique=True, index=True, nullable=False)
    glassdoor_data = Column(Text, default="")
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, nullable=True)
    fetched_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


def fetch_glassdoor_rating(company_name: str, db: Session) -> dict | None:
    """Fetch Glassdoor rating for a company using DB cache.

    Returns a dict with rating data, or None if unavailable.
    """
    if not company_name or not company_name.strip():
        return None

    if not settings.rapidapi_key:
        return None

    normalized = company_name.lower().strip()

    cached = db.query(GlassdoorCache).filter(GlassdoorCache.company_name == normalized).first()
    if cached and cached.fetched_at:
        age = datetime.now(UTC) - cached.fetched_at
        if age < timedelta(days=CACHE_DAYS):
            return _parse_cached(cached)

    try:
        data = _call_api(company_name.strip())
        if data is None:
            return None

        company = _best_match(data, company_name.strip())
        if company is None:
            return None

        parsed = _parse_company(company)

        if cached:
            cached.glassdoor_data = json.dumps(company, ensure_ascii=False)
            cached.rating = parsed.get("glassdoor_rating")
            cached.review_count = parsed.get("review_count")
            cached.fetched_at = datetime.now(UTC)
        else:
            cached = GlassdoorCache(
                company_name=normalized,
                glassdoor_data=json.dumps(company, ensure_ascii=False),
                rating=parsed.get("glassdoor_rating"),
                review_count=parsed.get("review_count"),
            )
            db.add(cached)
        db.flush()
        parsed["cached"] = False
        return parsed

    except Exception:
        return None


def _call_api(query: str) -> dict | None:
    """Call company-data12 company-search endpoint."""
    try:
        response = httpx.get(
            SEARCH_URL,
            params={"query": query, "limit": 5},
            headers={
                "X-RapidAPI-Key": settings.rapidapi_key,
                "X-RapidAPI-Host": RAPIDAPI_HOST,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError:
        return None
    except Exception:
        return None


def _best_match(data: dict, query: str) -> dict | None:
    """Pick the best matching company from API results.

    Requires at least 3 reviews for reliability.
    """
    if data.get("status") != "OK":
        return None
    results = data.get("data", [])
    if not results:
        return None

    q = query.lower().strip()
    min_reviews = 3

    for r in results:
        name = (r.get("name") or "").lower().strip()
        if name == q and r.get("rating") and (r.get("review_count") or 0) >= min_reviews:
            return r

    for r in results:
        name = (r.get("name") or "").lower().strip()
        if (
            (name.startswith(q) or q.startswith(name))
            and r.get("rating")
            and (r.get("review_count") or 0) >= min_reviews
        ):
            return r

    for r in results:
        name = (r.get("name") or "").lower().strip()
        if q in name and r.get("rating") and (r.get("review_count") or 0) >= min_reviews:
            return r

    return None


def _parse_company(c: dict) -> dict:
    """Parse a company-data12 company object into our standard format."""
    rating = float(c.get("rating", 0))
    review_count = int(c.get("review_count", 0))

    sub_ratings = {}
    rating_map = {
        "culture_and_values_rating": "culture",
        "compensation_and_benefits_rating": "compensation",
        "work_life_balance_rating": "work_life_balance",
        "career_opportunities_rating": "career_opportunities",
        "senior_management_rating": "senior_management",
        "diversity_and_inclusion_rating": "diversity",
    }
    for api_key, our_key in rating_map.items():
        val = c.get(api_key)
        if val and float(val) > 0:
            sub_ratings[our_key] = round(float(val), 1)

    ceo_name = c.get("ceo") or ""
    ceo_rating = c.get("ceo_rating")
    ceo_approval = round(float(ceo_rating) * 100) if ceo_rating and float(ceo_rating) > 0 else None

    company_name_slug = (c.get("name") or "").replace(" ", "-")
    company_id = c.get("company_id", "")
    glassdoor_url = (
        f"https://www.glassdoor.com/Overview/Working-at-{company_name_slug}-EI_IE{company_id}.htm" if company_id else ""
    )

    return {
        "glassdoor_rating": rating,
        "glassdoor_url": glassdoor_url,
        "review_count": review_count,
        "sub_ratings": sub_ratings,
        "ceo_name": ceo_name,
        "ceo_approval": ceo_approval,
        "recommend_to_friend": (
            round(float(c["recommend_to_friend_rating"]) * 100) if c.get("recommend_to_friend_rating") else None
        ),
        "business_outlook": (
            round(float(c["business_outlook_rating"]) * 100) if c.get("business_outlook_rating") else None
        ),
        "industry": c.get("industry") or "",
        "company_size": c.get("company_size") or "",
        "source": "glassdoor_api",
        "cached": False,
    }


def _parse_cached(cached: GlassdoorCache) -> dict | None:
    """Build result dict from cached DB record."""
    try:
        company = json.loads(cached.glassdoor_data) if cached.glassdoor_data else {}
    except (json.JSONDecodeError, TypeError):
        company = {}

    if company:
        parsed = _parse_company(company)
        parsed["cached"] = True
        return parsed

    if cached.rating:
        return {
            "glassdoor_rating": cached.rating,
            "glassdoor_url": "",
            "review_count": cached.review_count or 0,
            "sub_ratings": {},
            "ceo_name": "",
            "ceo_approval": None,
            "recommend_to_friend": None,
            "business_outlook": None,
            "industry": "",
            "company_size": "",
            "source": "glassdoor_api",
            "cached": True,
        }
    return None
