# JobSearch UI Redesign — Design Document

**Data**: 2026-02-26
**Stato**: Approvato
**Approccio**: Rewrite in-place su branch `redesign`

---

## 1. Contesto

JobSearch Command Center è un tool personale di job search potenziato da AI (Claude API). Il frontend attuale è Flask/Jinja2 + Alpine.js + vanilla JS, single-page con container centrato. L'obiettivo è un redesign completo dell'interfaccia mantenendo backend e API invariati.

Stack esistente: FastAPI, Jinja2 templates, Alpine.js 3.14.8, Flatpickr 4.6.13, 5 file CSS puri, 7 moduli JS vanilla. Nessun build step.

---

## 2. Decisioni di design

| # | Decisione | Scelta |
|---|-----------|--------|
| 1 | Routing | Ibrido: route Flask per pagine, Alpine per interazioni locali |
| 2 | Dashboard vs Storico | Dashboard leggera (metriche + 5 recenti), storico su pagina dedicata |
| 3 | Pagina Colloqui | Prossimi con prep scripts + passati collassati |
| 4 | Impostazioni | Minimalista: solo CV + crediti API |
| 5 | Batch analysis | Tab Singola/Multipla nella pagina "Nuova analisi" |
| 6 | Cover letter / follow-up | Alert in dashboard, azioni nel dettaglio candidatura |
| 7 | Icone | SVG inline custom, nessuna dipendenza |
| 8 | Transizioni pagina | CSS fade 150ms sul body |
| 9 | Approccio implementazione | Rewrite in-place su branch `redesign` |

---

## 3. Architettura e routing

### Route Flask

```
GET /                     → dashboard.html      (home, metriche + preview + alert)
GET /analyze              → analyze.html         (tab Singola/Multipla)
GET /history              → history.html         (storico completo, 4 tab stato)
GET /interviews           → interviews.html      (prossimi con prep + passati collassati)
GET /settings             → settings.html        (CV + crediti API)
GET /analysis/{id}        → analysis_detail.html (dettaglio singola candidatura)
GET /login                → login.html           (invariato)
```

### Struttura template

```
templates/
├── base.html                 ← sidebar + content wrapper + fade CSS
├── dashboard.html            ← extends base
├── analyze.html              ← extends base
├── history.html              ← extends base
├── interviews.html           ← extends base
├── settings.html             ← extends base
├── analysis_detail.html      ← extends base
├── login.html                ← standalone (no sidebar)
├── 404.html                  ← extends base
├── 500.html                  ← extends base
└── partials/
    ├── sidebar.html          ← nav icon + label
    ├── metric_card.html      ← card metrica riusabile
    ├── score_ring.html       ← SVG ring component
    ├── job_card.html         ← card candidatura compatta
    ├── job_detail.html       ← dettaglio espanso (strengths/gaps/advice)
    ├── cover_letter_form.html
    ├── cover_letter_result.html
    ├── interview_modal.html
    ├── interview_card.html   ← card colloquio con prep
    ├── followup_alerts.html
    ├── batch_form.html
    └── contacts_panel.html
```

### Struttura CSS

```
static/css/
├── variables.css      ← nuova palette Apple dark, nuovi token
├── base.css           ← reset + fade animation + tipografia
├── components.css     ← card, btn, pill, badge, input, score-ring, modal, toast
├── layout.css         ← sidebar + content area + grid responsive
└── sections.css       ← stili specifici per ogni pagina
```

### JS — cambiamenti minimi

I moduli JS restano quasi identici. Cambiamenti:
- `app.js`: init condizionale (carica solo i moduli necessari per la pagina corrente)
- Nuova funzione globale `showToast(message, type)` per feedback AJAX
- Selettori DOM aggiornati dove necessario
- Nessun nuovo framework JS

---

## 4. Direzione estetica: Apple-inspired Refined Dark

### Palette colori

```css
--bg-primary: #0D0D0F;
--bg-secondary: #1C1C1E;
--bg-tertiary: #2C2C2E;
--bg-glass: rgba(28, 28, 30, 0.85);

--accent-blue: #0A84FF;
--accent-green: #30D158;
--accent-orange: #FF9F0A;
--accent-red: #FF453A;

--text-primary: #F5F5F7;
--text-secondary: #8E8E93;
--text-tertiary: #48484A;

--border-subtle: rgba(255, 255, 255, 0.06);
--border-medium: rgba(255, 255, 255, 0.10);
```

