"""Extract plain text from CV files (PDF, DOCX, DOC, TXT)."""

import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".doc", ".docx"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from an uploaded file. Raises ValueError on failure."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Formato non supportato: {ext}. Usa PDF, DOCX, DOC o TXT.")
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError("File troppo grande (max 10 MB).")
    if len(file_bytes) == 0:
        raise ValueError("File vuoto.")

    extractors = {
        ".pdf": _extract_pdf,
        ".docx": _extract_docx,
        ".doc": _extract_doc,
        ".txt": _extract_txt,
    }
    text = extractors[ext](file_bytes)
    text = text.strip()
    if len(text) < 20:
        raise ValueError("Impossibile estrarre testo sufficiente dal file.")
    return text


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    doc = Document(BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_doc(data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        result = subprocess.run(
            ["antiword", tmp.name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise ValueError("Impossibile leggere il file DOC. Prova a convertirlo in DOCX.")
        return result.stdout


def _extract_txt(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError("Encoding del file non riconosciuto. Salva il file come UTF-8.")
