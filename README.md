# Job Search Command Center

**Your AI-powered job search companion.** Paste your CV once, then paste any job listing to get an instant compatibility analysis: score, recommendation, strengths, skill gaps, interview prep, follow-up tools, and recruiter contact management.

**Il tuo assistente AI per la ricerca lavoro.** Incolla il CV una volta, poi incolla ogni annuncio e ricevi un'analisi completa: punteggio, raccomandazione, punti di forza, lacune, preparazione colloquio, strumenti follow-up e gestione contatti recruiter.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Fly.io](https://img.shields.io/badge/Fly.io-Deploy-8B5CF6?logo=fly.io&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Features

| | English | Italiano |
|---|---|---|
| **AI Analysis** | Claude Haiku (fast) or Sonnet (deep) analyze CV-to-job compatibility | Claude Haiku (veloce) o Sonnet (approfondito) analizzano la compatibilita' |
| **Score 0-100** | With recommendation: APPLY / CONSIDER / SKIP | Con raccomandazione: APPLY / CONSIDER / SKIP |
| **Strengths** | Your matching skills highlighted with confidence | I tuoi punti di forza evidenziati |
| **Skill Gaps** | Structured by severity, closability, and action plan | Strutturate per severita', colmabilita' e piano d'azione |
| **Interview Prep** | Likely questions + suggested answers based on your CV | Domande probabili + risposte basate sul tuo CV |
| **Cover Letter** | AI-generated, multi-language, with subject lines | Generata dall'AI, multilingua, con subject line |
| **Follow-up Email** | AI-generated follow-up after application | Email di follow-up AI dopo la candidatura |
| **LinkedIn Message** | Connection note + direct message, ready to copy | Nota connessione + messaggio diretto, pronto da copiare |
| **Recruiter Contacts** | Store name, email, phone, LinkedIn per application | Salva nome, email, telefono, LinkedIn per candidatura |
| **Follow-up Alerts** | Reminds you to follow up after 5+ days | Ti ricorda di fare follow-up dopo 5+ giorni |
| **Dashboard** | Stats, top match, active applications at a glance | Statistiche, miglior match, candidature attive |
| **Batch Analysis** | Queue multiple job listings, analyze all at once | Accoda piu' annunci, analizzali tutti insieme |
| **Cost Tracking** | Per-analysis cost, daily totals, budget with remaining balance | Costo per analisi, totali giornalieri, budget con saldo |
| **Redis Cache** | Skip duplicate API calls (optional) | Evita chiamate API duplicate (opzionale) |

---

## Architecture

```
Browser ──▶ FastAPI + Jinja2 ──▶ Claude API (Haiku / Sonnet)
                │
         ┌──────┴──────┐
         │             │
    PostgreSQL 16   Redis 7
    (persistent)    (cache, optional)
```

**Stack:** Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL 16 / Redis 7 / Docker Compose / Fly.io

---

## Quick Start

### Prerequisites / Prerequisiti

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose
- An [Anthropic API key](https://console.anthropic.com/) / Una [API key Anthropic](https://console.anthropic.com/)

### Local Setup

```bash
git clone https://github.com/MK023/JobSearch.git
cd JobSearch

cp .env.example .env
# Edit .env → set your ANTHROPIC_API_KEY

docker compose up -d

open http://localhost:8000
```

### First Use / Primo utilizzo

1. **Paste your CV** in the left panel, click "Salva CV"
2. **Paste a job listing** in the right panel
3. **Pick a model** — Haiku (fast, ~$0.005) or Sonnet (deep, ~$0.02)
4. **Click "Analizza"** — wait a few seconds
5. **Read the analysis** — score, advice, strengths, gaps, interview prep
6. **Set status** — Da valutare → Candidato → Colloquio / Scartato
7. **Use tools** — Follow-up email, LinkedIn message, recruiter contacts appear for active applications

---

## Deploy on Fly.io

The app runs on Fly.io's free tier. No Redis needed in production.

```bash
cd backend

fly apps create jobsearch
fly postgres create --name jobsearch-db --region cdg --vm-size shared-cpu-1x --volume-size 1
fly postgres attach jobsearch-db

fly secrets set ANTHROPIC_API_KEY=sk-ant-...

fly deploy

fly open  # → https://jobsearch.fly.dev
```

The VM auto-sleeps when idle and wakes on first request (~2-3s cold start).

To redeploy after changes:

```bash
cd backend && fly deploy
```

---

## Cost / Costi

| Model | Input | Output | ~Cost per analysis |
|-------|-------|--------|--------------------|
| Haiku | $0.80/MTok | $4.00/MTok | ~$0.005 |
| Sonnet | $3.00/MTok | $15.00/MTok | ~$0.02 |

Follow-up emails and LinkedIn messages cost ~$0.001 each (Haiku).

Cost tracking is built into the UI: budget, spent, remaining, daily breakdown.

---

## Project Structure

```
JobSearch/
├── docker-compose.yml          # PostgreSQL + Redis + Backend
├── .env.example                # Environment variables template
└── backend/
    ├── Dockerfile
    ├── fly.toml                # Fly.io deployment config
    ├── requirements.txt
    ├── templates/
    │   └── index.html          # Single-page UI (Jinja2)
    ├── static/
    │   ├── css/style.css
    │   └── js/app.js
    └── src/
        ├── app.py              # FastAPI routes + business logic
        ├── config.py           # Pydantic settings
        ├── database.py         # SQLAlchemy models + migrations
        ├── ai_client.py        # Anthropic client + Redis cache
        └── prompts.py          # System prompts (analysis, cover letter, follow-up, LinkedIn)
```

---

## Development / Sviluppo

```bash
# Live logs
docker compose logs -f backend

# Rebuild after Dockerfile changes
docker compose up -d --build

# Direct DB access
psql postgresql://jobsearch:jobsearch@localhost:5432/jobsearch

# Stop
docker compose down

# Stop and delete all data
docker compose down -v
```

The backend runs with `--reload` locally — Python and template changes apply instantly.

---

## License

MIT
