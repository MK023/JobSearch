"""Unified metrics across JobAnalysis (cowork flow) and LinkedinApplication
(Easy Apply import).

The two tables record the same real-world event — "Marco applied for a job"
— from two different sources. The analytics snapshot needs a merged view so
the dashboard shows the actual volume / role distribution / monthly trend,
not the two partial views that existed before.

Dedup rule: same ``(lower(company), role_bucket)`` key counts as one logical
candidature regardless of which table it came from. This is intentionally
lossy — two different ads at the same company for the same role bucket
collapse — because the alternative (exact role string match) keeps near-
duplicates apart and inflates the count.

All functions are pure: they accept the already-extracted JobAnalysis
feature list (the ``extract_features`` output) and a SQLAlchemy ``Session``
for the LinkedIn table. No HTTP, no ORM leakage in the return types.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from ..analytics.extractor import _role_bucket
from .models import LinkedinApplication


def _canonical_company(name: str | None) -> str:
    return (name or "").strip().lower()


def _linkedin_rows(db: Session) -> list[dict[str, Any]]:
    """Read the LinkedIn table into plain dicts (one DB round-trip)."""
    rows = db.query(
        LinkedinApplication.company_name,
        LinkedinApplication.job_title,
        LinkedinApplication.application_date,
    ).all()
    return [
        {
            "company": _canonical_company(r.company_name),
            "role": (r.job_title or "").strip(),
            "role_bucket": _role_bucket(r.job_title),
            "date": r.application_date,
        }
        for r in rows
    ]


def _analysis_rows(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise the JobAnalysis features to the same shape as LinkedIn rows."""
    out: list[dict[str, Any]] = []
    for f in features:
        # ``extract_features`` already computed ``role_bucket`` and kept the
        # original ``role`` / ``company``; we just normalise the company
        # string so the dedup key matches the LinkedIn side.
        out.append(
            {
                "company": _canonical_company(f.get("company")),
                "role": (f.get("role") or "").strip(),
                "role_bucket": f.get("role_bucket") or "other",
                "date": f.get("created_at") or f.get("applied_at"),
            }
        )
    return out


def _unique_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row["company"], row["role_bucket"])


def total_volume_unified(db: Session, features: list[dict[str, Any]]) -> dict[str, int]:
    """Return the three headline counts: analyses-only, linkedin-only, union.

    ``unique_candidatures`` is the deduped count across both sources using
    ``(company, role_bucket)`` as the equivalence key.
    """
    analysis = _analysis_rows(features)
    linkedin = _linkedin_rows(db)

    analysis_keys = {_unique_key(r) for r in analysis if r["company"]}
    linkedin_keys = {_unique_key(r) for r in linkedin if r["company"]}
    union = analysis_keys | linkedin_keys

    return {
        "job_analyses_count": len(features),
        "linkedin_count": len(linkedin),
        "unique_candidatures": len(union),
        "overlap_count": len(analysis_keys & linkedin_keys),
    }


def role_distribution_unified(db: Session, features: list[dict[str, Any]]) -> dict[str, int]:
    """Count candidature per role_bucket across both sources, deduped."""
    analysis = _analysis_rows(features)
    linkedin = _linkedin_rows(db)

    seen: set[tuple[str, str]] = set()
    dist: Counter[str] = Counter()
    for row in analysis + linkedin:
        key = _unique_key(row)
        if not row["company"] or key in seen:
            continue
        seen.add(key)
        dist[row["role_bucket"]] += 1
    return dict(dist)


def applications_by_month_unified(db: Session, features: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    """Merge application dates from both sources into one monthly series.

    Same dedup rule: one ``(company, role_bucket)`` contributes at most
    once per month (on the earliest available date). Result is sorted
    oldest→newest, trimmed to the last ``limit`` months.
    """
    analysis = _analysis_rows(features)
    linkedin = _linkedin_rows(db)

    # Dates arrive in two shapes: ``datetime`` from the LinkedIn ORM rows
    # and ISO strings from ``extract_features`` output. Normalise both to
    # ``YYYY-MM-DD`` strings up front — that lets us compare with ``<``
    # lexicographically and avoids mixed-type TypeError.
    def _iso_day(d: Any) -> str | None:
        if d is None:
            return None
        if hasattr(d, "strftime"):
            # datetime → explicit str() narrows the mypy "Returning Any"
            # warning that triggers under --warn-return-any on ``Any``.
            return str(d.strftime("%Y-%m-%d"))
        return str(d)[:10] or None

    best_date: dict[tuple[str, str], str] = {}
    for row in analysis + linkedin:
        key = _unique_key(row)
        iso = _iso_day(row["date"])
        if not row["company"] or not iso:
            continue
        prev = best_date.get(key)
        if prev is None or iso < prev:
            best_date[key] = iso

    monthly: Counter[str] = Counter()
    for iso in best_date.values():
        monthly[iso[:7]] += 1

    result = [{"month": m, "count": c} for m, c in sorted(monthly.items())]
    return result[-limit:]
