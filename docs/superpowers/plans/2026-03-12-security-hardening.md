# Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden all API endpoints with UUID validation, input schemas, rate limiting, CSP header, and CORS tightening.

**Architecture:** Add a reusable `ValidAnalysisId` dependency for UUID path param validation. Add Pydantic schemas where missing. Add rate limits on AI-heavy endpoints. Replace deprecated X-XSS-Protection with Content-Security-Policy. Tighten CORS allow_headers.

**Tech Stack:** FastAPI, Pydantic, slowapi, Starlette middleware

---

## Chunk 1: UUID Validation Dependency + Contacts Schema

### Task 1: Reusable UUID Path Parameter Validation

**Files:**
- Modify: `backend/src/dependencies.py`
- Create: `backend/tests/test_dependencies.py`

- [ ] **Step 1: Write failing tests for UUID validation**

```python
# backend/tests/test_dependencies.py
"""Tests for shared dependencies."""

import pytest
from fastapi import HTTPException

from src.dependencies import validate_uuid


class TestValidateUuid:
    def test_valid_uuid(self):
        import uuid
        valid = str(uuid.uuid4())
        result = validate_uuid(valid)
        assert isinstance(result, uuid.UUID)

    def test_invalid_uuid(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("not-a-uuid")
        assert exc_info.value.status_code == 400

    def test_empty_string(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("")
        assert exc_info.value.status_code == 400

    def test_sql_injection_attempt(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("'; DROP TABLE users; --")
        assert exc_info.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_dependencies.py -v`
Expected: FAIL - `validate_uuid` not found

- [ ] **Step 3: Implement validate_uuid in dependencies.py**

Add to `backend/src/dependencies.py`:

```python
from fastapi import HTTPException

def validate_uuid(value: str) -> UUID:
    """Validate and parse a UUID string. Raises 400 on invalid input."""
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid ID format")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_dependencies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/dependencies.py backend/tests/test_dependencies.py
git commit -m "feat: add reusable UUID validation dependency"
```

---

### Task 2: Contacts Pydantic Schema + Input Validation

**Files:**
- Modify: `backend/src/contacts/routes.py`
- Create: `backend/tests/test_contacts_validation.py`

- [ ] **Step 1: Write failing tests for contacts validation**

```python
# backend/tests/test_contacts_validation.py
"""Tests for contacts route validation."""

import re
import pytest

from src.contacts.routes import VALID_SOURCES, ContactPayload


class TestContactPayload:
    def test_valid_payload(self):
        p = ContactPayload(name="Mario Rossi", email="mario@example.com", source="manual")
        assert p.name == "Mario Rossi"

    def test_name_max_length(self):
        with pytest.raises(Exception):
            ContactPayload(name="x" * 256)

    def test_email_max_length(self):
        with pytest.raises(Exception):
            ContactPayload(email="x" * 256)

    def test_linkedin_url_max_length(self):
        with pytest.raises(Exception):
            ContactPayload(linkedin_url="x" * 501)


class TestValidSources:
    @pytest.mark.parametrize("source", ["manual", "linkedin", "email", "other"])
    def test_valid_sources(self, source):
        assert source in VALID_SOURCES

    @pytest.mark.parametrize("source", ["random", "api", ""])
    def test_invalid_sources(self, source):
        assert source not in VALID_SOURCES
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_contacts_validation.py -v`
Expected: FAIL - `ContactPayload`, `VALID_SOURCES` not found

- [ ] **Step 3: Implement contacts validation in routes.py**

Rewrite `backend/src/contacts/routes.py`:

