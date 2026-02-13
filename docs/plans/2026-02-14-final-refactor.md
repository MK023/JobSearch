# Final Refactor & Polish Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor, clean up, and polish the Job Search Command Center for daily production use — better cache, delete analysis, split files, improved UI, lint compliance.

**Architecture:** Server-side Jinja2 with extracted static assets (CSS/JS), FastAPI lifespan, content-hash based duplicate detection at DB level, ruff for linting. No new frameworks.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL 16, Redis 7, Jinja2, ruff

---

### Task 1: Lint setup with ruff

**Files:**
- Create: `pyproject.toml`
- Modify: `backend/src/config.py:1-4` (remove unused `import os`)

**Step 1: Create pyproject.toml**

Create `pyproject.toml` at project root:

```toml
[project]
name = "jobsearch"
version = "1.0.0"
requires-python = ">=3.12"

[tool.ruff]
target-version = "py312"
line-length = 120
src = ["backend/src"]

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # bugbear
    "UP",  # pyupgrade
    "SIM", # simplify
]
ignore = [
    "E501",  # line length (handled by formatter)
    "B008",  # function call in default arg (FastAPI Depends)
]

[tool.ruff.lint.isort]
known-first-party = ["src"]
```

**Step 2: Remove unused import from config.py**

In `backend/src/config.py`, remove `import os` (line 3) — it is unused.

**Step 3: Run ruff and fix all issues**

```bash
pip install ruff
ruff check backend/src/ --fix
ruff format backend/src/
```

Fix any remaining issues manually.

**Step 4: Commit**

```bash
git add pyproject.toml backend/src/
git commit -m "chore: add ruff linting config and fix all lint issues"
```

---

### Task 2: Code cleanup — lifespan + API key validation

**Files:**
- Modify: `backend/src/app.py:1-28` (replace on_event with lifespan, add key check)

**Step 1: Replace deprecated @app.on_event("startup") with lifespan**

In `backend/src/app.py`, replace the startup event and app creation (lines 19-27) with:

```python
from contextlib import asynccontextmanager

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
```

Remove the old `@app.on_event("startup")` function and the `Depends` import if no longer needed (it is still needed for get_db).

Remove `asynccontextmanager` if already imported elsewhere; add it to imports at top.

**Step 2: Verify app starts correctly**

```bash
cd /Users/marcobellingeri/Documents/GitHub/JobSearch
docker compose up --build backend
```

Check logs for "Avvio Job Search Command Center" and "Database inizializzato" messages. If ANTHROPIC_API_KEY is set, it should start normally. If not set, it should fail with clear error.

**Step 3: Commit**

```bash
git add backend/src/app.py
git commit -m "refactor: migrate to FastAPI lifespan, add API key validation at startup"
```

---

### Task 3: Cache anti-duplicates with content hash

**Files:**
- Modify: `backend/src/database.py` (add content_hash column + index)
- Modify: `backend/src/ai_client.py:82-84` (use full content hash)
- Modify: `backend/src/app.py:157-217` (check DB for existing analysis before API call)

**Step 1: Add content_hash column to JobAnalysis**

In `backend/src/database.py`, add to the JobAnalysis class after `job_url` (line 44):

```python
content_hash = Column(String(64), default="", index=True)
```

Add the auto-migration in `init_db()`:

```python
_add_column_if_missing(conn, "job_analyses", "content_hash", "VARCHAR(64) DEFAULT ''")
```

**Step 2: Create a content hash helper**

In `backend/src/ai_client.py`, replace the `_cache_key` function (lines 82-84) to use full text:

```python
def _content_hash(cv_text: str, job_description: str) -> str:
    """SHA-256 hash of full CV + job description for duplicate detection."""
    content = f"{cv_text}:{job_description}"
    return hashlib.sha256(content.encode()).hexdigest()


def _cache_key(content_hash: str, model: str) -> str:
    return f"analysis:{model}:{content_hash[:16]}"
```

Update `analyze_job` to use the new functions:

```python
def analyze_job(cv_text: str, job_description: str, model: str = "haiku") -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])
    ch = _content_hash(cv_text, job_description)

    # Check Redis cache
    r = _get_redis()
    if r:
        key = _cache_key(ch, model)
        cached = r.get(key)
        ...
```

Also update the cache write to use the new key format.

Export `_content_hash` by adding it to the module-level (it will be imported by app.py).

**Step 3: Check DB for existing analysis in app.py run_analysis**

In `backend/src/app.py`, modify `run_analysis()` to check DB before calling AI:

