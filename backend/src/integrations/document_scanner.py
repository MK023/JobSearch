"""Document scanning service using Claude API.

Analyzes uploaded PDF/DOCX files to determine if they have been
properly filled/compiled by the user, or are still blank/template.
"""

import base64
import io
import logging

import anthropic
from docx import Document as DocxDocument

from ..interview.file_models import FileStatus
from .anthropic_client import MODELS, _calculate_cost, _extract_and_parse_json, get_client

logger = logging.getLogger(__name__)

SCAN_SYSTEM_PROMPT = """\
Sei un assistente che analizza documenti relativi a candidature lavorative.
Il tuo compito e' determinare se il documento e' stato compilato/riempito dall'utente
oppure se e' ancora un modello vuoto/template non compilato.

Rispondi SOLO con un JSON valido nel seguente formato:
{
    "compiled": true/false,
    "confidence": "high"/"medium"/"low",
    "summary": "breve descrizione di cosa contiene il documento (max 200 caratteri)"
}

Criteri per "compiled: true":
- Il documento contiene dati personali specifici (nome, cognome, indirizzo, ecc.)
- I campi del modulo sono stati riempiti con informazioni reali
- Il documento ha contenuto sostanziale oltre alle intestazioni/template

Criteri per "compiled: false":
- Il documento e' un template vuoto con campi placeholder (es. "___", "[Nome]", "INSERIRE QUI")
- Il documento contiene solo intestazioni senza contenuto
- Il documento e' praticamente vuoto
"""

SCAN_USER_PROMPT = """\
Analizza il seguente documento e determina se e' stato compilato o meno.

Nome file: {filename}
Tipo: {content_type}

Contenuto del documento:
{content}
"""


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text content from a DOCX file."""
    doc = DocxDocument(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    # Also extract from tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    paragraphs.append(text)
    return "\n".join(paragraphs)


def scan_document(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    model: str = "haiku",
) -> dict:
    """Scan a document with Claude API to check if it's been compiled.

    For PDFs: sends as base64 document to Claude's vision/document support.
    For DOCX: extracts text first, then sends as text.

    Args:
        file_bytes: Raw file content.
        filename: Original filename.
        content_type: MIME type.
        model: Claude model to use (default: haiku for cost savings).

    Returns:
        dict with keys:
        - status: FileStatus.COMPILED or FileStatus.NOT_COMPILED or FileStatus.SCAN_ERROR
        - scan_result: summary string from Claude
        - compiled: bool
        - confidence: str
        - cost_usd: float
        - tokens: dict
    """
    model_id = MODELS.get(model, MODELS["haiku"])
    client = get_client()

    try:
        if content_type == "application/pdf":
            return _scan_pdf(client, file_bytes, filename, content_type, model_id)
        return _scan_docx(client, file_bytes, filename, content_type, model_id)
    except Exception:
        logger.exception("Document scan failed for %s", filename)
        return {
            "status": FileStatus.SCAN_ERROR,
            "scan_result": "Errore durante la scansione del documento.",
            "compiled": False,
            "confidence": "low",
            "cost_usd": 0.0,
            "tokens": {"input": 0, "output": 0, "total": 0},
        }


def _scan_pdf(
    client: anthropic.Anthropic,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    model_id: str,
) -> dict:
    """Scan a PDF using Claude's document understanding (base64 input)."""
    b64_data = base64.b64encode(file_bytes).decode("utf-8")

    message = client.messages.create(
        model=model_id,
        max_tokens=512,
        system=SCAN_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Analizza questo documento PDF.\n"
                            f"Nome file: {filename}\n"
                            f"Determina se e' stato compilato o e' ancora un template vuoto."
                        ),
                    },
                ],
            }
        ],
    )

    return _parse_scan_response(message, model_id)


def _scan_docx(
    client: anthropic.Anthropic,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    model_id: str,
) -> dict:
    """Scan a DOCX by extracting text and sending to Claude."""
    text_content = _extract_text_from_docx(file_bytes)

    if not text_content.strip():
        return {
            "status": FileStatus.NOT_COMPILED,
            "scan_result": "Il documento e' vuoto (nessun testo trovato).",
            "compiled": False,
            "confidence": "high",
            "cost_usd": 0.0,
            "tokens": {"input": 0, "output": 0, "total": 0},
        }

    # Truncate to avoid huge API costs
    truncated = text_content[:8000]

    user_prompt = SCAN_USER_PROMPT.format(
        filename=filename,
        content_type=content_type,
        content=truncated,
    )

    message = client.messages.create(
        model=model_id,
        max_tokens=512,
        system=SCAN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    return _parse_scan_response(message, model_id)


def _parse_scan_response(message: anthropic.types.Message, model_id: str) -> dict:
    """Parse Claude's response and return structured result."""
    import json

    raw_text = message.content[0].text
    cost = _calculate_cost(message.usage, model_id)

    try:
        result = _extract_and_parse_json(raw_text)
        compiled = result.get("compiled", False)
        confidence = result.get("confidence", "low")
        summary = result.get("summary", "")

        return {
            "status": FileStatus.COMPILED if compiled else FileStatus.NOT_COMPILED,
            "scan_result": summary,
            "compiled": compiled,
            "confidence": confidence,
            "cost_usd": cost,
            "tokens": {
                "input": message.usage.input_tokens,
                "output": message.usage.output_tokens,
                "total": message.usage.input_tokens + message.usage.output_tokens,
            },
        }
    except json.JSONDecodeError:
        logger.warning("Failed to parse scan response: %s", raw_text[:200])
        return {
            "status": FileStatus.SCAN_ERROR,
            "scan_result": "Errore nel parsing della risposta AI.",
            "compiled": False,
            "confidence": "low",
            "cost_usd": cost,
            "tokens": {
                "input": message.usage.input_tokens,
                "output": message.usage.output_tokens,
                "total": message.usage.input_tokens + message.usage.output_tokens,
            },
        }
