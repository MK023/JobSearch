"""Analytics page service — lock/unlock logic, run execution, profile building."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..analysis.models import JobAnalysis
from ..analytics.discriminator import bias_signals, discriminant_features
from ..analytics.extractor import extract_features
from ..analytics.stats import conversion_rate, counts_by_status, distribution
from .models import AnalyticsRun, UserProfile

UNLOCK_THRESHOLD = 15  # new analyses-with-status since last run needed to unlock


def analyses_with_status_count(db: Session) -> int:
    """Count analyses eligible for the learning loop.

    Must be: (1) triaged by the user (not da_valutare) AND (2) produced by
    prompt v7+ so they have a career_track assigned. Pre-v7 analyses are
    excluded because a run on mixed data would poison the user profile.
    """
    return int(
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status.in_(["candidato", "colloquio", "offerta", "scartato", "rifiutato"]),
            JobAnalysis.career_track.isnot(None),
        )
        .count()
    )


def get_lock_state(db: Session) -> dict[str, Any]:
    """Return lock state: whether the user can run a new analytics pass.

    Unlocked when at least UNLOCK_THRESHOLD new triaged analyses exist since
    the last run. Always unlocked if no run has ever been executed.
    """
    last = db.query(AnalyticsRun).order_by(AnalyticsRun.created_at.desc()).first()
    current_count = analyses_with_status_count(db)

    if last is None:
        return {
            "locked": current_count < UNLOCK_THRESHOLD,
            "current": current_count,
            "threshold": UNLOCK_THRESHOLD,
            "last_run_count": 0,
            "new_since_last": current_count,
            "last_run_at": None,
        }

    new_since = max(0, current_count - (last.analyses_count or 0))
    return {
        "locked": new_since < UNLOCK_THRESHOLD,
        "current": current_count,
        "threshold": UNLOCK_THRESHOLD,
        "last_run_count": last.analyses_count,
        "new_since_last": new_since,
        "last_run_at": last.created_at.isoformat() if last.created_at else None,
    }


def _build_profile(snapshot: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Synthesize a user profile JSON + short prompt snippet from a run snapshot."""
    disc = snapshot.get("discriminant", {})
    cat = disc.get("categorical", {})
    role_rows = cat.get("role_bucket", [])
    kept_total = disc.get("kept_total", 0)
    rejected_total = disc.get("rejected_total", 0)

    # Top 2 preferred role buckets by lift (among those with at least 3 kept)
    strong_roles = sorted(
        [r for r in role_rows if r.get("kept_count", 0) >= 3],
        key=lambda r: r.get("lift", 0),
        reverse=True,
    )[:2]
    weak_roles = sorted(
        [r for r in role_rows if r.get("rejected_count", 0) >= 3 and r.get("lift", 1) < 0.7],
        key=lambda r: r.get("lift", 1),
    )[:2]

    numeric = disc.get("numeric", {})
    score_delta = numeric.get("score", {}) or {}

    profile = {
        "kept_total": kept_total,
        "rejected_total": rejected_total,
        "prefer_roles": [r["value"] for r in strong_roles],
        "avoid_roles": [r["value"] for r in weak_roles],
        "kept_score_mean": score_delta.get("kept_mean"),
        "rejected_score_mean": score_delta.get("rejected_mean"),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    prefer = ", ".join(profile["prefer_roles"]) or "devops"
    avoid = ", ".join(profile["avoid_roles"]) or "cybersec senior"
    snippet = (
        f"Dati storici utente ({kept_total} tenuti vs {rejected_total} scartati su {kept_total + rejected_total} decisi). "
        f"Pattern preferiti: {prefer}. Pattern scartati di frequente: {avoid}. "
        f"Score medio kept: {profile['kept_score_mean']}, rejected: {profile['rejected_score_mean']}. "
        f"Usa questi segnali come contesto, non come regola assoluta — l'utente evolve."
    )

    return profile, snippet


def run_analytics(db: Session, user_id: UUID, triggered_by: str = "manual") -> AnalyticsRun:
    """Execute a full analytics pass and persist snapshot + user_profile."""
    analyses = db.query(JobAnalysis).order_by(JobAnalysis.created_at.asc()).all()
    features = [
        extract_features(
            {
                "id": str(a.id),
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "applied_at": a.applied_at.isoformat() if a.applied_at else None,
                "status": a.status or None,
                "company": a.company,
                "role": a.role,
                "location": a.location,
                "work_mode": a.work_mode,
                "salary_info": a.salary_info,
                "score": a.score,
                "recommendation": a.recommendation,
                "strengths": a.strengths or [],
                "gaps": a.gaps or [],
                "recruiter_info": a.recruiter_info or {},
                "experience_required": a.experience_required or {},
                "company_reputation": a.company_reputation or {},
                "career_track": a.career_track,
                "interviews": [],  # interviews are merged separately in report but not needed for profile
            }
        )
        for a in analyses
    ]

    snapshot: dict[str, Any] = {
        "counts_by_status": counts_by_status(features),
        "role_distribution": distribution(features, "role_bucket"),
        "career_track_distribution": distribution(features, "career_track")
        if any(f.get("career_track") for f in features)
        else {},
        "conversion_by_role": conversion_rate(features, "role_bucket"),
        "discriminant": discriminant_features(features),
        "bias_signals": bias_signals(features),
        "total_features": len(features),
    }

    run = AnalyticsRun(
        analyses_count=analyses_with_status_count(db),
        triggered_by=triggered_by,
        snapshot=snapshot,
    )
    db.add(run)
    db.flush()

    # Build + upsert user profile
    profile_data, snippet = _build_profile(snapshot)
    existing = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if existing:
        existing.profile = profile_data  # type: ignore[assignment]
        existing.prompt_snippet = snippet  # type: ignore[assignment]
        existing.source_run_id = run.id  # type: ignore[assignment]
        existing.updated_at = datetime.now(UTC)  # type: ignore[assignment]
    else:
        db.add(
            UserProfile(
                user_id=user_id,
                source_run_id=run.id,
                profile=profile_data,
                prompt_snippet=snippet,
            )
        )

    db.commit()
    return run


def get_user_profile_snippet(db: Session, user_id: UUID) -> str:
    """Fetch the current user profile snippet for prompt injection. Empty if none."""
    row = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not row:
        return ""
    return str(row.prompt_snippet or "")


def get_latest_runs(db: Session, limit: int = 5) -> list[AnalyticsRun]:
    """Return the latest analytics runs for trend display."""
    return list(db.query(AnalyticsRun).order_by(AnalyticsRun.created_at.desc()).limit(limit).all())
