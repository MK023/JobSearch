# Job Search Command Center — Makefile
# Comandi rapidi per sviluppo, test e deploy

.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Docker ──────────────────────────────────────────────────────────

.PHONY: up down build rebuild logs logs-backend logs-db ps clean

up: ## Avvia tutti i container
	docker compose up -d

down: ## Ferma tutti i container
	docker compose down

build: ## Build delle immagini
	docker compose build

rebuild: ## Rebuild e riavvia (forza ricostruzione)
	docker compose up -d --build

logs: ## Log live di tutti i container
	docker compose logs -f

logs-backend: ## Log live solo del backend
	docker compose logs -f backend

logs-db: ## Log live solo del database
	docker compose logs -f db

ps: ## Stato dei container
	docker compose ps

clean: ## Ferma tutto e rimuovi volumi (ATTENZIONE: cancella i dati)
	@echo "⚠️  Questo cancellera' tutti i dati del database!"
	@read -p "Confermi? [y/N] " confirm && [ "$$confirm" = "y" ] && docker compose down -v || echo "Annullato."

# ── Database ────────────────────────────────────────────────────────

.PHONY: db migrate

db: ## Shell PostgreSQL
	docker compose exec db psql -U $${POSTGRES_USER:-jobsearch} -d $${POSTGRES_DB:-jobsearch}

migrate: ## Esegui migrazioni Alembic
	docker compose exec backend alembic upgrade head

# ── Test ────────────────────────────────────────────────────────────

.PHONY: test test-cov test-routes

test: ## Esegui tutti i test
	cd backend && python -m pytest tests/ -v --tb=short

test-cov: ## Test con coverage report
	cd backend && python -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing --cov-fail-under=50

test-routes: ## Test solo delle route HTTP
	cd backend && python -m pytest tests/test_routes.py -v

# ── Lint & Format ───────────────────────────────────────────────────

.PHONY: lint lint-py lint-css format check

lint: lint-py lint-css ## Esegui tutti i linter

lint-py: ## Lint Python (ruff)
	ruff check backend/src/ backend/tests/
	ruff format --check backend/src/ backend/tests/

lint-css: ## Lint CSS (stylelint)
	npx stylelint "frontend/static/css/**/*.css" --formatter compact

format: ## Auto-format Python (ruff)
	ruff format backend/src/ backend/tests/
	ruff check --fix backend/src/ backend/tests/

check: lint test ## Lint + test (simula CI in locale)

# ── Shadow-prod replica (Docker locale 1:1) ─────────────────────────
# Pattern: lavorare offline o in disaster-recovery con un DB locale
# popolato dall'ultimo pg_dump in R2 (o da un archivio su disco).
# Vedi scripts/dev_restore.py per i dettagli.

.PHONY: dev-bootstrap dev-restore-from-r2 dev-restore-from-file

dev-bootstrap: ## Up + alembic upgrade head: stack pronto, DB schema aggiornato (vuoto)
	docker compose up -d
	@echo "Waiting for DB to be healthy..."
	@for i in $$(seq 1 18); do \
		st=$$(docker inspect --format='{{.State.Health.Status}}' "$$(docker compose ps -q db)" 2>/dev/null || echo "starting"); \
		[ "$$st" = "healthy" ] && break; \
		sleep 5; \
	done
	docker compose exec -T backend alembic upgrade head
	@echo "Bootstrap complete. Run 'make dev-restore-from-r2' to populate with prod data."

dev-restore-from-r2: ## Scarica l'ultimo pg_dump da R2 e ripristina nel DB locale
	python3 scripts/dev_restore.py --from-r2 --yes

dev-restore-from-file: ## Ripristina un archivio .sql.gz locale (FILE=path obbligatorio)
	@if [ -z "$(FILE)" ]; then echo "Usage: make dev-restore-from-file FILE=<path>.sql.gz"; exit 1; fi
	python3 scripts/dev_restore.py --from-file $(FILE) --yes

# ── Render (deploy + observability) ─────────────────────────────────
# Render fa auto-deploy su push to main — niente `deploy` manuale.
# Questi target servono per logs e status su free tier (8GB RAM Mac:
# meglio CLI che dashboard browser).

.PHONY: render-logs render-status

RENDER_SVC := srv-d7bp6o6a2pns73eouueg

render-logs: ## Tail degli ultimi 50 log su Render
	render logs -r $(RENDER_SVC) --limit 50 -o text

render-status: ## Stato del service Render (e ultimo deploy)
	render services -o json --confirm | python3 -c "import json,sys; svcs=[s for s in json.load(sys.stdin) if s.get('id')=='$(RENDER_SVC)']; import pprint; pprint.pprint(svcs[0] if svcs else 'service not found')"

# ── Pre-commit ──────────────────────────────────────────────────────

.PHONY: hooks hooks-run

hooks: ## Installa pre-commit hooks
	pip install pre-commit
	pre-commit install

hooks-run: ## Esegui pre-commit su tutti i file
	pre-commit run --all-files

# ── Help ────────────────────────────────────────────────────────────

.PHONY: help

help: ## Mostra questo help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
