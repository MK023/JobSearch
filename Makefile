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

# ── Deploy ──────────────────────────────────────────────────────────

.PHONY: deploy deploy-status

deploy: ## Deploy su Fly.io
	fly deploy

deploy-status: ## Stato del deploy su Fly.io
	fly status

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
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
