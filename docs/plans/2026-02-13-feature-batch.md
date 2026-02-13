# Feature Batch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add cover letter generation, Glassdoor auto-flag, batch analysis, UI improvements (reorder, pill actions, tab history) to Job Search Command Center.

**Architecture:** Server-side FastAPI + Jinja2, AJAX with vanilla fetch() for interactive elements, BackgroundTasks for batch processing. New CoverLetter DB table. Glassdoor info via AI prompt enhancement.

**Tech Stack:** Python 3.12, FastAPI (BackgroundTasks), SQLAlchemy, PostgreSQL 16, Redis 7, Anthropic Claude API, vanilla JS

---

## Task 1: Riordino UI - Spostare Consiglio dopo Forza/Lacune

**Files:**
- Modify: `backend/templates/index.html:232-238` (move advice-box block)

**Step 1: Move the advice-box HTML block**

In `backend/templates/index.html`, cut the advice-box section (lines 232-238) from its current position (after hero, before verdict) and paste it after the strengths/gaps grid (after line 292), before the interview section.

Current order in template:
```
hero -> advice-box -> verdict -> jd-box -> grid2 (strengths/gaps) -> interview -> actions
```

New order:
```
hero -> verdict -> jd-box -> grid2 (strengths/gaps) -> advice-box -> interview -> actions
```

The advice-box block to move is:
```html
        {% if result.advice %}
        <div class="advice-box">
            <div class="advice-title">Il mio consiglio per te</div>
            <div class="advice-text">{{ result.advice }}</div>
        </div>
        {% endif %}
```

**Step 2: Verify visually**

Run: `docker compose up -d --build`
Open: `http://localhost:8000`
Verify: Run an analysis and confirm the advice box now appears between Forza/Lacune and Colloquio.

**Step 3: Commit**

```bash
git add backend/templates/index.html
git commit -m "feat: move advice box after strengths/gaps, before interview"
```

---

## Task 2: Pill Azioni - Sostituire bottoni con pill selezionabili AJAX

**Files:**
- Modify: `backend/templates/index.html:307-318` (actions section)
- Modify: `backend/src/app.py:183-195` (status endpoint - add JSON response)

**Step 1: Update status endpoint to support JSON response**

In `backend/src/app.py`, modify the `update_status` function to return JSON when called via AJAX (checking Accept header), otherwise redirect as before:

```python
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

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
```

**Step 2: Replace actions HTML with pill chips**

Replace the actions section (lines 307-318) in `index.html` with:

```html
        {% if current %}
        <div class="actions" id="actions-{{ current.id }}">
            {% if current.job_url %}
            <a href="{{ current.job_url }}" target="_blank" class="btn btn-b btn-s">Apri annuncio</a>
            {% endif %}
            <div class="pill-group" data-analysis-id="{{ current.id }}">
                <button class="pill-btn pill-da_valutare {{ 'active' if (current.status or 'da_valutare') == 'da_valutare' }}" data-status="da_valutare" onclick="setStatus(this)">Da valutare</button>
                <button class="pill-btn pill-candidato {{ 'active' if current.status == 'candidato' }}" data-status="candidato" onclick="setStatus(this)">Candidato</button>
                <button class="pill-btn pill-colloquio {{ 'active' if current.status == 'colloquio' }}" data-status="colloquio" onclick="setStatus(this)">Colloquio</button>
                <button class="pill-btn pill-scartato {{ 'active' if current.status == 'scartato' }}" data-status="scartato" onclick="setStatus(this)">Scartato</button>
            </div>
        </div>
        {% endif %}
```

**Step 3: Add pill CSS**

Add to the `<style>` section in `index.html`:

```css
.pill-group{display:flex;gap:4px;flex-wrap:wrap}
.pill-btn{padding:6px 14px;border-radius:20px;border:2px solid #475569;background:transparent;color:#94a3b8;font-size:.78rem;font-weight:600;cursor:pointer;transition:all .15s}
.pill-btn:hover{border-color:#6366f1;color:#c7d2fe}
.pill-da_valutare.active{background:#334155;border-color:#64748b;color:#e2e8f0}
.pill-candidato.active{background:#1e3a5f;border-color:#3b82f6;color:#93c5fd}
.pill-colloquio.active{background:#365314;border-color:#84cc16;color:#d9f99d}
.pill-scartato.active{background:#450a0a;border-color:#f87171;color:#fca5a5}
```

