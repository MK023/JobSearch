# Final Refactor & Polish - Design Document

## Goal
Refactor, clean up, and polish the Job Search Command Center for daily production use. No new major features — focus on code quality, performance, UX, and maintainability.

## Scope

### 1. File Reorganization (Frontend/Backend Split)
Extract inline CSS and JS from `index.html` (601 lines) into dedicated static files. Split monolithic template into partials via Jinja2 `{% include %}`.

**New structure:**
```
backend/
  static/
    css/style.css
    js/app.js
  templates/
    base.html
    partials/
      cv_form.html
      analysis_form.html
      result_card.html
      cover_letter.html
      batch.html
      history.html
  src/ (unchanged)
```

FastAPI serves static files via `app.mount("/static", StaticFiles(...))`. No new dependencies.

### 2. Cache Anti-Duplicates
- Full hash of CV + job description (not truncated at 500 chars)
- DB-level duplicate check: before calling API, query `JobAnalysis` for matching content hash
- UI warning when duplicate detected: "Analisi gia eseguita il DD/MM — rivedi o rifai?"

### 3. Delete Analysis
- `DELETE /analysis/{id}` endpoint with cascade delete on associated cover letters
- Delete button in result card and history list
- JS confirmation dialog before delete

### 4. Glassdoor UI Improvement
- Larger, more visible rating badge (star visualization or color bar)
- Pro/Cons in 2-column layout
- Warning icon when rating is "non disponibile"

### 5. Code Cleanup
- Remove unused `import os` from config.py
- API key validation at startup (fail-fast)
- Migrate `@app.on_event("startup")` to FastAPI `lifespan` context manager
- Review and remove any dead code patterns

### 6. Lint + PEP Compliance
- Add `pyproject.toml` with ruff configuration
- Auto-fix all warnings
- Ensure PEP 8 compliance across all modules

## Non-Goals
- No SPA/React/Vue migration
- No Doppler integration (keep .env + Docker)
- No new roadmap features (PDF upload, auth, statistics, etc.)
- No new Python dependencies (except ruff as dev tool)

## Approach
- Keep .env + Docker Compose as-is
- Single-user, server-side Jinja2
- All changes backward-compatible with existing DB data