```python
from .ai_client import analyze_job, generate_cover_letter, _content_hash

# Inside run_analysis(), after getting the CV and before calling analyze_job:
    content_hash = _content_hash(cv.raw_text, job_description)

    # Check for existing identical analysis
    existing = db.query(JobAnalysis).filter(
        JobAnalysis.content_hash == content_hash
    ).order_by(JobAnalysis.created_at.desc()).first()

    if existing:
        logger.info("Analisi duplicata trovata: id=%s, score=%s", existing.id, existing.score)
        result = {... rebuild from existing ...}
        return templates.TemplateResponse(
            "index.html",
            _base_context(request, db, current=existing, result=result,
                         message=f"Analisi gia' eseguita il {existing.created_at.strftime('%d/%m/%Y %H:%M')} — mostro il risultato salvato"),
        )
```

When saving a NEW analysis, include the content_hash:

```python
    analysis = JobAnalysis(
        cv_id=cv.id,
        content_hash=content_hash,
        job_description=job_description,
        ...
    )
```

**Step 4: Update batch to also save content_hash**

In `_run_batch()`, compute and save the content_hash for each batch item.

**Step 5: Commit**

```bash
git add backend/src/database.py backend/src/ai_client.py backend/src/app.py
git commit -m "feat: add content-hash duplicate detection to save API tokens"
```

---

### Task 4: Delete analysis with cascade

**Files:**
- Modify: `backend/src/app.py` (add DELETE endpoint)
- Modify: `backend/templates/index.html` (add delete button + JS)

**Step 1: Add DELETE endpoint in app.py**

Add after the `update_status` endpoint:

```python
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

    # Cascade: delete associated cover letters
    db.query(CoverLetter).filter(CoverLetter.analysis_id == analysis.id).delete()
    db.delete(analysis)
    db.commit()
    logger.info("Analisi eliminata: id=%s, role=%s @ %s", analysis_id, analysis.role, analysis.company)

    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": True})
    return RedirectResponse(url="/", status_code=303)
```

**Step 2: Add delete button in the actions section of index.html**

In the `<!-- 7. AZIONI -->` section, add a delete button after the pill-group:

```html
<button class="btn btn-r btn-s" onclick="deleteAnalysis('{{ current.id }}')">🗑️ Elimina</button>
```

Add in the history list, a small delete button per item.

**Step 3: Add JS function for delete**

```javascript
function deleteAnalysis(id){
    if(!confirm('Sei sicuro di voler eliminare questa analisi?'))return;
    fetch('/analysis/'+id,{method:'DELETE',headers:{'Accept':'application/json'}})
    .then(function(r){return r.json();}).then(function(data){
        if(data.ok) window.location.href='/';
    });
}
```

**Step 4: Commit**

```bash
git add backend/src/app.py backend/templates/index.html
git commit -m "feat: add delete analysis with cascade on cover letters"
```

---

### Task 5: Extract CSS to static file

**Files:**
- Create: `backend/static/css/style.css`
- Modify: `backend/templates/index.html:7-165` (replace inline `<style>` with `<link>`)
- Modify: `backend/src/app.py` (mount static files)

**Step 1: Mount static files in app.py**

Add to `backend/src/app.py` after app creation:

```python
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")
```

**Step 2: Create backend/static/css/style.css**

Move the entire content of the `<style>` tag (lines 8-164 of index.html) into `backend/static/css/style.css`.

**Step 3: Replace the `<style>` tag in index.html**

Replace lines 7-165 with:

```html
<link rel="stylesheet" href="/static/css/style.css">
```

**Step 4: Verify styling works**

Open http://localhost:8000 and verify all styles render correctly.

**Step 5: Commit**

```bash
git add backend/static/css/style.css backend/templates/index.html backend/src/app.py
git commit -m "refactor: extract CSS to static/css/style.css"
```

---

### Task 6: Extract JS to static file

**Files:**
- Create: `backend/static/js/app.js`
- Modify: `backend/templates/index.html:473-599` (replace inline `<script>` with `<script src>`)

**Step 1: Create backend/static/js/app.js**

Move the entire content of the `<script>` tag (lines 473-599 of index.html) into `backend/static/js/app.js`.

Note: The cover letter form listener (`var clf=...`) must handle the case where `#clf` doesn't exist on the page (it already does with the `if(clf)` check). Same for `#hist-tabs`.

**Step 2: Replace the `<script>` tag in index.html**

Replace lines 472-600 with:

