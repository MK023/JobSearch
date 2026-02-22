"""Add notification_logs table for email tracking.

Revision ID: 003
Revises: 002
Create Date: 2026-02-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id", UUID(as_uuid=True), sa.ForeignKey("job_analyses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), server_default=""),
        sa.Column("detail", sa.Text, server_default=""),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_notif_analysis_type", "notification_logs", ["analysis_id", "notification_type"])


def downgrade() -> None:
    op.drop_index("idx_notif_analysis_type", table_name="notification_logs")
    op.drop_table("notification_logs")