**Step 4: Add pill JS**

Add to the `<script>` section in `index.html`:

```javascript
function setStatus(btn){
    var group=btn.closest('.pill-group');
    var id=group.dataset.analysisId;
    var status=btn.dataset.status;
    fetch('/status/'+id+'/'+status,{method:'POST',headers:{'Accept':'application/json'}})
    .then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            group.querySelectorAll('.pill-btn').forEach(function(b){b.classList.remove('active');});
            btn.classList.add('active');
            var histItem=document.querySelector('[data-hist-id="'+id+'"]');
            if(histItem) histItem.dataset.histStatus=status;
            updateHistTabs();
        }
    });
}
```

**Step 5: Verify**

Run analysis, confirm pills render with current status highlighted. Click different pill, confirm it changes without page reload.

**Step 6: Commit**

```bash
git add backend/templates/index.html backend/src/app.py
git commit -m "feat: replace action buttons with AJAX pill selectors"
```

---

## Task 3: Storico a 3 Tab

**Files:**
- Modify: `backend/templates/index.html:322-343` (history section)

**Step 1: Add tab CSS**

Add to `<style>` in `index.html`:

```css
.tabs{display:flex;gap:2px;margin-bottom:12px;background:#0f172a;border-radius:8px;padding:3px;border:1px solid #334155}
.tab{flex:1;padding:8px 12px;border-radius:6px;text-align:center;cursor:pointer;font-size:.8rem;font-weight:600;color:#64748b;transition:all .15s}
.tab:hover{color:#94a3b8}
.tab.active{background:#1e293b;color:#e2e8f0}
.tab-badge{display:inline-block;min-width:18px;padding:1px 6px;border-radius:10px;font-size:.68rem;margin-left:4px;background:#334155;color:#94a3b8}
.tab.active .tab-badge{background:#6366f1;color:#fff}
```

**Step 2: Replace history section HTML**

Replace the history section (lines 322-343) with:

```html
    {% if analyses %}
    <div class="hist">
        <h2>Storico analisi</h2>
        <div class="tabs" id="hist-tabs">
            <div class="tab active" data-tab="valutazione" onclick="switchTab(this)">In valutazione <span class="tab-badge" id="badge-valutazione">0</span></div>
            <div class="tab" data-tab="applicato" onclick="switchTab(this)">Applicato <span class="tab-badge" id="badge-applicato">0</span></div>
            <div class="tab" data-tab="skippato" onclick="switchTab(this)">Skippato <span class="tab-badge" id="badge-skippato">0</span></div>
        </div>
        <div class="card" style="padding:0;overflow:hidden" id="hist-list">
            {% for a in analyses %}
            <a href="/analysis/{{ a.id }}" style="text-decoration:none;color:inherit">
            <div class="hi" data-hist-id="{{ a.id }}" data-hist-status="{{ a.status or 'da_valutare' }}">
                <div class="hi-score score-{{ a.recommendation|lower }}">{{ a.score }}</div>
                <div class="hi-info">
                    <div class="hi-role">{{ a.role or 'Ruolo sconosciuto' }}</div>
                    <div class="hi-co">{{ a.company or 'Azienda sconosciuta' }}{% if a.work_mode %} · {{ a.work_mode }}{% endif %}{% if a.salary_info %} · {{ a.salary_info }}{% endif %}</div>
                </div>
                <span class="st st-{{ a.status or 'da_valutare' }}">{% if a.status == 'candidato' %}Candidato{% elif a.status == 'colloquio' %}Colloquio{% elif a.status == 'scartato' %}Scartato{% else %}Da valutare{% endif %}</span>
                <span class="rec rec-{{ a.recommendation }}" style="font-size:.72rem;padding:3px 9px">{{ a.recommendation }}</span>
                <span class="hi-date">${{ '%.4f' % (a.cost_usd or 0) }}<br>{{ a.created_at.strftime('%d/%m %H:%M') if a.created_at else '' }}</span>
            </div>
            </a>
            {% endfor %}
        </div>
    </div>
    {% endif %}
```

