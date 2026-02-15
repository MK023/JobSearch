"""Cover letter service."""

from sqlalchemy.orm import Session

from ..analysis.models import JobAnalysis
from ..integrations.anthropic_client import generate_cover_letter
from ..integrations.cache import CacheService
from .models import CoverLetter


def create_cover_letter(
    db: Session,
    analysis: JobAnalysis,
    cv_text: str,
    language: str,
    model: str = "haiku",
    cache: CacheService | None = None,
) -> tuple[CoverLetter, dict]:
    """Generate and persist a cover letter for an analysis."""
    analysis_data = {
        "role": analysis.role,
        "company": analysis.company,
        "score": analysis.score,
        "strengths": analysis.strengths or [],
        "gaps": analysis.gaps or [],
    }

    result = generate_cover_letter(
        cv_text, analysis.job_description, analysis_data, language, model, cache
    )

    cl = CoverLetter(
        analysis_id=analysis.id,
        language=language,
        content=result.get("cover_letter", ""),
        subject_lines=result.get("subject_lines", []),
        model_used=result.get("model_used", ""),
        tokens_input=result.get("tokens", {}).get("input", 0),
        tokens_output=result.get("tokens", {}).get("output", 0),
        cost_usd=result.get("cost_usd", 0.0),
    )
    db.add(cl)
    db.flush()
    return cl, result
