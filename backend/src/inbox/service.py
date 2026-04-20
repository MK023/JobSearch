"""Inbox service: sanitization, deduplication, async analysis trigger.

Security-critical: every byte coming from the extension is treated as
untrusted user input. The checks here are the only barrier between a
malicious page paste and the DB/LLM.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID

import bleach  # type: ignore[import-untyped]
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.models import AnalysisSource, JobAnalysis
from ..analysis.service import find_existing_analysis, run_analysis
from ..cv.service import get_latest_cv
from ..integrations.anthropic_client import MODELS
from ..integrations.cache import CacheService
from .models import InboxItem, InboxStatus

# Whitelist of allowed host suffixes for source_url. Entries match the
# rightmost dot-segments so subdomains resolve cleanly (e.g., it.indeed.com
# matches "indeed.com").
ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (
    "linkedin.com",
    "indeed.com",
    "indeed.it",
    "infojobs.it",
    "welcometothejungle.com",
    "remoteok.com",
    "remoteok.io",
    "wellfound.com",
    "ycombinator.com",
    "weworkremotely.com",
    "lever.co",
    "greenhouse.io",
    "workable.com",
    "stackoverflow.com",
    "glassdoor.com",
    "glassdoor.it",
)


class InboxValidationError(ValueError):
    """Raised when input fails a validation gate."""


def _strip_html(text: str) -> str:
    """Remove every HTML tag/attribute; keep visible text only."""
    return cast(str, bleach.clean(text, tags=[], attributes={}, strip=True))


def _normalize_text(text: str) -> str:
    """NFKC-normalize, strip control/invisible chars, collapse whitespace."""
    normalized = unicodedata.normalize("NFKC", text)
    # Strip category Cc (control), Cf (format/invisible), Cs (surrogate)
    cleaned = "".join(ch for ch in normalized if unicodedata.category(ch)[0] != "C" or ch in "\n\t ")
    # Collapse 3+ consecutive newlines into 2 (preserve paragraph breaks)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def sanitize_raw(text: str) -> str:
    """Full sanitization pipeline applied before persistence."""
    return _normalize_text(_strip_html(text))


def content_hash(text: str) -> str:
    """Hash the sanitized text for dedup (sha256 hex)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_allowed_host(url: str) -> bool:
    """Check if the source_url's host matches a whitelisted suffix."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def count_pending_for_user(db: Session, user_id: UUID) -> int:
    """How many inbox_items are currently not-yet-resolved for this user."""
    return (
        db.query(InboxItem)
        .filter(
            InboxItem.user_id == user_id,
            InboxItem.status.in_([InboxStatus.PENDING.value, InboxStatus.PROCESSING.value]),
        )
        .count()
    )


def get_inbox_stats(db: Session, user_id: UUID) -> dict[str, Any]:
    """Aggregate KPIs for the dashboard widget.

    - ``today_total``: inbox_items received since local midnight (auto-resets)
    - ``pending_active``: pending + processing, not-yet-resolved
    - ``done_total``: done (linked to an analysis) in the last 30 days
    - ``error_total``: error (failed analysis) in the last 30 days
    - ``last_received_at``: ISO-formatted timestamp of the most recent item
                              (any status, any age), or None if empty
    """
    cutoff_30d = datetime.now(UTC) - timedelta(days=30)

    today_total = (
        db.query(func.count(InboxItem.id))
        .filter(
            InboxItem.user_id == user_id,
            func.date(InboxItem.created_at) == func.current_date(),
        )
        .scalar()
        or 0
    )

    pending_active = count_pending_for_user(db, user_id)

    done_total = (
        db.query(func.count(InboxItem.id))
        .filter(
            InboxItem.user_id == user_id,
            InboxItem.status == InboxStatus.DONE.value,
            InboxItem.created_at >= cutoff_30d,
        )
        .scalar()
        or 0
    )

    error_total = (
        db.query(func.count(InboxItem.id))
        .filter(
            InboxItem.user_id == user_id,
            InboxItem.status == InboxStatus.ERROR.value,
            InboxItem.created_at >= cutoff_30d,
        )
        .scalar()
        or 0
    )

    last_row = (
        db.query(InboxItem.created_at)
        .filter(InboxItem.user_id == user_id)
        .order_by(InboxItem.created_at.desc())
        .first()
    )
    last_received_at = last_row[0].isoformat() if last_row and last_row[0] else None

    return {
        "today_total": int(today_total),
        "pending_active": int(pending_active),
        "done_total": int(done_total),
        "error_total": int(error_total),
        "last_received_at": last_received_at,
    }


def ingest(
    db: Session,
    user_id: UUID,
    raw_text: str,
    source_url: str,
    source: str,
    *,
    max_pending: int = 50,
) -> tuple[InboxItem, bool]:
    """Persist a new inbox item after validation.

    Returns (item, is_dedup). ``is_dedup=True`` when the content_hash already
    has an existing analysis — the item is marked SKIPPED and linked to it.
    """
    if not is_allowed_host(source_url):
        raise InboxValidationError("source_url host not in allowlist")

    sanitized = sanitize_raw(raw_text)
    if len(sanitized) < 50:
        raise InboxValidationError("sanitized text too short (<50 chars)")

    if count_pending_for_user(db, user_id) >= max_pending:
        raise InboxValidationError(f"pending inbox quota exhausted (max {max_pending})")

    hash_value = content_hash(sanitized)

    # Dedup: if we already analyzed this exact content with Haiku, reuse it
    existing = find_existing_analysis(db, hash_value, MODELS["haiku"])
    if existing:
        item = InboxItem(
            user_id=user_id,
            source_url=source_url[:500],
            source=source,
            raw_text=sanitized,
            content_hash=hash_value,
            status=InboxStatus.SKIPPED.value,
            analysis_id=cast(UUID, existing.id),
            processed_at=datetime.now(UTC),
        )
        db.add(item)
        db.flush()
        return item, True

    item = InboxItem(
        user_id=user_id,
        source_url=source_url[:500],
        source=source,
        raw_text=sanitized,
        content_hash=hash_value,
        status=InboxStatus.PENDING.value,
    )
    db.add(item)
    db.flush()
    return item, False


def process_pending(
    db: Session,
    inbox_id: UUID,
    user_id: UUID,
    cache: CacheService | None = None,
    model: str = "haiku",
) -> None:
    """Background worker: analyze one pending inbox_item.

    Called by FastAPI BackgroundTasks after ingest() persists the item. Raw
    text flows directly into analyze_job — no wrapper, no prompt injection
    defense at the LLM layer (we trust the output schema Pydantic validation
    in anthropic_client to catch malformed replies).
    """
    item = db.query(InboxItem).filter(InboxItem.id == inbox_id).first()
    if not item or item.status != InboxStatus.PENDING.value:
        return

    cv = get_latest_cv(db, user_id)
    if not cv:
        item.status = InboxStatus.ERROR.value  # type: ignore[assignment]
        item.error_message = "No CV on file"  # type: ignore[assignment]
        item.processed_at = datetime.now(UTC)  # type: ignore[assignment]
        db.commit()
        return

    item.status = InboxStatus.PROCESSING.value  # type: ignore[assignment]
    db.commit()

    try:
        analysis, _result = run_analysis(
            db=db,
            cv_text=cast(str, cv.raw_text),
            cv_id=cast(UUID, cv.id),
            job_description=cast(str, item.raw_text),
            job_url=cast(str, item.source_url),
            model=model,
            cache=cache,
            user_id=user_id,
            source=AnalysisSource.EXTENSION.value,  # inbox ingestion = Chrome extension flow
        )
        item.analysis_id = cast(UUID, analysis.id)  # type: ignore[assignment]
        item.status = InboxStatus.DONE.value  # type: ignore[assignment]
        item.processed_at = datetime.now(UTC)  # type: ignore[assignment]
        db.commit()
    except Exception as exc:  # noqa: BLE001 — log the error into the item itself
        db.rollback()
        item = db.query(InboxItem).filter(InboxItem.id == inbox_id).first()
        if item:
            item.status = InboxStatus.ERROR.value  # type: ignore[assignment]
            item.error_message = str(exc)[:2000]  # type: ignore[assignment]
            item.processed_at = datetime.now(UTC)  # type: ignore[assignment]
            db.commit()


def serialize(item: InboxItem, analysis: JobAnalysis | None = None) -> dict[str, Any]:
    """JSON-friendly shape for API responses."""
    return {
        "inbox_id": str(item.id),
        "status": str(item.status),
        "analysis_id": str(item.analysis_id) if item.analysis_id else None,
        "source": str(item.source),
        "source_url": item.source_url,
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "error_message": item.error_message or "",
        "analysis_score": int(analysis.score or 0) if analysis else None,
    }
