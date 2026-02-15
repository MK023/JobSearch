"""Analysis JSON API routes (status changes, deletion)."""

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..audit.service import audit
from ..auth.models import User
from ..cover_letter.models import CoverLetter
from ..dashboard.service import remove_spending
from ..database import get_db
from ..dependencies import get_current_user
from .models import AnalysisStatus
from .service import get_analysis_by_id, update_status

router = APIRouter(tags=["analysis-api"])


@router.post("/status/{analysis_id}/{new_status}")
def change_status(
    request: Request,
    analysis_id: str,
    new_status: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        status_enum = AnalysisStatus(new_status)
    except ValueError:
        return JSONResponse({"error": "invalid status"}, status_code=400)

    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "not found"}, status_code=404)

    update_status(db, analysis, status_enum)
    audit(db, request, "status_change", f"id={analysis_id}, status={new_status}")
    db.commit()
    return JSONResponse({"ok": True, "status": new_status})


@router.delete("/analysis/{analysis_id}")
def delete_analysis(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    analysis = get_analysis_by_id(db, analysis_id)
    if not analysis:
        return JSONResponse({"error": "Analysis not found"}, status_code=404)

    today = date.today()

    cover_letters = db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).all()
    for cl in cover_letters:
        cl_today = cl.created_at and cl.created_at.date() == today
        remove_spending(db, cl.cost_usd or 0, cl.tokens_input or 0, cl.tokens_output or 0, is_analysis=False, created_today=cl_today)

    a_today = analysis.created_at and analysis.created_at.date() == today
    remove_spending(db, analysis.cost_usd or 0, analysis.tokens_input or 0, analysis.tokens_output or 0, is_analysis=True, created_today=a_today)

    audit(db, request, "delete_analysis", f"id={analysis_id}, {analysis.role} @ {analysis.company}")
    db.delete(analysis)
    db.commit()

    return JSONResponse({"ok": True})
