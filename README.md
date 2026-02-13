# 🎯 Job Search Command Center

Analizza le tue candidature con l'intelligenza artificiale. Incolla il tuo CV una volta, poi incolla ogni annuncio di lavoro e ricevi un'analisi completa: score di compatibilità, raccomandazione (APPLY / CONSIDER / SKIP), punti di forza, aree di crescita e preparazione al colloquio.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Funzionalità

- **🤖 Analisi AI** — Claude Haiku (veloce) o Sonnet (approfondito) analizzano la compatibilità CV ↔ annuncio
- **📊 Score 0-100** con raccomandazione 🚀 APPLY / 🤔 CONSIDER / ⛔ SKIP
- **💪 Punti di forza** evidenziati per darti fiducia
- **🌱 Aree di crescita** strutturate con severità, colmabilità e piano d'azione
- **🎤 Preparazione colloquio** con domande probabili e risposte suggerite basate sul tuo CV
- **💡 Consiglio personalizzato** che spiega il perché della valutazione
- **📈 Score potenziale** e timeline per colmare le lacune
- **💰 Tracking costi** per ogni analisi e saldo rimanente
- **⚡ Cache Redis** per evitare analisi duplicate
- **📚 Storico** cliccabile con gestione stato candidatura

## 🏗️ Architettura

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Browser    │────▶│   FastAPI     │────▶│  Claude API  │
│  (HTML/CSS)  │◀────│  + Jinja2     │◀────│ Haiku/Sonnet │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────┴───────┐
                    │              │
               ┌────▼────┐  ┌─────▼────┐
               │ Postgres │  │  Redis   │
               │   16     │  │    7     │
               └──────────┘  └──────────┘
```

**Stack:** Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL 16 · Redis 7 · Docker Compose

## 🚀 Quick Start

### Prerequisiti

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose
- Una [API key Anthropic](https://console.anthropic.com/)

### Setup

```bash
# 1. Clona il repo
git clone https://github.com/marcobellingeri/JobSearch.git
cd JobSearch

# 2. Configura le variabili d'ambiente
cp .env.example .env
# Modifica .env e inserisci la tua ANTHROPIC_API_KEY

# 3. Avvia tutto
docker compose up -d

# 4. Apri nel browser
open http://localhost:8000
```

### Primo utilizzo

1. **Incolla il tuo CV** nel pannello sinistro e clicca "Salva CV"
2. **Incolla un annuncio di lavoro** nel pannello destro
3. **Scegli il modello** (🐇 Haiku per velocità, 🧠 Sonnet per profondità)
4. **Clicca "Analizza"** e attendi qualche secondo
5. **Leggi l'analisi**: score, consiglio, punti di forza, lacune, prep colloquio

## 💶 Costi

| Modello | Input | Output | ~Costo per analisi |
|---------|-------|--------|-------------------|
| 🐇 Haiku | $0.80/MTok | $4.00/MTok | ~$0.005 |
| 🧠 Sonnet | $3.00/MTok | $15.00/MTok | ~$0.02 |

Il tracking dei costi è integrato nella UI: vedi quanto spendi per ogni analisi e il saldo rimanente.

## 📁 Struttura progetto

```
JobSearch/
├── docker-compose.yml       # PostgreSQL + Redis + Backend
├── .env.example             # Template variabili d'ambiente
├── ROADMAP.md               # Feature in arrivo
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    ├── templates/
    │   └── index.html       # UI single-page
    └── src/
        ├── app.py           # FastAPI routes
        ├── config.py        # Pydantic settings
        ├── database.py      # SQLAlchemy models
        ├── ai_client.py     # Anthropic client + cache
        └── prompts.py       # System prompts
```

## 🔧 Sviluppo

```bash
# Logs in tempo reale
docker compose logs -f backend

# Riavvia dopo modifiche al Dockerfile
docker compose up -d --build

# Accesso diretto al DB
psql postgresql://jobsearch:jobsearch@localhost:5432/jobsearch

# Stop
docker compose down

# Stop e cancella i dati
docker compose down -v
```

Il backend gira con `--reload`, quindi le modifiche ai file Python e ai template vengono applicate automaticamente.

## 📝 License

MIT
