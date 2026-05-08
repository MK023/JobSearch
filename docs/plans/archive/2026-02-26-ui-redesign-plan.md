# UI Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the JobSearch frontend from a single-page layout to a sidebar-navigated, Apple-inspired dark theme multi-page app — backend logic unchanged.

**Architecture:** Flask/Jinja2 multi-page with sidebar navigation. Each sidebar item is a separate Flask route rendering a dedicated template that extends `base.html`. Alpine.js handles local interactivity (tabs, modals, forms). CSS custom properties drive the entire design token system. No new JS frameworks.

**Tech Stack:** FastAPI, Jinja2, Alpine.js 3.14.8, Flatpickr 4.6.13, vanilla JS modules, pure CSS custom properties.

**Design doc:** `docs/plans/2026-02-26-ui-redesign-design.md`

**Branch:** `redesign` (rewrite in-place)

---

## Phase 1: Foundation

### Task 1: Create branch and verify baseline

**Files:**
- None (git only)

**Step 1: Create redesign branch**

```bash
git checkout -b redesign
```

**Step 2: Run existing tests to establish baseline**

```bash
cd /Users/marcobellingeri/Documents/GitHub/JobSearch
python -m pytest backend/tests/ -v
```

Expected: All tests PASS. Note the count — this is the baseline.

**Step 3: Start the app and verify it loads**

```bash
cd /Users/marcobellingeri/Documents/GitHub/JobSearch
python -m uvicorn backend.src.main:app --reload
```

Open `http://localhost:8000` — verify the current UI loads without errors. Stop the server.

**Step 4: Commit branch creation**

```bash
git commit --allow-empty -m "chore: start redesign branch"
```

---

### Task 2: Rewrite CSS design tokens (variables.css)

**Files:**
- Modify: `frontend/static/css/variables.css`

**Step 1: Read the current variables.css**

Read `frontend/static/css/variables.css` fully to understand existing token names and usage.

**Step 2: Rewrite variables.css with Apple dark palette**

Replace the entire file with new tokens. The new palette follows the design doc (Section 4):

```css
/* === JobSearch Design Tokens — Apple-inspired Dark === */

:root {
  /* Backgrounds */
  --bg-primary: #0D0D0F;
  --bg-secondary: #1C1C1E;
  --bg-tertiary: #2C2C2E;
  --bg-glass: rgba(28, 28, 30, 0.85);

  /* Accent colors */
  --accent-blue: #0A84FF;
  --accent-green: #30D158;
  --accent-orange: #FF9F0A;
  --accent-red: #FF453A;
  --accent-lime: #30D158;

  /* Text */
  --text-primary: #F5F5F7;
  --text-secondary: #8E8E93;
  --text-tertiary: #48484A;

  /* Borders */
  --border-subtle: rgba(255, 255, 255, 0.06);
  --border-medium: rgba(255, 255, 255, 0.10);

  /* Typography — SF Pro stack */
  --font-family: 'SF Pro Display', 'SF Pro Text', -apple-system, 'Helvetica Neue', sans-serif;
  --text-xs: 11px;
  --text-sm: 13px;
  --text-base: 15px;
  --text-lg: 17px;
  --text-xl: 22px;
  --text-2xl: 28px;

  /* Font weights */
  --weight-normal: 400;
  --weight-medium: 500;
  --weight-semibold: 600;
  --weight-bold: 700;

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
  --space-xl: 24px;
  --space-2xl: 32px;
  --space-3xl: 48px;

  /* Radii */
  --radius-sm: 8px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-full: 9999px;

  /* Shadows */
  --shadow-card: 0 2px 12px rgba(0, 0, 0, 0.3);
  --shadow-hover: 0 8px 24px rgba(0, 0, 0, 0.4);
  --shadow-focus: 0 0 0 3px rgba(10, 132, 255, 0.15);

  /* Transitions */
  --transition-fast: 0.15s ease;
  --transition-normal: 0.2s ease;
  --transition-slow: 0.3s ease;

  /* Sidebar */
  --sidebar-width: 60px;
  --sidebar-active: var(--accent-blue);

  /* Content */
  --content-max-width: 960px;
  --content-padding: 32px;

  /* Score colors (set dynamically via JS or Jinja) */
  --score-green: var(--accent-green);
  --score-orange: var(--accent-orange);
  --score-red: var(--accent-red);

  /* Status colors */
  --status-da-valutare: var(--accent-orange);
  --status-candidato: var(--accent-blue);
  --status-colloquio: var(--accent-green);
  --status-scartato: var(--accent-red);
}

/* Respect system preference, but default is dark */
@media (prefers-color-scheme: light) {
  :root {
    /* Light mode overrides — future, keep dark for now */
  }
}
```

**Step 3: Grep for old variable names still referenced**

Search all CSS files and templates for old variable names (e.g. `--clr-`, `--fs-`, `--gap-`, etc.) from the previous `variables.css`. Keep a list of mappings needed for later tasks.

```bash
cd /Users/marcobellingeri/Documents/GitHub/JobSearch
grep -rn "var(--" frontend/static/css/ --include="*.css" | grep -v "variables.css" | head -50
```

Do NOT update references yet — the other CSS files will be fully rewritten in later tasks.

**Step 4: Commit**

```bash
git add frontend/static/css/variables.css
git commit -m "style: rewrite CSS tokens with Apple dark palette"
```

---

### Task 3: Rewrite base.css (reset + typography + fade)

**Files:**
- Modify: `frontend/static/css/base.css`

**Step 1: Read current base.css**

Read `frontend/static/css/base.css` fully.

**Step 2: Rewrite base.css**

Replace entirely. Key elements:
- CSS reset (box-sizing, margin reset)
- Body: `--bg-primary` background, `--font-family`, `--text-base` size, `--text-primary` color
- Page fade animation: `@keyframes fadeIn` 150ms on body
- Scrollbar styling for dark theme (webkit + firefox)
- Accessibility: `.sr-only`, `.skip-link`, focus-visible ring
- Form element base styles: inputs/textarea/select inherit font, use `--bg-tertiary`, `--border-subtle`, `--radius-md`
- Focus state: `--accent-blue` border + `--shadow-focus`
- Loading spinner keyframe (keep existing)
- Shimmer keyframe:
  ```css
  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }
  .loading-shimmer {
    background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-secondary) 50%, var(--bg-tertiary) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: var(--radius-md);
  }
  ```
- `::selection` with accent-blue background

**Step 3: Commit**

```bash
git add frontend/static/css/base.css
git commit -m "style: rewrite base.css with reset, typography, fade animation"
```

---

### Task 4: Create sidebar partial with SVG icons

**Files:**
- Create: `frontend/templates/partials/sidebar.html`

**Step 1: Create the sidebar partial**

The sidebar contains 5 navigation items. Each icon is an inline SVG (~20x20 viewBox). Settings is anchored to the bottom.

```html
{# Sidebar navigation — included in base.html #}
<nav class="sidebar" aria-label="Navigazione principale">
  <div class="sidebar-top">
    {# Dashboard #}
    <a href="/" class="sidebar-item {% if active_page == 'dashboard' %}active{% endif %}"
       aria-label="Dashboard" data-tooltip="Dashboard">
      <svg><!-- home icon SVG path --></svg>
    </a>

    {# Nuova analisi #}
    <a href="/analyze" class="sidebar-item {% if active_page == 'analyze' %}active{% endif %}"
       aria-label="Nuova analisi" data-tooltip="Nuova analisi">
      <svg><!-- plus-circle icon SVG path --></svg>
    </a>

    {# Storico #}
    <a href="/history" class="sidebar-item {% if active_page == 'history' %}active{% endif %}"
       aria-label="Storico candidature" data-tooltip="Storico">
      <svg><!-- list icon SVG path --></svg>
    </a>

    {# Colloqui #}
    <a href="/interviews" class="sidebar-item {% if active_page == 'interviews' %}active{% endif %}"
       aria-label="Colloqui" data-tooltip="Colloqui">
      <svg><!-- calendar icon SVG path --></svg>
    </a>
  </div>

  <div class="sidebar-bottom">
    {# Impostazioni #}
    <a href="/settings" class="sidebar-item {% if active_page == 'settings' %}active{% endif %}"
       aria-label="Impostazioni" data-tooltip="Impostazioni">
      <svg><!-- gear icon SVG path --></svg>
    </a>
  </div>
</nav>
```

