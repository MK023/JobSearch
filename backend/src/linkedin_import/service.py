"""Read-only aggregate queries over ``linkedin_applications``.

All functions accept a ``Session`` and return plain Python dicts/lists so they
can be serialised by FastAPI without ORM leakage.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import JobAnalysis
from .models import LinkedinApplication


def get_summary(db: Session) -> dict[str, Any]:
    """Return the headline figures shown on the analytics page.

    Keeps the shape compact (one dict, two nested lists) so the template can
    render it without conditionals.
    """
    total = db.query(func.count(LinkedinApplication.id)).scalar() or 0
    unique_companies = db.query(func.count(func.distinct(func.lower(LinkedinApplication.company_name)))).scalar() or 0
    date_row = db.query(
        func.min(LinkedinApplication.application_date),
        func.max(LinkedinApplication.application_date),
    ).first()
    first_date, last_date = date_row if date_row else (None, None)

    return {
        "total_applications": int(total),
        "unique_companies": int(unique_companies),
        "first_application": first_date.date().isoformat() if first_date else None,
        "last_application": last_date.date().isoformat() if last_date else None,
        "applications_by_month": _applications_by_month(db),
        "top_companies_without_analysis": _top_dark_companies(db),
    }


def _applications_by_month(db: Session, limit: int = 24) -> list[dict[str, Any]]:
    """Return the last ``limit`` months sorted oldest→newest.

    SQLite (tests) does not support ``date_trunc``, so we fall back on
    ``strftime``. Both paths produce ``YYYY-MM`` strings.
    """
    dialect = db.bind.dialect.name if db.bind else "sqlite"
    if dialect == "postgresql":
        month_expr = func.to_char(LinkedinApplication.application_date, "YYYY-MM")
    else:
        month_expr = func.strftime("%Y-%m", LinkedinApplication.application_date)

    rows = (
        db.query(month_expr.label("month"), func.count(LinkedinApplication.id).label("count"))
        .filter(LinkedinApplication.application_date.isnot(None))
        .group_by("month")
        .order_by("month")
        .all()
    )
    data = [{"month": r.month, "count": int(r.count)} for r in rows]
    return data[-limit:]


def _top_dark_companies(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    """Companies with most LinkedIn applications **not covered** by job_analyses.

    "Dark" = company where we applied via Easy Apply but never fed the job
    description through the AI analysis pipeline. These are the highest-value
    targets for either manual follow-up or future batch analysis.
    """
    analysed_subq = (
        db.query(func.lower(func.trim(JobAnalysis.company))).filter(JobAnalysis.company.isnot(None)).distinct()
    )

    rows = (
        db.query(
            func.lower(func.trim(LinkedinApplication.company_name)).label("company"),
            func.count(LinkedinApplication.id).label("count"),
            func.min(LinkedinApplication.application_date).label("first_apply"),
            func.max(LinkedinApplication.application_date).label("last_apply"),
        )
        .filter(LinkedinApplication.company_name.isnot(None))
        .filter(func.lower(func.trim(LinkedinApplication.company_name)).notin_(analysed_subq))
        .group_by("company")
        .order_by(func.count(LinkedinApplication.id).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "company": r.company,
            "count": int(r.count),
            "first_apply": _to_iso(r.first_apply),
            "last_apply": _to_iso(r.last_apply),
        }
        for r in rows
    ]


def _to_iso(value: Any) -> str | None:
    """Best-effort ISO-date stringifier used in the summary payload.

    Always produces ``YYYY-MM-DD`` regardless of whether the driver returns
    ``datetime`` (PostgreSQL timestamptz) or ``date`` (SQLite string coerce).
    Checking ``datetime`` before ``date`` matters because ``datetime`` is a
    subclass of ``date`` — the order would invert otherwise and we'd emit
    a full ISO timestamp instead of a day.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
