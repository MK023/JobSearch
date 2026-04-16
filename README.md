# Job Search Command Center

[![CI](https://github.com/MK023/JobSearch/actions/workflows/ci.yml/badge.svg)](https://github.com/MK023/JobSearch/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.131-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-465_passed-30D158)
![mypy](https://img.shields.io/badge/mypy-strict-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

AI-powered job search platform. Paste your CV, analyze job postings, get compatibility scores, gap analysis, interview prep, cover letters, and automated outreach tools. Query your data from Claude Desktop via MCP.

**[Live](https://jobsearches.cc)** | **[API](https://api.jobsearches.cc/health)**

---

## Architecture

```
  Claude Desktop          Browser
       |                     |
       v                     |
  +---------------+          |
  |  MCP Server   |          |
  | (local, stdio)|          |
  | 15 read-only  |          |
  | tools, proxy  |          |
  +-------+-------+          |
          | HTTP (X-API-Key) |
          v                  v
  +----------------------------------+
  |       FastAPI + Jinja2           |---- Claude API (Haiku/Sonnet)
  |    (Render.com, Frankfurt)      |---- Cloudflare R2 (file storage)
  +---------------+------------------+---- Resend (email reminders)
                  |
           +------+------+
           |              |
     +-----v------+  +----v----+
     | PostgreSQL |  |  Redis  |
     |  (Neon)    |  |  (opt)  |
     +------------+  +---------+
```

The MCP server runs locally on macOS via Claude Desktop (stdio transport). It is a thin HTTP proxy (~120 lines) — every tool is a single HTTP call to the backend. The backend on Render.com does everything: AI analysis via Anthropic API (tool-use schema-driven JSON), PostgreSQL persistence (Neon), deduplication, cost tracking, and serves the web UI.

---

## Features

| Feature | Description |
|---------|-------------|
| **AI Analysis** | Claude Haiku/Sonnet scores CV-to-job compatibility (0-100) |
| **Gap Analysis** | Structured gaps with severity, bridgeability, and action plan |
| **Interview Prep** | Likely questions + suggested answers based on your CV |
| **Cover Letter** | Multi-language, context-aware (uses analysis results) |
| **Follow-up Email/LinkedIn** | Automated outreach scaled to days since application |
| **Multi-round Interviews** | Per-round scheduling (conoscitivo/tecnico/finale) with outcome tracking (passed/rejected/withdrawn) |
| **Notification Center** | 6 computed rules (upcoming interview, low budget, interview without outcome, DB size, followup, backlog) |
| **Stats Page** | 9 Chart.js charts: funnel, score distribution, timeline, top companies, work mode, contract split, recommendation, spending |
| **File Upload** | Document upload via Cloudflare R2 with presigned URLs |
| **Document Scanner** | Claude API checks if uploaded documents are filled in |
| **Email Reminder** | Resend notifies about unfilled documents |
| **Batch Analysis** | Persistent PostgreSQL queue, survives crashes and autostop |
| **Recruiter Contacts** | Per-application CRM: name, email, phone, LinkedIn |
| **Company Reputation** | Glassdoor rating via RapidAPI with 30-day cache |
| **Cost Tracking** | Per-analysis cost, daily totals, configurable budget |
| **DB Usage Monitoring** | Track PostgreSQL usage against 1GB free tier limit |
| **Audit Trail** | DB log of all user actions |
| **Dashboard** | Stats, top matches, active applications, upcoming interviews |
| **DB Cleanup** | Delete old low-score analyses to free 1GB storage (dry-run default) |
| **Claude MCP** | 15 read-only tools to query data from Claude Desktop |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI + Uvicorn + Jinja2 SSR |
| **ORM** | SQLAlchemy 2.0 + Alembic |
| **Database** | PostgreSQL 17 (Neon serverless, 1GB free tier) |
| **Cache** | Redis 7 (optional, graceful degradation) |
| **AI** | Anthropic Claude API (tool-use schema-driven JSON, prompt v6 candidate-aware) |
| **File Storage** | Cloudflare R2 (S3-compatible, presigned URLs) |
| **Email** | Resend (document reminders) |
| **Auth** | Session + bcrypt + rate limiting (slowapi) for web UI; API key (X-API-Key) for MCP |
| **MCP** | FastMCP (local, stdio) — 15 read-only tools, thin HTTP proxy |
| **Charts** | Chart.js 4.4 (self-hosted, no CDN) |
| **CI/CD** | GitHub Actions 9-stage (ruff, ruff format, mypy strict, bandit, pip-audit, stylelint, CodeQL, pytest, Docker build) |
| **Deploy** | Render.com (Frankfurt) + Cloudflare (DNS, R2, domain) |

---

## Security

- Content-Security-Policy (CSP) with script/style/font/img whitelist
- Permissions-Policy (camera, microphone, geolocation denied)
- HSTS (2 years, includeSubDomains) + X-Content-Type-Options + X-Frame-Options
- UUID validation on all path parameters (anti-injection)
- Pydantic schema validation on all inputs (email regex, URL whitelist, enum whitelist)
- Rate limiting: 60/min global, 10/min AI routes, 5/min login
- bcrypt password hashing + session-based auth for web UI
- API key auth (X-API-Key header) for MCP-to-backend calls
- HTTPS only (force_https=true)
- TrustedHost middleware + restrictive CORS origins
- DB audit trail for all user actions
- Bandit security scanning + pip-audit in CI
- mypy strict on all modules (0 errors, 76 files)
- Input size limits (CV 100KB, job description 50KB)
- API key rejection when unconfigured (prevents auth bypass)
- BOLA protection on batch item status updates
- Field-level input validation (max_length on all import fields)
- URL scheme validation on job URLs
- Budget hard stop: analysis blocked when budget exhausted

---

## Quick Start

```bash
git clone https://github.com/MK023/JobSearch.git
cd JobSearch
cp .env.example .env
# Configure: ANTHROPIC_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d
```

Open `http://localhost` — log in with your admin credentials.

---

## Deploy (Render.com)

The app is deployed on Render.com (Frankfurt region) as a Docker web service with auto-deploy on push to `main`. PostgreSQL is hosted on Neon (serverless, 1GB free tier).

```bash
# Environment variables on Render:
ANTHROPIC_API_KEY, SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD,
DATABASE_URL (from Neon), REDIS_URL (optional),
R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL, R2_BUCKET_NAME,
API_KEY (for MCP auth), RESEND_API_KEY,
TRUSTED_HOSTS, CORS_ALLOWED_ORIGINS
```

Alembic migrations run automatically on deploy (Dockerfile entrypoint).

---

## Costs

| Model | Per analysis | Follow-up |
|-------|-------------|-----------|
| Haiku 4.5 | ~$0.005 | ~$0.001 |
| Sonnet 4.5 | ~$0.02 | ~$0.001 |

Render free tier: 750 hours/month. Neon free tier: 1GB storage, autosuspend. R2 free tier: 10GB storage, 1M ops/month.

---

## License

MIT