### Tipografia

```css
font-family: 'SF Pro Display', 'SF Pro Text', -apple-system, 'Helvetica Neue', sans-serif;

--text-xs: 11px;
--text-sm: 13px;
--text-base: 15px;
--text-lg: 17px;
--text-xl: 22px;
--text-2xl: 28px;
```

### Superficie e profondita

```css
/* Card */
background: var(--bg-secondary);
border-radius: 16px;
border: 1px solid var(--border-subtle);
box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);

/* Glassmorphism (modal) */
background: var(--bg-glass);
backdrop-filter: blur(24px) saturate(180%);
border-radius: 20px;

/* Input */
background: var(--bg-tertiary);
border-radius: 10px;
focus: border-color accent-blue + ring 3px
```

---

## 5. Layout e sidebar

### Desktop

- Sidebar fissa 60px, solo icone SVG
- Hover su icona: tooltip con label
- Pagina attiva: icona accent-blue + barra verticale 3px a sinistra
- Settings ancorata in basso, separata dalle altre 4
- Content area: max-width 960px, centrata, padding 32px

### Mobile (≤768px)

- Sidebar diventa bottom bar orizzontale, 56px altezza
- 5 icone equidistanziate
- Pagina attiva: dot sotto icona
- Content area: padding 16px, full width

### Voci sidebar

1. Dashboard (home)
2. Nuova analisi
3. Storico candidature
4. Colloqui
5. Impostazioni (in basso)

---

## 6. Componenti chiave

### Score Ring (SVG)

```svg
<svg viewBox="0 0 72 72">
  <circle cx="36" cy="36" r="30" stroke="var(--bg-tertiary)" stroke-width="5" fill="none"/>
  <circle cx="36" cy="36" r="30" stroke="var(--score-color)" stroke-width="5" fill="none"
          stroke-dasharray="188.5" stroke-dashoffset="CALC" stroke-linecap="round"
          transform="rotate(-90 36 36)"/>
  <text x="36" y="40" text-anchor="middle">SCORE</text>
</svg>
```

- Colore: green ≥75, orange 50-74, red <50
- Animazione: stroke-dashoffset 0.6s cubic-bezier
- Due dimensioni: 64px (lista) e 96px (dettaglio)

### Job Card

```
┌─────────────────────────────────────────────────────────┐
│  ◯72   DevOps Engineer              22 feb · 14:27      │
│        Azienda Italiana · ibrido       ● DA VALUTARE    │
└─────────────────────────────────────────────────────────┘
```

- Flex row: score ring | info | metadata
- Hover: translateY(-1px) + ombra profonda
- Click: naviga a `/analysis/{id}`

### Metric Card

```
┌─────────────┐
│  29          │  ← --text-2xl, bold
│  Analizzate  │  ← --text-sm, --text-secondary
└─────────────┘
```

- 3 card affiancate desktop, impilate mobile

### Modal

- Overlay: rgba(0,0,0,0.5) + backdrop-filter blur(8px)
- Content: bg-secondary, border-radius 20px
- Animazione: scale(0.96)→scale(1) + opacity, 200ms ease-out

### Bottoni

- Primario: accent-blue, radius 10px. Hover: brightness(1.1). Active: scale(0.98)
- Secondario: trasparente, bordo border-medium. Hover: bg-tertiary
- Pill stato: radius full, sfondo tenue del colore stato

### Toast notification

- Fixed, bottom-right, z-index alto
- slideUp + fadeIn, auto-dismiss 3s
- Varianti: success (verde), error (rosso), info (blu)
- Funzione globale `showToast(message, type)`

---

## 7. Flusso dati per pagina

### Dashboard (`GET /`)

**Backend passa:** dashboard stats, spending, recent_analyses[:5], followup_alerts, upcoming_interviews.

**Renderizza:**
1. Header: titolo + pill crediti
2. 3 metric card
3. Follow-up alerts (se presenti)
4. Upcoming interviews banner (se presenti)
5. Ultime 5 job card → click a `/analysis/{id}`
6. Link "Vedi tutto lo storico →"

**JS:** spending.js, dashboard.js, followup.js

### Nuova Analisi (`GET /analyze`)

**Backend passa:** cv status, spending, batch_items.

**Renderizza:**
1. Banner CV stato (link a `/settings`)
2. Toggle: Singola | Multipla
3. Singola: URL input + textarea + model selector + bottone "Analizza →"
4. Multipla: coda batch con add/run/clear

