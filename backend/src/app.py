import json
import logging
import uuid as uuid_mod
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from .ai_client import _content_hash, analyze_job, generate_cover_letter
from .config import settings, setup_logging
from .database import CoverLetter, CVProfile, JobAnalysis, SessionLocal, get_db, init_db

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Avvio Job Search Command Center")
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY non configurata! L'app non funzionera'.")
        raise RuntimeError("ANTHROPIC_API_KEY mancante. Configura il file .env")
    init_db()
    logger.info("Database inizializzato")
    yield


app = FastAPI(title="Job Search Command Center", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


# Batch analysis state (in-memory)
batch_queue: dict[str, dict] = {}


def _run_batch(batch_id: str):
    """Background task to process batch analysis queue."""
    batch = batch_queue.get(batch_id)
    if not batch:
        return
    total = len(batch["items"])
    logger.info("Batch %s avviato: %d analisi in coda", batch_id[:8], total)
    batch["status"] = "running"
    db = SessionLocal()
    try:
        cv = db.query(CVProfile).order_by(CVProfile.updated_at.desc()).first()
        if not cv:
            batch["status"] = "error"
            batch["error"] = "Nessun CV trovato"
            logger.error("Batch %s fallito: nessun CV trovato", batch_id[:8])
            return
        for idx, item in enumerate(batch["items"], 1):
            if item["status"] == "cancelled":
                continue
            item["status"] = "running"
            logger.info("Batch %s [%d/%d]: analisi in corso", batch_id[:8], idx, total)
            try:
                batch_content_hash = _content_hash(cv.raw_text, item["job_description"])
                result = analyze_job(cv.raw_text, item["job_description"], item.get("model", "haiku"))
                analysis = JobAnalysis(
                    cv_id=cv.id,
                    job_description=item["job_description"],
                    job_url=item.get("job_url", ""),
                    content_hash=batch_content_hash,
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
                item["status"] = "done"
                item["result_preview"] = (
                    f"{result.get('role', '?')} @ {result.get('company', '?')} -- {result.get('score', 0)}/100"
                )
                logger.info("Batch %s [%d/%d]: completata - %s", batch_id[:8], idx, total, item["result_preview"])
            except Exception as e:
                item["status"] = "error"
                item["error"] = str(e)
                logger.error("Batch %s [%d/%d]: fallita - %s", batch_id[:8], idx, total, e, exc_info=True)
        done = sum(1 for i in batch["items"] if i["status"] == "done")
        errors = sum(1 for i in batch["items"] if i["status"] == "error")
        batch["status"] = "done"
        logger.info("Batch %s completato: %d ok, %d errori su %d totali", batch_id[:8], done, errors, total)
    finally:
        db.close()


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
    analyses = db.query(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(50).all()
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
        logger.info("CV aggiornato: name=%s, len=%d", cv_name, len(cv_text))
    else:
        existing = CVProfile(raw_text=cv_text, name=cv_name)
        db.add(existing)
        logger.info("CV creato: name=%s, len=%d", cv_name, len(cv_text))
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

    # Compute hash and check for existing identical analysis in DB
    content_hash = _content_hash(cv.raw_text, job_description)

    existing = (
        db.query(JobAnalysis)
        .filter(JobAnalysis.content_hash == content_hash)
        .order_by(JobAnalysis.created_at.desc())
        .first()
    )

    if existing:
        logger.info("Analisi duplicata trovata: id=%s, score=%s", existing.id, existing.score)
        # Rebuild result dict from stored data (same pattern as view_analysis)
        result = {
            "company": existing.company,
            "role": existing.role,
            "location": existing.location,
            "work_mode": existing.work_mode,
            "salary_info": existing.salary_info,
            "score": existing.score,
            "recommendation": existing.recommendation,
            "job_summary": existing.job_summary,
            "strengths": json.loads(existing.strengths) if existing.strengths else [],
            "gaps": json.loads(existing.gaps) if existing.gaps else [],
            "interview_scripts": json.loads(existing.interview_scripts) if existing.interview_scripts else [],
            "advice": existing.advice or "",
            "company_reputation": json.loads(existing.company_reputation) if existing.company_reputation else {},
            "summary": "",
            "model_used": existing.model_used,
            "tokens": {
                "input": existing.tokens_input or 0,
                "output": existing.tokens_output or 0,
                "total": (existing.tokens_input or 0) + (existing.tokens_output or 0),
            },
            "cost_usd": existing.cost_usd or 0.0,
            "from_cache": True,
        }
        return templates.TemplateResponse(
            "index.html",
            _base_context(
                request,
                db,
                current=existing,
                result=result,
                message=f"Analisi gia' eseguita il {existing.created_at.strftime('%d/%m/%Y %H:%M')} - mostro il risultato salvato (0 token usati)",
            ),
        )

    try:
        logger.info("Analisi avviata: model=%s, cv=%dc, jd=%dc", model, len(cv.raw_text), len(job_description))
        result = analyze_job(cv.raw_text, job_description, model)
        logger.info(
            "Analisi completata: score=%s, rec=%s, cache=%s, costo=$%.6f",
            result.get("score"),
            result.get("recommendation"),
            result.get("from_cache"),
            result.get("cost_usd", 0),
        )
    except Exception as e:
        logger.error("Analisi fallita: %s", e, exc_info=True)
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, error=f"Analisi AI fallita: {e}"),
        )

    analysis = JobAnalysis(
        cv_id=cv.id,
        job_description=job_description,
        job_url=job_url,
        content_hash=content_hash,
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
        old_status = analysis.status
        analysis.status = new_status
        db.commit()
        logger.info("Status aggiornato: analysis=%s, %s -> %s", analysis_id, old_status, new_status)
    else:
        logger.warning("Status update: analisi %s non trovata", analysis_id)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": True, "status": new_status})
    return RedirectResponse(url="/", status_code=303)


@app.post("/cover-letter", response_class=HTMLResponse)
def create_cover_letter(
    request: Request,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
):
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, error="Analisi non trovata"),
        )

    cv = db.query(CVProfile).filter(CVProfile.id == analysis.cv_id).first()
    if not cv:
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, error="CV non trovato"),
        )

    analysis_data = {
        "role": analysis.role,
        "company": analysis.company,
        "score": analysis.score,
        "strengths": json.loads(analysis.strengths) if analysis.strengths else [],
        "gaps": json.loads(analysis.gaps) if analysis.gaps else [],
    }

    try:
        logger.info("Cover letter avviata: analysis=%s, lang=%s, model=%s", analysis_id, language, model)
        result = generate_cover_letter(cv.raw_text, analysis.job_description, analysis_data, language, model)
        logger.info("Cover letter completata: costo=$%.6f", result.get("cost_usd", 0))
    except Exception as e:
        logger.error("Cover letter fallita: %s", e, exc_info=True)
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, error=f"Generazione cover letter fallita: {e}"),
        )

    cl = CoverLetter(
        analysis_id=analysis.id,
        language=language,
        content=result.get("cover_letter", ""),
        subject_lines=json.dumps(result.get("subject_lines", []), ensure_ascii=False),
        model_used=result.get("model_used", ""),
        tokens_input=result.get("tokens", {}).get("input", 0),
        tokens_output=result.get("tokens", {}).get("output", 0),
        cost_usd=result.get("cost_usd", 0.0),
    )
    db.add(cl)
    db.commit()

    return templates.TemplateResponse(
        "index.html",
        _base_context(
            request,
            db,
            cover_letter=cl,
            cover_letter_result=result,
            message=f"Cover letter generata! ({language})",
        ),
    )