**Step 3: Add tab JS**

Add to `<script>`:

```javascript
function switchTab(tabEl){
    document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});
    tabEl.classList.add('active');
    updateHistTabs();
}
function updateHistTabs(){
    var activeTab=document.querySelector('.tab.active');
    if(!activeTab) return;
    var tab=activeTab.dataset.tab;
    var countVal=0,countApp=0,countSkip=0;
    document.querySelectorAll('.hi').forEach(function(hi){
        var st=hi.dataset.histStatus||'da_valutare';
        var isVal=st==='da_valutare';
        var isApp=st==='candidato'||st==='colloquio';
        var isSkip=st==='scartato';
        if(tab==='valutazione') hi.parentElement.style.display=isVal?'':'none';
        else if(tab==='applicato') hi.parentElement.style.display=isApp?'':'none';
        else hi.parentElement.style.display=isSkip?'':'none';
        if(isVal)countVal++;if(isApp)countApp++;if(isSkip)countSkip++;
    });
    document.getElementById('badge-valutazione').textContent=countVal;
    document.getElementById('badge-applicato').textContent=countApp;
    document.getElementById('badge-skippato').textContent=countSkip;
}
document.addEventListener('DOMContentLoaded',function(){if(document.getElementById('hist-tabs'))updateHistTabs();});
```

Note: We use `hi.parentElement.style.display` because each `.hi` div is wrapped in an `<a>` tag. We need to hide/show the parent `<a>` element.

**Step 4: Verify**

Load page with existing analyses. Confirm tabs filter correctly. Change status via pills, confirm tab counts update.

**Step 5: Commit**

```bash
git add backend/templates/index.html
git commit -m "feat: add 3-tab history view (valutazione/applicato/skippato)"
```

---

## Task 4: Glassdoor Auto-Flag

**Files:**
- Modify: `backend/src/prompts.py:1-61` (update analysis prompt)
- Modify: `backend/src/app.py:111-132` (store new field)
- Modify: `backend/src/app.py:150-172` (load new field in view_analysis)
- Modify: `backend/src/database.py:35-67` (add column)
- Modify: `backend/templates/index.html` (glassdoor badge in hero)

**Step 1: Update analysis prompt**

In `prompts.py`, add the `company_reputation` field to the JSON schema in `ANALYSIS_SYSTEM_PROMPT`. Add this entry to the JSON structure (after "advice"):

```
  "company_reputation": {
    "glassdoor_estimate": "<rating stimato su 5, es: '3.8/5' oppure 'non disponibile' se non conosci l'azienda>",
    "known_pros": ["aspetto positivo 1", "aspetto positivo 2"],
    "known_cons": ["aspetto negativo 1", "aspetto negativo 2"],
    "note": "breve nota sulla fonte/affidabilita' della stima"
  }
```

Also add this instruction at the end of the prompt (before the closing `"""`):

```
Per company_reputation:
- Stima il rating Glassdoor basandoti sulle tue conoscenze dell'azienda
- Se non conosci l'azienda, usa "non disponibile" come glassdoor_estimate e liste vuote per pro/cons
- Sii onesto: se non sei sicuro, dillo nella nota
- Pro e cons devono essere specifici dell'azienda, non generici
```

**Step 2: Add DB column**

In `backend/src/database.py`, add to `JobAnalysis` class:

```python
    company_reputation = Column(Text, default="")  # JSON: glassdoor_estimate, pros, cons
```

**Step 3: Update app.py to store company_reputation**

In `backend/src/app.py`, in `run_analysis` function, add to the `JobAnalysis(...)` constructor:

```python
        company_reputation=json.dumps(result.get("company_reputation", {}), ensure_ascii=False),
```

In `view_analysis` function, add to the result dict:

```python
        "company_reputation": json.loads(analysis.company_reputation) if analysis.company_reputation else {},
```

