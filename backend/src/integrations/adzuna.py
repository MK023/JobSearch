"""Adzuna API client for the WorldWild ingest layer.

Single responsibility: fetch + normalize Adzuna search results into a flat
``dict`` schema that the WorldWild ingest service can hash, dedup, and persist.

Out of scope: dedup, persistence, pre-filter, AI analysis. Those live in
``..worldwild.services.ingest`` to keep the client testable in isolation.

Graceful degradation: empty list on missing keys, network errors, 4xx/5xx.
Sentry breadcrumbs are added for non-2xx responses so an adapter going stale
becomes visible without raising.
"""

from typing import Any

import httpx

from ..config import settings
from ._common import parse_iso_datetime, record_error, safe_str

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs"
DEFAULT_COUNTRY = "it"  # Italian market is Marco's primary bucket
DEFAULT_RESULTS_PER_PAGE = 50
DEFAULT_MAX_PAGES = 4  # 4 × 50 = 200 results/run; conservative on free tier
DEFAULT_MAX_DAYS_OLD = 7
HTTP_TIMEOUT_SECONDS = 12.0


def fetch_adzuna_jobs(
    *,
    what: str,
    country: str = DEFAULT_COUNTRY,
    max_pages: int = DEFAULT_MAX_PAGES,
    results_per_page: int = DEFAULT_RESULTS_PER_PAGE,
    max_days_old: int = DEFAULT_MAX_DAYS_OLD,
    sort_by: str = "date",
) -> list[dict[str, Any]]:
    """Fetch jobs matching ``what`` from Adzuna's ``country`` market.

    Returns a list of normalized dicts. Empty list on missing credentials or
    on any error (the caller should treat this as "this run produced nothing"
    rather than crashing the cron).

    The ``what`` param is space-separated keywords (e.g. ``"devops python"``).
    Adzuna treats it as OR by default, ranked by relevance to the full phrase.
    """
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return []

    aggregated: list[dict[str, Any]] = []
    seen_external_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        try:
            page_results = _fetch_page(
                what=what,
                country=country,
                page=page,
                results_per_page=results_per_page,
                max_days_old=max_days_old,
                sort_by=sort_by,
            )
        except (httpx.HTTPError, ValueError) as exc:
            # Capture and stop pagination on first hard error; keep what we got.
            record_error(exc, source="adzuna", page=page)
            break

        if not page_results:
            break

        for raw in page_results:
            normalized = _normalize(raw)
            if normalized is None:
                continue
            ext_id = normalized["external_id"]
            if ext_id in seen_external_ids:
                continue
            seen_external_ids.add(ext_id)
            aggregated.append(normalized)

        # Adzuna doesn't expose a hasMore flag — short-circuit when a page
        # comes back smaller than requested (last page).
        if len(page_results) < results_per_page:
            break

    return aggregated


def _fetch_page(
    *,
    what: str,
    country: str,
    page: int,
    results_per_page: int,
    max_days_old: int,
    sort_by: str,
) -> list[dict[str, Any]]:
    url = f"{ADZUNA_BASE}/{country}/search/{page}"
    params: dict[str, str | int] = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": results_per_page,
        "what": what,
        "max_days_old": max_days_old,
        "sort_by": sort_by,
        "content-type": "application/json",
    }
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = client.get(url, params=params)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        return []
    results = payload.get("results", [])
    return results if isinstance(results, list) else []


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten an Adzuna result into the WorldWild canonical shape.

    Returns ``None`` when the row is missing essentials (no id or no title) —
    those would be useless garbage in ``job_offers``.
    """
    ext_id = str(raw.get("id") or "").strip()
    title = (raw.get("title") or "").strip()
    if not ext_id or not title:
        return None

    company_raw = raw.get("company") or {}
    location_raw = raw.get("location") or {}
    category_raw = raw.get("category") or {}

    return {
        "source": "adzuna",
        "external_id": ext_id,
        "title": title[:500],
        "company": safe_str(company_raw.get("display_name"), 255),
        "location": safe_str(location_raw.get("display_name"), 255),
        "url": safe_str(raw.get("redirect_url"), 1000),
        "description": (raw.get("description") or "").strip(),
        "salary_min": _safe_int(raw.get("salary_min")),
        "salary_max": _safe_int(raw.get("salary_max")),
        "salary_currency": safe_str(raw.get("salary_currency"), 8) or _infer_currency(country_raw=raw),
        "contract_type": safe_str(raw.get("contract_type"), 32),
        "contract_time": safe_str(raw.get("contract_time"), 32),
        "category": safe_str(category_raw.get("label"), 128),
        "posted_at": parse_iso_datetime(raw.get("created")),
        "raw_payload": raw,
    }


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _infer_currency(*, country_raw: dict[str, Any]) -> str:
    """Default currency by Adzuna country code when not explicit."""
    country = (country_raw.get("__CLASS__") or "").lower()
    # Adzuna IT search returns Italian listings; salaries are EUR by convention.
    # Fallback to empty when unknown.
    if "it" in country or country_raw.get("location", {}).get("area", []):
        return "EUR"
    return ""
