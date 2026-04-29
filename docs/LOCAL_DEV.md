# Local development & disaster recovery

How to run JobSearch on your laptop with the same shape as production
(Render + Supabase), populate the local DB from a real prod dump, and
flip the entire DB/Redis wiring with a single env var.

This is the operational counterpart to the disaster-recovery story
documented in PRs #199 → #205 (29 Apr 2026).

## Prerequisites

- Docker Desktop running (≥ 24.x)
- `make`, `git`, `python3` (3.11+) on PATH
- A `.env` at the repo root with at least the `R2_*` credentials
  (only needed for `make dev-restore-from-r2`; everything else has
  safe defaults via Compose)
- The `render` CLI authenticated (only for `make render-logs` /
  `make render-status`)

## Quick start

First-time setup, from a clean checkout:

```bash
make dev-bootstrap                           # up + alembic upgrade head
make dev-restore-from-r2                     # populate DB from R2
```

That's it. Open <http://localhost> (frontend nginx) or
<http://localhost:8000> (backend direct). Login with **the same
credentials you use on production** — the dump preserves the real
`users` table.

If R2 has no archives yet (the daily cron hasn't fired), use the
on-disk dump instead:

```bash
make dev-restore-from-file FILE=~/Documents/JobSearch_backups/<file>.sql.gz
```

## Daily workflow

| Goal | Command |
|---|---|
| Start the stack (data persists in `pgdata` volume) | `make up` |
| Stop the stack (data stays safe) | `make down` |
| Wipe everything (containers + volumes) | `make clean` |
| Tail backend logs live | `make logs-backend` |
| Open `psql` shell on the local DB | `make db` |
| Run unit tests | `make test` |
| Lint everything (Python + CSS) | `make lint` |
| Render production logs | `make render-logs` |

After `make clean`, redo the **Quick start** to repopulate.

## Sync local DB with production

Production runs a daily `pg_dump` at 03:00 UTC (see
`.github/workflows/daily-backup-pg-dump.yml`). Each run uploads a
gzipped SQL archive to R2 under `backups-pg/{date}/{HHMMSS}.sql.gz`.
Retention: 14 archives = 2 weeks of point-in-time recovery.

```bash
make dev-restore-from-r2
```

Internals (`scripts/dev_restore.py --from-r2 --yes`):

1. List `backups-pg/` in the configured R2 bucket.
2. Pick the newest `.sql.gz` by `LastModified`.
3. Download it to a temp file.
4. `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` on the local
   DB so the dump's `CREATE TYPE` / `CREATE TABLE` statements don't
   collide with whatever's already there (alembic migrations from
   `dev-bootstrap`, leftover state from previous restores, etc.).
5. `gunzip -c <tmp> | docker compose exec -T db psql --single-transaction --set ON_ERROR_STOP=on`.
6. Print the source key and the new counts.

If the restore fails mid-way, the `--single-transaction` rolls back —
the local DB is never left in a half-populated state.

To force a fresh prod backup (ahead of the 03:00 UTC schedule):

```bash
gh workflow run daily-backup-pg-dump.yml
```

The workflow run takes ~3 min end-to-end. After it completes,
`make dev-restore-from-r2` will pick it up.

## Environment switching with `JOBSEARCH_ENV`

The Pydantic config loader (`backend/src/config.py`) reads an optional
`config.toml` at the repo root. Setting `JOBSEARCH_ENV=<name>` makes
the loader translate every key in `[env.<name>]` into an
UPPER-CASED env var **before** Settings is constructed — flipping the
entire DB / Redis / etc. wiring with one variable.

Sections shipped in `config.toml`:

| `JOBSEARCH_ENV` | DB target | Redis logical db |
|---|---|---|
| *unset* (production path) | whatever the OS env / Render dashboard / `.env` says | `0` (or whatever's in env) |
| `local` | `postgresql://jobsearch:jobsearch@localhost:5432/jobsearch` | `0` |
| `dr` | same as `local` | `1` (separate namespace, no key clash with a parallel `local` session) |

In production, **leave `JOBSEARCH_ENV` unset** — the loader is a
no-op, the Render dashboard env vars stay authoritative.

Example:

```bash
# Run the API from your Mac shell against the local Docker DB
cd backend
JOBSEARCH_ENV=local uvicorn src.main:app --reload --port 8000

# Sanity check what URL Pydantic resolved
JOBSEARCH_ENV=dr python3 -c \
  "from src.config import settings; print(settings.database_url, settings.redis_url)"
```

To add a new section (e.g. a `[env.staging]` pointing at a separate
Render preview), edit `config.toml` directly. The file is committed —
**do not put secrets there**, only connection targets. Secrets stay
in OS env vars or in the Render dashboard.

## Make targets reference

```bash
make help   # full target list with descriptions
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'src'` from `alembic upgrade head`
The runtime container needs `PYTHONPATH=/app/backend`. Already set in
`backend/Dockerfile`. If you're invoking alembic from the host shell
instead, prepend `PYTHONPATH=.` from inside `backend/`.

### `ERROR: type "batchitemstatus" already exists` during restore
The local DB still has schema (typically from a previous
`dev-bootstrap`). The restore script auto-handles this by dropping
and recreating `public` before the dump. If you ever see the error,
it means you skipped `scripts/dev_restore.py` and called `psql`
directly — go through the Make target.

### `dev-restore-from-r2` says "No .sql.gz objects under backups-pg/"
The daily backup workflow hasn't run yet on this branch, or it ran
but failed. Trigger manually with `gh workflow run daily-backup-pg-dump.yml`,
then check the Actions tab for the run. Otherwise fall back to
`make dev-restore-from-file FILE=...`.

### Compose interpolates `${VAR}` to empty string in CI / on a clean shell
That's the `${VAR:-fallback}` pattern doing its job. The base
`docker-compose.yml` defines safe fallbacks for `POSTGRES_USER`,
`ANTHROPIC_API_KEY`, `DATABASE_URL`. If you see "variable not set"
warnings on `docker compose up`, they're informational — Compose
applies the defaults silently.

### "Backend never became healthy in 90s" in CI
Pull the per-service log spool from the failed Actions run (the
`Spooler` step always runs, even on failure). Most likely a
startup-validation mismatch — check the lifespan output for
`ANTHROPIC_API_KEY missing` or similar. Add the missing var to the
backend `environment:` block in `docker-compose.yml` with a fixture
default.

## Cross-references

- `docker-compose.yml` — the single source of truth for the dev stack.
- `backend/Dockerfile` — multi-stage, non-root, K8s-ready (CIS 4.1).
- `backend/src/integrations/db_dump.py` — the pg_dump endpoint.
- `scripts/dev_restore.py` — the restore CLI used by the Make targets.
- `config.toml` — environment-switching config.
- `.github/workflows/daily-backup-pg-dump.yml` — the production backup cron.
- `.github/workflows/ci.yml` — `Docker Build & Smoke` job replicates
  this exact local stack on every push.
