"""Job Salary Data integration via RapidAPI.

Provides salary estimates for job titles with DB-level caching (30 days).
Graceful degradation: returns None on missing API key, errors, or no data.

Includes a global 429 circuit breaker: on rate limit, all calls are skipped
for 1 hour to avoid burning through remaining quota.
"""

import json
import logging
import time
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

CACHE_DAYS = 30
RAPIDAPI_HOST = "job-salary-data.p.rapidapi.com"
SALARY_URL = f"https://{RAPIDAPI_HOST}/job-salary"

# Circuit breaker: when RapidAPI returns 429, skip all calls for this many seconds.
# Resets automatically after the cooldown. Protects monthly quota.
_RATE_LIMIT_COOLDOWN_S = 3600
_rate_limited_until: float = 0.0


class SalaryCache(Base):
    """DB-level cache for salary data (30-day TTL)."""

    __tablename__ = "salary_cache"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cache_key = Column(String(255), unique=True, index=True, nullable=False)
    salary_data = Column(Text, default="")
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def _call_api(job_title: str, location: str | None = None) -> list[dict[str, Any]] | None:
    """Call the Job Salary Data API. Returns parsed data list or None."""
    global _rate_limited_until

    if not settings.rapidapi_key:
        return None

    # Circuit breaker: skip if we recently hit the rate limit
    if time.time() < _rate_limited_until:
        return None

    params: dict[str, str] = {"job_title": job_title}
    if location:
        params["location"] = location
        params["radius"] = "200"

    try:
        resp = httpx.get(
            SALARY_URL,
            headers={
                "X-RapidAPI-Key": settings.rapidapi_key,
                "X-RapidAPI-Host": RAPIDAPI_HOST,
            },
            params=params,
            timeout=10.0,
        )
        if resp.status_code == 429:
            _rate_limited_until = time.time() + _RATE_LIMIT_COOLDOWN_S
            logger.warning("Salary API rate-limited (429). Circuit open for %ds", _RATE_LIMIT_COOLDOWN_S)
            return None
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", [])
        return data if isinstance(data, list) else None
    except Exception:
        logger.warning("Salary API call failed for %r", job_title, exc_info=True)
        return None


def _parse_salary(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a salary API result into a clean dict."""
    return {
        "location": item.get("location", ""),
        "job_title": item.get("job_title", ""),
        "min_salary": item.get("min_salary"),
        "max_salary": item.get("max_salary"),
        "median_salary": item.get("median_salary"),
        "salary_period": item.get("salary_period", "YEAR"),
        "salary_currency": item.get("salary_currency", "USD"),
        "salary_count": item.get("salary_count", 0),
        "confidence": item.get("confidence", ""),
        "publisher": item.get("publisher_name", ""),
        "source": "job_salary_data_api",
    }


_UNSUPPORTED_LOCATIONS = (
    "italia",
    "italy",
    "milano",
    "roma",
    "torino",
    "bologna",
    "firenze",
    "napoli",
    "genova",
    "palermo",
    "france",
    "francia",
    "deutschland",
    "germany",
    "españa",
    "spain",
    "portugal",
)


def fetch_salary_data(
    job_title: str,
    location: str | None = None,
    db: Session | None = None,
) -> dict[str, Any] | None:
    """Fetch salary estimate for a job title. DB cache 30-day TTL.

    Skips API call for known-unsupported locations (Italy/EU) to save quota.
    """
    if not job_title or not settings.rapidapi_key:
        return None

    title_norm = job_title.strip().lower()
    loc_norm = (location or "").strip().lower()

    # Skip unsupported locations — API returns empty, wasting quota
    if loc_norm and any(kw in loc_norm for kw in _UNSUPPORTED_LOCATIONS):
        return None

    key = f"{title_norm}:{loc_norm}"

    # Single cache lookup, reused for both read and write paths
    cached = None
    if db is not None:
        try:
            cached = db.query(SalaryCache).filter(SalaryCache.cache_key == key).first()
            if cached and cached.fetched_at:
                age = datetime.now(UTC) - cached.fetched_at.replace(tzinfo=UTC)
                if age < timedelta(days=CACHE_DAYS) and cached.salary_data:
                    return cast(dict[str, Any], json.loads(str(cached.salary_data)))
        except Exception:  # noqa: S110 — cache miss is non-fatal
            pass

    # Single API call — no automatic fallback (burns quota too fast)
    data = _call_api(job_title, location) if location else _call_api(job_title)
    if not data:
        return None

    result = _parse_salary(data[0])

    # Update cache reusing the row we already fetched (no second query)
    if db is not None:
        try:
            if cached:
                cached.salary_data = json.dumps(result)  # type: ignore[assignment]
                cached.fetched_at = datetime.now(UTC)  # type: ignore[assignment]
            else:
                db.add(SalaryCache(cache_key=key, salary_data=json.dumps(result)))
            db.flush()
        except Exception:
            logger.warning("Failed to cache salary data", exc_info=True)

    return result
