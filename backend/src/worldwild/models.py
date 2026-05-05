"""SQLAlchemy models for the WorldWild ingest layer (stored in Supabase).

Three tables:

- ``job_offers``     — raw layer; one row per ingested offer per source.
- ``decisions``      — Marco's skip/promote actions on offers; feedback loop.
- ``adapter_runs``   — cron / manual ingest run history; per-source observability.

Design notes:

- All inherit from ``WorldwildBase`` (separate metadata from primary ``Base``).
- Status / source / decision columns are ``String`` not SQLEnum — see
  ``feedback_status_column.md``: SQLEnum migrations are brittle, plain strings
  validated at app boundary are the established convention.
- Cross-DB references (e.g. ``promoted_to_neon_id``) are stored as bare UUIDs,
  no foreign-key constraint — Postgres can't enforce FKs across databases.
- ``content_hash`` is the dedup key across sources (same job posted on Adzuna +
  Remotive must collapse to one ``JobOffer`` row).
- ``raw_payload`` keeps the original API response as JSONB so re-parsing or new
  field extraction never requires re-fetching from the source.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..database.worldwild_db import WorldwildBase

# -- enum-like string constants --------------------------------------------------------
# Validated at application boundary, not by SQLEnum. Keeps migrations simple.

SOURCE_ADZUNA = "adzuna"
SOURCE_REMOTIVE = "remotive"
SOURCE_ARBEITNOW = "arbeitnow"
SOURCE_JOBICY = "jobicy"
SOURCE_REMOTEOK = "remoteok"
SOURCE_THEMUSE = "themuse"
SOURCE_FINDWORK = "findwork"
SOURCE_WORKINGNOMADS = "workingnomads"
SOURCE_WEWORKREMOTELY = "weworkremotely"
ALL_SOURCES = (
    SOURCE_ADZUNA,
    SOURCE_REMOTIVE,
    SOURCE_ARBEITNOW,
    SOURCE_JOBICY,
    SOURCE_REMOTEOK,
    SOURCE_THEMUSE,
    SOURCE_FINDWORK,
    SOURCE_WORKINGNOMADS,
    SOURCE_WEWORKREMOTELY,
)

DECISION_PENDING = "pending"
DECISION_SKIP = "skip"
DECISION_PROMOTE = "promote"
ALL_DECISIONS = (DECISION_PENDING, DECISION_SKIP, DECISION_PROMOTE)

# State machine for the promotion background task that runs after Marco hits
# "Promote". ``idle`` is the schema default and means "nothing started";
# ``pending`` is the in-flight window between gate-pass and AI completion;
# ``skipped_low_match`` is the cheap exit when stack-match score is below
# the configurable threshold (no AI call, no Neon write); ``done`` and
# ``failed`` are terminal.
PROMOTION_STATE_IDLE = "idle"
PROMOTION_STATE_PENDING = "pending"
PROMOTION_STATE_SKIPPED_LOW_MATCH = "skipped_low_match"
PROMOTION_STATE_DONE = "done"
PROMOTION_STATE_FAILED = "failed"
ALL_PROMOTION_STATES = (
    PROMOTION_STATE_IDLE,
    PROMOTION_STATE_PENDING,
    PROMOTION_STATE_SKIPPED_LOW_MATCH,
    PROMOTION_STATE_DONE,
    PROMOTION_STATE_FAILED,
)

RUN_TYPE_CRON = "cron"
RUN_TYPE_MANUAL = "manual"
ALL_RUN_TYPES = (RUN_TYPE_CRON, RUN_TYPE_MANUAL)

RUN_STATUS_RUNNING = "running"
RUN_STATUS_SUCCESS = "success"
RUN_STATUS_FAILED = "failed"


class JobOffer(WorldwildBase):
    """Raw external job posting fetched from a public API."""

    __tablename__ = "job_offers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Source identity
    source = Column(String(32), nullable=False, index=True)
    external_id = Column(String(128), nullable=False)
    # sha256 of normalized (company + title + location + posted_date_week);
    # stable across sources for the same posting → enables cross-source dedup.
    content_hash = Column(String(64), nullable=False, index=True)

    # Core fields (all sources expose these in some shape)
    title = Column(String(500), nullable=False)
    company = Column(String(255), nullable=False, index=True)
    location = Column(String(255), default="")
    url = Column(String(1000), default="")
    description = Column(Text, default="")

    # Optional / source-dependent
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    salary_currency = Column(String(8), default="")
    contract_type = Column(String(32), default="")  # permanent | contract | …
    contract_time = Column(String(32), default="")  # full_time | part_time | …
    category = Column(String(128), default="")

    # Timestamps
    posted_at = Column(DateTime(timezone=True), nullable=True)
    ingested_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    # Pre-filter outcome (rule-based, before AI)
    pre_filter_passed = Column(Boolean, default=False, nullable=False, index=True)
    pre_filter_reason = Column(String(255), default="")

    # Stack-match score (0-100) calcolato at-ingest contro Marco's CV skills.
    # ``None`` = score non calcolabile (offer privo di tech tokens estraibili,
    # oppure CV non disponibile al momento dell'ingest → safety fallback).
    # Un valore basso non droppa di per sé l'insert: è il filtro at-ingest
    # in ``services/ingest._execute_ingest`` che applica la threshold prima
    # di persistere. Indicizzato per future query "show offers with high match".
    cv_match_score = Column(Integer, nullable=True, index=True)

    # Full original payload for reparsing / new field extraction.
    # Postgres prod uses JSONB; SQLite test fixtures fall back to plain JSON
    # (text-based) — the with_variant keeps both dialects portable so we don't
    # need a separate test-only schema.
    raw_payload = Column(JSONB().with_variant(JSON, "sqlite"), nullable=True)

    __table_args__ = (
        # Dedup intra-source: same (source, external_id) pair must be unique.
        Index("ix_job_offers_source_external_id", "source", "external_id", unique=True),
        # Common query: "what came in today, ranked"
        Index("ix_job_offers_source_ingested_at", "source", "ingested_at"),
    )


class Decision(WorldwildBase):
    """Marco's skip / promote action on a JobOffer.

    One row per (job_offer_id) — kept as a separate table rather than a column on
    ``JobOffer`` so the decision audit (timestamp, optional reason, promoted-to
    pointer) survives even if the offer row is later pruned by TTL.
    """

    __tablename__ = "decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # UNIQUE: one decision per offer, enforced at the schema level (migration 002).
    job_offer_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)

    decision = Column(String(16), nullable=False, default=DECISION_PENDING, index=True)
    reason = Column(String(500), default="")
    decided_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)

    # When ``decision == 'promote'``, this points to the ``job_analyses.id`` row
    # created on the PRIMARY DB (Neon). No FK constraint — cross-DB pointer.
    promoted_to_neon_id = Column(UUID(as_uuid=True), nullable=True)

    # Promotion state machine (added in migration 003).
    # ``promotion_state``: idle / pending / skipped_low_match / done / failed.
    # ``promotion_score``: stack-match score 0-100 from the pre-AI gate.
    # ``promotion_started_at``: when the background task picked it up.
    # ``promotion_error``: short string with last failure reason for retries.
    promotion_state = Column(
        String(32),
        nullable=False,
        default=PROMOTION_STATE_IDLE,
        server_default=PROMOTION_STATE_IDLE,
        index=True,
    )
    promotion_score = Column(Integer, nullable=True)
    promotion_started_at = Column(DateTime(timezone=True), nullable=True)
    promotion_error = Column(String(500), nullable=False, default="", server_default="")


class AdapterRun(WorldwildBase):
    """Observability log for one ingest run (per source, per trigger)."""

    __tablename__ = "adapter_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source = Column(String(32), nullable=False, index=True)
    run_type = Column(String(16), nullable=False, default=RUN_TYPE_MANUAL)
    status = Column(String(16), nullable=False, default=RUN_STATUS_RUNNING)

    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    offers_fetched = Column(Integer, default=0, nullable=False)
    offers_new = Column(Integer, default=0, nullable=False)
    offers_pre_filtered_out = Column(Integer, default=0, nullable=False)

    error_message = Column(Text, default="")
