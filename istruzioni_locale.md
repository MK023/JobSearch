# JobSearch — istruzioni locale

Guida pratica in italiano per far girare JobSearch sul Mac, sincronizzato con la copia di produzione su Supabase. Per la versione tecnica completa (in inglese) vedi `docs/LOCAL_DEV.md`.

---

## 1. Cosa serve

- Docker Desktop avviato
- File `.env` al root del repo (per le credenziali R2 — già configurato)
- Sei nella cartella del repo: `cd ~/Documents/GitHub/JobSearch`

---

## 2. Setup primo avvio (~30 secondi)

```bash
make dev-bootstrap
make dev-restore-from-r2
```

- **`make dev-bootstrap`**: avvia 4 container (backend, frontend, db, redis) + applica tutte le migration Alembic (schema vuoto).
- **`make dev-restore-from-r2`**: scarica l'ultimo backup pg_dump da R2 (cron quotidiano 03:00 UTC) e lo carica nel DB locale. Dopo, il DB locale è una copia esatta di produzione.

> **Nota:** se R2 non ha ancora archivi (cron non ha ancora girato), usa l'archivio su disco:
> ```bash
> make dev-restore-from-file FILE=~/Documents/JobSearch_backups/neon-dump-20260429-pre-supabase-migration.sql.gz
> ```

Apri **http://localhost** o **http://localhost:8000** → login con la stessa email + password che usi su `jobsearches.cc`.

---

## 3. Workflow giornaliero

| Cosa vuoi fare | Comando |
|---|---|
| Avviare lo stack (i dati restano dal giorno prima) | `make up` |
| Spegnere lo stack (i dati restano salvi) | `make down` |
| Cancellare TUTTO (container + volumi + dati) | `make clean` |
| Vedere i log del backend in tempo reale | `make logs-backend` |
| Aprire psql sul DB locale | `make db` |
| Eseguire i test | `make test` |
| Lint completo (Python + CSS) | `make lint` |
| Vedere i log produzione su Render | `make render-logs` |

I dati nel DB locale persistono finché non fai `make clean`. Per **risincronizzare** il locale con la produzione (es. dopo qualche giorno): `make dev-restore-from-r2`.

---

## 4. Cambiare ambiente al volo (`JOBSEARCH_ENV`)

Il file `config.toml` al root ha 2 sezioni pre-configurate. Lanciando il backend dal Mac (non in container) con la variabile `JOBSEARCH_ENV` settata, l'app punta automaticamente al DB / Redis giusti.

```bash
cd backend

# Locale (Docker compose)
JOBSEARCH_ENV=local uvicorn src.main:app --reload --port 8000

# Disaster recovery (stesso DB locale, Redis db=1 per non collidere con local)
JOBSEARCH_ENV=dr uvicorn src.main:app --reload --port 8000

# Produzione (NON serve flag — legge dal .env / Render dashboard)
uvicorn src.main:app --port 8000
```

> **Verifica veloce di quale URL Pydantic risolve:**
> ```bash
> JOBSEARCH_ENV=local python3 -c "from src.config import settings; print(settings.database_url)"
> ```

⚠️ In produzione, **NON impostare `JOBSEARCH_ENV`**. Render usa le sue env vars dalla dashboard.

---

## 5. Login locale

Hai due opzioni:

**Opzione A — credenziali di produzione (default).**
Dopo `make dev-restore-from-r2`, il DB locale ha la tabella `users` identica a prod. Login con la stessa email + password che usi su `jobsearches.cc`.

**Opzione B — password locale-only (più igienica).**
Se non vuoi digitare la password prod su localhost, generane una solo per il dev:

```bash
# 1. Genera l'hash (output: $2b$12$abc...XYZ)
docker compose exec -T backend python3 -c \
  "from src.auth.security import hash_password; print(hash_password('dev-local-not-real'))"

# 2. Aggiorna nel DB
make db
```
Dentro psql:
```sql
UPDATE users
SET hashed_password = '$2b$12$abc...XYZ'   -- incolla qui
WHERE email = 'marco.bellingeri@gmail.com';
\q
```

Ora ti logghi su localhost con `marco.bellingeri@gmail.com` + `dev-local-not-real`.
Produzione resta intoccata.

---

## 6. Backup e disaster recovery

**Cosa succede automaticamente:**
- **Daily 03:00 UTC** → cron `daily-backup-pg-dump.yml` chiama `/api/v1/backup/full` su prod, salva pg_dump compresso su R2 (path `backups-pg/{date}/{HHMMSS}.sql.gz`). Retention: 14 archivi.
- **Daily 03:30 UTC** → cron `daily-backup.yml` (più vecchio, parziale) salva 7 tabelle critiche come JSON. Backup ridondante per restore parziale veloce.

**Cosa puoi fare manualmente:**
- Scaricare l'ultimo pg_dump in locale → `make dev-restore-from-r2`
- Forzare un backup pg_dump fuori cron → `gh workflow run daily-backup-pg-dump.yml` (usa GitHub Actions manuale)
- Restore da archivio su disco (es. `~/Documents/JobSearch_backups/...`) → `make dev-restore-from-file FILE=<path>`

**In caso di emergenza (Supabase down):**
1. `make dev-bootstrap` (avvia stack locale)
2. `make dev-restore-from-r2` (popola da R2)
3. `JOBSEARCH_ENV=dr uvicorn src.main:app` (avvia backend pointing al locale)
4. Lavori in locale finché Supabase torna su
5. Quando Supabase torna, fai pg_dump del locale e restore su Supabase con `psql --single-transaction`

---

## 7. Cleanup hardware (Mac 8GB RAM)

Quando hai finito per la giornata:

```bash
make down       # ferma container, mantiene i dati
```

oppure più aggressivo (libera tutta la RAM Docker):

```bash
make clean      # ti chiede conferma, risponde 'y'
docker system prune -f   # libera image dangling
```

---

## 8. Cheat sheet rapidissimo

```bash
# Setup primo
make dev-bootstrap && make dev-restore-from-r2

# Lavoro quotidiano
make up                    # mattina
make logs-backend          # vedi log
make db                    # psql se serve
make down                  # sera

# Risincronizza con prod
make dev-restore-from-r2

# Backend dal Mac (non containerizzato), DB locale Docker
cd backend && JOBSEARCH_ENV=local uvicorn src.main:app --reload

# Trigger backup manuale
gh workflow run daily-backup-pg-dump.yml

# Reset totale
make clean
```

---

## Quando qualcosa non funziona

- **`alembic upgrade head` dice `ModuleNotFoundError: No module named 'src'`** → il container non ha `PYTHONPATH=/app/backend` (già fixato in PR #205, ma se rompe ancora aggiungilo a mano in `backend/Dockerfile`).
- **Restore dice `type "X" already exists`** → il DB ha già lo schema. Lo script `dev_restore.py` lo gestisce (drop+recreate prima del restore). Se vedi l'errore, lanci `psql` direttamente bypassando lo script.
- **`backend never became healthy`** → guarda `make logs-backend`, di solito è una env var mancante. Aggiungi il default in `docker-compose.yml` con `${VAR:-fallback}`.
- **R2 vuoto, `dev-restore-from-r2` fallisce** → forza il primo backup con `gh workflow run daily-backup-pg-dump.yml` e aspetta ~3 min, poi riprova.

Per troubleshooting più profondo vai su `docs/LOCAL_DEV.md`.
