"""Add interviews table for scheduling.

Revision ID: 004
Revises: 003
Create Date: 2026-02-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_analyses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interview_type", sa.String(20), nullable=True),
        sa.Column("recruiter_name", sa.String(255), nullable=True),
        sa.Column("recruiter_email", sa.String(255), nullable=True),
        sa.Column("meeting_link", sa.String(500), nullable=True),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("phone_pin", sa.String(20), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_interviews_scheduled", "interviews", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("idx_interviews_scheduled", table_name="interviews")
    op.drop_table("interviews")
