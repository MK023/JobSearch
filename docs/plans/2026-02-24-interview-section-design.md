# Design: Sezione Colloqui + Revisione Logica Status

**Data:** 2026-02-24
**Stato:** Approvato

## Problema

L'applicazione ha 4 status nel modello (`da_valutare`, `candidato`, `colloquio`, `scartato`) ma la UI raggruppa `candidato` e `colloquio` nello stesso tab "Candidature". Non esiste:
- Un tab dedicato ai colloqui nella history
- Una funzionalità di prenotazione/scheduling colloquio
- Una sezione dettaglio colloquio nella pagina candidatura
- Un banner per colloqui imminenti

## Decisioni prese

1. **4 tab separati** nella history: Da valutare | Candidature | Colloqui | Scartati
2. **Flow unico**: click su pill "Colloquio" apre modale con form prenotazione
3. **Sezione dettaglio** nella pagina candidatura, sotto info azienda, sopra cover letter
4. **Banner imminenti** in dashboard per colloqui nelle prossime 48h
5. **Mobile-first** per tutto il nuovo codice
6. **Campi opzionali**: solo data/ora inizio e FK sono obbligatori

## Nuovo modello: Interview

```
interviews
├── id (UUID, PK)
├── analysis_id (UUID, FK -> job_analyses, NOT NULL, UNIQUE)
├── scheduled_at (TIMESTAMP WITH TZ, NOT NULL)
├── ends_at (TIMESTAMP WITH TZ, NULL)
├── interview_type (VARCHAR: virtual/phone/in_person, NULL)
├── recruiter_name (VARCHAR, NULL)
├── recruiter_email (VARCHAR, NULL)
├── meeting_link (VARCHAR, NULL)
├── phone_number (VARCHAR, NULL)
├── phone_pin (VARCHAR, NULL)
├── location (VARCHAR, NULL)
├── notes (TEXT, NULL)
├── created_at (TIMESTAMP)
├── updated_at (TIMESTAMP)
```

Relazione 1:1 con JobAnalysis (UNIQUE su analysis_id).

## Flusso status

```
          ┌──────────────┐
          │  DA VALUTARE  │  (stato iniziale)
          └──────┬───────┘
       ┌─────────┼──────────┐
       ▼         ▼          ▼
  CANDIDATO   COLLOQUIO   SCARTATO
       │         ▲
       └─────────┘  (bidirezionale)
```

- Qualsiasi stato -> qualsiasi stato (flessibilita reale)
- Click "Colloquio" -> modale form -> status cambia solo se conferma
- Uscita da "Colloquio" -> dati colloquio restano nel DB, sezione nascosta
- `applied_at` settato alla prima transizione verso CANDIDATO o COLLOQUIO

## History: 4 tab

| Tab | Status filtrato | Icona |
|-----|----------------|-------|
| Da valutare | da_valutare | magnifier |
| Candidature | candidato | envelope |
| Colloqui | colloquio | speech |
| Scartati | scartato | cross |

Mobile: scroll orizzontale sui tab.

## Modale prenotazione colloquio

- Si apre al click su pill "Colloquio"
- Campo obbligatorio: data/ora inizio
- Campi opzionali: ora fine, tipo, recruiter, email, link meet, telefono, PIN, luogo, note
- "Conferma" -> POST backend -> status + interview creati
- "Annulla" -> niente cambia
- Se interview esiste gia: form pre-popolato per modifica

## Sezione dettaglio nella pagina candidatura

Posizione: sotto info azienda, sopra cover letter.
Mostra solo i campi compilati. Bottoni "Modifica" (riapre modale) e "Rimuovi" (cancella interview, status torna a candidato).

## Banner colloqui imminenti

In cima alla dashboard per colloqui nelle prossime 48h.
Stile lime/green coerente con colore colloquio.
Link diretto al dettaglio della candidatura.
Multipli banner se piu colloqui.

## Endpoint API necessari

- `POST /api/v1/interviews/{analysis_id}` - Crea/aggiorna interview
- `GET /api/v1/interviews/{analysis_id}` - Dettaglio interview
- `DELETE /api/v1/interviews/{analysis_id}` - Rimuovi interview
- `GET /api/v1/interviews/upcoming` - Colloqui prossime 48h (per banner)
