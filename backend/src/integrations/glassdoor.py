"""Glassdoor company data integration via RapidAPI (company-data12).

Provides company reputation data with DB-level caching (30 days).
Graceful degradation: returns None on missing API key, errors, or no match.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from ..config import settings
from ..database.base import Base

if TYPE_CHECKING:
    from .cache import CacheService

CACHE_DAYS = 30
RAPIDAPI_HOST = "company-data12.p.rapidapi.com"
SEARCH_URL = f"https://{RAPIDAPI_HOST}/company-search"


class GlassdoorCache(Base):
    """DB-level cache for Glassdoor company data (30-day TTL)."""

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


def _lookup_redis_cache(cache: "CacheService | None", cache_key: str) -> dict[str, Any] | None:
    """Tier-1 cache lookup (Redis). Returns a parsed result or None."""
    if cache is None:
        return None
    cached_redis = cache.get_json(cache_key)
    if not cached_redis:
        return None
    cached_redis["cached"] = True
    return cast(dict[str, Any], cached_redis)


def _lookup_db_cache(
    db: Session,
    normalized: str,
    cache: "CacheService | None",
    cache_key: str,
) -> dict[str, Any] | None:
    """Tier-2 cache lookup (DB, 30-day TTL). Returns a parsed result or None."""
    cached = db.query(GlassdoorCache).filter(GlassdoorCache.company_name == normalized).first()
    if not cached or not cached.fetched_at:
        return None
    age = datetime.now(UTC) - cached.fetched_at
    if age >= timedelta(days=CACHE_DAYS):
        return None
    parsed = _parse_cached(cached)
    if parsed and cache is not None:
        cache.set_json(cache_key, parsed, 3600)  # 1h Redis TTL
    return parsed


def _persist_glassdoor_cache(
    db: Session,
    normalized: str,
    company: dict[str, Any],
    parsed: dict[str, Any],
) -> None:
    """Persist the fetched company data to the DB cache (best-effort).

    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE — atomic, zero race.
    The savepoint approach leaked exceptions into the outer transaction
    causing PendingRollbackError on subsequent flush() calls.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(GlassdoorCache)
        .values(
            id=uuid.uuid4(),
            company_name=normalized,
            glassdoor_data=json.dumps(company, ensure_ascii=False),
            rating=parsed.get("glassdoor_rating"),
            review_count=parsed.get("review_count"),
            fetched_at=datetime.now(UTC),
        )
        .on_conflict_do_update(
            index_elements=["company_name"],
            set_={
                "glassdoor_data": json.dumps(company, ensure_ascii=False),
                "rating": parsed.get("glassdoor_rating"),
                "review_count": parsed.get("review_count"),
                "fetched_at": datetime.now(UTC),
            },
        )
    )
    try:
        db.execute(stmt)
        db.flush()
    except Exception:
        # Caching is best-effort. If it fails, the parsed result is still valid.
        db.rollback()


def _fetch_and_cache_from_api(
    company_name: str,
    normalized: str,
    db: Session,
    cache: "CacheService | None",
    cache_key: str,
) -> dict[str, Any] | None:
    """Call the Glassdoor API, parse the best match, and populate both caches."""
    try:
        data = _call_api(company_name)
    except Exception:
        return None
    if data is None:
        return None

    company = _best_match(data, company_name)
    if company is None:
        return None

    parsed = _parse_company(company)
    _persist_glassdoor_cache(db, normalized, company, parsed)

    parsed["cached"] = False
    # Populate Redis cache so subsequent batch items hit it fast
    if cache is not None:
        cache.set_json(cache_key, parsed, 3600)
    return parsed


def fetch_glassdoor_rating(
    company_name: str, db: Session, cache: "CacheService | None" = None
) -> dict[str, Any] | None:
    """Fetch Glassdoor rating for a company using two-tier cache (Redis → DB → API).

    Returns a dict with rating data, or None if unavailable.
    """
    if not company_name or not company_name.strip():
        return None
    if not settings.rapidapi_key:
        return None

    normalized = company_name.lower().strip()
    cache_key = f"glassdoor:{normalized}"

    redis_hit = _lookup_redis_cache(cache, cache_key)
    if redis_hit is not None:
        return redis_hit

    db_hit = _lookup_db_cache(db, normalized, cache, cache_key)
    if db_hit is not None:
        return db_hit

    return _fetch_and_cache_from_api(company_name.strip(), normalized, db, cache, cache_key)


