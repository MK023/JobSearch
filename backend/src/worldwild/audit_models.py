"""Mirror of the primary AuditLog on the secondary DB.

Same column shape as ``..audit.models.AuditLog`` but anchored to
``WorldwildBase`` and *without* the ``users`` foreign key — Postgres can't
enforce FK across databases. The user_id is stored as a bare UUID; resolution
to a user row happens at read time (and only when needed) via the primary DB.

Purpose: defense-in-depth on auditability. If Neon hits its monthly compute
quota and starts rejecting writes mid-month, the secondary copy on Supabase
preserves the audit trail. The two writes are independent — neither blocks
the user-facing action on failure.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from ..database.worldwild_db import WorldwildBase


class WorldwildAuditLog(WorldwildBase):
    """Mirror audit log stored on the secondary DB (Supabase)."""

    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No FK on user_id — primary DB owns the users table.
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)
    detail = Column(Text, default="")
    ip_address = Column(String(45), default="")
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
