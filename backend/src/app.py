import json
import logging
import uuid as uuid_mod
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .ai_client import MODELS, _content_hash, analyze_job, generate_cover_letter, generate_followup_email, generate_linkedin_message
from .config import settings, setup_logging
from .database import AppSettings, Contact, CoverLetter, CVProfile, JobAnalysis, SessionLocal, get_db, init_db
from .glassdoor import fetch_glassdoor_rating

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
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")


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
                batch_model_id = MODELS.get(item.get("model", "haiku"), MODELS["haiku"])
                existing = (
                    db.query(JobAnalysis)
                    .filter(
                        JobAnalysis.content_hash == batch_content_hash,
                        JobAnalysis.model_used == batch_model_id,
                    )
                    .first()
                )
                if existing:
                    item["status"] = "done"
                    item["result_preview"] = f"{existing.role} @ {existing.company} -- {existing.score}/100 (duplicato)"
                    logger.info("Batch %s [%d/%d]: duplicato trovato, skip API", batch_id[:8], idx, total)
                    continue
                result = analyze_job(cv.raw_text, item["job_description"], item.get("model", "haiku"))
                _merge_glassdoor(result)
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
                _spending_add(db, result.get("cost_usd", 0.0), result.get("tokens", {}).get("input", 0), result.get("tokens", {}).get("output", 0))
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


def _get_or_create_settings(db: Session) -> AppSettings:
    s = db.query(AppSettings).first()
    if not s:
        s = AppSettings(id=1, anthropic_budget=0.0)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _check_today_reset(s: AppSettings):
    """Reset contatori giornalieri se la data e' cambiata."""
    from datetime import date
    today = date.today().isoformat()
    if (s.today_date or "") != today:
        s.today_date = today
        s.today_cost_usd = 0.0
        s.today_tokens_input = 0
        s.today_tokens_output = 0
        s.today_analyses = 0


def _spending_add(db: Session, cost: float, tokens_in: int, tokens_out: int, is_analysis: bool = True):
    """Aggiorna i totali in app_settings dopo un insert."""
    s = _get_or_create_settings(db)
    _check_today_reset(s)
    s.total_cost_usd = round((s.total_cost_usd or 0) + cost, 6)
    s.total_tokens_input = (s.total_tokens_input or 0) + tokens_in
    s.total_tokens_output = (s.total_tokens_output or 0) + tokens_out
    s.today_cost_usd = round((s.today_cost_usd or 0) + cost, 6)
    s.today_tokens_input = (s.today_tokens_input or 0) + tokens_in
    s.today_tokens_output = (s.today_tokens_output or 0) + tokens_out
    if is_analysis:
        s.total_analyses = (s.total_analyses or 0) + 1
        s.today_analyses = (s.today_analyses or 0) + 1
    else:
        s.total_cover_letters = (s.total_cover_letters or 0) + 1


def _spending_remove(db: Session, cost: float, tokens_in: int, tokens_out: int, is_analysis: bool = True, created_today: bool = False):
    """Aggiorna i totali in app_settings dopo un delete."""
    s = _get_or_create_settings(db)
    _check_today_reset(s)
    s.total_cost_usd = round(max((s.total_cost_usd or 0) - cost, 0), 6)
    s.total_tokens_input = max((s.total_tokens_input or 0) - tokens_in, 0)
    s.total_tokens_output = max((s.total_tokens_output or 0) - tokens_out, 0)
    if is_analysis:
        s.total_analyses = max((s.total_analyses or 0) - 1, 0)
    else:
        s.total_cover_letters = max((s.total_cover_letters or 0) - 1, 0)
    if created_today:
        s.today_cost_usd = round(max((s.today_cost_usd or 0) - cost, 0), 6)
        s.today_tokens_input = max((s.today_tokens_input or 0) - tokens_in, 0)
        s.today_tokens_output = max((s.today_tokens_output or 0) - tokens_out, 0)
        if is_analysis:
            s.today_analyses = max((s.today_analyses or 0) - 1, 0)


def _get_spending(db: Session) -> dict:
    """Legge i totali direttamente da app_settings - nessuna query aggregata."""
    s = _get_or_create_settings(db)
    _check_today_reset(s)
    db.commit()
    budget = float(s.anthropic_budget or 0)
    total_cost = float(s.total_cost_usd or 0)
    remaining = round(budget - total_cost, 4) if budget > 0 else None
    return {
        "budget": round(budget, 2),
        "total_cost_usd": round(total_cost, 4),
        "remaining": remaining,
        "total_analyses": int(s.total_analyses or 0),
        "total_tokens_input": int(s.total_tokens_input or 0),
        "total_tokens_output": int(s.total_tokens_output or 0),
        "today_cost_usd": round(float(s.today_cost_usd or 0), 4),
        "today_analyses": int(s.today_analyses or 0),
        "today_tokens_input": int(s.today_tokens_input or 0),
        "today_tokens_output": int(s.today_tokens_output or 0),
    }