**Step 4: Add Glassdoor badge to hero section in template**

In `index.html`, inside the `hero-tags` div, add after the last tag:

```html
                    {% if result.company_reputation and result.company_reputation.glassdoor_estimate and result.company_reputation.glassdoor_estimate != 'non disponibile' %}
                    {% set gr = result.company_reputation.glassdoor_estimate|replace('/5','')|float %}
                    <span class="ht {% if gr >= 4.0 %}ht-sal{% elif gr >= 3.0 %}ht-time{% else %}tag-r{% endif %}" title="{{ result.company_reputation.known_pros|join(', ') }} | {{ result.company_reputation.known_cons|join(', ') }}{% if result.company_reputation.note %} - {{ result.company_reputation.note }}{% endif %}">
                        Glassdoor ~{{ result.company_reputation.glassdoor_estimate }}
                    </span>
                    {% elif result.company_reputation %}
                    <span class="ht ht-conf" title="{{ result.company_reputation.note|default('') }}">Glassdoor: n/d</span>
                    {% endif %}
```

**Step 5: Add expandable reputation detail box**

In `index.html`, after the hero section and before the verdict, add:

```html
        {% if result.company_reputation and (result.company_reputation.known_pros or result.company_reputation.known_cons) %}
        <details style="margin-bottom:16px">
            <summary>Reputazione aziendale {% if result.company_reputation.glassdoor_estimate and result.company_reputation.glassdoor_estimate != 'non disponibile' %}(~{{ result.company_reputation.glassdoor_estimate }}){% endif %}</summary>
            <div style="padding:12px;background:#0f172a;border-radius:8px;border:1px solid #334155">
                {% if result.company_reputation.known_pros %}
                <div style="margin-bottom:8px"><span style="color:#34d399;font-weight:600">Pro:</span>
                {% for p in result.company_reputation.known_pros %}<span class="ht ht-sal" style="margin:2px">{{ p }}</span>{% endfor %}
                </div>{% endif %}
                {% if result.company_reputation.known_cons %}
                <div><span style="color:#f87171;font-weight:600">Contro:</span>
                {% for c in result.company_reputation.known_cons %}<span class="ht" style="background:#450a0a;color:#fca5a5;margin:2px">{{ c }}</span>{% endfor %}
                </div>{% endif %}
                {% if result.company_reputation.note %}
                <div style="margin-top:8px;font-size:.72rem;color:#475569">{{ result.company_reputation.note }}</div>
                {% endif %}
            </div>
        </details>
        {% endif %}
```

**Step 6: Rebuild and verify**

Run: `docker compose down && docker compose up -d --build`

Note: Since we added a new column to the DB, existing data won't have it. SQLAlchemy `create_all` only creates new tables, not new columns. For development, either:
- `docker compose down -v` to reset DB, or
- Connect to psql and run: `ALTER TABLE job_analyses ADD COLUMN company_reputation TEXT DEFAULT '';`

Verify: Run a new analysis on a well-known company (es. Google, Amazon). Confirm Glassdoor badge appears in hero tags and expandable details show pro/cons.

**Step 7: Commit**

```bash
git add backend/src/prompts.py backend/src/database.py backend/src/app.py backend/templates/index.html
git commit -m "feat: add Glassdoor auto-flag with company reputation in analysis"
```

---

## Task 5: Cover Letter Generation

**Files:**
- Modify: `backend/src/database.py` (add CoverLetter table)
- Modify: `backend/src/prompts.py` (add COVER_LETTER prompts)
- Modify: `backend/src/ai_client.py` (add generate_cover_letter function)
- Modify: `backend/src/app.py` (add /cover-letter endpoints)
- Modify: `backend/templates/index.html` (add cover letter UI section)

**Step 1: Add CoverLetter model to database.py**

Add to `backend/src/database.py`, after the `JobAnalysis` class:

