import json
import logging
from pathlib import Path

from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import settings
from .database import init_db, get_db, CVProfile, JobAnalysis
from .ai_client import analyze_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Job Search Command Center")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@app.on_event("startup")
def startup():
    init_db()


def _get_spending(db: Session) -> dict:
    row = db.query(
        func.coalesce(func.sum(JobAnalysis.cost_usd), 0.0),
        func.coalesce(func.sum(JobAnalysis.tokens_input), 0),
        func.coalesce(func.sum(JobAnalysis.tokens_output), 0),
        func.count(JobAnalysis.id),
    ).first()
    total = float(row[0])
    return {
        "total_cost_usd": round(total, 4),
        "total_tokens_input": int(row[1]),
        "total_tokens_output": int(row[2]),
        "total_analyses": int(row[3]),
        "balance_usd": round(settings.credit_budget_usd - total, 4),
    }


def _base_context(request: Request, db: Session, **extra) -> dict:
    cv = db.query(CVProfile).order_by(CVProfile.updated_at.desc()).first()
    analyses = (
        db.query(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(50).all()
    )
    ctx = {
        "request": request,
        "cv": cv,
        "analyses": analyses,
        "spending": _get_spending(db),
    }
    ctx.update(extra)
    return ctx


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("index.html", _base_context(request, db))


@app.post("/cv", response_class=HTMLResponse)
def save_cv(
    request: Request,
    cv_text: str = Form(...),
    cv_name: str = Form(""),
    db: Session = Depends(get_db),
):
    existing = db.query(CVProfile).first()
    if existing:
        existing.raw_text = cv_text
        existing.name = cv_name
    else:
        existing = CVProfile(raw_text=cv_text, name=cv_name)
        db.add(existing)
    db.commit()
    return templates.TemplateResponse(
        "index.html",
        _base_context(request, db, message="CV salvato!"),
    )


@app.post("/analyze", response_class=HTMLResponse)
def run_analysis(
    request: Request,
    job_description: str = Form(...),
    job_url: str = Form(""),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
):
    cv = db.query(CVProfile).order_by(CVProfile.updated_at.desc()).first()
    if not cv:
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, error="Salva prima il tuo CV!"),
        )

    try:
        logger.info(f"Analisi: model={model}, cv={len(cv.raw_text)}c, jd={len(job_description)}c")
        result = analyze_job(cv.raw_text, job_description, model)
        logger.info(f"Risultato: score={result.get('score')}, rec={result.get('recommendation')}, cache={result.get('from_cache')}")
    except Exception as e:
        logger.error(f"Analisi fallita: {e}")
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, error=f"Analisi AI fallita: {e}"),
        )

    analysis = JobAnalysis(
        cv_id=cv.id,
        job_description=job_description,
        job_url=job_url,
        job_summary=result.get("job_summary", ""),
        company=result.get("company", ""),
        role=result.get("role", ""),
        location=result.get("location", ""),
        work_mode=result.get("work_mode", ""),
        salary_info=result.get("salary_info", ""),
        score=result.get("score", 0),
        recommendation=result.get("recommendation", ""),
        strengths=json.dumps(result.get("strengths", []), ensure_ascii=False),
        gaps=json.dumps(result.get("gaps", []), ensure_ascii=False),
        interview_scripts=json.dumps(result.get("interview_scripts", []), ensure_ascii=False),
        advice=result.get("advice", ""),
        company_reputation=json.dumps(result.get("company_reputation", {}), ensure_ascii=False),
        full_response=result.get("full_response", ""),
        model_used=result.get("model_used", ""),
        tokens_input=result.get("tokens", {}).get("input", 0),
        tokens_output=result.get("tokens", {}).get("output", 0),
        cost_usd=result.get("cost_usd", 0.0),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return templates.TemplateResponse(
        "index.html",
        _base_context(request, db, current=analysis, result=result),
    )


@app.get("/analysis/{analysis_id}", response_class=HTMLResponse)
def view_analysis(request: Request, analysis_id: str, db: Session = Depends(get_db)):
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return RedirectResponse(url="/", status_code=303)

    # Rebuild result dict from stored data
    result = {
        "company": analysis.company,
        "role": analysis.role,
        "location": analysis.location,
        "work_mode": analysis.work_mode,
        "salary_info": analysis.salary_info,
        "score": analysis.score,
        "recommendation": analysis.recommendation,
        "job_summary": analysis.job_summary,
        "strengths": json.loads(analysis.strengths) if analysis.strengths else [],
        "gaps": json.loads(analysis.gaps) if analysis.gaps else [],
        "interview_scripts": json.loads(analysis.interview_scripts) if analysis.interview_scripts else [],
        "advice": analysis.advice or "",
        "company_reputation": json.loads(analysis.company_reputation) if analysis.company_reputation else {},
        "summary": "",
        "model_used": analysis.model_used,
        "tokens": {
            "input": analysis.tokens_input or 0,
            "output": analysis.tokens_output or 0,
            "total": (analysis.tokens_input or 0) + (analysis.tokens_output or 0),
        },
        "cost_usd": analysis.cost_usd or 0.0,
        "from_cache": False,
    }

    return templates.TemplateResponse(
        "index.html",
        _base_context(request, db, current=analysis, result=result),
    )


VALID_STATUSES = {"da_valutare", "candidato", "colloquio", "scartato"}


@app.post("/status/{analysis_id}/{new_status}")
def update_status(
    request: Request,
    analysis_id: str,
    new_status: str,
    db: Session = Depends(get_db),
):
    if new_status not in VALID_STATUSES:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": "invalid status"}, status_code=400)
        return RedirectResponse(url="/", status_code=303)
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if analysis:
        analysis.status = new_status
        db.commit()
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": True, "status": new_status})
    return RedirectResponse(url="/", status_code=303)