def _parse_full_response(raw: str) -> dict:
    """Parse the stored full_response JSON, handling markdown wrapping."""
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, TypeError):
                pass
    return {}


def _rebuild_result(analysis: JobAnalysis, from_cache: bool = False) -> dict:
    """Rebuild full result dict from stored analysis row."""
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
        "from_cache": from_cache,
    }

    # Extract extra fields from full_response (score_label, application_method, etc.)
    full = _parse_full_response(analysis.full_response)
    for key in ("score_label", "potential_score", "gap_timeline", "confidence",
                "confidence_reason", "summary", "application_method"):
        if key in full:
            result[key] = full[key]

    return result


def _base_context(request: Request, db: Session, **extra) -> dict:
    from datetime import datetime as dt, timedelta
    cv = db.query(CVProfile).order_by(CVProfile.updated_at.desc()).first()
    analyses = db.query(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(50).all()

    # Follow-up alerts: candidature con applied_at > 5 giorni e non followed_up
    threshold = dt.utcnow() - timedelta(days=5)
    followup_alerts = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status.in_(["candidato", "colloquio"]),
            JobAnalysis.applied_at.isnot(None),
            JobAnalysis.applied_at <= threshold,
            JobAnalysis.followed_up == False,
        )
        .order_by(JobAnalysis.applied_at.asc())
        .all()
    )

    # Dashboard motivazionale
    total_analyses = len(analyses)
    applied = sum(1 for a in analyses if a.status in ("candidato", "colloquio"))
    avg_score = round(sum(a.score or 0 for a in analyses) / total_analyses, 1) if total_analyses else 0
    top_match = max((a for a in analyses if a.status != "scartato"), key=lambda a: a.score or 0, default=None) if analyses else None

    active_apps = [a for a in analyses if a.status in ("candidato", "colloquio")]

    dashboard = {
        "total": total_analyses,
        "applied": applied,
        "interviews": sum(1 for a in analyses if a.status == "colloquio"),
        "skipped": sum(1 for a in analyses if a.status == "scartato"),
        "pending": sum(1 for a in analyses if a.status == "da_valutare"),
        "avg_score": avg_score,
        "top_match": top_match,
        "followup_count": len(followup_alerts),
    }

    ctx = {
        "request": request,
        "cv": cv,
        "analyses": analyses,
        "spending": _get_spending(db),
        "followup_alerts": followup_alerts,
        "dashboard": dashboard,
        "active_apps": active_apps,
    }
    ctx.update(extra)
    return ctx


def _merge_glassdoor(result: dict):
    """Merge Glassdoor API data into result's company_reputation, if available."""
    company = result.get("company", "")
    if not company:
        return
    gd = fetch_glassdoor_rating(company)
    if not gd:
        return
    rep = result.get("company_reputation", {}) or {}
    review_count = gd.get("review_count", 0)
    rep["glassdoor_estimate"] = f"{gd['glassdoor_rating']:.1f}/5"
    rep["review_count"] = review_count
    rep["sub_ratings"] = gd.get("sub_ratings", {})
    rep["ceo_name"] = gd.get("ceo_name", "")
    rep["ceo_approval"] = gd.get("ceo_approval")
    rep["recommend_to_friend"] = gd.get("recommend_to_friend")
    rep["business_outlook"] = gd.get("business_outlook")
    rep["glassdoor_url"] = gd.get("glassdoor_url", "")
    rep["source"] = "glassdoor_api"
    count_fmt = f"{review_count:,}".replace(",", ".") if review_count else "n/d"
    rep["note"] = f"Fonte: Glassdoor ({count_fmt} recensioni)"
    result["company_reputation"] = rep


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