```python
class CoverLetter(Base):
    __tablename__ = "cover_letters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), nullable=False)
    language = Column(String(20), default="italiano")
    content = Column(Text, default="")
    subject_lines = Column(Text, default="")  # JSON list
    model_used = Column(String(50), default="")
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Step 2: Add cover letter prompts to prompts.py**

Add to `backend/src/prompts.py`:

```python
COVER_LETTER_SYSTEM_PROMPT = """Sei un esperto copywriter specializzato in candidature di lavoro. Scrivi cover letter professionali, personalizzate e convincenti.

Rispondi SOLO con JSON valido con questa struttura:
{
  "cover_letter": "Testo completo della cover letter, pronto da copiare. Includi saluto iniziale e chiusura. Usa paragrafi separati da \\n\\n. Non usare placeholder come [Nome] - scrivi una lettera generica ma personalizzata basata sul CV.",
  "subject_lines": [
    "Subject line 1 per email di candidatura",
    "Subject line 2 alternativa",
    "Subject line 3 alternativa"
  ]
}

Linee guida:
- La cover letter deve essere 250-400 parole
- Collega esperienze specifiche dal CV ai requisiti dell'annuncio
- Evidenzia i punti di forza identificati nell'analisi
- Se ci sono lacune, affrontale positivamente (es. "sono entusiasta di approfondire X")
- Tono: professionale ma personale, sicuro ma non arrogante
- Le subject line devono essere brevi (max 60 caratteri), specifiche per il ruolo e accattivanti
- IMPORTANTE: scrivi nella lingua richiesta dall'utente"""

COVER_LETTER_USER_PROMPT = """## CV DEL CANDIDATO
{cv_text}

## DESCRIZIONE DEL LAVORO
{job_description}

## RISULTATI ANALISI
- Ruolo: {role} @ {company}
- Score compatibilita: {score}/100
- Punti di forza: {strengths}
- Lacune: {gaps}

## LINGUA RICHIESTA
{language}

Scrivi la cover letter e le subject line nella lingua indicata."""
```

**Step 3: Add generate_cover_letter to ai_client.py**

Add to `backend/src/ai_client.py`:

```python
from .prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT, COVER_LETTER_SYSTEM_PROMPT, COVER_LETTER_USER_PROMPT

def generate_cover_letter(cv_text: str, job_description: str, analysis_result: dict, language: str, model: str = "haiku") -> dict:
    model_id = MODELS.get(model, MODELS["haiku"])

    # Check cache
    r = _get_redis()
    cache_key = None
    if r:
        content = f"cl:{model}:{cv_text[:300]}:{job_description[:300]}:{language}"
        cache_key = f"coverletter:{hashlib.sha256(content.encode()).hexdigest()[:16]}"
        cached = r.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["from_cache"] = True
            return result

    strengths_text = ", ".join(analysis_result.get("strengths", [])[:5])
    gaps_list = analysis_result.get("gaps", [])
    gaps_text = ", ".join(
        g.get("gap", g) if isinstance(g, dict) else str(g) for g in gaps_list[:5]
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model_id,
        max_tokens=2048,
        system=COVER_LETTER_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": COVER_LETTER_USER_PROMPT.format(
                cv_text=cv_text,
                job_description=job_description,
                role=analysis_result.get("role", ""),
                company=analysis_result.get("company", ""),
                score=analysis_result.get("score", 0),
                strengths=strengths_text,
                gaps=gaps_text,
                language=language,
            ),
        }],
    )

    raw_text = message.content[0].text
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    result = json.loads(text)
    result["model_used"] = model_id
    result["from_cache"] = False

    usage = message.usage
    pricing = PRICING.get(model_id, PRICING["claude-haiku-4-5-20251001"])
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]

    result["tokens"] = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    result["cost_usd"] = round(input_cost + output_cost, 6)

    if r and cache_key:
        try:
            cache_data = {k: v for k, v in result.items() if k != "from_cache"}
            r.setex(cache_key, CACHE_TTL, json.dumps(cache_data, ensure_ascii=False))
        except Exception:
            pass

    return result
