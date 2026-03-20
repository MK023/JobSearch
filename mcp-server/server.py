"""JobSearch MCP Server — tools for querying and managing job candidature data."""

import asyncio
import logging
import os
import threading

from api_client import (
    _WAKE_TIMEOUT,
    api_delete,
    api_get,
    api_post,
    api_post_json,
)
from mcp.server.fastmcp import FastMCP

from config import settings

# Use stdio for Claude Desktop (local), streamable-http for remote deployment
_transport = os.environ.get("MCP_TRANSPORT", "stdio")

mcp = FastMCP(
    "JobSearch",
    **({"stateless_http": True, "host": settings.mcp_host, "port": settings.mcp_port} if _transport != "stdio" else {}),
)


# ── Backend Health ─────────────────────────────────────────────────


@mcp.tool()
async def wake_backend() -> dict:
    """Sveglia il backend Fly.io e verifica che sia pronto.

    Chiama GET /health per forzare il wake-up della macchina.
    Usare PRIMA di un batch per evitare timeout da cold start.
    Ritorna: status, db, uptime.
    """
    return await api_get("/health", timeout=_WAKE_TIMEOUT)


# ── Candidature ─────────────────────────────────────────────────────


@mcp.tool()
async def get_candidature(status: str | None = None, limit: int = 50) -> dict:
    """Lista candidature. Filtra per stato: da_valutare, candidato, colloquio, scartato."""
    params: dict = {"limit": limit}
    if status:
        params["status"] = status
    return await api_get("/api/v1/candidature", params)


@mcp.tool()
async def search_candidature(query: str, limit: int = 20) -> dict:
    """Cerca candidature per azienda o ruolo."""
    return await api_get("/api/v1/candidature/search", {"q": query, "limit": limit})


@mcp.tool()
async def get_candidature_detail(analysis_id: str) -> dict:
    """Dettaglio completo di una candidatura: score, gaps, strengths, advice, azienda."""
    return await api_get(f"/api/v1/candidature/{analysis_id}")


@mcp.tool()
async def get_top_candidature(limit: int = 10) -> dict:
    """Le candidature con score piu' alto (escluse le scartate)."""
    return await api_get("/api/v1/candidature/top", {"limit": limit})


@mcp.tool()
async def get_candidature_by_date_range(date_from: str, date_to: str) -> dict:
    """Candidature create in un periodo. Formato date: YYYY-MM-DD."""
    return await api_get("/api/v1/candidature/date-range", {"date_from": date_from, "date_to": date_to})


@mcp.tool()
async def get_stale_candidature(days: int = 7) -> dict:
    """Candidature ferme senza aggiornamenti da N giorni."""
    return await api_get("/api/v1/candidature/stale", {"days": days})


# ── Colloqui ────────────────────────────────────────────────────────


@mcp.tool()
async def get_upcoming_interviews(days: int = 7) -> list:
    """Colloqui programmati nei prossimi N giorni con dettagli azienda."""
    return await api_get("/api/v1/interviews-upcoming", {"days": days})


@mcp.tool()
async def get_interview_prep(analysis_id: str) -> dict:
    """Preparazione colloquio: strengths, gaps, domande suggerite, advice."""
    return await api_get(f"/api/v1/interview-prep/{analysis_id}")


# ── Cover Letter ────────────────────────────────────────────────────


@mcp.tool()
async def get_cover_letter(analysis_id: str) -> dict:
    """Recupera la lettera di presentazione per una candidatura."""
    return await api_get(f"/api/v1/cover-letters/{analysis_id}")


# ── Contatti ────────────────────────────────────────────────────────


@mcp.tool()
async def search_contacts(query: str, limit: int = 20) -> dict:
    """Cerca contatti recruiter per nome, azienda o email."""
    return await api_get("/api/v1/contacts/search", {"q": query, "limit": limit})


# ── Dashboard & Follow-up ──────────────────────────────────────────


@mcp.tool()
async def get_dashboard_stats() -> dict:
    """Riepilogo generale: candidature totali, colloqui, scartate, score medio."""
    return await api_get("/api/v1/dashboard")


@mcp.tool()
async def get_spending() -> dict:
    """Costi API: budget, speso oggi, speso totale, token usati."""
    return await api_get("/api/v1/spending")


@mcp.tool()
async def get_pending_followups() -> dict:
    """Candidature che aspettano un follow-up."""
    return await api_get("/api/v1/followups/pending")


@mcp.tool()
async def get_activity_summary(days: int = 7) -> dict:
    """Riepilogo attivita' degli ultimi N giorni: nuove candidature, colloqui, score medio."""
    return await api_get("/api/v1/activity-summary", {"days": days})


# ── Batch Analysis ─────────────────────────────────────────────────


@mcp.tool()
async def batch_clear() -> dict:
    """Svuota la coda batch corrente. Chiamare prima di iniziare un nuovo batch."""
    return await api_delete("/api/v1/batch/clear")


@mcp.tool()
async def batch_add(job_description: str, job_url: str = "", model: str = "haiku") -> dict:
    """Aggiunge una job description alla coda batch per analisi.

    Args:
        job_description: Testo completo della job description.
        job_url: URL dell'offerta (opzionale, per riferimento).
        model: Modello AI da usare: "haiku" (economico) o "opus" (preciso).
    """
    return await api_post(
        "/api/v1/batch/add",
        data={"job_description": job_description, "job_url": job_url, "model": model},
    )


_batch_logger = logging.getLogger("batch_local")

