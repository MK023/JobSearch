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

## Branch Naming

- `feat/` — new features
- `fix/` — bug fixes
- `cleanup/` — refactoring, cleanup
- `security/` — security hardening

## Security Reports

Do not open public issues. See [SECURITY.md](SECURITY.md).
