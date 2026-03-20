"""Add batch_items table for persistent batch queue.

Revision ID: 007
Revises: 006
Create Date: 2026-03-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batch_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column(
            "cv_id",
            sa.UUID(),
            sa.ForeignKey("cv_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("job_url", sa.String(500), server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(20), server_default="haiku"),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "skipped", "error", name="batchitemstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "analysis_id",
            sa.UUID(),
            sa.ForeignKey("job_analyses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0"),
        sa.Column("preview", sa.String(100), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_batch_items_batch_id", "batch_items", ["batch_id"])
    op.create_index("ix_batch_items_content_hash", "batch_items", ["content_hash"])
    op.create_index("idx_batch_items_batch_status", "batch_items", ["batch_id", "status"])
    op.create_index("idx_batch_items_content_hash_model", "batch_items", ["content_hash", "model"])


def downgrade() -> None:
    op.drop_index("idx_batch_items_content_hash_model", table_name="batch_items")
    op.drop_index("idx_batch_items_batch_status", table_name="batch_items")
    op.drop_index("ix_batch_items_content_hash", table_name="batch_items")
    op.drop_index("ix_batch_items_batch_id", table_name="batch_items")
    op.drop_table("batch_items")
    op.execute("DROP TYPE IF EXISTS batchitemstatus")
