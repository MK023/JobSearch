# Contributing

Grazie per il tuo interesse nel contribuire a Job Search Command Center!

## Setup locale

```bash
git clone https://github.com/MK023/JobSearch.git
cd JobSearch
cp .env.example .env
# Configura: ANTHROPIC_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d
```

## Workflow

1. Crea un branch dal `main`: `git checkout -b feat/nome-feature`
2. Scrivi codice + test
3. Verifica che la CI passi localmente:
   ```bash
   cd backend
   ruff check .
   ruff format --check .
   mypy src --strict
   pytest tests/ -x -q
   ```
4. Apri una PR verso `main`

## Convenzioni

- **Commit**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- **Python**: ruff (format + lint), mypy strict, bandit
- **CSS**: stylelint
- **Test**: pytest, ogni feature deve avere test

## Struttura branch

- `feat/` — nuove funzionalita
- `fix/` — bug fix
- `cleanup/` — refactoring, pulizia
- `security/` — hardening sicurezza

## Segnalazioni sicurezza

Non aprire issue pubbliche. Vedi [SECURITY.md](SECURITY.md).
