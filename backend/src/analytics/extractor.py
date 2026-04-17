"""Feature extraction from raw analysis dicts into flat numeric/categorical features.

Input: list[dict] as exported by /api/v1/admin/export/analyses.
Output: list[dict] of flat features ready for pandas / stats.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Canonical role buckets — lowercased keywords → bucket label.
# Order matters: more specific matches first.
ROLE_BUCKETS: list[tuple[str, tuple[str, ...]]] = [
    ("cybersec", ("cybersec", "security engineer", "soc ", "penetration", "appsec", "pentester")),
    ("cloud", ("cloud engineer", "cloud architect", "cloud devops", "aws engineer", "azure engineer", "gcp engineer")),
    ("devops", ("devops", "sre ", "site reliability", "platform engineer", "infrastructure engineer")),
    ("data", ("data engineer", "data scientist", "data analyst", "analytics engineer", "machine learning", " ml ")),
    ("backend", ("backend", "back-end", "back end", "api developer", "microservice")),
    ("fullstack", ("full stack", "full-stack", "fullstack")),
    ("frontend", ("frontend", "front-end", "front end", "react", "vue")),
    ("mobile", ("ios", "android", "mobile")),
    ("qa", ("qa ", "tester", "quality assurance", "automation tester")),
]


def _role_bucket(role: str | None) -> str:
    if not role:
        return "other"
    r = role.lower()
    for bucket, keywords in ROLE_BUCKETS:
        if any(kw in r for kw in keywords):
            return bucket
    return "other"


def _location_bucket(location: str | None) -> str:
    if not location:
        return "unknown"
    loc = location.lower()
    if any(w in loc for w in ("remoto", "remote")):
        return "remote"
    if any(w in loc for w in ("ibrido", "hybrid")):
        return "hybrid"
    if any(w in loc for w in ("milano", "roma", "torino", "bologna", "firenze", "napoli", "genova")):
        return "italy_major"
    if any(w in loc for w in ("italia", "italy")):
        return "italy_other"
    if any(w in loc for w in ("london", "berlin", "paris", "amsterdam", "madrid", "dublin")):
        return "eu_major"
    return "other"


_SALARY_RE = re.compile(r"(\d{1,3}(?:[.,]?\d{3})?)\s*[-–—a]\s*(\d{1,3}(?:[.,]?\d{3})?)", re.I)
_SINGLE_SALARY_RE = re.compile(r"(\d{2,3}(?:[.,]?\d{3})?)\s*[kK€]")


def _parse_salary_midpoint(salary_info: str | None) -> int | None:
    """Extract a rough salary midpoint in EUR thousands, or None."""
    if not salary_info:
        return None
    text = salary_info.replace(".", "").replace(",", "")
    m = _SALARY_RE.search(text)
    if m:
        try:
            low = int(m.group(1))
            high = int(m.group(2))
            mid = (low + high) // 2
            # Heuristic: if in euros (e.g. 40000), convert to k
            return mid // 1000 if mid > 1000 else mid
        except ValueError:
            return None
    m2 = _SINGLE_SALARY_RE.search(salary_info)
    if m2:
        try:
            val = int(m2.group(1).replace(".", "").replace(",", ""))
            return val // 1000 if val > 1000 else val
        except ValueError:
            return None
    return None


def _is_piva(recruiter_info: dict[str, Any] | None) -> bool | None:
    if not recruiter_info:
        return None
    val = recruiter_info.get("is_freelance")
    return bool(val) if val is not None else None


def _is_body_rental(recruiter_info: dict[str, Any] | None) -> bool | None:
    if not recruiter_info:
        return None
    val = recruiter_info.get("is_body_rental")
    return bool(val) if val is not None else None


def _is_recruiter(recruiter_info: dict[str, Any] | None) -> bool | None:
    if not recruiter_info:
        return None
    val = recruiter_info.get("is_recruiter")
    return bool(val) if val is not None else None


def _gap_severities(gaps: list[Any]) -> dict[str, int]:
    counts = {"bloccante": 0, "importante": 0, "minore": 0}
    for g in gaps or []:
        if isinstance(g, dict):
            sev = g.get("severity", "").lower()
            if sev in counts:
                counts[sev] += 1
    return counts


def _experience_level(exp_req: dict[str, Any] | None) -> str | None:
    if not exp_req:
        return None
    level = exp_req.get("level")
    if isinstance(level, str) and level:
        return level.lower()
    return None


def _years_required(exp_req: dict[str, Any] | None) -> int | None:
    if not exp_req:
        return None
    ymin = exp_req.get("years_min")
    ymax = exp_req.get("years_max")
    if isinstance(ymin, int) and isinstance(ymax, int):
        return (ymin + ymax) // 2
    if isinstance(ymin, int):
        return ymin
    if isinstance(ymax, int):
        return ymax
    return None


def _interview_stats(interviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize interview rounds for an analysis."""
    if not interviews:
        return {"interview_count": 0, "any_passed": False, "any_rejected": False, "last_outcome": None}
    outcomes = [i.get("outcome") for i in interviews]
    last = sorted(interviews, key=lambda i: i.get("scheduled_at") or "", reverse=True)
    return {
        "interview_count": len(interviews),
        "any_passed": any(o == "passed" for o in outcomes),
        "any_rejected": any(o == "rejected" for o in outcomes),
        "last_outcome": last[0].get("outcome") if last else None,
    }