Each SVG should be a simple 20x20 outline icon:
- **Home**: house outline (dashboard)
- **Plus-circle**: circle with plus (nuova analisi)
- **List**: stacked horizontal lines (storico)
- **Calendar**: calendar with date mark (colloqui)
- **Gear**: cogwheel (impostazioni)

Use `currentColor` for stroke so the active state can change color via CSS.

**Step 2: Commit**

```bash
git add frontend/templates/partials/sidebar.html
git commit -m "feat: add sidebar partial with SVG navigation icons"
```

---

### Task 5: Rewrite base.html with sidebar layout

**Files:**
- Modify: `frontend/templates/base.html`

**Step 1: Read current base.html**

Read `frontend/templates/base.html` fully to understand existing blocks, CSS/JS includes, and Alpine setup.

**Step 2: Rewrite base.html**

The new base.html structure:

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Job Search Command Center{% endblock %}</title>

  {# CSS #}
  <link rel="stylesheet" href="{{ url_for('static', path='css/variables.css') }}?v=10">
  <link rel="stylesheet" href="{{ url_for('static', path='css/base.css') }}?v=10">
  <link rel="stylesheet" href="{{ url_for('static', path='css/layout.css') }}?v=10">
  <link rel="stylesheet" href="{{ url_for('static', path='css/components.css') }}?v=10">
  <link rel="stylesheet" href="{{ url_for('static', path='css/sections.css') }}?v=10">
  {% block head_extra %}{% endblock %}
</head>
<body x-data="app()" x-init="init()">
  <a href="#main-content" class="skip-link">Vai al contenuto</a>

  {# Sidebar #}
  {% include "partials/sidebar.html" %}

  {# Main content area #}
  <main id="main-content" class="content-area">
    {% block content %}{% endblock %}
  </main>

  {# Toast container #}
  <div id="toast-container" class="toast-container" aria-live="polite"></div>

  {# JS #}
  <script src="{{ url_for('static', path='js/app.js') }}?v=10"></script>
  {% block scripts_extra %}{% endblock %}
</body>
</html>
```

Key changes from current base.html:
- Remove header partial include (no more top spending bar)
- Add sidebar include
- Add `.content-area` wrapper around block content
- Add toast container div
- Add `{% block head_extra %}` for page-specific CSS (flatpickr)
- Add `{% block scripts_extra %}` for page-specific JS modules
- Keep Alpine.js CDN script
- Bump cache version `?v=10` on all assets

**Step 3: Verify no syntax errors**

```bash
cd /Users/marcobellingeri/Documents/GitHub/JobSearch
python -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('frontend/templates')); env.get_template('base.html')"
```

Expected: No error (template parses).

**Step 4: Commit**

```bash
git add frontend/templates/base.html
git commit -m "feat: rewrite base.html with sidebar layout and content area"
```

---

### Task 6: Rewrite layout.css (sidebar + content + grid)

**Files:**
- Modify: `frontend/static/css/layout.css`

**Step 1: Read current layout.css**

Read `frontend/static/css/layout.css` fully.

**Step 2: Rewrite layout.css**

Replace entirely. Key sections:

```css
/* === Sidebar === */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: var(--space-lg) 0;
  z-index: 100;
}

.sidebar-top,
.sidebar-bottom {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
}

.sidebar-item {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  position: relative;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.sidebar-item:hover {
  color: var(--text-primary);
  background: var(--bg-tertiary);
}

.sidebar-item.active {
  color: var(--sidebar-active);
}

.sidebar-item.active::before {
  content: '';
  position: absolute;
  left: -10px; /* flush with sidebar left edge (accounting for padding) */
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: var(--sidebar-active);
  border-radius: var(--radius-full);
}

/* Tooltip on hover */
.sidebar-item[data-tooltip]:hover::after {
  content: attr(data-tooltip);
  position: absolute;
  left: calc(100% + 8px);
  top: 50%;
  transform: translateY(-50%);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  white-space: nowrap;
  z-index: 200;
  pointer-events: none;
}

.sidebar-item svg {
  width: 20px;
  height: 20px;
  stroke: currentColor;
  stroke-width: 1.5;
  fill: none;
}

/* === Content area === */
.content-area {
  margin-left: var(--sidebar-width);
  padding: var(--content-padding);
  min-height: 100vh;
}

.content-inner {
  max-width: var(--content-max-width);
  margin: 0 auto;
}

/* === Page header === */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-xl);
  max-height: 48px;
}

.page-title {
  font-size: var(--text-xl);
  font-weight: var(--weight-bold);
  color: var(--text-primary);
}

/* === Grid helpers === */
.grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-xl);
}

.grid-3col {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-lg);
}

/* === Mobile: sidebar → bottom bar === */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: auto;
    bottom: 0;
    left: 0;
    width: 100%;
    height: 56px;
    flex-direction: row;
    justify-content: space-around;
    align-items: center;
    padding: 0;
    border-right: none;
    border-top: 1px solid var(--border-subtle);
  }

  .sidebar-top,
  .sidebar-bottom {
    flex-direction: row;
    gap: 0;
  }

  .sidebar-item.active::before {
    left: 50%;
    top: auto;
    bottom: -2px;
    transform: translateX(-50%);
    width: 20px;
    height: 3px;
  }

  .sidebar-item[data-tooltip]:hover::after {
    display: none; /* no tooltips on mobile */
  }

  .content-area {
    margin-left: 0;
    margin-bottom: 56px; /* space for bottom bar */
    padding: var(--space-lg);
  }

  .grid-2col,
  .grid-3col {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .content-area {
    padding: var(--space-md);
  }
}
```

**Step 3: Commit**

```bash
git add frontend/static/css/layout.css
git commit -m "style: rewrite layout.css with sidebar and responsive bottom bar"
```

---

## Phase 2: Backend Routes

### Task 7: Add new GET routes

**Files:**
- Modify: `backend/src/main.py` (register new routes)
- Modify: `backend/src/analysis/routes.py` (refactor `_render_page` into page-specific renderers)
- Create: `backend/src/pages.py` (new page route handlers)

**Step 1: Read current route files**

Read these files fully:
- `backend/src/main.py`
- `backend/src/analysis/routes.py`

**Step 2: Create pages.py with new GET route handlers**

Create `backend/src/pages.py` with route handlers for the new pages. Each handler fetches only the context needed for that page:

```python
"""Page routes for the redesigned multi-page frontend."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .auth.dependencies import get_current_user
from .database import get_db
from .models import User

router = APIRouter()


def _get_templates(request: Request):
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dashboard: metrics + recent analyses + alerts."""
    from .analysis.service import get_recent_analyses
    from .dashboard.service import get_dashboard_metrics, get_spending_totals
    from .interview.service import get_upcoming_interviews

    templates = _get_templates(request)
    analyses = get_recent_analyses(db, user.id)
    spending = get_spending_totals(db, user.id)
    dashboard_data = get_dashboard_metrics(db, user.id)
    upcoming = get_upcoming_interviews(db, user.id)

    # Follow-up alerts: candidatures older than 7 days without follow-up
    from .analysis.service import get_followup_alerts
    followup_alerts = get_followup_alerts(db, user.id)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "active_page": "dashboard",
        "spending": spending,
        "dashboard": dashboard_data,
        "recent_analyses": analyses[:5],
        "analyses": analyses,
        "followup_alerts": followup_alerts,
        "upcoming_interviews": upcoming,
    })


@router.get("/analyze", response_class=HTMLResponse)
def analyze_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """New analysis page: single + batch tabs."""
    from .cv.service import get_latest_cv
    from .dashboard.service import get_spending_totals

    templates = _get_templates(request)
    cv = get_latest_cv(db, user.id)
    spending = get_spending_totals(db, user.id)

    return templates.TemplateResponse("analyze.html", {
        "request": request,
        "user": user,
        "active_page": "analyze",
        "cv": cv,
        "spending": spending,
    })


