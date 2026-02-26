# JobSearch Command Center — Redesign Brief per Claude Opus

## Contesto del progetto

**JobSearch Command Center** è un tool personale di job search potenziato da AI (Claude API).
Viene usato da un singolo utente (sviluppatore backend Python) per:
- Analizzare job posting confrontandoli con il proprio CV
- Ricevere un **match score** (0-100) e analisi dettagliata di skill match/gap
- Gestire lo stato delle candidature (Da valutare → Candidato → Colloquio → Scartato)
- Pianificare e tracciare i colloqui
- Analisi multipla di batch di offerte

Il tool è **già funzionante e mobile-ready**. Il backend non va toccato.
L'obiettivo è un **redesign completo del frontend**: stessa logica, nuova interfaccia.

**Contesto d'uso**: tool personale, ma presentato in portfolio e durante colloqui tecnici.
Il primo impatto visivo deve comunicare: precisione, cura, competenza tecnica.

---

## Problemi dell'UI attuale da risolvere

1. **Pannello CV sempre visibile** con textarea enorme — il CV viene caricato una volta e basta. Deve collassarsi in una riga "✅ Marco Bellingeri — Completo" con opzione modifica nascosta.

2. **Barra costi in header** (Crediti, Speso, Rimanente, Oggi) — informazione da developer, non da primo piano. Spostare in un menu secondario o pill discreto.

3. **"Analizza candidatura" e "Analisi multipla"** hanno lo stesso layout visivo — non è chiaro la differenza a colpo d'occhio.

4. **Emoji usate come icone** (📁🎯📊) — sostituire con icone SVG proper (Heroicons o Lucide).

5. **Troppa densità informativa** nella pagina principale — l'utente deve capire l'azione principale in <3 secondi.

6. **Pulsanti modello** (Haiku / Sonnet) esposti come bottoni separati — diventano un selector compatto.

---

## Direzione estetica: Apple-inspired Refined Dark

### Filosofia
**"Strumento professionale, non dashboard aziendale."**
Ogni elemento deve guadagnarsi il proprio spazio. Se può essere rimosso senza perdere funzionalità, va rimosso o nascosto. L'eleganza viene dalla sottrazione, non dall'aggiunta.

### Palette colori

```css
/* Dark mode principale */
--bg-primary: #0D0D0F;         /* nero quasi puro, non #000 */
--bg-secondary: #1C1C1E;       /* card background iOS dark */
--bg-tertiary: #2C2C2E;        /* input, elementi secondari */
--bg-glass: rgba(28, 28, 30, 0.85); /* glassmorphism */

/* Accenti */
--accent-blue: #0A84FF;        /* Apple blue — azioni primarie */
--accent-green: #30D158;       /* Apple green — successo, score alto */
--accent-orange: #FF9F0A;      /* Apple orange — warning, score medio */
--accent-red: #FF453A;         /* Apple red — scartato, errori */

/* Testo */
--text-primary: #F5F5F7;       /* bianco caldo Apple */
--text-secondary: #8E8E93;     /* grigio medio iOS */
--text-tertiary: #48484A;      /* grigio scuro, label disabilitate */

/* Bordi */
--border-subtle: rgba(255, 255, 255, 0.06);
--border-medium: rgba(255, 255, 255, 0.10);
```

### Tipografia

```css
/* Font stack */
font-family: 'SF Pro Display', 'SF Pro Text', -apple-system, 'Helvetica Neue', sans-serif;

/* Scale */
--text-xs: 11px;      /* label, badge */
--text-sm: 13px;      /* body secondario */
--text-base: 15px;    /* body principale */
--text-lg: 17px;      /* titoli sezione */
--text-xl: 22px;      /* titoli pagina */
--text-2xl: 28px;     /* hero number (score) */
```

### Superficie e profondità

```css
/* Card standard */
.card {
  background: var(--bg-secondary);
  border-radius: 16px;
  border: 1px solid var(--border-subtle);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
}

/* Glassmorphism (per modal, overlay) */
.glass {
  background: var(--bg-glass);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border: 1px solid var(--border-medium);
  border-radius: 16px;
}

/* Input */
.input {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  color: var(--text-primary);
  transition: border-color 0.15s ease;
}
.input:focus {
  border-color: var(--accent-blue);
  outline: none;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.15);
}
```

---

## Struttura e layout

### Layout principale
Sidebar sinistra fissa (60px icon-only, espandibile a 220px) + area contenuto principale.

**Sidebar navigation:**
- 🎯 Dashboard (home)
- ➕ Nuova analisi
- 📋 Storico candidature
- 📅 Colloqui
- ⚙️ Impostazioni (CV + crediti API qui)

### Pagina: Dashboard (home)

**Header row** (compatto, max 48px altezza):
```
Job Search Command Center    [pill: 💰 $3.07 rimanenti]   [avatar/menu]
```

**Hero section** — 3 metric card affiancate:
```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  29         │  │  17         │  │  72.4       │
│  Analizzate │  │  Candidature│  │  Score medio│
└─────────────┘  └─────────────┘  └─────────────┘
```

