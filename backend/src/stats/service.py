"""Aggregate queries for the Stats page.

Each helper is a single SQL aggregate (COUNT, AVG, GROUP BY, DATE_TRUNC)
designed so Neon handles the work and Python just reshapes the rows
for the chart renderer. The full payload is cached in Redis with a
short TTL so repeated page loads don't hammer the DB.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisStatus, JobAnalysis
from ..cover_letter.models import CoverLetter
from ..integrations.cache import CacheService

_STATS_CACHE_KEY = "stats:dashboard:v1"
_STATS_CACHE_TTL_SECONDS = 60


def funnel_counts(db: Session) -> dict[str, int]:
    """Rows per status — the candidate's hiring funnel in absolute numbers."""
    rows = db.query(JobAnalysis.status, func.count(JobAnalysis.id)).group_by(JobAnalysis.status).all()
    by_status = {row[0]: int(row[1]) for row in rows}
    return {
        "da_valutare": by_status.get(AnalysisStatus.PENDING.value, 0),
        "candidato": by_status.get(AnalysisStatus.APPLIED.value, 0),
        "colloquio": by_status.get(AnalysisStatus.INTERVIEW.value, 0),
        "offerta": by_status.get(AnalysisStatus.OFFER.value, 0),
        "scartato": by_status.get(AnalysisStatus.REJECTED.value, 0),
    }


_SCORE_BINS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]


def score_distribution(db: Session) -> list[dict[str, Any]]:
    """Histogram of score values on applied/interview/offer rows.

    Bin bounds are [lo, hi) except the last bin which is inclusive of 100.
    """
    live = [
        AnalysisStatus.APPLIED.value,
        AnalysisStatus.INTERVIEW.value,
        AnalysisStatus.OFFER.value,
    ]
    out: list[dict[str, Any]] = []
    for lo, hi in _SCORE_BINS:
        count = (
            db.query(func.count(JobAnalysis.id))
            .filter(
                JobAnalysis.status.in_(live),
                JobAnalysis.score >= lo,
                JobAnalysis.score < hi,
            )
            .scalar()
            or 0
        )
        label = f"{lo}-{hi - 1 if hi <= 100 else 100}"
        out.append({"bin": label, "count": int(count)})
    return out


def applications_per_week(db: Session, weeks: int = 12) -> list[dict[str, Any]]:
    """Candidature inviate per settimana, ultime N settimane.

    Uses SQLAlchemy's ``date_trunc`` on Postgres and ``strftime`` on SQLite
    via a portable helper so the same code works in dev (SQLite) and prod
    (Postgres).
    """
    cutoff = datetime.now(UTC) - timedelta(weeks=weeks)
    bucket = _week_bucket(db, JobAnalysis.created_at)
    rows = (
        db.query(bucket.label("week"), func.count(JobAnalysis.id).label("count"))
        .filter(
            JobAnalysis.created_at >= cutoff,
            JobAnalysis.status.in_(
                [
                    AnalysisStatus.APPLIED.value,
                    AnalysisStatus.INTERVIEW.value,
                    AnalysisStatus.OFFER.value,
                ]
            ),
        )
        .group_by(bucket)
        .order_by(bucket.asc())
        .all()
    )
    return [{"week": str(r[0]), "count": int(r[1])} for r in rows]


