# Technical Documentation - Job Search Command Center

> Companion to the [project README](../README.md) (high-level overview, features, costs, deploy targets) and the editable [architecture diagram](architecture.drawio). For the local dev setup see [LOCAL_DEV.md](LOCAL_DEV.md).

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Project Structure](#2-project-structure)
3. [Backend: FastAPI and App Factory](#3-backend-fastapi-and-app-factory)
4. [Database and ORM](#4-database-and-orm)
5. [Authentication and Security](#5-authentication-and-security)
6. [AI Integration (Anthropic Claude)](#6-ai-integration-anthropic-claude)
7. [Cache and Performance](#7-cache-and-performance)
8. [API Versioning](#8-api-versioning)
9. [Frontend and SSR](#9-frontend-and-ssr)
10. [Docker Infrastructure](#10-docker-infrastructure)
11. [CI/CD](#11-cicd)
12. [Render.com Deployment](#12-rendercom-deployment)
13. [Monitoring and Observability](#13-monitoring-and-observability)
14. [Architectural Patterns and Decisions](#14-architectural-patterns-and-decisions)
15. [MCP Server (Claude Desktop Integration)](#15-mcp-server-claude-desktop-integration)
16. [Learning Loop (Analytics + Auto-Adapt)](#16-learning-loop-analytics--auto-adapt)

---

## 1. Architecture Overview

The system has two runtime components:

1. **Backend (Render.com, Frankfurt)** — does everything: AI analysis via Anthropic API, PostgreSQL persistence, deduplication via content_hash, cost tracking, and serves the web UI (Jinja2 SSR). Single Docker container, free tier, auto-stop after ~5 min inactivity.
2. **MCP server (local, macOS)** — thin HTTP proxy (~120 lines) that runs on the developer's machine via Claude Desktop (stdio transport). All 15 read-only tools are HTTP calls to the backend, authenticated with an API key (X-API-Key header).
3. **GitHub Actions** — CI pipeline (11 checks: ruff, mypy strict, bandit, pip-audit, stylelint, ESLint, CodeQL 3-lang, SonarCloud QG, pytest, Docker build, Alembic migrations) + daily DB backup cron + weekly cleanup.
4. **Checkly** — 6 uptime/API checks managed as Terraform IaC.

```
Claude Desktop (stdio)     Browser            GitHub Actions
       |                      |               (CI + daily backup)
       v                      |                     |
  MCP Server (local)          |                     |
  15 tools, thin proxy        |                     |
       | HTTP (X-API-Key)     |                     |
       v                      v                     v
  FastAPI + Jinja2 (Render.com) ---- Anthropic Claude API (Haiku/Sonnet)
       |                     ---- Cloudflare R2 (file storage + backups)
       |                     ---- Resend (email reminders)
       |                     ---- RapidAPI (Glassdoor ratings)
       v
  PostgreSQL (Neon, 1GB free tier)

  Checkly (6 checks, Terraform IaC) → monitors /health + key endpoints
```

### Design Principles

- **Separation of concerns**: backend handles all business logic, MCP is a stateless proxy
- **Graceful degradation**: Redis and Glassdoor are optional, the app works without them
- **Fail-fast**: missing environment variables block startup (not runtime)
- **Defense in depth**: rate limiting + CORS + security headers + trusted hosts + audit trail
- **Crash-resistant batch**: PostgreSQL-backed batch queue survives server restarts and Render.com autostop

---

## 2. Project Structure

```
backend/src/
├── main.py              # App factory (create_app)
├── pages.py             # Multi-page SSR route handlers
├── read_routes.py       # Read-only API routes (MCP + dashboard)
├── config.py            # Settings da env con Pydantic
├── api_v1.py            # Aggregatore router JSON
├── prompts.py           # Prompt AI ottimizzati per token
├── rate_limit.py        # Singleton SlowAPI
├── dependencies.py      # Dipendenze condivise (auth, cache)
│
├── database/            # Engine, session, Base
│   ├── __init__.py      # Re-export
│   └── base.py          # create_engine + DeclarativeBase
│
├── auth/                # Autenticazione
│   ├── models.py        # User model (with login lockout)
│   ├── service.py       # hash_password, authenticate_user
│   └── routes.py        # /login, /logout (HTML)
│
├── cv/                  # Gestione CV
│   ├── models.py        # CVProfile model
│   ├── service.py       # get_latest_cv, save_cv
│   └── routes.py        # /cv (HTML)
│
├── analysis/            # Core: analisi AI
│   ├── models.py        # JobAnalysis, AppSettings, AnalysisStatus (StrEnum)
│   ├── schemas.py       # Pydantic validation schemas (AnalysisResponse)
│   ├── service.py       # run_analysis, rebuild_result
│   ├── routes.py        # /analyze, /analysis/{id} (HTML)
│   ├── api_routes.py    # /status, /analysis (JSON API)
│   └── followup_routes.py  # /followup-email, /linkedin-message (JSON)
│
├── cover_letter/        # Generazione cover letter
│   ├── models.py        # CoverLetter model
│   ├── service.py       # generate, persist
│   └── routes.py        # /cover-letter (HTML)
│
├── contacts/            # CRM recruiter
│   ├── models.py        # Contact model
│   ├── service.py       # CRUD contatti
│   └── routes.py        # /contacts (JSON API)
│
├── dashboard/           # Dashboard with 6 widgets + spending
│   ├── service.py       # add_spending, seed_totals, widget data
│   └── routes.py        # /spending, /dashboard (JSON API)
│
├── agenda/              # To-do page (DB-backed tasks)
│   ├── models.py        # TodoItem model
│   ├── service.py       # CRUD todo items
│   └── routes.py        # /agenda (HTML + JSON API)
│
├── stats/               # Statistics page (9 Chart.js charts)
│   ├── service.py       # Stats aggregation queries
│   └── routes.py        # /stats (HTML)
│
├── preferences/         # App preferences (persisted in DB)
│   ├── models.py        # AppPreferences model
│   ├── service.py       # get/set preferences
│   └── routes.py        # /preferences (JSON API)
│
├── metrics/             # Internal request metrics
│   ├── models.py        # RequestMetric model
│   ├── service.py       # Metrics aggregation
│   ├── middleware.py     # Request timing middleware
│   └── routes.py        # /admin/metrics (HTML)
│
├── analytics/           # Pure data-science primitives (no external deps)
│   └── __init__.py      # Discriminants, bias signals, profile derivation
│
├── analytics_page/      # /analytics page (learning loop UI)
│   ├── models.py        # AnalyticsRun, UserProfile models
│   ├── service.py       # Run analytics pass, persist snapshot, update profile
│   └── routes.py        # /analytics (HTML + JSON API)
│
├── notification_center/ # Server-side notification center
│   ├── models.py        # NotificationDismissal model
│   ├── service.py       # Computed rules + dismiss/undismiss
│   └── routes.py        # /notifications (HTML + JSON API)
│
├── batch/               # Batch analysis (persistent PostgreSQL queue)
│   ├── models.py        # BatchItem model (batch_items table)
│   ├── service.py       # Persistent queue, run_batch, item status
│   └── routes.py        # /batch/* (JSON API)
│
├── audit/               # Audit trail
│   ├── models.py        # AuditLog model
│   └── service.py       # audit() helper
│
├── notifications/       # Email alerts
│   ├── models.py        # NotificationLog model
│   └── service.py       # SMTP + Fernet encryption
│
├── interview/           # Multi-round interviews
│   ├── models.py        # Interview model (multi-round per JobAnalysis)
│   ├── service.py       # CRUD + upcoming interviews + outcomes
│   └── routes.py        # /interviews (JSON API)
│
└── integrations/        # Client esterni
    ├── anthropic_client.py  # Claude API + 7-strategy JSON parsing
    ├── validation.py        # AI response validation + repair
    ├── cache.py             # Redis/Null cache (Protocol)
    └── glassdoor.py         # Company enrichment (RapidAPI)

mcp-server/
├── server.py              # FastMCP app, 15 read-only tools (thin HTTP proxy)
├── api_client.py          # HTTP client → backend API (X-API-Key auth, retry with backoff)
├── config.py              # Pydantic settings (backend_url, api_key, mcp_host/port)
├── requirements.txt       # fastmcp, httpx, pydantic-settings
├── tests/
│   ├── test_server.py     # Tool → endpoint mapping tests
│   └── test_api_client.py # Auth, retry, error handling tests
└── pyproject.toml         # Ruff + mypy config

infra/
└── checkly/               # Uptime monitoring as Terraform IaC
    ├── providers.tf       # Checkly provider config
    ├── checks.tf          # 6 API/browser checks
    └── terraform.tfvars.example
```

Each backend module follows the **models -> service -> routes** pattern:
- `models.py`: SQLAlchemy table definition
- `service.py`: business logic (no HTTP dependency)
- `routes.py`: HTTP handler that calls the service

---

## 3. Backend: FastAPI e App Factory

### App Factory (`main.py`)

L'app viene creata tramite `create_app()`, un pattern factory che separa configurazione da istanza:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Job Search Command Center", lifespan=lifespan)
    # middleware, routes, exception handlers...
    return app

app = create_app()
```

### Lifespan

Il lifecycle dell'app e' gestito con `@asynccontextmanager`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY missing")
    _run_migrations()                               # Alembic upgrade head
    app.state.cache = create_cache_service()        # Redis o NullCache
    ensure_admin_user(db)                           # Crea admin da env
    seed_spending_totals(db)                        # Inizializza riga singleton
    check_and_send_followup_reminders(db)           # Email pending al boot
    yield
    # Shutdown (niente da fare)
```

### Stack Middleware

I middleware sono applicati in ordine LIFO (ultimo aggiunto = piu' esterno):

```
Request → uvicorn (proxy-headers) → SecurityHeaders → TrustedHost → CORS → SlowAPI → Session → Route Handler
```

0. **uvicorn --proxy-headers**: legge `X-Forwarded-Proto`/`X-Forwarded-For` a livello server ASGI (prima di qualsiasi middleware applicativo)
1. **SecurityHeaders** (custom `@app.middleware`): aggiunge X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, HSTS (outermost — aggiunto per ultimo)
2. **TrustedHostMiddleware**: attivo solo se `TRUSTED_HOSTS != "*"`
3. **CORSMiddleware**: origins configurabili via `CORS_ALLOWED_ORIGINS`
4. **SlowAPIMiddleware**: rate limiting globale con slowapi
5. **SessionMiddleware**: sessioni server-side con itsdangerous (TTL 7 giorni, innermost — aggiunto per primo)

### Exception Handlers

Tre exception handler custom gestiscono errori specifici:

```python
# Auth: redirect a login se non autenticato
@app.exception_handler(AuthRequired)
async def auth_redirect_handler(request, exc):
    return RedirectResponse(url="/login", status_code=303)

# HTTP: 404 mostra template custom, altri errori ritornano JSON
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 404:
        return templates.TemplateResponse("404.html", ...)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

# Generic: 500 mostra template custom + logging
@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return templates.TemplateResponse("500.html", ..., status_code=500)
```

Le pagine 404 e 500 estendono `base.html` (con sidebar visibile) e mostrano un messaggio centrato con un link "Torna alla Dashboard".

### Health Check

```python
@app.get("/health")
def health(db: Session = Depends(get_db)):
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unreachable"

    status = "ok" if db_status == "ok" else "degraded"
    return {
        "status": status,           # "ok" | "degraded"
        "db": db_status,            # "ok" | "unreachable"
        "version": "2.0.0",
        "uptime_seconds": uptime,   # Secondi dal boot
    }
```

L'endpoint `/health` verifica la connessione DB con `SELECT 1` e ritorna `"degraded"` se il database non e' raggiungibile.

### Rate Limiting

```python
# rate_limit.py
limiter = Limiter(key_func=_get_real_ip)

# Nelle route:
@router.post("/analyze")
@limiter.limit(settings.rate_limit_analyze)  # "10/minute"
def analyze(...):
```

`_get_real_ip()` legge `X-Forwarded-For` per funzionare dietro nginx.

Route protette con rate limiting esplicito:
- `POST /analyze` — `10/minute` (analisi AI)
- `POST /login` — `5/minute` (brute force protection)
- `POST /batch/run` — `10/minute` (batch processing)
- `POST /cover-letter` — `10/minute` (generazione AI)

Il rate limit handler supporta **content negotiation**:
- Richieste HTML → redirect alla pagina corrente con header `Retry-After`
- Richieste JSON → risposta 429 strutturata con `retry_after` e `Retry-After` header

Sul frontend, `handleRateLimit(response, msg)` in `app.js` cattura le risposte 429 e mostra un alert con i secondi di attesa.

---

## 4. Database e ORM

### Engine e Connection Pool

```python
engine = create_engine(
    settings.effective_database_url,
    poolclass=QueuePool,
    pool_size=5,        # Connessioni permanenti
    max_overflow=10,    # Connessioni extra sotto carico
    pool_pre_ping=True, # Testa connessione prima dell'uso
)
```

`pool_pre_ping=True` e' fondamentale: evita errori "connection closed" dopo periodi di inattivita' (es. Render.com che dorme la VM).

### DeclarativeBase

```python
class Base(DeclarativeBase):
    pass
```

Tutte le tabelle ereditano da `Base`. I modelli usano:
- **UUID come primary key**: `Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)`
- **JSONB per dati strutturati**: strengths, gaps, interview_scripts, company_reputation
- **DateTime timezone-aware**: `DateTime(timezone=True)` per consistenza UTC
- **Foreign key con cascade**: `ondelete="CASCADE"` per pulizia automatica

### Schema del Database

| Tabella | Scopo | Relazioni |
|---------|-------|-----------|
| `users` | Utenti con login (+ lockout) | 1:N cv_profiles, 1:N audit_logs |
| `cv_profiles` | CV in testo plain | FK user_id, 1:N job_analyses |
| `job_analyses` | Risultato analisi AI | FK cv_id, 1:N cover_letters + contacts |
| `cover_letters` | Lettere generate | FK analysis_id |
| `contacts` | Contatti recruiter | FK analysis_id |
| `app_settings` | Budget e spese (singleton) | Nessuna FK |
| `app_preferences` | Operational preferences (singleton) | Nessuna FK |
| `glassdoor_cache` | Cache rating aziende | Nessuna FK |
| `audit_logs` | Trail azioni utente | FK user_id (SET NULL) |
| `notification_logs` | Log email inviate | FK analysis_id (CASCADE) |
| `notification_dismissals` | Dismissed notification center items | FK user_id |
| `interviews` | Multi-round interviews | FK analysis_id (CASCADE) |
| `interview_files` | Interview document uploads | FK interview_id (CASCADE) |
| `batch_items` | Persistent batch queue items | FK cv_id (CASCADE), FK analysis_id (SET NULL) |
| `todo_items` | Agenda to-do tasks | FK user_id |
| `request_metrics` | Internal request timing metrics | Nessuna FK |
| `analytics_runs` | Snapshot of each /analytics pass (stats, discriminants, bias signals) | FK user_id |
| `user_profiles` | Learned profile (prompt_snippet auto-injected into next analysis) | FK user_id (1:1) |

### Indici

```sql
-- job_analyses: 5 indici per le query piu' frequenti
idx_analyses_score        -- Ordinamento per score
idx_analyses_status       -- Filtro per stato
idx_analyses_created      -- Ordinamento cronologico
idx_analyses_cv_id        -- Join con cv_profiles
idx_analyses_content_hash -- Deduplicazione
```

### Migrazioni (Alembic)

```
backend/alembic/
├── alembic.ini         # Config (sqlalchemy.url da settings)
├── env.py              # Import tutti i modelli
└── versions/
    ├── 001_initial_schema.py             # All original tables
    ├── 002_add_audit_logs.py             # Audit table
    ├── 003_add_notification_logs.py      # Notification logs table
    ├── 004_add_interviews.py             # Interviews table
    ├── 005_interview_redesign.py         # Interview schema redesign
    ├── 006_add_interview_files.py        # Interview file uploads
    ├── 007_add_batch_items.py            # Persistent batch queue table
    ├── 008_recover_applied_status.py     # Applied status recovery
    ├── 009_add_login_lockout.py          # Login lockout fields
    ├── 010_add_benefits_recruiter.py     # Benefits + recruiter fields
    ├── 011_add_analyses_hash_model_index.py # Composite index
    ├── 012_add_app_preferences.py        # App preferences table
    ├── 013_interview_multiround.py       # Multi-round interview redesign
    ├── 014_add_notification_dismissals.py # Notification dismissals
    ├── 015_add_todo_items.py             # Agenda to-do items
    ├── 016_add_request_metrics.py        # Request metrics table
    ├── 017_add_salary_data_and_company_news.py  # Salary + news caches
    ├── 018_add_career_track.py           # career_track column on job_analyses
    └── 019_add_analytics_runs_user_profile.py   # Analytics runs + learned user profile
```

`env.py` importa tutti i modelli per farli "vedere" ad Alembic:
```python
from src.auth.models import User
from src.cv.models import CVProfile
# ... tutti i modelli
```

Per creare una nuova migrazione:
```bash
cd backend
alembic revision --autogenerate -m "descrizione"
alembic upgrade head
```

---

## 5. Autenticazione e Sicurezza

### Flusso di autenticazione

1. **Login** (`POST /login`): email + password → `bcrypt.checkpw()` → sessione
2. **Sessione**: `request.session["user_id"] = str(user.id)` (UUID serializzato)
3. **Verifica**: `get_current_user()` legge sessione → query DB → ritorna `User`
4. **Logout**: `request.session.clear()` → redirect a `/login`

### Password hashing

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
```

bcrypt genera un salt random per ogni hash. Il costo di default (12 round) rende il brute force impraticabile.

### Auth Dependency

```python
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id_str = request.session.get("user_id")
    if not user_id_str:
        raise AuthRequired()  # → redirect a /login
    # ... valida UUID, query DB, verifica is_active
```

`AuthRequired` e' un'eccezione custom gestita da un exception handler in `main.py`:
```python
@app.exception_handler(AuthRequired)
async def auth_redirect_handler(request, exc):
    return RedirectResponse(url="/login", status_code=303)
```

### Admin user auto-creazione

Al primo avvio, `ensure_admin_user()` crea l'utente admin dalle variabili d'ambiente:
```python
def ensure_admin_user(db: Session) -> None:
    if not settings.admin_email or not settings.admin_password:
        return
    existing = get_user_by_email(db, settings.admin_email)
    if existing:
        return
    admin = User(email=settings.admin_email, password_hash=hash_password(settings.admin_password))
    db.add(admin)
```

### Audit Trail

Ogni azione utente viene registrata nel DB:

```python
def audit(db, request, action, detail="", user_id=None):
    db.add(AuditLog(
        user_id=user_id or UUID(request.session.get("user_id")),
        action=action,       # "login", "analyze", "delete_analysis", etc.
        detail=detail,       # Contesto aggiuntivo
        ip_address=_get_ip(request),  # X-Forwarded-For aware
    ))
```

Azioni tracciate: `login`, `login_failed`, `logout`, `analyze`, `analyze_cache`, `analyze_error`, `status_change`, `delete_analysis`, `cover_letter`, `cv_save`, `cv_download`, `followup_email`, `linkedin_message`, `batch_add`, `batch_run`, `followup_done`.

---

## 6. Integrazione AI (Anthropic Claude)

### Client Singleton

```python
_client: anthropic.Anthropic | None = None

def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client
```

Il singleton evita di ricreare il client HTTP ad ogni chiamata.

### Modelli disponibili

```python
MODELS = {
    "haiku": "claude-haiku-4-5-20251001",    # Veloce, economico
    "sonnet": "claude-sonnet-4-6",            # Approfondito, costoso
}
```

### Flusso di una chiamata API

```
_call_api() → messages.create() → raw_text → _extract_and_parse_json() → dict
                                                      ↓ fallback
                                              _retry_json_fix() → AI corregge il JSON
```

### Parsing JSON robusto (7 + 1 strategie)

L'AI non sempre produce JSON valido. `_extract_and_parse_json()` tenta 7 strategie in cascata:

1. **Parse diretto**: `json.loads(text)` — funziona nel 90% dei casi
2. **Estrai da code block**: trova JSON dentro ` ```json ... ``` `
3. **Clean JSON**: rimuove trailing comma, commenti `//`, NaN/Infinity, aggiunge virgole mancanti tra oggetti adiacenti
4. **Estrai frammento**: trova il primo `{` e l'ultimo `}`, estrae il frammento
5. **Fix control chars**: sostituisce `\t`, `\f`, `\r` non escapati
6. **Fix single quotes**: converte `'key': 'value'` in `"key": "value"`
7. **Fix trailing text**: rimuove testo dopo la chiusura del JSON (`}...garbage`)

Se tutti falliscono, `_retry_json_fix()` chiede all'AI stessa di correggere il JSON rotto:

```python
def _retry_json_fix(model_id, broken_json):
    fix_msg = client.messages.create(
        system="You fix malformed JSON. Respond ONLY with the corrected JSON.",
        messages=[{"role": "user", "content": f"Fix this malformed JSON:\n\n{broken_json}"}],
    )
    return _extract_and_parse_json(fix_msg.content[0].text)
```

### Validazione Pydantic

Dopo il parsing JSON, le risposte AI vengono validate tramite schema Pydantic (`analysis/schemas.py`):

```python
class AnalysisResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    recommendation: Literal["APPLY", "CONSIDER", "SKIP"]
    strengths: list[StrengthItem]
    gaps: list[GapItem]
    interview_scripts: list[InterviewScript]
    # ...
```

La validazione garantisce che campi obbligatori, range numerici e valori enum siano corretti prima di persistere i risultati nel DB. In caso di errore di validazione, il sistema logga il warning e tenta comunque di salvare i dati raw.

### Deduplicazione con content hash

```python
def content_hash(cv_text: str, job_description: str) -> str:
    content = f"{cv_text}:{job_description}"
    return hashlib.sha256(content.encode()).hexdigest()
```

Se CV + annuncio producono lo stesso hash di un'analisi esistente con lo stesso modello, l'analisi viene saltata (risparmio API).

### Calcolo costi

```python
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

def _calculate_cost(usage, model_id):
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
```

Ogni analisi traccia: token input, token output, costo in USD. I totali vengono aggregati in `app_settings`.

### Prompt Engineering

I prompt sono in `prompts.py` (current version: **v7**), ottimizzati per minimizzare token:
- **Schema JSON inline**: ogni campo su una riga
- **Regole in formato tabellare**: `80-100=APPLY | 60-79=CONSIDER | ...`
- **Zero ridondanza**: niente ripetizioni tra system e user prompt
- **Istruzioni sullo scoring calibrato**: lo score deve riflettere competenze REALI e DIMOSTRATE
- **Career track classification**: ogni analisi ritorna `career_track` ∈ `{plan_a_devops, plan_b_dev, hybrid_a_b, cybersec_junior_ok, out_of_scope}` per classificare il job nella strategia di carriera dell'utente
- **Auto-adapt**: il `prompt_snippet` in `user_profiles` (popolato dal learning loop, vedi sezione 16) viene **prepended** automaticamente al system prompt ad ogni chiamata. Questo permette al tool di auto-calibrarsi sulla base delle decisioni passate dell'utente.

---

## 7. Cache e Performance

### Pattern Protocol

```python
class CacheService(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int) -> None: ...
    def get_json(self, key: str) -> dict | None: ...
    def set_json(self, key: str, data: dict, ttl: int) -> None: ...
```

Due implementazioni:
- `RedisCacheService`: connessione Redis reale
- `NullCacheService`: no-op (tutti i metodi ritornano None)

### Factory con graceful degradation

```python
def create_cache_service() -> CacheService:
    if not settings.redis_url:
        return NullCacheService()
    try:
        return RedisCacheService(settings.redis_url)
    except Exception:
        return NullCacheService()  # Redis non raggiungibile? Vai senza cache
```

### Strategia di caching

| Operazione | Chiave | TTL |
|-----------|--------|-----|
| Analisi AI | `analysis:{model}:{hash[:16]}` | 24h |
| Cover letter | `coverletter:{hash[:16]}` | 24h |
| Glassdoor | DB-level (tabella dedicata) | 30 giorni |

### Connection Pool PostgreSQL

```python
engine = create_engine(
    url,
    pool_size=5,         # Connessioni "calde"
    max_overflow=10,     # Burst fino a 15 totali
    pool_pre_ping=True,  # Health check pre-query
)
```

---

## 8. API Versioning

### Separazione HTML / JSON

Le route sono divise in due gruppi:

**Route HTML** (root level): servono pagine Jinja2 (multi-page con sidebar)
```
GET  /              → dashboard.html (6 widgets: follow-up, interviews, Cowork, activity, top 5, DB usage)
GET  /analyze       → analyze.html (tab singola/multipla)
GET  /history       → history.html (storico, tab per stato)
GET  /analysis/{id} → analysis_detail.html (dettaglio candidatura)
GET  /interviews    → interviews.html (prossimi + passati, multi-round)
GET  /stats         → stats.html (9 Chart.js charts)
GET  /agenda        → agenda.html (to-do tasks)
GET  /settings      → settings.html (CV + crediti API)
GET  /admin         → admin.html (parameters, maintenance, diagnostics)
GET  /notifications → notifications.html (notification center)
GET  /admin/metrics → metrics dashboard
GET  /login         → login.html (standalone, no sidebar)
POST /login         → autenticazione
POST /logout        → logout
POST /cv            → salva CV → redirect /settings
POST /cover-letter  → genera cover letter → redirect /analysis/{id}
```

**Route JSON** (sotto `/api/v1/`): rispondono con JSON
```
POST   /api/v1/analyze
POST   /api/v1/status/{id}/{status}
DELETE /api/v1/analysis/{id}
POST   /api/v1/followup-email
POST   /api/v1/linkedin-message
POST   /api/v1/followup-done/{id}
GET    /api/v1/contacts/{id}
POST   /api/v1/contacts
DELETE /api/v1/contacts/{cid}
GET    /api/v1/spending
PUT    /api/v1/spending/budget
GET    /api/v1/dashboard
POST   /api/v1/interviews/{id}
GET    /api/v1/interviews/{id}
DELETE /api/v1/interviews/{id}
GET    /api/v1/interviews-upcoming
POST   /api/v1/batch/add
POST   /api/v1/batch/run
GET    /api/v1/batch/status
DELETE /api/v1/batch/clear
```

### Aggregatore API

```python
# api_v1.py
api_v1_router = APIRouter(prefix="/api/v1", tags=["api-v1"])
api_v1_router.include_router(analysis_api_router)
api_v1_router.include_router(followup_router)
api_v1_router.include_router(contacts_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(batch_router)
api_v1_router.include_router(interview_router)
```

### Swagger autodocumentazione

FastAPI genera automaticamente la documentazione Swagger su `/api/v1/docs`. Nessun codice extra necessario — il titolo, i tag e i parametri vengono inferiti dalle route.

---

## 9. Frontend e SSR

### Server-Side Rendering con Jinja2

Il frontend e' **server-side rendered** con architettura **multi-page**: ogni sezione ha la sua route e template dedicato (dashboard, analyze, history, interviews, settings). FastAPI genera l'HTML completo tramite Jinja2. La navigazione usa una sidebar fissa (60px, icon-only) su desktop e una bottom bar su mobile (≤768px). Non c'e' un framework JS (React, Vue, etc.).

```python
# Nelle route:
templates = request.app.state.templates
return templates.TemplateResponse("index.html", {"request": request, ...})
```

### Template structure

```
frontend/templates/
├── base.html                # Layout: sidebar + content area + toast container
├── dashboard.html           # Home: 6 widgets (follow-up, interviews, Cowork, activity, top 5, DB usage)
├── analyze.html             # Single + batch analysis (tab toggle)
├── history.html             # Analysis history with status tabs (URL hash + sessionStorage persistence)
├── analysis_detail.html     # Full analysis: score ring, status toggle, action card grid
├── interviews.html          # All upcoming interviews + past (collapsed)
├── stats.html               # 9 Chart.js charts (funnel, distribution, timeline, etc.)
├── agenda.html              # To-do page with DB-backed tasks
├── settings.html            # CV management + API credit tracking
├── admin.html               # Admin panel: parameters, maintenance, diagnostics
├── notifications.html       # Notification center with dismiss/undismiss
├── login.html               # Standalone login page (no sidebar)
├── 404.html                 # Error page (extends base, with sidebar)
├── 500.html                 # Error page (extends base, with sidebar)
└── partials/                # Reusable components
    ├── sidebar.html             # SVG icon nav items + theme toggle
    ├── score_ring.html          # SVG ring with color tiers (CSS-driven responsive sizing)
    ├── job_card.html            # Compact analysis row for lists
    ├── metric_card.html         # Big number + label card
    ├── result_reputation.html   # Glassdoor company rating
    ├── cover_letter_form.html   # Cover letter generation
    ├── cover_letter_result.html # Cover letter display
    ├── followup_alerts.html     # Follow-up email alerts
    ├── batch.html               # Batch analysis queue
    ├── interview_modal.html     # Interview booking modal
    └── interview_detail.html    # Interview detail card
```

`base.html` definisce sidebar, content-area wrapper e toast container. I template figli sovrascrivono `{% block content %}` e opzionalmente `{% block head_extra %}` e `{% block scripts_extra %}`. `login.html` e' standalone (non estende base.html) perche' non ha sidebar.

### CSS modulare

Il CSS e' suddiviso in file tematici, validati con **stylelint** in CI:

```
frontend/static/css/
├── variables.css    # Design tokens: dark (default) + light theme
├── base.css         # Reset, tipografia, fadeIn, utility classes (.hidden, .mb-*, .mt-*)
├── layout.css       # Sidebar (60px fixed), content area, responsive grid, theme toggle
├── components.css   # Score ring, cards, buttons, toast, modal, status toggle, action cards
└── sections.css     # Stili specifici per ogni pagina + flatpickr light mode overrides
```

### Tema chiaro/scuro

Il sistema supporta un toggle dark/light mode:

- I token di colore sono in `variables.css`: `:root` (dark, default) e `html[data-theme="light"]`
- Il tema viene persistito in `localStorage` e applicato prima del rendering CSS tramite un inline script in `<head>` (previene FOUC)
- Il toggle e' un bottone sun/moon nella sidebar, gestito da `toggleTheme()` in `app.js`
- Flatpickr ha overrides CSS dedicati per il tema chiaro in `sections.css`

### JavaScript modules

Vanilla JS con `fetch()` + **Alpine.js** per reattivita' dichiarativa:

```
frontend/static/js/modules/
├── toast.js       # Toast notification system
├── interview.js   # Modale colloquio (open, submit, delete)
├── status.js      # Cambio stato analisi (intercetta colloquio -> modale)
├── spending.js    # Aggiornamento budget (inline edit)
├── dashboard.js   # Caricamento statistiche
├── batch.js       # Gestione coda batch
├── contacts.js    # CRUD contatti recruiter
├── followup.js    # Generazione email/LinkedIn
├── analyze.js     # AJAX analysis submission (fetch POST to /api/v1/analyze)
├── cv.js          # Upload e download CV
└── history.js     # Filtri, ordinamento storico, tab persistence (hash + sessionStorage)
```

Tutti i fetch puntano a `/api/v1/...`. I moduli JS si caricano condizionalmente in base alla pagina attiva (typeof guards in app.js). Alpine.js gestisce la UI reattiva (tabs, toggle, x-show/x-cloak). Nessuna dipendenza build-time (no bundler, no npm in frontend).

Il JS gestisce anche il **rate limiting lato client**: `handleRateLimit(response, msg)` in `app.js` cattura le risposte 429 e mostra un alert con i secondi di attesa letti dall'header `Retry-After`.

### Accessibilita' (WCAG)

Il frontend implementa le best practice di accessibilita' web:

- **Skip link**: `<a href="#main-content" class="skip-link">` nascosto visivamente, appare con Tab per saltare al contenuto
- **Screen reader text**: classe `.sr-only` per testo leggibile solo da screen reader (es. label dei form)
- **Focus visible**: `:focus-visible` con outline `2px solid` per navigazione da tastiera, rimosso per click
- **ARIA labels**: `aria-label` su textarea, input, select e bottoni senza testo visibile
- **ARIA roles**: `role="status"` su messaggi di successo e spinner, `role="alert"` su toast notifications
- **ARIA dialog**: `role="dialog"` + `aria-modal="true"` + `aria-labelledby` sul modale colloquio
- **Label association**: `<label for="id">` su tutti i campi del form login
- **Landmark**: `id="main-content"` sulla pagina principale per lo skip link

### Responsive Design

Layout adattivo con media query a due breakpoint:

**768px** (tablet):
- Container con padding ridotto, h1 piu' piccolo
- Spending bar e followup alert passano a layout colonna
- Bottoni con `min-height: 44px` per touch target
- Tabs, toggle, pill-btn in layout verticale/wrap
- Result hero e contact form in colonna singola
- Input e textarea con `min-height: 44px`

**480px** (mobile):
- Padding container ulteriormente ridotto
- Login card con padding minimo

### Static files

In Docker Compose, nginx serve `/static/` direttamente (zero latenza backend):
```nginx
location /static/ {
    alias /usr/share/nginx/html/static/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

In single-container (Render.com), FastAPI serve i file statici con `StaticFiles`:
```python
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
```

---

## 10. Infrastruttura Docker

### docker-compose.yml

```yaml
services:
  frontend:     # nginx:1.27-alpine, :80, reverse proxy
  backend:      # python:3.12-slim, :8000 (solo interna)
  db:           # postgres:16-alpine, :5432, volume persistente
  redis:        # redis:7-alpine, :6379, cache opzionale
```

### Rete

Tutti i servizi comunicano sulla rete bridge `jobsearch`:
- `frontend` chiama `backend:8000`
- `backend` chiama `db:5432` e `redis:6379`
- Solo `frontend` espone la porta 80 all'host

Il backend **non** espone porte all'host in produzione Docker.

### Nginx come reverse proxy

```nginx
upstream backend {
    server backend:8000;
}

server {
    listen 80;

    location /static/ {
        alias /usr/share/nginx/html/static/;   # Servito diretto
        expires 30d;
    }

    location /api/v1/ {
        proxy_pass http://backend;              # JSON API
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        proxy_pass http://backend;              # SSR routes
    }
}
```

Header proxy fondamentali:
- `X-Forwarded-For`: IP reale del client (usato da rate limiter e audit)
- `X-Forwarded-Proto`: schema originale (per HSTS)
- `Host`: hostname originale

### Security headers (nginx)

Nginx aggiunge header di sicurezza su tutte le risposte:

- `X-Frame-Options: DENY` — previene clickjacking
- `X-Content-Type-Options: nosniff` — previene MIME sniffing
- `Referrer-Policy: strict-origin-when-cross-origin` — limita il referrer
- `Permissions-Policy` — disabilita geolocation, camera, microfono
- `Content-Security-Policy` — whitelist per script (self + unpkg + jsdelivr), stili (self + inline + jsdelivr), frame-ancestors none

### Gzip compression

Nginx comprime risposte > 1KB per i tipi: text/plain, text/css, text/javascript, application/javascript, application/json, image/svg+xml. Il backend in Render.com (senza nginx) non ha gzip nativo, ma Render.com edge proxy fornisce compressione.

### Subresource Integrity (SRI)

Tutte le risorse CDN hanno attributo `integrity` con hash SHA-384 per garantire che il contenuto non sia stato alterato:
- Alpine.js (unpkg.com)
- Flatpickr CSS, JS e locale (cdn.jsdelivr.net)

### Healthcheck

```yaml
db:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
    interval: 5s
    retries: 5

redis:
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
```

Il backend aspetta che `db` e `redis` siano healthy prima di avviarsi (`depends_on: condition: service_healthy`).

### Logging

Tutti i container usano il driver `json-file` con rotazione:
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"
```

Visualizzazione: `docker compose logs -f backend`

---

## 11. CI/CD

### GitHub Actions

Three workflows:

1. **CI** (`.github/workflows/ci.yml`) — runs on push/PR to main
2. **Daily backup** (`.github/workflows/daily-backup.yml`) — cron 03:30 UTC, wakes Render + calls `POST /api/v1/backup` to snapshot DB to R2
3. **Weekly cleanup** (`.github/workflows/weekly-cleanup.yml`) — cron 03:00 UTC

### CI Pipeline

5 jobs with dependencies:

```
lint ────────┐
             ├──→ test ──→ docker
frontend ────┘              ↑
security ───────────────────┘
```

**Job 1 - Ruff Lint & Format + mypy**: linting, formatting, and strict type checking (Python)
```yaml
- ruff check backend/src/ backend/tests/
- ruff format --check backend/src/ backend/tests/
- mypy backend/src/ (strict: --disallow-untyped-defs --no-implicit-optional --warn-return-any)
```

**Job 2 - Frontend Lint**: CSS + HTML + JS validation
```yaml
- stylelint "frontend/static/css/**/*.css"    # CSS lint (blocking)
- HTML tag validation (div open/close)        # Basic template check
- npx eslint frontend/static/js/              # ESLint for JavaScript
```

**Job 3 - Security Audit**: static analysis + dependency CVE check
```yaml
- bandit -r backend/src/ -c pyproject.toml -ll -ii   # High severity
- pip-audit -r backend/requirements.txt --desc        # CVE check
```

**Job 4 - Tests & Coverage**: 477 tests, pytest with coverage minimum 50%
```yaml
- pytest tests/ -v --tb=short --cov=src --cov-fail-under=50
  env:
    DATABASE_URL: "sqlite:///test.db"
    ANTHROPIC_API_KEY: "test-key"
```

**Job 5 - Docker Build**: verifies all images build successfully
```yaml
- docker compose build
```

Additionally, **CodeQL** runs as a separate GitHub-managed workflow for code scanning.

### Pre-commit Hooks

Il progetto usa **pre-commit** per validazione locale prima dei commit:

```yaml
# .pre-commit-config.yaml
- ruff (lint + format)           # Python quality
- stylelint                      # CSS validation
- trailing-whitespace            # Pulizia whitespace
- end-of-file-fixer              # Newline finale
- check-yaml, check-json         # Syntax check config
```

La configurazione stylelint e' in `.stylelintrc.json`, condivisa tra pre-commit e CI. ESLint (`.eslintrc.json`) runs in CI for JavaScript linting.

Installazione: `pip install pre-commit && pre-commit install`

### Test strategy

I test usano **SQLite in-memory** invece di PostgreSQL per velocita':

```python
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

Limitazione: SQLite non supporta JSONB e UUID nativi, ma funziona per testare la logica di business.

I servizi esterni (Anthropic API) sono mockati con `unittest.mock.MagicMock`.

### Coverage e test suite

477 tests, coverage > 55%, threshold CI: 50%. Real DB integration tests (no mocks for DB layer).

```
tests/
├── conftest.py                     # Fixture condivise (db_session, test_analysis, etc.)
├── test_analysis_service.py        # Analysis CRUD, status transitions, rebuild
├── test_anthropic_client.py        # JSON parsing (7 strategie), content_hash
├── test_audit_service.py           # Audit log creation, IP extraction
├── test_auth_service.py            # Password hashing, authenticate_user
├── test_batch_service.py           # Queue CRUD, clear, status
├── test_cache_service.py           # Redis/Null cache protocol
├── test_contacts_service.py        # Contacts CRUD
├── test_cover_letter_service.py    # get_by_id, build_docx
├── test_cv_service.py              # CV save, get_latest
├── test_dashboard_service.py       # Spending, dashboard stats
├── test_interview_service.py       # Interview CRUD, upcoming filter
├── test_notifications_service.py   # Fernet encrypt/decrypt, already_notified
└── test_routes.py                  # TestClient: health, 404, login, auth, multi-page rendering
```

I test di route usano `FastAPI.TestClient` con lifespan patchato per evitare migrazioni e servizi esterni:

```python
@asynccontextmanager
async def _test_lifespan(app):
    app.state.cache = NullCacheService()
    yield

with patch("src.main.lifespan", _test_lifespan):
    app = create_app()
    with TestClient(app) as client: ...
```

---

## 12. Deploy su Render.com

### Configuration

The app runs on Render.com (Frankfurt region) as a Docker web service (`srv-d7bp6o6a2pns73eouueg`). Auto-deploy triggers on push to `main`. The Dockerfile entrypoint runs Alembic migrations before starting Uvicorn.

- **Runtime**: Docker (backend/Dockerfile)
- **Plan**: Free tier
- **Region**: Frankfurt
- **Auto-deploy**: on commit to main
- **Custom domains**: jobsearches.cc, api.jobsearches.cc, www.jobsearches.cc (via Cloudflare DNS)

### Differences with Docker Compose

| Aspect | Docker Compose | Render.com |
|---------|---------------|--------|
| Container | 4 (nginx + backend + db + redis) | 1 (backend only) |
| Static files | Nginx serves /static/ | FastAPI StaticFiles |
| Database | Local container | Neon PostgreSQL (managed) |
| Cache | Redis container | None (REDIS_URL empty) |
| HTTPS | No (port 80) | Yes (Render edge proxy) |
| Port | 80 (nginx) → 8000 (backend) | 8080 direct |

### Database URL

Render.com uses `postgres://` as schema, but SQLAlchemy 2.0 requires `postgresql://`:

```python
@property
def effective_database_url(self) -> str:
    url = self.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url
```

---

## 13. Monitoring and Observability

### Checkly (External Monitoring)

6 API/browser checks managed as Terraform IaC in `infra/checkly/`:

- Health endpoint monitoring
- Key API endpoint checks
- Alerting on degradation

Configuration: `infra/checkly/checks.tf` with provider in `providers.tf`.

### Internal Metrics

The `metrics/` module provides request-level observability:

- **Middleware** (`metrics/middleware.py`): records request timing, status code, and path for every request
- **Storage**: `request_metrics` table (migration 016)
- **Dashboard**: admin-only metrics page at `/admin/metrics` with aggregated stats
- **Service** (`metrics/service.py`): aggregation queries (avg response time, error rate, top endpoints)

### DB Backup

- **Manual**: `POST /api/v1/backup` (API key auth) — dumps PostgreSQL to Cloudflare R2
- **Automated**: GitHub Actions daily cron (`daily-backup.yml`) at 03:30 UTC — wakes Render free tier, then calls backup endpoint
- **Storage**: Cloudflare R2 bucket (`jobsearch-files`, EEUR region)

### Notification Center

Server-side computed rules with dismiss/undismiss:

- Upcoming interviews
- Low budget warnings
- Interviews without outcome
- DB size approaching limit
- Pending follow-ups
- Application backlog

Dismissals are persisted in `notification_dismissals` table. Rules are re-evaluated on each page load.

---

## 14. Pattern e Decisioni Architetturali

### Protocol Pattern per Cache

Invece di un'interfaccia astratta (ABC), usiamo `typing.Protocol` per structural subtyping:

```python
class CacheService(Protocol):
    def get(self, key: str) -> str | None: ...
```

Qualsiasi classe con i metodi giusti soddisfa il protocollo, senza ereditarla. Questo permette test semplici:

```python
class NullCacheService:  # Non eredita da CacheService
    def get(self, key: str) -> str | None:
        return None
```

### Singleton Pattern

Usato per:
- `anthropic.Anthropic` client (evita overhead creazione HTTP client)
- `Limiter` di slowapi (condiviso tra tutte le route)
- `app_settings` nel DB (riga con id=1, seed al primo avvio)

### Content Hash per Deduplicazione

`SHA-256(CV + annuncio)` identifica univocamente ogni combinazione. Se esiste gia' un'analisi con lo stesso hash + modello, viene riusata senza chiamare l'API.

### Factory Pattern per Cache

`create_cache_service()` decide a runtime quale implementazione usare:
- Redis disponibile → `RedisCacheService`
- Redis non raggiungibile o URL vuoto → `NullCacheService`

L'app non sa (e non deve sapere) quale cache sta usando.

### Separation of Concerns: Routes vs Service

Le route gestiscono:
- Request parsing (form data, path params)
- Autenticazione (dipendenze FastAPI)
- Rendering (template o JSON)
- Audit logging

I service gestiscono:
- Logica di business
- Query database
- Chiamate API esterne
- Validazione dati

Questo permette di testare i service senza HTTP e di cambiare il transport layer senza toccare la logica.

### Batch Processing

The batch queue is **persistent in PostgreSQL** via the `batch_items` table. Each item stores the full job description, content hash, model choice, and processing status (`pending`, `running`, `done`, `skipped`, `error`). This design survives Render.com autostop, server crashes, and restarts — pending items are picked up on the next `batch_run` call.

Key endpoints:
- `POST /api/v1/batch/add` — enqueue a job description
- `POST /api/v1/batch/run` — start processing pending items
- `GET /api/v1/batch/status` — poll progress (batch_status polling every ~7s from the Cowork agent keeps Render.com awake during batch processing)
- `GET /api/v1/batch/results` — retrieve completed analyses
- `DELETE /api/v1/batch/clear` — clear the current batch queue
- `GET /api/v1/batch/pending-items` — return pending items + CV (for external processing)
- `POST /api/v1/batch/item/{id}/status` — update a single item's status

Deduplication: each item has a `content_hash` (SHA-256 of CV + job description). If an analysis with the same hash and model already exists, the item is marked `skipped` without calling the Anthropic API.

### Glassdoor con DB Cache

Invece di Redis (volatile), i dati Glassdoor sono cachati in PostgreSQL per 30 giorni:

```python
cached = db.query(GlassdoorCache).filter(...).first()
if cached and (now - cached.fetched_at) < timedelta(days=30):
    return _parse_cached(cached)
# Altrimenti chiama l'API e aggiorna il DB
```

Questo sopravvive ai riavvii e riduce le chiamate API a pagamento.

### Error Handling nell'AI Client

Il client Anthropic gestisce gli errori a piu' livelli:

1. **JSON parsing**: 7 strategie di fallback + retry con AI (8° tentativo)
2. **Pydantic validation**: schema validation post-parsing con warning log
3. **Cache**: evita chiamate duplicate
4. **Content hash**: evita rianalisi dello stesso contenuto
5. **Graceful degradation**: se Glassdoor fallisce, l'analisi prosegue senza reputation data

Non ci sono `try/except` generici che "mangiano" errori — ogni fallback e' intenzionale e documentato.

### Robustezza della Logica Core

Il sistema implementa diverse protezioni per garantire l'integrita' dei dati e prevenire costi imprevisti:

**Input validation:**
- CV max 100KB, job description max 50KB (configurabili via `config.py`)
- Campi interview con limiti Pydantic (`max_length` per tipo, nome, email, link, note)
- Datetime colloqui: no date nel passato, `ends_at > scheduled_at`

**Budget enforcement:**
- `check_budget_available()` verifica il budget residuo prima di ogni chiamata AI
- Se il budget e' esaurito, analisi, batch e cover letter vengono bloccati con messaggio
- Lo spending tracker si aggiorna atomicamente con l'analisi

**Transazioni atomiche:**
- `db.rollback()` in tutti i catch block delle route (analisi, cover letter, batch)
- Impedisce la persistenza di stato inconsistente (es. analisi salvata ma spending non aggiornato)
- L'audit log viene scritto dopo il rollback in una transazione separata

**Anthropic API resilience:**
- Client con timeout 120s e 3 retry automatici con backoff esponenziale (SDK built-in)
- 7 strategie di JSON parsing + AI-assisted repair come 8° tentativo
- Cache Redis per evitare chiamate duplicate

### Notifiche Email

Il modulo `notifications/` invia email SMTP quando un'analisi con raccomandazione APPLY viene completata:

```python
# Le credenziali SMTP sono criptate con Fernet
def encrypt_credential(value: str) -> str:
    return Fernet(settings.fernet_key).encrypt(value.encode()).decode()
```

- **Anti-spam**: header compliant (List-Unsubscribe, Message-ID, MIME multipart)
- **Rate limiting**: massimo 1 email per analisi (deduplicazione via `notification_logs`)
- **Graceful degradation**: se SMTP non configurato, le notifiche vengono silenziosamente skippate

---

## 15. MCP Server (Claude Desktop Integration)

### Architettura

Il MCP server è un thin proxy locale (~120 righe) che espone 15 read-only tool via Model Context Protocol (MCP), permettendo di interrogare e gestire il database delle candidature direttamente da Claude Desktop.

```
Claude Desktop (stdio) → MCP Server (local) → HTTPS + X-API-Key → FastAPI backend (Render.com) → PostgreSQL
```

### Stack tecnico

| Componente | Tecnologia |
|-----------|-----------|
| Framework | FastMCP (Python MCP SDK) |
| Trasporto | stdio (local, macOS) |
| Auth | API key (X-API-Key header) |
| Deploy | Locale via Claude Desktop |
| HTTP client | httpx (async, retry with backoff) |

### Pattern MCP → Backend API → DB

Il MCP server **non accede direttamente al database**. Ogni tool chiama un endpoint REST del backend via HTTP:

```python
@mcp.tool()
async def get_candidature(status: str | None = None, limit: int = 50) -> dict:
    params = {"limit": limit}
    if status:
        params["status"] = status
    return await api_get("/api/v1/candidature", params)
```

Vantaggi:
- **Security**: un solo punto di accesso al DB (il backend), con auth e rate limiting
- **DRY**: le query SQL restano nel backend, il MCP le riusa
- **Semplicità**: il MCP server è un thin proxy (~120 righe)

### Auto-wake e networking

Il MCP server usa l'URL pubblico del backend (`https://jobsearch.fly.dev`) invece della rete interna Render.com (`*.internal`). Questo perché i nomi `.internal` non triggerano l'auto-start delle VM in sleep — solo il proxy pubblico di Render.com sveglia le macchine automaticamente.

### Tool disponibili (25)

| Tool | Endpoint | Descrizione |
|------|----------|------------|
| `get_candidature` | `/api/v1/candidature` | Lista con filtro per stato |
| `search_candidature` | `/api/v1/candidature/search` | Ricerca per azienda/ruolo |
| `get_candidature_detail` | `/api/v1/candidature/{id}` | Dettaglio completo |
| `get_top_candidature` | `/api/v1/candidature/top` | Top per score |
| `get_candidature_by_date_range` | `/api/v1/candidature/date-range` | Per periodo |
| `get_stale_candidature` | `/api/v1/candidature/stale` | Senza aggiornamenti |
| `get_upcoming_interviews` | `/api/v1/interviews-upcoming` | Colloqui prossimi |
| `get_interview_prep` | `/api/v1/interview-prep/{id}` | Preparazione colloquio |
| `get_cover_letter` | `/api/v1/cover-letters/{id}` | Lettera di presentazione |
| `search_contacts` | `/api/v1/contacts/search` | Ricerca contatti |
| `get_dashboard_stats` | `/api/v1/dashboard` | Stats generali |
| `get_spending` | `/api/v1/spending` | Costi API |
| `get_pending_followups` | `/api/v1/followups/pending` | Follow-up in attesa |
| `get_activity_summary` | `/api/v1/activity-summary` | Riepilogo attività |
| `db_usage` | `/api/v1/db-usage` | Monitoraggio utilizzo PostgreSQL vs 1GB free tier |
| `cleanup_old_analyses` | `/api/v1/cleanup` | Pulizia analisi vecchie a basso score (dry-run default) |

### Configurazione Claude Desktop

```json
{
  "mcpServers": {
    "JobSearch": {
      "command": "python",
      "args": ["/path/to/mcp-server/server.py"],
      "env": {
        "BACKEND_URL": "https://api.jobsearches.cc",
        "API_KEY": "your-api-key"
      }
    }
  }
}
```

Il file si trova in `~/Library/Application Support/Claude/claude_desktop_config.json` su macOS.

### Test

18 test unitari (pytest + asyncio):
- `test_server.py`: 16 test — verifica che ogni tool chiami l'endpoint corretto con i parametri giusti
- `test_api_client.py`: 3 test — login flow, estrazione session cookie, gestione errori

---

## 16. Learning Loop (Analytics + Auto-Adapt)

The tool implements a **closed feedback loop** between the user's triage decisions and the AI analysis prompt. The goal: as the user accumulates triaged analyses (APPLY / CONSIDER / SKIP / rejected / hired), the tool learns the user's implicit preferences and injects them into future prompts automatically — no manual prompt tuning required.

### Architecture

```
  [1] User triages analyses (status changes, outcomes)
           │
           ▼
  [2] /analytics page unlocks when ≥15 new triaged analyses exist
      since the last AnalyticsRun
           │
           ▼
  [3] User triggers a run → backend/src/analytics_page/service.py
           │
           ▼
  [4] backend/src/analytics/ computes (pure Python, no external deps):
        • aggregate stats (distribution, scoring bias)
        • discriminant features (what differentiates applied vs skipped)
        • bias signals (model drift, score inflation, tech stack drift)
           │
           ▼
  [5] Persist snapshot in `analytics_runs` (audit trail)
      Update `user_profiles` with refreshed `prompt_snippet`
           │
           ▼
  [6] Next call to analyze() → prompt_snippet auto-prepended
      to Claude system prompt → AI aligns with user's learned preferences
           │
           └─► loop back to [1]
```

### Module Split

| Module | Purpose | Dependencies |
|--------|---------|--------------|
| `backend/src/analytics/` | Pure data-science primitives (stats, discriminants, bias) | **None** (stdlib only) |
| `backend/src/analytics_page/` | Route handler, orchestration, DB persistence | SQLAlchemy, FastAPI |

The split keeps the core analysis logic **deterministic, testable, and dep-free**. The page module is the thin HTTP/DB glue.

### Database

- **`analytics_runs`**: one row per `/analytics` execution. Stores snapshot of computed stats/discriminants/bias as JSONB + timestamp + user_id. Audit-trail friendly — you can diff two runs to see how the learned profile evolved.
- **`user_profiles`**: 1:1 with `users`. Stores the latest learned `prompt_snippet` (string, prepended to AI calls) plus structured metadata (dominant tracks, preferred stacks, red flags). Updated on each `/analytics` run.

### Unlock Gate

The `/analytics` entry in the sidebar is **locked** until at least **15 new triaged analyses** exist since the last `analytics_runs.created_at`. This avoids:
- running expensive recomputes on stale data
- updating the profile on too-small samples (noise > signal)

### Prompt Injection Point

In `analysis/service.py`, before calling the Anthropic client:

```python
profile = get_user_profile(db, user_id)
system_prompt = profile.prompt_snippet + "\n\n" + base_system_prompt_v7
```

If `user_profiles` row is empty (first run), the base v7 prompt is used unchanged. Once the user completes their first `/analytics` pass, the snippet starts shaping subsequent analyses.

### CLI Scripts (Offline Analysis)

For power users who want to run analytics offline or on a DB snapshot:

- `scripts/export_db.py` — dump relevant tables (job_analyses, interviews, outcomes) to JSON
- `scripts/analyze_db.py` — run the same `backend/src/analytics/` primitives on an exported snapshot, outputs a report

Useful for A/B testing prompt snippets without touching production data.

### Career Track as a Discriminant

The `career_track` field (see section 6) is a first-class discriminant in the learning loop: the analytics module tracks the user's triage decisions **per track**, which lets the profile capture patterns like "user consistently applies to `plan_a_devops` + `hybrid_a_b` but skips `plan_b_dev`". The resulting `prompt_snippet` steers the AI toward highlighting that bias on future jobs.
