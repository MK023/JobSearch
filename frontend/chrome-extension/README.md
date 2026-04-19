# JobSearch Inbox — Chrome Extension

Estensione Chrome Manifest V3 che invia il testo di un annuncio di lavoro (copy-paste o auto-capture dal DOM della pagina attiva) all'endpoint `POST /api/v1/inbox` della tua istanza JobSearch self-hosted. Il backend dedupa, lancia l'analisi AI in background, e apre l'analisi nel tuo storico pronta da valutare.

## Install (locale, non-Chrome-Web-Store)

1. Apri `chrome://extensions`
2. Attiva **Developer mode** (toggle in alto a destra)
3. Click **Load unpacked** → seleziona questa cartella (`frontend/chrome-extension/`)
4. L'icona con i 5 petali ember appare nella barra estensioni

## Prima configurazione

1. Click sull'icona → popup si apre
2. Click sull'ingranaggio ⚙ → pannello Impostazioni
3. Inserisci:
   - **Endpoint**: default `https://www.jobsearches.cc` (modificabile se usi un dominio diverso)
   - **API Key**: la stessa chiave che usi nel cron `weekly-cleanup.yml` e nel server MCP (vedi la tua `.env`, variabile `API_KEY`)
4. **Salva** → le credenziali restano in `chrome.storage.sync` (cifrate da Chrome, sincronizzate tra i tuoi dispositivi)

## Uso quotidiano

**LinkedIn** (ToS: no scraping → paste manuale):
1. Apri l'annuncio → seleziona e copia il corpo
2. Click icona extension → incolla nel textarea
3. Click **Invia** (o `Cmd/Ctrl+Enter`)

**Indeed, InfoJobs, WTTJ, RemoteOK** (auto-capture):
1. Apri l'annuncio
2. Click icona extension → **Auto-capture**
3. Il popup legge `document.body.innerText` della tab attiva via `chrome.scripting.executeScript`
4. Rivedi il testo (puoi editarlo) → **Invia**

## Sicurezza

- **Permissions minimal**: `activeTab` (solo quando clicchi l'estensione), `storage` (per l'API key), `scripting` (solo al click di Auto-capture). Niente `<all_urls>` né background worker always-on.
- **Host permissions**: solo `jobsearches.cc` — l'extension non può parlare con altri server.
- **Backend gate**: l'endpoint `/api/v1/inbox` ha 10 validation checks indipendenti (domain whitelist, HTML strip, unicode normalize, rate limit, quota, dedup, ecc.). Non si fida del client.
- **API Key**: sempre in header (`X-API-Key`), mai in URL. Storage lato Chrome cifrato.
- **HTTPS-only**: endpoint hardcoded `https://`.

## Limitazioni note

- **LinkedIn Auto-capture non funziona** intenzionalmente: ToS LinkedIn vieta estrazione automatica. Manual paste only su LinkedIn.
- **Max 50.000 caratteri** per annuncio (limite backend). Testi più lunghi vengono troncati prima dell'invio.
- **Rate limit backend**: 20 invii/ora per API key. Sopra → 429.
- **Dedup**: se lo stesso testo è stato già analizzato con Haiku, il backend riusa l'analisi esistente (nessuna seconda chiamata AI, risposta `dedup=true`).

## Keyboard shortcuts

- `Cmd/Ctrl+Enter` = Invia (quando il testo ≥ 50 caratteri)
- `Esc` = Chiudi pannello Impostazioni

## Aggiornare le icone

Le 3 icone PNG (`icons/icon-{16,48,128}.png`) sono generate da `generate_icons.py` partendo dal motivo dei 5 petali ember — lo stesso del favicon del sito (`frontend/static/favicon.svg`). Per rigenerarle dopo una modifica visuale:

```bash
cd frontend/chrome-extension
python3 generate_icons.py
```

Richiede `Pillow` (`pip install Pillow`).

## Troubleshooting

| Sintomo | Causa probabile | Fix |
|---------|----------------|-----|
| "API Key mancante" | Prima installazione o key cancellata | Apri Impostazioni, reinserisci |
| "Errore di rete" | Backend down o offline | Controlla `https://www.jobsearches.cc/health` |
| "host not in allowlist" | Auto-capture su sito non nella whitelist backend | Paste manuale + source = "Altro" |
| 429 "rate limit" | Troppi invii/ora | Attendi 60 minuti |
| 401 + redirect 303 | API Key sbagliata | Verifica la key in Impostazioni |
| Auto-capture non trova testo | Pagina SPA lento-caricamento o protetta | Paste manuale |

## Architettura (riepilogo)

```
┌──────────────┐  HTTPS+JSON  ┌─────────────────┐
│ Chrome popup │─────────────▶│ FastAPI /inbox  │
│ (~5 MB RAM)  │  X-API-Key   │ 10 val. gates   │
│ vanilla JS   │              │ inbox_items DB  │
└──────────────┘              │      ↓ async    │
                              │ analyze_job()   │
                              │      ↓          │
                              │ job_analyses    │
                              │      ↓          │
                              │ /history UI     │
                              └─────────────────┘
```

Zero parsing client-side: il popup invia il raw text. Il parsing tecnico (azienda, ruolo, skill, score, career_track, ecc.) è fatto dall'AI server-side usando lo stesso prompt v7 del flusso web normale.