```html
<script src="/static/js/app.js"></script>
```

**Step 3: Verify JS functionality works**

Test: submit analysis form (loading spinner appears), pill status change, tab switching, batch add/run/clear, cover letter form loading spinner.

**Step 4: Commit**

```bash
git add backend/static/js/app.js backend/templates/index.html
git commit -m "refactor: extract JS to static/js/app.js"
```

---

### Task 7: Improve Glassdoor UI

**Files:**
- Modify: `backend/static/css/style.css` (add reputation styles)
- Modify: `backend/templates/index.html:331-348` (improved reputation section)

**Step 1: Add reputation-specific CSS**

Add to `style.css`:

```css
/* Reputation section */
.rep-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}
@media(max-width:768px){.rep-grid{grid-template-columns:1fr}}
.rep-col{padding:10px 12px;border-radius:8px}
.rep-pros{background:#064e3b;border:1px solid #065f46}
.rep-cons{background:#450a0a;border:1px solid #7f1d1d}
.rep-label{font-size:.78rem;font-weight:700;margin-bottom:6px}
.rep-label-pro{color:#34d399}
.rep-label-con{color:#f87171}
.rep-item{font-size:.82rem;line-height:1.5;padding:4px 0;color:#cbd5e1}
.rep-item::before{margin-right:6px}
.rep-rating{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:8px;font-weight:700;font-size:.95rem}
.rep-rating-good{background:#064e3b;color:#34d399;border:1px solid #065f46}
.rep-rating-mid{background:#78350f;color:#fbbf24;border:1px solid #92400e}
.rep-rating-low{background:#7f1d1d;color:#f87171;border:1px solid #991b1b}
.rep-rating-na{background:#334155;color:#94a3b8;border:1px solid #475569}
.rep-note{font-size:.72rem;color:#64748b;margin-top:8px;font-style:italic}
```

**Step 2: Replace the reputation details section in index.html**

Replace the existing reputation `<details>` block (lines 331-348) with improved 2-column layout:

```html
{% if result.company_reputation and (result.company_reputation.known_pros or result.company_reputation.known_cons) %}
<details style="margin-bottom:16px" open>
    <summary>🏢 Reputazione aziendale
        {% set gr_str = result.company_reputation.glassdoor_estimate|default('non disponibile') %}
        {% if gr_str != 'non disponibile' %}
        {% set gr = gr_str|replace('/5','')|float %}
        <span class="rep-rating {% if gr >= 4.0 %}rep-rating-good{% elif gr >= 3.0 %}rep-rating-mid{% else %}rep-rating-low{% endif %}">
            ⭐ {{ gr_str }}
        </span>
        {% else %}
        <span class="rep-rating rep-rating-na">⭐ n/d</span>
        {% endif %}
    </summary>
    <div class="rep-grid">
        {% if result.company_reputation.known_pros %}
        <div class="rep-col rep-pros">
            <div class="rep-label rep-label-pro">👍 Punti di forza</div>
            {% for p in result.company_reputation.known_pros %}
            <div class="rep-item">✅ {{ p }}</div>
            {% endfor %}
        </div>
        {% endif %}
        {% if result.company_reputation.known_cons %}
        <div class="rep-col rep-cons">
            <div class="rep-label rep-label-con">👎 Criticita'</div>
            {% for c in result.company_reputation.known_cons %}
            <div class="rep-item">⚠️ {{ c }}</div>
            {% endfor %}
        </div>
        {% endif %}
    </div>
    {% if result.company_reputation.note %}
    <div class="rep-note">⚠️ {{ result.company_reputation.note }}</div>
    {% endif %}
</details>
{% endif %}
```

**Step 3: Commit**

```bash
git add backend/static/css/style.css backend/templates/index.html
git commit -m "feat: improve Glassdoor reputation UI with 2-column layout and rating badge"
```

---

### Task 8: Final ruff pass + verify

**Step 1: Run ruff on all Python files**

```bash
ruff check backend/src/ --fix
ruff format backend/src/
```

**Step 2: Verify the full app works**

```bash
docker compose up --build
```

Test all functionality:
- Save CV
- Run analysis (verify duplicate detection on re-submit)
- View analysis detail
- Change status via pills
- Generate cover letter
- Delete analysis
- Batch analysis
- Check all CSS/JS loads from static files
- Check Glassdoor section renders correctly

**Step 3: Final commit if any changes**

```bash
git add -A
git commit -m "chore: final lint pass and cleanup"
```