# Background batch state (survives across tool calls within the same MCP process)
_batch_thread: threading.Thread | None = None


def _run_batch_sync(items: list, cv_text: str, batch_id: str) -> None:
    """Process batch items synchronously in a background thread."""
    import contextlib

    from anthropic_client import analyze_job as local_analyze

    loop = asyncio.new_event_loop()

    for i, item in enumerate(items, 1):
        item_id = item["id"]

        # Mark as running
        loop.run_until_complete(api_post(f"/api/v1/batch/item/{item_id}/status", data={"status": "running"}))

        try:
            # Check dedup
            dedup = loop.run_until_complete(
                api_get(
                    "/api/v1/analysis/check-dedup",
                    {"content_hash": item["content_hash"], "model_id": item["model_id"]},
                )
            )

            if dedup.get("exists"):
                loop.run_until_complete(
                    api_post(
                        f"/api/v1/batch/item/{item_id}/status",
                        data={"status": "skipped", "analysis_id": dedup["analysis_id"]},
                    )
                )
                _batch_logger.info("Item %d/%d: skipped (dedup)", i, len(items))
                continue

            # Analyze locally
            result = local_analyze(cv_text, item["job_description"], item.get("model", "haiku"))

            # Save to backend
            import_data = {
                "job_description": item["job_description"],
                "job_url": item.get("job_url", ""),
                "content_hash": item["content_hash"],
                "job_summary": result.get("job_summary", ""),
                "company": result.get("company", ""),
                "role": result.get("role", ""),
                "location": result.get("location", ""),
                "work_mode": result.get("work_mode", ""),
                "salary_info": result.get("salary_info", ""),
                "score": result.get("score", 0),
                "recommendation": result.get("recommendation", ""),
                "strengths": result.get("strengths", []),
                "gaps": result.get("gaps", []),
                "interview_scripts": result.get("interview_scripts", []),
                "advice": result.get("advice", ""),
                "company_reputation": result.get("company_reputation", {}),
                "full_response": result.get("full_response", ""),
                "model_used": result.get("model_used", ""),
                "tokens_input": result.get("tokens", {}).get("input", 0),
                "tokens_output": result.get("tokens", {}).get("output", 0),
                "cost_usd": result.get("cost_usd", 0.0),
            }

            import_resp = loop.run_until_complete(api_post_json("/api/v1/analysis/import", import_data))

            loop.run_until_complete(
                api_post(
                    f"/api/v1/batch/item/{item_id}/status",
                    data={"status": "done", "analysis_id": import_resp.get("analysis_id", "")},
                )
            )

            _batch_logger.info(
                "Item %d/%d: done — %s @ %s, score=%s",
                i,
                len(items),
                result.get("role", "?"),
                result.get("company", "?"),
                result.get("score", 0),
            )

        except Exception as exc:
            with contextlib.suppress(Exception):
                loop.run_until_complete(
                    api_post(
                        f"/api/v1/batch/item/{item_id}/status",
                        data={"status": "error", "error_message": str(exc)},
                    )
                )
            _batch_logger.error("Item %d/%d: error — %s", i, len(items), exc)

    loop.close()


@mcp.tool()
async def batch_run() -> dict:
    """Avvia l'elaborazione del batch IN LOCALE in background.

    Lancia l'analisi e ritorna SUBITO — non blocca.
    Usa batch_status() per monitorare il progresso, batch_results() per i risultati.
    """
    global _batch_thread

    if _batch_thread and _batch_thread.is_alive():
        return {
            "status": "already_running",
            "message": "Batch gia' in elaborazione. Usa batch_status() per il progresso.",
        }

    # Get pending items + CV from backend
    resp = await api_get("/api/v1/batch/pending-items")
    items = resp.get("items", [])
    cv_text = resp.get("cv_text", "")
    batch_id = resp.get("batch_id", "")

    if not items:
        return {"status": "empty", "message": "Nessun item pending nel batch"}
    if not cv_text:
        return {"status": "error", "message": "Nessun CV trovato sul backend"}

    # Launch background thread (won't be killed by MCP tool timeout)
    _batch_thread = threading.Thread(
        target=_run_batch_sync,
        args=(items, cv_text, batch_id),
        daemon=True,
        name="batch_local",
    )
    _batch_thread.start()

    return {
        "status": "started",
        "batch_id": batch_id,
        "total_items": len(items),
        "message": f"Analisi avviata per {len(items)} offerte. Usa batch_status() ogni 10 secondi per il progresso.",
    }


@mcp.tool()
async def batch_status() -> dict:
    """Stato del batch corrente: pending, running, done, error."""
    return await api_get("/api/v1/batch/status")


@mcp.tool()
async def batch_results() -> dict:
    """Risultati strutturati del batch: score, azienda, ruolo, gaps, strengths per ogni offerta."""
    return await api_get("/api/v1/batch/results")


# ── Analisi Singola ────────────────────────────────────────────────


@mcp.tool()
async def analyze_job(job_description: str, job_url: str = "", model: str = "haiku") -> dict:
    """Analizza una singola offerta contro il CV. Restituisce score, gaps, strengths, advice.

    Args:
        job_description: Testo completo della job description.
        job_url: URL dell'offerta (opzionale).
        model: Modello AI: "haiku" (economico) o "sonnet" (piu' preciso).
    """
    return await api_post(
        "/api/v1/analyze",
        data={"job_description": job_description, "job_url": job_url, "model": model},
    )


if __name__ == "__main__":
    mcp.run(transport=_transport)