def top_companies(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    """Aziende con più analisi, escludendo i nomi vuoti."""
    rows = (
        db.query(JobAnalysis.company, func.count(JobAnalysis.id).label("n"))
        .filter(JobAnalysis.company.isnot(None), JobAnalysis.company != "")
        .group_by(JobAnalysis.company)
        .order_by(func.count(JobAnalysis.id).desc())
        .limit(limit)
        .all()
    )
    return [{"company": r[0], "count": int(r[1])} for r in rows]


def work_mode_split(db: Session) -> list[dict[str, Any]]:
    """Remoto / ibrido / in sede / non specificato."""
    rows = db.query(JobAnalysis.work_mode, func.count(JobAnalysis.id)).group_by(JobAnalysis.work_mode).all()
    total = sum(int(r[1]) for r in rows) or 1
    out: list[dict[str, Any]] = []
    for mode, count in rows:
        label = mode or "non specificato"
        out.append({"mode": label, "count": int(count), "pct": round(100.0 * int(count) / total, 1)})
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def contract_split(db: Session) -> dict[str, int]:
    """Dipendente (default) vs body rental vs freelance vs recruiter esterno.

    Reads the JSON ``recruiter_info`` populated by analysis prompt v6.
    Counts are done in Python over the fetched rows instead of pure SQL:
    the dialect mismatch between JSONB (Postgres) and JSON-as-TEXT
    (SQLite) makes a SQL-only version fragile, and the dataset is small
    enough (O(10k) foreseeable) that one SELECT is cheap and readable.
    """
    rows = db.query(JobAnalysis.recruiter_info).all()
    body_rental = 0
    freelance = 0
    recruiter = 0
    for (info,) in rows:
        if not isinstance(info, dict):
            continue
        if info.get("is_body_rental"):
            body_rental += 1
        if info.get("is_freelance"):
            freelance += 1
        if info.get("is_recruiter"):
            recruiter += 1

    total = len(rows)
    dipendente = max(0, total - body_rental - freelance)
    return {
        "dipendente": dipendente,
        "body_rental": body_rental,
        "freelance": freelance,
        "recruiter_esterno": recruiter,
    }


def recommendation_split(db: Session) -> dict[str, int]:
    """APPLY / CONSIDER / SKIP dalle raccomandazioni AI."""
    rows = db.query(JobAnalysis.recommendation, func.count(JobAnalysis.id)).group_by(JobAnalysis.recommendation).all()
    out: dict[str, int] = {"APPLY": 0, "CONSIDER": 0, "SKIP": 0, "ALTRO": 0}
    for rec, count in rows:
        key = (rec or "").upper()
        if key not in ("APPLY", "CONSIDER", "SKIP"):
            out["ALTRO"] += int(count)
        else:
            out[key] += int(count)
    return out


def spending_timeline(db: Session, days: int = 30) -> list[dict[str, Any]]:
    """Costo API Anthropic per giorno sugli ultimi N giorni.

    Somma i cost_usd di JobAnalysis + CoverLetter raggruppati per giorno.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    analysis_bucket = _day_bucket(db, JobAnalysis.created_at)
    analysis_rows = (
        db.query(analysis_bucket.label("day"), func.coalesce(func.sum(JobAnalysis.cost_usd), 0.0).label("cost"))
        .filter(JobAnalysis.created_at >= cutoff)
        .group_by(analysis_bucket)
        .all()
    )

    cl_bucket = _day_bucket(db, CoverLetter.created_at)
    cl_rows = (
        db.query(cl_bucket.label("day"), func.coalesce(func.sum(CoverLetter.cost_usd), 0.0).label("cost"))
        .filter(CoverLetter.created_at >= cutoff)
        .group_by(cl_bucket)
        .all()
    )

    merged: dict[str, float] = {}
    for day, cost in analysis_rows:
        merged[str(day)] = merged.get(str(day), 0.0) + float(cost or 0)
    for day, cost in cl_rows:
        merged[str(day)] = merged.get(str(day), 0.0) + float(cost or 0)

    return [{"day": day, "cost_usd": round(merged[day], 5)} for day in sorted(merged)]


def score_by_status(db: Session) -> list[dict[str, Any]]:
    """Score medio per stato — utile per capire se filtri meglio prima di candidarti."""
    rows = (
        db.query(JobAnalysis.status, func.avg(JobAnalysis.score), func.count(JobAnalysis.id))
        .group_by(JobAnalysis.status)
        .all()
    )
    out: list[dict[str, Any]] = []
    for status, avg, count in rows:
        out.append(
            {
                "status": status or "unknown",
                "avg_score": round(float(avg), 1) if avg is not None else 0.0,
                "count": int(count),
            }
        )
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def get_stats(db: Session, cache: CacheService | None = None) -> dict[str, Any]:
    """Build the full stats payload. Cached in Redis with a short TTL.

    On cache miss we run 8 lightweight aggregate queries — each one is a
    pure SQL COUNT/AVG/GROUP BY, so the DB does the work and Python just
    reshapes rows into the Chart.js-friendly dicts.
    """
    if cache is not None:
        hit = cache.get_json(_STATS_CACHE_KEY)
        if hit is not None:
            return hit

    payload: dict[str, Any] = {
        "funnel": funnel_counts(db),
        "score_distribution": score_distribution(db),
        "applications_per_week": applications_per_week(db),
        "top_companies": top_companies(db),
        "work_mode_split": work_mode_split(db),
        "contract_split": contract_split(db),
        "recommendation_split": recommendation_split(db),
        "spending_timeline": spending_timeline(db),
        "score_by_status": score_by_status(db),
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if cache is not None:
        cache.set_json(_STATS_CACHE_KEY, payload, _STATS_CACHE_TTL_SECONDS)

    return payload


# ------- Portable SQL helpers (SQLite in tests, Postgres in prod) -------


def _week_bucket(db: Session, column: Any) -> Any:
    """Return a SQL expression that truncates ``column`` to the ISO week start."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return func.date_trunc("week", column)
    # SQLite: isoformat date of the Monday of the week containing the value.
    return func.strftime("%Y-%W", column)


def _day_bucket(db: Session, column: Any) -> Any:
    """Return a SQL expression that truncates ``column`` to the calendar day."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return func.date_trunc("day", column)
    return func.strftime("%Y-%m-%d", column)