**Tab storico** (già presente, va raffinato):
- In valutazione | Candidature | Colloqui | Scartati
- Ogni tab con badge numerico
- Row di ogni candidatura: score ring + titolo + azienda + stato + data + azioni

### Pagina: Nuova analisi

Layout a singola colonna, focus totale sull'input.

```
[Stato CV: ✅ Marco Bellingeri — aggiorna]

┌─────────────────────────────────────────┐
│ 🔗 Link annuncio (opzionale)            │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│                                         │
│  Incolla la descrizione del lavoro...   │
│                                         │
│                                         │
└─────────────────────────────────────────┘

[Modello: ○ Haiku  ● Sonnet]    [  Analizza  →  ]
```

Il bottone Analizza è l'unico elemento prominente. Grande, blu, con freccia.

### Componente: Score Ring

L'elemento più importante visivamente — deve essere memorabile.

```
     ╭──────╮
    /  72    \      ← numero grande, bold
   │  ●●●●●○  │    ← ring SVG con progress colorato
    \         /     verde >75, arancio 50-75, rosso <50
     ╰──────╯
      Senior
    DevOps Eng      ← job title sotto
```

```css
/* Ring SVG */
.score-ring {
  width: 64px;
  height: 64px;
}
.score-ring circle {
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}
```

### Componente: Job Card (storico)

```
┌─────────────────────────────────────────────────────┐
│  [82]  DevOps Engineer                    [APPLY ↗] │
│        Azienda Italiana · Campus Brunello · ibrido  │
│        22/02 14:27                    ● DA VALUTARE │
└─────────────────────────────────────────────────────┘
```

- Click sulla card → espande il dettaglio analisi (non nuova pagina)
- Il dettaglio usa le due colonne già esistenti (skill match + gap) ma più ariose
- Bottoni stato in fondo alla card espansa: pill selezionabile

### Componente: Dettaglio analisi (espanso)

Mantieni la logica delle due colonne che funziona bene:
- **Sinistra**: Skill match (verde, lista)
- **Destra**: Gap analysis (con severità IMPORTANTE/MINORE)

Ma:
- Più whitespace tra gli item
- Niente bordi colorati pesanti sulle card gap — solo un dot colorato a sinistra
- Il consiglio AI ("IL MIO CONSIGLIO PER TE") in un box separato, tipografia leggermente più grande, come se fosse una citazione

### Componente: Modal colloquio

Il calendario date-picker è già buono. Migliorare:
- Border-radius 20px sul modal
- Backdrop blur sull'overlay
- Animazione enter: scale(0.96) → scale(1) con opacity, 200ms ease-out

---

## Micro-interazioni

```css
/* Hover su card */
.job-card {
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.job-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

/* Bottone primario */
.btn-primary {
  background: var(--accent-blue);
  transition: filter 0.15s ease, transform 0.1s ease;
}
.btn-primary:hover {
  filter: brightness(1.1);
}
.btn-primary:active {
  transform: scale(0.98);
}

/* Loading state analisi */
/* Usa uno shimmer sui campi mentre elabora, non uno spinner generico */
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
.loading {
  background: linear-gradient(90deg, 
    var(--bg-tertiary) 25%, 
    var(--bg-secondary) 50%, 
    var(--bg-tertiary) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
```

---

## Cose da NON fare

- ❌ Niente emoji come icone funzionali (ok nel testo, non come UI element)
- ❌ Niente sfondo blu navy scuro (#0f1729 e simili)
- ❌ Niente purple gradients
- ❌ Niente bordi colorati spessi sulle card
- ❌ Niente tooltip con testo lunghissimo — se serve spazio, usalo
- ❌ Non esporre i costi API in primo piano
- ❌ Non mostrare il CV textarea di default

---

## Stack tecnico atteso

> **Nota per Opus**: Prima di iniziare, leggi la struttura del progetto e identifica il framework frontend in uso (React, Vue, Jinja templates, vanilla JS). Adatta il codice di conseguenza. Se è Jinja/HTML vanilla, usa CSS custom properties e vanilla JS. Se è React, usa componenti funzionali con hooks e CSS modules o Tailwind.

Princìpi tecnici:
- Nessuna dipendenza nuova pesante se evitabile
- CSS custom properties per tutto il design token system
- SVG inline per le icone (niente icon font)
- `prefers-color-scheme` rispettato (anche se il default è dark)
- Performance: niente re-render inutili, transizioni su `transform` e `opacity` (GPU-accelerated)

---

## Priorità di implementazione

1. **Design token system** (CSS variables) — base di tutto
2. **Layout principale** (sidebar + content area)
3. **Score Ring component** — è il visual hero del progetto
4. **Job Card component** + expand/collapse dettaglio
5. **Pagina nuova analisi** semplificata
6. **Header** con pill crediti
7. **Modal colloquio** con glassmorphism
8. **Micro-interazioni** e transizioni

---

*Brief preparato per Claude Opus — eseguire il redesign mantenendo tutta la logica backend e le funzionalità esistenti invariate.*