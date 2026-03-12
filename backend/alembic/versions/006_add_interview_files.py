"""Add interview_files table for R2 file attachments.

Revision ID: 006
Revises: 005
Create Date: 2026-03-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_files",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "interview_id",
            sa.UUID(),
            sa.ForeignKey("interviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("r2_key", sa.String(500), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("scan_result", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_interview_files_interview_id", "interview_files", ["interview_id"])
    op.create_index("idx_interview_files_status", "interview_files", ["status"])


def downgrade() -> None:
    op.drop_index("idx_interview_files_status", table_name="interview_files")
    op.drop_index("idx_interview_files_interview_id", table_name="interview_files")
    op.drop_table("interview_files")
