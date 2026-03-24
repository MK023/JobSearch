# Job Search Command Center

[![CI](https://github.com/MK023/JobSearch/actions/workflows/ci.yml/badge.svg)](https://github.com/MK023/JobSearch/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.131-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-320_passed-30D158)
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
  | 25 tools,     |          |
  | thin proxy    |          |
  +-------+-------+          |
          | HTTP (X-API-Key) |
          v                  v
  +----------------------------------+
  |       FastAPI + Jinja2           |---- Claude API (Haiku/Sonnet)
  |     (Fly.io free tier, CDG)     |---- Cloudflare R2 (file storage)
  +---------------+------------------+---- Resend (email reminders)
                  |
           +------+------+
           |              |
     +-----v------+  +----v----+
     | PostgreSQL |  |  Redis  |
     |  (Fly.io)  |  |  (opt)  |
     +------------+  +---------+
```

The MCP server runs locally on macOS via Claude Desktop (stdio transport). It is a thin HTTP proxy (~120 lines) — every tool is a single HTTP call to the backend. The backend on Fly.io does everything: AI analysis via Anthropic API, PostgreSQL persistence, deduplication, cost tracking, and serves the web UI.

---

## Features

| Feature | Description |
|---------|-------------|
| **AI Analysis** | Claude Haiku/Sonnet scores CV-to-job compatibility (0-100) |
| **Gap Analysis** | Structured gaps with severity, bridgeability, and action plan |
| **Interview Prep** | Likely questions + suggested answers based on your CV |
| **Cover Letter** | Multi-language, context-aware (uses analysis results) |
| **Follow-up Email/LinkedIn** | Automated outreach scaled to days since application |
| **Interviews** | Scheduling with dynamic form (Meet/Teams/Zoom/phone/in-person) |
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
| **Claude MCP** | 25 tools to query and manage data from Claude Desktop |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI + Uvicorn + Jinja2 SSR |
| **ORM** | SQLAlchemy 2.0 + Alembic |
| **Database** | PostgreSQL 16 (Fly.io, 1GB free tier) |
| **Cache** | Redis 7 (optional, graceful degradation) |
| **AI** | Anthropic Claude API + 7-strategy JSON parsing |
| **File Storage** | Cloudflare R2 (S3-compatible, presigned URLs) |
| **Email** | Resend (document reminders) |
| **Auth** | Session + bcrypt + rate limiting (slowapi) for web UI; API key (X-API-Key) for MCP |
| **MCP** | FastMCP (local, stdio) — 25 tools, thin HTTP proxy |
| **CI/CD** | GitHub Actions (ruff, mypy strict, bandit, pip-audit, pytest, docker) |
| **Deploy** | Fly.io (512MB shared CPU, CDG) + Cloudflare (DNS, R2, domain) |

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
- mypy strict on all modules (0 errors, 67 files)
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

## Deploy (Fly.io)

```bash
fly apps create jobsearch
fly postgres create --name jobsearch-db --region cdg
fly postgres attach jobsearch-db
fly secrets set ANTHROPIC_API_KEY=sk-ant-... SECRET_KEY=$(openssl rand -hex 32)
fly secrets set ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=your-password
fly secrets set R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_ENDPOINT_URL=... R2_BUCKET_NAME=...
fly secrets set API_KEY=your-mcp-api-key
fly deploy
```

Alembic migrations run automatically on deploy (`release_command`).

Free tier limits: 512MB shared CPU, PostgreSQL 1GB / 300 connections, auto-stop after ~5 min inactivity, auto-start on first request.

---

## Costs

| Model | Per analysis | Follow-up |
|-------|-------------|-----------|
| Haiku 4.5 | ~$0.005 | ~$0.001 |
| Sonnet 4.5 | ~$0.02 | ~$0.001 |

Fly.io free tier: 3 shared-cpu VMs, 256MB each. R2 free tier: 10GB storage, 1M ops/month.

---

## License

MIT