def _call_api(query: str) -> dict[str, Any] | None:
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
        return cast(dict[str, Any] | None, response.json())
    except httpx.HTTPStatusError:
        return None
    except Exception:
        return None


_MIN_REVIEWS = 3


def _is_usable_result(r: dict[str, Any]) -> bool:
    """True if the result has a rating and enough reviews to be reliable."""
    return bool(r.get("rating")) and (r.get("review_count") or 0) >= _MIN_REVIEWS


def _find_match(results: list[dict[str, Any]], q: str, predicate: Any) -> dict[str, Any] | None:
    """Return the first usable result whose name satisfies the given predicate."""
    for r in results:
        name = (r.get("name") or "").lower().strip()
        if predicate(name, q) and _is_usable_result(r):
            return r
    return None


def _best_match(data: dict[str, Any], query: str) -> dict[str, Any] | None:
    """Pick the best matching company from API results.

    Requires at least 3 reviews for reliability. Tries exact → prefix → substring.
    """
    if data.get("status") != "OK":
        return None
    results: list[dict[str, Any]] = data.get("data", [])
    if not results:
        return None

    q = query.lower().strip()

    exact = _find_match(results, q, lambda name, query_: name == query_)
    if exact is not None:
        return exact

    prefix = _find_match(results, q, lambda name, query_: name.startswith(query_) or query_.startswith(name))
    if prefix is not None:
        return prefix

    return _find_match(results, q, lambda name, query_: query_ in name)


_SUB_RATING_MAP = {
    "culture_and_values_rating": "culture",
    "compensation_and_benefits_rating": "compensation",
    "work_life_balance_rating": "work_life_balance",
    "career_opportunities_rating": "career_opportunities",
    "senior_management_rating": "senior_management",
    "diversity_and_inclusion_rating": "diversity",
}


def _extract_sub_ratings(c: dict[str, Any]) -> dict[str, float]:
    """Extract and normalize sub-ratings from a raw API company object."""
    sub_ratings: dict[str, float] = {}
    for api_key, our_key in _SUB_RATING_MAP.items():
        val = c.get(api_key)
        if val and float(val) > 0:
            sub_ratings[our_key] = round(float(val), 1)
    return sub_ratings


def _rating_to_percent(value: Any) -> int | None:
    """Convert a 0..1 rating to a 0..100 integer, or None if missing/zero."""
    if not value:
        return None
    f = float(value)
    if f <= 0:
        return None
    return round(f * 100)


def _glassdoor_url(c: dict[str, Any]) -> str:
    """Build the public Glassdoor overview URL for a company, if id is present."""
    company_id = c.get("company_id", "")
    if not company_id:
        return ""
    company_name_slug = (c.get("name") or "").replace(" ", "-")
    return f"https://www.glassdoor.com/Overview/Working-at-{company_name_slug}-EI_IE{company_id}.htm"


def _parse_company(c: dict[str, Any]) -> dict[str, Any]:
    """Parse a company-data12 company object into our standard format."""
    return {
        "glassdoor_rating": float(c.get("rating", 0)),
        "glassdoor_url": _glassdoor_url(c),
        "review_count": int(c.get("review_count", 0)),
        "sub_ratings": _extract_sub_ratings(c),
        "ceo_name": c.get("ceo") or "",
        "ceo_approval": _rating_to_percent(c.get("ceo_rating")),
        "recommend_to_friend": _rating_to_percent(c.get("recommend_to_friend_rating")),
        "business_outlook": _rating_to_percent(c.get("business_outlook_rating")),
        "industry": c.get("industry") or "",
        "company_size": c.get("company_size") or "",
        "website": c.get("website") or "",
        "headquarters": c.get("headquarters") or "",
        "founded": c.get("founded") or "",
        "revenue": c.get("revenue") or "",
        "source": "glassdoor_api",
        "cached": False,
    }


def _parse_cached(cached: GlassdoorCache) -> dict[str, Any] | None:
    """Build result dict from cached DB record."""
    try:
        company = json.loads(str(cached.glassdoor_data)) if cached.glassdoor_data else {}
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