```python
"""Contact routes."""

import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..dependencies import CurrentUser, DbSession, validate_uuid
from .service import create_contact, delete_contact_by_id, get_contacts_for_analysis

router = APIRouter(tags=["contacts"])

VALID_SOURCES = {"manual", "linkedin", "email", "other"}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class ContactPayload(BaseModel):
    analysis_id: str = ""
    name: str = Field("", max_length=255)
    email: str = Field("", max_length=255)
    phone: str = Field("", max_length=50)
    company: str = Field("", max_length=255)
    linkedin_url: str = Field("", max_length=500)
    notes: str = Field("", max_length=2000)
    source: str = Field("manual", max_length=20)


@router.post("/contacts")
def add_contact(
    payload: ContactPayload,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    if payload.source and payload.source not in VALID_SOURCES:
        return JSONResponse({"error": f"Source non valida: {payload.source}"}, status_code=400)
    if payload.email and not EMAIL_RE.match(payload.email):
        return JSONResponse({"error": "Formato email non valido"}, status_code=400)
    if payload.linkedin_url and not URL_RE.match(payload.linkedin_url):
        return JSONResponse({"error": "URL LinkedIn deve iniziare con http:// o https://"}, status_code=400)

    if payload.analysis_id:
        validate_uuid(payload.analysis_id)

    contact = create_contact(
        db, payload.analysis_id, payload.name, payload.email,
        payload.phone, payload.company, payload.linkedin_url,
        payload.notes, payload.source,
    )
    db.commit()
    return JSONResponse(
        {
            "ok": True,
            "contact": {
                "id": str(contact.id),
                "name": contact.name,
                "email": contact.email,
                "phone": contact.phone,
                "company": contact.company,
                "linkedin_url": contact.linkedin_url,
                "notes": contact.notes,
            },
        }
    )


@router.get("/contacts/{analysis_id}")
def list_contacts(
    analysis_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    validate_uuid(analysis_id)
    contacts = get_contacts_for_analysis(db, analysis_id)
    return JSONResponse(
        {
            "contacts": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "email": c.email,
                    "phone": c.phone,
                    "company": c.company,
                    "linkedin_url": c.linkedin_url,
                    "notes": c.notes,
                    "source": c.source,
                }
                for c in contacts
            ]
        }
    )


@router.delete("/contacts/{contact_id}")
def remove_contact(
    contact_id: str,
    db: DbSession,
    user: CurrentUser,
) -> JSONResponse:
    validate_uuid(contact_id)
    if not delete_contact_by_id(db, contact_id):
        return JSONResponse({"error": "Contact not found"}, status_code=404)
    db.commit()
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_contacts_validation.py tests/test_dependencies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/contacts/routes.py backend/tests/test_contacts_validation.py
git commit -m "feat: add Pydantic schema and validation to contacts routes"
```

---

## Chunk 2: UUID Validation on All Routes + Budget Range Check

### Task 3: Add validate_uuid to All Path Param Routes

**Files:**
- Modify: `backend/src/read_routes.py`
- Modify: `backend/src/analysis/api_routes.py`
- Modify: `backend/src/analysis/followup_routes.py`
- Modify: `backend/src/interview/routes.py`
- Modify: `backend/src/cover_letter/routes.py`

For each file, add `from .dependencies import validate_uuid` (or `from ..dependencies import validate_uuid`) and call `validate_uuid(analysis_id)` at the start of every route that takes `analysis_id`, `contact_id`, or `cover_letter_id` as a path parameter.

- [ ] **Step 1: Add validate_uuid to read_routes.py**

Add import and calls for:
- `candidature_detail(analysis_id)` — line 108
- `interview_prep(analysis_id)` — line 129
- `cover_letters(analysis_id)` — line 154

- [ ] **Step 2: Add validate_uuid to analysis/api_routes.py**

Add import and calls for:
- `change_status(analysis_id)` — line 76
- `delete_analysis(analysis_id)` — line 99

- [ ] **Step 3: Add validate_uuid to analysis/followup_routes.py**

Add import and calls for:
- `mark_followup_done(analysis_id)` — line 104
- Also validate `analysis_id` from Form in `create_followup_email` and `create_linkedin_message`

- [ ] **Step 4: Add validate_uuid to interview/routes.py**

Add import and calls for:
- `upsert_interview(analysis_id)` — line 47
- `get_interview(analysis_id)` — line 112
- `remove_interview(analysis_id)` — line 142

- [ ] **Step 5: Add validate_uuid to cover_letter/routes.py**

Read file first, add validate_uuid to download endpoint with `cover_letter_id`.

- [ ] **Step 6: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/read_routes.py backend/src/analysis/api_routes.py \
  backend/src/analysis/followup_routes.py backend/src/interview/routes.py \
  backend/src/cover_letter/routes.py