@router.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full history with status tabs."""
    from .analysis.service import get_recent_analyses

    templates = _get_templates(request)
    analyses = get_recent_analyses(db, user.id)

    # Count per status
    counts = {"da_valutare": 0, "candidato": 0, "colloquio": 0, "scartato": 0}
    for a in analyses:
        status = a.status.value if hasattr(a.status, "value") else a.status
        if status in counts:
            counts[status] += 1

    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "active_page": "history",
        "analyses": analyses,
        "counts": counts,
    })


@router.get("/interviews", response_class=HTMLResponse)
def interviews_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Interviews: upcoming with prep + past collapsed."""
    from .interview.service import get_all_interviews

    templates = _get_templates(request)
    upcoming, past = get_all_interviews(db, user.id)

    return templates.TemplateResponse("interviews.html", {
        "request": request,
        "user": user,
        "active_page": "interviews",
        "upcoming_interviews": upcoming,
        "past_interviews": past,
    })


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Settings: CV + API credits."""
    from .cv.service import get_latest_cv
    from .dashboard.service import get_spending_totals

    templates = _get_templates(request)
    cv = get_latest_cv(db, user.id)
    spending = get_spending_totals(db, user.id)

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": user,
        "active_page": "settings",
        "cv": cv,
        "spending": spending,
    })
```

**Important notes for implementer:**
- The exact service function names (`get_recent_analyses`, `get_dashboard_metrics`, etc.) must be verified by reading the actual service modules. The current `_render_page()` in `analysis/routes.py` calls these — trace them.
- `get_all_interviews()` may not exist yet. If only `get_upcoming_interviews()` exists, create a wrapper or query that also returns past interviews.
- Each route passes `active_page` — used by `sidebar.html` to highlight the current item.

**Step 3: Register routes in main.py**

Add to `main.py`:
```python
from .pages import router as pages_router
app.include_router(pages_router)
```

Make sure the pages router is included BEFORE the analysis router, since both define `GET /`. The pages router's `GET /` replaces the old `home()` function — remove or comment out the old `home()` route.

**Step 4: Update POST /analyze to redirect**

In `backend/src/analysis/routes.py`, change the success path of `POST /analyze`:

```python
# OLD: return _render_page(request, db, user, current=analysis, result=result)
# NEW:
from fastapi.responses import RedirectResponse
return RedirectResponse(url=f"/analysis/{analysis.id}", status_code=303)
```

For error paths, redirect back to `/analyze` with error in session flash:
```python
# OLD: return _render_page(request, db, user, error="message")
# NEW:
request.session["flash_error"] = "message"
return RedirectResponse(url="/analyze", status_code=303)
```

Update `analyze_page()` in `pages.py` to read flash messages from session:
```python
error = request.session.pop("flash_error", None)
message = request.session.pop("flash_message", None)
```

Do the same for `POST /cover-letter` — redirect to `/analysis/{id}` after success.

Do the same for `POST /cv` — redirect to `/settings` instead of `/`.

**Step 5: Update GET /analysis/{id}**

In `analysis/routes.py`, update `view_analysis()` to render `analysis_detail.html` instead of calling `_render_page()`:

```python
@router.get("/analysis/{analysis_id}", response_class=HTMLResponse)
def view_analysis(request, analysis_id, db, user):
    analysis = get_analysis_by_id(db, analysis_id, user.id)
    if not analysis:
        return RedirectResponse(url="/history", status_code=303)

    result = rebuild_result(analysis)
    # Fetch related data
    interview = get_interview_for_analysis(db, analysis_id)
    cover_letter = get_cover_letter_for_analysis(db, analysis_id)
    contacts = get_contacts_for_analysis(db, analysis_id)

    return templates.TemplateResponse("analysis_detail.html", {
        "request": request,
        "user": user,
        "active_page": "history",  # highlight storico in sidebar
        "current": analysis,
        "result": result,
        "interview": interview,
        "cover_letter": cover_letter,
        "contacts": contacts,
    })
```

**Step 6: Write route tests**

Add to `backend/tests/test_routes.py`:

```python
def test_dashboard_requires_auth(app_client):
    resp = app_client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]

def test_analyze_page_requires_auth(app_client):
    resp = app_client.get("/analyze", follow_redirects=False)
    assert resp.status_code == 303

def test_history_page_requires_auth(app_client):
    resp = app_client.get("/history", follow_redirects=False)
    assert resp.status_code == 303

def test_interviews_page_requires_auth(app_client):
    resp = app_client.get("/interviews", follow_redirects=False)
    assert resp.status_code == 303

def test_settings_page_requires_auth(app_client):
    resp = app_client.get("/settings", follow_redirects=False)
    assert resp.status_code == 303
```

**Step 7: Run tests**

```bash
python -m pytest backend/tests/test_routes.py -v
```

Expected: New tests PASS (unauthenticated requests redirect to /login).

**Step 8: Commit**

```bash
git add backend/src/pages.py backend/src/main.py backend/src/analysis/routes.py backend/src/cv/routes.py backend/src/cover_letter/routes.py backend/tests/test_routes.py
git commit -m "feat: add multi-page routes and redirect POST handlers"
```

---

## Phase 3: Reusable Components

### Task 8: Create Score Ring partial

**Files:**
- Create: `frontend/templates/partials/score_ring.html`

**Step 1: Create the Score Ring Jinja partial**

This partial accepts `score` and `size` variables:

```html
{#
  Score Ring component.
  Usage: {% with score=75, size="lg" %}{% include "partials/score_ring.html" %}{% endwith %}
  Sizes: "lg" (96px, for detail page) or "sm" (48px, for list cards)
#}
{% set ring_size = 96 if size == "lg" else 48 %}
{% set viewbox = 72 %}
{% set cx = 36 %}
{% set r = 30 %}
{% set circumference = 188.5 %}
{% set offset = circumference - (circumference * (score | float / 100)) %}
{% set score_color = "var(--score-green)" if score >= 75 else ("var(--score-orange)" if score >= 50 else "var(--score-red)") %}

<div class="score-ring-wrapper score-ring-{{ size | default('sm') }}">
  <svg viewBox="0 0 {{ viewbox }} {{ viewbox }}"
       width="{{ ring_size }}" height="{{ ring_size }}"
       class="score-ring"
       role="img"
       aria-label="Score: {{ score }}">
    {# Track #}
    <circle cx="{{ cx }}" cy="{{ cx }}" r="{{ r }}"
            stroke="var(--bg-tertiary)" stroke-width="5" fill="none"/>
    {# Progress #}
    <circle cx="{{ cx }}" cy="{{ cx }}" r="{{ r }}"
            stroke="{{ score_color }}" stroke-width="5" fill="none"
            stroke-dasharray="{{ circumference }}"
            stroke-dashoffset="{{ offset }}"
            stroke-linecap="round"
            transform="rotate(-90 {{ cx }} {{ cx }})"
            class="score-ring-progress"/>
    {# Number #}
    <text x="{{ cx }}" y="{{ cx + 5 }}"
          text-anchor="middle"
          class="score-ring-text"
          fill="var(--text-primary)">{{ score | int }}</text>
  </svg>
</div>
```

**Step 2: Commit**

```bash
git add frontend/templates/partials/score_ring.html
git commit -m "feat: add Score Ring SVG partial component"
```

---

### Task 9: Create Job Card partial

**Files:**
- Create: `frontend/templates/partials/job_card.html`

**Step 1: Create the Job Card partial**

Accepts an `analysis` object. Used in dashboard preview and history list.

```html
{#
  Job Card component — compact row for lists.
  Usage: {% with analysis=item %}{% include "partials/job_card.html" %}{% endwith %}
  Expects: analysis object with .id, .score, .role, .company, .work_mode, .status, .created_at
#}
{% set result = analysis.result_data if analysis.result_data else {} %}
{% set score = result.get('score', analysis.score | default(0)) %}
{% set role = result.get('role', analysis.role | default('—')) %}
{% set company = result.get('company', analysis.company | default('—')) %}

<a href="/analysis/{{ analysis.id }}" class="job-card">
  <div class="job-card-score">
    {% with size="sm" %}
      {% include "partials/score_ring.html" %}
    {% endwith %}
  </div>

  <div class="job-card-info">
    <span class="job-card-role">{{ role }}</span>
    <span class="job-card-meta">
      {{ company }}
      {% if result.get('work_mode') %} · {{ result.get('work_mode') }}{% endif %}
    </span>
  </div>

  <div class="job-card-end">
    <span class="job-card-date">
      {{ analysis.created_at.strftime('%d %b · %H:%M') if analysis.created_at else '' }}
    </span>
    {% set status_val = analysis.status.value if analysis.status.value is defined else analysis.status %}
    <span class="status-badge status-{{ status_val }}">
      {{ status_val | replace('_', ' ') | upper }}
    </span>
  </div>
</a>
```

**Note for implementer:** The exact attribute names on the `analysis` object (`.score`, `.role`, `.company`, `.result_data`, etc.) must be verified by reading the model definition. The current templates in `history.html` and `result.html` show the actual attribute access pattern — trace those.

**Step 2: Commit**

```bash
git add frontend/templates/partials/job_card.html
git commit -m "feat: add Job Card partial component"
```

---

### Task 10: Create Metric Card partial

**Files:**
- Create: `frontend/templates/partials/metric_card.html`

**Step 1: Create the Metric Card partial**

```html
{#
  Metric Card component — big number + label.
  Usage: {% with value=29, label="Analizzate" %}{% include "partials/metric_card.html" %}{% endwith %}
#}
<div class="metric-card">
  <span class="metric-value">{{ value }}</span>
  <span class="metric-label">{{ label }}</span>
</div>
```

**Step 2: Commit**

```bash
git add frontend/templates/partials/metric_card.html
git commit -m "feat: add Metric Card partial component"
```

---

### Task 11: Rewrite components.css

**Files:**
- Modify: `frontend/static/css/components.css`

**Step 1: Read current components.css**

Read `frontend/static/css/components.css` fully. Note all component classes used across templates.

**Step 2: Rewrite components.css**

Replace entirely. Must include these components with the new design tokens:

- **`.card`**: `--bg-secondary`, `--radius-lg`, `--border-subtle`, `--shadow-card`
- **`.btn`**: base reset. Variants: `.btn-primary` (accent-blue, hover brightness, active scale), `.btn-ghost` (transparent, border-medium), `.btn-danger` (accent-red), `.btn-sm` (smaller padding)
- **`.pill`**: `--radius-full`, small padding, colored variants per status
- **`.status-badge`**: pill with status-specific background (tinted, low opacity)
- **`.tabs`**: flex row, `.tab` items with bottom border indicator, badge count
- **`.toggle`**: inline radio group styled as segmented control (Singola/Multipla, Haiku/Sonnet)
- **`.score-ring-wrapper`**: sizing for lg/sm. `.score-ring-text`: font-size, weight. `.score-ring-progress`: transition for stroke-dashoffset 0.6s cubic-bezier(0.4, 0, 0.2, 1)
- **`.job-card`**: flex row, text-decoration none, padding, border-bottom subtle. Hover: translateY(-1px) + shadow-hover. Transition on transform + box-shadow.
- **`.metric-card`**: bg-secondary, radius-lg, padding. `.metric-value`: text-2xl bold. `.metric-label`: text-sm text-secondary.
- **`.modal-overlay`**: fixed inset-0, rgba(0,0,0,0.5), backdrop-filter blur(8px), z-index 1000
- **`.modal-content`**: bg-secondary, radius-xl (20px), border-medium, max-width 560px, animation modalEnter 200ms
- **`.toast-container`**: fixed bottom-right, z-index 1100, flex column, gap. `.toast`: bg-tertiary, radius-md, padding, slideUp animation. Variants: `.toast-success`, `.toast-error`, `.toast-info`.
- **`.message-banner`**: full-width, padding, radius-md. `.banner-success` (green tint), `.banner-error` (red tint).
- **`.input`**, **`.textarea`**: bg-tertiary, border-subtle, radius-md. Focus: accent-blue border + shadow-focus.
- **`.recommendation-badge`**: APPLY (green), CONSIDER (orange), SKIP (red)
- **`.severity-badge`**: for gap severity indicators
- **`.tag`**: small inline pill for metadata (location, work mode, salary)

Preserve ALL class names that are referenced in JS files (check with grep). If renaming, update JS too.

**Step 3: Commit**

```bash
git add frontend/static/css/components.css
git commit -m "style: rewrite components.css with Apple dark theme"
```

---

### Task 12: Add toast notification component (JS + CSS)

**Files:**
- Create: `frontend/static/js/modules/toast.js`
- Toast CSS is already part of components.css (Task 11)

**Step 1: Create toast.js**

```javascript
/**
 * Toast notification system.
 * Usage: showToast("Stato aggiornato", "success")
 * Types: "success", "error", "info"
 */
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  // Auto-dismiss after 3s
  setTimeout(() => {
    toast.classList.add("toast-exit");
    toast.addEventListener("animationend", () => toast.remove());
  }, 3000);
}
```

**Step 2: Include toast.js in base.html**

Add before `app.js`:
```html
<script src="{{ url_for('static', path='js/modules/toast.js') }}?v=10"></script>
```

**Step 3: Commit**

```bash
git add frontend/static/js/modules/toast.js frontend/templates/base.html
git commit -m "feat: add toast notification component"
```

---

## Phase 4: Page Templates

### Task 13: Create dashboard.html

**Files:**
- Create: `frontend/templates/dashboard.html`

**Step 1: Create the dashboard template**

```html
{% extends "base.html" %}

{% block title %}Dashboard — Job Search Command Center{% endblock %}

{% block content %}
<div class="content-inner">

  {# Page header #}
  <div class="page-header">
    <h1 class="page-title">Job Search Command Center</h1>
    {% if spending %}
    <span class="pill pill-credit">
      ${{ "%.2f" | format(spending.remaining | default(0)) }} rimanenti
    </span>
    {% endif %}
  </div>

  {# Flash messages #}
  {% if error %}
  <div class="message-banner banner-error">{{ error }}</div>
  {% endif %}
  {% if message %}
  <div class="message-banner banner-success">{{ message }}</div>
  {% endif %}

  {# Metric cards #}
  <div class="grid-3col metrics-row">
    {% with value=dashboard.total | default(0), label="Analizzate" %}
      {% include "partials/metric_card.html" %}
    {% endwith %}
    {% with value=dashboard.applied | default(0), label="Candidature" %}
      {% include "partials/metric_card.html" %}
    {% endwith %}
    {% with value="%.1f" | format(dashboard.avg_score | default(0) | float), label="Score medio" %}
      {% include "partials/metric_card.html" %}
    {% endwith %}
  </div>

  {# Follow-up alerts #}
  {% if followup_alerts %}
  <section class="section-followup">
    <h2 class="section-title">Follow-up in scadenza</h2>
    {% include "partials/followup_alerts.html" %}
  </section>
  {% endif %}

  {# Upcoming interviews banner #}
  {% if upcoming_interviews %}
  <section class="section-upcoming">
    {% for iv in upcoming_interviews %}
    <div class="upcoming-banner">
      <!-- interview banner content: date, role, company, link -->
    </div>
    {% endfor %}
  </section>
  {% endif %}

  {# Recent analyses preview #}
  <section class="section-recent">
    <div class="section-header">
      <h2 class="section-title">Ultime analisi</h2>
      <a href="/history" class="link-subtle">Vedi tutto lo storico →</a>
    </div>

    {% if recent_analyses %}
      {% for analysis in recent_analyses %}
        {% with analysis=analysis %}
          {% include "partials/job_card.html" %}
        {% endwith %}
      {% endfor %}
    {% else %}
      <div class="empty-state">
        <p>Nessuna analisi ancora</p>
        <a href="/analyze" class="btn btn-primary">Analizza la tua prima offerta →</a>
      </div>
    {% endif %}
  </section>

</div>
{% endblock %}

{% block scripts_extra %}
<script src="{{ url_for('static', path='js/modules/spending.js') }}?v=10"></script>
<script src="{{ url_for('static', path='js/modules/dashboard.js') }}?v=10"></script>
<script src="{{ url_for('static', path='js/modules/followup.js') }}?v=10"></script>
{% endblock %}
```

**Note for implementer:** The exact variable names (`dashboard.total`, `spending.remaining`, etc.) must be verified against the actual context passed by the route handler and the existing template usage patterns.

**Step 2: Commit**

```bash
git add frontend/templates/dashboard.html
git commit -m "feat: add dashboard page template"
```

---

### Task 14: Create analyze.html

**Files:**
- Create: `frontend/templates/analyze.html`

**Step 1: Create the analyze template**

```html
{% extends "base.html" %}

{% block title %}Nuova Analisi — Job Search Command Center{% endblock %}

{% block content %}
<div class="content-inner">

  <div class="page-header">
    <h1 class="page-title">Nuova Analisi</h1>
  </div>

  {# Flash messages #}
  {% if error %}
  <div class="message-banner banner-error">{{ error }}</div>
  {% endif %}

  {# CV status banner #}
  <div class="cv-status-bar">
    {% if cv and cv.raw_text %}
      <span class="cv-status cv-ok">✅ {{ cv.name | default("CV caricato") }}</span>
      <a href="/settings" class="link-subtle">aggiorna</a>
    {% else %}
      <span class="cv-status cv-missing">⚠️ CV mancante</span>
      <a href="/settings" class="btn btn-sm btn-primary">Carica CV</a>
    {% endif %}
  </div>

  {# Tab toggle: Singola / Multipla #}
  <div class="tabs analyze-tabs" x-data="{ tab: 'single' }">
    <button class="tab" :class="{ active: tab === 'single' }" @click="tab = 'single'">
      Singola
    </button>
    <button class="tab" :class="{ active: tab === 'batch' }" @click="tab = 'batch'">
      Multipla
    </button>
  </div>

  {# Single analysis form #}
  <div x-show="tab === 'single'">
    <form action="/analyze" method="post" class="analyze-form"
          @submit="analyzeLoading = true">
      <div class="form-group">
        <label for="job_url" class="form-label">Link annuncio (opzionale)</label>
        <input type="url" id="job_url" name="job_url" class="input"
               placeholder="https://...">
      </div>

      <div class="form-group">
        <label for="job_description" class="form-label">Descrizione del lavoro</label>
        <textarea id="job_description" name="job_description" class="textarea"
                  placeholder="Incolla la descrizione del lavoro..."
                  required rows="10"></textarea>
      </div>

      <div class="analyze-actions">
        <div class="toggle">
          <label class="toggle-option">
            <input type="radio" name="model" value="haiku" checked>
            <span>Haiku</span>
          </label>
          <label class="toggle-option">
            <input type="radio" name="model" value="sonnet">
            <span>Sonnet</span>
          </label>
        </div>

        <button type="submit" class="btn btn-primary btn-lg"
                :disabled="analyzeLoading"
                :class="{ 'loading-shimmer': analyzeLoading }">
          <span x-show="!analyzeLoading">Analizza →</span>
          <span x-show="analyzeLoading">Analizzando...</span>
        </button>
      </div>
    </form>
  </div>

  {# Batch analysis #}
  <div x-show="tab === 'batch'">
    {% include "partials/batch_form.html" %}
  </div>

</div>
{% endblock %}

{% block scripts_extra %}
<script src="{{ url_for('static', path='js/modules/batch.js') }}?v=10"></script>
{% endblock %}
```

**Step 2: Rename batch.html → batch_form.html**

```bash
mv frontend/templates/partials/batch.html frontend/templates/partials/batch_form.html
```

Update any existing references to the old name.

**Step 3: Commit**

```bash
git add frontend/templates/analyze.html frontend/templates/partials/batch_form.html
git commit -m "feat: add analyze page with single/batch tabs"
```

---

### Task 15: Create history.html

**Files:**
- Create: `frontend/templates/history.html`

**Step 1: Create the history template**

```html
{% extends "base.html" %}

{% block title %}Storico — Job Search Command Center{% endblock %}

{% block content %}
<div class="content-inner" x-data="historyTabs()">

  <div class="page-header">
    <h1 class="page-title">Storico candidature</h1>
  </div>

  {# Status tabs with counts #}
  <div class="tabs">
    <button class="tab" :class="{ active: currentTab === 'all' }"
            @click="switchTab('all')">
      Tutte <span class="tab-badge">{{ analyses | length }}</span>
    </button>
    <button class="tab" :class="{ active: currentTab === 'da_valutare' }"
            @click="switchTab('da_valutare')">
      In valutazione <span class="tab-badge">{{ counts.da_valutare }}</span>
    </button>
    <button class="tab" :class="{ active: currentTab === 'candidato' }"
            @click="switchTab('candidato')">
      Candidature <span class="tab-badge">{{ counts.candidato }}</span>
    </button>
    <button class="tab" :class="{ active: currentTab === 'colloquio' }"
            @click="switchTab('colloquio')">
      Colloqui <span class="tab-badge">{{ counts.colloquio }}</span>
    </button>
    <button class="tab" :class="{ active: currentTab === 'scartato' }"
            @click="switchTab('scartato')">
      Scartati <span class="tab-badge">{{ counts.scartato }}</span>
    </button>
  </div>

  {# Job card list #}
  <div class="job-card-list">
    {% if analyses %}
      {% for analysis in analyses %}
        {% set status_val = analysis.status.value if analysis.status.value is defined else analysis.status %}
        <div class="job-card-wrapper" data-status="{{ status_val }}">
          {% with analysis=analysis %}
            {% include "partials/job_card.html" %}
          {% endwith %}
        </div>
      {% endfor %}
    {% else %}
      <div class="empty-state">
        <p>Nessuna candidatura trovata</p>
        <a href="/analyze" class="btn btn-primary">Analizza un'offerta →</a>
      </div>
    {% endif %}
  </div>

</div>
{% endblock %}

{% block scripts_extra %}
<script src="{{ url_for('static', path='js/modules/history.js') }}?v=10"></script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add frontend/templates/history.html
git commit -m "feat: add history page with status tabs"
```

---

### Task 16: Create analysis_detail.html

**Files:**
- Create: `frontend/templates/analysis_detail.html`

**Step 1: Read the current result.html partial and related partials**

Read these files fully to understand the existing result rendering:
- `frontend/templates/partials/result.html`
- `frontend/templates/partials/result_reputation.html`
- `frontend/templates/partials/interview_detail.html`
- `frontend/templates/partials/cover_letter_form.html`
- `frontend/templates/partials/cover_letter_result.html`

**Step 2: Create analysis_detail.html**

This is the largest template. It extends base.html and includes the existing partials where possible, restructured for the new layout:

```html
{% extends "base.html" %}

{% block title %}{{ result.role | default("Analisi") }} — Job Search Command Center{% endblock %}

{% block content %}
<div class="content-inner">

  {# Back link #}
  <a href="/history" class="link-back">← Storico</a>

  {# Hero section #}
  <div class="analysis-hero">
    <div class="hero-score">
      {% with score=result.score | default(0), size="lg" %}
        {% include "partials/score_ring.html" %}
      {% endwith %}
    </div>
    <div class="hero-info">
      <h1 class="hero-title">{{ result.role | default("—") }}</h1>
      <p class="hero-company">{{ result.company | default("—") }}</p>
      {% if result.recommendation %}
      <span class="recommendation-badge rec-{{ result.recommendation | lower }}">
        {{ result.recommendation }}
      </span>
      {% endif %}
    </div>
  </div>

  {# Tags row #}
  <div class="tags-row">
    <!-- location, work_mode, salary, confidence, etc. as .tag pills -->
    <!-- Port from current result.html hero-tags section -->
  </div>

  {# Company reputation — if available #}
  {% if result.glassdoor_rating %}
    {% include "partials/result_reputation.html" %}
  {% endif %}

  {# AI verdict #}
  {% if result.summary %}
  <div class="card verdict-box">
    <p>{{ result.summary }}</p>
  </div>
  {% endif %}

  {# Job summary #}
  {% if result.job_summary %}
  <div class="card job-summary-box">
    <h2 class="section-title">Sintesi offerta</h2>
    <p>{{ result.job_summary }}</p>
  </div>
  {% endif %}

  {# Strengths vs Gaps — 2 columns #}
  <div class="grid-2col strengths-gaps">
    {# Strengths #}
    <div class="card strengths-col">
      <h2 class="section-title">Punti di forza</h2>
      {% for item in result.strengths | default([]) %}
      <div class="strength-item">
        <span class="strength-text">{{ item }}</span>
      </div>
      {% endfor %}
    </div>

    {# Gaps #}
    <div class="card gaps-col">
      <h2 class="section-title">Gap analysis</h2>
      {% for gap in result.gaps | default([]) %}
      <div class="gap-item gap-{{ gap.severity | default('minor') | lower }}">
        <div class="gap-header">
          <span class="severity-dot"></span>
          <span class="gap-text">{{ gap.skill | default(gap) }}</span>
        </div>
        {% if gap.how_to_close %}
        <p class="gap-close">{{ gap.how_to_close }}</p>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  {# Advice box #}
  {% if result.advice %}
  <blockquote class="advice-box">
    {{ result.advice }}
  </blockquote>
  {% endif %}

  {# Interview section #}
  {% if interview %}
    {% include "partials/interview_detail.html" %}
  {% endif %}

  {# Cover letter section #}
  {% if cover_letter %}
    {% include "partials/cover_letter_result.html" %}
  {% else %}
    {% include "partials/cover_letter_form.html" %}
  {% endif %}

  {# Actions bar #}
  <div class="actions-bar">
    {% if current.job_url %}
    <a href="{{ current.job_url }}" target="_blank" rel="noopener" class="btn btn-ghost">
      Apri annuncio ↗
    </a>
    {% endif %}

    <div class="status-pills">
      <!-- Status pill buttons — port from current result.html -->
      <!-- Each calls setStatus(analysisId, status) -->
    </div>

    <button class="btn btn-ghost" onclick="openInterviewModal('{{ current.id }}')">
      Pianifica colloquio
    </button>

    <button class="btn btn-danger btn-sm" onclick="deleteAnalysis('{{ current.id }}')">
      Elimina
    </button>
  </div>

</div>

{# Interview modal #}
{% include "partials/interview_modal.html" %}
{% endblock %}

{% block head_extra %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/themes/dark.css">
{% endblock %}

{% block scripts_extra %}
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script src="https://cdn.jsdelivr.net/npm/flatpickr/dist/l10n/it.js"></script>
<script src="{{ url_for('static', path='js/modules/status.js') }}?v=10"></script>
<script src="{{ url_for('static', path='js/modules/interview.js') }}?v=10"></script>
<script src="{{ url_for('static', path='js/modules/followup.js') }}?v=10"></script>
<script src="{{ url_for('static', path='js/modules/contacts.js') }}?v=10"></script>
{% endblock %}
```

**Important for implementer:** This template is a SKELETON. You must:
1. Read the current `result.html` line by line
2. Port every data field and conditional
3. Verify exact attribute names from the `result` dict and `current` analysis object
4. Port the status pill buttons, tag rendering, and action handlers exactly

**Step 3: Commit**

```bash
git add frontend/templates/analysis_detail.html
git commit -m "feat: add analysis detail page template"
```

---

### Task 17: Create interviews.html

**Files:**
- Create: `frontend/templates/interviews.html`
- Create: `frontend/templates/partials/interview_card.html`

**Step 1: Read existing interview-related code**

Read:
- `frontend/templates/partials/interview_detail.html`
- `frontend/templates/partials/interview_modal.html`
- `backend/src/interview/service.py` (to understand what data is available)

**Step 2: Create interview_card.html partial**

```html
{#
  Interview Card — shows interview details + prep scripts.
  Usage: {% with item=interview_data %}{% include "partials/interview_card.html" %}{% endwith %}
  Expects: item with .interview (Interview model) and .analysis (JobAnalysis model)
#}
{% set iv = item.interview %}
{% set analysis = item.analysis %}

<div class="card interview-card">
  <div class="interview-card-header">
    <div class="interview-datetime">
      <span class="interview-date">{{ iv.scheduled_at.strftime('%d %b %Y') }}</span>
      <span class="interview-time">{{ iv.scheduled_at.strftime('%H:%M') }}
        {% if iv.ends_at %} – {{ iv.ends_at.strftime('%H:%M') }}{% endif %}
      </span>
    </div>
    <span class="tag">{{ iv.interview_type | default('virtual') }}</span>
  </div>

  <a href="/analysis/{{ analysis.id }}" class="interview-card-role">
    {{ analysis.role | default("—") }} @ {{ analysis.company | default("—") }}
  </a>

  {# Logistic details #}
  <div class="interview-details">
    {% if iv.recruiter_name %}
    <div class="detail-row">
      <span class="detail-label">Recruiter</span>
      <span>{{ iv.recruiter_name }}{% if iv.recruiter_email %} · {{ iv.recruiter_email }}{% endif %}</span>
    </div>
    {% endif %}
    {% if iv.meeting_link %}
    <div class="detail-row">
      <a href="{{ iv.meeting_link }}" target="_blank" class="btn btn-sm btn-primary">Join meeting ↗</a>
    </div>
    {% endif %}
    {% if iv.phone_number %}
    <div class="detail-row">
      <span class="detail-label">Tel</span>
      <span>{{ iv.phone_number }}{% if iv.phone_pin %} PIN: {{ iv.phone_pin }}{% endif %}</span>
    </div>
    {% endif %}
    {% if iv.location %}
    <div class="detail-row">
      <span class="detail-label">Luogo</span>
      <span>{{ iv.location }}</span>
    </div>
    {% endif %}
  </div>

  {# Prep scripts (expandable) #}
  {% if item.prep_scripts %}
  <details class="prep-section">
    <summary class="prep-toggle">Domande preparazione</summary>
    <div class="prep-content">
      {% for qa in item.prep_scripts %}
      <div class="prep-qa">
        <p class="prep-q">{{ qa.question }}</p>
        <p class="prep-a">{{ qa.answer }}</p>
      </div>
      {% endfor %}
    </div>
  </details>
  {% endif %}
</div>
```

**Step 3: Create interviews.html**

```html
{% extends "base.html" %}

{% block title %}Colloqui — Job Search Command Center{% endblock %}

{% block content %}
<div class="content-inner">

  <div class="page-header">
    <h1 class="page-title">Colloqui</h1>
  </div>

  {# Upcoming interviews #}
  {% if upcoming_interviews %}
    <section class="section-upcoming-full">
      {% for item in upcoming_interviews %}
        {% with item=item %}
          {% include "partials/interview_card.html" %}
        {% endwith %}
      {% endfor %}
    </section>
  {% else %}
    <div class="empty-state">
      <p>Nessun colloquio pianificato</p>
    </div>
  {% endif %}

  {# Past interviews #}
  {% if past_interviews %}
  <details class="past-section">
    <summary class="section-title clickable">
      Colloqui passati ({{ past_interviews | length }})
    </summary>
    <div class="past-list">
      {% for item in past_interviews %}
        {% with item=item %}
          {% include "partials/interview_card.html" %}
        {% endwith %}
      {% endfor %}
    </div>
  </details>
  {% endif %}

</div>
{% endblock %}
```

**Note for implementer:** The `get_all_interviews()` service function may need to be created. It should return two lists: upcoming (scheduled_at > now) and past (scheduled_at <= now), each with the associated analysis and prep scripts. Check existing interview service code.

**Step 4: Commit**

```bash
git add frontend/templates/interviews.html frontend/templates/partials/interview_card.html
git commit -m "feat: add interviews page with prep scripts"
```

---

### Task 18: Create settings.html

**Files:**
- Create: `frontend/templates/settings.html`

**Step 1: Read current cv_form.html and spending logic**

Read:
- `frontend/templates/partials/cv_form.html`
- `frontend/static/js/modules/spending.js`
- `frontend/static/js/modules/cv.js`

**Step 2: Create settings.html**

```html
{% extends "base.html" %}

{% block title %}Impostazioni — Job Search Command Center{% endblock %}

{% block content %}
<div class="content-inner">

  <div class="page-header">
    <h1 class="page-title">Impostazioni</h1>
  </div>

  {# CV Section #}
  <section class="card settings-section" x-data="{ editing: false }">
    <h2 class="section-title">Curriculum Vitae</h2>

    {% if cv and cv.raw_text %}
      <div class="cv-status-row" x-show="!editing">
        <span class="cv-status cv-ok">✅ {{ cv.name | default("CV caricato") }}</span>
        <button class="btn btn-ghost btn-sm" @click="editing = true">Modifica</button>
        <a href="/cv/download" class="btn btn-ghost btn-sm">Download</a>
      </div>
    {% endif %}

    <form action="/cv" method="post"
          x-show="editing || !{{ 'true' if cv and cv.raw_text else 'false' }}"
          class="cv-form">
      <div class="form-group">
        <label for="cv_name" class="form-label">Nome</label>
        <input type="text" id="cv_name" name="cv_name" class="input"
               value="{{ cv.name | default('') }}">
      </div>

      <div class="form-group">
        <label for="cv_text" class="form-label">Testo CV</label>
        <textarea id="cv_text" name="cv_text" class="textarea" rows="12"
                  placeholder="Incolla il testo del tuo CV..."
                  required>{{ cv.raw_text | default('') }}</textarea>
      </div>

      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Salva CV</button>
        <button type="button" class="btn btn-ghost" onclick="uploadCV()">
          Upload file
        </button>
        <input type="file" id="cv-file-input" accept=".txt,.pdf,.doc,.docx" hidden>
        {% if cv and cv.raw_text %}
        <button type="button" class="btn btn-ghost btn-sm" @click="editing = false">Annulla</button>
        {% endif %}
      </div>
    </form>
  </section>

  {# API Credits Section #}
  <section class="card settings-section">
    <h2 class="section-title">Crediti API</h2>

    <div class="credits-grid">
      <div class="credit-item">
        <span class="credit-label">Budget</span>
        <span class="credit-value" id="budget-display" contenteditable="true"
              data-budget="{{ spending.budget | default(0) }}">
          ${{ "%.2f" | format(spending.budget | default(0)) }}
        </span>
      </div>
      <div class="credit-item">
        <span class="credit-label">Speso totale</span>
        <span class="credit-value">${{ "%.4f" | format(spending.total_cost_usd | default(0)) }}</span>
      </div>
      <div class="credit-item">
        <span class="credit-label">Rimanente</span>
        <span class="credit-value credit-remaining"
              id="remaining-display">${{ "%.2f" | format(spending.remaining | default(0)) }}</span>
      </div>
      <div class="credit-item">
        <span class="credit-label">Spesa oggi</span>
        <span class="credit-value">${{ "%.4f" | format(spending.today_cost_usd | default(0)) }}</span>
      </div>
    </div>
  </section>

</div>
{% endblock %}

{% block scripts_extra %}
<script src="{{ url_for('static', path='js/modules/cv.js') }}?v=10"></script>
<script src="{{ url_for('static', path='js/modules/spending.js') }}?v=10"></script>
{% endblock %}
```

**Step 3: Commit**

```bash
git add frontend/templates/settings.html
git commit -m "feat: add settings page with CV and API credits"
```

---

## Phase 5: JS Updates and Sections CSS

### Task 19: Update app.js for conditional module init

**Files:**
- Modify: `frontend/static/js/app.js`

**Step 1: Read current app.js**

Read `frontend/static/js/app.js` fully.

**Step 2: Update app.js**

The init function should only initialize modules present on the current page. Since modules are now loaded per-page via `{% block scripts_extra %}`, the app.js only needs to handle shared concerns:

```javascript
function app() {
  return {
    analyzeLoading: false,
    coverLetterLoading: false,

    init() {
      // Init modules that are loaded on this page
      if (typeof initBudgetEditing === "function") initBudgetEditing();
      if (typeof initCVUpload === "function") initCVUpload();

      // Periodic refresh for dashboard (if on dashboard)
      if (document.querySelector(".metrics-row")) {
        setInterval(() => {
          if (typeof refreshDashboard === "function") refreshDashboard();
          if (typeof refreshSpending === "function") refreshSpending();
        }, 60000);
      }
    },

    handleRateLimit(resp) {
      if (resp && resp.status === 429) {
        showToast("Troppe richieste, riprova tra qualche secondo", "error");
        return true;
      }
      return false;
    }
  };
}
```

**Step 3: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "refactor: update app.js for multi-page conditional init"
```

---

### Task 20: Update JS modules for new DOM structure

**Files:**
- Modify: `frontend/static/js/modules/status.js`
- Modify: `frontend/static/js/modules/followup.js`
- Modify: `frontend/static/js/modules/contacts.js`
- Modify: `frontend/static/js/modules/dashboard.js`
- Modify: `frontend/static/js/modules/spending.js`

**Step 1: Read all JS modules**

Read each JS module file fully.

**Step 2: Update DOM selectors and callbacks**

Key changes across modules:
- Replace `alert()` calls with `showToast()` calls
- Update `querySelector` selectors if class names changed
- In `status.js`: after status change, use `showToast()` instead of updating a banner. If on the detail page, the pill buttons update in-place. If on history page, refresh the card's status badge.
- In `followup.js`: no structural changes needed, the functions work on any page that includes the followup partial.
- In `dashboard.js`: update selectors to match new `.metric-value` class names.
- In `spending.js`: update selector for the pill credit display (`#budget-display`, `#remaining-display`).
- In `contacts.js`: no changes if the contacts panel structure stays the same.

**Important:** Do NOT refactor working code unnecessarily. Only change what's needed for the new DOM structure. Read each module, compare selectors with new templates, update only mismatches.

**Step 3: Run the app and verify each page loads**

```bash
python -m uvicorn backend.src.main:app --reload
```

Test each page manually:
- `/` — dashboard loads, metrics show
- `/analyze` — form renders, tab toggle works
- `/history` — tabs filter correctly
- `/settings` — CV form works, credits display
- `/analysis/{id}` — detail page renders with score ring

**Step 4: Commit**

```bash
git add frontend/static/js/modules/
git commit -m "refactor: update JS modules for new DOM structure and toast notifications"
```

---

### Task 21: Rewrite sections.css

**Files:**
- Modify: `frontend/static/css/sections.css`

**Step 1: Read current sections.css**

Read `frontend/static/css/sections.css` fully. This is the largest CSS file (~1060 lines).

**Step 2: Rewrite sections.css**

Replace entirely. Organize by page:

**Dashboard sections:**
- `.metrics-row`: gap spacing for metric cards
- `.section-followup`: amber-tinted card for alerts
- `.section-upcoming`: subtle card for interview banners
- `.upcoming-banner`: flex row, date + role + link
- `.section-recent`: list container. `.section-header`: flex between title and "vedi tutto" link
- `.empty-state`: centered text + CTA button, padding, muted text

**Analyze sections:**
- `.cv-status-bar`: flex row, gap, align center, margin bottom
- `.analyze-form`: max-width 640px (focused single column)
- `.analyze-actions`: flex between toggle and submit button, margin top
- `.form-group`: margin bottom. `.form-label`: text-sm, text-secondary, margin bottom xs

**Analysis detail sections:**
- `.analysis-hero`: flex row, gap xl, align center, margin bottom
- `.hero-score`: flex-shrink 0
- `.hero-title`: text-xl, bold
- `.hero-company`: text-secondary
- `.tags-row`: flex wrap, gap sm. `.tag`: bg-tertiary, radius-full, padding xs sm, text-xs
- `.verdict-box`: border-left 3px accent-blue, padding
- `.job-summary-box`: padding, text-secondary
- `.strengths-gaps`: margin top/bottom xl
- `.strength-item`: padding sm, left-border green dot
- `.gap-item`: padding sm. `.severity-dot`: 6px circle, inline-block. Colors by severity.
- `.gap-close`: text-sm, text-tertiary, margin top xs
- `.advice-box`: blockquote, text-lg, padding xl, border-left 3px accent-blue, bg-secondary, italic
- `.actions-bar`: flex wrap, gap, padding top, border-top subtle
- `.status-pills`: flex row, gap sm
- `.link-back`: text-secondary, text-sm, margin bottom lg

**History sections:**
- `.job-card-list`: flex column, gap 2px (tight list)
- `.job-card`: (already in components.css)

**Interviews sections:**
- `.interview-card`: card with padding, margin bottom
- `.interview-card-header`: flex between datetime and type tag
- `.interview-datetime`: flex column, `.interview-date` bold, `.interview-time` text-secondary
- `.interview-card-role`: text-lg, text-primary, hover accent-blue
- `.interview-details`: grid 2col on desktop. `.detail-row`: flex, gap
- `.detail-label`: text-secondary, min-width 80px
- `.prep-section`: margin top. `.prep-toggle`: cursor pointer, text-secondary, hover text-primary
- `.prep-qa`: padding, border-bottom subtle. `.prep-q` bold, `.prep-a` text-secondary
- `.past-section`: margin top xl

**Settings sections:**
- `.settings-section`: margin bottom xl, padding xl
- `.cv-status-row`: flex row, gap, align center
- `.cv-form`: margin top lg. `.form-actions`: flex row, gap, margin top
- `.credits-grid`: grid 2col, gap lg. `.credit-item`: flex column. `.credit-label`: text-sm text-secondary. `.credit-value`: text-lg bold
- `.credit-remaining`: color based on threshold (green/orange/red — set via JS or Jinja conditional class)

**Login page** (standalone):
- `.login-wrapper`: centered flex, min-height 100vh, bg-primary
- `.login-card`: bg-secondary, radius-xl, padding 2xl, max-width 400px

**Error pages** (404, 500):
- `.error-page`: centered flex, text-center, padding 3xl

**Step 3: Commit**

```bash
git add frontend/static/css/sections.css
git commit -m "style: rewrite sections.css for all redesigned pages"
```

---

## Phase 6: Polish and Finalization

### Task 22: Update login page styling

**Files:**
- Modify: `frontend/templates/login.html`

**Step 1: Read current login.html**

Read `frontend/templates/login.html` fully.

**Step 2: Update login.html**

Login is standalone (no sidebar). Update to use new design tokens:
- Dark background (`--bg-primary`)
- Centered card (`--bg-secondary`, `--radius-xl`)
- Inputs with new styling
- Primary button
- Keep it simple — just the visual update, no structural change

**Step 3: Commit**

```bash
git add frontend/templates/login.html
git commit -m "style: update login page with new design tokens"
```

---

### Task 23: Update error pages (404, 500)

**Files:**
- Modify: `frontend/templates/404.html`
- Modify: `frontend/templates/500.html`

**Step 1: Update both error pages**

Both should extend `base.html` (with sidebar visible). Content: centered message with large error code, description, and link to dashboard.

**Step 2: Commit**

```bash
git add frontend/templates/404.html frontend/templates/500.html
git commit -m "style: update error pages with sidebar layout"
```

---

### Task 24: Update existing partials for new design

**Files:**
- Modify: `frontend/templates/partials/followup_alerts.html`
- Modify: `frontend/templates/partials/cover_letter_form.html`
- Modify: `frontend/templates/partials/cover_letter_result.html`
- Modify: `frontend/templates/partials/interview_modal.html`
- Modify: `frontend/templates/partials/interview_detail.html`
- Modify: `frontend/templates/partials/batch_form.html` (renamed from batch.html)
- Modify: `frontend/templates/partials/contacts_panel.html` (if exists, or the contacts section in dashboard)

**Step 1: Read each partial**

Read each file fully.

**Step 2: Update class names and structure**

For each partial:
- Replace emoji icons used as UI elements with text or remove (per brief: no emoji as functional icons)
- Update CSS class names to match the new components.css
- Update button classes: `btn btn-primary`, `btn btn-ghost`, `btn btn-danger`, `btn btn-sm`
- Update card/container classes
- Keep all Alpine.js bindings and JS function calls intact
- Keep all form field names and action URLs intact

**Important:** DO NOT change form `action` URLs, `name` attributes, or JS function calls. Only update visual classes and HTML structure.

**Step 3: Commit**

```bash
git add frontend/templates/partials/
git commit -m "style: update all partials for new design system"
```

---

### Task 25: Remove old index.html and header partial

**Files:**
- Delete: `frontend/templates/index.html` (replaced by dashboard + analyze + etc.)
- Delete: `frontend/templates/partials/header.html` (replaced by sidebar)
- Delete: `frontend/templates/partials/cv_form.html` (now in settings.html)
- Delete: `frontend/templates/partials/analyze_form.html` (now in analyze.html)
- Delete: `frontend/templates/partials/result.html` (now in analysis_detail.html)
- Delete: `frontend/templates/partials/history.html` (now in history.html page)
- Delete: `frontend/templates/partials/dashboard.html` (now in dashboard.html page)

**Step 1: Verify no remaining references**

```bash
grep -rn "index.html\|partials/header.html\|partials/cv_form.html\|partials/analyze_form.html\|partials/result.html\|partials/history.html\|partials/dashboard.html" backend/ frontend/ --include="*.py" --include="*.html"
```

Remove or update any remaining references (old `_render_page()` function, old route that renders `index.html`, etc.).

**Step 2: Delete files**

```bash
git rm frontend/templates/index.html
git rm frontend/templates/partials/header.html
git rm frontend/templates/partials/cv_form.html
git rm frontend/templates/partials/analyze_form.html
git rm frontend/templates/partials/result.html
git rm frontend/templates/partials/history.html
git rm frontend/templates/partials/dashboard.html
```

**Step 3: Commit**

```bash
git commit -m "chore: remove old single-page templates replaced by multi-page layout"
```

---

### Task 26: Full integration test

**Files:**
- Modify: `backend/tests/test_routes.py` (add authenticated route tests)

**Step 1: Add authenticated page render tests**

Add tests that verify each page renders successfully when authenticated. This requires creating a test fixture that logs in:

```python
@pytest.fixture
def auth_client(app_client):
    """Client with an authenticated session."""
    # Create test user and log in
    # Implementation depends on how test_user fixture works
    # May need to POST to /login or directly set session
    ...

def test_dashboard_renders(auth_client):
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert "Job Search Command Center" in resp.text

def test_analyze_renders(auth_client):
    resp = auth_client.get("/analyze")
    assert resp.status_code == 200
    assert "Nuova Analisi" in resp.text

def test_history_renders(auth_client):
    resp = auth_client.get("/history")
    assert resp.status_code == 200
    assert "Storico" in resp.text

def test_interviews_renders(auth_client):
    resp = auth_client.get("/interviews")
    assert resp.status_code == 200

def test_settings_renders(auth_client):
    resp = auth_client.get("/settings")
    assert resp.status_code == 200
    assert "Impostazioni" in resp.text
```

**Step 2: Run full test suite**

```bash
python -m pytest backend/tests/ -v
```

Expected: ALL tests pass (baseline + new).

**Step 3: Manual visual testing**

Start the app and verify each page:
1. `/login` — dark theme, centered card
2. `/` — sidebar highlighted, 3 metric cards, recent analyses
3. `/analyze` — tab toggle works, form submits, shimmer loading
4. `/history` — tabs filter, job cards render with score rings
5. `/analysis/{id}` — full detail with hero score, strengths/gaps, actions
6. `/interviews` — upcoming cards with prep, past collapsed
7. `/settings` — CV edit toggle, credits display
8. Mobile (resize to 375px width) — bottom bar, stacked layouts
9. Click through: analyze → result → back to history → detail
10. Test toast: change status on a card, verify toast appears

**Step 4: Commit tests**

```bash
git add backend/tests/test_routes.py
git commit -m "test: add authenticated page render tests for all routes"
```

---

### Task 27: Final polish — micro-interactions and cleanup

**Step 1: Verify all micro-interactions**

Check that these work:
- Card hover: translateY(-1px) + shadow
- Button hover: brightness(1.1)
- Button active: scale(0.98)
- Modal: backdrop blur + scale animation
- Page load: fade in
- Loading: shimmer on buttons
- Toast: slide up, auto-dismiss

**Step 2: Bump asset versions**

In `base.html`, ensure all CSS/JS references use `?v=10` (or a new version number) to bust caches.

**Step 3: Final commit on redesign branch**

```bash
git add -A
git commit -m "style: final polish — micro-interactions, asset version bump"
```

**Step 4: Run full test suite one last time**

```bash
python -m pytest backend/tests/ -v
```

Expected: ALL pass.

---

## Summary

| Phase | Tasks | Focus |
|-------|-------|-------|
| 1. Foundation | 1–6 | Branch, CSS tokens, base template, sidebar, layout |
| 2. Backend | 7 | New routes, redirect refactoring, route tests |
| 3. Components | 8–12 | Score ring, job card, metric card, components CSS, toast |
| 4. Pages | 13–18 | Dashboard, analyze, history, detail, interviews, settings |
| 5. JS + CSS | 19–21 | app.js update, module selectors, sections.css |
| 6. Polish | 22–27 | Login, errors, partials update, cleanup, integration test |

**Total tasks:** 27
**Estimated commits:** ~27

Each task is independently committable and testable. The app may be in a broken visual state between Phase 1 and Phase 4 (templates reference classes not yet defined), but becomes functional once Phase 4 completes.