```

**Step 4: Add cover letter endpoints to app.py**

Add imports at top of `app.py`:

```python
from .database import init_db, get_db, CVProfile, JobAnalysis, CoverLetter
from .ai_client import analyze_job, generate_cover_letter
```

Add endpoint:

```python
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
        result = generate_cover_letter(
            cv.raw_text, analysis.job_description, analysis_data, language, model
        )
    except Exception as e:
        logger.error(f"Cover letter fallita: {e}")
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
            request, db,
            cover_letter=cl,
            cover_letter_result=result,
            message=f"Cover letter generata! ({language})",
        ),
    )
```

**Step 5: Add cover letter UI section to index.html**

Add after the analysis form card (after line ~202), a new card:

```html
    {% if analyses %}
    <div class="card" style="margin-bottom:20px">
        <h2>Cover Letter</h2>
        <form method="post" action="/cover-letter" id="clf">
            <select name="analysis_id" style="width:100%;background:#0f172a;border:1px solid #475569;border-radius:6px;padding:8px 10px;color:#e2e8f0;font-size:.85rem;margin-bottom:8px">
                {% for a in analyses %}
                <option value="{{ a.id }}">{{ a.role or 'Ruolo' }} @ {{ a.company or 'Azienda' }} ({{ a.score }}/100)</option>
                {% endfor %}
            </select>
            <div class="btns">
                <select name="language" style="background:#0f172a;border:1px solid #475569;border-radius:6px;padding:6px 10px;color:#e2e8f0;font-size:.82rem">
                    <option value="italiano">Italiano</option>
                    <option value="english">English</option>
                    <option value="francais">Francais</option>
                    <option value="deutsch">Deutsch</option>
                    <option value="espanol">Espanol</option>
                </select>
                <div class="toggle">
                    <input type="radio" name="model" value="haiku" id="clmh" checked><label for="clmh">Haiku</label>
                    <input type="radio" name="model" value="sonnet" id="clms"><label for="clms">Sonnet</label>
                </div>
                <button type="submit" class="btn btn-g">Genera Cover Letter</button>
            </div>
        </form>
        <div class="loading" id="cld"><div class="spin"></div><span>Generazione in corso...</span></div>
    </div>
    {% endif %}

    {% if cover_letter_result %}
    <div class="card" style="margin-bottom:20px">
        <h2>Cover Letter generata</h2>
        <div style="margin-bottom:12px">
            <div class="advice-title" style="color:#059669">Lettera</div>
            <div id="cl-text" style="background:#0f172a;padding:14px;border-radius:8px;border:1px solid #334155;color:#cbd5e1;font-size:.85rem;line-height:1.7;white-space:pre-line;margin-bottom:8px">{{ cover_letter_result.cover_letter }}</div>
            <button class="btn btn-muted btn-s" onclick="navigator.clipboard.writeText(document.getElementById('cl-text').textContent)">Copia lettera</button>
        </div>
        {% if cover_letter_result.subject_lines %}
        <div>
            <div class="advice-title" style="color:#f59e0b">Subject line suggerite</div>
            {% for sl in cover_letter_result.subject_lines %}
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                <span style="background:#0f172a;padding:6px 12px;border-radius:6px;border:1px solid #334155;color:#e2e8f0;font-size:.82rem;flex:1" id="sl-{{ loop.index }}">{{ sl }}</span>
                <button class="btn btn-muted btn-s" onclick="navigator.clipboard.writeText(document.getElementById('sl-{{ loop.index }}').textContent)">Copia</button>
            </div>
            {% endfor %}
        </div>
        {% endif %}
        <div style="margin-top:8px;font-size:.72rem;color:#475569">
            Costo: ${{ '%.5f' % cover_letter_result.cost_usd }} | {{ cover_letter_result.tokens.total }} token
        </div>
    </div>
    {% endif %}