git commit -m "feat: add UUID validation to all path parameter routes"
```

---

### Task 4: Budget Range Validation

**Files:**
- Modify: `backend/src/dashboard/routes.py`

- [ ] **Step 1: Add budget range validation**

In `set_budget()`, add validation before calling `update_budget()`:

```python
if budget < 0 or budget > 1000:
    return JSONResponse({"error": "Budget deve essere tra 0 e 1000 USD"}, status_code=400)
```

- [ ] **Step 2: Add return type annotations**

Add `-> JSONResponse` to all route functions in dashboard/routes.py.

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/dashboard/routes.py
git commit -m "feat: add budget range validation and return type annotations"
```

---

## Chunk 3: Rate Limiting + Security Headers

### Task 5: Rate Limit AI-Heavy Endpoints

**Files:**
- Modify: `backend/src/analysis/followup_routes.py`

- [ ] **Step 1: Add rate limiting to followup-email and linkedin-message**

Add `from ..rate_limit import limiter` and `from ..config import settings` imports.

Add decorator to both endpoints:
```python
@router.post("/followup-email")
@limiter.limit(settings.rate_limit_analyze)  # 10/minute, same as analyze
def create_followup_email(...)
```

```python
@router.post("/linkedin-message")
@limiter.limit(settings.rate_limit_analyze)
def create_linkedin_message(...)
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/src/analysis/followup_routes.py
git commit -m "feat: add rate limiting to followup-email and linkedin-message"
```

---

### Task 6: Security Headers — CSP + CORS Tightening

**Files:**
- Modify: `backend/src/main.py`

- [ ] **Step 1: Replace X-XSS-Protection with Content-Security-Policy**

In the `security_headers` middleware (line 145-154), replace:

```python
response.headers["X-XSS-Protection"] = "1; mode=block"
```

with:

```python
response.headers["Content-Security-Policy"] = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)
```

Note: `'unsafe-inline'` needed for Jinja2 templates with inline scripts/styles. `frame-ancestors 'none'` replaces X-Frame-Options DENY.

- [ ] **Step 2: Tighten CORS allow_headers**

Change from:
```python
allow_headers=["*"],
```

to:
```python
allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
```

- [ ] **Step 3: Add Permissions-Policy header**

Add to the security_headers middleware:
```python
response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
```

- [ ] **Step 4: Verify app works with new headers**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/main.py
git commit -m "feat: add CSP, Permissions-Policy, tighten CORS headers"
```

---

## Chunk 4: Tests + Final Verification

### Task 7: Integration Tests for Security Headers

**Files:**
- Create: `backend/tests/test_security_headers.py`

- [ ] **Step 1: Write security header tests**

```python
# backend/tests/test_security_headers.py
"""Tests for security headers and middleware."""

import pytest
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        response = client.get("/health")
        assert "Content-Security-Policy" in response.headers
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_nosniff_header(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy(self, client):
        response = client.get("/health")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        response = client.get("/health")
        assert "Permissions-Policy" in response.headers

    def test_no_deprecated_xss_protection(self, client):
        response = client.get("/health")
        assert "X-XSS-Protection" not in response.headers
```

- [ ] **Step 2: Run new tests**

Run: `cd backend && python -m pytest tests/test_security_headers.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing`
Expected: All PASS

- [ ] **Step 4: Run linters**

Run: `ruff check backend/src/ backend/tests/ && ruff format --check backend/src/ backend/tests/`
Expected: Clean

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_security_headers.py
git commit -m "test: add security header integration tests"
```

---

### Task 8: Final Review + Squash Commit

- [ ] **Step 1: Run full CI checks locally**

```bash
cd backend && python -m pytest tests/ -v --tb=short --cov=src --cov-fail-under=50
ruff check backend/src/ backend/tests/
ruff format --check backend/src/ backend/tests/
mypy backend/src/interview/ --ignore-missing-imports --disallow-untyped-defs --no-implicit-optional --warn-return-any --follow-imports=silent
```

- [ ] **Step 2: Push branch and open PR**

```bash
git push -u origin security/hardening
gh pr create --title "feat: security hardening - UUID validation, CSP, rate limiting" --body "..."
```
