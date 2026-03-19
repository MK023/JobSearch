# Job Search Command Center

[![CI](https://github.com/MK023/JobSearch/actions/workflows/ci.yml/badge.svg)](https://github.com/MK023/JobSearch/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.131-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-275_passed-30D158)
![mypy](https://img.shields.io/badge/mypy-strict-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

Piattaforma AI per la ricerca lavoro. Incolla il CV, analizza annunci, ottieni score di compatibilità, gap analysis, preparazione colloqui, cover letter e strumenti di outreach automatizzati. Interroga i dati da Claude Desktop via MCP.

**[Live](https://jobsearches.cc)** | **[API](https://api.jobsearches.cc/health)** | **[MCP](https://jobsearch-mcp.fly.dev/mcp)**

---

## Architettura

```
  Claude Desktop          Browser
       │                     │
       ▼                     │
  ┌──────────────┐           │
  │  MCP Server  │           │
  │ (15 tools,   │           │
  │  read-only)  │           │
  └──────┬───────┘           │
         │ HTTP              │
         ▼                   ▼
  ┌─────────────────────────────────┐
  │        FastAPI + Jinja2         │──── Claude API (Haiku/Sonnet)
  │      (Fly.io, 512MB x2)        │──── Cloudflare R2 (file storage)
  └──────────────┬──────────────────┘──── Resend (email reminders)
                 │
          ┌──────┴──────┐
          │             │
    ┌─────▼──────┐ ┌────▼────┐
    │ PostgreSQL │ │  Redis  │
    │   (Fly.io) │ │  (opt)  │
    └────────────┘ └─────────┘
```

---

## Funzionalità

| Feature | Descrizione |
|---------|-------------|
| **Analisi AI** | Claude Haiku/Sonnet valuta compatibilità CV-annuncio (score 0-100) |
| **Gap Analysis** | Lacune strutturate con severità, colmabilità e piano d'azione |
| **Preparazione Colloquio** | Domande probabili + risposte suggerite basate sul CV |
| **Cover Letter** | Multi-lingua, context-aware (usa i risultati dell'analisi) |
| **Follow-up Email/LinkedIn** | Outreach automatizzato scalato ai giorni dalla candidatura |
| **Colloqui** | Scheduling con form dinamico (Meet/Teams/Zoom/telefono/presenza) |
| **File Upload** | Upload documenti via Cloudflare R2 con presigned URL |
| **Document Scanner** | Claude API verifica se i documenti sono compilati |
| **Email Reminder** | Resend notifica documenti non compilati |
| **Batch Analysis** | Coda multipla, elaborazione sequenziale |
| **Contatti Recruiter** | CRM per candidatura: nome, email, telefono, LinkedIn |
| **Reputazione Azienda** | Rating Glassdoor via RapidAPI con cache 30gg |
| **Cost Tracking** | Costo per analisi, totali giornalieri, budget configurabile |
| **Audit Trail** | Log DB di tutte le azioni utente |
| **Dashboard** | Statistiche, top match, candidature attive, colloqui imminenti |
| **Claude MCP** | 15 tool read-only per interrogare dati da Claude Desktop |

---

## Tech Stack

| Layer | Tecnologia |
|-------|-----------|
| **Backend** | FastAPI + Uvicorn + Jinja2 SSR |
| **ORM** | SQLAlchemy 2.0 + Alembic |
| **Database** | PostgreSQL 16 (Fly.io) |
| **Cache** | Redis 7 (opzionale, graceful degradation) |
| **AI** | Anthropic Claude API + 7-strategy JSON parsing |
| **File Storage** | Cloudflare R2 (S3-compatible, presigned URLs) |
| **Email** | Resend (reminder documenti) + SMTP (notifiche) |
| **Auth** | Session + bcrypt + rate limiting (slowapi) |
| **MCP** | FastMCP + streamable-http (15 tool read-only) |
| **CI/CD** | GitHub Actions (ruff, mypy strict, bandit, pip-audit, pytest, docker) |
| **Deploy** | Fly.io (512MB x2) + Cloudflare (DNS, R2, dominio) |

---

## Sicurezza

- Content-Security-Policy (CSP) con whitelist script/style/font/img
- Permissions-Policy (camera, microphone, geolocation negati)
- HSTS (2 anni, includeSubDomains) + X-Content-Type-Options + X-Frame-Options
- UUID validation su tutti i path parameter (anti-injection)
- Pydantic schema validation su tutti gli input (email regex, URL whitelist, enum whitelist)
- Rate limiting: 60/min globale, 10/min AI routes, 5/min login
- bcrypt password hashing + session-based auth
- TrustedHost middleware + CORS origins restrittive
- Audit trail DB per tutte le azioni utente
- Bandit security scanning + pip-audit in CI
- mypy strict su tutti i moduli (0 errori, 67 file)
- Input size limits (CV 100KB, job description 50KB)
- Budget hard stop: analisi bloccata a budget esaurito

---

## Quick Start

```bash
git clone https://github.com/MK023/JobSearch.git
cd JobSearch
cp .env.example .env
# Configura: ANTHROPIC_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d
```

Apri `http://localhost` — login con le credenziali admin.

---

## Deploy (Fly.io)

```bash
fly apps create jobsearch
fly postgres create --name jobsearch-db --region cdg
fly postgres attach jobsearch-db
fly secrets set ANTHROPIC_API_KEY=sk-ant-... SECRET_KEY=$(openssl rand -hex 32)
fly secrets set ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=your-password
fly secrets set R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... R2_ENDPOINT_URL=... R2_BUCKET_NAME=...
fly deploy
```

Le migrazioni Alembic vengono eseguite automaticamente al deploy (`release_command`).

---

## Costi

| Modello | Per analisi | Follow-up |
|---------|-------------|-----------|
| Haiku 4.5 | ~$0.005 | ~$0.001 |
| Sonnet 4.5 | ~$0.02 | ~$0.001 |

Fly.io free tier: 3 VM shared-cpu, 256MB ciascuna. R2 free tier: 10GB storage, 1M ops/mese.

---

## License

MIT