```

**Step 6: Add loading spinner for cover letter form**

Add to `<script>`:

```javascript
var clf=document.getElementById('clf');
if(clf){clf.addEventListener('submit',function(){document.getElementById('cld').classList.add('on');});}
```

**Step 7: Rebuild and verify**

Run: `docker compose down -v && docker compose up -d --build`

Test: Save CV, run analysis, then use cover letter section to generate a letter. Verify content + subject lines + copy buttons work.

**Step 8: Commit**

```bash
git add backend/src/database.py backend/src/prompts.py backend/src/ai_client.py backend/src/app.py backend/templates/index.html
git commit -m "feat: add cover letter generation with subject lines and language selection"
```

---

## Task 6: Batch Analysis

**Files:**
- Modify: `backend/src/app.py` (batch endpoints + background tasks)
- Modify: `backend/templates/index.html` (batch UI)

**Step 1: Add batch state and endpoints to app.py**

Add imports:

```python
import uuid as uuid_mod
from fastapi import FastAPI, Depends, Form, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
```

Add batch state (module-level, after app creation):

```python
# Batch analysis state (in-memory)
batch_queue: dict[str, dict] = {}


def _run_batch(batch_id: str):
    """Background task to process batch analysis queue."""
    batch = batch_queue.get(batch_id)
    if not batch:
        return
    batch["status"] = "running"
    db = SessionLocal()
    try:
        cv = db.query(CVProfile).order_by(CVProfile.updated_at.desc()).first()
        if not cv:
            batch["status"] = "error"
            batch["error"] = "Nessun CV trovato"
            return
        for item in batch["items"]:
            if item["status"] == "cancelled":
                continue
            item["status"] = "running"
            try:
                result = analyze_job(cv.raw_text, item["job_description"], item.get("model", "haiku"))
                analysis = JobAnalysis(
                    cv_id=cv.id,
                    job_description=item["job_description"],
                    job_url=item.get("job_url", ""),
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
                item["result_preview"] = f"{result.get('role', '?')} @ {result.get('company', '?')} -- {result.get('score', 0)}/100"
            except Exception as e:
                item["status"] = "error"
                item["error"] = str(e)
        batch["status"] = "done"
    finally:
        db.close()
```

Add batch endpoints:

```python
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

    active[1]["items"].append({
        "job_description": job_description,
        "job_url": job_url,
        "model": model,
        "status": "pending",
        "preview": job_description[:80] + "..." if len(job_description) > 80 else job_description,
    })
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
```

Note: Import `SessionLocal` from database module at top of app.py:
```python
from .database import init_db, get_db, CVProfile, JobAnalysis, CoverLetter, SessionLocal
```

**Step 2: Export SessionLocal from database.py**

`SessionLocal` is already defined in `database.py` and importable. No changes needed.

**Step 3: Add batch UI to index.html**

Add a new card after the cover letter section, before the results section:

```html
    <div class="card" style="margin-bottom:20px">
        <h2>Analisi multipla</h2>
        <div id="batch-form">
            <input type="url" id="batch-url" placeholder="Link annuncio (opzionale)" style="width:100%;background:#0f172a;border:1px solid #475569;border-radius:6px;padding:8px 10px;color:#e2e8f0;font-size:.85rem;margin-bottom:8px">
            <textarea id="batch-jd" placeholder="Incolla la descrizione del lavoro..." style="width:100%;min-height:80px;background:#0f172a;border:1px solid #475569;border-radius:6px;padding:10px;color:#e2e8f0;font-size:.85rem;resize:vertical;margin-bottom:8px"></textarea>
            <div class="btns">
                <button class="btn btn-a btn-s" onclick="batchAdd()">Aggiungi alla coda</button>
                <div class="toggle">
                    <input type="radio" name="batch_model" value="haiku" id="bmh" checked><label for="bmh">Haiku</label>
                    <input type="radio" name="batch_model" value="sonnet" id="bms"><label for="bms">Sonnet</label>
                </div>
            </div>
        </div>
        <div id="batch-queue" style="margin-top:12px"></div>
        <div id="batch-actions" style="display:none;margin-top:10px" class="btns">
            <button class="btn btn-g" onclick="batchRun()">Analizza tutti</button>
            <button class="btn btn-r btn-s" onclick="batchClear()">Svuota coda</button>
            <span id="batch-status-text" style="font-size:.82rem;color:#94a3b8"></span>
        </div>
    </div>
```

**Step 4: Add batch JS (using safe DOM methods, no innerHTML)**

Add to `<script>`:

```javascript
var batchItems=[];
function batchAdd(){
    var jd=document.getElementById('batch-jd').value.trim();
    if(!jd){alert('Inserisci una descrizione del lavoro');return;}
    var url=document.getElementById('batch-url').value.trim();
    var model=document.querySelector('input[name="batch_model"]:checked').value;
    var fd=new FormData();fd.append('job_description',jd);fd.append('job_url',url);fd.append('model',model);
    fetch('/batch/add',{method:'POST',body:fd}).then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            batchItems.push({preview:jd.substring(0,80)+(jd.length>80?'...':''),status:'pending',result_preview:''});
            renderBatchQueue();
            document.getElementById('batch-jd').value='';
            document.getElementById('batch-url').value='';
        }
    });
}
function renderBatchQueue(){
    var q=document.getElementById('batch-queue');
    var acts=document.getElementById('batch-actions');
    while(q.firstChild)q.removeChild(q.firstChild);
    if(batchItems.length===0){acts.style.display='none';return;}
    acts.style.display='flex';
    batchItems.forEach(function(item,i){
        var color=item.status==='done'?'#34d399':item.status==='running'?'#fbbf24':item.status==='error'?'#f87171':'#64748b';
        var row=document.createElement('div');
        row.style.cssText='display:flex;align-items:center;gap:8px;padding:6px 10px;border-bottom:1px solid #1e293b;font-size:.82rem';
        var num=document.createElement('span');
        num.style.cssText='color:'+color+';font-weight:600';
        num.textContent='['+(i+1)+']';
        var prev=document.createElement('span');
        prev.style.cssText='flex:1;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        prev.textContent=item.preview;
        var st=document.createElement('span');
        st.style.cssText='color:'+color+';font-size:.75rem';
        st.textContent=item.status;
        row.appendChild(num);row.appendChild(prev);row.appendChild(st);
        if(item.result_preview){
            var rp=document.createElement('span');
            rp.style.cssText='color:#94a3b8;font-size:.72rem';
            rp.textContent=item.result_preview;
            row.appendChild(rp);
        }
        q.appendChild(row);
    });
}
function batchRun(){
    fetch('/batch/run',{method:'POST'}).then(function(r){return r.json();}).then(function(data){
        if(data.ok){
            document.getElementById('batch-status-text').textContent='Analisi in corso...';
            pollBatch();
        }
    });
}
function pollBatch(){
    fetch('/batch/status').then(function(r){return r.json();}).then(function(data){
        if(data.items){
            data.items.forEach(function(item,i){
                if(batchItems[i]){
                    batchItems[i].status=item.status;
                    if(item.result_preview)batchItems[i].result_preview=item.result_preview;
                }
            });
            renderBatchQueue();
        }
        if(data.status==='running'){setTimeout(pollBatch,2000);}
        else if(data.status==='done'){
            document.getElementById('batch-status-text').textContent='Completato! Ricarica la pagina per vedere i risultati.';
        }
    });
}
function batchClear(){
    fetch('/batch/clear',{method:'DELETE'}).then(function(r){return r.json();}).then(function(){
        batchItems=[];renderBatchQueue();
        document.getElementById('batch-status-text').textContent='';
    });
}
```

**Step 5: Verify**

Test: Add 2-3 job descriptions to the queue, click "Analizza tutti", watch the status update in real-time via polling.

**Step 6: Commit**

```bash
git add backend/src/app.py backend/templates/index.html
git commit -m "feat: add batch analysis with background tasks and queue UI"
```

---

## Task 7: Final cleanup and verification

**Step 1: Full integration test**

1. `docker compose down -v && docker compose up -d --build`
2. Open `http://localhost:8000`
3. Save a CV
4. Run a single analysis -> verify: reordered layout, Glassdoor badge, pill actions
5. Change status via pills -> verify no reload, storico tabs update
6. Generate cover letter -> verify content + subject lines + copy
7. Add 2 jobs to batch queue -> run -> verify background processing
8. Check storico tabs filter correctly

**Step 2: Update ROADMAP.md**

Mark completed items and add new ones.

**Step 3: Commit**

```bash
git add -A
git commit -m "docs: update roadmap with completed features"
```
