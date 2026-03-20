"""JobSearch MCP Server — tools for querying and managing job candidature data."""

from api_client import (
    _WAKE_TIMEOUT,
    api_delete,
    api_get,
    api_post,
    api_post_json,
)
from mcp.server.fastmcp import FastMCP

from config import settings

mcp = FastMCP(
    "JobSearch",
    stateless_http=True,
    json_response=True,
    host=settings.mcp_host,
    port=settings.mcp_port,
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


@mcp.tool()
async def batch_run() -> dict:
    """Avvia l'elaborazione del batch IN LOCALE.

    Chiama Anthropic direttamente dal Mac, poi salva i risultati sul backend.
    Piu' robusto del processing server-side perche' non dipende da Fly.io.
    """
    import asyncio

    from anthropic_client import analyze_job as local_analyze

    # 1. Get pending items + CV from backend
    resp = await api_get("/api/v1/batch/pending-items")
    items = resp.get("items", [])
    cv_text = resp.get("cv_text", "")
    batch_id = resp.get("batch_id", "")

    if not items:
        return {"status": "empty", "message": "Nessun item pending nel batch"}
    if not cv_text:
        return {"status": "error", "message": "Nessun CV trovato sul backend"}

    results = []
    total_cost = 0.0
    done = 0
    skipped = 0
    errors = 0

    for i, item in enumerate(items, 1):
        item_id = item["id"]

        # Mark as running
        await api_post(f"/api/v1/batch/item/{item_id}/status", data={"status": "running"})

        try:
            # Check dedup first
            dedup = await api_get(
                "/api/v1/analysis/check-dedup",
                {
                    "content_hash": item["content_hash"],
                    "model_id": item["model_id"],
                },
            )

            if dedup.get("exists"):
                await api_post(
                    f"/api/v1/batch/item/{item_id}/status",
                    data={
                        "status": "skipped",
                        "analysis_id": dedup["analysis_id"],
                    },
                )
                skipped += 1
                results.append(
                    {
                        "item": i,
                        "status": "skipped",
                        "company": "dedup",
                        "analysis_id": dedup["analysis_id"],
                    }
                )
                continue

            # Analyze locally (synchronous call wrapped in thread)
            result = await asyncio.to_thread(
                local_analyze, cv_text, item["job_description"], item.get("model", "haiku")
            )

            # Save to backend via /analysis/import
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

            import_resp = await api_post_json("/api/v1/analysis/import", import_data)

            # Update batch item status
            await api_post(
                f"/api/v1/batch/item/{item_id}/status",
                data={
                    "status": "done",
                    "analysis_id": import_resp.get("analysis_id", ""),
                },
            )

            cost = result.get("cost_usd", 0.0)
            total_cost += cost
            done += 1
            results.append(
                {
                    "item": i,
                    "status": "done",
                    "company": result.get("company", "?"),
                    "role": result.get("role", "?"),
                    "score": result.get("score", 0),
                    "cost_usd": cost,
                    "analysis_id": import_resp.get("analysis_id", ""),
                }
            )

        except Exception as exc:
            # Try to update backend status (ignore if backend is down)
            try:  # noqa: SIM105
                await api_post(
                    f"/api/v1/batch/item/{item_id}/status",
                    data={"status": "error", "error_message": str(exc)},
                )
            except Exception:  # noqa: S110
                pass

            errors += 1
            results.append({"item": i, "status": "error", "error": str(exc)})

    return {
        "status": "done",
        "batch_id": batch_id,
        "total": len(items),
        "done": done,
        "skipped": skipped,
        "errors": errors,
        "total_cost_usd": round(total_cost, 6),
        "results": results,
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
    mcp.run(transport="streamable-http")