def extract_features(analysis: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw analysis dict into features suitable for stats/pandas."""
    recruiter = analysis.get("recruiter_info") or {}
    exp_req = analysis.get("experience_required") or {}
    company_rep = analysis.get("company_reputation") or {}
    gaps = analysis.get("gaps") or []
    strengths = analysis.get("strengths") or []
    iv_stats = _interview_stats(analysis.get("interviews") or [])
    gap_sev = _gap_severities(gaps)

    return {
        "id": analysis.get("id"),
        "created_at": analysis.get("created_at"),
        "applied_at": analysis.get("applied_at"),
        "status": analysis.get("status"),
        "company": analysis.get("company"),
        "role": analysis.get("role"),
        "role_bucket": _role_bucket(analysis.get("role")),
        "location_bucket": _location_bucket(analysis.get("location")),
        "work_mode": analysis.get("work_mode") or "unknown",
        "score": analysis.get("score") or 0,
        "recommendation": analysis.get("recommendation"),
        "model_used": analysis.get("model_used"),
        "cost_usd": analysis.get("cost_usd") or 0.0,
        "salary_midpoint_k": _parse_salary_midpoint(analysis.get("salary_info")),
        "is_piva": _is_piva(recruiter),
        "is_body_rental": _is_body_rental(recruiter),
        "is_recruiter": _is_recruiter(recruiter),
        "experience_level": _experience_level(exp_req),
        "years_required": _years_required(exp_req),
        "strengths_count": len(strengths),
        "gaps_count": len(gaps),
        "gaps_blocking": gap_sev["bloccante"],
        "gaps_important": gap_sev["importante"],
        "gaps_minor": gap_sev["minore"],
        "glassdoor_rating": company_rep.get("glassdoor_rating") or company_rep.get("glassdoor_estimate"),
        "review_count": company_rep.get("review_count"),
        "followed_up": analysis.get("followed_up"),
        **iv_stats,
    }


def feature_summary(features: list[dict[str, Any]]) -> dict[str, Any]:
    """Quick summary of extracted features for sanity checks."""
    if not features:
        return {"total": 0}

    def _dates(f: dict[str, Any]) -> datetime | None:
        raw = f.get("created_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

    dates = [d for d in (_dates(f) for f in features) if d is not None]
    return {
        "total": len(features),
        "with_status": sum(1 for f in features if f.get("status")),
        "with_score": sum(1 for f in features if f.get("score", 0) > 0),
        "with_salary": sum(1 for f in features if f.get("salary_midpoint_k")),
        "with_interviews": sum(1 for f in features if f.get("interview_count", 0) > 0),
        "date_range": {
            "first": min(dates).isoformat() if dates else None,
            "last": max(dates).isoformat() if dates else None,
        },
    }
