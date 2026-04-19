"""Add inbox_items table for Chrome extension raw paste ingestion.

Revision ID: 020
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
            server_default=sa.func.now(),
        ),
        sa.Column("source_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default="", index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending", index=True),
        sa.Column(
            "analysis_id",
            UUID(as_uuid=True),
            sa.ForeignKey("job_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_inbox_user_status", "inbox_items", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_inbox_user_status", table_name="inbox_items")
    op.drop_table("inbox_items")