@app.post("/batch/add")
def batch_add(
    job_description: str = Form(...),
    job_url: str = Form(""),
    model: str = Form("haiku"),
):
    active = None
    for bid, b in batch_queue.items():
        if b["status"] == "pending":
            active = (bid, b)
            break
    if not active:
        bid = str(uuid_mod.uuid4())
        batch_queue[bid] = {"items": [], "status": "pending"}
        active = (bid, batch_queue[bid])

    active[1]["items"].append(
        {
            "job_description": job_description,
            "job_url": job_url,
            "model": model,
            "status": "pending",
            "preview": job_description[:80] + "..." if len(job_description) > 80 else job_description,
        }
    )
    return JSONResponse({"ok": True, "batch_id": active[0], "count": len(active[1]["items"])})


@app.post("/batch/run")
def batch_run(background_tasks: BackgroundTasks):
    active = None
    for bid, b in batch_queue.items():
        if b["status"] == "pending":
            active = bid
            break
    if not active:
        return JSONResponse({"error": "Nessuna coda attiva"}, status_code=400)
    background_tasks.add_task(_run_batch, active)
    return JSONResponse({"ok": True, "batch_id": active})


@app.get("/batch/status")
def batch_status():
    for bid in reversed(list(batch_queue.keys())):
        return JSONResponse({"batch_id": bid, **batch_queue[bid]})
    return JSONResponse({"status": "empty"})


@app.delete("/batch/clear")
def batch_clear():
    to_remove = [bid for bid, b in batch_queue.items() if b["status"] in ("pending", "done")]
    for bid in to_remove:
        del batch_queue[bid]
    return JSONResponse({"ok": True})
