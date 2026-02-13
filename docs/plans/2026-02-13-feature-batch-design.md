# Design: Job Search Command Center - Feature Batch

**Data:** 2026-02-13
**Approccio:** B - Server-side + Background Tasks

## Requisiti

| # | Feature | Dettaglio |
|---|---------|-----------|
| 1 | Riordino UI | Consiglio dopo Forza/Lacune, prima di Colloquio |
| 2 | Cover Letter | Sezione separata, scelta analisi + lingua, include subject line email |
| 3 | Storico a 3 tab | In valutazione / Applicato / Skippato |
| 4 | Pill azioni | Chip selezionabili con AJAX, stato evidenziato |
| 5 | Glassdoor auto-flag | Info reputazione azienda nel prompt AI |
| 6 | Batch analysis | Coda multipla con BackgroundTasks |

## 1. Riordino UI + Pill Azioni

### Nuovo ordine risultati

1. Hero (score + tags + Glassdoor badge)
2. Verdetto AI
3. Punti chiave annuncio
4. Forza + Lacune (side by side)
5. Consiglio personalizzato (spostato da posizione 2)
6. Colloquio (collassabile)
7. Pill azioni (nuovo design)

### Pill azioni

Gruppo di pill/chip che sostituiscono i 3 form POST separati:
- Da valutare (grigio) | Candidato (blu) | Colloquio (verde) | Scartato (rosso)
- Stato attuale evidenziato con background pieno
- Click -> fetch() AJAX -> aggiorna colore senza reload
- Endpoint esistente `POST /status/{id}/{status}` riutilizzato

## 2. Storico a 3 Tab

3 tab sopra la lista storico, switch via JS puro (nascondi/mostra):

- **In valutazione** -> status = da_valutare
- **Applicato** -> status in (candidato, colloquio)
- **Skippato** -> status = scartato

Counter badge su ogni tab. Tab attivo evidenziato.

## 3. Cover Letter

### UI
Nuovo card dedicato sotto il form di analisi:
- Dropdown per selezionare analisi dallo storico
- Dropdown lingua (Italiano, English, Francais, Deutsch, Espanol)
- Bottone "Genera Cover Letter"
- Risultato: testo cover letter + 2-3 subject line email
- Bottone "Copia" per ciascun elemento

### Backend
- Nuovo prompt `COVER_LETTER_PROMPT` in prompts.py
- Nuovo endpoint `POST /cover-letter`
- Nuova tabella `CoverLetter`:
  - id (UUID), analysis_id (UUID FK), language (String), content (Text)
  - subject_lines (Text JSON), model_used, tokens_input, tokens_output
  - cost_usd, created_at
- Cache Redis con chiave basata su analysis_id + language

### Prompt
Riceve: CV, annuncio, risultati analisi (score, strengths, gaps), lingua target.
Genera: cover letter professionale + 2-3 subject line email.

## 4. Glassdoor Auto-Flag

Integrato nel prompt di analisi esistente. Nuovo campo JSON:

```json
"company_reputation": {
  "glassdoor_estimate": "3.8/5",
  "known_pros": ["buon work-life balance"],
  "known_cons": ["crescita lenta"],
  "note": "Basato su informazioni pubbliche"
}
```

### UI
Badge colorato nell'hero section:
- Verde (4.0+), Giallo (3.0-3.9), Rosso (<3.0), Grigio (non disponibile)
- Tooltip/expand con pro/cons

### Limitazioni
Basato su conoscenze di Claude (training cutoff). Dichiarato nella UI.

## 5. Batch Analysis

### UI
Nuovo card "Analisi multipla":
- Textarea per aggiungere annuncio + campo URL opzionale
- Bottone "Aggiungi alla coda"
- Lista coda con preview (troncata)
- Bottone "Analizza tutti"
- Status per ogni job: in attesa / in corso / completato / errore
- Polling JS ogni 2s per aggiornamento stato

### Backend
- Stato batch in-memory (dict con UUID come batch_id)
- `POST /batch/add` -> aggiunge annuncio alla coda
- `POST /batch/run` -> avvia BackgroundTasks, processa sequenzialmente
- `GET /batch/status` -> ritorna stato corrente
- `DELETE /batch/clear` -> svuota la coda
- Ogni analisi completata viene salvata normalmente in JobAnalysis

## File coinvolti

| File | Modifiche |
|------|-----------|
| `backend/templates/index.html` | Riordino, pill, tab, cover letter UI, batch UI, glassdoor badge |
| `backend/src/app.py` | Endpoint cover-letter, batch/*, AJAX status |
| `backend/src/prompts.py` | Prompt cover letter, aggiornamento prompt analisi per glassdoor |
| `backend/src/database.py` | Tabella CoverLetter |
| `backend/src/ai_client.py` | Funzione generate_cover_letter, aggiornamento parsing per glassdoor |

## Stack
- Python 3.12, FastAPI (BackgroundTasks), SQLAlchemy, PostgreSQL, Redis
- Frontend: HTML/CSS/JS vanilla, fetch() per AJAX