@app.get("/cv/download")
def download_cv(db: Session = Depends(get_db)):
    cv = db.query(CVProfile).order_by(CVProfile.updated_at.desc()).first()
    if not cv:
        return RedirectResponse(url="/", status_code=303)
    filename = f"CV_{cv.name or 'senza_nome'}.txt".replace(" ", "_")
    return PlainTextResponse(
        cv.raw_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    model_id = MODELS.get(model, MODELS["haiku"])
    existing = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.content_hash == content_hash,
            JobAnalysis.model_used == model_id,
        )
        .order_by(JobAnalysis.created_at.desc())
        .first()
    )

    if existing:
        logger.info("Analisi duplicata trovata: id=%s, score=%s", existing.id, existing.score)
        result = _rebuild_result(existing, from_cache=True)
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

    # Merge Glassdoor real data into company_reputation
    _merge_glassdoor(result)

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
    _spending_add(db, result.get("cost_usd", 0.0), result.get("tokens", {}).get("input", 0), result.get("tokens", {}).get("output", 0))
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

    result = _rebuild_result(analysis)

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
        if new_status in ("candidato", "colloquio") and not analysis.applied_at:
            from datetime import datetime as dt
            analysis.applied_at = dt.utcnow()
        db.commit()
        logger.info("Status aggiornato: analysis=%s, %s -> %s", analysis_id, old_status, new_status)
    else:
        logger.warning("Status update: analisi %s non trovata", analysis_id)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": True, "status": new_status})
    return RedirectResponse(url="/", status_code=303)


