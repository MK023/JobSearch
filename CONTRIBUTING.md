# Contributing

Thanks for your interest in contributing to Job Search Command Center!

## Local Setup

```bash
git clone https://github.com/MK023/JobSearch.git
cd JobSearch
cp .env.example .env
# Configure: ANTHROPIC_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d
```

## Workflow

1. Create a branch from `main`: `git checkout -b feat/feature-name`
2. Write code + tests
3. Make sure CI passes locally:
   ```bash
   cd backend
   ruff check .
   ruff format --check .
   mypy src --strict
   pytest tests/ -x -q
   ```
4. Open a PR against `main`

## Conventions

- **Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- **Python**: ruff (format + lint), mypy strict, bandit
- **CSS**: stylelint
- **Tests**: pytest — every feature must include tests

## Backend Module Layout

Each backend module follows the **models → service → routes** pattern. Notable modules:

- `backend/src/analysis/` — core AI analysis (includes `career_track` classification)
- `backend/src/analytics/` — **pure** data-science primitives (stats, discriminants, bias). No external deps — stdlib only. Deterministic + easily unit-testable.
- `backend/src/analytics_page/` — `/analytics` route + service + models. Orchestrates the learning loop (persists `analytics_runs` snapshots, updates `user_profiles`).
- See `docs/technical.md` section 16 for the full learning-loop architecture.

Offline-analysis CLI scripts live in `scripts/` (`export_db.py`, `analyze_db.py`).

## Alembic Migrations

- Location: `backend/alembic/versions/`
- Naming: `NNN_short_description.py` — 3-digit zero-padded sequential prefix, snake_case description (e.g. `019_add_analytics_runs_user_profile.py`)
- Always register new models in `backend/alembic/env.py` so autogenerate sees them
- Generate: `cd backend && alembic revision --autogenerate -m "descrizione"` — then review & rename the output file to match the convention
- Apply locally: `alembic upgrade head` (runs automatically on Render deploy)

## Branch Naming

- `feat/` — new features
- `fix/` — bug fixes
- `cleanup/` — refactoring, cleanup
- `security/` — security hardening

## Security Reports

Do not open public issues. See [SECURITY.md](SECURITY.md).