**Submit:** POST /analyze → redirect a `/analysis/{id}`
**JS:** batch.js, cv.js

### Dettaglio Analisi (`GET /analysis/{id}`)

**Backend passa:** result, analysis, cover_letter, interview, contacts.

**Renderizza:**
1. Hero: Score Ring 96px + ruolo + azienda + recommendation
2. Tags: location, work mode, salary, confidence
3. Company reputation (se presente)
4. AI verdict + job summary
5. 2 colonne: strengths | gaps
6. Advice box (stile citazione)
7. Interview section (se schedulato) + prep scripts
8. Cover letter (form + risultato)
9. Azioni: link annuncio, pill stato, contatti, elimina
10. Interview modal (hidden)

**JS:** status.js, interview.js, followup.js, contacts.js

### Storico (`GET /history`)

**Backend passa:** analyses (tutte), counts per stato.

**Renderizza:**
1. 4 tab con badge numerici
2. Lista job card filtrate
3. Click → `/analysis/{id}`

**JS:** history.js, status.js

### Colloqui (`GET /interviews`)

**Backend passa:** upcoming (con prep scripts), past.

**Renderizza:**
1. Prossimi: card con data/ora, ruolo, tipo, recruiter, prep Q&A espandibili
2. Passati: sezione `<details>` collassata

**JS:** interview.js

### Impostazioni (`GET /settings`)

**Backend passa:** cv, spending.

**Renderizza:**
1. CV: stato + modifica espandibile + upload/download
2. Crediti: budget editabile + totali + oggi

**JS:** cv.js, spending.js

---

## 8. Stati vuoti e gestione errori

### Stati vuoti

| Pagina | Messaggio |
|--------|-----------|
| Dashboard | Metriche a zero + "Analizza la tua prima offerta →" link a /analyze |
| Storico | Tab a (0) + "Nessuna candidatura trovata" |
| Colloqui | "Nessun colloquio pianificato" |
| Impostazioni | CV mancante: textarea espansa con "Carica il tuo CV per iniziare" |

### Errori

| Scenario | Comportamento |
|----------|---------------|
| Analisi fallita | Redirect a /analyze + banner rosso |
| Rate limit 429 | Banner amber + bottone disabilitato 10s |
| Budget esaurito | Pill rossa + avviso inline + bottone disabilitato |
| Rete assente | Toast "Connessione persa" auto-dismiss 5s |
| 404 / 500 | Pagina con sidebar + messaggio centrato |

### Loading states

| Azione | Feedback |
|--------|----------|
| Analisi | Bottone shimmer + "Analizzando...", textarea disabilitata |
| Batch | Shimmer individuale per item |
| Cover letter | Bottone shimmer + "Generando..." |
| Follow-up | Bottone shimmer, risultato fadeIn |
| Cambio pagina | Fade CSS 150ms |

---

## 9. Micro-interazioni

```css
/* Card hover */
.job-card { transition: transform 0.15s ease, box-shadow 0.15s ease; }
.job-card:hover { transform: translateY(-1px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }

/* Bottone primario */
.btn-primary { transition: filter 0.15s ease, transform 0.1s ease; }
.btn-primary:hover { filter: brightness(1.1); }
.btn-primary:active { transform: scale(0.98); }

/* Shimmer loading */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
.loading {
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-secondary) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

/* Modal enter */
@keyframes modalEnter {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}

/* Page fade */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
body { animation: fadeIn 150ms ease; }
```

---

## 10. Cosa NON cambia

- Backend: zero modifiche alla logica
- API endpoints: tutti i `/api/v1/*` invariati
- Alpine.js: resta come framework reattivo
- Flatpickr: resta per date picker
- JS modules: stessa architettura, adattamenti minimi ai selettori DOM
- Auth: stesso flusso login/session
- Database: invariata

## 11. Nuove route backend

```python
GET /analyze      → render analyze.html
GET /history      → render history.html
GET /interviews   → render interviews.html
GET /settings     → render settings.html
```

Le route esistenti (POST /analyze, POST /cv, POST /cover-letter, ecc.) restano. Redirect aggiornati (es. POST /analyze → redirect a /analysis/{id}).

## 12. Vincoli tecnici

- Nessuna dipendenza nuova pesante
- CSS custom properties per tutto il design token system
- SVG inline per icone
- `prefers-color-scheme` rispettato (default dark)
- Transizioni su transform e opacity (GPU-accelerated)
- No build step