@app.delete("/analysis/{analysis_id}")
def delete_analysis(
    request: Request,
    analysis_id: str,
    db: Session = Depends(get_db),
):
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"error": "Analisi non trovata"}, status_code=404)
        return RedirectResponse(url="/", status_code=303)

    # Aggiorna totali: sottrai cover letters associate
    from datetime import date
    today = date.today()
    cover_letters = db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).all()
    for cl in cover_letters:
        cl_today = cl.created_at and cl.created_at.date() == today
        _spending_remove(db, cl.cost_usd or 0, cl.tokens_input or 0, cl.tokens_output or 0, is_analysis=False, created_today=cl_today)
    db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).delete()
    db.query(Contact).filter(Contact.analysis_id == analysis.id).delete()

    # Aggiorna totali: sottrai analisi
    a_today = analysis.created_at and analysis.created_at.date() == today
    _spending_remove(db, analysis.cost_usd or 0, analysis.tokens_input or 0, analysis.tokens_output or 0, is_analysis=True, created_today=a_today)
    db.delete(analysis)
    db.commit()
    logger.info("Analisi eliminata: id=%s, role=%s @ %s", analysis_id, analysis.role, analysis.company)

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": True})
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
    _spending_add(db, result.get("cost_usd", 0.0), result.get("tokens", {}).get("input", 0), result.get("tokens", {}).get("output", 0), is_analysis=False)
    db.commit()

    # Passa current + result per mantenere visibili sia l'analisi che il form cover letter
    analysis_result = _rebuild_result(analysis)
    return templates.TemplateResponse(
        "index.html",
        _base_context(
            request,
            db,
            current=analysis,
            result=analysis_result,
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


@app.get("/spending")
def spending_api(db: Session = Depends(get_db)):
    return JSONResponse(_get_spending(db))


@app.put("/spending/budget")
def update_budget(budget: float = Form(...), db: Session = Depends(get_db)):
    s = _get_or_create_settings(db)
    s.anthropic_budget = max(budget, 0)
    db.commit()
    logger.info("Budget aggiornato: $%.2f", s.anthropic_budget)
    return JSONResponse({"ok": True, "budget": round(s.anthropic_budget, 2)})


# ========== CONTACTS ==========

@app.post("/contacts")
def create_contact(
    analysis_id: str = Form(""),
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    company: str = Form(""),
    linkedin_url: str = Form(""),
    notes: str = Form(""),
    source: str = Form("manual"),
    db: Session = Depends(get_db),
):
    contact = Contact(
        analysis_id=analysis_id if analysis_id else None,
        name=name, email=email, phone=phone,
        company=company, linkedin_url=linkedin_url,
        notes=notes, source=source,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    logger.info("Contatto creato: %s (%s) per analisi %s", name, email, analysis_id or "nessuna")
    return JSONResponse({
        "ok": True,
        "contact": {
            "id": str(contact.id), "name": contact.name, "email": contact.email,
            "phone": contact.phone, "company": contact.company,
            "linkedin_url": contact.linkedin_url, "notes": contact.notes,
        },
    })


@app.get("/contacts/{analysis_id}")
def get_contacts(analysis_id: str, db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.analysis_id == analysis_id).order_by(Contact.created_at.desc()).all()
    return JSONResponse({
        "contacts": [
            {
                "id": str(c.id), "name": c.name, "email": c.email,
                "phone": c.phone, "company": c.company,
                "linkedin_url": c.linkedin_url, "notes": c.notes, "source": c.source,
            }
            for c in contacts
        ]
    })


@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        return JSONResponse({"error": "Contatto non trovato"}, status_code=404)
    db.delete(contact)
    db.commit()
    logger.info("Contatto eliminato: %s", contact_id)
    return JSONResponse({"ok": True})


# ========== FOLLOW-UP EMAIL ==========

@app.post("/followup-email")
def create_followup_email(
    request: Request,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
):
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return JSONResponse({"error": "Analisi non trovata"}, status_code=404)

    cv = db.query(CVProfile).filter(CVProfile.id == analysis.cv_id).first()
    if not cv:
        return JSONResponse({"error": "CV non trovato"}, status_code=404)

    from datetime import datetime as dt
    days_since = (dt.utcnow() - analysis.applied_at).days if analysis.applied_at else 7

    try:
        result = generate_followup_email(cv.raw_text, analysis.role, analysis.company, days_since, language, model)
    except Exception as e:
        logger.error("Follow-up email fallita: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

    _spending_add(db, result.get("cost_usd", 0.0), result.get("tokens", {}).get("input", 0), result.get("tokens", {}).get("output", 0), is_analysis=False)
    db.commit()
    logger.info("Follow-up email generata per %s @ %s, $%.6f", analysis.role, analysis.company, result.get("cost_usd", 0))
    return JSONResponse({"ok": True, **result})


# ========== LINKEDIN MESSAGE ==========

@app.post("/linkedin-message")
def create_linkedin_message(
    request: Request,
    analysis_id: str = Form(...),
    language: str = Form("italiano"),
    model: str = Form("haiku"),
    db: Session = Depends(get_db),
):
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return JSONResponse({"error": "Analisi non trovata"}, status_code=404)

    cv = db.query(CVProfile).filter(CVProfile.id == analysis.cv_id).first()
    if not cv:
        return JSONResponse({"error": "CV non trovato"}, status_code=404)

    # Cerca contatto associato per info
    contact = db.query(Contact).filter(Contact.analysis_id == analysis.id).first()
    contact_info = ""
    if contact:
        parts = []
        if contact.name:
            parts.append(f"Nome: {contact.name}")
        if contact.linkedin_url:
            parts.append(f"LinkedIn: {contact.linkedin_url}")
        contact_info = ", ".join(parts)

    try:
        result = generate_linkedin_message(cv.raw_text, analysis.role, analysis.company, contact_info, language, model)
    except Exception as e:
        logger.error("LinkedIn message fallita: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

    _spending_add(db, result.get("cost_usd", 0.0), result.get("tokens", {}).get("input", 0), result.get("tokens", {}).get("output", 0), is_analysis=False)
    db.commit()
    logger.info("LinkedIn message generata per %s @ %s, $%.6f", analysis.role, analysis.company, result.get("cost_usd", 0))
    return JSONResponse({"ok": True, **result})


# ========== FOLLOW-UP MARK ==========

@app.post("/followup-done/{analysis_id}")
def mark_followup_done(analysis_id: str, db: Session = Depends(get_db)):
    analysis = db.query(JobAnalysis).filter(JobAnalysis.id == analysis_id).first()
    if not analysis:
        return JSONResponse({"error": "Analisi non trovata"}, status_code=404)
    analysis.followed_up = True
    db.commit()
    logger.info("Follow-up segnato come fatto: %s", analysis_id)
    return JSONResponse({"ok": True})


# ========== DASHBOARD ==========

@app.get("/dashboard")
def dashboard_api(db: Session = Depends(get_db)):
    from datetime import datetime as dt, timedelta
    analyses = db.query(JobAnalysis).order_by(JobAnalysis.created_at.desc()).limit(50).all()
    total = len(analyses)
    applied = sum(1 for a in analyses if a.status in ("candidato", "colloquio"))
    avg_score = round(sum(a.score or 0 for a in analyses) / total, 1) if total else 0

    threshold = dt.utcnow() - timedelta(days=5)
    followup_count = (
        db.query(JobAnalysis)
        .filter(
            JobAnalysis.status.in_(["candidato", "colloquio"]),
            JobAnalysis.applied_at.isnot(None),
            JobAnalysis.applied_at <= threshold,
            JobAnalysis.followed_up == False,
        )
        .count()
    )

    top = max((a for a in analyses if a.status != "scartato"), key=lambda a: a.score or 0, default=None)

    return JSONResponse({
        "total": total,
        "applied": applied,
        "interviews": sum(1 for a in analyses if a.status == "colloquio"),
        "skipped": sum(1 for a in analyses if a.status == "scartato"),
        "pending": sum(1 for a in analyses if a.status == "da_valutare"),
        "avg_score": avg_score,
        "followup_count": followup_count,
        "top_match": {"role": top.role, "company": top.company, "score": top.score} if top else None,
    })
