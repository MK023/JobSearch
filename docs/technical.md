# Documentazione Tecnica - Job Search Command Center

## Indice

1. [Panoramica Architetturale](#1-panoramica-architetturale)
2. [Struttura del Progetto](#2-struttura-del-progetto)
3. [Backend: FastAPI e App Factory](#3-backend-fastapi-e-app-factory)
4. [Database e ORM](#4-database-e-orm)
5. [Autenticazione e Sicurezza](#5-autenticazione-e-sicurezza)
6. [Integrazione AI (Anthropic Claude)](#6-integrazione-ai-anthropic-claude)
7. [Cache e Performance](#7-cache-e-performance)
8. [API Versioning](#8-api-versioning)
9. [Frontend e SSR](#9-frontend-e-ssr)
10. [Infrastruttura Docker](#10-infrastruttura-docker)
11. [CI/CD](#11-cicd)
12. [Deploy su Fly.io](#12-deploy-su-flyio)
13. [Pattern e Decisioni Architetturali](#13-pattern-e-decisioni-architetturali)

---

## 1. Panoramica Architetturale

Il progetto segue un'architettura a **microservizi containerizzati** con 4 componenti:

```
Browser → Nginx (reverse proxy) → FastAPI (backend) → PostgreSQL + Redis
                                                     → Anthropic Claude API
                                                     → RapidAPI (Glassdoor)
```

### Principi di design

- **Separation of concerns**: nginx gestisce static files e routing, il backend gestisce logica e rendering
- **Graceful degradation**: Redis e Glassdoor sono opzionali, l'app funziona senza
- **Fail-fast**: variabili d'ambiente mancanti bloccano lo startup (non il runtime)
- **Defense in depth**: rate limiting + CORS + security headers + trusted hosts + audit trail

---

## 2. Struttura del Progetto

```
backend/src/
├── main.py              # App factory (create_app)
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
│   ├── models.py        # User model
│   ├── service.py       # hash_password, authenticate_user
│   └── routes.py        # /login, /logout (HTML)
│
├── cv/                  # Gestione CV
│   ├── models.py        # CVProfile model
│   ├── service.py       # get_latest_cv, save_cv
│   └── routes.py        # /cv (HTML)
│
├── analysis/            # Core: analisi AI
│   ├── models.py        # JobAnalysis, AppSettings, AnalysisStatus
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
├── dashboard/           # Spese e statistiche
│   ├── service.py       # add_spending, seed_totals
│   └── routes.py        # /spending, /dashboard (JSON API)
│
├── batch/               # Analisi batch
│   ├── service.py       # Coda in-memory, run_batch
│   └── routes.py        # /batch/* (JSON API)
│
├── audit/               # Audit trail
│   ├── models.py        # AuditLog model
│   └── service.py       # audit() helper
│
└── integrations/        # Client esterni
    ├── anthropic_client.py  # Claude API + JSON retry
    ├── cache.py             # Redis/Null cache (Protocol)
    └── glassdoor.py         # Company ratings (RapidAPI)
```

Ogni modulo segue il pattern **models → service → routes**:
- `models.py`: definizione tabella SQLAlchemy
- `service.py`: logica di business (nessuna dipendenza da HTTP)
- `routes.py`: handler HTTP che chiama il service

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
    Base.metadata.create_all(bind=engine)     # Crea tabelle se non esistono
    app.state.cache = create_cache_service()  # Redis o NullCache
    ensure_admin_user(db)                     # Crea admin da env
    seed_spending_totals(db)                  # Inizializza riga singleton
    yield
    # Shutdown (niente da fare)
```

### Stack Middleware

I middleware sono applicati in ordine LIFO (ultimo aggiunto = piu' esterno):

```
Request → SecurityHeaders → CORS → TrustedHost → SlowAPI → Session → Route Handler
```

1. **SecurityHeaders** (custom `@app.middleware`): aggiunge X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy, HSTS
2. **CORSMiddleware**: origins configurabili via `CORS_ALLOWED_ORIGINS`
3. **TrustedHostMiddleware**: attivo solo se `TRUSTED_HOSTS != "*"`
4. **SlowAPIMiddleware**: rate limiting globale con slowapi
5. **SessionMiddleware**: sessioni server-side con itsdangerous (TTL 7 giorni)

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

`pool_pre_ping=True` e' fondamentale: evita errori "connection closed" dopo periodi di inattivita' (es. Fly.io che dorme la VM).

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
| `users` | Utenti con login | 1:N cv_profiles, 1:N audit_logs |
| `cv_profiles` | CV in testo plain | FK user_id, 1:N job_analyses |
| `job_analyses` | Risultato analisi AI | FK cv_id, 1:N cover_letters + contacts |
| `cover_letters` | Lettere generate | FK analysis_id |
| `contacts` | Contatti recruiter | FK analysis_id |
| `app_settings` | Budget e spese (singleton) | Nessuna FK |
| `glassdoor_cache` | Cache rating aziende | Nessuna FK |
| `audit_logs` | Trail azioni utente | FK user_id (SET NULL) |

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
    ├── 001_initial_schema.py   # Tutte le tabelle originali
    └── 002_add_audit_logs.py   # Tabella audit aggiunta dopo
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
    "sonnet": "claude-sonnet-4-5-20250929",  # Approfondito, costoso
}
```

### Flusso di una chiamata API

```
_call_api() → messages.create() → raw_text → _extract_and_parse_json() → dict
                                                      ↓ fallback
                                              _retry_json_fix() → AI corregge il JSON
```

### Parsing JSON robusto (4 + 1 tentativi)

L'AI non sempre produce JSON valido. `_extract_and_parse_json()` tenta 4 strategie:

1. **Parse diretto**: `json.loads(text)` — funziona nel 90% dei casi
2. **Clean JSON**: rimuove trailing comma, commenti `//`, aggiunge virgole mancanti
3. **Estrai frammento**: trova il primo `{` e l'ultimo `}`, estrae il frammento
4. **Fix control chars**: sostituisce `\t`, `\f` non escapati

Se tutti falliscono, `_retry_json_fix()` chiede all'AI stessa di correggere il JSON rotto:

```python
def _retry_json_fix(model_id, broken_json):
    fix_msg = client.messages.create(
        system="You fix malformed JSON. Respond ONLY with the corrected JSON.",
        messages=[{"role": "user", "content": f"Fix this malformed JSON:\n\n{broken_json}"}],
    )
    return _extract_and_parse_json(fix_msg.content[0].text)
```

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
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}

def _calculate_cost(usage, model_id):
    input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
    output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
```

Ogni analisi traccia: token input, token output, costo in USD. I totali vengono aggregati in `app_settings`.

### Prompt Engineering

I prompt sono in `prompts.py`, ottimizzati per minimizzare token:
- **Schema JSON inline**: ogni campo su una riga
- **Regole in formato tabellare**: `80-100=APPLY | 60-79=CONSIDER | ...`
- **Zero ridondanza**: niente ripetizioni tra system e user prompt
- **Istruzioni sullo scoring calibrato**: lo score deve riflettere competenze REALI e DIMOSTRATE

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

**Route HTML** (root level): servono pagine Jinja2
```
GET  /              → pagina principale
GET  /login         → form login
POST /login         → autenticazione
POST /logout        → logout
POST /cv            → salva CV
POST /analyze       → avvia analisi
GET  /analysis/{id} → dettaglio analisi
POST /cover-letter  → genera cover letter
```

**Route JSON** (sotto `/api/v1/`): rispondono con JSON
```
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
```

### Swagger autodocumentazione

FastAPI genera automaticamente la documentazione Swagger su `/api/v1/docs`. Nessun codice extra necessario — il titolo, i tag e i parametri vengono inferiti dalle route.

---

## 9. Frontend e SSR

### Server-Side Rendering con Jinja2

Il frontend e' **server-side rendered**: FastAPI genera l'HTML completo e lo invia al browser. Non c'e' un framework JS (React, Vue, etc.).

```python
# Nelle route:
templates = request.app.state.templates
return templates.TemplateResponse("index.html", {"request": request, ...})
```

### Template structure

```
frontend/templates/
├── base.html       # Layout base (head, nav, footer)
├── index.html      # Pagina principale (CV + analisi + dashboard)
└── login.html      # Form di login
```

`base.html` definisce i blocchi Jinja2 (`{% block content %}`) che i template figli sovrascrivono.

### JavaScript modules

Vanilla JS con `fetch()` per le operazioni asincrone:

```
frontend/static/js/modules/
├── status.js      # Cambio stato analisi (candidato/colloquio/scartato)
├── spending.js    # Aggiornamento budget
├── dashboard.js   # Caricamento statistiche
├── batch.js       # Gestione coda batch
├── contacts.js    # CRUD contatti recruiter
└── followup.js    # Generazione email/LinkedIn
```

Tutti i fetch puntano a `/api/v1/...`. Nessuna dipendenza esterna (no jQuery, no htmx).

### Static files

In Docker Compose, nginx serve `/static/` direttamente (zero latenza backend):
```nginx
location /static/ {
    alias /usr/share/nginx/html/static/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

In single-container (Fly.io), FastAPI serve i file statici con `StaticFiles`:
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

### GitHub Actions (`.github/workflows/ci.yml`)

Pipeline a 3 stage:

```
lint → test → docker
```

**Stage 1 - Lint**: pyflakes su tutto il codice
```yaml
- run: pip install pyflakes
- run: pyflakes src/ tests/
```

**Stage 2 - Test**: pytest con SQLite in-memory
```yaml
- run: pip install -r requirements.txt pytest
- run: pytest tests/ -v --tb=short
  env:
    DATABASE_URL: "sqlite:///test.db"
    ANTHROPIC_API_KEY: "test-key"
```

**Stage 3 - Docker**: verifica che le immagini si buildano
```yaml
- run: docker compose build
```

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

---

## 12. Deploy su Fly.io

### Configurazione (`fly.toml`)

```toml
app = "jobsearch"
primary_region = "cdg"              # Parigi

[build]
  dockerfile = "backend/Dockerfile"  # Usa il Dockerfile del backend

[processes]
  app = "uvicorn src.main:app --host 0.0.0.0 --port 8080"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"       # Dormi dopo inattivita'
  auto_start_machines = true        # Svegliati alla prima richiesta
  min_machines_running = 0          # Zero quando nessuno usa l'app
```

### Differenze con Docker Compose

| Aspetto | Docker Compose | Fly.io |
|---------|---------------|--------|
| Container | 4 (nginx + backend + db + redis) | 1 (solo backend) |
| Static files | Nginx serve /static/ | FastAPI StaticFiles |
| Database | Container locale | Fly Postgres (managed) |
| Cache | Redis container | Nessuna (REDIS_URL vuoto) |
| HTTPS | No (porta 80) | Si (force_https=true) |
| Porta | 80 (nginx) → 8000 (backend) | 8080 diretto |

### Database URL

Fly.io usa `postgres://` come schema, ma SQLAlchemy 2.0 richiede `postgresql://`:

```python
@property
def effective_database_url(self) -> str:
    url = self.database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url
```

---

## 13. Pattern e Decisioni Architetturali

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

La coda batch e' **in-memory** (dict Python), non persistente:

```python
_batch_queue: dict[str, dict] = {}
```

Scelta deliberata: il batch e' una feature di sessione, non un job queue persistente. Se il server riavvia, la coda si svuota. Per un job queue persistente servirebbe Celery + broker (over-engineering per questo caso d'uso).

Il processing avviene come `BackgroundTask` di FastAPI: la risposta HTTP torna subito, l'elaborazione continua in background.

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

1. **JSON parsing**: 4 strategie di fallback + retry con AI
2. **Cache**: evita chiamate duplicate
3. **Content hash**: evita rianalisi dello stesso contenuto
4. **Graceful degradation**: se Glassdoor fallisce, l'analisi prosegue senza reputation data

Non ci sono `try/except` generici che "mangiano" errori — ogni fallback e' intenzionale e documentato.
