import json
import logging
from datetime import datetime, timedelta

import httpx

from .config import settings
from .database import GlassdoorCache, SessionLocal

logger = logging.getLogger(__name__)

CACHE_DAYS = 30
RAPIDAPI_HOST = "company-data12.p.rapidapi.com"
SEARCH_URL = f"https://{RAPIDAPI_HOST}/company-search"


def fetch_glassdoor_rating(company_name: str) -> dict | None:
    """Fetch Glassdoor rating for a company, using DB cache.

    Returns a dict with rating data, or None if unavailable.
    Graceful degradation: returns None on missing key, API errors, etc.
    """
    if not company_name or not company_name.strip():
        return None

    if not settings.rapidapi_key:
        logger.debug("RapidAPI key non configurata, skip Glassdoor lookup")
        return None

    normalized = company_name.lower().strip()

    db = SessionLocal()
    try:
        # Check cache
        cached = db.query(GlassdoorCache).filter(GlassdoorCache.company_name == normalized).first()
        if cached and cached.fetched_at:
            age = datetime.utcnow() - cached.fetched_at
            if age < timedelta(days=CACHE_DAYS):
                logger.info("Glassdoor cache hit per '%s' (age: %d giorni)", normalized, age.days)
                return _parse_cached(cached)

        # Call API
        data = _call_api(company_name.strip())
        if data is None:
            return None

        company = _best_match(data, company_name.strip())
        if company is None:
            return None

        parsed = _parse_company(company)

        # Save/update cache
        if cached:
            cached.glassdoor_data = json.dumps(company, ensure_ascii=False)
            cached.rating = parsed.get("glassdoor_rating")
            cached.review_count = parsed.get("review_count")
            cached.fetched_at = datetime.utcnow()
        else:
            cached = GlassdoorCache(
                company_name=normalized,
                glassdoor_data=json.dumps(company, ensure_ascii=False),
                rating=parsed.get("glassdoor_rating"),
                review_count=parsed.get("review_count"),
                fetched_at=datetime.utcnow(),
            )
            db.add(cached)
        db.commit()
        logger.info("Glassdoor dati salvati per '%s': rating=%.1f, reviews=%s",
                     normalized, parsed.get("glassdoor_rating", 0), parsed.get("review_count"))

        parsed["cached"] = False
        return parsed

    except Exception as e:
        logger.error("Errore Glassdoor per '%s': %s", normalized, e, exc_info=True)
        return None
    finally:
        db.close()


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
        data = response.json()
        logger.debug("company-data12 API response per '%s': status=%d", query, response.status_code)
        return data
    except httpx.HTTPStatusError as e:
        logger.warning("company-data12 API HTTP error per '%s': %s", query, e)
        return None
    except Exception as e:
        logger.warning("company-data12 API error per '%s': %s", query, e)
        return None


def _best_match(data: dict, query: str) -> dict | None:
    """Pick the best matching company from API results.

    Compares company names case-insensitively to find the closest match.
    Requires at least 3 reviews for reliability.
    """
    if data.get("status") != "OK":
        return None
    results = data.get("data", [])
    if not results:
        return None

    q = query.lower().strip()

    # First pass: exact name match (case-insensitive)
    for r in results:
        name = (r.get("name") or "").lower().strip()
        if name == q and r.get("rating") and (r.get("review_count") or 0) >= 3:
            return r

    # Second pass: name starts with query or query starts with name
    for r in results:
        name = (r.get("name") or "").lower().strip()
        if (name.startswith(q) or q.startswith(name)) and r.get("rating") and (r.get("review_count") or 0) >= 3:
            return r

    # Third pass: query is contained in name
    for r in results:
        name = (r.get("name") or "").lower().strip()
        if q in name and r.get("rating") and (r.get("review_count") or 0) >= 3:
            return r

    logger.debug("Glassdoor: nessun match affidabile per '%s' tra %d risultati", query, len(results))
    return None


def _parse_company(c: dict) -> dict:
    """Parse a company-data12 company object into our standard format."""
    rating = float(c.get("rating", 0))
    review_count = int(c.get("review_count", 0))

    sub_ratings = {}
    for api_key, our_key in [
        ("culture_and_values_rating", "culture"),
        ("compensation_and_benefits_rating", "compensation"),
        ("work_life_balance_rating", "work_life_balance"),
        ("career_opportunities_rating", "career_opportunities"),
        ("senior_management_rating", "senior_management"),
        ("diversity_and_inclusion_rating", "diversity"),
    ]:
        val = c.get(api_key)
        if val and float(val) > 0:
            sub_ratings[our_key] = round(float(val), 1)

    ceo_name = c.get("ceo") or ""
    ceo_rating = c.get("ceo_rating")
    ceo_approval = round(float(ceo_rating) * 100) if ceo_rating and float(ceo_rating) > 0 else None

    # Build Glassdoor URL from company name (no direct URL in this API)
    company_name_slug = (c.get("name") or "").replace(" ", "-")
    company_id = c.get("company_id", "")
    glassdoor_url = f"https://www.glassdoor.com/Overview/Working-at-{company_name_slug}-EI_IE{company_id}.htm" if company_id else ""

    return {
        "glassdoor_rating": rating,
        "glassdoor_url": glassdoor_url,
        "review_count": review_count,
        "sub_ratings": sub_ratings,
        "ceo_name": ceo_name,
        "ceo_approval": ceo_approval,
        "recommend_to_friend": round(float(c.get("recommend_to_friend_rating", 0)) * 100) if c.get("recommend_to_friend_rating") else None,
        "business_outlook": round(float(c.get("business_outlook_rating", 0)) * 100) if c.get("business_outlook_rating") else None,
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

    # Fallback: use stored rating/review_count
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
